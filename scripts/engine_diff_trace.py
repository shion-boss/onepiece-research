# -*- coding: utf-8 -*-
"""Engine 差分同期ハーネス: trace 記録 + 決定論検証 (2026-07-29、 Rust engine 土台)。

Python engine で1ゲームを再生し、 各 action 後の canonical state digest 列を記録 (= trace)。
将来 Rust engine が同じ seed/deck/action 列で同じ digest 列を出すか comparator で照合する。
まず「Python 自身が決定論的か」(同一 seed → 同一 trace)を確認 = Rust が満たすべき ground truth。

  .venv/bin/python scripts/engine_diff_trace.py --deck-a cardrush_1385 --deck-b cardrush_1385 --seed 1 --runs 2
"""
from __future__ import annotations

import argparse, json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.core import reset_iid
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions, apply_action
from engine.ai import GreedyAI
from engine.state_snapshot import state_digest, canonical_state, diff_canonical

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _deck(slug):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


def _action_label(a):
    """action の言語非依存ラベル (type + 主要 operand)。 Rust replay 用エンコードの原型。"""
    d = {"t": type(a).__name__}
    for attr in ("attacker_id", "target_id", "card_id", "instance_id", "hand_index",
                 "target_instance_id", "don_count", "choice_index"):
        if hasattr(a, attr):
            v = getattr(a, attr)
            d[attr] = getattr(v, "card_id", v) if hasattr(v, "card_id") else v
    return d


def record_trace(deck_a, deck_b, seed, max_actions=600):
    """1ゲームを GreedyAI(決定論)で再生し、 (action_label, digest) 列 + 最終 canonical を返す。"""
    reset_iid()  # 同一 seed → 同一 iid 列 = 決定論の担保 (game 間 offset を除去)
    st = setup_game(_deck(deck_a), _deck(deck_b), rng=random.Random(seed),
                    first_player=0, effects_overlay=_OV)
    play_until_main(st)
    ais = [GreedyAI(rng=random.Random(seed * 3 + 1)), GreedyAI(rng=random.Random(seed * 5 + 2))]
    steps = [{"n": 0, "action": None, "digest": state_digest(st)}]  # 初期状態
    n = 0
    while not st.game_over and st.turn_number < 40 and n < max_actions:
        cur = st.turn_player_idx
        try:
            act = ais[cur].choose_action(st)
        except Exception as e:
            steps.append({"n": n + 1, "action": {"t": "ERROR", "e": str(e)[:60]}, "digest": "err"})
            break
        if act is None:
            break
        try:
            apply_action(st, act)
        except Exception as e:
            steps.append({"n": n + 1, "action": {"t": "APPLY_ERR", "e": str(e)[:60]}, "digest": "err"})
            break
        n += 1
        steps.append({"n": n, "action": _action_label(act), "digest": state_digest(st)})
    return {"seed": seed, "deck_a": deck_a, "deck_b": deck_b,
            "n_steps": len(steps), "game_over": st.game_over, "winner": getattr(st, "winner", -1),
            "steps": steps, "final_canonical": canonical_state(st)}


def compare_traces(t1, t2):
    """2 trace の digest 列を比較 → 最初の乖離 step を返す (None なら一致)。"""
    s1, s2 = t1["steps"], t2["steps"]
    for i in range(min(len(s1), len(s2))):
        if s1[i]["digest"] != s2[i]["digest"]:
            return i
    if len(s1) != len(s2):
        return min(len(s1), len(s2))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck-a", default="cardrush_1385")
    ap.add_argument("--deck-b", default="cardrush_1385")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--dump", help="trace を JSON 保存するパス")
    a = ap.parse_args()

    traces = [record_trace(a.deck_a, a.deck_b, a.seed) for _ in range(a.runs)]
    t0 = traces[0]
    print(f"trace: {a.deck_a} vs {a.deck_b} seed={a.seed}  steps={t0['n_steps']} "
          f"game_over={t0['game_over']} winner={t0['winner']}")
    print(f"  最終 digest = {t0['steps'][-1]['digest']}")
    # 決定論チェック: 全 run が同一 trace か
    ok = True
    for k in range(1, len(traces)):
        d = compare_traces(traces[0], traces[k])
        if d is not None:
            ok = False
            print(f"  ✗ run0 vs run{k}: step {d} で乖離 (非決定論!)")
            # 乖離箇所を pinpoint (canonical 差分)
            if d < len(traces[0]["steps"]) and d < len(traces[k]["steps"]):
                print(f"    action={traces[0]['steps'][d]['action']}")
    if ok:
        print(f"  ✓ 全 {len(traces)} run が bit 一致 = Python engine は決定論的 (Rust の ground truth)")
    if a.dump:
        Path(a.dump).write_text(json.dumps(t0, ensure_ascii=False), encoding="utf-8")
        print(f"  trace 保存: {a.dump}")


if __name__ == "__main__":
    main()
