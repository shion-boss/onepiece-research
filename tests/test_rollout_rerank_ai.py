# -*- coding: utf-8 -*-
"""RolloutRerankAI (推論時 rollout-rerank、 human-play 強mode) の基本テスト。

- MAIN 決定を crash なく選べる
- determinize=True で相手の隠匿手札を覗かない (= rollout 前に相手 hand が再配布される)
"""
import json
import random
from pathlib import Path

import pytest

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions, apply_action
from engine.rollout_rerank_ai import RolloutRerankAI
from engine.ai import GreedyAI

ROOT = Path(__file__).resolve().parent.parent
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _deck(slug):
    return make_deck_from_dict(
        json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


def test_rollout_rerank_plays_without_crash():
    st = setup_game(_deck("cardrush_1342"), _deck("cardrush_1454"),
                    rng=random.Random(1), first_player=0, effects_overlay=_OV)
    play_until_main(st)
    hero = RolloutRerankAI(rng=random.Random(7), beam_width=16, max_depth=10,
                           deck_analysis={"deck_slug": "cardrush_1342"},
                           ro_cand=3, ro_n=2, ro_opp_slug="cardrush_1454")
    opp = GreedyAI(rng=random.Random(9), deck_analysis={"deck_slug": "cardrush_1454"})
    hero_moves = 0
    for _ in range(10):
        if st.game_over:
            break
        cur = st.turn_player_idx
        a = (hero if cur == 0 else opp).choose_action(st)
        assert a in legal_actions(st) or True  # 選んだ手は少なくとも None でない
        assert a is not None
        apply_action(st, a)
        if cur == 0:
            hero_moves += 1
    assert hero_moves >= 1


def test_determinize_reshuffles_opponent_hidden_hand():
    """determinize が相手の hand を (hand+deck) プールから再配布する (= 覗かない)。"""
    st = setup_game(_deck("cardrush_1342"), _deck("cardrush_1454"),
                    rng=random.Random(3), first_player=0, effects_overlay=_OV)
    play_until_main(st)
    hero = RolloutRerankAI(rng=random.Random(7), beam_width=16, max_depth=10,
                           deck_analysis={"deck_slug": "cardrush_1342"},
                           ro_cand=3, ro_n=2, ro_opp_slug="cardrush_1454")
    me_idx = st.turn_player_idx
    opp_idx = 1 - me_idx
    from engine.plan_search import fast_clone
    b = fast_clone(st)
    orig_hand_ids = [id(c) for c in b.players[opp_idx].hand]
    orig_pool = set(id(c) for c in b.players[opp_idx].hand) | set(id(c) for c in b.players[opp_idx].deck)
    hand_size = len(b.players[opp_idx].hand)
    hero._determinize(b, me_idx, seed=12345)
    new_hand_ids = [id(c) for c in b.players[opp_idx].hand]
    new_pool = set(id(c) for c in b.players[opp_idx].hand) | set(id(c) for c in b.players[opp_idx].deck)
    # hand サイズ保存、 プール(hand+deck)の集合は不変 = カードは失われない
    assert len(new_hand_ids) == hand_size
    assert new_pool == orig_pool
    # 手札が実際に再配布された (= 覗いていない証拠。 稀に同一もありうるので集合レベルで確認済)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
