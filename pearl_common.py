"""Shared helpers: config loading, web3 setup, keccak, ABI."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))

MINING_ABI = [
    {"name": n, "type": "function", "stateMutability": "view", "inputs": i, "outputs": o}
    for n, i, o in [
        ("challenge", [{"name": "wallet", "type": "address"}, {"name": "id", "type": "uint256"}],
         [{"name": "seed", "type": "bytes32"}, {"name": "target", "type": "uint256"}, {"name": "reward", "type": "uint256"},
          {"name": "eligible", "type": "bool"}, {"name": "live", "type": "bool"}, {"name": "claims", "type": "uint256"}]),
        ("puzzleSeed", [{"name": "w", "type": "address"}], [{"name": "", "type": "bytes32"}]),
        ("proofDigest", [{"name": "w", "type": "address"}, {"name": "n", "type": "uint256"}], [{"name": "", "type": "bytes32"}]),
        ("usedProofs", [{"name": "p", "type": "bytes32"}], [{"name": "", "type": "bool"}]),
        ("currentTarget", [], [{"name": "", "type": "uint256"}]),
        ("currentReward", [], [{"name": "", "type": "uint256"}]),
        ("dailyRemaining", [], [{"name": "", "type": "uint256"}]),
        ("isLive", [], [{"name": "", "type": "bool"}]),
        ("startsAt", [], [{"name": "", "type": "uint256"}]),
        ("miningDay", [], [{"name": "", "type": "uint256"}]),
        ("MAX_BATCH", [], [{"name": "", "type": "uint256"}]),
        ("decimals", [], [{"name": "", "type": "uint8"}]),
        ("balanceOf", [{"name": "a", "type": "address"}], [{"name": "", "type": "uint256"}]),
    ]
] + [{"name": "mineBatch", "type": "function", "stateMutability": "nonpayable",
      "inputs": [{"name": "id", "type": "uint256"}, {"name": "nonces", "type": "uint256[]"},
                 {"name": "minTotalReward", "type": "uint256"}], "outputs": []}]

REGISTRY_ABI = [
    {"name": "handleOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "w", "type": "address"}], "outputs": [{"name": "", "type": "string"}]},
    {"name": "ownerOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "id", "type": "uint256"}], "outputs": [{"name": "", "type": "address"}]},
]

try:
    from Crypto.Hash import keccak as _k
    def keccak256(b):
        h = _k.new(digest_bits=256); h.update(b); return h.digest()
except ImportError:
    from eth_utils import keccak as keccak256  # noqa


def load_config(path=None):
    path = path or os.environ.get("PEARL_CONFIG") or os.path.join(HERE, "config.yaml")
    if not os.path.exists(path):
        sys.exit(f"config not found: {path} (copy config.example.yaml to config.yaml)")
    import yaml
    cfg = yaml.safe_load(open(path)) or {}
    if "private_key" in json.dumps(cfg).lower():
        sys.exit("refusing: config contains a private_key field. Use the PRIVATE_KEY env var instead.")
    cfg.setdefault("miner", {}); cfg.setdefault("submit", {}); cfg.setdefault("paths", {})
    base = os.path.dirname(os.path.abspath(path))
    for k, v in list(cfg["paths"].items()):
        if isinstance(v, str) and not os.path.isabs(v):
            cfg["paths"][k] = os.path.join(base, v)
    if isinstance(cfg.get("rpc_urls"), str):
        cfg["rpc_urls"] = [cfg["rpc_urls"]]
    return cfg


def web3_for(url, timeout=20):
    from web3 import Web3
    w = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": timeout}))
    try:
        from web3.middleware import ExtraDataToPOAMiddleware
        w.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    except ImportError:
        pass
    return w


def contracts(cfg, w=None):
    from web3 import Web3
    w = w or web3_for(cfg["rpc_urls"][0])
    m = w.eth.contract(Web3.to_checksum_address(cfg["mining_contract"]), abi=MINING_ABI)
    r = w.eth.contract(Web3.to_checksum_address(cfg["registry"]), abi=REGISTRY_ABI)
    return w, m, r


def wallet_of(cfg):
    from web3 import Web3
    wal = str(cfg.get("wallet", ""))
    if not Web3.is_address(wal):
        sys.exit(f"invalid wallet in config: {wal!r}")
    return Web3.to_checksum_address(wal)


def resolve_id(cfg, reg, wallet):
    """Returns (handle, id). id = uint256(keccak256(raw handle bytes)); never add/remove '.ai'."""
    if cfg.get("agent_id"):
        return None, int(str(cfg["agent_id"]), 0)
    handle = reg.functions.handleOf(wallet).call()
    if not handle:
        return "", None
    return handle, int.from_bytes(keccak256(handle.encode("utf-8")), "big")


def digest(seed: bytes, nonce: int) -> bytes:
    return keccak256(seed + int(nonce).to_bytes(32, "big"))


def read_nonce_file(path):
    out = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split(",")
        try:
            out.append((int(p[0]), p[1].strip() if len(p) > 1 else None))
        except ValueError:
            pass
    return out


ERRORS = {"efdc789e": "MiningNotStarted", "178423dd": "InvalidIdentity", "d9c1988f": "InvalidSolution",
          "c9838a65": "ProofAlreadyUsed", "577742ca": "RewardChanged", "8a7d2016": "MiningFinished",
          "7862e959": "InvalidBatchSize", "f402e5b1": "DailyLimitReached", "d93c0665": "EnforcedPause (paused)"}


def decode_error(e):
    s = str(e)
    for k, v in ERRORS.items():
        if k in s: return v
    return s[:200]
