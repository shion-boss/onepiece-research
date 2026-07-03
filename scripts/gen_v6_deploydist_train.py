"""ExploitBeam_v6 self-play(=配備分布)の (v6特徴, 勝敗) 訓練データを生成。

配備 value の miscalibration は train/deploy 分布ズレが濃厚(value は beam-vs-greedy/旧
データで訓練、 配備は ExploitBeam 同士)。 これを直すため、 **配備そのもの(ExploitBeam_v6
self-play)の局面 → 勝敗** を訓練データにして value を再学習する(value iteration = 現 policy
の対局で value を訓練)。

target deck を idx0 固定で varied 相手と ExploitBeam 対戦させ、 各 MAIN 手番頭で
features(state, 0, v6=True) + y(target 勝=1) を記録 → jsonl {feat, y}。

  .venv/bin/python scripts/gen_v6_deploydist_train.py --deck cardrush_1454 \
      --opponents cardrush_1454 cardrush_1342 tcgportal_bonney tcgportal_calgara \
      --n-games 12 --out db/_analyst/deploydist_cardrush_1454.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.core import Phase
from engine.exploit_beam_ai import ExploitBeamAI
from engine.gbm_value import features

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _deck(slug):
    return make_deck_from_dict(
        json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO
    )


def _play(deck_t, deck_o, slug_t, slug_o, seed):
    """target=idx0 固定。 各 MAIN 手番頭で target 視点 v6 特徴を集め、 終局勝敗をラベルに。"""
    st = setup_game(deck_t, deck_o, rng=random.Random(seed),
                    first_player=seed % 2, effects_overlay=_OVERLAY)
    play_until_main(st)
    ais = [
        ExploitBeamAI(rng=random.Random(seed * 3 + 1), deck_analysis={"deck_slug": slug_t}),
        ExploitBeamAI(rng=random.Random(seed * 5 + 2), deck_analysis={"deck_slug": slug_o}),
    ]
    feats = []
    last_tp = None
    n = 0
    while not st.game_over and st.turn_number < 50 and n < 1500:
        cur = st.turn_player_idx
        if st.phase == Phase.MAIN and cur != last_tp:  # 手番頭でサンプル
            try:
                feats.append(features(st, 0, v6=True))  # target(idx0)視点 38dim
            except Exception:
                pass
            last_tp = cur
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not st.game_over:
        return []
    y = 1 if getattr(st, "winner", -1) == 0 else 0  # target=idx0 が勝ったか
    return [(f, y) for f in feats]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--opponents", nargs="+", required=True)
    ap.add_argument("--n-games", type=int, default=12)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    dt = _deck(a.deck)
    n_games = n_samp = n_win = 0
    with open(out, "w", encoding="utf-8") as f:
        for opp in a.opponents:
            do = _deck(opp)
            for i in range(a.n_games):
                rows = _play(dt, do, a.deck, opp, 800 + i)
                if not rows:
                    continue
                for feat, y in rows:
                    f.write(json.dumps({"feat": feat, "y": y}) + "\n")
                    n_samp += 1
                f.flush()
                n_games += 1
                n_win += rows[0][1]
                print(f"  {a.deck} vs {opp} seed{800+i}: y={rows[0][1]} (+{len(rows)} samples)",
                      flush=True)
    print(f"\n[done] {n_games} games, {n_samp} samples, target 勝率={n_win/max(1,n_games)*100:.0f}% "
          f"-> {out}")


if __name__ == "__main__":
    main()
