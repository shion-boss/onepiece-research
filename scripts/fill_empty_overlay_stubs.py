#!/usr/bin/env python3
"""空の overlay に 公式テキストから 確実に identify できる パターン を 自動補完。

保守的方針: 不確実なケースは 触らない (= 過剰補正 を 避ける)。

対象パターン:
  P1: "このキャラは相手の効果でKOされない" → set_ko_immune self
  P2: "このキャラはターンに1回、相手の効果でKOされない" → set_ko_immune self once_per_turn
  P3: "【自分のターン中】このキャラのパワー+N" → static power_pump self with if self_turn
  P4: "【相手のターン中】このキャラのパワー+N" → static power_pump self with if opp_turn
  P5: 単純な leader 条件付き パワー: "自分のリーダーが特徴《X》を持つ場合、 このキャラのパワー+N"
      → static power_pump self with if leader_feature
  P6: "自分の「X」がいる場合、 このキャラのパワー+N" → 未実装 (= named char ref)

注: 既存の overlay に entry がある カードは スキップ。
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))
CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}


def normalize_don(text: str) -> str:
    return text.replace("‼", "!!").replace("！", "!")


def get_text(cid: str) -> str:
    text = (CARDS.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARDS.get(base, {}).get("text") or "").strip()
    return text


def generate_entries(text: str) -> list[dict]:
    """テキストから entries を 自動生成。 該当なし は []。"""
    entries = []
    t = normalize_don(text)

    # P1: 「このキャラは相手の効果でKOされない」 (= 永続)
    if re.search(r"このキャラは相手の効果でKOされない", t):
        entries.append({
            "_text": "[auto] このキャラは相手の効果でKOされない (= passive immunity)",
            "when": "on_attached_don",
            "n": 0,
            "do": [{"set_ko_immune": "self"}],
        })

    # P2: 「このキャラはターンに1回、相手の効果でKOされない」
    if re.search(r"このキャラはターンに1回、相手の効果でKOされない", t):
        entries.append({
            "_text": "[auto] このキャラはターンに1回、相手の効果でKOされない",
            "when": "on_attached_don",
            "n": 0,
            "do": [{"set_ko_immune": "self"}],
            "cost": {"once_per_turn": True},
        })

    # P3: 「【自分のターン中】 ... このキャラのパワー+N」
    m = re.search(r"【自分のターン中】.{0,40}このキャラのパワー\+(\d+)", t)
    if m:
        n = int(m.group(1))
        entries.append({
            "_text": f"[auto] 【自分のターン中】このキャラのパワー+{n}",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_turn": True},
            "do": [{"power_pump": {"target": "self", "amount": n, "duration": "static"}}],
        })

    # P4: 「【相手のターン中】 ... このキャラのパワー+N」
    m = re.search(r"【相手のターン中】.{0,40}このキャラのパワー\+(\d+)", t)
    if m:
        n = int(m.group(1))
        entries.append({
            "_text": f"[auto] 【相手のターン中】このキャラのパワー+{n}",
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_turn": True},
            "do": [{"power_pump": {"target": "self", "amount": n, "duration": "static"}}],
        })

    # P4b: 「【相手のターン中】 ... このキャラのパワー-N」
    m = re.search(r"【相手のターン中】.{0,40}このキャラのパワー-(\d+)", t)
    if m:
        n = int(m.group(1))
        entries.append({
            "_text": f"[auto] 【相手のターン中】このキャラのパワー-{n}",
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_turn": True},
            "do": [{"power_pump": {"target": "self", "amount": -n, "duration": "static"}}],
        })

    # P5: 「自分のリーダーが特徴《X》(か《Y》)?を持つ場合、 このキャラのパワー+N」
    m = re.search(
        r"自分のリーダーが特徴《(.+?)》(?:か《(.+?)》)?を持つ場合、.{0,20}このキャラのパワー\+(\d+)",
        t,
    )
    if m:
        f1, f2, n = m.group(1), m.group(2), int(m.group(3))
        cond = {"leader_features_any": [f1, f2]} if f2 else {"leader_feature": f1}
        entries.append({
            "_text": f"[auto] リーダー特徴 {f1}{'/'+f2 if f2 else ''} で このキャラ パワー+{n}",
            "when": "on_attached_don",
            "n": 0,
            "if": cond,
            "do": [{"power_pump": {"target": "self", "amount": n, "duration": "static"}}],
        })

    # P7: 「ライフが N 以下の場合、 (このリーダーは|このキャラの)パワー+M」
    m = re.search(r"(?:自分の)?ライフが\s*(\d+)\s*(?:枚)?以下の場合、.{0,15}(?:このリーダーは|このキャラの)パワー\+(\d+)", t)
    if m:
        life, n = int(m.group(1)), int(m.group(2))
        entries.append({
            "_text": f"[auto] ライフ{life}以下の場合 自身パワー+{n}",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_life_le": life},
            "do": [{"power_pump": {"target": "self", "amount": n, "duration": "static"}}],
        })

    # P8: 「自分の元々のパワーN以上のキャラがいない場合、 このキャラのパワー+M」
    m = re.search(r"自分の元々のパワー\s*(\d+)\s*以上のキャラがいない場合、.{0,10}このキャラのパワー\+(\d+)", t)
    if m:
        # 完全な対応は engine 拡張要だが 簡略 で 「self_chara_power_ge: N 以上 = false」 という否定条件
        # 現状の primitives で 直接対応する条件 なし → スキップ (= 偽陽性 回避)
        pass

    # P9: 「自分の場のドン!!N枚以下の場合、 このキャラのパワー+M」
    m = re.search(r"自分の場のドン[!!‼]+\s*(\d+)\s*枚以下の場合、.{0,10}このキャラのパワー\+(\d+)", t)
    if m:
        d, n = int(m.group(1)), int(m.group(2))
        entries.append({
            "_text": f"[auto] 自分の場のドン{d}以下で 自身パワー+{n}",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_don_le": d},
            "do": [{"power_pump": {"target": "self", "amount": n, "duration": "static"}}],
        })

    # P10: 単純 「自分のレストのカードが N 以上ある場合、 このキャラのパワー+M」
    m = re.search(r"自分のレストのカードが\s*(\d+)\s*枚以上ある場合、.{0,10}このキャラのパワー\+(\d+)", t)
    if m:
        n_rest, n_pump = int(m.group(1)), int(m.group(2))
        entries.append({
            "_text": f"[auto] 自分レスト{n_rest}以上で 自身パワー+{n_pump}",
            "when": "on_attached_don",
            "n": 0,
            "if": {"self_rested_cards_count_ge": n_rest},
            "do": [{"power_pump": {"target": "self", "amount": n_pump, "duration": "static"}}],
        })

    # P11: 「(このキャラは)アタックできない (条件)」 のうち シンプル 条件付
    m = re.search(r"相手の元々のパワー\s*(\d+)\s*以上のキャラが\s*(\d+)\s*枚以上いない場合、.{0,10}このキャラはアタックできない", t)
    if m:
        # 現状の primitives で 直接対応する条件 なし → スキップ
        pass

    # P12: 「【相手のターン中】 自分の特徴《X》を持つリーダーを、元々のパワーN にする」
    m = re.search(r"【相手のターン中】.{0,15}自分の特徴《(.+?)》を持つリーダーを、.{0,10}元々のパワー\s*(\d+)\s*にする", t)
    if m:
        feat, p = m.group(1), int(m.group(2))
        entries.append({
            "_text": f"[auto] 【相手のターン中】 リーダー({feat}) 元々のパワー{p}",
            "when": "on_attached_don",
            "n": 0,
            "if": {"opp_turn": True, "leader_feature": feat},
            "do": [{"set_base_power": {"target": "self_leader", "amount": p}}],
        })

    # P13: 「【ターン1回】このキャラが相手の効果で場を離れる場合、 代わりに〜できる」
    # シンプル変形のみ: 「相手のキャラ1枚をレストにできる」
    m = re.search(r"【ターン1回】このキャラが相手の効果で場を離れる場合、代わりに相手の.{0,8}キャラ.{0,3}枚.{0,5}レストにできる", t)
    if m:
        entries.append({
            "_text": "[auto] このキャラ離脱の代わりに 相手キャラ1枚レスト (= replace_leave)",
            "when": "replace_leave",
            "if": {"target": "self", "by_opp_effect": True},
            "cost": [{"once_per_turn": True}],
            "do": [{"rest": "one_opponent_character_any"}],
        })

    # P14: 「【ターン1回】 キャラがKOされた時、 カードN枚を引き、 自分の手札N枚を捨てる」
    m = re.search(r"【ターン1回】キャラがKOされた時、.{0,15}カード\s*(\d+)\s*枚を引き、.{0,15}自分の手札\s*(\d+)\s*枚を捨てる", t)
    if m:
        d, h = int(m.group(1)), int(m.group(2))
        entries.append({
            "_text": f"[auto] キャラKO時 draw{d} discard{h}",
            "when": "on_opp_chara_ko",
            "cost": {"once_per_turn": True},
            "do": [{"draw": d}, {"trash_self_hand_random": h}],
        })
        entries.append({
            "_text": f"[auto] 自キャラKO時 draw{d} discard{h}",
            "when": "on_self_chara_ko",
            "cost": {"once_per_turn": True},
            "do": [{"draw": d}, {"trash_self_hand_random": h}],
        })

    # P15: 「手札のこのカードは、 ... 場合、 コスト-N」
    m = re.search(r"手札のこのカードは、.{0,30}場合、.{0,5}コスト-(\d+)", t)
    if m:
        # 一律 静的 in_hand コスト減 (= 条件は audit 別 detect)
        n = int(m.group(1))
        # 「自分のリーダーがパワー N 以下の場合」 等 を 抽出
        leader_cond_m = re.search(r"自分のリーダーがパワー\s*(\d+)\s*以下の場合、.{0,5}コスト-(\d+)", t)
        entry = {
            "_text": f"[auto] 手札のこのカード コスト-{n}",
            "when": "in_hand",
            "do": [{"in_hand_cost_minus": n}],
        }
        if leader_cond_m:
            entry["if"] = {"self_leader_power_le": int(leader_cond_m.group(1))}
        entries.append(entry)

    return entries


def main():
    added = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        if len(entries) > 0:
            continue  # 既存の overlay は 触らない
        text = get_text(cid)
        if not text:
            continue
        new_entries = generate_entries(text)
        if new_entries:
            OVERLAY[cid] = new_entries
            log.append(f"  {cid}: +{len(new_entries)} entries: {[e.get('_text', '?')[:60] for e in new_entries]}")
            added += len(new_entries)

    print(f"Added {added} stub entries to {len(log)} cards")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fill_empty_overlay_log.md").write_text(
        "# empty overlay 自動補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
