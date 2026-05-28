#!/usr/bin/env python3
"""Phase 3 oracle validator (= 2026-05-28、 docs/AUTO_AUDIT_SYSTEM.md Layer 3 後段)。

db/oracle_assertions.yaml の seed assertion を 機械的 突合:
- card scope     : 該当 card の overlay 値 が 期待 と 一致 する か
- rule scope     : engine の invariant が 宣言 されている か
- engine scope   : engine 実装 が 特定 動作 を 持つか

不一致 を db/oracle_validation_report.json に 出力 + auto_issues に 追加。
これ で Layer 1 (静的 lint) + Layer 2 (runtime) + Layer 3 (cardqa 由来) の 3 軸
audit が end-to-end で 動作 する 状態 へ。

実行:
  .venv/bin/python scripts/audit_oracle_validate.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# yaml は std 不要、 軽量 parser を 使う
try:
    import yaml  # type: ignore
except ImportError:
    print("ERROR: pyyaml が 必要 (= .venv/bin/pip install pyyaml)", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSERTIONS_PATH = REPO_ROOT / "db" / "oracle_assertions.yaml"
OVERLAY_PATH = REPO_ROOT / "db" / "card_effects.json"
INVARIANTS_MODULE = REPO_ROOT / "engine" / "audit_invariants.py"
OUT_PATH = REPO_ROOT / "db" / "oracle_validation_report.json"


def _check_card_assertion(a: dict, overlay: dict) -> tuple[bool, str]:
    """card scope assertion を 突合。"""
    cid = a.get("card_id")
    if not cid:
        return False, "card_id 未指定"
    entries = overlay.get(cid)
    if not isinstance(entries, list):
        return False, f"{cid} に overlay なし"
    assert_spec = a.get("assert", {})
    where = assert_spec.get("where", {})  # 例: {when: replace_ko}
    field = assert_spec.get("field")
    field_path = assert_spec.get("field_path")  # 例: "if.target_feature"
    expected = assert_spec.get("expected")
    contains_primitive = assert_spec.get("contains_primitive")
    contains_anywhere = assert_spec.get("contains_primitive_anywhere")

    # contains_primitive_anywhere は 全 entry 再帰 で 探す (= choice_effect 内 等 も 拾う)
    if contains_anywhere is not None:
        found = [False]
        def _walk(node):
            if found[0]:
                return
            if isinstance(node, dict):
                if contains_anywhere in node:
                    found[0] = True
                    return
                for v in node.values():
                    _walk(v)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)
        _walk(entries)
        if found[0]:
            return True, f"contains_primitive_anywhere {contains_anywhere} OK"
        return False, f"contains_primitive_anywhere {contains_anywhere} が overlay に なし"

    # entry filter
    matching = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        ok = True
        for wk, wv in where.items():
            if e.get(wk) != wv:
                ok = False
                break
        if ok:
            matching.append(e)

    if not matching:
        return False, f"where {where} match する entry なし"

    # field 突合
    for e in matching:
        if field:
            if e.get(field) == expected:
                return True, f"field {field}={expected} OK"
        elif field_path:
            # dotted path 解決
            node = e
            for seg in field_path.split("."):
                if isinstance(node, dict):
                    node = node.get(seg)
                else:
                    node = None
                    break
            if node == expected:
                return True, f"field_path {field_path}={expected} OK"
        elif contains_primitive:
            for prim in e.get("do", []) or []:
                if isinstance(prim, dict) and contains_primitive in prim:
                    return True, f"contains_primitive {contains_primitive} OK"
    if field:
        return False, f"field {field}={expected} 一致 する entry なし"
    if field_path:
        return False, f"field_path {field_path}={expected} 一致 する entry なし"
    if contains_primitive:
        return False, f"contains_primitive {contains_primitive} なし"
    return False, "assert 形式 認識 不可"


def _check_rule_assertion(a: dict) -> tuple[bool, str]:
    """rule scope: engine/audit_invariants.py に 該当 invariant が 宣言 されているか。"""
    assert_spec = a.get("assert", {})
    invariant = assert_spec.get("invariant")
    if not invariant:
        return False, "invariant 未指定"
    if not INVARIANTS_MODULE.exists():
        return False, "audit_invariants.py が ない"
    text = INVARIANTS_MODULE.read_text(encoding="utf-8")
    if invariant in text:
        return True, f"invariant {invariant} 宣言 済"
    return False, f"invariant {invariant} 宣言 が ない"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assertions", default=str(ASSERTIONS_PATH))
    args = ap.parse_args()

    apath = Path(args.assertions)
    if not apath.exists():
        print(f"ERROR: {apath} not found", file=sys.stderr)
        sys.exit(1)

    with apath.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    assertions = data.get("assertions", [])
    print(f"loaded {len(assertions)} assertions from {apath.name}")

    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))

    results = []
    passed = 0
    failed = 0
    for a in assertions:
        scope = a.get("scope")
        aid = a.get("id", "?")
        if scope == "card":
            ok, msg = _check_card_assertion(a, overlay)
        elif scope == "rule":
            ok, msg = _check_rule_assertion(a)
        else:
            ok, msg = False, f"unknown scope: {scope}"
        results.append({
            "id": aid,
            "scope": scope,
            "passed": ok,
            "message": msg,
            "card_id": a.get("card_id"),
            "source_q": a.get("source_q"),
            "source_a": a.get("source_a"),
            "suggested_fix": a.get("suggested_fix"),
        })
        sigil = "✓" if ok else "✗"
        print(f"  {sigil} {aid:40s} {msg}")
        if ok:
            passed += 1
        else:
            failed += 1

    report = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "summary": {
            "total": len(assertions),
            "passed": passed,
            "failed": failed,
        },
        "results": results,
    }
    OUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"passed: {passed} / {len(assertions)}")
    print(f"failed: {failed} / {len(assertions)}")
    print(f"output: {OUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
