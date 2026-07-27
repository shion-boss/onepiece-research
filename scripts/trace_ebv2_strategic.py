# -*- coding: utf-8 -*-
"""EBV2 戦略トレース (2026-07-27、 Claude-analyst loop = 戦略層)。

カード名(手札・盤面・攻撃対象)込みで hero の全手番を記録 → Claude が「プロならどう打つか」で
戦略的最善との差を分析(機械バグでなく戦略の凡庸さを探す)。 control 系マッチ推奨。

  TR_HERO=cardrush_1342 TR_OPP=cardrush_1385 TR_GAMES=2 .venv/bin/python scripts/trace_ebv2_strategic.py
"""
import sys, os, random, json
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, AttackLeader, AttackCharacter,
                         AttachDonToLeader, AttachDonToCharacter, EndPhase,
                         PlayCharacter, PlayEvent, ActivateMain)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.eval import project_opp_next_turn_lethal
from engine.hand_estimator import expected_counter_total
from engine.lethal_planner import lethal_available

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ.get("TR_HERO", "cardrush_1342")
OPP = os.environ.get("TR_OPP", "cardrush_1385")


def _dl(slug):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)


def _nm(card):
    n = getattr(card, "name", "?") or "?"
    return n[:8]


def _inplay(state, me, iid):
    p = state.players[me]
    if getattr(p.leader, "instance_id", None) == iid:
        return p.leader
    for c in p.characters:
        if c.instance_id == iid:
            return c
    return None


def _board(p):
    if not p.characters:
        return "空"
    def _blk(c):
        try:
            return c.is_blocker_now
        except Exception:
            return getattr(c, "is_blocker", False)
    return "・".join(f"{_nm(c.card)}({c.power}{'休' if c.rested else ''}{'B' if _blk(c) else ''})"
                     for c in p.characters)


def _hand(p):
    if not p.hand:
        return "空"
    parts = []
    for c in p.hand:
        cv = getattr(c, "counter", 0) or 0
        cost = getattr(c, "cost", "?")
        parts.append(f"{_nm(c)}[{cost}c{cv}]")
    return "・".join(parts)


def _act_str(state, me, a):
    opp = 1 - me
    mp = state.players[me]
    if isinstance(a, AttackLeader):
        atk = _inplay(state, me, a.attacker_iid); ap = atk.power if atk else 0
        dp = state.players[opp].leader.power
        return f"顔攻撃 {_nm(atk.card) if atk else '?'}({ap}) → leader({dp}) {'○' if ap>=dp else '✗届かず'}"
    if isinstance(a, AttackCharacter):
        atk = _inplay(state, me, a.attacker_iid); tgt = _inplay(state, opp, a.target_iid)
        ap = atk.power if atk else 0; dp = tgt.power if tgt else 0
        return f"キャラ攻撃 {_nm(atk.card) if atk else '?'}({ap}) → {_nm(tgt.card) if tgt else '?'}({dp}) {'○KO' if ap>=dp else '✗届かず'}"
    if isinstance(a, PlayCharacter):
        c = mp.hand[a.hand_idx] if 0 <= getattr(a, "hand_idx", -1) < len(mp.hand) else None
        return f"登場 {_nm(c) if c else '?'}"
    if isinstance(a, PlayEvent):
        c = mp.hand[a.hand_idx] if 0 <= getattr(a, "hand_idx", -1) < len(mp.hand) else None
        return f"イベント {_nm(c) if c else '?'}"
    if isinstance(a, ActivateMain):
        return "起動メイン"
    if isinstance(a, AttachDonToLeader):
        return "DON→leader"
    if isinstance(a, AttachDonToCharacter):
        t = _inplay(state, me, a.target_iid)
        return f"DON→{_nm(t.card) if t else '?'}"
    if isinstance(a, EndPhase):
        return "ターン終了"
    return type(a).__name__


def trace_game(seed, out):
    fp = seed % 2
    state = setup_game(_dl(HERO), _dl(OPP), rng=random.Random(seed), first_player=fp,
                       effects_overlay=_OVERLAY)
    play_until_main(state)
    # ⚠ setup_game は先攻を players[0] に置く。 hero(deck1) は fp==0→idx0 / fp==1→idx1。
    hero_idx = 0 if fp == 0 else 1
    opp_idx = 1 - hero_idx
    ais = [None, None]
    ais[hero_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 1), deck_analysis={"deck_slug": HERO})
    ais[opp_idx] = ExploitBeamAI(rng=random.Random(seed * 7 + 3), deck_analysis={"deck_slug": OPP})
    out.append(f"\n{'#'*94}\n### GAME seed={seed} : {HERO}(hero) vs {OPP}、 先攻={'hero' if fp==0 else 'opp'} ###")
    n, last_turn = 0, -1
    while not state.game_over and state.turn_number < 50 and n < 1200:
        cur = state.turn_player_idx
        if cur == hero_idx:
            if state.turn_number != last_turn:
                last_turn = state.turn_number
                try:
                    sr = project_opp_next_turn_lethal(state, hero_idx); il = lethal_available(state, hero_idx)
                    oc = expected_counter_total(state, opp_idx)
                except Exception:
                    sr, il, oc = -1, False, -1
                mp, op = state.players[hero_idx], state.players[opp_idx]
                out.append(f"\n──[T{state.turn_number}] 自ライフ{len(mp.life)} DON{mp.don_active} | 相ライフ{len(op.life)}──")
                out.append(f"  自盤面: {_board(mp)}")
                out.append(f"  相盤面: {_board(op)}")
                out.append(f"  自手札: {_hand(mp)}")
                out.append(f"  計算機: 被リーサル={sr:.2f} 自リーサル可={il} 相手counter推定={oc}")
                out.append(f"  手順:")
            try:
                chosen = ais[hero_idx].choose_action(state)
                out.append(f"    • {_act_str(state, hero_idx, chosen)}")
            except Exception:
                pass
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    w = getattr(state, "winner", -1)
    res = "hero勝ち" if w == hero_idx else ("opp勝ち" if w == opp_idx else "引分")
    out.append(f"\n### 結果: {res} (turn {state.turn_number}) ###")


def main():
    games = int(os.environ.get("TR_GAMES", "2"))
    seed0 = int(os.environ.get("TR_SEED", "300"))
    out = [f"EBV2 戦略トレース: {HERO}(hero) vs {OPP}"]
    for i in range(games):
        trace_game(seed0 + i, out)
    text = "\n".join(out)
    (ROOT / "db" / "eiv1" / "ebv2_strategic_trace.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
