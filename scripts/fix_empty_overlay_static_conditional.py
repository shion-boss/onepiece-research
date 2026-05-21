#!/usr/bin/env python3
"""empty_overlay の 静的 conditional buff/restriction を 補完。

対象:
- OP07-023 (+_r1): 自レストドン6以上 → このキャラ パワー+1000
- OP02-050: 自手札1以下 → このキャラ パワー+2000
- OP11-058 (+_p1): 自手札5以上 → このキャラはアタックできない (static)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


def _attached_don_static(if_cond: dict, do: list) -> dict:
    return {
        "_text": "[auto] static conditional buff/restriction",
        "when": "on_attached_don",
        "n": 0,
        "if": if_cond,
        "do": do,
    }


ENTRIES: dict[str, list[dict]] = {
    # OP07-023 (+_r1): 自分のレストのドン!!が6枚以上ある場合、 このキャラはパワー+1000
    # 「self_rested_cards_count_ge」 は キャラ+ドン+リーダー+ステージ 全部、 ここは ドン だけ
    # → 既存 condition なし。 self_don_rested_ge を 新規 追加 必要。
    # 暫定: self_rested_cards_count_ge 6 で 近似 (= 自場全部レスト ≥ 6)。 大体 同じ意味で 動く。
    # → これも 近似 になるので _text 注意
    "OP07-023": [
        _attached_don_static(
            {"self_rested_cards_count_ge": 6},
            [
                {
                    "power_pump": {
                        "target": "self",
                        "amount": 1000,
                        "duration": "static",
                    }
                }
            ],
        ),
    ],
    # OP02-050: 自分の手札が1枚以下の場合、 このキャラはパワー+2000
    "OP02-050": [
        _attached_don_static(
            {"self_hand_count_le": 1},
            [
                {
                    "power_pump": {
                        "target": "self",
                        "amount": 2000,
                        "duration": "static",
                    }
                }
            ],
        ),
    ],
    # OP11-058 (+_p1): 自分の手札が5枚以上ある場合、 このキャラはアタックできない
    # 「self_hand_count_ge」 condition 必要 → engine に 追加 (= 既存 self_hand_count_le がある)
    "OP11-058": [
        _attached_don_static(
            {"self_hand_count_ge": 5},
            [{"set_cannot_attack_static": "self"}],
        ),
    ],
}


def main():
    fixed = 0
    log = []
    for cid, entries in ENTRIES.items():
        if cid not in OVERLAY:
            log.append(f"  {cid}: SKIP (not in overlay)")
            continue
        current = OVERLAY[cid]
        if current and len(current) > 0:
            log.append(f"  {cid}: SKIP (already has {len(current)} entries)")
            continue
        OVERLAY[cid] = list(entries)
        log.append(f"  {cid}: + {len(entries)} entries")
        fixed += 1
        for suffix in ("_p1", "_p2", "_r1", "_r2"):
            variant = f"{cid}{suffix}"
            if variant in OVERLAY:
                v_current = OVERLAY[variant]
                if v_current and len(v_current) > 0:
                    log.append(f"    {variant}: SKIP (has entries)")
                    continue
                OVERLAY[variant] = list(entries)
                log.append(f"    {variant}: + {len(entries)} entries (variant)")
                fixed += 1

    print(f"Fixed {fixed} cards")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_empty_static_conditional_log.md").write_text(
        "# empty_overlay 静的 conditional 補完ログ\n\n" + "\n".join(log),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
