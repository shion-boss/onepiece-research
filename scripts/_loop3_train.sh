#!/usr/bin/env bash
# Loop3 (target=bonney) focused scale-up 訓練。 contesting counter を深く訓練。
# probe-first: calgara を最初に回し、 SLOPE が loop2 を超えるか早期判定可能。
# done-marker で crash-resume。 各 counter は selfplay_beam_loop が pkl を逐次保存。
set -u
cd /home/ohtsuki/projects/onepiece_research
PY=.venv/bin/python
MARK=db/_selfplay/_l3_train_marks
mkdir -p "$MARK"
LOG=db/_selfplay/l3_train.log

ITERS=10; GAMES=120; EVAL=80; BW=8; BD=6

# counter : opp(comma)
ROSTER=(
  "tcgportal_calgara:tcgportal_bonney"                       # probe (loop2 peak ~18-35%)
  "cardrush_1455:tcgportal_bonney,tcgportal_calgara"         # skypiea (loop2 best contester 42-58%)
  "cardrush_1456:tcgportal_bonney,tcgportal_calgara"         # ace (46% both-seat, loop2 no-deploy)
  "cardrush_1439:tcgportal_bonney,tcgportal_calgara"         # nami
  "tcgportal_hancock:tcgportal_bonney,tcgportal_calgara"     # hancock
)

echo "=== L3 train start $(date -u +%FT%TZ) | scale iters=$ITERS games=$GAMES eval=$EVAL beam=$BW/$BD ===" | tee -a "$LOG"
for entry in "${ROSTER[@]}"; do
  c="${entry%%:*}"; opp="${entry##*:}"
  if [ -f "$MARK/$c.done" ]; then echo ">>> SKIP $c (done)" | tee -a "$LOG"; continue; fi
  echo "" | tee -a "$LOG"
  echo "######## TRAIN $c vs $opp @ $(date -u +%FT%TZ) ########" | tee -a "$LOG"
  $PY scripts/selfplay_beam_loop.py --deck "$c" --opp "$opp" \
      --iters $ITERS --games $GAMES --eval $EVAL --epsilon 0.25 --eps-end 0.05 \
      --beam-width $BW --max-depth $BD --workers 12 >> "$LOG" 2>&1
  rc=$?
  if [ $rc -eq 0 ]; then touch "$MARK/$c.done"; echo ">>> $c TRAIN DONE" | tee -a "$LOG"
  else echo ">>> $c TRAIN FAILED rc=$rc — 続行" | tee -a "$LOG"; fi
done
echo "" | tee -a "$LOG"
echo "=== L3 train COMPLETE $(date -u +%FT%TZ) ===" | tee -a "$LOG"
