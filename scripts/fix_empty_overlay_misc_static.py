#!/usr/bin/env python3
"""empty_overlay の その他 静的 効果 を 補完。

対象:
- OP06-110 (+_p1,_p2,_p3,_r1): ドン×2 → このキャラはアクティブキャラにもアタックできる
- EB04-005: 相手元P5000+ キャラ 2 以上 「いない場合」 → このキャラはアタックできない (static)
- EB01-024: 自手札4以下 → 自《SMILE》全キャラ +1000 (static)
- OP04-099: 名前 alias (= 「シャーロット・リンリン」 として 扱う) → audit 既に intrinsic 認識済
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


ENTRIES: dict[str, list[dict]] = {
    # OP06-110: ドン×2 → アクティブキャラにもアタックできる
    "OP06-110": [
        {
            "_text": "[auto] ドン×2 → このキャラ アクティブキャラ アタック可 (static)",
            "when": "on_attached_don",
            "n": 2,
            "do": [{"give_attack_active_chara": "self"}],
        }
    ],
    # EB04-005 ナンバーズ:
    # 「相手の元々のパワー5000以上のキャラが2枚以上いない場合、 このキャラはアタックできない」
    # → 静的 set_cannot_attack_static + if opp_chara_filtered_count_le (count: 1)
    "EB04-005": [
        {
            "_text": "[auto] 相手元P5000+ キャラ 2 未満 → このキャラ アタック不可 (static)",
            "when": "on_attached_don",
            "n": 0,
            "if": {
                "opp_chara_filtered_count_le": {
                    "filter": {"power_ge": 5000},
                    "count": 1,
                }
            },
            "do": [{"set_cannot_attack_static": "self"}],
        }
    ],
    # EB01-024 シーザー:
    # 「自分の手札が4枚以下の場合、 自分の特徴《SMILE》を持つキャラすべては、 パワー+1000」
    "EB01-024": [
        {
            "_text": "[auto] 自手札4以下 → 自《SMILE》 キャラ全 +1000 (static)",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_hand_count_le": 4},
            "do": [
                {
                    "power_pump": {
                        "target": {
                            "type": "all_self_chara_filtered",
                            "filter": {"feature": "SMILE"},
                        },
                        "amount": 1000,
                        "duration": "static",
                    }
                }
            ],
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
        for suffix in ("_p1", "_p2", "_p3", "_r1", "_r2"):
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
    (ROOT / "db" / "fix_empty_misc_static_log.md").write_text(
        "# empty_overlay misc 静的 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
