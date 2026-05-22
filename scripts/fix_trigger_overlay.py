"""trigger 効果 が cards.json の trigger field に あるが overlay に when='trigger' エントリ
が 無い カード を 自動 修正。

パターン:
  A. 「このカードを登場させる」 → {"play_self": true}
  B. 条件付き登場 (= leader feature / life condition) → {"play_self": true} + if
  C. 「ドン!!デッキからドン!!1枚 アクティブ追加」 → {"add_don": 1}
  D. 「このカードの【メイン】効果を発動」 → {"fire_self_main": true}
  E. 「カード2枚を引き、手札1枚捨てる」 → {"draw": 2} + discard
  F. その他 (= 手動 必要)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "db" / "cards.json"
OVERLAY_PATH = ROOT / "db" / "card_effects.json"


def parse_trigger(trigger_text: str) -> list[dict] | None:
    """trigger テキスト を 解析 して overlay spec を 返す。 未対応 なら None。"""
    t = trigger_text
    # 除去: 「【トリガー】」 prefix
    t = re.sub(r"^【トリガー】\s*", "", t)
    t = t.strip()

    # A. このカードを登場させる
    if t == "このカードを登場させる。":
        return [{
            "_text": f"trigger: 自身登場 (play_self)",
            "when": "trigger",
            "do": [{"play_self": True}],
        }]

    # A'. 自分の手札N枚捨てることができる：このカードを登場させる。
    m = re.match(r"^自分の手札(\d+)枚を捨てることができる:?：このカードを登場させる。$", t)
    if m:
        n = int(m.group(1))
        return [{
            "_text": f"trigger: 手札{n}捨て → 自身登場",
            "when": "trigger",
            "do": [{
                "optional_cost_then": {
                    "cost": [{"trash_self_hand_random": n}],
                    "effect": [{"play_self": True}],
                }
            }],
        }]

    # B. 条件付き登場 — leader feature
    m = re.match(r"^自分のリーダーが特徴《(.+?)》を持(?:つ|ち)(.*)、このカードを登場させる。$", t)
    if m:
        feat, extra = m.group(1), m.group(2)
        conds: dict = {"leader_feature": feat}
        # extra に life 条件 等 が ある
        life_m = re.search(r"お互いのライフの合計枚数が(\d+)枚以下", extra)
        if life_m:
            conds["total_life_le"] = int(life_m.group(1))
        own_life_m = re.search(r"自分のライフが(\d+)枚以下", extra)
        if own_life_m:
            conds["self_life_le"] = int(own_life_m.group(1))
        return [{
            "_text": f"trigger: 条件 ({conds}) で 自身登場",
            "when": "trigger",
            "if": conds,
            "do": [{"play_self": True}],
        }]

    # B'. 自分のリーダーが「<name>」 の場合 登場
    m = re.match(r"^自分のリーダーが「(.+?)」の場合、このカードを登場させる。$", t)
    if m:
        name = m.group(1)
        return [{
            "_text": f"trigger: リーダー {name} で 自身登場",
            "when": "trigger",
            "if": {"leader_name": name},
            "do": [{"play_self": True}],
        }]

    # B''. ライフ条件のみ
    m = re.match(r"^自分のライフが(\d+)枚以下の場合、このカードを登場させる。$", t)
    if m:
        return [{
            "_text": f"trigger: 自ライフ≤{m.group(1)} で 自身登場",
            "when": "trigger",
            "if": {"self_life_le": int(m.group(1))},
            "do": [{"play_self": True}],
        }]
    m = re.match(r"^相手のライフが(\d+)枚以下の場合、このカードを登場させる。$", t)
    if m:
        return [{
            "_text": f"trigger: 相手ライフ≤{m.group(1)} で 自身登場",
            "when": "trigger",
            "if": {"opp_life_le": int(m.group(1))},
            "do": [{"play_self": True}],
        }]

    # C. ドン!!デッキから 1 アクティブ 追加
    if re.match(r"^ドン[!‼][!‼]?デッキからドン[!‼][!‼]?1枚までを、アクティブで追加する。$", t):
        return [{
            "_text": f"trigger: ドン1 アクティブ 追加",
            "when": "trigger",
            "do": [{"add_don": 1}],
        }]

    # D. このカードの【メイン】効果を発動する
    if t == "このカードの【メイン】効果を発動する。":
        return [{
            "_text": f"trigger: 自身の【メイン】効果 発動",
            "when": "trigger",
            "do": [{"fire_self_main": True}],
        }]

    # E. カード2枚を引き、自分の手札1枚を捨てる
    m = re.match(r"^カード(\d+)枚を引き、自分の手札(\d+)枚を捨てる。$", t)
    if m:
        n_draw, n_discard = int(m.group(1)), int(m.group(2))
        return [{
            "_text": f"trigger: {n_draw}ドロー + 手札{n_discard}捨て",
            "when": "trigger",
            "do": [
                {"draw": n_draw},
                {"trash_self_hand_random": n_discard},
            ],
        }]

    # F. カードN枚を引く (= 単純 draw)
    m = re.match(r"^カード(\d+)枚を引く。$", t)
    if m:
        n = int(m.group(1))
        return [{
            "_text": f"trigger: {n}ドロー",
            "when": "trigger",
            "do": [{"draw": n}],
        }]

    # G. 相手のコストN以下のキャラ1枚までを、 レストにする
    m = re.match(r"^相手のコスト(\d+)以下のキャラ1枚までを、レストにする。$", t)
    if m:
        n = int(m.group(1))
        return [{
            "_text": f"trigger: 相手 cost≤{n} キャラ 1 レスト",
            "when": "trigger",
            "do": [{
                "rest": {"type": "one_opp_chara_filtered", "filter": {"cost_le": n}}
            }],
        }]

    # G'. ライフ条件付き レスト
    m = re.match(r"^自分のライフが(\d+)枚以下の場合、相手のコスト(\d+)以下のキャラ1枚までを、レストにする。$", t)
    if m:
        life, cost = int(m.group(1)), int(m.group(2))
        return [{
            "_text": f"trigger: 自ライフ≤{life} で 相手 cost≤{cost} キャラ 1 レスト",
            "when": "trigger",
            "if": {"self_life_le": life},
            "do": [{
                "rest": {"type": "one_opp_chara_filtered", "filter": {"cost_le": cost}}
            }],
        }]

    # H. 相手のコストN以下のキャラ1枚までを、 KOする
    m = re.match(r"^相手のコスト(\d+)以下のキャラ1枚までを、KOする。$", t)
    if m:
        n = int(m.group(1))
        return [{
            "_text": f"trigger: 相手 cost≤{n} キャラ 1 KO",
            "when": "trigger",
            "do": [{
                "ko": {"type": "one_opp_chara_filtered", "filter": {"cost_le": n}}
            }],
        }]

    # H'. KO + 自身を手札に加える
    m = re.match(r"^相手のコスト(\d+)以下のキャラ1枚までを、KOし、このカードを手札に加える。$", t)
    if m:
        n = int(m.group(1))
        return [{
            "_text": f"trigger: 相手 cost≤{n} キャラ 1 KO + 自身手札へ",
            "when": "trigger",
            "do": [
                {"ko": {"type": "one_opp_chara_filtered", "filter": {"cost_le": n}}},
                {"play_self": False},  # 「手札に加える」 = play_self しない (= default 手札へ)
            ],
        }]

    # I. 相手のリーダーかキャラ1枚までを、 このターン中、 パワー-N
    m = re.match(r"^相手のリーダーかキャラ1枚までを、このターン中、パワー(-?\d+)。$", t)
    if m:
        amount = int(m.group(1))
        return [{
            "_text": f"trigger: 相手リーダー or キャラ 1 power{amount} turn",
            "when": "trigger",
            "do": [{
                "power_pump": {
                    "target": "one_opp_character_any",
                    "amount": amount,
                    "duration": "turn",
                }
            }],
        }]

    # J. ドン!!-N (cost) → このカードを登場させる
    m = re.match(r"^ドン[!‼][!‼]?\s*[-－]\s*(\d+).*?[:：]\s*このカードを登場させる。$", t)
    if m:
        n = int(m.group(1))
        return [{
            "_text": f"trigger: DON-{n} で 自身登場",
            "when": "trigger",
            "do": [{
                "optional_cost_then": {
                    "cost": [{"pay_don": n}],
                    "effect": [{"play_self": True}],
                }
            }],
        }]

    # K. 自分のライフの上か下から1枚をトラッシュに置くことができる：このカードを登場させる。
    if re.match(r"^自分のライフの上か下から1枚をトラッシュに置くことができる:?：このカードを登場させる。$", t):
        return [{
            "_text": f"trigger: 自ライフ1捨て で 自身登場",
            "when": "trigger",
            "do": [{
                "optional_cost_then": {
                    "cost": [{"mill_self_life_to_trash": 1}],
                    "effect": [{"play_self": True}],
                }
            }],
        }]

    return None


def main():
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))

    fixed = 0
    skipped: list[tuple[str, str, str]] = []
    for c in cards:
        cid = c["card_id"]
        tt = c.get("trigger") or ""
        if not tt:
            continue
        effs = overlay.get(cid, [])
        if isinstance(effs, list) and any(
            isinstance(e, dict) and e.get("when") == "trigger" for e in effs
        ):
            continue
        spec = parse_trigger(tt)
        if spec is None:
            skipped.append((cid, c.get("name", "?"), tt[:80]))
            continue
        bundle = overlay.setdefault(cid, [])
        if not isinstance(bundle, list):
            continue
        bundle.extend(spec)
        fixed += 1

    OVERLAY_PATH.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Auto-fixed: {fixed}")
    print(f"Skipped (= manual): {len(skipped)}")
    print()
    print("Skipped 一覧 (= 残 manual case):")
    for cid, name, tt in skipped[:30]:
        print(f"  {cid} {name[:18]} | {tt}")
    if len(skipped) > 30:
        print(f"  ... 他 {len(skipped)-30} 件")


if __name__ == "__main__":
    main()
