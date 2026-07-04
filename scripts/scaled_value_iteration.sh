#!/bin/bash
# スケール value 反復(option 3): コーパスをバッチで積み増し、 各 round で from-scratch value を
# 再訓練 + A/B screen し、 svi% が iter1(baseline)% を超えるか曲線で監視。 resumable(batch file
# 存在で skip)、 こまめに checkpoint(無駄最小)。 docs/block_value_architecture.md。
#
#   bash scripts/scaled_value_iteration.sh <max_rounds> <games_per_round>
#
# baseline = value_gbm_cardrush_1454.pkl (iter1, 固定=生成にも使う best)。 svi 候補を毎 round A/B。
# svi が iter1 を安定して超えたら手動で promote。 停止は round 上限 or 手動 kill(resumable)。
set -u
cd /home/ohtsuki/projects/onepiece_research
PY=.venv/bin/python
SCR=/tmp/claude-1000/-home-ohtsuki-projects-onepiece-research/921ed30f-b57f-4c33-93f1-bc83dac5a319/scratchpad
DECK=cardrush_1454
OPPS_GEN="cardrush_1454 tcgportal_calgara tcgportal_bonney cardrush_1342 cardrush_1439 tcgportal_hancock cardrush_1385"
OPPS_AB="cardrush_1454,tcgportal_calgara,tcgportal_bonney"   # screen 用(climb 追跡)
MAX_ROUNDS="${1:-6}"
GPR="${2:-300}"           # games/round(全 opp 合計 ≈ この数)
NOPP=7
PER=$(( (GPR + NOPP - 1) / NOPP ))   # opp あたり game 数
CURVE="$SCR/svi_curve.log"
LOG="$SCR/svi.log"
BOOT=db/value_gbm_${DECK}.pkl        # iter1(生成 bootstrap + AI)

echo "[start] max_rounds=$MAX_ROUNDS games/round≈$((PER*NOPP)) per_opp=$PER" | tee -a "$LOG"
[ -f "$CURVE" ] || echo "round  samples  iter1%  svi%   delta" > "$CURVE"

for r in $(seq 0 $((MAX_ROUNDS-1))); do
  BATCH=db/_analyst/svi_batch_${r}.jsonl
  SEEDBASE=$((3000 + r*1000))
  if [ ! -s "$BATCH" ]; then
    echo "[round $r] generate $((PER*NOPP)) games (seed-base $SEEDBASE) ..." | tee -a "$LOG"
    $PY scripts/gen_block_value_targets.py --deck $DECK --opponents $OPPS_GEN \
      --n-games $PER --feat v11 --value-path $BOOT --seed-base $SEEDBASE \
      --out $BATCH >> "$LOG" 2>&1
  else
    echo "[round $r] batch 既存 → skip gen" | tee -a "$LOG"
  fi
  # 累積コーパス
  CORPUS=db/_analyst/svi_corpus.jsonl
  cat db/_analyst/svi_batch_*.jsonl > "$CORPUS" 2>/dev/null
  N=$(wc -l < "$CORPUS")
  # from-scratch value(blend lam0.5、 容量は data で拡大)
  EST=$(( N > 3000 ? 500 : 300 ))
  $PY scripts/train_block_value.py --in db/_analyst/svi_corpus.jsonl --lam 0.5 \
    --out db/_selfplay/mcab_${DECK}_svi.pkl >> "$LOG" 2>&1
  # A/B screen(iter1 vs svi)
  echo "[round $r] A/B screen (N=20, $OPPS_AB) ..." | tee -a "$LOG"
  $PY scripts/matchup_value_deploy_ab.py --deck $DECK --arms default,svi \
    --opps $OPPS_AB --n 20 --beam-width 16 --max-depth 10 --workers 12 \
    > "$SCR/svi_ab_${r}.log" 2>&1
  LINE=$(grep "OVERALL" "$SCR/svi_ab_${r}.log" | tail -1)
  I1=$(echo "$LINE" | awk '{print $2}')
  SV=$(echo "$LINE" | awk '{print $3}')
  DELTA=$($PY -c "print(f'{float('$SV')-float('$I1'):+.1f}')" 2>/dev/null || echo "?")
  printf "%-6s %-8s %-7s %-6s %s\n" "$r" "$N" "$I1" "$SV" "$DELTA" >> "$CURVE"
  echo "[round $r] samples=$N  iter1=$I1  svi=$SV  delta=$DELTA" | tee -a "$LOG"
  # 保存(この round の value を残す)
  cp db/_selfplay/mcab_${DECK}_svi.pkl db/_selfplay/svi_iter_${r}.pkl
done
echo "[done] curve:" | tee -a "$LOG"; cat "$CURVE" | tee -a "$LOG"
