#!/usr/bin/env bash
# Loop2 残り gate sweep (target = bonney 固定)。 各 counter を deploy_counter.py で
# gate→deploy→matrix書戻し→recompute→json追記。 done-marker で crash-resume。
set -u
cd /home/ohtsuki/projects/onepiece_research
PY=.venv/bin/python
TOP=tcgportal_bonney
MARK=db/_selfplay/_l2_resume_marks
mkdir -p "$MARK"
LOG=db/_selfplay/l2_sweep_resume.log

# counter slug : iter
COUNTERS=(
  "cardrush_1453:iter6"          # mihawk (crash 地点)
  "cardrush_1456:iter2"          # ace
  "tcgportal_op13_luffy:iter7"   # op13
  "cardrush_1385:iter3"          # kuro
  "cardrush_1392:iter5"          # im
  "tcgportal_calgara:iter4"      # calgara
)

echo "=== L2 resume sweep start $(date -u +%FT%TZ) | top=$TOP ===" | tee -a "$LOG"
for entry in "${COUNTERS[@]}"; do
  c="${entry%%:*}"; it="${entry##*:}"
  if [ -f "$MARK/$c.done" ]; then
    echo ">>> SKIP $c ($it) — already done" | tee -a "$LOG"
    continue
  fi
  echo "" | tee -a "$LOG"
  echo "######## GATE $c ($it) vs $TOP @ $(date -u +%FT%TZ) ########" | tee -a "$LOG"
  $PY scripts/deploy_counter.py --counter "$c" --top "$TOP" --iter "$it" \
      --n 40 --beam-width 16 --max-depth 10 >> "$LOG" 2>&1
  rc=$?
  if [ $rc -eq 0 ]; then
    touch "$MARK/$c.done"
    echo ">>> $c DONE (rc=0)" | tee -a "$LOG"
  else
    echo ">>> $c FAILED rc=$rc — 続行 (次の counter へ)" | tee -a "$LOG"
  fi
done
echo "" | tee -a "$LOG"
echo "=== L2 resume sweep COMPLETE $(date -u +%FT%TZ) ===" | tee -a "$LOG"
