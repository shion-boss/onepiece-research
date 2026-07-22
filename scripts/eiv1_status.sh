#!/usr/bin/env bash
# EIV1 進捗の一覧表示 — 2026-07-24。 いつでも `bash scripts/eiv1_status.sh` で状態を確認。
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
D="$ROOT/db/eiv1"
PY="$ROOT/.venv/bin/python"

echo "===== EIV1 status ($(date '+%F %T')) ====="

# 1) いま走っているか
if pgrep -f "eiv1_collect.py" >/dev/null 2>&1; then
  echo "[実行状態] ● 収集中 (collect 稼働)"
elif [ -f "$D/.daily.lock" ] && command -v flock >/dev/null && ! (flock -n 9 9>"$D/.daily.lock"); then
  echo "[実行状態] ● 実行中 (lock 保持)"
else
  echo "[実行状態] ○ アイドル (次の :00/:30 発火待ち)"
fi

# 2) corpus 量
if [ -f "$D/corpus.jsonl" ]; then
  N=$(wc -l < "$D/corpus.jsonl"); SZ=$(du -h "$D/corpus.jsonl" | cut -f1)
  echo "[corpus]   $N samples ($SZ)"
else
  echo "[corpus]   まだ無し"
fi

# 3) 学習 (AUC 推移 = 天井なしの証拠)
if [ -f "$D/manifest.json" ]; then
  "$PY" - "$D/manifest.json" <<'PYEOF'
import json, sys
m = json.load(open(sys.argv[1]))
h = m.get("history", [])
print(f"[学習]     iter={m.get('train_iters')} 累計n={m.get('corpus_n')} dim={m.get('dim')}")
print( "[AUC推移]  (データ↑で単調に上がるか = 天井なしの証拠)")
for e in h[-10:]:
    a = e.get("auc"); a = f"{a:.4f}" if a is not None else "  -  "
    print(f"            iter{e['iter']:>3}  n={e['n']:>7}  AUC={a}")
PYEOF
else
  echo "[学習]     まだ学習前 (corpus n>=100 で発火)"
fi

# 4) 直近の run 履歴 (loop.log)
if [ -f "$D/loop.log" ]; then
  echo "[直近run]"
  grep -E "daily start|daily done|ERROR|skip" "$D/loop.log" | tail -4 | sed 's/^/            /'
fi

# 5) cron 登録
echo "[cron]     $(crontab -l 2>/dev/null | grep eiv1_daily | grep -v '^#' || echo '未登録')"
echo "==========================================="
echo "リアルタイム追跡: tail -f $D/loop.log"
