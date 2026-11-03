#!/usr/bin/env python3
"""Generic PEARL mineBatch submitter (local key, Mode A).

The private key is read ONLY from the PRIVATE_KEY environment variable. Never put it in config.

  python3 submit.py --dry-run --max-groups 3            # eth_call simulation only, nothing sent
  PRIVATE_KEY=0x... python3 submit.py                   # sign & send
  PRIVATE_KEY=0x... python3 submit.py --wait-until 1767225600 --gas-limit 700000
      # pre-sign the first wave, then broadcast exactly at that unix time (e.g. the daily open)

Features: nonce management, broadcast of each raw tx to every RPC in rpc_urls, usedProofs dedupe,
append-only resume log (nonces already submitted/confirmed are skipped), stop conditions.
"""
import argparse, csv, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pearl_common import load_config, contracts, wallet_of, resolve_id, digest, read_nonce_file, web3_for, decode_error
from web3 import Web3

ap = argparse.ArgumentParser()
ap.add_argument("--config"); ap.add_argument("--nonces", help="override paths.valid_nonces")
ap.add_argument("--dry-run", action="store_true", help="simulate with eth_call; never sign or send")
ap.add_argument("--wait-until", type=float, default=0, help="unix timestamp to start broadcasting")
ap.add_argument("--max-groups", type=int, default=10**9)
ap.add_argument("--batch-size", type=int); ap.add_argument("--concurrency", type=int)
ap.add_argument("--gas-limit", type=int); ap.add_argument("--gas-price-gwei", type=float)
ap.add_argument("--no-used-check", action="store_true")
ap.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
a = ap.parse_args()

cfg = load_config(a.config); S = cfg["submit"]
BATCH = min(16, a.batch_size or int(S.get("batch_size", 16)))
CONC = max(1, a.concurrency or int(S.get("concurrency", 4)))
GAS_LIMIT = a.gas_limit if a.gas_limit is not None else int(S.get("gas_limit", 0))
GP_GWEI = a.gas_price_gwei if a.gas_price_gwei is not None else float(S.get("gas_price_gwei", 0))
SLIP = int(S.get("min_reward_slippage_bps", 100))
MIN_NATIVE = float(S.get("min_native_balance", 0.005))
MAX_FAIL = int(S.get("max_consecutive_failures", 5))
RCPT_TIMEOUT = int(S.get("receipt_timeout", 120))
NONCES = a.nonces or cfg["paths"].get("valid_nonces", "out/valid_nonces.txt")
LOG = cfg["paths"].get("submit_log", "out/submit_log.csv")
FIELDS = ["time", "tx_nonce", "nonces", "min_reward", "tx_hash", "status", "note"]

w, M, REG = contracts(cfg)
writers = [web3_for(u) for u in cfg["rpc_urls"]]
wallet = wallet_of(cfg)
cid = w.eth.chain_id
if cfg.get("chain_id") and int(cfg["chain_id"]) != cid: sys.exit("chain id mismatch")
handle, AID = resolve_id(cfg, REG, wallet)
if AID is None: sys.exit("wallet has no registry handle")

acct = None
if not a.dry_run:
    pk = os.environ.get("PRIVATE_KEY", "").strip()
    if not pk: sys.exit("set PRIVATE_KEY env var (or use --dry-run)")
    from eth_account import Account
    acct = Account.from_key(pk); del pk
    if acct.address != wallet: sys.exit(f"PRIVATE_KEY address {acct.address} != config wallet {wallet}")

def ts(): return time.strftime("%Y-%m-%d %H:%M:%S")
lock = threading.Lock()
def log_row(**r):
    with lock:
        os.makedirs(os.path.dirname(os.path.abspath(LOG)), exist_ok=True)
        new = not os.path.exists(LOG)
        with open(LOG, "a", newline="") as f:
            wr = csv.DictWriter(f, FIELDS)
            if new: wr.writeheader()
            wr.writerow({k: r.get(k, "") for k in FIELDS} | {"time": ts()})

# ---- resume: nonces in a submitted/confirmed row are not resent ----
done = set()
if os.path.exists(LOG):
    last = {}
    for r in csv.DictReader(open(LOG)): last[r["nonces"]] = r["status"]
    for ns, st in last.items():
        if st in ("submitted", "confirmed"): done.update(ns.split(";"))

seed, target, reward, eligible, live, claims = M.functions.challenge(wallet, AID).call()
rows = [(n, d) for n, d in read_nonce_file(NONCES) if str(n) not in done]
good = []
for n, _ in rows:
    d = digest(seed, n)
    if int.from_bytes(d, "big") <= target: good.append((n, d))
print(f"wallet={wallet} handle={handle!r} live={live} eligible={eligible} reward={reward} "
      f"nonces: file={len(rows)+len(done)} resumed-skip={len(done)} valid-now={len(good)}")
if not eligible: sys.exit("eligible=false: wallet does not own this agent id")
if not a.no_used_check and good and (live or a.dry_run):
    with ThreadPoolExecutor(16) as ex:
        used = list(ex.map(lambda x: M.functions.usedProofs(x[1]).call(), good))
    good = [g for g, u in zip(good, used) if not u]
    print(f"after usedProofs dedupe: {len(good)}")
groups = [[n for n, _ in good[i:i + BATCH]] for i in range(0, len(good), BATCH)][:a.max_groups]
if not groups: sys.exit("nothing to submit")

def min_reward(n, rew): return rew * n * (10000 - SLIP) // 10000

if a.dry_run:
    for gi, g in enumerate(groups):
        mr = min_reward(len(g), reward)
        try:
            M.functions.mineBatch(AID, g, mr).call({"from": wallet})
            gas = M.functions.mineBatch(AID, g, mr).estimate_gas({"from": wallet})
            print(f"g{gi} n={len(g)} minReward={mr} eth_call OK gas~{gas}")
        except Exception as e:
            print(f"g{gi} n={len(g)} eth_call REVERT: {decode_error(e)}")
    sys.exit(0)

gas_price = int(GP_GWEI * 1e9) if GP_GWEI else w.eth.gas_price
bal = w.eth.get_balance(wallet)
est = (GAS_LIMIT or 700000) * gas_price * len(groups)
print(f"groups={len(groups)} batch={BATCH} conc={CONC} gasPrice={gas_price/1e9:.3f} gwei "
      f"balance={bal/1e18:.5f} worst-case fee~{est/1e18:.5f}")
if not a.yes and input("type YES to sign and broadcast: ").strip() != "YES": sys.exit("aborted")

state = dict(nonce=w.eth.get_transaction_count(wallet, "pending"), fails=0, stop=None, reward=reward)

def sign(g, txn):
    mr = min_reward(len(g), state["reward"])
    gl = GAS_LIMIT
    if not gl:
        try: gl = int(M.functions.mineBatch(AID, g, mr).estimate_gas({"from": wallet}) * 1.2)
        except Exception as e:
            if a.wait_until and time.time() < a.wait_until: gl = 700000
            else: raise
    tx = M.functions.mineBatch(AID, g, mr).build_transaction(
        {"from": wallet, "nonce": txn, "gas": gl, "gasPrice": gas_price, "chainId": cid, "value": 0})
    return acct.sign_transaction(tx), mr

def broadcast(raw):
    errs = []
    def one(wr):
        try: return wr.eth.send_raw_transaction(raw).hex()
        except Exception as e: errs.append(str(e)); return None
    with ThreadPoolExecutor(len(writers)) as ex: hs = [h for h in ex.map(one, writers) if h]
    if hs: return hs[0], None
    if any("already known" in e.lower() or "known transaction" in e.lower() for e in errs): return "known", None
    return None, "; ".join(errs)[:300]

def run_wave(wave):
    signed = []
    for g in wave:
        try: st, mr = sign(g, state["nonce"])
        except Exception as e:
            print("presign/estimate failed:", decode_error(e)); log_row(nonces=";".join(map(str, g)), status="sim_failed", note=str(e)[:200])
            state["fails"] += 1; continue
        signed.append((g, st, mr, state["nonce"])); state["nonce"] += 1
    if a.wait_until and time.time() < a.wait_until:
        print(f"pre-signed {len(signed)} txs; waiting until {a.wait_until} ({a.wait_until-time.time():.1f}s)", flush=True)
        while time.time() < a.wait_until - 0.5: time.sleep(0.2)
        while time.time() < a.wait_until: pass
    sent = []
    def go(item):
        g, st, mr, txn = item
        h, err = broadcast(st.raw_transaction)
        if h == "known": h = st.hash.hex()
        ns = ";".join(map(str, g))
        if h:
            log_row(tx_nonce=txn, nonces=ns, min_reward=mr, tx_hash=h, status="submitted"); print(f"[{ts()}] sent nonce={txn} {h}", flush=True)
            return (g, st.hash, txn, mr)
        log_row(tx_nonce=txn, nonces=ns, min_reward=mr, status="send_failed", note=err); print("send failed:", err)
        return None
    with ThreadPoolExecutor(len(signed) or 1) as ex: sent = [x for x in ex.map(go, signed) if x]
    if len(sent) < len(signed):  # a gap in nonces would block later txs: resync
        state["nonce"] = w.eth.get_transaction_count(wallet, "pending")
    for g, h, txn, mr in sent:
        try:
            rc = w.eth.wait_for_transaction_receipt(h, timeout=RCPT_TIMEOUT)
            st = "confirmed" if rc.status == 1 else "reverted"
            note = f"gasUsed={rc.gasUsed}"
        except Exception as e:
            st, note = "timeout", str(e)[:120]
        log_row(tx_nonce=txn, nonces=";".join(map(str, g)), min_reward=mr, tx_hash=h.hex(), status=st, note=note)
        print(f"  tx nonce={txn} {st} {note}", flush=True)
        state["fails"] = 0 if st == "confirmed" else state["fails"] + 1

p0 = M.functions.balanceOf(wallet).call(); b0 = w.eth.get_balance(wallet)
q = list(groups)
try:
    while q and not state["stop"]:
        wave, q = q[:CONC], q[CONC:]
        run_wave(wave)
        if state["fails"] >= MAX_FAIL: state["stop"] = f"{MAX_FAIL} consecutive failures"; break
        live = M.functions.isLive().call(); rew = M.functions.currentReward().call(); state["reward"] = rew
        rem = M.functions.dailyRemaining().call(); tgt = M.functions.currentTarget().call()
        if not live: state["stop"] = "not live (paused / daily cap)"
        elif rem < rew * BATCH: state["stop"] = "dailyRemaining < batch reward"
        elif w.eth.get_balance(wallet) < MIN_NATIVE * 1e18: state["stop"] = "native balance low"
        if tgt != target:  # difficulty stage changed: drop nonces that no longer qualify
            q = [[n for n in g if int.from_bytes(digest(seed, n), "big") <= tgt] for g in q]; q = [g for g in q if g]
            target = tgt; print("target changed; remaining groups re-filtered")
except KeyboardInterrupt:
    state["stop"] = "interrupted"
p1 = M.functions.balanceOf(wallet).call(); b1 = w.eth.get_balance(wallet)
print(f"stop={state['stop']} token gained={p1-p0} (raw units) native spent={(b0-b1)/1e18:.6f}")
