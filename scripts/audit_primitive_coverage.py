#!/usr/bin/env python3
"""overlay 内 全 `do` primitive key を 集計、 engine の execute_effect 分岐 と coverage 比較。

検出: overlay で 使われている primitive key が engine に 未実装 か。

Run: .venv/bin/python scripts/audit_primitive_coverage.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))
EFFECTS_PY = (ROOT / "engine" / "effects.py").read_text(encoding="utf-8")


def extract_primitive_keys() -> dict[str, int]:
    """overlay 全体 で `do` 配列の各要素の キー を 集計。"""
    counts: dict[str, int] = {}

    def walk_do_list(do_list):
        if not isinstance(do_list, list):
            return
        for op in do_list:
            if not isinstance(op, dict):
                continue
            for k in op.keys():
                if k.startswith("_"):  # _chain, _comment 等 は除外
                    continue
                counts[k] = counts.get(k, 0) + 1
            # ネスト: optional_cost_then.effect, replace_ko_complex.branches[].do, etc.
            for sub_k, sub_v in op.items():
                if isinstance(sub_v, dict):
                    if "effect" in sub_v:
                        walk_do_list(sub_v["effect"])
                    if "do" in sub_v:
                        walk_do_list(sub_v["do"])
                    if "branches" in sub_v:
                        for br in sub_v.get("branches", []):
                            if isinstance(br, dict):
                                walk_do_list(br.get("do", []))

    def walk_overlay(node):
        if isinstance(node, dict):
            if "do" in node and isinstance(node["do"], list):
                walk_do_list(node["do"])
            if "then" in node and isinstance(node["then"], list):
                walk_do_list(node["then"])
            if "else" in node and isinstance(node["else"], list):
                walk_do_list(node["else"])
            for v in node.values():
                walk_overlay(v)
        elif isinstance(node, list):
            for x in node:
                walk_overlay(x)

    walk_overlay(OVERLAY)
    return counts


def find_handlers() -> set[str]:
    """engine/effects.py の primitive 検出 patterns:
    - `if/elif k == "X"` in execute_effect
    - `"X" in primitive` / `"X" in eff` (= 常在効果スキャン)
    - `primitive.get("X")` 等
    """
    keys = set()
    patterns = [
        r'(?:if|elif) k == "([a-z_]+)"',
        r'\bk == "([a-z_]+)"',  # alias forms (= elif k == "X" or k == "Y")
        r'"([a-z_]+)" in primitive',
        r'"([a-z_]+)" in eff',
        r'"([a-z_]+)" in prim\b',
        r'primitive\.get\("([a-z_]+)"',
        r'prim\.get\("([a-z_]+)"',
        r'eff\.get\("([a-z_]+)"',
        r'spec\.get\("([a-z_]+)"',
    ]
    for pat in patterns:
        keys.update(re.findall(pat, EFFECTS_PY))
    # 他 engine files も 走査
    for fname in ["game.py", "core.py"]:
        path = ROOT / "engine" / fname
        if path.exists():
            content = path.read_text(encoding="utf-8")
            for pat in patterns:
                keys.update(re.findall(pat, content))
    return keys


def main():
    print("=== primitive coverage audit ===")
    overlay_keys = extract_primitive_keys()
    handler_keys = find_handlers()

    missing = []
    print("\nOverlay primitive keys (= 出現数 付き):")
    for k, n in sorted(overlay_keys.items(), key=lambda x: -x[1]):
        in_engine = "✓" if k in handler_keys else "✗"
        print(f"  [{in_engine}] {k:40s} n={n:6d}")
        if k not in handler_keys:
            missing.append((k, n))

    print()
    if missing:
        print(f"[CRITICAL] {len(missing)} primitive(s) overlay にあるが engine に 未実装:")
        for k, n in sorted(missing, key=lambda x: -x[1]):
            print(f"  {k} (n={n})")
    else:
        print("[OK] All overlay primitive keys have engine handlers.")

    out_path = ROOT / "db" / "primitive_coverage.json"
    report = {
        "overlay_keys": overlay_keys,
        "engine_handlers": sorted(handler_keys),
        "missing": [{"key": k, "n": n} for k, n in missing],
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote: {out_path}")
    return len(missing)


if __name__ == "__main__":
    raise SystemExit(main())
