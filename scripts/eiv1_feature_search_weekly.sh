#!/usr/bin/env bash
# EIV1 自動 feature 探索の週次ランナー — 2026-07-23。
#
# 「指標が自動で増える」仕組みの定期実行。 日次の学習ループ (eiv1_daily.sh) は 30 分毎に
# データを貯め続け、 こちらは週 1 で **列そのもの** を増やす:
#   生成 → 帰無分布で刈り込み → ブロック AUC → 候補 value → ε=0 arena gate → 採用/棄却
# 採用されると db/eiv1/feature_spec.json が伸び、 次の train から次元が増える。
#
#   cron: 30 4 * * 0 bash /home/ohtsuki/projects/onepiece_research/scripts/eiv1_feature_search_weekly.sh
#
# 調整 (env): SAMPLE(120000) FULL_SAMPLE(200000) ARENA_PAIRS(40) WORKERS(4) MIN_AUC(0.0010)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
LOG="$ROOT/db/eiv1/feature_search.log"
mkdir -p "$ROOT/db/eiv1"

export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

SAMPLE="${SAMPLE:-120000}"; FULL_SAMPLE="${FULL_SAMPLE:-200000}"
ARENA_PAIRS="${ARENA_PAIRS:-40}"; WORKERS="${WORKERS:-4}"; MIN_AUC="${MIN_AUC:-0.0010}"

# 多重起動防止 (前回がまだ探索中なら skip)。 ⚠ 日次ループとは別 lock = 収集は止めない
LOCK="$ROOT/db/eiv1/.search.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 別の探索が実行中 → skip" >> "$LOG"
  exit 0
fi

echo "[$(date '+%F %T')] feature search start (sample=$SAMPLE arena=$ARENA_PAIRS)" >> "$LOG"
# nice: 日次の収集ワーカーを優先させ、 探索は空きコアで回す
nice -n 14 "$PY" scripts/eiv1_feature_search.py \
  --sample "$SAMPLE" --full-sample "$FULL_SAMPLE" \
  --arena-pairs "$ARENA_PAIRS" --workers "$WORKERS" --min-auc "$MIN_AUC" >> "$LOG" 2>&1 || {
    echo "[$(date '+%F %T')] feature search ERROR (exit $?)" >> "$LOG"; exit 1; }
echo "[$(date '+%F %T')] feature search done" >> "$LOG"
