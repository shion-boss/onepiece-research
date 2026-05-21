#!/usr/bin/env python3
"""empty_overlay の ko_immune 系を 静的 entry で 補完。

対象 (= mechanical な もの に 限定):
- ST05-008 (+_r1): 自場ドン8以上 → このキャラ battle_ko_immune
- OP06-052: ドン×1 + 自手札4以下 → このキャラ battle_ko_immune
- OP02-100: 自「フルボディ」あり → このキャラ battle_ko_immune
- OP09-045 (+_r1): 自「バギー」or「モージ」あり → このキャラ battle_ko_immune
- OP03-032: 属性《斬》とのバトルKO免疫 (= set_immune_attribute_in_battle)
- OP01-099: 自「黒炭せみ丸」以外《黒炭家》→ それら battle_ko_immune
- P-040: 相手場ドン10 → このキャラ ko_immune (= 全KO)

skip:
- OP14-003: source 元P5000以下 限定 (= 細粒度、 engine 拡張要)
- OP09-025: attacker=leader 限定 (= 細粒度、 engine 拡張要)
- OP06-012: opp 元P6000+ inplay 条件 (= 新 condition 要)
- OP06-109: 効果KO免疫 (= 新 primitive 要)
- OP08-029 / OP07-033 / OP07-069: 効果KO免疫 + filter (= 新 primitive 要)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


ENTRIES: dict[str, list[dict]] = {
    # ST05-008: 自場ドン8以上 → battle_ko_immune
    "ST05-008": [
        {
            "_text": "[auto] 自ドン8以上 → このキャラ バトルKO免疫 (static)",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_don_ge": 8},
            "do": [{"set_ko_immune_battle_only": True}],
        }
    ],
    # OP06-052: ドン×1 + 自手札4以下 → battle_ko_immune
    "OP06-052": [
        {
            "_text": "[auto] ドン×1 + 自手札4以下 → このキャラ バトルKO免疫 (static)",
            "when": "on_attached_don",
            "n": 1,
            "if": {"self_hand_count_le": 4},
            "do": [{"set_ko_immune_battle_only": True}],
        }
    ],
    # OP02-100: 自「フルボディ」あり → battle_ko_immune
    "OP02-100": [
        {
            "_text": "[auto] 自「フルボディ」あり → このキャラ バトルKO免疫 (static)",
            "when": "on_attached_don",
            "n": 0,
            "if": {
                "self_chara_filtered_count_ge": {
                    "filter": {"name": "フルボディ"},
                    "count": 1,
                }
            },
            "do": [{"set_ko_immune_battle_only": True}],
        }
    ],
    # OP09-045: 自「バギー」or「モージ」あり → battle_ko_immune
    "OP09-045": [
        {
            "_text": "[auto] 自「バギー」or「モージ」あり → このキャラ バトルKO免疫 (static)",
            "when": "on_attached_don",
            "n": 0,
            "if": {
                "self_chara_filtered_count_ge": {
                    "filter": {"name_in": ["バギー", "モージ"]},
                    "count": 1,
                }
            },
            "do": [{"set_ko_immune_battle_only": True}],
        }
    ],
    # OP03-032: 属性《斬》 とのバトルKO免疫
    "OP03-032": [
        {
            "_text": "[auto] 属性《斬》 とのバトルKO免疫 (static)",
            "when": "on_attached_don",
            "n": 0,
            "do": [
                {
                    "set_immune_attribute_in_battle": {
                        "target": "self",
                        "attributes": ["斬"],
                    }
                }
            ],
        }
    ],
    # OP01-099: 自「黒炭せみ丸」 以外 《黒炭家》 → battle_ko_immune
    "OP01-099": [
        {
            "_text": "[auto] 自「黒炭せみ丸」 以外 《黒炭家》 → バトルKO免疫 (static)",
            "when": "on_attached_don",
            "n": 0,
            "do": [
                {
                    "set_ko_immune_battle_only": {
                        "target": {
                            "type": "all_self_chara_filtered",
                            "filter": {
                                "feature": "黒炭家",
                                "exclude_name": "黒炭せみ丸",
                            },
                        }
                    }
                }
            ],
        }
    ],
    # P-040: 相手場ドン10 → このキャラ ko_immune (= 全KO)
    "P-040": [
        {
            "_text": "[auto] 相手場ドン10 → このキャラ KO免疫 (static)",
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_don_count_ge": 10},
            "do": [{"set_ko_immune": "self"}],
        }
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
    (ROOT / "db" / "fix_empty_ko_immune_log.md").write_text(
        "# empty_overlay ko_immune 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
