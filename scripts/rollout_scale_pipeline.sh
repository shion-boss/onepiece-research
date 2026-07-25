#!/bin/bash
# beam-rollout value 強気実装パイプライン (2026-07-25、 harness 追跡 background で完走→通知)。
#   1. beam rollout データを小 batch で収集 (rollout_corpus_beam.jsonl に APPEND=checkpointed)
#   2. 2 batch 毎に retrain + arena (value_rollout_beam vs value_outcome_beam) = signal×データ量の推移
#   3. 最終 gate: value_rollout_beam vs agnostic(絶対) + vs 配備 value.pkl(実配備相手)
# 途中停止しても完了済 batch は corpus に残る (resumable = 再実行で続きから)。
set -u
cd /home/ohtsuki/projects/onepiece_research
export ONEPIECE_EIV1_RO_AI=beam
PY=.venv/bin/python
CORPUS=db/eiv1/rollout_corpus_beam.jsonl
VR=db/eiv1/value_rollout_beam.pkl
VO=db/eiv1/value_outcome_beam.pkl
VDEPLOY=db/eiv1/value.pkl
AGN=db/value_gbm_agnostic.pkl
NBATCH="${NBATCH:-6}"; GAMES="${GAMES:-150}"; WORKERS="${WORKERS:-6}"
log(){ echo "[$(date +%H:%M:%S)] $*"; }

log "=== rollout scale pipeline 開始 (target NBATCH=$NBATCH × GAMES=$GAMES, corpus 初期=$(wc -l < $CORPUS)) ==="
for b in $(seq 1 "$NBATCH"); do
  n0=$(wc -l < "$CORPUS" 2>/dev/null || echo 0)
  log "--- batch $b/$NBATCH collect 開始 (corpus=$n0) ---"
  $PY scripts/eiv1_rollout.py collect --games "$GAMES" --rollouts 6 --workers "$WORKERS" 2>&1 | tail -2
  n1=$(wc -l < "$CORPUS" 2>/dev/null || echo 0)
  log "--- batch $b/$NBATCH collect 完了 (corpus=$n1, +$((n1 - n0))) ---"
  # 2 batch 毎に signal 推移を測る
  if [ $((b % 2)) -eq 0 ]; then
    log "  [checkpoint b=$b] retrain + arena(vs outcome)"
    $PY scripts/eiv1_rollout.py train 2>&1 | grep -E 'train:|保存' | head -3
    $PY scripts/eiv1_arena.py --arm "$VR" --refs "$VO" --pairs 40 --workers "$WORKERS" 2>&1 | grep -E '勝率' | sed "s/^/  [b=$b vs outcome] /"
  fi
done

log "=== 最終 gate (corpus=$(wc -l < $CORPUS)) ==="
$PY scripts/eiv1_rollout.py train 2>&1 | grep -E 'train:|保存' | head -3
log "gate1: value_rollout_beam vs agnostic (絶対強さ vs EBV2)"
$PY scripts/eiv1_arena.py --arm "$VR" --refs "$AGN" --pairs 80 --workers "$WORKERS" 2>&1 | grep -E '勝率' | sed 's/^/  [vs agnostic] /'
log "gate2: value_rollout_beam vs 配備 value.pkl (実配備相手)"
$PY scripts/eiv1_arena.py --arm "$VR" --refs "$VDEPLOY" --pairs 80 --workers "$WORKERS" 2>&1 | grep -E '勝率' | sed 's/^/  [vs deployed] /'
log "gate3 (対照): value_outcome_beam vs agnostic (rollout でなく outcome ラベルの絶対強さ)"
$PY scripts/eiv1_arena.py --arm "$VO" --refs "$AGN" --pairs 80 --workers "$WORKERS" 2>&1 | grep -E '勝率' | sed 's/^/  [outcome vs agnostic] /'
log "=== pipeline 完了 ==="
