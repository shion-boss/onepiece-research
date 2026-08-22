# -*- coding: utf-8 -*-
"""発動コスト (手札捨て) の **効果単位の中断・再開** と、 選択待ち中のイベント drain の検証。

⭐ 背景 (2026-08-22): 選択列挙 ON (= 探索が効果中の選択を分岐する mode) で Python↔Rust の
   差分を取ったところ、 **Python 側の実バグ** が 2 件出た。

   1. `resolve_triggers` に **入口ガードが無く**、 選択待ちのままイベントを解決していた。
      pending_choice は 1 スロットしか無いので、 その状態で効果を解決すると各 primitive の
      「if state.pending_choice is not None: return」 ガード (26 箇所) が **黙って no-op** し、
      **発動コストを払ったのに効果が消える** (実例: 攻撃側の【アタック時】選択が立っている間に
      防御側 OP11-041 ナミの【相手のアタック時】が解決され、 手札 1 枚を捨てたのに +2000 が
      乗らなかった)。 ループ内には既に 「解決後に pending が立ったら break」 があり、
      「残り event は queue に残し pick 解決後に再 drain する」 とコメントもあった =
      入口ガードだけが抜けていた。

   2. 発動コストの手札捨ては `counter_discard_pick` で **効果単位に中断** し、 再開時に
      「コスト支払い → effect_indexes 指定で再発火」 する。 この経路が壊れると
      「コストだけ払って効果が出ない」 になるので、 通しで検証する。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    enqueue_event,
    load_effect_overlay,
    resolve_pending_choice,
    resolve_triggers,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent

# EB04-061 モンキー・D・ルフィ: 【登場時】 手札1枚を捨てる: 自リーダー +2000 (次の相手ターン終了時まで)
COST_DISCARD_CARD = "EB04-061"
FILLER = "OP01-013"


def _repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _setup(repo, overlay, hand_ids):
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-002"), sickness=False))
    p0.deck = [repo.get(FILLER)] * 10
    p1.deck = [repo.get(FILLER)] * 10
    p0.hand = [repo.get(c) for c in hand_ids]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(7),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    p0.don_active = 10
    return st, p0, p1


def test_resolve_triggers_does_not_drain_while_choice_pending():
    """選択待ちが立っている間は **イベントを解決しない** (キューに残す)。

    これが無いと primitive の pending ガードが黙って no-op し、
    「コストは払ったのに効果が消える」 が起きる。
    """
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, _p1 = _setup(repo, overlay, [FILLER])
    ip = InPlay.of(repo.get(COST_DISCARD_CARD), sickness=False)
    p0.characters.append(ip)
    st.pending_choice = {"kind": "target_pick", "candidates": [], "limit": 1}
    enqueue_event(st, when="on_play", owner_idx=0,
                  source_card_id=COST_DISCARD_CARD, source_iid=ip.instance_id)
    n_before = len(st.event_queue)
    resolve_triggers(st)
    assert len(st.event_queue) == n_before, "選択待ち中は drain せずキューに残す"


def test_event_cost_discard_suspends_then_fires_after_resolve():
    """列挙 ON: 発動コストの手札捨ては選択になり、 解決後に **コスト支払い + 効果発動**。"""
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _setup(repo, overlay, [FILLER, FILLER])
    st.choice_enumeration = True
    ip = InPlay.of(repo.get(COST_DISCARD_CARD), sickness=False)
    p0.characters.append(ip)

    trigger_on_play(st, p0, p1, ip, overlay)
    resolve_triggers(st)

    assert st.pending_choice is not None, "手札捨てコストは選択になる"
    assert st.pending_choice["kind"] == "counter_discard_pick"
    assert len(st.pending_choice["candidates"]) == 2, "候補は手札全部"
    assert p0.leader.next_opp_turn_end_buff == 0, "解決前は未適用"
    assert len(p0.trash) == 0, "解決前はコスト未払い"

    resolve_pending_choice(st, [0])

    assert st.pending_choice is None
    assert len(p0.trash) == 1 and len(p0.hand) == 1, "選んだ手札 1 枚を捨てた"
    assert p0.leader.next_opp_turn_end_buff == 2000, (
        "コストを払ったら効果は必ず発動する (= 払い損にならない)"
    )


def test_event_cost_discard_declined_keeps_hand_and_effect():
    """コストとして選んだ枚数が足りなければ **効果は不発** (公式 4-10)。 手札も減らない。"""
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _setup(repo, overlay, [FILLER, FILLER])
    st.choice_enumeration = True
    ip = InPlay.of(repo.get(COST_DISCARD_CARD), sickness=False)
    p0.characters.append(ip)

    trigger_on_play(st, p0, p1, ip, overlay)
    resolve_triggers(st)
    assert st.pending_choice is not None

    resolve_pending_choice(st, [])  # 0 枚 = 払わない

    assert st.pending_choice is None
    assert len(p0.trash) == 0 and len(p0.hand) == 2, "コスト未払い = 手札はそのまま"
    assert p0.leader.next_opp_turn_end_buff == 0, "効果も発動しない"


def test_play_from_trash_pick_caps_at_limit():
    """人間が上限を超えて選んでも **engine が limit で cap** する (公式 「1枚まで」)。

    ⚠ 以前は 「渡された picks を全部登場させる」 実装で、 上限 1 の効果で 2 枚以上を
    場に出せた。 「1 枚目の【登場時】が別の選択を立てて解決が止まる」 のに救われていただけで、
    選択待ち中の drain を止めた途端に露見した (= 近似が下のバグを隠す型)。
    """
    from engine.effects import execute_effect

    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p0, p1 = _setup(repo, overlay, [])
    st.human_player_idx = 0  # 人間経路 = modal を立てる
    # トラッシュに 「コスト4以下 + 特徴 B・W」 のキャラを 3 枚置く (= 候補 3、 上限 1)
    for cid in ("OP14-085", "OP14-091", "OP14-093"):
        p0.trash.append(repo.get(cid))
    spec = {"play_from_trash": {"filter": {"cost_le": 4, "feature_contains": "B・W"}, "limit": 1}}

    execute_effect(spec, st, p0, p1, None)

    assert st.pending_choice is not None
    assert st.pending_choice["kind"] == "play_from_trash_pick"
    assert st.pending_choice["limit"] == 1
    assert len(st.pending_choice["candidates"]) == 3

    resolve_pending_choice(st, [0, 1, 2])  # 上限超えを要求する

    assert len(p0.characters) == 1, "上限 1 枚を超えて登場させない"
    assert len(p0.trash) == 2, "登場したのは 1 枚だけ"


def test_mandatory_discard_has_no_skip_option():
    """強制の 「N枚を捨てる」 に 「選ばない」 を出さない (= AI の no-op 無限ループ防止)。

    「N枚**まで**」 (up_to) は 0 枚を選べる (公式 1-3-5-1) ので従来どおり () を出す。
    """
    from engine.effects import enumerate_choice_options

    cands = [{"hand_idx": i, "card_id": "x", "name": "x"} for i in range(3)]
    forced = {"kind": "self_hand_discard_pick", "candidates": cands, "limit": 1, "up_to": False}
    optional = {"kind": "self_hand_discard_pick", "candidates": cands, "limit": 1, "up_to": True}

    assert () not in enumerate_choice_options(forced), "強制の捨てに 「選ばない」 は出さない"
    assert len(enumerate_choice_options(forced)) >= 1
    assert () in enumerate_choice_options(optional), "「N枚まで」 は 0 枚を選べる"
