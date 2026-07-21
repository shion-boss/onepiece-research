#!/bin/bash
# pros02 デッキ (model無し) に agnostic value を配備するか batch gate。
# 各 deck で default(現fallback=board_eval or archetype-gate agnostic) vs agn(明示 agnostic) を
# 両seat×4opp×N24 で比較。 aggro deck で agn>default なら archetype gate が過剰保守の証拠。
set -e
cd /home/ohtsuki/projects/onepiece_research
LOG=/tmp/claude-1000/-home-ohtsuki-projects-onepiece-research/6d37881d-ef4f-41e4-a698-d3e9446e0c9f/scratchpad/batch_gate.log
OPPS="cardrush_1454,tcgportal_calgara,tcgportal_bonney,cardrush_1385"
: > "$LOG"
for DECK in pros02_zoro_g pros02_luffy_r pros02_sabo_rb pros02_kid_y pros02_katakuri_p pros02_kuzan_b; do
  echo "===== $DECK =====" >> "$LOG"
  cp db/value_gbm_agnostic.pkl "db/_selfplay/mcab_${DECK}_agn.pkl"
  .venv/bin/python scripts/matchup_value_deploy_ab.py --deck "$DECK" \
    --opps "$OPPS" --arms default,agn --n 24 --beam-width 8 --max-depth 6 --workers 12 \
    >> "$LOG" 2>&1 || echo "!! $DECK gate 失敗" >> "$LOG"
done
echo "ALL_BATCH_DONE" >> "$LOG"
