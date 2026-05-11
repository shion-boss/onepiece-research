#!/bin/bash
# scripts/auto_rewrite_round.sh
# ローカル cron から呼ばれて 1 ラウンドの DSL 書き換えを実行する。
#
# 安全装置:
# - .auto_rewrite.STOP marker があれば即終了
# - .auto_rewrite.lock で並行実行防止
# - pre-test と post-test (pytest + smoke) が pass しないと commit しない
# - 失敗時は git reset --hard HEAD で巻き戻し + STOP marker
#
# 使い方:
#   ./scripts/auto_rewrite_round.sh        # 1 回実行
#   crontab -e で */30 * * * * /home/ohtsuki/projects/onepiece_research/scripts/auto_rewrite_round.sh

set -uo pipefail

REPO=/home/ohtsuki/projects/onepiece_research
LOG=$REPO/.auto_rewrite.log
LOCK=$REPO/.auto_rewrite.lock
STOP=$REPO/.auto_rewrite.STOP
PROMPT_FILE=$REPO/scripts/auto_rewrite_prompt.md

cd "$REPO" || { echo "cd failed" >&2; exit 1; }

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

log "=== round start ==="

# STOP marker check
if [ -f "$STOP" ]; then
  log "STOP marker present, exiting"
  exit 0
fi

# Lock check
if [ -f "$LOCK" ]; then
  PID=$(cat "$LOCK" 2>/dev/null || echo "?")
  if kill -0 "$PID" 2>/dev/null; then
    log "previous run (pid=$PID) still active, skipping"
    exit 1
  else
    log "stale lock (pid=$PID), reclaiming"
    rm -f "$LOCK"
  fi
fi
echo $$ > "$LOCK"
# shellcheck disable=SC2064
trap "rm -f $LOCK" EXIT

# Pre-test
log "pre-test: pytest"
.venv/bin/pytest tests/ -q > /tmp/pytest_before.txt 2>&1
PT=$?
if [ $PT -ne 0 ]; then
  log "PRE-TEST FAILED, creating STOP marker"
  tail -30 /tmp/pytest_before.txt >> "$LOG"
  touch "$STOP"
  exit 1
fi

# Working tree must be clean (= previous round committed)
if [ -n "$(git status --porcelain)" ]; then
  log "working tree not clean, creating STOP marker"
  git status >> "$LOG"
  touch "$STOP"
  exit 1
fi

HEAD_BEFORE=$(git rev-parse HEAD)
log "HEAD before: $HEAD_BEFORE"

# Run Claude headless
log "invoking claude -p"
claude -p \
  --no-session-persistence \
  --max-budget-usd 5 \
  --permission-mode bypassPermissions \
  --model claude-haiku-4-5-20251001 \
  --fallback-model claude-sonnet-4-6 \
  "$(cat "$PROMPT_FILE")" \
  >> "$LOG" 2>&1
CLAUDE_RC=$?
log "claude exit code: $CLAUDE_RC"

# Post-check
log "post-test: pytest"
.venv/bin/pytest tests/ -q > /tmp/pytest_after.txt 2>&1
PT=$?
if [ $PT -ne 0 ]; then
  log "POST-TEST FAILED, reverting"
  tail -50 /tmp/pytest_after.txt >> "$LOG"
  git reset --hard "$HEAD_BEFORE" >> "$LOG" 2>&1
  touch "$STOP"
  exit 1
fi

# Smoke test
log "post-test: smoke"
.venv/bin/python scripts/smoke_test_card_effects.py > /tmp/smoke_after.txt 2>&1
SM=$?
if [ $SM -ne 0 ] || grep -qE 'ERROR=\s*[1-9]' /tmp/smoke_after.txt; then
  log "SMOKE TEST FAILED, reverting"
  tail -30 /tmp/smoke_after.txt >> "$LOG"
  git reset --hard "$HEAD_BEFORE" >> "$LOG" 2>&1
  touch "$STOP"
  exit 1
fi

HEAD_AFTER=$(git rev-parse HEAD)
if [ "$HEAD_BEFORE" = "$HEAD_AFTER" ]; then
  log "no new commit (claude likely exited via STOP path)"
else
  # 件数チェック
  COUNT=$(.venv/bin/python -c "
import json
from collections import Counter
with open('db/card_effects.json') as f: data = json.load(f)
c = Counter()
def w(o):
    if isinstance(o, dict):
        if '_unimplemented' in o: c[o['_unimplemented']] += 1
        for v in o.values(): w(v)
    elif isinstance(o, list):
        for v in o: w(v)
for cid, e in data.items():
    if not cid.startswith('_'): w(e)
print(f'{sum(c.values())} / {len(c)}')
" 2>/dev/null)
  log "committed $HEAD_AFTER, _unimplemented total/unique: $COUNT"
fi

log "=== round end OK ==="
exit 0
