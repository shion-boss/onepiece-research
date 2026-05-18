#!/bin/bash
# Phase 2 cycle 2: snapshot 3000 試合 collection + ohtsuki さん handoff
# cycle 1 完了通知後 即起動 (= weight_nn_rl.pt が来た直後)
#
# 使い方:
#   ./scripts/phase2_cycle2_start.sh
#
# 前提:
#   - db/weight_nn_rl.pt 存在 (= cycle 1 学習結果、 ohtsuki さん が download 済)
#   - cycle 1 mirror eval で 効果確認済

cd /home/ohtsuki/projects/onepiece_research

if [ ! -f db/weight_nn_rl.pt ]; then
  echo "[ERROR] db/weight_nn_rl.pt 不在、 cycle 1 完了待ち"
  exit 1
fi

echo "=== Phase 2 cycle 2 起動 ==="
echo "  snapshot 3000 試合 (= cycle 1 の 3x)"
echo "  NN base = db/weight_nn_rl.pt (= cycle 1 学習済)"
echo "  ETA ~2.5-3 時間 (= 8 worker)"

# cycle 2 snapshot collection (= weight_nn_rl.pt を base に self-play)
ONEPIECE_WEIGHT_NN_PATH=db/weight_nn_rl.pt \
nohup .venv/bin/python scripts/collect_twoturn_snapshots.py \
  --n-games 3000 --workers 8 \
  --nn-path db/weight_nn_rl.pt \
  --output db/twoturn_snapshots_cycle2.jsonl > logs/twoturn_snapshots_cycle2.log 2>&1 &

P=$!
echo "  cycle 2 collection PID=$P, ETA ~2.5-3 時間"
echo "  完了通知 → ohtsuki さん handoff (Drive アップロード + Colab で REINFORCE 学習)"
echo $P > /tmp/cycle2.pid
