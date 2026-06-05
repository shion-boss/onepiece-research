# -*- coding: utf-8 -*-
"""配備された人間対戦相手 AI (= api.main._build_default_ai_factory = SmartOpponentAI) を
**実デプロイ経路そのまま** で vs GreedyAI 実測し、 full強度(~70%)か degrade(~62%)かを判定。
ミラー (両者 同deck) で AI 質のみを isolate。 第1引数=deck slug、 第2引数=N。"""
import sys, os, json, random
sys.path.insert(0, ".")
from api.main import _build_default_ai_factory
from engine.harness import run_matchup
from engine.deck import DeckList, CardRepository
from engine.effects import load_effect_overlay
from engine.ai import GreedyAI

repo = CardRepository.from_json("db/cards.json")
overlay = load_effect_overlay("db/card_effects.json")
slug = sys.argv[1] if len(sys.argv) > 1 else "cardrush_1342"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 50
dl = DeckList.from_json(f"decks/{slug}.json", repo)
ana = json.load(open(f"decks/{slug}.analysis.json"))

deployed = _build_default_ai_factory(slug)  # SmartOpponentAI(ExploitBeam/greedy)


def greedy_fac(rng, deck_analysis=None):
    return GreedyAI(rng=rng, deck_analysis=deck_analysis)


res = run_matchup(dl, dl, n_games=N, seed=20260605,
                  ai_factory_1=deployed, ai_factory_2=greedy_fac,
                  effects_overlay=overlay, deck1_analysis=ana, deck2_analysis=ana)

# 配備AI = deck1 (player 0)、 greedy = deck2 (player 1)
p1 = res.deck1_wins
p2 = res.deck2_wins
draws = res.draws
print(f"deck={slug} N={N}")
print(f"配備AI(SmartOpponent/ExploitBeam) 勝: {p1} / greedy 勝: {p2} / draw: {draws}")
wr = p1 / N
print(f"配備AI 勝率: {wr:.1%}  =>  "
      f"{'full強度 (GBM有効)' if wr >= 0.66 else 'degrade疑い (board_eval相当)' if wr < 0.6 else '中間 (要N増)'}")
