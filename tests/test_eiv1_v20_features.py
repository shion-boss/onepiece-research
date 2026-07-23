"""v19 (盤面の個体解像度) / v20 (除去の射程 × 的) のテスト。

⚠ 一番大事なのは **live state と保存済み snapshot で列が一致すること**。 学習は corpus の
snapshot、 推論は live state から同じ列を作るので、 ズレると value が静かに壊れる。
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from engine import card_magnitudes as CM
from engine import gbm_value as gv
from engine.deck import CardRepository, make_deck_from_dict
from engine.eiv1_features import (
    board_detail_feats_from_snapshot, hand_reach_feats_from_snapshot,
)
from engine.game import play_until_main, setup_game
from engine.game_corpus import snapshot_state

_ROOT = Path(__file__).resolve().parent.parent


def _state(me_slug: str, opp_slug: str, seed: int = 1):
    repo = CardRepository.from_json(_ROOT / "db" / "cards.json")
    me = make_deck_from_dict(json.loads((_ROOT / "decks" / f"{me_slug}.json").read_text(encoding="utf-8")), repo)
    opp = make_deck_from_dict(json.loads((_ROOT / "decks" / f"{opp_slug}.json").read_text(encoding="utf-8")), repo)
    st = setup_game(me, opp, rng=random.Random(seed), first_player=0)
    play_until_main(st)
    return st


def test_dimensions_match_keys():
    st = _state("cardrush_1454", "cardrush_1342")
    assert len(gv.features(st, 0, v19=True)) == len(gv.FEATURE_KEYS_V19) == 84
    assert len(gv.features(st, 0, v20=True)) == len(gv.FEATURE_KEYS_V20) == 94


def test_v20_is_superset_of_v18():
    """列順が v18 ⊂ v19 ⊂ v20 であること (= 既存モデルの列を壊していない)。"""
    st = _state("cardrush_1454", "cardrush_1342")
    f18 = gv.features(st, 0, v18=True)
    f19 = gv.features(st, 0, v19=True)
    f20 = gv.features(st, 0, v20=True)
    assert f19[:len(f18)] == f18
    assert f20[:len(f19)] == f19


def test_live_matches_snapshot():
    """live state の列 == 同じ state の snapshot から復元した列 (学習と推論のズレ防止)。"""
    for seed in (1, 7, 23):
        st = _state("cardrush_1454", "cardrush_1342", seed=seed)
        for me_idx in (0, 1):
            snap = snapshot_state(st)
            snap["hero_idx"] = me_idx
            live = gv.features(st, me_idx, v20=True)
            n18 = len(gv.FEATURE_KEYS_V18)
            assert live[n18:n18 + 20] == board_detail_feats_from_snapshot(snap)
            assert live[n18 + 20:] == hand_reach_feats_from_snapshot(snap)


def test_feat_for_dim_dispatch():
    """model 次元 84/94 から正しい版が選ばれること (gbm_score の自動判別経路)。"""
    st = _state("cardrush_1454", "cardrush_1342")
    assert len(gv._feat_for_dim(st, 0, 84)) == 84
    assert len(gv._feat_for_dim(st, 0, 94)) == 94


def test_magnitude_distinguishes_removal_reach():
    """ohtsuki 指摘の核: 『コスト4以下をKO』と『コスト1以下をKO』が別の値になること。"""
    db = CM.magnitudes_db()
    reaches = {round(m["rm_play_cost"]) for m in db.values() if m["rm_play_cost"] > 0}
    assert len(reaches) >= 5, f"射程が潰れている: {reaches}"
    # 条件なし除去は条件付きより射程が大きい
    assert max(reaches) >= CM.UNCOND_COST
    # 除去を持たないカードは 0 のまま (誤検出しない)
    assert db["OP01-016"]["rm_play_cost"] == 0.0   # ナミ = デッキサーチのみ
