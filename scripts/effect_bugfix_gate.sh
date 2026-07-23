#!/usr/bin/env bash
# effect-bugfix ルーティンの deterministic 安全 gate — 2026-07-24。
#
# 呼ぶ前提: LLM が「人間レビュー行き」skip / overlay _unimplemented を 1 件 修正 + unskip 済。
# この gate が **フル pytest green + _unimplemented 非増加** を確認し、 通れば commit+push、
# 通らなければ **全 revert** (壊れたコードは絶対 commit しない)。 = 完全自動でも安全な核。
#
#   bash scripts/effect_bugfix_gate.sh "コミットメッセージ"
#   exit 0 = commit+push 成功 / 2 = 変更なし(no-op) / 1 = 検証失敗で revert / 3 = push 失敗
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
PY="$ROOT/.venv/bin/python"
MSG="${1:-fix(engine): カード効果 人間レビュー行きバグ 自動修正 (auto)}"
BRANCH="feat/public-app-vscode-redesign"

# 変更が無ければ no-op
if git diff --quiet && [ -z "$(git status --porcelain --untracked-files=no)" ]; then
  echo "GATE: 変更なし → no-op"; exit 2
fi

# 不変条件1: _unimplemented を増やしていない (= 安易な再マークで green にする不正を防ぐ)。
# grep -c は 0 件でも "0" を出力し exit 1 する → || は付けない (付けると "0\n0" で比較が壊れる)。
before=$(git show HEAD:db/card_effects.json 2>/dev/null | grep -c "_unimplemented"); before=${before:-0}
after=$(grep -c "_unimplemented" db/card_effects.json); after=${after:-0}
if [ "$after" -gt "$before" ]; then
  echo "GATE: _unimplemented が増加 ($before → $after) → revert"; git checkout -- .; exit 1
fi

# 不変条件1b: 無条件 skip を増やしていない (= 失敗するテストを skip して green にする不正を防ぐ)。
# _unimplemented と同じ「安易に green にする」抜け穴の tests/ 側 (2026-07-24 追加)。
# mark.skip( のみ数える (skipif( = 条件付き data 依存 skip は正当なので除外、 "if(" 前置で不一致)。
sk_before=$( (git ls-tree -r HEAD --name-only tests/ 2>/dev/null | while read -r f; do
  case "$f" in *.py) git show "HEAD:$f" 2>/dev/null;; esac
done) | grep -c "mark\.skip(" ); sk_before=${sk_before:-0}
sk_after=$(cat tests/*.py 2>/dev/null | grep -c "mark\.skip("); sk_after=${sk_after:-0}
if [ "$sk_after" -gt "$sk_before" ]; then
  echo "GATE: 無条件 skip が増加 ($sk_before → $sk_after) = テストを skip して green にする不正 → revert"
  git checkout -- .; exit 1
fi

# 不変条件2: フル pytest が green
echo "GATE: フル pytest 実行中..."
if ! "$PY" -m pytest tests/ -q -p no:warnings; then
  echo "GATE: pytest 失敗 → 全 revert (壊さない)"; git checkout -- .; exit 1
fi

# 全 green → commit + robust push
echo "GATE: 全 green ($before → $after unimplemented) → commit+push"
git add -A
git commit -m "$MSG" || { echo "GATE: commit 対象なし"; exit 2; }
if git push origin "$BRANCH" 2>&1; then
  echo "GATE: push 成功 (origin)"; exit 0
fi
if [ -n "${GH_PUSH_TOKEN:-}" ] && \
   git push "https://x-access-token:${GH_PUSH_TOKEN}@github.com/shion-boss/onepiece-research.git" "$BRANCH" 2>&1; then
  echo "GATE: push 成功 (PAT)"; exit 0
fi
echo "GATE: push 失敗 (commit は済、 次回 push される)"; exit 3
