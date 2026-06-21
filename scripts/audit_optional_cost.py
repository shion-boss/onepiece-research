# -*- coding: utf-8 -*-
"""任意「〜できる：」効果の human decline 欠落 audit (= 2026-06-17、 ゼウス OP11-106 修正の横展開)。

受動トリガー (on_play/on_ko/trigger/on_attack/on_block) に top-level `cost` を持ち、 公式 text に
「できる」 を含むカードを抽出 → **人間操作時に「やらない(発動しない)」選択が出るか** を実証検証する。

判定 (on_play は合成盤面に注入して play、 pending_choice と効果発火を観測):
  - prompt 出る (counter_discard_pick / optional_cost_confirm 等)        → OK (decline 可)
  - prompt 無し + 効果が勝手に発火 (= cost 自動払い)                      → BUG (ゼウス型、 要 optional_cost_then 化)
  - prompt 無し + 効果不発 (= 条件未達 / cost 不能)                       → INCONCLUSIVE (手動確認)

usage: PYTHONPATH=. .venv/bin/python scripts/audit_optional_cost.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import random

from engine.deck import CardRepository, DeckList
from engine.game import setup_game, play_until_main, Phase, apply_action, PlayCharacter
from engine.effects import load_effect_overlay

PASSIVE = {"on_play", "on_ko", "trigger", "on_attack", "on_block"}
PAYABLE = {
    "life_top_or_bottom_to_hand", "life_to_hand", "hand_to_self_life",
    "mill_self_life_to_trash", "trash_self_hand_random", "discard_hand",
    "discard_hand_with_filter", "pay_don",
}


def candidates(ce, cards):
    out = []
    for cid, entries in ce.items():
        if cid.endswith("_p1") or cid.endswith("_p2"):
            continue
        if not isinstance(entries, list):
            continue
        for ei, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            if e.get("when") not in PASSIVE:
                continue
            cost = e.get("cost")
            if not isinstance(cost, dict):
                continue
            real = {k for k in cost if k != "once_per_turn"}
            if not (real & PAYABLE):
                continue
            txt = (cards.get(cid, {}).get("text") or "")
            if "できる" not in txt:
                continue
            out.append((cid, e.get("when"), sorted(real), ei))
    return out


def verify_on_play(cid, repo, overlay, opp_deck):
    """on_play カードを合成盤面 (human=P0) に注入して play、 decline 提示を観測。"""
    card = repo.get(cid)
    rng = random.Random(0)
    base = DeckList.from_json("decks/cardrush_1478.json", repo)
    st = setup_game(base, opp_deck, rng=rng, first_player=0,
                    effects_overlay=overlay, do_mulligan_and_finalize=True)
    play_until_main(st)
    h = st.turn_player_idx
    st.human_player_idx = h
    me = st.players[h]
    opp = st.players[1 - h]
    # 合成: 手番=human MAIN / 十分な DON / 手札 = [対象カード + filler×3]
    st.turn_number = 5
    st.phase = Phase.MAIN
    me.don_active = max(int(card.cost or 0), 1) + 2
    filler = repo.get("OP14-102")  # クマシー (vanilla 1cost) を filler に
    me.hand = [card, filler, filler, filler]
    # 相手に KO/対象 候補を用意 (= 効果条件を満たしやすく)
    from engine.game import InPlay
    if not opp.characters:
        tgt = InPlay.of(repo.get("OP14-102"))
        opp.characters.append(tgt)
    hand_before = len(me.hand)
    trash_before = len(me.trash)
    opp_chars_before = len(opp.characters)
    try:
        apply_action(st, PlayCharacter(hand_idx=0))
    except Exception as e:
        return ("ERROR", f"{type(e).__name__}: {e}")
    pc = st.pending_choice
    if pc is not None:
        return ("OK", f"prompt={pc.get('kind')}")
    # prompt 無し: 効果が発火したか (= cost 自動払い or 効果適用) を検出
    me2 = st.players[h]
    opp2 = st.players[1 - h]
    discarded = len(me2.trash) - trash_before
    # 注: play した1枚は trash でなく場へ。 discard cost が自動払いされたら trash +1。
    fired = (discarded > 0) or (len(opp2.characters) < opp_chars_before)
    if fired:
        return ("BUG", f"効果自動発火 (discard={discarded}, opp_ko={opp_chars_before-len(opp2.characters)})")
    return ("INCONCLUSIVE", "prompt無し+発火無し (条件未達の可能性)")


def main():
    cards = {c["card_id"]: c for c in json.load(open("db/cards.json"))}
    ce = json.load(open("db/card_effects.json"))
    repo = CardRepository.from_json("db/cards.json")
    overlay = load_effect_overlay("db/card_effects.json")
    opp_deck = DeckList.from_json("decks/cardrush_1342.json", repo)

    cands = candidates(ce, cards)
    print(f"候補 (受動trigger + top-level payable cost + 「できる」): {len(cands)}\n")
    by_when = {}
    for cid, when, costs, ei in cands:
        by_when.setdefault(when, []).append((cid, costs))
    for when, lst in sorted(by_when.items()):
        print(f"  when={when}: {len(lst)} 枚")
    print()

    results = {"OK": [], "BUG": [], "INCONCLUSIVE": [], "ERROR": [], "SKIP(non-on_play)": []}
    for cid, when, costs, ei in cands:
        name = cards.get(cid, {}).get("name", "?")
        if when != "on_play":
            results["SKIP(non-on_play)"].append((cid, name, when, costs))
            continue
        verdict, detail = verify_on_play(cid, repo, overlay, opp_deck)
        results.setdefault(verdict, []).append((cid, name, when, costs, detail))

    for verdict in ["BUG", "INCONCLUSIVE", "ERROR", "OK", "SKIP(non-on_play)"]:
        lst = results.get(verdict, [])
        print(f"===== {verdict}: {len(lst)} =====")
        for row in lst:
            print("   ", row)
        print()


if __name__ == "__main__":
    main()
