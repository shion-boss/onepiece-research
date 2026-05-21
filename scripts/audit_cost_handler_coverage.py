#!/usr/bin/env python3
"""overlay 内 全 cost key を 集計、 engine の cost ハンドラ 分岐 と coverage 比較。

検出: overlay で 使われている cost key が engine の以下の分岐に 漏れていないか:
- engine/effects.py:_can_pay_activate_cost
- engine/effects.py:fire_activate_main
- engine/effects.py:apply_do_list の optional_cost_then 系
- engine/game.py で play_character / play_event 等の各 action 処理

Run: .venv/bin/python scripts/audit_cost_handler_coverage.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))
EFFECTS_PY = (ROOT / "engine" / "effects.py").read_text(encoding="utf-8")


def extract_cost_keys() -> dict[str, int]:
    """overlay 全体 で 使われている cost key を 出現数 付き で 集計。

    複数 階層 (cost / cost.<sub> / optional_cost_then.cost / replace_ko.cost / etc.) を 全部 拾う。
    """
    counts: dict[str, int] = {}

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "cost" and isinstance(v, dict):
                    for ck in v.keys():
                        counts[ck] = counts.get(ck, 0) + 1
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(OVERLAY)
    return counts


def find_handlers_in_function(fn_name: str, source: str) -> set[str]:
    """指定関数 内 で `cost.get("X")` / `cs.get("X")` / `cost["X"]` から X を 抽出。"""
    # 関数定義を切り出し
    m = re.search(rf"def {fn_name}\(.*?\n(.*?)(?=\n(?:def |class ))", source, re.DOTALL)
    if not m:
        return set()
    body = m.group(1)
    keys = set()
    for pat in [
        r'cost\.get\("([a-z_]+)"',
        r'cs\.get\("([a-z_]+)"',
        r'cost\["([a-z_]+)"\]',
        r'"([a-z_]+)" in cost',
        r'"([a-z_]+)" in cs',
        r'cost\.get\("([a-z_]+)",',
    ]:
        keys.update(re.findall(pat, body))
    return keys


def main():
    print("=== cost handler coverage audit ===")
    overlay_keys = extract_cost_keys()
    handler_can_pay = find_handlers_in_function("_can_pay_activate_cost", EFFECTS_PY)
    handler_fire = find_handlers_in_function("fire_activate_main", EFFECTS_PY)
    # apply_do_list 内 で 使われる optional_cost_then 系
    handler_opt = find_handlers_in_function("apply_do_list", EFFECTS_PY)

    # optional_cost_then 内 cs.get(...) は 別関数 (= optional_cost_then の execute_effect 内)。
    # まとめて 走査
    all_engine_keys = handler_can_pay | handler_fire | handler_opt
    # effects.py 全文から 補助検索 (= 他関数 で 使われていれば known)
    for pat in [
        r'cs\.get\("([a-z_]+)"',
        r'cost\.get\("([a-z_]+)"',
        r'"([a-z_]+)" in cost',
        r'"([a-z_]+)" in cs',
    ]:
        all_engine_keys.update(re.findall(pat, EFFECTS_PY))

    # 既知の non-cost フィールド (= cost dict の メタ情報) は 除外
    known_meta = {
        "once_per_turn",  # _act_used で 管理
        "once_per_game",
        # additional meta keys if any
    }

    # game.py も 軽く スキャン
    game_py = (ROOT / "engine" / "game.py").read_text(encoding="utf-8")
    for pat in [
        r'cost\.get\("([a-z_]+)"',
        r'"([a-z_]+)" in cost',
    ]:
        all_engine_keys.update(re.findall(pat, game_py))

    print(f"\nOverlay cost keys (= 出現数 付き):")
    for k, n in sorted(overlay_keys.items(), key=lambda x: -x[1]):
        in_engine = "✓" if (k in all_engine_keys or k in known_meta) else "✗"
        in_can_pay = "✓" if k in handler_can_pay else " "
        in_fire = "✓" if k in handler_fire else " "
        print(f"  [{in_engine}] {k:35s} n={n:5d}  can_pay={in_can_pay} fire={in_fire}")

    # 漏れ 検出
    missing = []
    only_can_pay = []
    only_fire = []
    for k, n in overlay_keys.items():
        if k in known_meta:
            continue
        if k not in all_engine_keys:
            missing.append((k, n))
        # 起動メイン cost で 使う もので、 can_pay / fire の どちらか だけ ある
        elif k in handler_can_pay and k not in handler_fire and k != "once_per_turn":
            only_can_pay.append((k, n))
        elif k in handler_fire and k not in handler_can_pay and k != "once_per_turn":
            only_fire.append((k, n))

    print()
    if missing:
        print(f"[CRITICAL] {len(missing)} cost key(s) overlay にあるが engine に 未実装:")
        for k, n in sorted(missing, key=lambda x: -x[1]):
            print(f"  {k} (n={n})")
    else:
        print("[OK] All overlay cost keys have engine handlers.")
    if only_can_pay:
        print(f"\n[WARN] {len(only_can_pay)} key only in _can_pay (not in fire_activate_main):")
        for k, n in only_can_pay:
            print(f"  {k} (n={n}) — pay 可能判定はあるが 実際の支払いが 抜け")
    if only_fire:
        print(f"\n[WARN] {len(only_fire)} key only in fire (not in _can_pay):")
        for k, n in only_fire:
            print(f"  {k} (n={n}) — 支払い処理はあるが 可能判定が 抜け (= 不可な ケース でも 発動可能?)")

    out_path = ROOT / "db" / "cost_handler_coverage.json"
    report = {
        "overlay_keys": overlay_keys,
        "engine_keys_all": sorted(all_engine_keys),
        "engine_can_pay": sorted(handler_can_pay),
        "engine_fire": sorted(handler_fire),
        "missing": [{"key": k, "n": n} for k, n in missing],
        "only_can_pay": [{"key": k, "n": n} for k, n in only_can_pay],
        "only_fire": [{"key": k, "n": n} for k, n in only_fire],
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote: {out_path}")
    return len(missing) + len(only_can_pay) + len(only_fire)


if __name__ == "__main__":
    raise SystemExit(main())
