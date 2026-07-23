"""カード効果 人間レビュー待ちバックログの自動一覧化 (escalation) — 2026-07-24。

optcg-effect-bugfix ルーティンが自動修正できなかった (escape hatch / gate revert) 項目 =
skip されたテスト + overlay `_unimplemented` を走査し、 診断付きの人間可読 markdown
`db/_pending_review.md` を **再生成** する。 各実行末尾で呼び、 内容が変わっていれば commit+push。

= ohtsuki「結局こちらから依頼が要るなら意味ない」への回答: 難 case を黙って残すのでなく
**常に最新の一覧を repo に出す** → 人間は「覚えて依頼」でなく「ファイルを見て判断」で済む。

  .venv/bin/python scripts/effect_bugfix_escalate.py          # 再生成のみ
  .venv/bin/python scripts/effect_bugfix_escalate.py --commit # 変更あれば commit+push も
"""
from __future__ import annotations
import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "db" / "_pending_review.md"
BRANCH = "feat/public-app-vscode-redesign"
KEYWORDS = ("人間レビュー", "engine bug", "engine limitation", "engine leniency")


def _skip_reason(dec: ast.AST):
    """@pytest.mark.skip(reason=...) デコレータなら reason 文字列を返す (それ以外 None)。"""
    if not isinstance(dec, ast.Call):
        return None
    try:
        fn = ast.unparse(dec.func)
    except Exception:
        return None
    if "mark.skip" not in fn:
        return None
    for kw in dec.keywords:
        if kw.arg == "reason":
            try:
                return ast.literal_eval(kw.value)
            except Exception:
                try:
                    return ast.unparse(kw.value)
                except Exception:
                    return ""
    return ""  # skip だが reason 無し


def _collect_skips():
    rows = []
    for tf in sorted((ROOT / "tests").glob("*.py")):
        try:
            tree = ast.parse(tf.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                reason = _skip_reason(dec)
                if reason and any(k in reason for k in KEYWORDS):
                    diag = " ".join(reason.split())
                    rows.append((tf.name, node.name, diag))
    return rows


def _collect_unimplemented():
    rows = []
    try:
        d = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    except Exception:
        return rows
    for cid, entry in d.items():
        if not isinstance(cid, str) or cid.startswith("_"):
            continue
        txt = json.dumps(entry, ensure_ascii=False)
        if "_unimplemented" not in txt:
            continue
        # 最初の _unimplemented の説明を抜き出す
        diag = ""
        def _walk(x):
            nonlocal diag
            if diag:
                return
            if isinstance(x, dict):
                if "_unimplemented" in x and isinstance(x["_unimplemented"], str):
                    diag = " ".join(x["_unimplemented"].split())
                    return
                for v in x.values():
                    _walk(v)
            elif isinstance(x, list):
                for v in x:
                    _walk(v)
        _walk(entry)
        rows.append((cid, diag))
    return rows


def _render(skips, unimpl) -> str:
    lines = [
        "# カード効果 人間レビュー待ちバックログ (自動生成)",
        "",
        "> `scripts/effect_bugfix_escalate.py` が `optcg-effect-bugfix` ルーティンの各実行末尾で再生成。",
        "> 自動修正ルーティンが直せなかった項目 (= 忠実な自動修正が困難で human の判断が要る) の一覧。",
        "> 空なら「レビュー待ちなし」。 消化するには session で私 (Claude) に「pending review やって」と伝えるか、",
        "> 各項目を手動修正 → skip 解除 / `_unimplemented` 実装 で対応する。",
        "",
        f"**合計: {len(skips) + len(unimpl)} 件** (skip {len(skips)} / _unimplemented {len(unimpl)})",
        "",
    ]
    if not skips and not unimpl:
        lines += ["現在レビュー待ちなし ✅", ""]
        return "\n".join(lines)
    if skips:
        lines += ["## skip されているテスト (engine バグ等)", "",
                  "| テスト | ファイル | 診断 |", "|---|---|---|"]
        for fname, tname, diag in skips:
            d = diag if len(diag) <= 240 else diag[:237] + "..."
            lines.append(f"| `{tname}` | {fname} | {d} |")
        lines.append("")
    if unimpl:
        lines += ["## overlay `_unimplemented` (DSL 未対応)", "",
                  "| card_id | 診断 |", "|---|---|"]
        for cid, diag in unimpl:
            d = diag if len(diag) <= 300 else diag[:297] + "..."
            lines.append(f"| {cid} | {d} |")
        lines.append("")
    return "\n".join(lines)


def _git(*args):
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="変更あれば commit+robust push も行う")
    a = ap.parse_args()
    skips = _collect_skips()
    unimpl = _collect_unimplemented()
    content = _render(skips, unimpl)
    old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if content == old:
        print(f"escalate: 変更なし (skip {len(skips)} / _unimplemented {len(unimpl)})")
        return
    OUT.write_text(content, encoding="utf-8")
    print(f"escalate: db/_pending_review.md 更新 (skip {len(skips)} / _unimplemented {len(unimpl)})")
    if not a.commit:
        return
    _git("add", "db/_pending_review.md")
    r = _git("commit", "-m", "chore(ai): 人間レビュー待ちバックログ更新 (auto)")
    if r.returncode != 0:
        print("escalate: commit 対象なし / 失敗:", r.stdout.strip(), r.stderr.strip())
        return
    p = _git("push", "origin", BRANCH)
    if p.returncode == 0:
        print("escalate: push 成功 (origin)")
        return
    tok = os.environ.get("GH_PUSH_TOKEN")
    if tok:
        url = f"https://x-access-token:{tok}@github.com/shion-boss/onepiece-research.git"
        p2 = _git("push", url, BRANCH)
        if p2.returncode == 0:
            print("escalate: push 成功 (PAT)")
            return
    print("escalate: push 失敗 (commit は済、 次回再送)")


if __name__ == "__main__":
    main()
