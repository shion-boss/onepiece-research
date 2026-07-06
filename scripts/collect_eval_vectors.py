"""現最強AI(配備 ExploitBeam)同士の対戦を、 多軸評価関数で計測してデータ化(ohtsuki 設計)。

各ターンで「ターン開始 state(orig)→ ターン終了 state(cur)」の評価関数ベクトルを、 ターンプレイヤー
視点で記録 + そのプレイヤーの最終勝敗。 = 「この評価値の時にこう動いた結果どうなったか」の学習/分析源。
出力 jsonl の各行 = {game, turn, player, deck, vec:{軸:値}, next_vec:{...}, won}。
  vec      : このターンの塊が達成した評価ベクトル(orig→cur delta 系 + cur 絶対系)
  next_vec : 次の自分のターンの vec(= 塊の帰結。 状況が良くなったか = advantage 分析用)
  won      : そのプレイヤーが最終的に勝ったか

  .venv/bin/python scripts/collect_eval_vectors.py --n-games 30 \
      --decks cardrush_1454 tcgportal_calgara tcgportal_bonney --out db/_analyst/eval_vectors.jsonl
"""
from __future__ import annotations
import argparse, json, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.core import Phase
from engine.exploit_beam_ai import ExploitBeamAI
from engine.plan_search import fast_clone
from engine import eval_functions as EF

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _deck(slug):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


def _play(deck_a, deck_o, slug_a, slug_o, seed):
    """1 game。 各ターン頭で orig を clone、 ターン終了で cur を取り eval_vector を記録。
    戻り値 = [(turn, player_idx, vec)] の list + winner。"""
    st = setup_game(deck_a, deck_o, rng=random.Random(seed), first_player=seed % 2, effects_overlay=_OVERLAY)
    play_until_main(st)
    ais = [ExploitBeamAI(rng=random.Random(seed * 3 + 1), deck_analysis={"deck_slug": slug_a}),
           ExploitBeamAI(rng=random.Random(seed * 5 + 2), deck_analysis={"deck_slug": slug_o})]
    records = []  # (turn, player, vec)
    orig = None
    cur_turn_player = None
    plan_acc = []  # そのターンプレイヤーが打った行動列(= 推論軸 forced_defense/effects_used 等が読む plan)
    k = 0
    while not st.game_over and st.turn_number < 50 and k < 1500:
        tp = st.turn_player_idx
        if tp != cur_turn_player:
            # 前ターンの締め: 前プレイヤーの vec を記録(orig=前ターン頭、 cur=今、 plan=そのターンの行動列)
            if orig is not None and cur_turn_player is not None:
                try:
                    vec = EF.eval_vector(orig, st, plan_acc, cur_turn_player)
                    records.append((st.turn_number, cur_turn_player, vec))
                except Exception:
                    pass
            orig = fast_clone(st)
            cur_turn_player = tp
            plan_acc = []
        try:
            action = play_one_action(st, ais[tp], ais[1 - tp])
            plan_acc.append(action)
        except Exception:
            break
        k += 1
    winner = getattr(st, "winner", -1)
    return records, winner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=20)
    ap.add_argument("--decks", nargs="+", default=["cardrush_1454", "tcgportal_calgara", "tcgportal_bonney"])
    ap.add_argument("--out", default="db/_analyst/eval_vectors.jsonl")
    a = ap.parse_args()
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    decks = a.decks
    n_rows = n_games = 0
    with open(out, "w", encoding="utf-8") as f:
        for i in range(a.n_games):
            sa = decks[i % len(decks)]
            so = decks[(i + 1 + i // len(decks)) % len(decks)]
            recs, winner = _play(_deck(sa), _deck(so), sa, so, 1000 + i)
            if winner < 0:
                continue
            # player→次の同playerターンの vec を next_vec に(塊帰結)
            by_player = {0: [], 1: []}
            for turn, pl, vec in recs:
                by_player[pl].append((turn, vec))
            for pl in (0, 1):
                seq = by_player[pl]
                deck_slug = sa if pl == 0 else so
                for j, (turn, vec) in enumerate(seq):
                    nvec = seq[j + 1][1] if j + 1 < len(seq) else None
                    f.write(json.dumps({"game": i, "turn": turn, "player": pl,
                                        "deck": deck_slug, "vec": vec, "next_vec": nvec,
                                        "won": int(winner == pl)}) + "\n")
                    n_rows += 1
            f.flush()
            n_games += 1
            if n_games % 5 == 0:
                print(f"  {n_games}/{a.n_games} games, {n_rows} rows", flush=True)
    print(f"[done] {n_games} games, {n_rows} turn-records -> {out}")


if __name__ == "__main__":
    main()
