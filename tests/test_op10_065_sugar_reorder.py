# -*- coding: utf-8 -*-
"""OP10-065 シュガー activate_main の 残り並び替え regression。

公式: 自分のデッキの上から5枚を見て、特徴《ドンキホーテ海賊団》を持つカード1枚までを
公開し手札に加える。その後、残りを好きな順番でデッキの下に置く。

bug (2026-06-04 修正前):
  search_top_n_bottom_reorder の picks に UI (ScryDeckReorderModal 流用) が付ける
  「上/下」 位置フラグ (= 末尾 0/1) が remaining の index と 誤解釈 され、
  remaining[flag] が 複製 → 残り4枚 が 5枚 に 増える (= デッキ に ファントム カード)。
このテストは その picks 形式 でも カード 複製/欠落 が 起きない こと を 保証 する。
"""
from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import pytest

from engine.deck import CardRepository, DeckList
from engine.core import InPlay, Category
from engine.game import setup_game
from engine.effects import (
    fire_activate_main,
    resolve_pending_choice,
    load_effect_overlay,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


@pytest.fixture(scope="module")
def overlay() -> dict:
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _ids(cards):
    return [c.card_id for c in cards]


def _build_sugar_state(repo, overlay):
    """シュガー が 場 + デッキ上5枚 = [ドフラ, 非, ドフラ, 非, 非] の human state。"""
    don_feat = "ドンキホーテ海賊団"
    haspirate, nonpirate = [], []
    seen = set()
    for c in repo._by_id.values():
        if c.card_id in seen or c.category != Category.CHARACTER:
            continue
        seen.add(c.card_id)
        feat = "/".join(c.features or ())
        if don_feat in feat:
            if len(haspirate) < 4:
                haspirate.append(c.card_id)
        elif len(nonpirate) < 12:
            nonpirate.append(c.card_id)

    leader = repo.get("OP01-001")
    top5 = [haspirate[0], nonpirate[0], haspirate[1], nonpirate[1], nonpirate[2]]
    main_ids = top5 + nonpirate[3:] + haspirate[2:]
    while len(main_ids) < 50:
        main_ids.append(nonpirate[len(main_ids) % len(nonpirate)])
    main_ids = main_ids[:50]
    opp_ids = [nonpirate[i % len(nonpirate)] for i in range(50)]

    me_deck = DeckList(name="me", leader=leader,
                       main=[repo.get(x) for x in main_ids], slug="t_me")
    opp_deck = DeckList(name="opp", leader=leader,
                        main=[repo.get(x) for x in opp_ids], slug="t_opp")
    state = setup_game(me_deck, opp_deck, rng=random.Random(42),
                       first_player=0, effects_overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    state.turn_player_idx = 0
    state.human_player_idx = 0
    # デッキ上5枚 を 意図 した 並び に 強制
    me.deck = [repo.get(x) for x in top5] + list(me.deck)
    sugar = InPlay.of(repo.get("OP10-065"), rested=False, sickness=False)
    me.characters.append(sugar)
    me.don_active = 3
    me.don_rested = 0
    return state, me, opp, sugar


def _fire_and_pick_one(state, me, opp, sugar, overlay):
    eff = overlay.get("OP10-065").effects[0]
    fire_activate_main(state, me, opp, sugar, eff)
    pc = state.pending_choice
    assert pc and pc.get("kind") == "search_top_n", f"search_top_n modal 未発火: {pc}"
    cards = pc.get("cards", [])
    matching = [c["idx"] for c in cards if c.get("matches_filter")]
    assert matching, "ドフラ 海賊団 候補 が 公開 cards に ない"
    resolve_pending_choice(state, matching[:1])  # 1 枚 手札 へ


@pytest.mark.parametrize("reorder_picks", [
    [3, 2, 1, 0, 1],   # 旧UI形: full perm + 下フラグ(1)  ← 元バグ trigger
    [3, 2, 1, 0, 0],   # 旧UI形: full perm + 上フラグ(0)
    [0, 1, 2, 3],      # 正規 perm (フラグ なし)
    [1],               # 空order + フラグ のみ (= UI が candidates 読めず order 空)
    [],                # おまかせ (= 元順序 fallback)
])
def test_sugar_reorder_no_duplication_or_loss(repo, overlay, reorder_picks):
    state, me, opp, sugar = _build_sugar_state(repo, overlay)
    deck_before = list(me.deck)
    hand_before = list(me.hand)
    multiset_before = Counter(_ids(deck_before) + _ids(hand_before))

    _fire_and_pick_one(state, me, opp, sugar, overlay)

    pc2 = state.pending_choice
    assert pc2 and pc2.get("kind") == "search_top_n_bottom_reorder", \
        f"reorder modal 未発火: {pc2}"
    remaining = list(getattr(state, "search_top_n_pending_remaining", []) or [])
    assert len(remaining) == 4, f"残り は 4 枚 の はず: {len(remaining)}"

    resolve_pending_choice(state, reorder_picks)

    # (1) 枚数 保存: deck は 1 枚 (= 手札 へ) 減った だけ、 重複/欠落 なし
    assert len(me.deck) == len(deck_before) - 1, \
        f"deck 枚数 異常 (複製/欠落?): {len(me.deck)} != {len(deck_before) - 1}"
    # (2) 手札 は ちょうど 1 枚 増えた
    assert len(me.hand) == len(hand_before) + 1
    # (3) deck+hand の card_id multiset が 不変 (= 取得カード は デッキ から 移動、 新規生成 なし)
    multiset_after = Counter(_ids(me.deck) + _ids(me.hand))
    assert multiset_after == multiset_before, \
        f"card multiset が 変化 (複製/欠落): {multiset_after - multiset_before} / {multiset_before - multiset_after}"
    # (4) 残り 4 枚 が 確かに デッキ 底 4 枚 に いる (= trash や 消失 して ない)
    bottom4 = set(_ids(me.deck[-4:]))
    assert bottom4 == set(_ids(remaining)), \
        f"底4枚 が 残り と 不一致: {bottom4} vs {set(_ids(remaining))}"
    # pending クリア
    assert state.pending_choice is None
    assert getattr(state, "search_top_n_pending_remaining", None) is None


def test_sugar_reorder_respects_user_order(repo, overlay):
    """末尾 フラグ が 付いて も、 ユーザー が 指定 した 並び順 が 底 に 反映 される。"""
    state, me, opp, sugar = _build_sugar_state(repo, overlay)
    _fire_and_pick_one(state, me, opp, sugar, overlay)
    remaining = list(getattr(state, "search_top_n_pending_remaining", []) or [])
    assert len(remaining) == 4
    # 逆順 [3,2,1,0] を 底 へ。 末尾 に 下フラグ(1) が 付く 旧UI形
    resolve_pending_choice(state, [3, 2, 1, 0, 1])
    # deck.extend(ordered) → 底 は ... ordered[-1] が 一番 下。 ordered=[r3,r2,r1,r0]
    expected_bottom = [remaining[3].card_id, remaining[2].card_id,
                       remaining[1].card_id, remaining[0].card_id]
    assert _ids(me.deck[-4:]) == expected_bottom, \
        f"底4枚 順序 が 指定 と 不一致: {_ids(me.deck[-4:])} != {expected_bottom}"
