"""32 件 の 「【相手のターン中】 」 実装漏れ カード に overlay 追加。

カテゴリ:
  A. passive static buff (on_attached_don + if opp_turn + power_pump)
  B. on_self_chara_ko + if opp_turn (= 自キャラ KO 時 reactive)
  C. 特殊 (replace_leave / on_opp_trigger_played 等)
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_PATH = ROOT / "db" / "card_effects.json"


# === Category A: passive opp_turn static buff ===

CAT_A: dict[str, dict] = {
    # EB04-001_p1 ボニー: コピー from EB04-001
    "EB04-001_p1": {
        "_text": "赤黄ボニー 相手ターン中 ライフ1以下: 自リーダー +2000",
        "when": "on_attached_don",
        "n": 0,
        "if": {"opp_turn": True, "self_life_le": 1},
        "do": [{"power_pump": {"target": "self_leader", "amount": 2000, "duration": "static"}}],
    },
    # EB04-010 ルルシア王国 (STAGE): 元コスト1キャラ全員 +5000
    "EB04-010": {
        "_text": "EB04-010 ルルシア王国 相手ターン中: 元コスト1キャラ全員 +5000",
        "when": "on_attached_don",
        "n": 0,
        "if": {"opp_turn": True},
        "do": [{
            "power_pump": {
                "target": {"type": "all_self_chara_filtered", "filter": {"original_cost_eq": 1}},
                "amount": 5000,
                "duration": "static",
            }
        }],
    },
    # EB03-041 孔雀: SWORD cost≤6 +2000
    "EB03-041": {
        "_text": "EB03-041 孔雀 相手ターン中: 自コスト6以下 SWORD キャラ全員 +2000",
        "when": "on_attached_don",
        "n": 0,
        "if": {"opp_turn": True},
        "do": [{
            "power_pump": {
                "target": {"type": "all_self_chara_filtered", "filter": {"cost_le": 6, "feature": "SWORD"}},
                "amount": 2000,
                "duration": "static",
            }
        }],
    },
    "EB03-041_p1": "alias:EB03-041",
    # EB02-003 チョッパー: 自身 +2000 (DON×2 条件)
    "EB02-003": {
        "_text": "EB02-003 チョッパー 相手ターン中 DON≥2: 自身 +2000",
        "when": "on_attached_don",
        "n": 0,
        "if": {"opp_turn": True, "self_attached_don_ge": 2},
        "do": [{"power_pump": {"target": "self", "amount": 2000, "duration": "static"}}],
    },
    "EB02-003_p1": "alias:EB02-003",
    # OP15-001 クリーク (LEADER): 自キャラが東の海オンリーなら opp_chara全員 -2000
    "OP15-001": {
        "_text": "OP15-001 クリーク 相手ターン中 DON≥1 自キャラ全 東の海 のみ: 相手キャラ全員 -2000",
        "when": "on_attached_don",
        "n": 0,
        "if": {
            "opp_turn": True,
            "self_don_active_ge": 1,
            "self_all_chara_feature": "東の海",
        },
        "do": [{
            "power_pump": {
                "target": "all_opp_characters",
                "amount": -2000,
                "duration": "static",
            }
        }],
    },
    "OP15-001_p1": "alias:OP15-001",
    # OP10-001 スモーカー (LEADER): 海軍/パンクハザード +1000
    "OP10-001": {
        "_text": "OP10-001 スモーカー 相手ターン中: 自海軍/パンクハザード キャラ +1000",
        "when": "on_attached_don",
        "n": 0,
        "if": {"opp_turn": True},
        "do": [{
            "power_pump": {
                "target": {"type": "all_self_chara_filtered", "filter": {"feature_in": ["海軍", "パンクハザード"]}},
                "amount": 1000,
                "duration": "static",
            }
        }],
    },
    "OP10-001_p1": "alias:OP10-001",
    # OP10-086 シリュウ: 自身 +2000
    "OP10-086": {
        "_text": "OP10-086 シリュウ 相手ターン中: 自身 +2000",
        "when": "on_attached_don",
        "n": 0,
        "if": {"opp_turn": True},
        "do": [{"power_pump": {"target": "self", "amount": 2000, "duration": "static"}}],
    },
    # ST19-004 ヒナ: 自身 cost +4 (DON≥1 条件)
    # cost buff は power_pump じゃない別 primitive 必要 だが、 簡略 で power_pump 代用 不可。
    # 公式: 「このキャラのコスト+4」 = 自キャラ コスト 増 (= 相手の cost_le 除去 対策)。
    # set_base_cost_timed があるが duration=static は別。 一旦 set_base_cost で 試す。
    "ST19-004": {
        "_text": "ST19-004 ヒナ 相手ターン中 DON≥1: 自身 コスト+4",
        "when": "on_attached_don",
        "n": 0,
        "if": {"opp_turn": True, "self_attached_don_ge": 1},
        "do": [{"set_base_cost_timed": {"target": "self", "amount": 4, "duration": "static", "relative": True}}],
    },
}


# === Category B: on_self_chara_ko + if opp_turn ===

CAT_B: dict[str, dict] = {
    # EB03-055 ロビン: 「1ダメージ」 = mill_opp_life_to_trash 1
    "EB03-055": {
        "_text": "EB03-055 ロビン 相手ターン中 自KO時: 相手に 1 ダメージ",
        "when": "on_self_chara_ko",
        "conditions": [{"opp_turn": True}, {"victim_iid_eq_self": True}],
        "do": [{"mill_opp_life_to_trash": 1}],
    },
    "EB03-055_p1": "alias:EB03-055",
    "EB03-055_p2": "alias:EB03-055",
    # OP12-107 ドフラ: デッキ→ライフ
    "OP12-107": {
        "_text": "OP12-107 ドフラ 相手ターン中 自KO時: 自デッキ上1枚→ライフ",
        "when": "on_self_chara_ko",
        "conditions": [{"opp_turn": True}, {"victim_iid_eq_self": True}],
        "do": [{"put_top_to_life": 1}],
    },
    # OP12-119 くま: デッキ→ライフ
    "OP12-119": {
        "_text": "OP12-119 くま 相手ターン中 自KO時: 自デッキ上1枚→ライフ",
        "when": "on_self_chara_ko",
        "conditions": [{"opp_turn": True}, {"victim_iid_eq_self": True}],
        "do": [{"put_top_to_life": 1}],
    },
    "OP12-119_p1": "alias:OP12-119",
    # OP14-115 リンドウ: デッキ→ライフ + 自身1ダメージ
    "OP14-115": {
        "_text": "OP14-115 リンドウ 相手ターン中 自KO時: 自デッキ→ライフ + 自身 1 ダメージ",
        "when": "on_self_chara_ko",
        "conditions": [{"opp_turn": True}, {"victim_iid_eq_self": True}],
        "do": [
            {"put_top_to_life": 1},
            {"mill_self_life_to_trash": 1},
        ],
    },
    # OP02-085 マゼラン: 相手 DON 2 デッキ戻し
    "OP02-085": {
        "_text": "OP02-085 マゼラン 相手ターン中 自KO時: 相手 DON 2 ドンデッキへ",
        "when": "on_self_chara_ko",
        "conditions": [{"opp_turn": True}, {"victim_iid_eq_self": True}],
        "do": [{"opp_don_to_deck": 2}],
    },
    "OP02-085_p1": "alias:OP02-085",
    "OP02-085_p2": "alias:OP02-085",
    # EB03-042 コアラ: 革命軍cost≤6 or ロビン 1枚 hand/trash から登場
    "EB03-042": {
        "_text": "EB03-042 コアラ 相手ターン中 自KO時: コアラ以外 革命軍cost6以下 or ロビン 1 枚 hand/trash から 登場",
        "when": "on_self_chara_ko",
        "conditions": [{"opp_turn": True}, {"victim_iid_eq_self": True}],
        "do": [{
            "play_from_hand_or_trash": {
                "filter": {
                    "exclude_name": "コアラ",
                    "or": [
                        {"feature": "革命軍", "cost_le": 6},
                        {"name": "ニコ・ロビン"},
                    ],
                },
                "count": 1,
            }
        }],
    },
    "EB03-042_p1": "alias:EB03-042",
    "EB03-042_p2": "alias:EB03-042",
    # OP08-071 ニワトリ伯爵: DON-1 → タマゴ男爵 デッキから登場
    "OP08-071": {
        "_text": "OP08-071 ニワトリ伯爵 相手ターン中 自KO時 [DON-1]: デッキから タマゴ男爵 cost4以下 1 枚 登場",
        "when": "on_self_chara_ko",
        "conditions": [{"opp_turn": True}, {"victim_iid_eq_self": True}],
        "cost": {"pay_don": 1},
        "do": [{
            "summon_from_deck": {
                "filter": {"name": "タマゴ男爵", "cost_le": 4},
                "count": 1,
            }
        }],
    },
    # OP08-073 ヒヨコ子爵: DON-1 → ニワトリ伯爵 デッキから登場
    "OP08-073": {
        "_text": "OP08-073 ヒヨコ子爵 相手ターン中 自KO時 [DON-1]: デッキから ニワトリ伯爵 cost6以下 1 枚 登場",
        "when": "on_self_chara_ko",
        "conditions": [{"opp_turn": True}, {"victim_iid_eq_self": True}],
        "cost": {"pay_don": 1},
        "do": [{
            "summon_from_deck": {
                "filter": {"name": "ニワトリ伯爵", "cost_le": 6},
                "count": 1,
            }
        }],
    },
}


# === Category C: 特殊 ===
# OP14-016 X・ドレーク: replace_leave with opp_turn + 超新星 + cost (self_leader -2000)
# OP13-106 コニー: on_opp_trigger_played → give_keyword self ブロッカー
# OP04-119 ロシナンテ: 自身レスト時 元コスト5自キャラ KO耐性 → 複雑
CAT_C: dict[str, dict] = {
    # OP13-106 コニー: 既存 on_opp_trigger_played が ないなら別途 engine 拡張 必要 → 一旦 skip
    # OP14-016 X・ドレーク: replace_leave with opp_turn (超新星のみ) → cost: self_leader -2000
    "OP14-016": {
        "_text": "OP14-016 X・ドレーク 相手ターン中 ターン1回: 超新星キャラ 効果 場離れ 代替 (cost: 自リーダー -2000 turn)",
        "when": "replace_leave",
        "if": {
            "opp_turn": True,
            "victim_feature_in": ["超新星"],
            "by_opp_effect": True,
        },
        "cost": [
            {"once_per_turn": True},
            {"power_pump": {"target": "self_leader", "amount": -2000, "duration": "turn"}},
        ],
        "do": [],  # 場離れ 代替 のみ (= victim survives)
    },
}


def main():
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))

    added = 0
    for cid, spec in {**CAT_A, **CAT_B, **CAT_C}.items():
        if isinstance(spec, str) and spec.startswith("alias:"):
            ref_cid = spec[len("alias:"):]
            if ref_cid not in overlay:
                print(f"  skip {cid}: ref {ref_cid} not found")
                continue
            ref_specs = [e for e in overlay[ref_cid] if isinstance(e, dict) and e.get("when") in ("on_attached_don", "on_self_chara_ko", "replace_leave")]
            # find the just-added entry by _text match
            new_entry = None
            for e in ref_specs:
                if "_text" in e and (cid.split("_p")[0] in e["_text"] or "alias" not in e["_text"]):
                    new_entry = dict(e)
                    break
            if new_entry is None and ref_specs:
                new_entry = dict(ref_specs[-1])
            if new_entry is None:
                print(f"  skip {cid}: no ref entry to alias")
                continue
            bundle = overlay.setdefault(cid, [])
            if not isinstance(bundle, list):
                continue
            bundle.append(new_entry)
            added += 1
            continue
        bundle = overlay.setdefault(cid, [])
        if not isinstance(bundle, list):
            continue
        # 同一 when + 同一 do の duplicate 検出 (= 既 追加済 skip、 別 effect は 追加)
        spec_when = spec.get("when")
        spec_text = spec.get("_text", "")
        already = any(
            isinstance(e, dict)
            and e.get("when") == spec_when
            and e.get("_text") == spec_text
            for e in bundle
        )
        if already:
            print(f"  skip {cid}: same _text already present")
            continue
        bundle.append(spec)
        added += 1
        print(f"  added {cid}: {spec.get('_text', '')[:60]}")

    OVERLAY_PATH.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTotal added: {added}")


if __name__ == "__main__":
    main()
