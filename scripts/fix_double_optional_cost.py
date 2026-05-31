#!/usr/bin/env python3
"""二重コスト bug 修復: top-level `cost` と do 内 `optional_cost_then` の cost 重複請求。

[[project_card_effect_100_plan_kickoff]] 順2 prototype で発見・runtime 実証:
  - OP14-096 (main) 公式 2 DON → 4 DON rest
  - OP13-026 / OP06-118_r2 (activate_main) も 同様 (条件成立時に do 内 oct が再請求)
両 when path (= _execute_event dispatch / fire_activate_main+resolve) で 二重化を確認。

修復方針 (= canonical sibling OP13-098 に合わせ top-level cost を残す):
  do 内 optional_cost_then を その .effect で 置換 (hoist)、 top-level cost を
  単一コストとして残す。 top-level cost path は human discard modal 対応あり。

安全境界 (= 機械修復する条件):
  - top-level cost が optional cost を 正規化後 ⊇ (= 同一コストの 純 二重請求)
  - do == [optional_cost_then] 単独 (= 他 primitive と混ざらない)
  - optional_cost_then.effect が 非空
個別例外:
  - EB02-025: oct.effect が do[1] の 誤複製 (search→hand) → oct を 丸ごと削除
  - OP07-058: top cost 不完全 (rest_self 欠落) → 補完してから hoist
保留 (= 公式テキスト個別検証が必要、 本修復では触らない):
  - top cost ≠ oct cost (異なるコスト): OP12-061* / OP06-06x* / OP04-111
  - oct.effect 空 (= missing impl): OP11-070*
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFF_PATH = ROOT / "db" / "card_effects.json"

REAL = {"rest_self_don", "discard_hand", "rest_self", "rest", "trash_self_hand_random",
        "pay_don", "return_self_don_to_deck", "return_self_don", "trash_self"}
SPECIAL_DROP = {"EB02-025"}          # oct.effect が誤複製
SPECIAL_COMPLETE = {"OP07-058"}      # top cost 補完が必要


def has_real(c) -> bool:
    if isinstance(c, dict):
        return any(k in REAL for k in c)
    if isinstance(c, list):
        return any(has_real(x) for x in c)
    return False


def canon(costobj) -> Counter:
    items = [costobj] if isinstance(costobj, dict) else (costobj if isinstance(costobj, list) else [])
    c: Counter = Counter()
    for it in items:
        if not isinstance(it, dict):
            continue
        for k, val in it.items():
            if k == "once_per_turn":
                continue
            n = 1 if isinstance(val, bool) else (int(val) if isinstance(val, int) else 1)
            if k == "rest_self_don":
                c["DON_rest"] += n
            elif k in ("pay_don", "return_self_don_to_deck", "return_self_don"):
                c["DON_remove"] += n
            elif k in ("discard_hand", "trash_self_hand_random"):
                c["hand_discard"] += n
            elif k == "rest_self" or (k == "rest" and val == "self"):
                c["rest_self"] += 1
            elif k == "trash_self":
                c["trash_self"] += 1
            else:
                c[f"other:{k}"] += 1
    return c


def classify(eff: dict):
    """各 target を (action, cid, ei, di) に分類して返す。"""
    targets = []
    for cid, v in eff.items():
        if cid == "_meta" or not isinstance(v, list):
            continue
        for ei, e in enumerate(v):
            if not isinstance(e, dict):
                continue
            top = e.get("cost")
            if not (isinstance(top, dict) and has_real(top)):
                continue
            do = e.get("do", [])
            for di, d in enumerate(do):
                if not (isinstance(d, dict) and "optional_cost_then" in d):
                    continue
                oct_ = d["optional_cost_then"]
                if not has_real(oct_.get("cost", [])):
                    continue
                effect = oct_.get("effect") or []
                if cid in SPECIAL_DROP:
                    targets.append(("DROP", cid, ei, di)); continue
                if not effect:
                    targets.append(("DEFER:empty-effect", cid, ei, di)); continue
                if cid in SPECIAL_COMPLETE:
                    targets.append(("COMPLETE+HOIST", cid, ei, di)); continue
                tc, occ = canon(top), canon(oct_.get("cost"))
                if any(occ[r] > tc.get(r, 0) for r in occ):
                    targets.append(("DEFER:diff-cost", cid, ei, di)); continue
                if len(do) != 1:
                    targets.append(("DEFER:multi-do", cid, ei, di)); continue
                targets.append(("HOIST", cid, ei, di))
    return targets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    eff = json.loads(EFF_PATH.read_text(encoding="utf-8"))
    targets = classify(eff)
    by_action = Counter(t[0] for t in targets)
    print("=== 分類 ===")
    for a, n in sorted(by_action.items()):
        print(f"  {a}: {n}")
    print("\n=== 保留 (要 個別 検証) ===")
    for a, cid, ei, di in targets:
        if a.startswith("DEFER"):
            print(f"  {a}: {cid} eff#{ei}")

    fix = [t for t in targets if t[0] in ("HOIST", "DROP", "COMPLETE+HOIST")]
    print(f"\n=== 機械修復 対象: {len(fix)} entry ===")
    if not args.apply:
        print("(dry-run。 --apply で適用)")
        return

    for action, cid, ei, di in fix:
        do = eff[cid][ei]["do"]
        oct_ = do[di]["optional_cost_then"]
        if action == "DROP":
            del do[di]
        elif action == "COMPLETE+HOIST":
            eff[cid][ei]["cost"] = {"discard_hand": 1, "rest_self": True}
            do[di:di + 1] = oct_.get("effect", [])
        else:  # HOIST
            do[di:di + 1] = oct_.get("effect", [])

    EFF_PATH.write_text(json.dumps(eff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"適用完了: {len(fix)} entry → {EFF_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
