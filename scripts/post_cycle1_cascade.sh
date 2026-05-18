#!/bin/bash
# Phase 2 cycle 1 完了後 (= db/weight_nn_rl.pt 到着後) の cascade 起動。
# 1 つの script で 全 検証 + cycle 2 起動を 並列実行。
#
# 使い方:
#   ./scripts/post_cycle1_cascade.sh
#
# 並行で:
#   1. Phase 2 cycle 1 学習結果 = mirror eval (= weight_nn_rl)
#   2. Step 5 belief NN 効果検証
#   3. AdaptiveCombo mirror eval (= +α 期待)
#   4. ComboAware mirror eval (= 紫エネル での効果)
#   5. Phase 2 cycle 2 snapshot collection 起動 (= 重い、 background)
#   6. Plan D snapshot collection 起動 (= 重い、 background)

cd /home/ohtsuki/projects/onepiece_research

if [ ! -f db/weight_nn_rl.pt ]; then
  echo "[ERROR] db/weight_nn_rl.pt 不在、 cycle 1 完了待ち"
  exit 1
fi

mkdir -p db/ai_search logs

# === 並列起動 (= 全部 background) ===
echo "[1/6] Phase 2 cycle 1 mirror eval (WeightNNTwoTurnAI vs baseline)"
ONEPIECE_WEIGHT_NN_PATH=db/weight_nn_rl.pt \
nohup .venv/bin/python scripts/run_ai_mirror_eval.py \
  --ai-class engine.ai_experimental.WeightNNTwoTurnAI \
  --ai-kwargs '{}' \
  --output db/ai_search/WeightNNTwoTurn_rl_iter1_n10.json \
  --n-games 10 --label cycle1_weightnn_2t > logs/cascade1_weightnn_2t.log 2>&1 &
echo "  PID=$!"

echo "[2/6] Step 5 belief NN 効果検証 (belief OFF vs ON)"
nohup ./scripts/eval_step5_belief_effect.sh > logs/cascade2_belief.log 2>&1 &
echo "  PID=$!"

echo "[3/6] AdaptiveCombo mirror eval"
nohup .venv/bin/python scripts/run_ai_mirror_eval.py \
  --ai-class engine.ai_experimental.AdaptiveComboAI \
  --ai-kwargs '{}' \
  --output db/ai_search/AdaptiveCombo_n10.json \
  --n-games 10 --label adaptive_combo > logs/cascade3_adaptive_combo.log 2>&1 &
echo "  PID=$!"

echo "[4/6] ComboAware mirror eval"
nohup .venv/bin/python scripts/run_ai_mirror_eval.py \
  --ai-class engine.ai_experimental.ComboAwarePlanningAI \
  --ai-kwargs '{}' \
  --output db/ai_search/ComboAware_n10.json \
  --n-games 10 --label combo_aware > logs/cascade4_combo_aware.log 2>&1 &
echo "  PID=$!"

echo "[5/6] Phase 2 cycle 2 snapshot collection 起動 (= 重い、 ETA 2-3h)"
ONEPIECE_WEIGHT_NN_PATH=db/weight_nn_rl.pt \
nohup .venv/bin/python scripts/collect_twoturn_snapshots.py \
  --n-games 3000 --workers 6 \
  --nn-path db/weight_nn_rl.pt \
  --output db/twoturn_snapshots_cycle2.jsonl > logs/cascade5_cycle2.log 2>&1 &
echo "  PID=$!"

echo "[6/6] Plan D MCTS rollout snapshot collection 起動 (= 重い、 ETA 1-2h)"
nohup .venv/bin/python scripts/collect_mcts_rollout_snapshots.py \
  --n-games 500 --workers 2 \
  --rollouts-per-state 10 --max-rollout-turns 6 \
  --output db/mcts_rollout_snapshots.jsonl > logs/cascade6_plan_d.log 2>&1 &
echo "  PID=$!"

echo ""
echo "全 6 task 並列起動完了 (= total 16 cores 占用、 完了予定):"
echo "  [1-4] 軽量 mirror eval = 30 分 〜 1 時間"
echo "  [5] Phase 2 cycle 2 snapshot = 2-3 時間"
echo "  [6] Plan D snapshot = 1-2 時間"
echo "  → 全完了 ~3-4 時間後 (= ohtsuki さん次の Colab 依頼)"
