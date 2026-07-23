#!/usr/bin/env bash
# EIV1 自律運転 — 2026-07-24 深夜。 ohtsuki 離席中に「情報を増やす → 効くものだけ採用」を回す。
#
# 段取り:
#   Stage 1  既に関門2を通っている der/don 25 列を arena gate (関門3) にかけ、 通れば採用
#   Stage 2  攻防履歴つきの新しい corpus 行が十分貯まるまで待つ (日次ループが生成)
#   Stage 3  eyes 191 列 (今夜追加した「目」) を 3 段ゲートに通し、 通れば採用
#   Stage 4  細分化+DON+eyes をまとめて再探索 (相互作用を拾う)
#
# 安全性: 採用は arena (ε=0、 現 value と直接対戦) で **回帰していない** ことが条件。
# AUC だけでは採用しない (本日 3 回「AUC↑・強さ不変」を実測したため)。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
LOG="$ROOT/db/eiv1/autopilot.log"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

LOCK="$ROOT/db/eiv1/.autopilot.lock"
exec 9>"$LOCK"
if ! flock -n 9; then echo "[$(date '+%F %T')] 別インスタンス実行中 → skip" >> "$LOG"; exit 0; fi

say() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

say "=== autopilot 開始 ==="

# --- Stage 1: der/don 候補を arena gate ---
if [ -f "$ROOT/db/eiv1/feature_spec.der_don_candidate.json" ]; then
  say "Stage 1: der/don 25 列を arena gate へ"
  nice -n 12 "$PY" scripts/eiv1_gate_candidate.py \
    db/eiv1/feature_spec.der_don_candidate.json \
    --sample 200000 --pairs 40 --workers 5 --accept >> "$LOG" 2>&1
  say "Stage 1 完了"
fi

# --- Stage 2: 攻防履歴つきの行が貯まるのを待つ ---
NEED="${NEED_FRESH:-90000}"
say "Stage 2: battle_stats を持つ行が $NEED 行貯まるまで待機"
for _ in $(seq 1 96); do          # 最大 8 時間 (5 分 × 96)
  FRESH=$("$PY" - <<'PYEOF'
import json
n = 0
try:
    with open("db/eiv1/corpus.jsonl", encoding="utf-8") as f:
        lines = f.readlines()[-200000:]
    for line in reversed(lines):
        try:
            if "battle_stats" in (json.loads(line).get("state") or {}):
                n += 1
            else:
                break
        except Exception:
            break
except Exception:
    pass
print(n)
PYEOF
)
  say "  新形式の行: $FRESH / $NEED"
  [ "${FRESH:-0}" -ge "$NEED" ] && break
  sleep 300
done

# --- Stage 3: eyes を 3 段ゲート ---
say "Stage 3: eyes 191 列を探索 (関門1-2)"
nice -n 12 "$PY" scripts/eiv1_feature_search.py --group eye \
  --card-block 96 --sample "$NEED" --max-keep 40 --min-auc 0.0010 >> "$LOG" 2>&1
if [ -f "$ROOT/db/eiv1/feature_spec.eye_candidate.json" ]; then
  say "Stage 3: 関門2 通過 → arena gate へ"
  nice -n 12 "$PY" scripts/eiv1_gate_candidate.py \
    db/eiv1/feature_spec.eye_candidate.json \
    --sample "$NEED" --pairs 40 --workers 5 --accept >> "$LOG" 2>&1
else
  say "Stage 3: 関門2 で棄却 (候補なし)"
fi

# --- Stage 4: 全ブロックまとめて再探索 (相互作用を拾う) ---
say "Stage 4: der,don,eye をまとめて再探索"
nice -n 12 "$PY" scripts/eiv1_feature_search.py --group der,don,eye \
  --card-block 128 --sample "$NEED" --max-keep 50 --min-auc 0.0015 >> "$LOG" 2>&1
if [ -f "$ROOT/db/eiv1/feature_spec.der_don_eye_candidate.json" ]; then
  nice -n 12 "$PY" scripts/eiv1_gate_candidate.py \
    db/eiv1/feature_spec.der_don_eye_candidate.json \
    --sample "$NEED" --pairs 40 --workers 5 --accept >> "$LOG" 2>&1
fi

say "=== autopilot 完了 ==="
"$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json
from pathlib import Path
p = Path("db/eiv1/feature_spec.json")
spec = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"columns": []}
print(f"最終 spec: {len(spec.get('columns') or [])} 列 採用")
a = Path("db/eiv1/arena.jsonl")
if a.exists():
    for line in list(open(a, encoding="utf-8"))[-4:]:
        d = json.loads(line)
        print(f"  arena iter{d.get('iter')} vs {str(d.get('ref'))[:24]} "
              f"勝率={d.get('win')} N={d.get('n_games')}")
PYEOF
