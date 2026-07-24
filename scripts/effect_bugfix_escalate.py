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


def _collect_approximations():
    """overlay の近似/未実装マーカー (_missing_effect / _approx_note / gap 系 _doc) を収集
    — 2026-07-24 追加。 `_unimplemented` とは別クラスで、 engine が効果を忠実表現できず近似
    (未対応/未実装/未配線/簡略) にしている箇所。 従来 escalate はこれを見ておらず放置されていた。
    engine 機構の新規実装が要るため human/engine レビュー行き。 base カードで dedup、
    「= 正確」 と注記された忠実マッピングは除外する。"""
    import re
    gap_re = re.compile(r"未対応|未実装|未配線|簡略")
    faithful_re = re.compile(r"=\s*正確")
    rows = []
    try:
        d = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    except Exception:
        return rows
    seen = set()

    def _walk(node, cid):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and k in ("_missing_effect", "_approx_note", "_doc"):
                    is_gap = (k in ("_missing_effect", "_approx_note")) or \
                             (bool(gap_re.search(v)) and not faithful_re.search(v))
                    if is_gap:
                        base = re.split(r"_(p|r|sp)\d", cid)[0]
                        if base not in seen:
                            seen.add(base)
                            rows.append((base, k, " ".join(v.split())))
                _walk(v, cid)
        elif isinstance(node, list):
            for v in node:
                _walk(v, cid)

    for cid, entry in d.items():
        if not isinstance(cid, str) or cid.startswith("_"):
            continue
        _walk(entry, cid)
    return sorted(rows)


def _render(skips, unimpl, approx) -> str:
    lines = [
        "# カード効果 人間レビュー待ちバックログ (自動生成)",
        "",
        "> `scripts/effect_bugfix_escalate.py` が `optcg-effect-bugfix` ルーティンの各実行末尾で再生成。",
        "> 自動修正ルーティンが直せなかった項目 (= 忠実な自動修正が困難で human の判断が要る) の一覧。",
        "> 空なら「レビュー待ちなし」。 消化するには session で私 (Claude) に「pending review やって」と伝えるか、",
        "> 各項目を手動修正 → skip 解除 / `_unimplemented` 実装 で対応する。",
        "",
        f"**合計: {len(skips) + len(unimpl) + len(approx)} 件** "
        f"(skip {len(skips)} / _unimplemented {len(unimpl)} / 近似・未実装 {len(approx)})",
        "",
    ]
    if not skips and not unimpl and not approx:
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
    if approx:
        lines += ["## overlay 近似・未実装マーカー (engine 機構が要る = engine/human レビュー)", "",
                  "> `_missing_effect` / `_approx_note` / gap 系 `_doc`。 効果を忠実表現できず近似",
                  "> している箇所 (多くは safely-incomplete = 誤動作せず no-op)。 新規 primitive/機構が要る。",
                  "",
                  "| card_id | marker | 診断 |", "|---|---|---|"]
        for cid, kind, diag in approx:
            d = diag if len(diag) <= 260 else diag[:257] + "..."
            lines.append(f"| {cid} | `{kind}` | {d} |")
        lines.append("")
    return "\n".join(lines)


def _git(*args):
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True)


def _auto_mechanical_fix(do_commit: bool):
    """escalate の前に、 engine が無視する primitive+param を同義の既存 primitive へ機械 swap する。
    = 「overlay が engine 未対応の primitive を使う」class を人間送りにせず自動修復 (2026-07-24)。
    `scripts/overlay_primitive_swap.py` の RULES を適用 → gate (フル pytest green) で検証+commit。
    do_commit=False (= 手動 regen) 時は検出報告のみ。 routine は --commit で回すので自動修復される。
    ⚠ 例外は握りつぶす (escalate 本体を止めない)。"""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from overlay_primitive_swap import scan_overlay
        overlay = ROOT / "db" / "card_effects.json"
        data = json.loads(overlay.read_text(encoding="utf-8"))
        hits = scan_overlay(data)   # in-place で data を修正 (適用は下の write で確定)
        if not hits:
            return
        n = sum(len(v) for v in hits.values())
        print(f"escalate: engine 無視 primitive を {n} 箇所検出 ({', '.join(sorted(hits))})")
        if not do_commit:
            print("escalate: (--commit 無し) 機械 swap は未適用。 "
                  "`.venv/bin/python scripts/overlay_primitive_swap.py --apply` で修正可")
            return
        # 元ファイルは json.dumps(ensure_ascii=False, indent=1) 末尾改行なし
        overlay.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("escalate: 機械 swap を適用 → gate (フル pytest) で検証")
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "effect_bugfix_gate.sh"),
             "fix(overlay): engine が無視する primitive を同義 primitive へ機械 swap (auto)"],
            cwd=str(ROOT))
        print(f"escalate: 機械 swap gate exit={r.returncode} "
              f"(0=commit+push / 1=非green revert / 2=no-op / 3=push失敗だがcommit済)")
    except Exception as e:  # noqa: BLE001
        print(f"escalate: 機械 swap skip (error: {e})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="変更あれば commit+robust push も行う")
    a = ap.parse_args()
    # まず機械的に直せる anti-pattern (engine 無視 primitive) を自動修復 → 人間送りを減らす
    _auto_mechanical_fix(a.commit)
    skips = _collect_skips()
    unimpl = _collect_unimplemented()
    approx = _collect_approximations()
    content = _render(skips, unimpl, approx)
    old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if content == old:
        print(f"escalate: 変更なし (skip {len(skips)} / _unimplemented {len(unimpl)} / 近似 {len(approx)})")
        return
    OUT.write_text(content, encoding="utf-8")
    print(f"escalate: db/_pending_review.md 更新 (skip {len(skips)} / _unimplemented {len(unimpl)} / 近似 {len(approx)})")
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
