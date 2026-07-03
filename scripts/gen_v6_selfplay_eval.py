"""ExploitBeam_v6 self-play を生成し、各手で eval グラフ(勝率推移)+ 悪手候補フラグを記録。

Claude-アナリスト loop の入力を作る: 配備 AI(ExploitBeam_v6)が打った試合を、各手ごとに
「その手で自分の勝率がどう動いたか」で評価し、勝率が最も急落した手 = 悪手候補として state
サマリ + action と共に保存する。Claude はこのフラグ点だけを分析する(プレイでなく診断 =
Claude の強み)。

出力(jsonl、 1 行 = 1 game): {deck_a, deck_b, seed, result, trajectory, flagged}
- trajectory: [(turn, player, winrate)]  (= 将棋の評価値グラフ相当、 各 player 視点)
- flagged: top-K の「自手番で自分の勝率が急落した手」= 悪手候補

使い方:
  .venv/bin/python scripts/gen_v6_selfplay_eval.py \
      --pairs cardrush_1342:cardrush_1454 cardrush_1454:cardrush_1454 \
      --n-games 10 --topk 3 --out db/_analyst/v6_selfplay_flagged.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.core import Phase
from engine.exploit_beam_ai import ExploitBeamAI
import engine.gbm_value as gv

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
SCALE = gv.SCALE


def _deck(slug):
    return make_deck_from_dict(
        json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO
    )


def _gbm_path(slug):
    p = ROOT / "db" / f"value_gbm_{slug}.pkl"
    return str(p) if p.exists() else None


def _winrate(state, idx, gbm_path):
    """acting player idx の勝率 P(win) を その deck の v6 value で評価。 path 無しは None。"""
    if not gbm_path:
        return None
    saved = os.environ.get("ONEPIECE_GBM_VALUE_PATH")
    os.environ["ONEPIECE_GBM_VALUE_PATH"] = gbm_path
    try:
        s = gv.gbm_score(state, idx)
    finally:
        if saved is None:
            os.environ.pop("ONEPIECE_GBM_VALUE_PATH", None)
        else:
            os.environ["ONEPIECE_GBM_VALUE_PATH"] = saved
    if s is None:
        return None
    return max(0.0, min(1.0, s / SCALE + 0.5))


def _state_summary(state, me_idx):
    """Claude 分析用の軽量盤面サマリ(公開情報 + 自手札)。"""
    me, opp = state.players[me_idx], state.players[1 - me_idx]

    def side(p, hidden_hand):
        d = {
            "leader": getattr(getattr(p.leader, "card", None), "name", "?"),
            "life": len(getattr(p, "life", []) or []),
            "don_active": int(getattr(p, "don_active", 0) or 0),
            "field": [f"{ip.card.name}({ip.power})" for ip in getattr(p, "characters", []) or []],
        }
        if hidden_hand:
            d["hand_count"] = len(getattr(p, "hand", []) or [])
        else:
            d["hand"] = [f"{c.name}(c{c.cost})" for c in getattr(p, "hand", []) or []]
        return d

    return {"me": side(me, False), "opp": side(opp, True)}


def _describe(action):
    return type(action).__name__ + (
        f"({getattr(action,'hand_idx','')})" if hasattr(action, "hand_idx") else ""
    )


def _play_one_game(deck_a, deck_b, slug_a, slug_b, seed, topk):
    gpa, gpb = _gbm_path(slug_a), _gbm_path(slug_b)
    gpaths = [gpa, gpb]
    st = setup_game(deck_a, deck_b, rng=random.Random(seed),
                    first_player=seed % 2, effects_overlay=_OVERLAY)
    play_until_main(st)
    ais = [
        ExploitBeamAI(rng=random.Random(seed * 3 + 1), deck_analysis={"deck_slug": slug_a}),
        ExploitBeamAI(rng=random.Random(seed * 5 + 2), deck_analysis={"deck_slug": slug_b}),
    ]
    traj = []       # (turn, player, winrate)
    moves = []      # 自手番の action ごとの (turn, player, action, wr_before, wr_after, drop, summary)
    n = 0
    while not st.game_over and st.turn_number < 50 and n < 1500:
        cur = st.turn_player_idx
        if st.phase == Phase.MAIN:
            wr_b = _winrate(st, cur, gpaths[cur])
            if wr_b is not None:
                traj.append((st.turn_number, cur, round(wr_b, 3)))
            # action の前後で acting player の勝率変化を測る
            try:
                summary = _state_summary(st, cur)
                # 実際に打たれる action を得るため choose は play_one_action に任せ、
                # before 状態を保存 → 1 action 適用 → after 勝率
                from engine.game import legal_actions
                legal = legal_actions(st)
                play_one_action(st, ais[cur], ais[1 - cur])
                wr_a = _winrate(st, cur, gpaths[cur]) if not st.game_over else None
                if wr_b is not None and wr_a is not None:
                    drop = wr_a - wr_b
                    moves.append({
                        "turn": st.turn_number, "player": cur,
                        "wr_before": round(wr_b, 3), "wr_after": round(wr_a, 3),
                        "drop": round(drop, 3), "n_legal": len(legal),
                        "summary": summary,
                    })
            except Exception:
                break
        else:
            try:
                play_one_action(st, ais[cur], ais[1 - cur])
            except Exception:
                break
        n += 1
    if not st.game_over:
        return None
    winner = getattr(st, "winner", -1)
    # 悪手候補 = 自手番で自分の勝率が最も下がった手 top-K(drop 昇順=最も負)
    flagged = sorted([m for m in moves if m["drop"] < 0], key=lambda m: m["drop"])[:topk]
    return {
        "deck_a": slug_a, "deck_b": slug_b, "seed": seed,
        "winner": winner, "turns": st.turn_number,
        "trajectory": traj, "flagged": flagged,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", required=True, help="deckA:deckB のリスト")
    ap.add_argument("--n-games", type=int, default=10)
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--out", default="db/_analyst/v6_selfplay_flagged.jsonl")
    a = ap.parse_args()
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    n_games = n_flagged = 0
    with open(out, "w", encoding="utf-8") as f:
        for pair in a.pairs:
            sa, sb = pair.split(":")
            da, db = _deck(sa), _deck(sb)
            for i in range(a.n_games):
                rec = _play_one_game(da, db, sa, sb, 700 + i, a.topk)
                if rec is None:
                    continue
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                n_games += 1
                n_flagged += len(rec["flagged"])
                print(f"  {sa} vs {sb} seed{700+i}: winner={rec['winner']} "
                      f"turns={rec['turns']} flagged={len(rec['flagged'])}", flush=True)
    print(f"\n[done] {n_games} games, {n_flagged} 悪手候補 -> {out}")


if __name__ == "__main__":
    main()
