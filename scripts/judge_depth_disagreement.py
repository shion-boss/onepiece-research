# -*- coding: utf-8 -*-
"""深さ不一致の審判(Claude idea 2026-07-06): 浅い探索(post-opp1)と深い探索(post-opp2)が違う手を
選んだ局面で、 どちらが実際に勝率が高いかを rollout で判定。 「深い手が本当に強い」なら myopia は
実害 = 深さ(or 深さの蒸留)が lever。 「互角」なら不一致は lateral = 深さは churn、 天井を受容。

審判法: 固定局面(盤面/手札/ライフ = 判断の文脈)はそのまま、 両者の残りデッキを再シャッフル(未来の
引きを変える)して分布を取る paired 比較。 同一 seed で shallow手/deep手 の両方を rollout(未来共通)。

  .venv/bin/python scripts/judge_depth_disagreement.py --deck cardrush_1454 --max-disagree 20 --rollouts 12
"""
from __future__ import annotations
import argparse, json, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, apply_action, EndPhase
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.plan_search import fast_clone

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _deck(slug):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


def _mk(slug, seed, turns, opp_value=False):
    ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                       deck_analysis={"deck_slug": slug}, postopp_turns=turns)
    if opp_value:
        ai._postopp_opp_value = True   # 相手 sim を value 誘導(greedy strawman でなく)
    return ai


def _reshuffle(state, seed):
    """両者の残りデッキ(引き山)を再シャッフル = 未来の引きを変える。 盤面/手札/ライフは不変。"""
    r = random.Random(seed)
    for p in state.players:
        d = list(getattr(p, "deck", []))
        r.shuffle(d)
        p.deck = d


def _rollout(state, first_move, tp, drivers):
    """first_move を強制適用 → 配備 AI で最後まで進行 → tp の勝敗(勝1/負0/分0.5)。"""
    try:
        apply_action(state, first_move)
    except Exception:
        return 0.5
    steps = 0
    while not state.game_over and state.turn_number < 50 and steps < 400:
        cur = state.turn_player_idx
        try:
            play_one_action(state, drivers[cur], drivers[1 - cur])
        except Exception:
            break
        steps += 1
    if not state.game_over:
        return 0.5
    w = getattr(state, "winner", -1)
    return 1.0 if w == tp else (0.0 if w == (1 - tp) else 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1454")
    ap.add_argument("--opp", default="cardrush_1454")
    ap.add_argument("--max-disagree", type=int, default=20)
    ap.add_argument("--rollouts", type=int, default=12)
    ap.add_argument("--deep-turns", type=int, default=2)
    ap.add_argument("--deep-opp-value", action="store_true",
                    help="深い探索の相手 sim を value 誘導に(greedy strawman を避ける)")
    ap.add_argument("--out", default="db/_analyst/depth_judge.jsonl")
    a = ap.parse_args()
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    fout = open(out, "w", encoding="utf-8")

    import os as _os
    if a.deep_opp_value:
        _os.environ["ONEPIECE_POSTOPP_SELF_VALUE"] = "1"  # turns>1 のみ効く = 浅い AI/driver に無害

    shallow = _mk(a.deck, 101, 1)
    deep = _mk(a.deck, 101, a.deep_turns, opp_value=a.deep_opp_value)

    judged = 0
    sum_s = sum_d = 0.0
    deep_better = shallow_better = tie = 0
    g = 0
    while judged < a.max_disagree:
        st = setup_game(_deck(a.deck), _deck(a.opp), rng=random.Random(2000 + g),
                        first_player=g % 2, effects_overlay=_OVERLAY)
        play_until_main(st)
        drivers = [_mk(a.deck, 7, 1), _mk(a.opp, 9, 1)]
        steps = 0
        while not st.game_over and st.turn_number < 50 and steps < 400 and judged < a.max_disagree:
            tp = st.turn_player_idx
            if steps % 2 == 0:
                try:
                    m_s = shallow.choose_action(fast_clone(st))
                    m_d = deep.choose_action(fast_clone(st))
                except Exception:
                    m_s = m_d = None
                if (m_s is not None and m_d is not None and m_s != m_d
                        and not isinstance(m_s, EndPhase) and not isinstance(m_d, EndPhase)):
                    ws = wd = 0.0
                    for si in range(a.rollouts):
                        base = fast_clone(st)
                        _reshuffle(base, 7919 * (judged + 1) + si)
                        dr = [_mk(a.deck, 100 + si, 1), _mk(a.opp, 200 + si, 1)]
                        ws += _rollout(fast_clone(base), m_s, tp, dr)
                        wd += _rollout(fast_clone(base), m_d, tp, dr)
                    ws /= a.rollouts; wd /= a.rollouts
                    sum_s += ws; sum_d += wd
                    if wd - ws > 0.08:
                        deep_better += 1
                    elif ws - wd > 0.08:
                        shallow_better += 1
                    else:
                        tie += 1
                    judged += 1
                    fout.write(json.dumps({"game": g, "turn": st.turn_number, "tp": tp,
                                           "shallow_kind": type(m_s).__name__, "deep_kind": type(m_d).__name__,
                                           "win_shallow": round(ws, 3), "win_deep": round(wd, 3)}) + "\n")
                    fout.flush()
                    print(f"  judged {judged}/{a.max_disagree}: shallow {ws:.2f} vs deep {wd:.2f} "
                          f"(Δ{wd-ws:+.2f})  [{type(m_s).__name__}→{type(m_d).__name__}]", flush=True)
            try:
                play_one_action(st, drivers[tp], drivers[1 - tp])
            except Exception:
                break
            steps += 1
        g += 1
    fout.close()

    n = max(1, judged)
    print(f"\n=== 深さ不一致の審判({a.deck} mirror、 不一致 {judged} 局面、 各 {a.rollouts} rollouts)===")
    print(f"平均勝率: 浅い手 {sum_s/n:.3f}  vs  深い手 {sum_d/n:.3f}  (Δ {(sum_d-sum_s)/n:+.3f})")
    print(f"深い手が明確に良い: {deep_better} / 浅い手が良い: {shallow_better} / 互角: {tie}")
    verdict = ("深さは実害を減らす(myopia が lever)" if (sum_d - sum_s) / n > 0.03
               else "深さは churn(不一致は lateral、 単一深度で天井)")
    print(f"→ {verdict}")


if __name__ == "__main__":
    main()
