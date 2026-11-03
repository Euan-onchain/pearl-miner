#!/usr/bin/env python3
"""Read-only: resolve handle -> id, read challenge(wallet,id) and write the miner params.
Usage: python3 fetch_challenge.py [--config config.yaml] [--wallet 0x..] [--out out/params.json]"""
import argparse, json, os, sys, time
from pearl_common import load_config, contracts, wallet_of, resolve_id, digest
from web3 import Web3

ap = argparse.ArgumentParser()
ap.add_argument("--config"); ap.add_argument("--wallet", help="override config wallet")
ap.add_argument("--out", help="override paths.params")
a = ap.parse_args()
cfg = load_config(a.config)
if a.wallet: cfg["wallet"] = a.wallet
w, m, reg = contracts(cfg)
wallet = wallet_of(cfg)

cid = w.eth.chain_id
if cfg.get("chain_id") and int(cfg["chain_id"]) != cid:
    sys.exit(f"chain id mismatch: rpc={cid} config={cfg['chain_id']}")
for addr, key in ((m.address, "mining_code_hash"), (reg.address, "registry_code_hash")):
    exp = (cfg.get(key) or "").lower()
    if exp:
        got = Web3.keccak(w.eth.get_code(addr)).hex().lower()
        got = got if got.startswith("0x") else "0x" + got
        print(f"{key}: {'OK' if got == exp else 'MISMATCH ' + got}")
        if got != exp: sys.exit("code hash mismatch - refusing (wrong address or contract changed)")

handle, aid = resolve_id(cfg, reg, wallet)
if aid is None:
    sys.exit(f"wallet {wallet} has no handle in registry {reg.address}; register one first")
seed, target, reward, eligible, live, claims = m.functions.challenge(wallet, aid).call()
rem = m.functions.dailyRemaining().call(); starts = m.functions.startsAt().call()
try: dec = m.functions.decimals().call()
except Exception: dec = 18
bits = 256 - target.bit_length()
# sanity: our local keccak must match the contract's proofDigest
assert m.functions.proofDigest(wallet, 1).call() == digest(seed, 1), "local keccak != on-chain proofDigest"

params = dict(chain_id=cid, mining_contract=m.address, registry=reg.address, wallet=wallet,
              handle=handle, agent_id=str(aid), seed="0x" + seed.hex(), target=hex(target),
              target_zero_bits=bits, reward=str(reward), decimals=dec, eligible=eligible, live=live,
              claims=claims, daily_remaining=str(rem), starts_at=starts, fetched_at=int(time.time()))
out = a.out or cfg["paths"].get("params", "out/params.json")
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
json.dump(params, open(out, "w"), indent=2)
with open(os.path.splitext(out)[0] + ".env", "w") as f:
    f.write(f"SEED={params['seed']}\nTARGET={params['target']}\nWALLET={wallet}\nAGENT_ID={aid}\n")
print(json.dumps(params, indent=2))
print(f"expected hashes per proof ~ {2**256/(target+1):.3e}")
if not eligible: print("WARNING: eligible=false (wallet does not own this id / no handle)")
if not live: print("WARNING: live=false (mining not started, paused, or daily cap reached)")
print(f"-> {out}")
