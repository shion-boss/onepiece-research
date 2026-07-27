#!/bin/bash
# 空きコアで beam-rollout を並列収集 (別 tag=beamP の別ファイルへ、 同一 policy/設定)。
# scale pipeline (beam) と同時書き込みを避けるため別ファイル。 train 前に cat で結合する。
set -u
cd /home/ohtsuki/projects/onepiece_research
export ONEPIECE_EIV1_RO_AI=beam ONEPIECE_EIV1_RO_TAG=beamP ONEPIECE_EIV1_RO_BW=4 ONEPIECE_EIV1_RO_BD=4
for b in $(seq 1 12); do
  echo "[$(date +%H:%M:%S)] parallel batch $b/12 開始 (beamP=$(wc -l < db/eiv1/rollout_corpus_beamP.jsonl 2>/dev/null || echo 0))"
  .venv/bin/python scripts/eiv1_rollout.py collect --games 150 --rollouts 6 --workers 8 2>&1 | tail -1
done
echo "[$(date +%H:%M:%S)] parallel collect 完了"
