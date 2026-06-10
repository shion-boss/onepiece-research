# -*- coding: utf-8 -*-
"""ジョズ OP08-047 optional_cost_then の cost (= 自キャラ1枚を手札に戻す) が
人間操作で踏み倒される bug の regression guard。

2026-06-10 (1456 赤青エース campaign 中に発見): optional_cost_then の cost loop が
人間 target pick で pending_choice を立てた直後に effect (= 相手キャラを戻す) を実行し、
effect の pending_choice が cost の pending_choice を上書き → cost (自キャラ返却) が
スキップされ「自分のキャラを戻さずに相手キャラだけ戻す」 不正発火 になっていた。

修正: cost / effect 各 spec 実行後に pending_choice を検知し、 残りを _continuation へ
退避 (= run_do_array と同じ halt-and-continue)。 これで cost → effect の順で 2 回 pick。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    TriggerEvent,
    _execute_event,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent


def _setup():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP13-002"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP13-002"), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    jozu = InPlay.of(repo.get("OP08-047"), sickness=True)   # ジョズ (cost6, 7000)
    other = InPlay.of(repo.get("ST22-002"), sickness=False)  # イゾウ (cost1) = 戻す対象
    p0.characters = [jozu, other]
    # 相手に cost6 以下のキャラ (= ハンコック cost6) を 1 体
    hancock = InPlay.of(repo.get("OP07-051"), sickness=False)
    p1.characters = [hancock]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.human_player_idx = 0
    st.turn_player_idx = 0
    p0.don_active = 10
    return st, p0, p1, jozu, other, hancock


def test_jozu_cost_is_enforced_on_human_path():
    """人間 ジョズ: 「自キャラ返却 (cost) → 相手キャラ返却 (effect)」 の 2 段 pick が
    両方 起きて、 自キャラ も 相手キャラ も 場 から 手札 へ 戻る。"""
    st, p0, p1, jozu, other, hancock = _setup()
    _execute_event(st, TriggerEvent(
        when="on_play", owner_idx=0,
        source_card_id="OP08-047", source_iid=jozu.instance_id,
    ))
    # 1) 任意コスト pay/skip の確認 modal
    assert st.pending_choice is not None
    assert st.pending_choice.get("kind") == "optional_cost_confirm"
    resolve_pending_choice(st, [1])  # pay

    # 2) ★ 修正の核心: 次は「自キャラを戻す」 cost の target pick が来る (= 旧 bug では
    #    ここが いきなり 相手キャラ pick で cost が踏み倒されていた)
    assert st.pending_choice is not None, "cost の pick modal が立っていない"
    assert st.pending_choice.get("kind") == "target_pick"
    cand_iids = [c["iid"] for c in st.pending_choice["candidates"]]
    assert other.instance_id in cand_iids, "自キャラ (イゾウ) が cost 候補に出ていない"
    assert hancock.instance_id not in cand_iids, "相手キャラが cost 候補に混入している"
    pick = cand_iids.index(other.instance_id)
    resolve_pending_choice(st, [pick])

    # 3) 続いて 相手キャラ (cost6以下) を戻す effect の target pick
    assert st.pending_choice is not None, "effect の pick modal が立っていない"
    assert st.pending_choice.get("kind") == "target_pick"
    cand_iids2 = [c["iid"] for c in st.pending_choice["candidates"]]
    assert hancock.instance_id in cand_iids2
    pick2 = cand_iids2.index(hancock.instance_id)
    resolve_pending_choice(st, [pick2])

    # 4) 検証: 自キャラ (イゾウ) は cost で 手札へ、 相手 ハンコック は effect で 手札へ。
    assert st.pending_choice is None
    p0_iids = [c.instance_id for c in p0.characters]
    assert other.instance_id not in p0_iids, "cost の 自キャラ返却 が 行われていない (踏み倒し)"
    assert jozu.instance_id in p0_iids, "ジョズ 本体 は 場 に 残るべき"
    assert any(c.card_id == "ST22-002" for c in p0.hand), "イゾウ が 手札に戻っていない"
    assert hancock.instance_id not in [c.instance_id for c in p1.characters], \
        "相手 ハンコック が 戻っていない"
    assert any(c.card_id == "OP07-051" for c in p1.hand), "ハンコック が 相手手札に戻っていない"


def test_jozu_cost_unpayable_skips_effect():
    """自キャラが ジョズ 本体のみ (= 戻す other が無い) なら cost 不能 → 相手キャラは
    戻らない (= : 以降の効果も不発)。"""
    st, p0, p1, jozu, other, hancock = _setup()
    p0.characters = [jozu]  # other を 除去 → 戻せる自キャラ無し
    _execute_event(st, TriggerEvent(
        when="on_play", owner_idx=0,
        source_card_id="OP08-047", source_iid=jozu.instance_id,
    ))
    # cost 不能 なので 任意コスト modal すら 立たない (= 不発)
    # (= 立っても pay 後に何も起きない。 いずれにせよ ハンコックは場に残る)
    if st.pending_choice is not None and st.pending_choice.get("kind") == "optional_cost_confirm":
        resolve_pending_choice(st, [1])
    assert hancock.instance_id in [c.instance_id for c in p1.characters], \
        "戻せる自キャラが無いのに 相手ハンコックが戻った (= cost 踏み倒し)"
