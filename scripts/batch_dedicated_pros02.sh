#!/bin/bash
# pros02 デッキに専用 value を beam-in-loop で学習する batch (luffy_gb で +4.2pt を実証したレシピ)。
# 各 deck: 7 iter × 48 games × 5相手 で単一デッキ学習 → iter pkl を db/_selfplay/ に出力。
# 学習後の A/B (両seat×4opp) は別途 batch_dedicated_ab.sh で回し、 超えた deck だけ配備。
set -e
cd /home/ohtsuki/projects/onepiece_research
LOG=/tmp/claude-1000/-home-ohtsuki-projects-onepiece-research/6d37881d-ef4f-41e4-a698-d3e9446e0c9f/scratchpad/batch_dedicated.log
: > "$LOG"
OPPS="cardrush_1454,tcgportal_calgara,tcgportal_bonney,cardrush_1385,tcgportal_hancock"
for DECK in pros02_zoro_g pros02_luffy_r pros02_sabo_rb pros02_kuzan_b; do
  echo "===== TRAIN $DECK =====" >> "$LOG"
  ONEPIECE_GBM_V6=1 .venv/bin/python scripts/selfplay_beam_loop.py \
    --deck "$DECK" --opp "$OPPS" \
    --iters 7 --games 48 --eval 40 --beam-width 8 --max-depth 6 \
    --workers 12 --feature-ver v2 --arm dedicated \
    >> "$LOG" 2>&1 || echo "!! $DECK 学習失敗" >> "$LOG"
done
echo "ALL_TRAIN_DONE" >> "$LOG"
