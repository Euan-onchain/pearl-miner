# pearl-miner-oss

Open-source GPU (CUDA) / CPU miner and submitter for **PEARL** (`PearlMiningV2`) on BNB Smart Chain.
Every address and user value is configurable; nothing user-specific is hardcoded.

## How the puzzle works
- `id = uint256(keccak256(handleOf(wallet)))` from the handle registry (raw handle bytes, no `.ai` added).
- `challenge(wallet, id)` returns `seed, target, reward, eligible, live, claims`.
- Find `nonce` such that `uint256(keccak256(abi.encode(bytes32 seed, uint256 nonce))) <= target`
  (Ethereum Keccak-256, 64-byte input). Equals the contract's `proofDigest(wallet, nonce)`.
- Submit with `mineBatch(uint256 id, uint256[] nonces, uint256 minTotalReward)`, max 16 nonces, sent **from the same wallet** (answers are bound to it). Used proofs are rejected; difficulty rises with progress; daily cap applies.

## Files
| file | purpose |
|---|---|
| `config.example.yaml` | template config (copy to `config.yaml`) |
| `fetch_challenge.py` | read-only: verify code hashes, resolve handle→id, read seed/target → `out/params.json` + `out/params.env` |
| `miner/pearl_miner.cu` | CUDA miner (self-test vs independent reference Keccak, re-verifies each hit) |
| `miner/cpu_miner.c` | multi-threaded CPU fallback |
| `miner/run.sh` | build + self-test + launch one process per GPU (or CPU) |
| `verify.py` | check/dedupe nonce files offline, optional on-chain `proofDigest`/`usedProofs` spot-check |
| `submit.py` | sign & send `mineBatch` txs with a local key from `PRIVATE_KEY` env |
| `pearl_common.py`, `abi.json` | shared helpers / contract ABI |

## Requirements
Python 3.9+, `pip install -r requirements.txt`; gcc for CPU; CUDA toolkit (nvcc) + NVIDIA GPU for GPU mining.

## Configure
```bash
cp config.example.yaml config.yaml   # set wallet, rpc_urls, devices, submit options
```
Default contract/registry are the public PEARL deployment on BSC mainnet; change them for other deployments.

## Run
```bash
python3 fetch_challenge.py                       # writes out/params.json / out/params.env
bash miner/run.sh                                # GPUs (ARCH=sm_89 etc. to override -arch=native)
CPU=1 bash miner/run.sh                          # CPU fallback
# manual: miner/pearl_miner --seed 0x.. --target 0x.. --device 0 --count 100 --out out/nonces_gpu0.txt
python3 verify.py --params out/params.json --onchain 5 --out out/valid_nonces.txt out/nonces_*.txt
```
Build manually: `nvcc -O3 -arch=native -o miner/pearl_miner miner/pearl_miner.cu`,
`gcc -O3 -march=native -pthread -o miner/cpu_miner miner/cpu_miner.c`.

## Submit
```bash
python3 submit.py --dry-run --max-groups 3       # eth_call + gas estimate, nothing sent
export PRIVATE_KEY=0x...                         # only in your shell; never in a file you commit
python3 submit.py                                # asks you to type YES
python3 submit.py --wait-until <unix_ts> --gas-limit 700000 --yes   # pre-sign, fire at the daily open
```
- Each signed tx is broadcast to **all** `rpc_urls` concurrently; tx nonces are managed locally and resynced on gaps.
- Nonces already marked used on chain are skipped; `out/submit_log.csv` is an append-only resume log (submitted/confirmed nonces are not resent).
- `minTotalReward = currentReward × n × (1 − slippage)`; stops on paused/not live, daily cap, low balance, or repeated failures. Re-filters when the target changes.
- Days are 86400-second windows from `startsAt`; the next open is `startsAt + (miningDay()+1)*86400`.

### Mode B: custodial / exchange wallets
If your registered wallet is custodial (exchange Web3 wallet, MPC, smart-account), you cannot export a key.
Use `verify.py` + `submit.py --dry-run` to prepare calldata, then submit with that provider's own official tooling. This repo contains no provider-specific code.

## Risks / disclaimer
Use at your own risk. No warranty. Smart-contract risk (the owner can pause mining; rules may change); gas is spent even on reverted txs; competing submissions are first-come-first-served; token value is not guaranteed.
**Keep your private key safe**: use a dedicated hot wallet with little balance, never commit `.env`/`config.yaml`, never paste the key into shared logs. Check the contract on BscScan before use. Not financial advice.

License: MIT.
