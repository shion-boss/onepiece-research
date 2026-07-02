"""agnostic value 用の own-deck 条件付け feature (gbm_value v10) のテスト。

v10 = v8(v6 + 相手 role vector)+ 自 leader role vector(myrole)。 多デッキ pool で学習する
1 個の agnostic value が「自 archetype × 相手 archetype × 盤面」で判断を可変化するための
inference 計算可能な条件付け。
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from engine.deck import CardRepository, make_deck_from_dict
from engine.game import setup_game, play_until_main
from engine import gbm_value as gv

_ROOT = Path(__file__).resolve().parent.parent


def _state(me_slug: str, opp_slug: str):
    repo = CardRepository.from_json(_ROOT / "db" / "cards.json")
    me = make_deck_from_dict(json.loads((_ROOT / "decks" / f"{me_slug}.json").read_text(encoding="utf-8")), repo)
    opp = make_deck_from_dict(json.loads((_ROOT / "decks" / f"{opp_slug}.json").read_text(encoding="utf-8")), repo)
    st = setup_game(me, opp, rng=random.Random(1), first_player=0)
    play_until_main(st)
    return st


def test_v10_dimension_matches_keys():
    st = _state("cardrush_1454", "cardrush_1342")
    f = gv.features(st, 0, v10=True)
    assert len(f) == len(gv.FEATURE_KEYS_V10) == 54


def test_v10_is_superset_of_v8():
    """v10[:46] == v8 (= 列 slice 互換、 gbm_score の次元自動判別が安全)。"""
    st = _state("cardrush_1454", "cardrush_1342")
    f10 = gv.features(st, 0, v10=True)
    f8 = gv.features(st, 0, v8=True)
    assert f10[: len(f8)] == f8


def test_myrole_reflects_own_leader_and_swaps_with_perspective():
    st = _state("cardrush_1454", "cardrush_1342")  # p0=エネル OP15-058, p1=ドフラ OP14-060
    f0 = gv.features(st, 0, v10=True)
    f1 = gv.features(st, 1, v10=True)
    my0 = f0[-8:]        # p0 視点の自 role (= エネル)
    opp0 = f0[-16:-8]    # p0 視点の相手 role (= ドフラ)
    my1 = f1[-8:]        # p1 視点の自 role (= ドフラ)
    # 視点を変えると「自分の役割ベクトル」が入れ替わる: p0 の相手 role == p1 の自 role
    assert opp0 == my1
    # エネルとドフラは別 archetype なので自 role ベクトルは異なる
    assert my0 != my1


def test_myrole_zero_for_unknown_leader():
    """leader_role_vectors.json に無い leader は全0 (= neutral、 汎化 fallback)。"""
    class _C:
        card_id = "ZZ99-999"

    class _IP:
        card = _C()

    class _P:
        leader = _IP()

    class _S:
        players = [_P(), _P()]

    vec = gv._my_role_vector(_S(), 0)
    assert vec == [0.0] * len(gv._ROLE_DIMS)


def test_other_versions_unchanged():
    """v10 追加で既存 version の次元が変わっていないこと (無回帰)。"""
    st = _state("cardrush_1454", "cardrush_1342")
    assert len(gv.features(st, 0, rich=True)) == len(gv.FEATURE_KEYS_V2) == 21
    assert len(gv.features(st, 0, v6=True)) == len(gv.FEATURE_KEYS_V6) == 38
    assert len(gv.features(st, 0, v8=True)) == len(gv.FEATURE_KEYS_V8) == 46
