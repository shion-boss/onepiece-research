# -*- coding: utf-8 -*-
"""OP08 弾 効果 回帰テスト バックフィル (自動生成 wave 090):
OP08-101 / OP08-102 / OP08-103 / OP08-104 / OP08-105 / OP08-106 /
OP08-107 / OP08-109 / OP08-111 / OP08-112 の 10 枚 (黄 ビッグ・マム海賊団 /
空島 / シャンドラの戦士 系)。

目的 (= test_backfill_auto_001〜089.py と同一方針):
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
from engine.deck import CardRepository
from engine.effects import (
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_BM = "OP08-058"      # シャーロット・プリン (leader、 特徴 ビッグ・マム海賊団)
_LEADER_SHANDIA = "OP08-098"  # カルガラ (leader、 特徴 ジャヤ/空島/シャンドラの戦士)
_LEADER_NEUTRAL = "OP01-001"  # モンキー・D・ルフィ (中立 leader、 条件不成立用)
_KARUGARA = "OP15-101"        # カルガラ (CHARACTER cost3)
_PRIN_CHAR = "EB04-034"       # シャーロット・プリン (CHARACTER cost2 power1000)
_OPP_C4 = "PRB02-006"         # ロロノア・ゾロ cost4 power4000
_OPP_C5 = "PRB02-017"         # ボア・ハンコック cost5 power7000
_OPP_C6 = "PRB02-014"         # サボ cost6 power6000
_OPP_C2 = "OP01-016"          # ナミ cost1 power1000 (小型 対象)
_FILLER = "OP01-013"          # サンジ cost2 (デッキ/手札 埋め用)
_TRIG_CARD = "OP08-104"       # シャーロット・ポワール (【トリガー】持ち 手札コスト用)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]


def _am(st, me, overlay, cid):
    """指定 card_id の legal な起動メイン (src, eff) を返す (無ければ空 list)。"""
    return [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == cid]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave90_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP08-101", "OP08-102", "OP08-103", "OP08-104", "OP08-105",
           "OP08-106", "OP08-107", "OP08-109", "OP08-111", "OP08-112"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP08-101 シャーロット・エンゼル (CHARACTER 黄 cost2):
#    【起動メイン】【ターン1回】自ライフ上1枚をトラッシュ (任意コスト)：
#      ビッグ・マム海賊団 リーダーなら このターン終了時 デッキ上1枚をライフに加える。
# --------------------------------------------------------------------------- #
def test_op08_101_angel_activate_main_mill_life_and_schedule_ai():
    """起動メイン (BM リーダー): 自ライフ上1枚をトラッシュ → ターン終了時効果を予約 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BM, overlay)
    me, opp = st.players[0], st.players[1]
    angel = InPlay.of(repo.get("OP08-101"), sickness=False)
    me.characters = [angel]
    me.life = [repo.get(_FILLER)] * 3

    opts = _am(st, me, overlay, "OP08-101")
    assert len(opts) == 1, f"OP08-101 の起動メインが legal に出ない: {len(opts)}"
    life_before = len(me.life)
    trash_before = len(me.trash)
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[1])  # 任意コストは承諾

    assert len(me.life) == life_before - 1, \
        f"自ライフ上1枚がトラッシュされていない: {len(me.life)} (before {life_before})"
    assert len(me.trash) == trash_before + 1, "トラッシュが1枚増えていない"
    scheduled = getattr(me, "scheduled_at_self_turn_end", None) or []
    assert len(scheduled) == 1, \
        f"ターン終了時 put_top_to_life が予約されていない: {scheduled}"


def test_op08_101_angel_scheduled_put_top_to_life_flush():
    """予約された【ターン終了時】do (put_top_to_life) を flush すると デッキ上1枚がライフへ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BM, overlay)
    me, opp = st.players[0], st.players[1]
    angel = InPlay.of(repo.get("OP08-101"), sickness=False)
    me.characters = [angel]
    me.life = [repo.get(_FILLER)] * 3

    opts = _am(st, me, overlay, "OP08-101")
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[1])
    scheduled = list(getattr(me, "scheduled_at_self_turn_end", None) or [])
    assert scheduled, "予約効果が存在しない"

    deck_before = len(me.deck)
    life_before = len(me.life)
    for spec in scheduled:
        for prim in spec.get("do", []):
            execute_effect(prim, st, me, opp, None)

    assert len(me.deck) == deck_before - 1, "デッキ上1枚がライフへ移っていない"
    assert len(me.life) == life_before + 1, "ライフが1枚増えていない"


def test_op08_101_angel_activate_main_human_optional_confirm():
    """人間: 任意コスト (ライフをトラッシュ) 確認 modal が立ち、 承諾で消費される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BM, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    angel = InPlay.of(repo.get("OP08-101"), sickness=False)
    me.characters = [angel]
    me.life = [repo.get(_FILLER)] * 3

    opts = _am(st, me, overlay, "OP08-101")
    assert len(opts) == 1
    life_before = len(me.life)
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, pick=[0])
    assert len(me.life) == life_before - 1, "承諾後 ライフ上1枚がトラッシュされていない"


# --------------------------------------------------------------------------- #
#  OP08-102 シャーロット・オペラ (CHARACTER 黄 cost6):
#    【登場時】手札1枚を捨てる (任意コスト)：自ライフ枚数以下のコストの相手キャラ1枚をKO。
# --------------------------------------------------------------------------- #
def test_op08_102_opera_on_play_ko_by_life_count_ai():
    """登場時: 手札1枚を捨て → 自ライフ枚数(=4) 以下コストの相手キャラをKO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 4      # ライフ4 → cost4 以下が対象
    me.hand = [repo.get(_FILLER)]          # 捨てるコスト用
    low = InPlay.of(repo.get(_OPP_C4), sickness=False)   # cost4 (<=4 → KO)
    high = InPlay.of(repo.get(_OPP_C6), sickness=False)  # cost6 (>4 → 残る)
    opp.characters = [low, high]

    hand_before = len(me.hand)
    for prim in _eff(overlay, "OP08-102", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-102"), sickness=True))
    _drain(st, pick=[0])

    assert len(me.hand) == hand_before - 1, "任意コストで手札1枚が捨てられていない"
    remaining = sorted(int(c.card.cost) for c in opp.characters)
    assert remaining == [6], \
        f"自ライフ枚数以下のコストの相手キャラがKOされていない: 残 {remaining}"


def test_op08_102_opera_on_play_human_optional_confirm():
    """人間: 任意コスト (手札1捨て) の確認 modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 4
    me.hand = [repo.get(_FILLER)]
    opp.characters = [InPlay.of(repo.get(_OPP_C4), sickness=False)]

    execute_effect(_eff(overlay, "OP08-102", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-102"), sickness=True))
    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"


# --------------------------------------------------------------------------- #
#  OP08-103 シャーロット・カスタード (CHARACTER 黄 cost2):
#    【起動メイン】【ターン1回】自ライフ上1枚を手札に加える (任意コスト)：
#      自分のキャラ1枚まで 次の相手のターン終了時まで パワー+1000。
# --------------------------------------------------------------------------- #
def test_op08_103_custard_activate_main_life_to_hand_pump_ai():
    """起動メイン: 自ライフ上1枚を手札へ → 自キャラ1枚を +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    custard = InPlay.of(repo.get("OP08-103"), sickness=False)
    friend = InPlay.of(repo.get(_OPP_C2), sickness=False)
    me.characters = [custard, friend]

    opts = _am(st, me, overlay, "OP08-103")
    assert len(opts) == 1, f"OP08-103 の起動メインが legal に出ない: {len(opts)}"
    life_before = len(me.life)
    hand_before = len(me.hand)
    total_before = sum(c.power for c in me.characters)
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])

    assert len(me.life) == life_before - 1, "自ライフ上1枚が手札に加わっていない (life-1)"
    assert len(me.hand) == hand_before + 1, "自ライフ上1枚が手札に加わっていない (hand+1)"
    total_after = sum(c.power for c in me.characters)
    assert total_after == total_before + 1000, \
        f"自キャラ1枚への +1000 が反映されていない: {total_before} -> {total_after}"


def test_op08_103_custard_activate_main_human_flow():
    """人間: 任意コスト確認 → target_pick で選んだ自キャラが +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    custard = InPlay.of(repo.get("OP08-103"), sickness=False)
    a = InPlay.of(repo.get(_OPP_C2), sickness=False)
    me.characters = [custard, a]

    opts = _am(st, me, overlay, "OP08-103")
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"最初の modal が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # コスト承諾

    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        "コスト承諾後に target_pick modal が立たない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.power
    resolve_pending_choice(st, [a_idx])
    _drain(st, pick=[0])
    assert a.power == a_before + 1000, "人間が選んだ自キャラに +1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP08-104 シャーロット・ポワール (CHARACTER 黄 cost1):
#    【トリガー】手札1枚を捨てる (任意コスト)：このカードを登場させる。 その後 1ドロー。
# --------------------------------------------------------------------------- #
def test_op08_104_poire_trigger_play_self_and_draw_ai():
    """トリガー: 手札1捨て → このカードを登場 + 1ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP08-104")]  # トリガー元は トラッシュに置かれている
    me.hand = [repo.get(_FILLER)]      # 捨てるコスト用
    st.current_source_card_id = "OP08-104"

    deck_before = len(me.deck)
    for prim in _eff(overlay, "OP08-104", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, pick=[0])

    assert any(c.card.card_id == "OP08-104" for c in me.characters), \
        "トリガーで OP08-104 が登場していない"
    assert len(me.deck) == deck_before - 1, "その後の1ドローでデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP08-105 ジュエリー・ボニー (CHARACTER 黄 cost3):
#    【ドン‼×1】【自分のターン中】【ターン1回】相手ライフが離れた時、
#      カード2枚を引き、 自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op08_105_bonney_life_taken_draw2_discard1_ai():
    """相手ライフ離脱時: 2ドロー + 手札1枚を捨てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    bonney = InPlay.of(repo.get("OP08-105"), sickness=False)
    me.characters = [bonney]
    me.hand = [repo.get(_FILLER), repo.get(_OPP_C2)]

    eff = _eff(overlay, "OP08-105", "on_opp_life_taken")
    conds = {list(c.keys())[0]: list(c.values())[0]
             for c in eff.get("conditions", [])}
    assert conds.get("self_attached_don_ge") == 1, \
        "overlay の ドン!!×1 ゲート self_attached_don_ge=1 が無い"
    assert conds.get("self_turn") is True, "overlay の【自分のターン中】ゲートが無い"

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, bonney)

    assert len(me.deck) == deck_before - 2, "2ドローでデッキが2枚減っていない"
    assert len(me.trash) == trash_before + 1, "手札1枚の捨てが起きていない (trash+1)"


# --------------------------------------------------------------------------- #
#  OP08-106 ナミ (CHARACTER 黄 cost5):
#    【登場時】手札から【トリガー】持ち1枚を捨てる (任意コスト)：
#      相手のコスト5以下のキャラ1枚をKO。 その後 手札3枚以下なら 1ドロー。
# --------------------------------------------------------------------------- #
def test_op08_106_nami_on_play_discard_trigger_ko_and_draw_ai():
    """登場時: 【トリガー】持ち手札1枚を捨て → 相手コスト5以下1枚をKO + (手札3以下)1ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_TRIG_CARD)]  # 【トリガー】持ち = 捨てられる
    victim = InPlay.of(repo.get(_OPP_C5), sickness=False)  # cost5 (<=5 → KO)
    opp.characters = [victim]

    trash_before = len(me.trash)
    deck_before = len(me.deck)
    for prim in _eff(overlay, "OP08-106", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-106"), sickness=True))
    _drain(st, pick=[0])

    assert len(opp.characters) == 0, "相手のコスト5以下キャラがKOされていない"
    assert len(me.trash) == trash_before + 1, "【トリガー】持ち手札1枚が捨てられていない"
    # 捨て後 手札0枚 (<=3) → 1ドロー
    assert len(me.deck) == deck_before - 1, "手札3枚以下条件での1ドローが起きていない"


# --------------------------------------------------------------------------- #
#  OP08-107 ニトロ (CHARACTER 黄 cost1):
#    【起動メイン】このキャラをレストにできる：
#      自分の「シャーロット・プリン」1枚まで このターン中 パワー+2000。
# --------------------------------------------------------------------------- #
def test_op08_107_nitro_activate_main_pump_prin_ai():
    """起動メイン: 自身をレスト (コスト) → 自「シャーロット・プリン」を +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    nitro = InPlay.of(repo.get("OP08-107"), sickness=False)
    prin = InPlay.of(repo.get(_PRIN_CHAR), sickness=False)  # power1000
    me.characters = [nitro, prin]

    opts = _am(st, me, overlay, "OP08-107")
    assert len(opts) == 1, f"OP08-107 の起動メインが legal に出ない: {len(opts)}"
    power_before = prin.power
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])

    assert nitro.rested is True, "起動メインコストで ニトロ がレストされていない"
    assert prin.power == power_before + 2000, \
        f"「シャーロット・プリン」への +2000 が反映されていない: {prin.power}"


def test_op08_107_nitro_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    nitro = InPlay.of(repo.get("OP08-107"), sickness=False)
    prin = InPlay.of(repo.get(_PRIN_CHAR), sickness=False)
    me.characters = [nitro, prin]

    opts1 = _am(st, me, overlay, "OP08-107")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, pick=[0])

    opts2 = _am(st, me, overlay, "OP08-107")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP08-109 モンブラン・ノーランド (CHARACTER 黄 cost5):
#    【登場時】自リーダーが《シャンドラの戦士》で、 自キャラに「カルガラ」がいる場合、
#      自分のデッキの上から1枚までを、 ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op08_109_noland_on_play_put_top_to_life_ai():
    """登場時 (シャンドラの戦士 リーダー + カルガラ在場): デッキ上1枚をライフへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANDIA, overlay)
    me, opp = st.players[0], st.players[1]
    karugara = InPlay.of(repo.get(_KARUGARA), sickness=False)
    me.characters = [karugara]

    eff = _eff(overlay, "OP08-109", "on_play")
    cond = eff.get("if", {})
    assert cond.get("leader_feature") == "シャンドラの戦士", \
        "overlay の 条件 leader_feature=シャンドラの戦士 が無い"
    assert cond.get("self_chara_filtered_count_ge", {}).get("filter", {}).get("name") \
        == "カルガラ", "overlay の 条件 (カルガラ在場) が無い"

    deck_before = len(me.deck)
    life_before = len(me.life)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-109"), sickness=True))

    assert len(me.deck) == deck_before - 1, "デッキ上1枚がライフへ移っていない"
    assert len(me.life) == life_before + 1, "ライフが1枚増えていない"


# --------------------------------------------------------------------------- #
#  OP08-111 S-シャーク (CHARACTER 黄 cost4):
#    【ドン‼×1】【アタック時】相手は、 このバトル中、【ブロッカー】を発動できない。
# --------------------------------------------------------------------------- #
def test_op08_111_sshark_attack_unblockable_ai():
    """アタック時 (ドン1): 自身が このバトル中【ブロック不可】を得る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    shark = InPlay.of(repo.get("OP08-111"), sickness=False)
    me.characters = [shark]

    eff = _eff(overlay, "OP08-111", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドン!!×1 ゲート self_attached_don_ge=1 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, shark)

    assert "ブロック不可" in shark.granted_keywords, \
        f"アタック時に【ブロック不可】が付与されていない: {shark.granted_keywords}"


# --------------------------------------------------------------------------- #
#  OP08-112 S-スネーク (CHARACTER 黄 cost5):
#    【登場時】「モンキー・D・ルフィ」以外の相手のコスト6以下のキャラ1枚までは、
#      次の相手のターン終了時まで、 アタックできない。
# --------------------------------------------------------------------------- #
def test_op08_112_ssnake_on_play_set_cannot_attack_ai():
    """登場時: 相手のコスト6以下キャラ1枚を 次の相手ターン終了まで アタック不可 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C6), sickness=False)  # cost6 (<=6)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP08-112", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-112"), sickness=True))
    _drain(st, pick=[0])

    assert victim.cannot_attack_through_opp_turn is True, \
        "相手キャラが 次の相手ターン終了までアタック不可 になっていない"


def test_op08_112_ssnake_on_play_human_pick():
    """人間 + 相手のコスト6以下キャラ複数 → set_cannot_attack の target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C4), sickness=False)  # cost4
    b = InPlay.of(repo.get(_OPP_C6), sickness=False)  # cost6
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP08-112", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-112"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.cannot_attack_through_opp_turn is True, \
        "人間が選んだキャラがアタック不可になっていない"
    assert a.cannot_attack_through_opp_turn is False, \
        "選ばなかったキャラはアタック不可にならないべき"
