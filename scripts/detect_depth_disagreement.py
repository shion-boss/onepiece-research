# -*- coding: utf-8 -*-
"""深さ不一致検出器(Claude idea 2026-07-06): 配備の浅い探索(post-opp 1턴)と 深い探索(post-opp 2턴)が
同一局面で違う手を選ぶ頻度 + どの判断種別が変わるか を実測。 = 探索 myopia が実害を出しているかの一次診断。

不一致が稀 → 深さは判断をほぼ変えない = myopia は問題でない(単一 state 天井を受容)。
不一致が多い → 深さが多くの判断を変える = どのパターンかを次に rollout 審判。

  .venv/bin/python scripts/detect_depth_disagreement.py --deck cardrush_1454 --positions 80
出力(checkpoint 付き): 不一致率 + action 種別内訳 + 不一致サンプル。
"""
from __future__ import annotations
import argparse, json, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main,
                         AttackLeader, AttackCharacter, ActivateMain, PlayCharacter,
                         PlayEvent, PlayStage, AttachDonToLeader, AttachDonToCharacter, EndPhase)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.plan_search import fast_clone

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _deck(slug):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


def _act_kind(a):
    if isinstance(a, AttackLeader):
        return "attack_leader"
    if isinstance(a, AttackCharacter):
        return "attack_chara"
    if isinstance(a, ActivateMain):
        return "activate_main"
    if isinstance(a, PlayCharacter):
        return "play_chara"
    if isinstance(a, (PlayEvent, PlayStage)):
        return "play_other"
    if isinstance(a, (AttachDonToLeader, AttachDonToCharacter)):
        return "attach_don"
    if isinstance(a, EndPhase):
        return "end_phase"
    return type(a).__name__


def _mk(slug, seed, turns):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                         deck_analysis={"deck_slug": slug}, postopp_turns=turns)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1454")
    ap.add_argument("--opp", default="cardrush_1454")
    ap.add_argument("--positions", type=int, default=80)
    ap.add_argument("--deep-turns", type=int, default=2)
    ap.add_argument("--out", default="db/_analyst/depth_disagree.jsonl")
    a = ap.parse_args()
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)

    shallow = _mk(a.deck, 101, 1)          # 配備の浅い探索(post-opp 1)
    deep = _mk(a.deck, 101, a.deep_turns)  # 深い探索(post-opp 2)

    n_pos = 0
    n_diff = 0
    kind_total = {}
    kind_diff = {}
    fout = open(out, "w", encoding="utf-8")
    g = 0
    while n_pos < a.positions:
        st = setup_game(_deck(a.deck), _deck(a.opp), rng=random.Random(1000 + g),
                        first_player=g % 2, effects_overlay=_OVERLAY)
        play_until_main(st)
        drivers = [_mk(a.deck, 7, 1), _mk(a.opp, 9, 1)]  # 対局進行は配備(浅い)で
        steps = 0
        while not st.game_over and st.turn_number < 50 and steps < 400 and n_pos < a.positions:
            tp = st.turn_player_idx
            # サンプル: この局面で shallow vs deep の "最初の手" を比較(手番頭のみ、 過負荷回避で間引き)
            if steps % 2 == 0:
                snap = fast_clone(st)
                try:
                    m_s = shallow.choose_action(snap)
                    m_d = deep.choose_action(fast_clone(st))
                except Exception:
                    m_s = m_d = None
                if m_s is not None and m_d is not None:
                    ks, kd = _act_kind(m_s), _act_kind(m_d)
                    same = (m_s == m_d)
                    kind_total[ks] = kind_total.get(ks, 0) + 1
                    if not same:
                        n_diff += 1
                        kind_diff[ks] = kind_diff.get(ks, 0) + 1
                    n_pos += 1
                    fout.write(json.dumps({"game": g, "turn": st.turn_number, "player": tp,
                                           "shallow_kind": ks, "deep_kind": kd, "same": same}) + "\n")
                    fout.flush()
                    if n_pos % 10 == 0:
                        print(f"  {n_pos}/{a.positions} pos, 不一致 {n_diff} ({100*n_diff/n_pos:.0f}%)", flush=True)
            try:
                play_one_action(st, drivers[tp], drivers[1 - tp])
            except Exception:
                break
            steps += 1
        g += 1
    fout.close()

    print(f"\n=== 深さ不一致(浅 post-opp1 vs 深 post-opp{a.deep_turns})、 {a.deck} mirror ===")
    print(f"総局面 {n_pos}, 不一致 {n_diff} ({100*n_diff/max(1,n_pos):.0f}%)")
    print("判断種別ごとの不一致率(浅い手の種別で集計):")
    for k in sorted(kind_total, key=lambda x: -kind_total[x]):
        t = kind_total[k]; df = kind_diff.get(k, 0)
        print(f"  {k:16} {df:>3}/{t:<3} ({100*df/max(1,t):.0f}% 変わる)")


if __name__ == "__main__":
    main()
