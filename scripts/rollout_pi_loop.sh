#!/bin/bash
# rollout policy-iteration scaling loop (2026-07-26)。 daily/ExIt 停止で空いた全コアを使い
# beam-rollout corpus を 12 workers で継続 scale。 2 batch 毎の checkpoint で:
#   retrain value_rollout_beam → arena vs deployed value.pkl (★criterion) + vs agnostic (絶対参照)。
# ★実装 criterion = value_rollout_beam が value.pkl を超える (vs deployed > 0.50) = crossover。
#   超えたら「ループを閉じる (rollout の読み手を value_rollout_beam に)」判断点。 value.pkl は
#   daily loop 停止で凍結済 = 安定した比較対象。
# 進捗は per-game で db/eiv1/collect_progress_beam.log に出る (tail -f 可)。
set -u
cd /home/ohtsuki/projects/onepiece_research
export ONEPIECE_EIV1_RO_AI=beam          # tag=beam → rollout_corpus_beam.jsonl に APPEND (resumable)
PY=.venv/bin/python
VR=db/eiv1/value_rollout_beam.pkl
VDEPLOY=db/eiv1/value.pkl
CORPUS=db/eiv1/rollout_corpus_beam.jsonl
NBATCH="${NBATCH:-20}"; GAMES="${GAMES:-150}"; WORKERS="${WORKERS:-12}"
log(){ echo "[$(date +%H:%M:%S)] $*"; }
winrate(){ grep -oE '勝率 = [0-9.]+' | grep -oE '[0-9.]+' | head -1; }

log "=== rollout PI scaling 開始 (WORKERS=$WORKERS, corpus 初期=$(wc -l < "$CORPUS")) ==="
for b in $(seq 1 "$NBATCH"); do
  n0=$(wc -l < "$CORPUS" 2>/dev/null || echo 0)
  log "--- batch $b/$NBATCH collect (corpus=$n0, workers=$WORKERS) ---"
  $PY scripts/eiv1_rollout.py collect --games "$GAMES" --rollouts 6 --workers "$WORKERS" 2>&1 | tail -1
  n1=$(wc -l < "$CORPUS" 2>/dev/null || echo 0)
  log "--- batch $b/$NBATCH 完了 (corpus=$n1, +$((n1 - n0))) ---"
  if [ $((b % 2)) -eq 0 ]; then
    log "  [checkpoint b=$b] retrain + gate (criterion=vs deployed)"
    $PY scripts/eiv1_rollout.py train 2>&1 | grep -E 'train:'
    WD=$($PY scripts/eiv1_arena.py --arm "$VR" --refs "$VDEPLOY" --pairs 40 --workers "$WORKERS" 2>&1 | winrate)
    WA=$($PY scripts/eiv1_arena.py --arm "$VR" --refs agnostic --pairs 40 --workers "$WORKERS" 2>&1 | winrate)
    log "  [b=$b GATE] ★vs deployed(criterion)=${WD:-?} | vs agnostic(ref)=${WA:-?}  (corpus=$n1)"
    if [ -n "${WD:-}" ] && awk "BEGIN{exit !($WD>0.52)}"; then
      log "  ⭐⭐ CROSSOVER 到達: vs deployed=$WD > 0.52 = value.pkl 超え → ループを閉じる判断点!"
    fi
  fi
done
log "=== PI scaling 完了 (最終 corpus=$(wc -l < "$CORPUS")) ==="
