# -*- coding: utf-8 -*-
"""OP15 弾 効果 回帰テスト バックフィル (自動生成 wave 142):
OP15-042 / OP15-043 / OP15-045 / OP15-046 / OP15-048 /
OP15-050 / OP15-051 / OP15-053 / OP15-055 / OP15-056 の 10 枚。

目的 (= test_backfill_auto_001〜141.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.effects import (
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` / optional_cost_then 内 の三形対応)。

    ⚠ 2026-08-05: 公式は 「「：」以前が発動コスト」 (cardqa_st_06)。 コロン後の条件は **効果のみ**
    を gate するので、 overlay ではその条件を `conditional` の中へ移した。
    `optional_cost_then` を持つ効果では **cost を条件の外に出す** 必要があるため、
    conditional は `effect` 配列の中に入る。 条件自体は変わっていないので、
    テストはどの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    def _dig(arr):
        for _p in arr or []:
            if not isinstance(_p, dict):
                continue
            if "conditional" in _p:
                return (_p.get("conditional") or {}).get("if") or {}
            if "optional_cost_then" in _p:
                got = _dig((_p["optional_cost_then"] or {}).get("effect") or [])
                if got:
                    return got
        return {}
    return _dig(eff.get("do") or [])


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        # ⚠ 2026-08-05: コロン後の条件を conditional / optional_cost_then の中へ移したため、
        #   目的の primitive が入れ子になっている。 平坦化して探す。
        def _flat(arr):
            out = []
            for _p in arr or []:
                if not isinstance(_p, dict):
                    continue
                if "conditional" in _p:
                    out += _flat((_p["conditional"] or {}).get("do"))
                elif "optional_cost_then" in _p:
                    out += _flat((_p["optional_cost_then"] or {}).get("effect"))
                else:
                    out.append(_p)
            return out
        for e in matches:
            if any(needle in prim for prim in _flat(e["do"])):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op15_wave142_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP15-042", "OP15-043", "OP15-045", "OP15-046", "OP15-048",
           "OP15-050", "OP15-051", "OP15-053", "OP15-055", "OP15-056"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP15-042 キュロス (CHARACTER 青 cost3 power5000):
#    【登場時】自分の手札1枚を捨てることができる：自分のリーダーが「レベッカ」の
#      場合、このキャラは、このターン中、【速攻】を得る。
#    【KO時】このキャラカードをトラッシュから手札に加える。
# --------------------------------------------------------------------------- #
def test_op15_042_on_play_condition_rebecca_leader():
    """登場時 条件: リーダー「レベッカ」 で if 成立、 非レベッカで不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-042", "on_play")
    st_ok = _state(repo, "OP15-039", overlay)   # レベッカ leader
    st_ng = _state(repo, "OP01-001", overlay)   # ゾロ (非レベッカ)
    assert eval_condition(_cond_of(eff), st_ok, st_ok.players[0]) is True, \
        "リーダー「レベッカ」で登場時条件が成立していない"
    assert eval_condition(_cond_of(eff), st_ng, st_ng.players[0]) is False, \
        "非「レベッカ」リーダーで登場時条件が成立してはいけない"


def test_op15_042_on_play_human_pay_gains_rush():
    """人間: 任意コスト (手札1捨て) → optional_cost_confirm modal → pay で
    このキャラが【速攻】を得て 手札が1枚減る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-039", overlay, human_idx=0)  # レベッカ leader
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]  # 捨てる用
    hand_before = len(me.hand)
    src = InPlay.of(repo.get("OP15-042"), sickness=True)
    me.characters = [src]  # このキャラ (= 自軍) を場に置く

    do, _ = _do(overlay, "OP15-042", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, src)
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st, [0])
    assert len(me.hand) == hand_before - 1, "任意コストの手札1捨てが起きていない"
    assert any(ip.is_rush_now for ip in [me.leader] + me.characters), \
        "払った後に 自軍キャラが【速攻】を得ていない"


def test_op15_042_on_play_ai_no_crash():
    """AI 文脈: 任意コストの 登場時効果を回しても crash せず modal も残さない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-039", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]
    src = InPlay.of(repo.get("OP15-042"), sickness=True)
    do, _ = _do(overlay, "OP15-042", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, src)
    _drain(st, [0])
    assert st.pending_choice is None, "AI 文脈で modal が残ってはいけない"


def test_op15_042_on_ko_return_self_from_trash_ai():
    """【KO時】このカードをトラッシュから手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP15-042")]
    me.hand = []
    do, _ = _do(overlay, "OP15-042", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-042"), sickness=False))
    _drain(st, [0])
    assert any(c.card_id == "OP15-042" for c in me.hand), \
        "KO時に キュロス がトラッシュから手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP15-043 ケリー・ファンク (CHARACTER 青 cost3 power3000):
#    【登場時】自分の手札から「ボビー・ファンク」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op15_043_on_play_summon_bobby_ai():
    """手札の「ボビー・ファンク」(OP15-050) を登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP15-050")]  # ボビー・ファンク
    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP15-043", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-043"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "OP15-050" for c in me.characters), \
        "手札の「ボビー・ファンク」が登場していない"
    assert len(me.hand) == hand_before - 1, "登場した分だけ手札が減っていない"


def test_op15_043_on_play_no_bobby_in_hand_noop():
    """手札に「ボビー・ファンク」が無ければ 何も登場しない (= 対象なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]  # ボビー・ファンク でない
    do, _ = _do(overlay, "OP15-043", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-043"), sickness=True))
    _drain(st, [0])
    assert not any(c.card.card_id == "OP15-050" for c in me.characters), \
        "「ボビー・ファンク」が手札に無いのに登場している"


# --------------------------------------------------------------------------- #
#  OP15-045 サイ (CHARACTER 青 cost5 power6000):
#    【ブロッカー】【登場時】自分の手札からイベント1枚を捨てることができる：
#      カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op15_045_on_play_discard_event_draw2_ai():
    """イベント1枚を捨てて 2ドロー (AI 自動)。手札=イベント1 → 捨て0残 → 2ドロー=2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP15-055")]  # 青イベント (捨てる用)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-045", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-045"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 2, \
        f"2ドローが起きていない: deck {len(me.deck)} (before {deck_before})"
    assert len(me.hand) == 2, \
        f"イベント1捨て + 2ドロー 後の手札が2でない: {len(me.hand)}"


def test_op15_045_on_play_human_optional_cost():
    """人間: optional_cost_confirm modal → pay ([1]) で 2ドロー が解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP15-055")]  # イベント
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-045", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-045"), sickness=True))
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 払う
    _drain(st, [0])
    assert len(me.deck) == deck_before - 2, "任意コスト承認後に 2ドローが起きていない"


# --------------------------------------------------------------------------- #
#  OP15-046 サボ (CHARACTER 青 cost7 power9000):
#    【ブロッカー】【登場時】自分のリーダーが特徴《ドレスローザ》を持つ場合、
#      自分の手札から特徴《ドレスローザ》を持つイベント1枚までを、発動する。
# --------------------------------------------------------------------------- #
def test_op15_046_on_play_condition_dressrosa_leader():
    """登場時 条件: 《ドレスローザ》リーダーで if 成立、 非ドレスローザで不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP15-046", "on_play")
    st_ok = _state(repo, "OP15-039", overlay)  # レベッカ (ドレスローザ)
    st_ng = _state(repo, "OP01-001", overlay)  # ゾロ (非ドレスローザ)
    assert eval_condition(_cond_of(eff), st_ok, st_ok.players[0]) is True, \
        "《ドレスローザ》リーダーで登場時条件が成立していない"
    assert eval_condition(_cond_of(eff), st_ng, st_ng.players[0]) is False, \
        "非《ドレスローザ》リーダーで登場時条件が成立してはいけない"


def test_op15_046_on_play_activate_dressrosa_event_ai():
    """手札の《ドレスローザ》イベントを発動する (= 手札から消費) (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-039", overlay)  # ドレスローザ leader
    me, opp = st.players[0], st.players[1]
    ev = repo.get("OP13-019")  # “火炎”が許さねェってよ (ドレスローザ/革命軍 イベント)
    assert "ドレスローザ" in (ev.features or ""), "テスト前提: OP13-019 は ドレスローザ"
    me.hand = [ev]
    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP15-046", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-046"), sickness=True))
    _drain(st, [0])
    assert not any(c.card_id == "OP13-019" for c in me.hand), \
        "《ドレスローザ》イベントが手札から発動 (消費) されていない"
    assert len(me.hand) == hand_before - 1, "発動したイベント分 手札が減っていない"


# --------------------------------------------------------------------------- #
#  OP15-048 チンジャオ (CHARACTER 青 cost4 power5000):
#    【登場時】自分の手札からイベント1枚を捨てることができる：カード2枚を引く。
#    【相手のターン中】【KO時】相手は自身の手札1枚をデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op15_048_on_play_discard_event_draw2_ai():
    """イベント1枚を捨てて 2ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP15-055")]  # イベント
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-048", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-048"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 2, "2ドローが起きていない"
    assert len(me.hand) == 2, f"イベント1捨て + 2ドロー 後の手札が2でない: {len(me.hand)}"


def test_op15_048_on_ko_opp_hand_to_deck_bottom_ai():
    """【KO時】相手は自身の手札1枚をデッキの下に置く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get("OP01-016"), repo.get("OP01-013")]
    opp_hand_before = len(opp.hand)
    opp_deck_before = len(opp.deck)
    do, _ = _do(overlay, "OP15-048", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-048"), sickness=False))
    _drain(st, [0])
    assert len(opp.hand) == opp_hand_before - 1, \
        f"相手の手札が1枚減っていない: {len(opp.hand)}"
    assert len(opp.deck) == opp_deck_before + 1, \
        f"相手のデッキが1枚増えていない (デッキ下へ): {len(opp.deck)}"


# --------------------------------------------------------------------------- #
#  OP15-050 ボビー・ファンク (CHARACTER 青 cost3 power3000):
#    自分の「ケリー・ファンク」がいる場合、このキャラのパワー+3000。 (静的)
# --------------------------------------------------------------------------- #
def test_op15_050_static_pump_with_kelly():
    """自軍に「ケリー・ファンク」(OP15-043) がいれば static_buff +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    bobby = InPlay.of(repo.get("OP15-050"), sickness=False)
    kelly = InPlay.of(repo.get("OP15-043"), sickness=False)
    me.characters = [bobby, kelly]
    evaluate_static_effects(st, overlay)
    assert bobby.static_buff == 3000, \
        f"「ケリー・ファンク」在で +3000 が乗っていない: {bobby.static_buff}"


def test_op15_050_static_no_pump_without_kelly():
    """「ケリー・ファンク」がいなければ static_buff +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    bobby = InPlay.of(repo.get("OP15-050"), sickness=False)
    me.characters = [bobby]
    evaluate_static_effects(st, overlay)
    assert bobby.static_buff == 0, \
        f"「ケリー・ファンク」不在で +3000 が乗ってはいけない: {bobby.static_buff}"


# --------------------------------------------------------------------------- #
#  OP15-051 モンキー・D・ルフィ (CHARACTER 青 cost3 power4000):
#    【相手のターン中】自分のリーダーが特徴《ドレスローザ》を持つ場合、
#      このキャラのパワー+3000。 (静的)
# --------------------------------------------------------------------------- #
def test_op15_051_static_pump_opp_turn_dressrosa():
    """相手ターン中 + 《ドレスローザ》リーダー で static_buff +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-039", overlay, turn_player=1)  # ドレスローザ leader / 相手ターン
    me = st.players[0]
    luffy = InPlay.of(repo.get("OP15-051"), sickness=False)
    me.characters = [luffy]
    assert eval_condition({"opp_turn": True}, st, me) is True, \
        "テスト前提: 相手ターンでない"
    evaluate_static_effects(st, overlay)
    assert luffy.static_buff == 3000, \
        f"相手ターン + ドレスローザ で +3000 が乗っていない: {luffy.static_buff}"


def test_op15_051_static_no_pump_self_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → static_buff +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-039", overlay, turn_player=0)  # 自分ターン
    me = st.players[0]
    luffy = InPlay.of(repo.get("OP15-051"), sickness=False)
    me.characters = [luffy]
    evaluate_static_effects(st, overlay)
    assert luffy.static_buff == 0, \
        f"自分ターンで +3000 が乗ってはいけない: {luffy.static_buff}"


# --------------------------------------------------------------------------- #
#  OP15-053 レベッカ (CHARACTER 青 cost1):
#    【ドン‼×1】このキャラは【ブロッカー】を得る。
#    【登場時】自分のデッキの上から3枚を見て、特徴《ドレスローザ》を持つカード
#      1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op15_053_static_blocker_with_don():
    """【ドン‼×1】付与で【ブロッカー】を得る。 ドン0では得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    rebecca = InPlay.of(repo.get("OP15-053"), sickness=False)
    me.characters = [rebecca]

    rebecca.attached_dons = 0
    evaluate_static_effects(st, overlay)
    assert rebecca.is_blocker_now is False, "ドン0で【ブロッカー】を得てはいけない"

    rebecca.attached_dons = 1
    evaluate_static_effects(st, overlay)
    assert rebecca.is_blocker_now is True, "ドン1で【ブロッカー】を得ていない"


def test_op15_053_on_play_search_dressrosa_to_hand_ai():
    """登場時: デッキ上3枚から《ドレスローザ》カード1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    sabo = repo.get("OP15-046")  # サボ ドレスローザ
    assert "ドレスローザ" in (sabo.features or ""), "テスト前提: OP15-046 は ドレスローザ"
    me.deck = [sabo] + [repo.get("OP01-016")] * 20
    me.hand = []
    do, _ = _do(overlay, "OP15-053", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP15-053"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == "OP15-046" for c in me.hand), \
        "デッキ上3枚から《ドレスローザ》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP15-055 使ってけれ‼ルフィ先輩ィ!!! (EVENT 青 cost3):
#    【メイン】以下から1つを選ぶ。
#      ・カード2枚を引く。
#      ・自分の特徴《ドレスローザ》を持つキャラ1枚までは、次の相手のエンドフェイズ
#        終了時まで、【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op15_055_main_choice_ai_no_crash():
    """AI: メイン choice_effect → 自動で 1 択を発動し crash / modal 残しなし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    dress = InPlay.of(repo.get("EB01-042"), sickness=False)  # スカーレット ドレスローザ
    me.characters = [dress]
    do, _ = _do(overlay, "OP15-055", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert st.pending_choice is None, "AI 文脈で modal が残ってはいけない"


def test_op15_055_main_choice_human_option_pick():
    """人間: メイン → option_pick modal が 2 択で立つ。 option 0 (2ドロー) を解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    dress = InPlay.of(repo.get("EB01-042"), sickness=False)
    me.characters = [dress]
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-055", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 choice で modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("options", [])) == 2, \
        f"2 択の option が立っていない: {st.pending_choice.get('options')}"
    resolve_pending_choice(st, [0])  # 「カード2枚を引く」を選ぶ
    _drain(st, [0])
    assert len(me.deck) == deck_before - 2, "option 0 (2ドロー) が解決されていない"


def test_op15_055_main_choice_human_blocker_option():
    """人間: option 1 (《ドレスローザ》キャラに【ブロッカー】付与) を選び 解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    dress = InPlay.of(repo.get("EB01-042"), sickness=False)  # ドレスローザ
    me.characters = [dress]
    do, _ = _do(overlay, "OP15-055", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 choice で modal が立たない"
    resolve_pending_choice(st, [1])  # ブロッカー付与を選ぶ
    _drain(st, [0])
    # duration=next_opp_turn_end → granted_keywords_through_opp_turn に積まれ is_blocker_now が拾う
    assert dress.is_blocker_now is True, \
        "《ドレスローザ》キャラに【ブロッカー】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP15-056 “メラメラの実”はおれが食っていいか？ (EVENT 青 cost7):
#    【メイン】カード2枚を引く。その後、自分のリーダー「ルーシー」は、このターン中、
#      【ダブルアタック】を得て、パワー+3000。
#    【トリガー】カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op15_056_main_draw2_and_leader_double_attack_ai():
    """メイン: 2ドロー + 自リーダーに【ダブルアタック】+3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-002", overlay)  # ルーシー leader
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    leader_before = me.leader.power
    do, _ = _do(overlay, "OP15-056", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == 2, f"2ドローが起きていない: 手札 {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減っていない"
    assert "ダブルアタック" in me.leader.granted_keywords, \
        f"自リーダーに【ダブルアタック】が付与されていない: {me.leader.granted_keywords}"
    assert me.leader.power == leader_before + 3000, \
        f"自リーダーへの +3000 が反映されていない: {me.leader.power} (before {leader_before})"


def test_op15_056_trigger_draw2_ai():
    """【トリガー】カード2枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP15-002", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP15-056", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == 2, f"トリガーで2ドローが起きていない: 手札 {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減っていない"
