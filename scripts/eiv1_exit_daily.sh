#!/usr/bin/env bash
# EIV1-ExIt 複利ループの日次自律ランナー — 2026-07-24。
# 探索→policy蒸留→探索↑ を回す (= コツコツ回すほど強くなる)。 token 消費ゼロ・compute 無料。
# single-instance (flock)。 ⚠ メイン value フライホイール (eiv1_daily.sh) とは別 lock で共存可
# (両方回すと CPU 競合するので、 片方に絞るか games/workers を下げる)。
#
#   cron: 15 */2 * * * cd ~/projects/onepiece_research && bash scripts/eiv1_exit_daily.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
PY="$ROOT/.venv/bin/python"
mkdir -p "$ROOT/db/eiv1"
LOG="$ROOT/db/eiv1/exit_loop.log"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1

ROUNDS="${ROUNDS:-6}"; GAMES="${GAMES:-150}"; WORKERS="${WORKERS:-8}"
TEMP="${TEMP:-0.6}"; EXIT_W="${EXIT_W:-0.6}"; ARENA_EVERY="${ARENA_EVERY:-3}"

LOCK="$ROOT/db/eiv1/.exit.lock"; exec 9>"$LOCK"
if ! flock -n 9; then echo "[$(date '+%F %T')] 別 ExIt が実行中 → skip" >> "$LOG"; exit 0; fi

BEFORE=0; [ -f "$ROOT/db/eiv1/exit_corpus.jsonl" ] && BEFORE=$(wc -l < "$ROOT/db/eiv1/exit_corpus.jsonl")
echo "[$(date '+%F %T')] ExIt daily start: rounds=$ROUNDS games=$GAMES exit_w=$EXIT_W | 判断=$BEFORE" >> "$LOG"
"$PY" scripts/eiv1_exit_loop.py --rounds "$ROUNDS" --games "$GAMES" --workers "$WORKERS" \
  --temperature "$TEMP" --exit-policy-w "$EXIT_W" --arena-every "$ARENA_EVERY" >> "$LOG" 2>&1 || {
    echo "[$(date '+%F %T')] ExIt daily ERROR (exit $?)" >> "$LOG"; exit 1; }
AFTER=0; [ -f "$ROOT/db/eiv1/exit_corpus.jsonl" ] && AFTER=$(wc -l < "$ROOT/db/eiv1/exit_corpus.jsonl")
echo "[$(date '+%F %T')] ExIt daily done | 判断 $BEFORE -> $AFTER (+$((AFTER-BEFORE)))" >> "$LOG"
