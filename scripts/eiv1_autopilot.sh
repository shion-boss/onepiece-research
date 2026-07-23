#!/usr/bin/env bash
# EIV1 自律運転 v2 — 2026-07-24 深夜。 ohtsuki 離席中に「情報を増やす → 効くものだけ採用」。
#
# ⚠ v1 の gate は候補を「全 corpus 学習の配備 value」と比べていた = データ量と次元が同時に
# 変わる交絡 (der/don が 0.409 に見えた原因)。 v2 は eiv1_gate_candidate.py 側で
# **data-matched baseline** (同一 sample・同一容量・base 特徴のみ) を学習し candidate と
# 直接 arena する。 = feature の純効果。 採用は非回帰 (>0.5-margin) が条件。
#
# 段取り (各 group を独立に data-matched gate。 待機せず今ある行で測る = 新 field は degrade):
#   der,don  → eye → der,don,eye 合同
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
PY="$ROOT/.venv/bin/python"; LOG="$ROOT/db/eiv1/autopilot.log"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
LOCK="$ROOT/db/eiv1/.autopilot.lock"; exec 9>"$LOCK"
if ! flock -n 9; then echo "[$(date '+%F %T')] 別インスタンス → skip" >> "$LOG"; exit 0; fi
say() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }
SAMPLE="${SAMPLE:-140000}"; PAIRS="${PAIRS:-40}"; W="${W:-5}"

say "=== autopilot v2 開始 (data-matched gate) ==="

gate_group() {  # $1=group名 $2=block $3=max_keep $4=min_auc
  local g="$1" blk="$2" keep="$3" auc="$4"
  local cand="$ROOT/db/eiv1/feature_spec.${g//,/_}_candidate.json"
  rm -f "$cand"
  say "[$g] 関門1-2 探索 (block=$blk keep=$keep min_auc=$auc)"
  nice -n 12 "$PY" scripts/eiv1_feature_search.py --group "$g" \
    --card-block "$blk" --sample "$SAMPLE" --max-keep "$keep" --min-auc "$auc" >> "$LOG" 2>&1
  if [ -f "$cand" ]; then
    say "[$g] 関門2 通過 → data-matched arena gate"
    nice -n 12 "$PY" scripts/eiv1_gate_candidate.py "$cand" \
      --sample "$SAMPLE" --pairs "$PAIRS" --workers "$W" --accept >> "$LOG" 2>&1
  else
    say "[$g] 関門2 で棄却 (候補なし)"
  fi
}

gate_group "der,don" 64 40 0.0010
gate_group "eye"     96 40 0.0010
gate_group "der,don,eye" 128 50 0.0015

say "=== autopilot v2 完了 ==="
"$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json
from pathlib import Path
sp = Path("db/eiv1/feature_spec.json")
cols = json.loads(sp.read_text(encoding="utf-8")).get("columns", []) if sp.exists() else []
print(f"最終採用 spec: {len(cols)} 列")
lg = Path("db/eiv1/feature_search_log.jsonl")
if lg.exists():
    for line in list(open(lg, encoding="utf-8"))[-6:]:
        d = json.loads(line)
        if d.get("gate") == "arena":
            print(f"  gate {d.get('spec','')[-30:]}: {d.get('result')} win={d.get('win')}")
PYEOF
