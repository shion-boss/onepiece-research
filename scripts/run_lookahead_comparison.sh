#!/bin/bash
# 2026-05-18: 1-turn NN / 3-turn NN / baseline の 3-way mirror 比較。
# 学習済 db/weight_nn_oneturn.pt / db/weight_nn_threeturn.pt の 到着後 実行。
#
# 使い方:
#   ./scripts/run_lookahead_comparison.sh
#
# 出力:
#   db/ai_search/oneturn_nn_n10.json    (= 1-turn NN vs baseline)
#   db/ai_search/threeturn_nn_n10.json  (= 3-turn NN vs baseline)
#   db/ai_search/oneturn_vs_threeturn_n10.json は 別途 (= 直接対決、 オプション)

cd /home/ohtsuki/projects/onepiece_research

ONE_NN="db/weight_nn_oneturn.pt"
THREE_NN="db/weight_nn_threeturn.pt"

if [ ! -f "$ONE_NN" ]; then
  echo "[ERROR] $ONE_NN 不在、 Colab 学習完了 + download 待ち"
  exit 1
fi
if [ ! -f "$THREE_NN" ]; then
  echo "[ERROR] $THREE_NN 不在、 Colab 学習完了 + download 待ち"
  exit 1
fi

mkdir -p db/ai_search logs

echo "=== 1-turn NN mirror eval (= WeightNNPlanningAI vs baseline) ==="
ONEPIECE_WEIGHT_NN_PATH="$ONE_NN" \
nohup .venv/bin/python scripts/run_ai_mirror_eval.py \
  --ai-class engine.ai_experimental.WeightNNPlanningAI \
  --ai-kwargs '{}' \
  --output db/ai_search/oneturn_nn_n10.json \
  --n-games 10 --label oneturn_nn > logs/eval_oneturn_nn.log 2>&1 &
ONE_PID=$!
echo "  PID=$ONE_PID"

echo "=== 3-turn NN mirror eval (= WeightNNThreeTurnAI vs baseline) ==="
ONEPIECE_WEIGHT_NN_PATH="$THREE_NN" \
nohup .venv/bin/python scripts/run_ai_mirror_eval.py \
  --ai-class engine.ai_experimental.WeightNNThreeTurnAI \
  --ai-kwargs '{"max_turns": 3, "max_depth": 12, "beam_width": 2, "adaptive": false}' \
  --output db/ai_search/threeturn_nn_n10.json \
  --n-games 10 --label threeturn_nn > logs/eval_threeturn_nn.log 2>&1 &
THREE_PID=$!
echo "  PID=$THREE_PID"

echo "=== 直接対決 mirror eval (= 1-turn NN vs 3-turn NN) ==="
nohup .venv/bin/python scripts/run_lookahead_direct_eval.py \
  --one-nn "$ONE_NN" --three-nn "$THREE_NN" \
  --output db/ai_search/oneturn_vs_threeturn_n10.json \
  --n-games 10 > logs/eval_direct.log 2>&1 &
DIRECT_PID=$!
echo "  PID=$DIRECT_PID"

echo ""
echo "3 並列起動完了、 完了予定:"
echo "  1-turn vs baseline (PID $ONE_PID): ~20-30 min"
echo "  3-turn vs baseline (PID $THREE_PID): ~3-5 時間"
echo "  1-turn vs 3-turn 直接対決 (PID $DIRECT_PID): ~3-5 時間"
echo ""
echo "進捗: tail -f logs/eval_oneturn_nn.log logs/eval_threeturn_nn.log logs/eval_direct.log"
