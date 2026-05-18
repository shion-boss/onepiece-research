#!/bin/bash
# Phase 2 完了後 即起動用: Step 5 belief NN の effect 測定
# adaptive AI (= DeepPlanningAI、 belief NN 自動 ON) vs adaptive AI (= belief OFF)
# mirror で 効果差を出す

cd /home/ohtsuki/projects/onepiece_research

# Test 1: 既存 adaptive AI (= belief NN auto-load) vs baseline mirror
echo "[1/2] adaptive AI (belief ON) vs baseline mirror"
.venv/bin/python scripts/run_ai_mirror_eval.py \
  --ai-class engine.ai.DeepPlanningAI \
  --ai-kwargs '{"adaptive": false, "beam_width": 2, "max_depth": 3}' \
  --output db/ai_search/adaptive_with_belief_n10.json \
  --n-games 10 --label adaptive_with_belief

# Test 2: belief NN を強制 OFF した adaptive AI vs baseline mirror
echo "[2/2] adaptive AI (belief OFF) vs baseline mirror"
ONEPIECE_OPP_ACTION_DISABLE=1 \
.venv/bin/python scripts/run_ai_mirror_eval.py \
  --ai-class engine.ai.DeepPlanningAI \
  --ai-kwargs '{"adaptive": false, "beam_width": 2, "max_depth": 3}' \
  --output db/ai_search/adaptive_without_belief_n10.json \
  --n-games 10 --label adaptive_without_belief

# 結果比較
echo ""
echo "=== Step 5 belief NN 効果検証 結果 ==="
.venv/bin/python -c "
import json
for label, path in [('belief ON', 'db/ai_search/adaptive_with_belief_n10.json'),
                    ('belief OFF', 'db/ai_search/adaptive_without_belief_n10.json')]:
    d = json.load(open(path))
    results = d.get('results', [])
    if results:
        avg = sum(r['improved_winrate'] for r in results) / len(results)
        print(f'  {label}: avg {avg*100:.1f}% across {len(results)} decks')
"
