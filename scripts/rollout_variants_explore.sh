#!/bin/bash
# rollout policy を「いろいろな視点」で複数作成 → panel⑬ に増やす (2026-07-25)。
# 現 scale pipeline (beam 4/4) の後に走らせ (過負荷回避)、 各 variant で小 proof corpus を集め
# train + arena(vs outcome) → record_rollout_result.py で results.json に追記 (⑬ 自動反映)。
# 視点: rollout policy の 強さ (深/浅) と 隠匿情報 (perfect-info 上限)。
set -u
cd /home/ohtsuki/projects/onepiece_research
PY=.venv/bin/python
GAMES="${VGAMES:-100}"; WORKERS="${VWORKERS:-5}"
log(){ echo "[$(date +%H:%M:%S)] $*"; }

# 1) 現 scale pipeline (rollout_scale_pipeline.sh) の完了を待つ (過負荷回避)
log "variant explorer: scale pipeline の完了待ち..."
for i in $(seq 1 480); do   # 最大 8h 安全網
  grep -q 'pipeline 完了' db/eiv1/rollout_scale/pipeline.log 2>/dev/null && { log "scale pipeline 完了検知"; break; }
  pgrep -f 'rollout_scale_pipeline.sh' >/dev/null 2>&1 || { log "scale pipeline プロセス消滅→続行"; break; }
  sleep 60
done

# 2) variant 定義: TAG|LABEL|RO_AI|BW|BD|NODET
VARIANTS=(
  "beam86|beam rollout 8/6 (深い読み)|beam|8|6|0"
  "beam22|beam rollout 2/2 (浅い読み)|beam|2|2|0"
  "beamPI|beam 4/4 perfect-info (determinize off=隠匿情報の上限)|beam|4|4|1"
)
for v in "${VARIANTS[@]}"; do
  IFS='|' read -r TAG LABEL RA BW BD NODET <<< "$v"
  log "=== variant $TAG collect (games=$GAMES, beam $BW/$BD, nodet=$NODET) ==="
  ONEPIECE_EIV1_RO_AI="$RA" ONEPIECE_EIV1_RO_TAG="$TAG" \
    ONEPIECE_EIV1_RO_BW="$BW" ONEPIECE_EIV1_RO_BD="$BD" ONEPIECE_EIV1_RO_NODET="$NODET" \
    $PY scripts/eiv1_rollout.py collect --games "$GAMES" --rollouts 6 --workers "$WORKERS" 2>&1 | tail -2
  CN=$(wc -l < "db/eiv1/rollout_corpus_${TAG}.jsonl" 2>/dev/null || echo 0)
  log "  train $TAG (corpus=$CN)"
  ONEPIECE_EIV1_RO_TAG="$TAG" $PY scripts/eiv1_rollout.py train 2>&1 | grep -E 'train:' | head -1
  log "  arena $TAG (vs outcome)"
  WIN=$($PY scripts/eiv1_arena.py --arm "db/eiv1/value_rollout_${TAG}.pkl" \
        --refs "db/eiv1/value_outcome_${TAG}.pkl" --pairs 40 --workers "$WORKERS" 2>&1 \
        | grep -oE '勝率 = [0-9.]+' | grep -oE '[0-9.]+' | head -1)
  WIN="${WIN:-0.5}"
  $PY scripts/record_rollout_result.py "$TAG" "$LABEL" "$WIN" 160 "$CN"
  log "=== variant $TAG 完了: arena vs outcome = $WIN ==="
done
log "=== 全 variant 完了 (panel⑬ に反映) ==="
