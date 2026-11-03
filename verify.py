#!/usr/bin/env python3
"""Verify / dedupe nonce files: keccak256(abi.encode(seed,nonce)) <= target.
Offline:  python3 verify.py --seed 0x.. --target 0x.. out/nonces_*.txt
From params + chain spot-check: python3 verify.py --params out/params.json --onchain 5 out/nonces_*.txt
--onchain N cross-checks N nonces with the contract's proofDigest and usedProofs (read-only)."""
import argparse, glob, json, sys
from pearl_common import digest, read_nonce_file

ap = argparse.ArgumentParser()
ap.add_argument("files", nargs="*")
ap.add_argument("--params"); ap.add_argument("--seed"); ap.add_argument("--target")
ap.add_argument("--out", help="write valid unique nonces here")
ap.add_argument("--onchain", type=int, default=0, help="spot-check N nonces via RPC")
ap.add_argument("--config")
a = ap.parse_args()
P = json.load(open(a.params)) if a.params else {}
seed_h = a.seed or P.get("seed"); tgt_h = a.target or P.get("target")
if not seed_h or not tgt_h: sys.exit("need --seed and --target (or --params)")
seed = bytes.fromhex(seed_h[2:] if seed_h.startswith("0x") else seed_h); assert len(seed) == 32
T = int(tgt_h, 16)
files = [f for p in a.files for f in sorted(glob.glob(p))]
if not files: sys.exit("no nonce files given")
seen = {}; bad = dup = total = 0
for fn in files:
    for n, dh in read_nonce_file(fn):
        total += 1; d = digest(seed, n)
        if int.from_bytes(d, "big") > T: bad += 1; print("INVALID", fn, n); continue
        if dh and dh.lower().replace("0x", "", 1) != d.hex(): print("WARN digest column mismatch", n)
        if d in seen: dup += 1; continue
        seen[d] = n
print(f"files={len(files)} lines={total} valid_unique={len(seen)} duplicate={dup} invalid={bad}")
if a.out:
    with open(a.out, "w") as f:
        for d, n in seen.items(): f.write(f"{n},0x{d.hex()}\n")
    print("->", a.out)
if a.onchain:
    from pearl_common import load_config, contracts
    from web3 import Web3
    cfg = load_config(a.config)
    w, m, _ = contracts(cfg)
    wal = Web3.to_checksum_address(P.get("wallet") or cfg["wallet"])
    ct = m.functions.currentTarget().call()
    print("chain puzzleSeed match:", m.functions.puzzleSeed(wal).call() == seed, "| currentTarget == target:", ct == T)
    ok = 0; items = list(seen.items())[:a.onchain]
    for d, n in items:
        pd = m.functions.proofDigest(wal, n).call(); used = m.functions.usedProofs(pd).call()
        ok += pd == d
        print(f"  nonce={n} proofDigest_match={pd == d} used={used} <=currentTarget={int.from_bytes(pd, 'big') <= ct}")
    print(f"on-chain spot-check {ok}/{len(items)} match")
    if ok != len(items): sys.exit(1)
if bad: sys.exit(2)
