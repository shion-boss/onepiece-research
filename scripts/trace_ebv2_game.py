# -*- coding: utf-8 -*-
"""EBV2 決定トレース v2 (2026-07-27、 Claude-analyst loop)。

各 hero 手番で AI の判断材料 + 選んだ手 + **攻撃の connect 判定(無駄打ち検出)** を記録。
control vs aggro 等 非ミラーも対応(TR_HERO / TR_OPP)。 Claude が読んで改善箇所を探す。

  TR_HERO=cardrush_1342 TR_OPP=cardrush_1454 TR_GAMES=4 .venv/bin/python scripts/trace_ebv2_game.py
"""
import sys, os, random, json
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, AttackLeader, AttackCharacter,
                         AttachDonToLeader, AttachDonToCharacter, EndPhase)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.eval import project_opp_next_turn_lethal
from engine.hand_estimator import expected_counter_total
from engine.lethal_planner import lethal_available

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ.get("TR_HERO", os.environ.get("TR_SLUG", "cardrush_1454"))
OPP = os.environ.get("TR_OPP", HERO)


def _dl(slug):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)


def _inplay(state, me, iid):
    p = state.players[me]
    if getattr(p.leader, "instance_id", None) == iid:
        return p.leader
    for c in p.characters:
        if c.instance_id == iid:
            return c
    return None


def _act_str(state, me, a, waste):
    opp = 1 - me
    if isinstance(a, AttackLeader):
        atk = _inplay(state, me, a.attacker_iid)
        ap = atk.power if atk else 0
        dp = state.players[opp].leader.power
        conn = "○通" if ap >= dp else "✗届かず"
        return f"顔攻撃 P{ap}vs{dp} {conn}", (ap < dp)
    if isinstance(a, AttackCharacter):
        atk = _inplay(state, me, a.attacker_iid)
        tgt = _inplay(state, opp, a.target_iid)
        ap = atk.power if atk else 0
        dp = tgt.power if tgt else 0
        conn = "○KO" if ap >= dp else "✗届かず"
        return f"キャラ攻撃 P{ap}vs{dp} {conn}", (ap < dp)
    if isinstance(a, AttachDonToLeader):
        return "DON→leader", False
    if isinstance(a, AttachDonToCharacter):
        return f"DON→iid{getattr(a,'target_iid','?')}", False
    if isinstance(a, EndPhase):
        return "ターン終了", False
    return type(a).__name__, False


def _board(p):
    return f"{len(p.characters)}体[{','.join(str(c.power) for c in p.characters)}]"


def trace_game(seed, out, stats):
    fp = seed % 2
    state = setup_game(_dl(HERO), _dl(OPP), rng=random.Random(seed), first_player=fp,
                       effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [ExploitBeamAI(rng=random.Random(seed * 5 + 1), deck_analysis={"deck_slug": HERO}),
           ExploitBeamAI(rng=random.Random(seed * 7 + 3), deck_analysis={"deck_slug": OPP})]
    out.append(f"\n{'='*92}\n=== GAME seed={seed} ({HERO} vs {OPP}、 先攻P{fp}) === hero=P0")
    n, last_turn = 0, -1
    while not state.game_over and state.turn_number < 50 and n < 1200:
        cur = state.turn_player_idx
        if cur == 0:
            if state.turn_number != last_turn:
                last_turn = state.turn_number
                try:
                    sr = project_opp_next_turn_lethal(state, 0)
                    il = lethal_available(state, 0)
                    oc = expected_counter_total(state, 1)
                except Exception:
                    sr, il, oc = -1, False, -1
                mp, op = state.players[0], state.players[1]
                out.append(f"\n[T{state.turn_number}] 自:手{len(mp.hand)}/ライフ{len(mp.life)}/{_board(mp)}/DON{mp.don_active}"
                           f" | 相:手{len(op.hand)}/ライフ{len(op.life)}/{_board(op)}")
                out.append(f"   計算機: 被リーサルリスク={sr:.2f} / 自リーサル可={il} / 相手counter推定={oc}")
            try:
                chosen = ais[0].choose_action(state)
                s, wasted = _act_str(state, 0, chosen, None)
                out.append(f"     → {s}")
                if wasted:
                    stats["waste"] += 1
                    stats["waste_games"].add(seed)
                if isinstance(chosen, (AttackLeader, AttackCharacter)):
                    stats["atk"] += 1
            except Exception:
                pass
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    w = getattr(state, "winner", -1)
    out.append(f"--- 結果: {'P0勝ち' if w==0 else ('P1勝ち' if w==1 else '引分')} (turn {state.turn_number}) ---")


def main():
    games = int(os.environ.get("TR_GAMES", "4"))
    seed0 = int(os.environ.get("TR_SEED", "200"))
    out = [f"EBV2 決定トレース v2 ({HERO} vs {OPP}, {games} games) hero=P0"]
    stats = {"waste": 0, "atk": 0, "waste_games": set()}
    for i in range(games):
        trace_game(seed0 + i, out, stats)
    out.append(f"\n{'='*92}\n[SUMMARY] hero 攻撃 {stats['atk']} 回中 **無駄打ち(connect しない攻撃)= {stats['waste']} 回** "
               f"({stats['waste']/max(1,stats['atk'])*100:.0f}%、 {len(stats['waste_games'])}/{games} game で発生)")
    text = "\n".join(out)
    (ROOT / "db" / "eiv1" / "ebv2_trace.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
