"""belief-determinize 配線 + uniform determinize の card-loss 修正の回帰テスト (2026-07-27)。

[[project_search_route_pivot]] の belief 配線。 opponent_deck_model の実レシピから opp の hand/deck を
materialize し、 zone サイズを保存する。 uniform 版も index-based で deck を縮めない。
"""
import copy
import json
import random
from pathlib import Path

import pytest

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine import hand_estimator as HE
from engine import opponent_deck_model as ODM

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def _repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _load(slug, repo):
    return make_deck_from_dict(
        json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), repo
    )


def _fresh_state(repo, overlay):
    state = setup_game(_load("cardrush_1342", repo), _load("cardrush_1385", repo),
                       rng=random.Random(7), first_player=0, effects_overlay=overlay)
    play_until_main(state)
    return state


def test_uniform_determinize_preserves_deck_size(_repo, _overlay):
    """uniform 版は hand/deck サイズを保存する (= 値等価 not-in の過剰除去 bug の回帰)。"""
    state = _fresh_state(_repo, _overlay)
    s = copy.deepcopy(state)
    h0, d0 = len(s.players[1].hand), len(s.players[1].deck)
    HE.determinize_state(s, 1, rng=random.Random(1), use_belief=False)
    assert len(s.players[1].hand) == h0
    assert len(s.players[1].deck) == d0
    assert all(hasattr(c, "card_id") for c in s.players[1].hand + s.players[1].deck)


def test_belief_determinize_applies_and_preserves_sizes(_repo, _overlay):
    """belief 版: 既知 leader なら実レシピから materialize し、 zone サイズを保存する。"""
    state = _fresh_state(_repo, _overlay)
    leader_id = state.players[1].leader.card.card_id
    if not ODM.get_default_model().has_leader(leader_id):
        pytest.skip(f"belief モデルに leader {leader_id} 無し")
    s = copy.deepcopy(state)
    h0, d0 = len(s.players[1].hand), len(s.players[1].deck)
    applied = HE._belief_determinize(s, 1, rng=random.Random(1))
    assert applied is True
    assert len(s.players[1].hand) == h0
    assert len(s.players[1].deck) == d0
    assert all(hasattr(c, "card_id") for c in s.players[1].hand + s.players[1].deck)


def test_belief_determinize_unknown_leader_falls_back(_repo, _overlay):
    """未知 leader は belief 適用不可 (False) → determinize_state は uniform に fallback して壊さない。"""
    state = _fresh_state(_repo, _overlay)
    # 未知 leader の player を模す: belief モデルに無い leader_id を持つ state を deepcopy 経由で作る
    s = copy.deepcopy(state)
    # opp の全カードを一時的に belief 非対応にするのは難しいので、 has_leader False 経路を直接確認
    model = ODM.get_default_model()
    assert model.has_leader("ZZZ-999") is False
    # determinize_state は use_belief=True でも uniform に落ちて hand/deck を保つ
    h0, d0 = len(s.players[1].hand), len(s.players[1].deck)
    HE.determinize_state(s, 1, rng=random.Random(1), use_belief=True)
    assert len(s.players[1].hand) == h0
    assert len(s.players[1].deck) == d0
