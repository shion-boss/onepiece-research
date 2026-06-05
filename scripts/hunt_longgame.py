# -*- coding: utf-8 -*-
"""defensive long-game 戦術 × 全オラクル で late-game 構造状態を hunt (= 2026-06-05)。

aggressive/field-flood sweep は試合が早く終わり **deck-out / life-zero トリガー / 長期 refresh
サイクル / end-of-turn 累積** に未到達。 人間を超防御的 (攻撃せず block/counter で生存) に
すると試合が長引き late-game 構造状態に届く。 全オラクル (各プレイヤー保存則/DON台帳/
RuleReferee構造) + deck-out 正常終了 + crash/STUCK/engine-error を検査。
"""
import random
import sys
from collections import Counter

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import fuzz_human_play as F
import hunt_aggressive_combined as A  # check_all / _per_player_card_counts / _don_ledger 再利用

F._setup()
DECKS = F.DECKS


def play(a, b, seed, hf):
    s = F._build_session(a, b, seed, hf)
    rng = random.Random(seed)
    steps = 0
    last = None
    same = 0
    base_cards = base_don = None
    max_turn = 0
    while not s.state.game_over and steps < 6000:
        steps += 1
        max_turn = max(max_turn, s.state.turn_number)
        pk = s.pending_kind
        pl = s.pending_payload or {}
        sig = (pk, pl.get("kind"), s.state.turn_number,
               len(s.state.players[0].deck), len(s.state.players[1].deck),
               len(s.state.players[0].hand), len(s.state.players[1].hand))
        if sig == last:
            same += 1
            if same > 150:
                return ("STUCK", steps, sig, max_turn)
        else:
            same = 0
            last = sig
        if pk == "action":
            if base_cards is None:
                base_cards = A._per_player_card_counts(s.state)
                base_don = [A._don_ledger(p) for p in s.state.players]
            v = A.check_all(s.state, base_cards, base_don)
            if v:
                return ("ORACLE", steps, f"t{s.state.turn_number} :: {v}", max_turn)
        try:
            if pk == "action":
                acts = s.legal_actions_for_human()
                if not acts:
                    return ("NO_ACT", steps, None, max_turn)
                # 超防御: 攻撃しない、 キャラ展開/効果のみ、 大半は End (= 生存して長引かせる)
                non_atk = [x for x in acts if x.get("kind") not in ("AttackLeader", "AttackCharacter", "EndPhase")]
                if non_atk and rng.random() < 0.5:
                    s.apply_human_action(rng.choice(non_atk)["idx"])
                else:
                    s.apply_human_action(next((x for x in acts if x.get("kind") == "EndPhase"), acts[0])["idx"])
            elif pk == "choice":
                s.apply_human_choice(A.modal_pick(pl, rng))
            elif pk == "defense":
                # 全力防御: blocker + counter 値 + カウンターイベント + opp_attack 効果
                A.do_defense(s, pl, rng)
            else:
                break
        except Exception as e:  # noqa: BLE001
            import traceback
            return ("PY_EXC", steps,
                    f"{type(e).__name__}: {str(e)[:60]} | {traceback.format_exc().splitlines()[-2][:60]}", max_turn)
    if base_cards is not None:
        v = A.check_all(s.state, base_cards, base_don)
        if v:
            return ("ORACLE", steps, f"(final) {v}", max_turn)
    for ln in s.state.log:
        if "engine error" in ln:
            return ("ENGINE_ERROR", steps, ln.split("engine error:")[-1].strip()[:90], max_turn)
    return ("OK", steps, None, max_turn)


def main():
    nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
    n = nums[0] if nums else 6
    pairs = [(d, d) for d in DECKS]
    for i, d in enumerate(DECKS):
        for j in (1, 2, 3):
            pairs.append((d, DECKS[(i + j) % len(DECKS)]))
    bugs = []
    res = Counter()
    total = 0
    turns = []
    for idx, (a, b) in enumerate(pairs):
        for sd in range(n):
            gs = 110000 + sd * 19
            st, steps, info, mt = play(a, b, gs, sd % 2 == 0)
            res[st] += 1
            total += 1
            turns.append(mt)
            if st != "OK":
                bugs.append((a, b, gs, sd % 2 == 0, st, info, mt))
        if idx % 8 == 0:
            print(f"  ... {a} vs {b} | total {total} bugs {len(bugs)} | max_turn 中央={sorted(turns)[len(turns)//2]}", flush=True)
    print(f"\n=== defensive long-game × 全オラクル hunt {total} 試合 ===")
    print(f"  到達ターン: 最小={min(turns)} 中央={sorted(turns)[len(turns)//2]} 最大={max(turns)}")
    for k, c in res.most_common():
        print(f"  {k}: {c}")
    if bugs:
        print(f"\n!!! 問題 {len(bugs)} 件:")
        for a, b, sd, hf, st, info, mt in bugs[:30]:
            print(f"  ★[{st}] {a} vs {b} seed={sd} hf={hf} (t{mt}): {info}")
    sys.exit(1 if bugs else 0)


if __name__ == "__main__":
    main()
