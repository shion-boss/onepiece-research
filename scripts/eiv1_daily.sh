#!/usr/bin/env bash
# EIV1 日次データ蓄積ランナー (ローカル cron/nohup 用) — 2026-07-24。
#
# collect+train を回して corpus を貯め value を育てる (= EIV1 の「回せば貯まる」を毎日自動で)。
# corpus/value はローカルディスク (db/eiv1/、 gitignore) に永続。 token 消費ゼロ・compute 無料。
# single-instance (flock) で多重起動防止 (前回がまだ回っていたら skip)。
#
#   手動:   bash scripts/eiv1_daily.sh
#   裏で:   nohup bash scripts/eiv1_daily.sh >/dev/null 2>&1 &
#   cron:   0 2 * * * cd ~/projects/onepiece_research && bash scripts/eiv1_daily.sh
#           (crontab -e に上記1行。 毎日 2:00 に 1 晩分回す)
#
# 調整 (env で上書き可):
#   ROUNDS(8) GAMES(500) WORKERS(12) BEAM_W(8) BEAM_D(6) HERO(cardrush_1454) OPPS(4デッキ)
#   例: ROUNDS=3 GAMES=300 bash scripts/eiv1_daily.sh   (軽め)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
mkdir -p "$ROOT/db/eiv1"
LOG="$ROOT/db/eiv1/loop.log"

# BLAS/OpenMP スレッドを 1 に固定 (multiprocessing の worker × 内部スレッド過剰subscription 防止)。
# eiv1_collect.py 側でも設定するが cron/任意起動でも効くよう export しておく。
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1

ROUNDS="${ROUNDS:-8}"; GAMES="${GAMES:-500}"; WORKERS="${WORKERS:-12}"
BEAM_W="${BEAM_W:-8}"; BEAM_D="${BEAM_D:-6}"
# ε=0 arena (強さ実測): ARENA_EVERY ラウンドごとに ARENA_PAIRS ペア (=4x game)。 0 で無効
ARENA_EVERY="${ARENA_EVERY:-8}"; ARENA_PAIRS="${ARENA_PAIRS:-100}"

# デッキ在庫フル活用: hero/opp とも全プール (233 デッキ/36 リーダー) を回転。 未生成なら自動生成。
POOL="$ROOT/db/eiv1/pool_all.txt"
[ -f "$POOL" ] || "$PY" scripts/eiv1_build_pools.py >> "$LOG" 2>&1
HEROES="${HEROES:-@db/eiv1/pool_all.txt}"
OPPS="${OPPS:-@db/eiv1/pool_all.txt}"

# 多重起動防止: 前回がまだ回っていたら今回は skip (長い collect が跨いでも stack しない)
LOCK="$ROOT/db/eiv1/.daily.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 別インスタンスが実行中 → skip" >> "$LOG"
  exit 0
fi

BEFORE=0; [ -f "$ROOT/db/eiv1/corpus.jsonl" ] && BEFORE=$(wc -l < "$ROOT/db/eiv1/corpus.jsonl")
echo "[$(date '+%F %T')] EIV1 daily start: heroes=$HEROES rounds=$ROUNDS games=$GAMES beam=$BEAM_W/$BEAM_D | corpus=$BEFORE" >> "$LOG"
"$PY" scripts/eiv1_loop.py --rounds "$ROUNDS" --games "$GAMES" --workers "$WORKERS" \
  --beam-width "$BEAM_W" --max-depth "$BEAM_D" --heroes "$HEROES" --opps "$OPPS" \
  --arena-every "$ARENA_EVERY" --arena-pairs "$ARENA_PAIRS" >> "$LOG" 2>&1 || {
    echo "[$(date '+%F %T')] EIV1 daily ERROR (exit $?)" >> "$LOG"; exit 1; }
AFTER=0; [ -f "$ROOT/db/eiv1/corpus.jsonl" ] && AFTER=$(wc -l < "$ROOT/db/eiv1/corpus.jsonl")
echo "[$(date '+%F %T')] EIV1 daily done | corpus $BEFORE -> $AFTER (+$((AFTER-BEFORE)))" >> "$LOG"
