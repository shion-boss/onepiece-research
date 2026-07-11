# -*- coding: utf-8 -*-
"""手札予測器の学習データ収集 (2026-07-11、 ohtsuki 案: 見えない手札を予測して公平に戦う)。

self-play を回し、 各局面で **対象 deck プレイヤーの (観測可能特徴, 実手札)** を記録。
観測可能特徴 = 相手から見える情報のみ: turn / 自 board の card_id 別枚数 / 自 trash の card_id 別枚数 /
hand_size / DON / life。 label = その時点の実手札 card_id 列。 = これから「盤面→手札分布」を学習。

  .venv/bin/python scripts/collect_hand_data.py --deck cardrush_1454 --n 200 --out db/_analyst/hand_data_1454.jsonl
"""
import argparse, json, os, random, sys
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, legal_actions, apply_action,
                         AttackLeader, AttackCharacter)
from engine.ai import GreedyAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
# 対象 deck を色々な相手と当てて手札分布を広く見る
_OPPS = ["cardrush_1342", "tcgportal_calgara", "tcgportal_bonney", "cardrush_1385",
         "cardrush_1453", "tcgportal_hancock", "cardrush_1439"]


def _deck(s):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _cid(c):
    return getattr(c, "card_id", None) or getattr(getattr(c, "card", None), "card_id", None)


def _obs_features(state, me_idx):
    """相手から見える特徴 (手札の中身は除く)。"""
    me = state.players[me_idx]
    from collections import Counter
    board = Counter(_cid(c) for c in getattr(me, "characters", []))
    trash = Counter(_cid(c) for c in getattr(me, "trash", []))
    leader = _cid(getattr(me, "leader", None))
    return {
        "turn": state.turn_number,
        "leader": leader,
        "hand_size": len(getattr(me, "hand", [])),
        "don_active": int(getattr(me, "don_active", 0) or 0),
        "don_rested": int(getattr(me, "don_rested", 0) or 0),
        "life": len(getattr(me, "life", []) or []),
        "board_counts": dict(board),
        "trash_counts": dict(trash),
        "n_board": sum(board.values()),
        "n_trash": sum(trash.values()),
    }


_AI_KIND = os.environ.get("HD_AI", "greedy")  # greedy(高速) / exploit(nuanced 防御=behavioral信号)


def _mk_ai(slug, seed):
    if _AI_KIND == "exploit":
        from engine.exploit_beam_ai import ExploitBeamAI
        return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                             deck_analysis={"deck_slug": slug})
    return GreedyAI(rng=random.Random(seed), deck_analysis={"deck_slug": slug})


def _run_game(args):
    deck, opp, seed = args
    rows = []
    st = setup_game(_deck(deck), _deck(opp), rng=random.Random(seed),
                    first_player=seed % 2, effects_overlay=_OV)
    play_until_main(st)
    # deck 側の席
    me_idx = 0 if seed % 2 == 0 else 1
    ais = [_mk_ai((deck if i == me_idx else opp), seed * 3 + i) for i in range(2)]
    n = 0
    attacks_faced = 0  # behavioral: me_idx が受けた攻撃回数 (= カウンターを切る"機会")
    while not st.game_over and st.turn_number < 40 and n < 800:
        cur = st.turn_player_idx
        if cur == me_idx and st.phase.name == "MAIN":
            feat = _obs_features(st, me_idx)
            feat["attacks_faced"] = attacks_faced
            feat["hand"] = [_cid(c) for c in st.players[me_idx].hand]
            feat["deck_slug"] = deck
            rows.append(feat)
        acts = legal_actions(st)
        if not acts:
            break
        try:
            action = ais[cur].choose_action(st)
        except Exception:
            break
        # 相手 (1-me_idx) の攻撃 = me_idx が受けた攻撃 (= カウンター/ブロック/受けの判断機会)
        if cur != me_idx and isinstance(action, (AttackLeader, AttackCharacter)):
            attacks_faced += 1
        try:
            apply_action(st, action)
        except Exception:
            break
        n += 1
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1454")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = a.out or f"db/_analyst/hand_data_{a.deck}.jsonl"
    tasks = [(a.deck, _OPPS[i % len(_OPPS)], 700000 + i) for i in range(a.n)]
    with mp.Pool(a.workers) as p:
        results = p.map(_run_game, tasks)
    rows = [r for g in results for r in g]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{a.deck}: {a.n} games -> {len(rows)} 局面サンプル -> {out}")


if __name__ == "__main__":
    main()
