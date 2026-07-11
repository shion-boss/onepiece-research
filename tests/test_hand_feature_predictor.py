# -*- coding: utf-8 -*-
"""HandFeaturePredictor (ohtsuki 案 ③、 デッキ採用率 prior 根拠の手札特徴予測) の基本テスト。"""
import json
import random
from pathlib import Path

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.hand_feature_predictor import HandFeaturePredictor, FEATURES

ROOT = Path(__file__).resolve().parent.parent
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _deck(slug):
    return make_deck_from_dict(
        json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


def test_predict_returns_valid_probabilities():
    hp = HandFeaturePredictor()
    st = setup_game(_deck("cardrush_1342"), _deck("cardrush_1454"),
                    rng=random.Random(1), first_player=0, effects_overlay=_OV)
    play_until_main(st)
    lid = _deck("cardrush_1454").leader.card_id
    p = hp.predict(lid, st, 1)
    assert set(p.keys()) == set(FEATURES)
    for f, v in p.items():
        assert 0.0 <= v <= 1.0, f"{f}={v} out of [0,1]"


def test_generalizes_across_leaders():
    """異なる leader は異なる採用率 prior を返す (per-deck 学習不要の汎化)。"""
    hp = HandFeaturePredictor()
    enel = hp.deck_prior(_deck("cardrush_1454").leader.card_id)
    calgara = hp.deck_prior(_deck("tcgportal_calgara").leader.card_id)
    # カルガラ (control) は 2000カウンター採用が エネルより多い
    assert calgara["counter2000"] > enel["counter2000"]


def test_unknown_leader_falls_back_to_average():
    hp = HandFeaturePredictor()
    prof = hp.deck_prior("NONEXISTENT-999")
    assert set(prof.keys()) == set(FEATURES)
    for f in FEATURES:
        assert prof[f] >= 0.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
