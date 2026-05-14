# -*- coding: utf-8 -*-
"""
deck_classifier Phase 7C テスト (= 2026-05-14)
===============================================

ベイズ Naive Bayes deck classifier の動作検証:
- 学習データ読込 (= 18 archetype × 106 recipe)
- leader 単独で archetype を高確率特定
- 観測カードでベイズ更新の精度向上
- alias 統合 (= 空島ルフィ ↔ 黄ルフィ(OP15))
- 未知 leader への fallback
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.deck_classifier import (
    ARCHETYPE_ALIASES,
    DEFAULT_PRIORS,
    DeckClassifier,
    get_default_classifier,
    reset_default_classifier,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, opp_leader_id, opp_field_card_ids=()):
    """opp に指定 leader + 場のキャラを持たせた state を作る。"""
    me = Player(name="me", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="opp", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    opp.characters = [InPlay.of(repo.get(cid), sickness=False) for cid in opp_field_card_ids]
    state = GameState(
        players=[me, opp],
        phase=Phase.MAIN,
        rng=random.Random(1),
    )
    return state


# ─────────────────────────────────────────────────────
# 学習データ読込
# ─────────────────────────────────────────────────────


def test_default_classifier_loads_archetypes():
    """DEFAULT_CLASSIFIER が active + archive を学習し、 想定 archetype を含む。"""
    reset_default_classifier()
    clf = get_default_classifier()
    assert clf.n_recipes > 50, f"学習 recipes ≥ 50 のはず ({clf.n_recipes})"
    assert clf.vocab_size > 100, f"vocab ≥ 100 のはず ({clf.vocab_size})"

    # 主要 archetype が含まれる
    archetypes = set(clf.card_probs.keys())
    for expected in ["紫エネル", "赤青ルーシー", "青黄ナミ", "緑ミホーク"]:
        assert expected in archetypes, f"{expected} が学習データに含まれていない"


def test_priors_sum_to_one():
    """priors は正規化されて sum = 1.0。"""
    clf = get_default_classifier()
    total = sum(clf.priors.values())
    assert abs(total - 1.0) < 1e-9, f"priors 総和 = 1.0 のはず ({total})"


def test_archetype_leader_mapping():
    """archetype → 代表 leader の mapping が正しい。"""
    clf = get_default_classifier()
    expected = {
        "紫エネル": "OP15-058",
        "赤青ルーシー": "OP15-002",
        "青黄ナミ": "OP11-041",
        "緑ミホーク": "OP14-020",
    }
    for arch, leader in expected.items():
        assert clf.archetype_leader.get(arch) == leader, \
            f"{arch} の leader 期待 {leader}, got {clf.archetype_leader.get(arch)}"


# ─────────────────────────────────────────────────────
# leader 単独 classification
# ─────────────────────────────────────────────────────


def test_classify_by_leader_alone_high_confidence():
    """leader だけで該当 archetype が高確率 (= ~0.99+)。"""
    clf = get_default_classifier()
    # OP15-058 → 紫エネル がほぼ確定
    probs = clf.classify(observed_card_ids=[], opp_leader_id="OP15-058")
    assert probs.get("紫エネル", 0) > 0.95, \
        f"紫エネル ≥ 0.95 のはず ({probs.get('紫エネル', 0)})"


def test_classify_no_leader_no_observations():
    """leader 無し + 観測 0 → prior に近い分布。"""
    clf = get_default_classifier()
    probs = clf.classify(observed_card_ids=[], opp_leader_id=None)
    # prior の top (= 紫エネル) が最も高い
    top_arch = max(probs, key=probs.get)
    assert top_arch == "紫エネル", f"prior top は 紫エネル のはず ({top_arch})"


# ─────────────────────────────────────────────────────
# 観測カードでベイズ更新
# ─────────────────────────────────────────────────────


def test_classify_with_observed_cards_refines():
    """leader + 観測カードで信頼度が さらに上がる (= 同じ archetype の場合)。"""
    clf = get_default_classifier()
    # leader だけの確率
    p_alone = clf.classify(observed_card_ids=[], opp_leader_id="OP15-058")
    # 紫エネル の典型カード (= OP15-066 サトリ、 OP15-076 雷獣) を観測
    p_with_obs = clf.classify(
        observed_card_ids=["OP15-066", "OP15-076"],
        opp_leader_id="OP15-058",
    )
    # 観測ありで信頼度はもう少し高くなるか少なくとも下がらない
    assert p_with_obs.get("紫エネル", 0) >= p_alone.get("紫エネル", 0) - 1e-6


def test_top_archetype_with_min_confidence():
    """top_archetype 関数: 信頼度フィルタ付き選択。"""
    clf = get_default_classifier()
    # 紫エネル leader: 高信頼で 紫エネル が返る
    result = clf.top_archetype(
        observed_card_ids=[],
        opp_leader_id="OP15-058",
        min_confidence=0.9,
    )
    assert result is not None
    arch, prob = result
    assert arch == "紫エネル"
    assert prob > 0.9


def test_top_archetype_returns_none_for_low_confidence():
    """min_confidence 超えない場合 None。"""
    clf = get_default_classifier()
    # leader 不明 + 観測 0 → どの archetype も低信頼
    result = clf.top_archetype(
        observed_card_ids=[],
        opp_leader_id=None,
        min_confidence=0.5,  # 50% 以上要求 → どの prior も 50% 未満
    )
    assert result is None


# ─────────────────────────────────────────────────────
# alias 統合
# ─────────────────────────────────────────────────────


def test_alias_unifies_archetypes():
    """空島ルフィ ↔ 黄ルフィ(OP15) は 統合されて 1 archetype に。"""
    clf = get_default_classifier()
    # ARCHETYPE_ALIASES で 「空島ルフィ → 黄ルフィ（OP15）」 に正規化される
    archetypes = set(clf.card_probs.keys())
    assert "空島ルフィ" not in archetypes, "alias 元 (空島ルフィ) は存在しないはず"
    assert "黄ルフィ（OP15）" in archetypes, "alias 先 (黄ルフィ(OP15)) が正規名"


def test_op15_098_leader_classifies_as_yellow_luffy():
    """OP15-098 leader → 黄ルフィ(OP15) として分類 (= alias 統合後)。"""
    clf = get_default_classifier()
    probs = clf.classify(observed_card_ids=[], opp_leader_id="OP15-098")
    assert probs.get("黄ルフィ（OP15）", 0) > 0.9


# ─────────────────────────────────────────────────────
# state-based classification
# ─────────────────────────────────────────────────────


def test_classify_from_state_uses_leader_and_field():
    """classify_from_state が state から opp 情報を抽出して分類。"""
    repo = _repo()
    clf = get_default_classifier()

    # opp leader = 紫エネル
    state = _make_state(repo, opp_leader_id="OP15-058")
    probs = clf.classify_from_state(state, opp_idx=1)
    assert probs.get("紫エネル", 0) > 0.9


# ─────────────────────────────────────────────────────
# 未知 leader への fallback
# ─────────────────────────────────────────────────────


def test_unknown_leader_returns_distribution():
    """未学習 leader でも何らかの確率分布を返す (= error なし)。"""
    clf = get_default_classifier()
    # OP01-001 (ゾロ) は active pool に無い (= 旧 starter デッキ)
    probs = clf.classify(observed_card_ids=[], opp_leader_id="OP01-001")
    assert len(probs) > 0
    total = sum(probs.values())
    assert abs(total - 1.0) < 1e-6
    # 全 archetype に対して leader 不一致 → priors のみで決定
    # top は prior 最大 = 紫エネル
    top_arch = max(probs, key=probs.get)
    assert top_arch == "紫エネル"


# ─────────────────────────────────────────────────────
# build() 単体 (= デフォルト以外の data)
# ─────────────────────────────────────────────────────


def test_build_with_custom_priors():
    """カスタム priors で再学習可能。"""
    decks_dir = ROOT / "decks"
    custom_priors = {"紫エネル": 50.0, "赤青ルーシー": 50.0}
    clf = DeckClassifier.build(
        recipes_dirs=[decks_dir],
        priors=custom_priors,
        alpha=1.0,
    )
    # 紫エネル と 赤青ルーシー がほぼ均等 (= 観測無しなら)
    probs = clf.classify(observed_card_ids=[], opp_leader_id=None)
    p_enel = probs.get("紫エネル", 0)
    p_lucy = probs.get("赤青ルーシー", 0)
    # その 2 つが top 候補だが、 active pool の他デッキも含まれるので 50% 均等とは限らない
    # ただし custom priors を反映、 他 archetype は historical_prior_pct=0.5%
    assert p_enel > 0.05, f"紫エネル prior が反映されてるはず ({p_enel})"
    assert p_lucy > 0.05, f"赤青ルーシー prior が反映されてるはず ({p_lucy})"
