# -*- coding: utf-8 -*-
"""デッキの card-pool を役割(role)別に分類し、 操縦非依存の「設計上のコンセプト」を導く。

ohtsuki『archetype が粗い。 各デッキ固有のコンセプト(何をコントロールしてどう勝つか)を、
カードプール分析(操縦に汚染されない ground truth)から導く』([[project_leader_aware_matchup_ai]])。
data 駆動(AI のプレイ勝ち相関)は誤操縦デッキで循環するので、 cards が何をするかを役割集計する。

役割は overlay(card_effects.json)の do[] primitive + カード stats から判定:
  ramp / big_threat / removal / protection / card_adv / go_wide / defense / recovery / finisher
出力 = 各デッキの role 構成(枚数)→ コンセプト profile authoring の grounding。

  .venv/bin/python scripts/analyze_deck_roles.py --decks cardrush_1342,... --out db/deck_roles.json
"""
import argparse, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

_CARDS = json.load(open(ROOT / "db" / "cards.json"))
_CLIST = _CARDS if isinstance(_CARDS, list) else _CARDS.get("cards", [])
_CARD = {c["card_id"]: c for c in _CLIST}
_OVL = json.load(open(ROOT / "db" / "card_effects.json"))
_OVMAP = _OVL if isinstance(_OVL, dict) else {e["card_id"]: e for e in _OVL}

# primitive(do[] の key) → 役割。 1 枚が複数役割を持ちうる。
RAMP = {"add_don", "add_rested_don", "attach_don", "attach_active_don", "attach_rested_don", "untap_don"}
REMOVAL = {"ko", "ko_multi", "ko_all_others", "return_to_hand", "return_to_hand_multi",
           "return_to_deck_bottom", "return_to_deck_bottom_multi", "rest", "rest_opp_don",
           "set_base_power", "power_pump"}  # power_pump は -系で除去補助 (後で精査)
PROTECT = {"replace_ko", "replace_leave", "replace_rest", "prevent_ko", "set_ko_immune",
           "set_ko_immune_timed", "set_ko_immune_battle_only", "set_immune_attribute_in_battle"}
CARD_ADV = {"draw", "draw_per_self_hand_discarded", "draw_per_self_chara_then_discard",
            "search", "search_top_n", "search_from_trash", "play_from_trash",
            "play_from_hand_or_trash", "reveal_top_play", "reveal_top_then", "summon_from_deck"}
RECOVERY = {"life_to_hand", "life_top_or_bottom_to_hand", "put_top_to_life", "hand_to_self_life",
            "chara_to_self_life", "then_life_to_hand", "or_to_life", "hand_or_trash_to_self_life"}


def _do_keys(entry):
    keys = set()
    arr = entry if isinstance(entry, list) else (entry.get("effects") if isinstance(entry, dict) and "effects" in entry else [entry] if isinstance(entry, dict) else [])
    for e in arr:
        for d in (e.get("do") or []):
            if isinstance(d, dict):
                keys.update(d.keys())
    return keys


def card_roles(cid):
    """1 枚の card の役割集合。"""
    c = _CARD.get(cid, {})
    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0
    cost = _int(c.get("cost"))
    cat = (c.get("category") or "").upper()
    power = _int(c.get("power"))
    kws = c.get("keywords") or c.get("attribute") or ""
    text = (c.get("effect") or c.get("text") or "")
    keys = _do_keys(_OVMAP.get(cid))
    roles = set()
    if keys & RAMP or "ドン" in text and ("追加" in text or "アクティブ" in text):
        roles.add("ramp")
    if keys & REMOVAL & {"ko", "ko_multi", "ko_all_others"} or "KO" in text:
        roles.add("removal")
    if "rest" in keys or "レストにする" in text:
        roles.add("removal")
    if keys & {"return_to_hand", "return_to_hand_multi", "return_to_deck_bottom"}:
        roles.add("removal")
    if keys & PROTECT or "代わりに" in text:
        roles.add("protection")
    if keys & CARD_ADV:
        roles.add("card_adv")
    if keys & RECOVERY:
        roles.add("recovery")
    if cat == "CHARACTER":
        if cost >= 7 or power >= 7000:
            roles.add("big_threat")
        if cost <= 3:
            roles.add("go_wide")
    if "ブロッカー" in str(kws) or "ブロッカー" in text:
        roles.add("defense")
    if "カウンター" in text and cat == "EVENT":
        roles.add("defense")
    return roles


def deck_role_profile(slug):
    d = json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8"))
    from collections import Counter
    role_count = Counter()
    big = []
    for entry in d.get("main", []):
        cid, cnt = entry["card_id"], entry["count"]
        rs = card_roles(cid)
        for r in rs:
            role_count[r] += cnt
        if "big_threat" in rs:
            big.append((_CARD.get(cid, {}).get("name", cid), _CARD.get(cid, {}).get("cost")))
    return {"name": d.get("name"), "leader": d.get("leader"),
            "roles": dict(role_count.most_common()), "big_threats": big}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", required=True)
    ap.add_argument("--out", default="db/deck_roles.json")
    a = ap.parse_args()
    out = {}
    for slug in [s.strip() for s in a.decks.split(",")]:
        prof = deck_role_profile(slug)
        out[slug] = prof
        roles = prof["roles"]
        # 上位役割で素朴なコンセプト示唆
        top = sorted(roles.items(), key=lambda kv: -kv[1])[:4]
        print(f"{slug:20} {prof['name'][:10]:10} | " + "  ".join(f"{r}={n}" for r, n in top), flush=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\nsaved → {a.out}", flush=True)


if __name__ == "__main__":
    main()
