#!/usr/bin/env bash
# Build + self-test + launch one miner per GPU (or the CPU fallback). Pure computation, no keys.
# Params come from env SEED/TARGET or from the params file written by fetch_challenge.py.
#   bash miner/run.sh                    # GPUs from config (or all), params from out/params.env
#   CPU=1 bash miner/run.sh              # CPU fallback
#   DEVICES="0 1" COUNT=100 bash miner/run.sh
set -e
cd "$(dirname "$0")"
ROOT=$(cd .. && pwd)
PARAMS=${PARAMS:-$ROOT/out/params.env}
[ -z "$SEED" ] && [ -f "$PARAMS" ] && source "$PARAMS"
: "${SEED:?SEED not set: run python3 fetch_challenge.py first}"
: "${TARGET:?TARGET not set}"
OUT=${OUT:-$ROOT/out}; mkdir -p "$OUT"
COUNT=${COUNT:-0}
if [ "${CPU:-0}" = 1 ] || ! command -v nvcc >/dev/null; then
  echo "== CPU fallback =="
  gcc -O3 -march=native -pthread -o cpu_miner cpu_miner.c
  ./cpu_miner --selftest
  nohup ./cpu_miner --seed "$SEED" --target "$TARGET" --count "$COUNT" ${THREADS:+--threads $THREADS} \
    --out "$OUT/nonces_cpu.txt" > "$OUT/log_cpu.txt" 2>&1 &
  echo $! > "$OUT/pid_cpu"; echo "CPU miner pid=$(cat "$OUT/pid_cpu")  log: $OUT/log_cpu.txt"; exit 0
fi
ARCH=${ARCH:-native}
echo "== build (nvcc -arch=$ARCH) =="
nvcc -O3 -arch="$ARCH" -o pearl_miner pearl_miner.cu
if [ -z "$DEVICES" ] && [ -f "$ROOT/config.yaml" ]; then
  DEVICES=$(python3 -c "import yaml;d=(yaml.safe_load(open('$ROOT/config.yaml')).get('miner') or {}).get('gpu_devices');print('' if d in (None,'all') else ' '.join(map(str,d)))" 2>/dev/null || true)
fi
if [ -z "$DEVICES" ]; then NG=$(nvidia-smi -L | wc -l); DEVICES=$(seq 0 $((NG-1))); fi
for i in $DEVICES; do ./pearl_miner --selftest --device $i || { echo "GPU$i selftest failed"; exit 1; }; done
for i in $DEVICES; do
  nohup ./pearl_miner --seed "$SEED" --target "$TARGET" --device $i --count "$COUNT" \
    --out "$OUT/nonces_gpu$i.txt" > "$OUT/log_gpu$i.txt" 2>&1 &
  echo $! > "$OUT/pid_gpu$i"; echo "GPU$i pid=$(cat "$OUT/pid_gpu$i")"
done
cat <<MSG
progress: tail -f $OUT/log_gpu*.txt
count:    cat $OUT/nonces_*.txt | wc -l
stop:     kill \$(cat $OUT/pid_*)
verify:   python3 verify.py --params $ROOT/out/params.json --out $ROOT/out/valid_nonces.txt $OUT/nonces_*.txt
MSG
