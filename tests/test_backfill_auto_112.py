# -*- coding: utf-8 -*-
"""OP11 弾 青 (ファイアタンク海賊団 / ジェルマ66 / 魚人族) 効果 回帰テスト
バックフィル (自動生成 wave 112):
OP11-039 / OP11-040 / OP11-042 / OP11-043 / OP11-044 / OP11-046 /
OP11-047 / OP11-048 / OP11-049 / OP11-050 の 10 枚。

  OP11-039 武頼貫 (EVENT 緑) = 【カウンター】自魚人族/人魚族 リーダーかキャラ1枚まで
     このバトル中 +3000 → その後 相手コスト3以下キャラ1枚レスト /
     トリガー 相手コスト4以下キャラ1枚レスト
     (counter power_pump one_self_chara_or_leader_filtered +3000 / rest cost_le_3 // trigger rest cost_le_4)
  OP11-040 モンキー・D・ルフィ (LEADER 青紫) = 自ターン開始時 自ドン8+なら デッキ上5枚を見て
     麦わらの一味 1枚を手札 → 残りをデッキ上か下
     (on_turn_start if self_don_ge 8 search_top_n depth5 麦わらの一味 → hand rest top_or_bottom)
  OP11-042 ヴィト (CHARACTER 青) = 【登場時】手札のファイアタンク海賊団1枚を捨てられる：
     このターン中【速攻】を得る (on_play cost discard_hand_with_filter / do give_keyword 速攻)
  OP11-043 ヴィンスモーク・イチジ (CHARACTER 青) = 【ブロッカー】【相手のアタック時】【ターン1回】
     自キャラがジェルマのみなら 自リーダーかキャラ1枚 +1000 → 自デッキ上2枚トラッシュ
     (opp_attack power_pump self_inplay +1000 / mill_self_top 2)
  OP11-044 ヴィンスモーク・ジャッジ (CHARACTER 青) = 【起動メイン】【ターン1回】手札1枚捨て：
     自ジェルマ66キャラすべて このターン中 +1000
     (activate_main power_pump all_self_chara_filtered ジェルマ66 +1000 turn)
  OP11-046 ヴィンスモーク・ヨンジ (CHARACTER 青) = 【ブロッカー】自キャラがジェルマのみなら
     このキャラは相手効果でKOされずレストにされない (static set_protect_from_opp_effect_static)
  OP11-047 ヴィンスモーク・レイジュ (CHARACTER 青) = 【登場時】自リーダーがヴィンスモーク家なら
     デッキ上5枚を見て ジェルマを含む特徴カード1枚を公開して手札 → 残りトラッシュ
     (on_play search_top_n depth5 feature_contains ジェルマ → hand rest trash public)
  OP11-048 カポネ・ベッジ (CHARACTER 青) = 【登場時】デッキ上4枚を見て コスト2以上の
     ファイアタンク海賊団/麦わらの一味 1枚を公開して手札 → 残りをデッキ下
     (on_play search_top_n depth4 feature_in cost_ge2 → hand rest bottom public)
  OP11-049 キャロット (CHARACTER 青) = 【登場時】デッキ上3枚を見て 好きな順で上か下 /
     【相手のアタック時】このキャラをトラッシュ：自リーダー1枚まで このバトル中 +1000
     (on_play look_top_reorder depth3 choice / opp_attack cost trash_self power_pump self_leader +1000)
  OP11-050 ゴッティ (CHARACTER 青) = 【アタック時】手札のファイアタンク海賊団1枚を捨てられる：
     コスト1以下キャラ1枚まで 持ち主の手札かデッキ下に戻す
     (on_attack optional_cost_then cost discard ファイアタンク / effect return_to_hand cost_le_1)

目的 (= test_backfill_auto_001〜111.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_GENERIC = "OP01-001"     # ロロノア・ゾロ (超新星/麦わらの一味 — 汎用埋め)
_LEADER_GYOJIN = "OP14-040"      # ジンベエ LEADER (魚人族/王下七武海/タイヨウの海賊団)
_LEADER_VINSMOKE = "OP06-042"    # ヴィンスモーク・レイジュ LEADER (ヴィンスモーク家/ジェルマ66)
_FILLER = "ST01-004"             # サンジ cost2 power4000 (麦わらの一味、 非魚人族/非ジェルマ)
_FILLER_P1000 = "OP16-043"       # ウソップ cost2 power1000
_FISH_C = "OP16-023"             # アーロン cost1 power3000 魚人族 (vanilla overlay)
_FISH_C2 = "OP03-101"            # ケイミー cost1 power3000 人魚族 (vanilla overlay)
_GERMA_C = "OP06-064"            # ヴィンスモーク・ニジ cost3 power3000 (ヴィンスモーク家/ジェルマ66)
_GERMA_C2 = "OP06-066"           # ヴィンスモーク・ヨンジ cost2 power2000 (ヴィンスモーク家/ジェルマ66)
_FIRETANK_C = "OP14-003"         # カポネ・ベッジ cost1 power2000 (超新星/ファイアタンク海賊団)


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


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave112_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP11-039", "OP11-040", "OP11-042", "OP11-043", "OP11-044",
           "OP11-046", "OP11-047", "OP11-048", "OP11-049", "OP11-050"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP11-039 武頼貫: 【カウンター】自魚人族/人魚族 +3000 → 相手コスト3以下レスト
# --------------------------------------------------------------------------- #
def test_op11_039_counter_pump_and_rest_ai():
    """カウンター: 魚人族リーダー +3000 → 相手コスト3以下キャラ1枚レスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay)  # 魚人族リーダー = pump 対象
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 3
    victim.rested = False
    opp.characters = [victim]

    power_before = me.leader.power
    for prim in _eff(overlay, "OP11-039", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が 魚人族リーダーに反映されていない: {me.leader.power}"
    assert victim.rested is True, \
        "その後の 相手コスト3以下キャラ レストが反映されていない"


def test_op11_039_counter_pump_human_pick():
    """人間 + 魚人族リーダー + 魚人族キャラ → +3000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FISH_C), sickness=False)  # アーロン 魚人族
    me.characters = [friend]

    execute_effect(_eff(overlay, "OP11-039", "counter")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (魚人族リーダー+魚人族キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 3000, \
        "人間が選んだ魚人族キャラに +3000 が反映されていない"


def test_op11_039_trigger_rest_cost4_ai():
    """トリガー: 相手のコスト4以下キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 4
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-039", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.rested is True, "トリガーで 相手コスト4以下キャラがレストにされていない"


# --------------------------------------------------------------------------- #
#  OP11-040 ルフィ (LEADER): ターン開始時 デッキ上5枚 → 麦わらの一味 1枚を手札
# --------------------------------------------------------------------------- #
def test_op11_040_turn_start_search_ai():
    """ターン開始時 do: デッキ上5枚を見て 麦わらの一味 1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # 上に 麦わらの一味 (ST01-004) を 1 枚、 残りは 魚人族 (非麦わら) で埋める
    me.deck = [repo.get(_FILLER)] + [repo.get(_FISH_C)] * 20

    for prim in _eff(overlay, "OP11-040", "on_turn_start")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card_id == _FILLER for c in me.hand), \
        "デッキ上5枚から 麦わらの一味 カードが手札に加わっていない"


def test_op11_040_turn_start_search_human_pick():
    """人間 + デッキ上5枚に 麦わらの一味 → search_top_n modal → resolve で手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] + [repo.get(_FISH_C)] * 20

    execute_effect(_eff(overlay, "OP11-040", "on_turn_start")["do"][0],
                   st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (麦わら) を選択
    _drain(st, [])
    assert any(c.card_id == _FILLER for c in me.hand), \
        "人間が選んだ 麦わらの一味 カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP11-042 ヴィト: 【登場時】(手札ファイアタンク捨て) このターン【速攻】
# --------------------------------------------------------------------------- #
def test_op11_042_on_play_give_rush_ai():
    """【登場時】do: このキャラに【速攻】を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    vito = InPlay.of(repo.get("OP11-042"), sickness=True)

    for prim in _eff(overlay, "OP11-042", "on_play")["do"]:
        execute_effect(prim, st, me, opp, vito)
    _drain(st, [0])
    assert "速攻" in vito.granted_keywords, \
        "登場時に ヴィト自身へ 速攻 が付与されていない"


def test_op11_042_on_play_give_rush_ai_context_no_crash():
    """AI 文脈 (human_idx=None) で crash せず 速攻 が付与される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=None)
    me, opp = st.players[0], st.players[1]
    vito = InPlay.of(repo.get("OP11-042"), sickness=True)
    execute_effect(_eff(overlay, "OP11-042", "on_play")["do"][0], st, me, opp, vito)
    _drain(st, [0])
    assert "速攻" in vito.granted_keywords


# --------------------------------------------------------------------------- #
#  OP11-043 ヴィンスモーク・イチジ: 【相手のアタック時】自 +1000 → 自デッキ上2枚トラッシュ
# --------------------------------------------------------------------------- #
def test_op11_043_opp_attack_pump_and_mill_ai():
    """相手アタック時 do: 自身 +1000 → 自デッキ上2枚をトラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    ichiji = InPlay.of(repo.get("OP11-043"), sickness=False)
    me.characters = [ichiji]
    me.deck = [repo.get(_FILLER)] * 10
    trash_before = len(me.trash)
    deck_before = len(me.deck)
    power_before = ichiji.power

    for prim in _eff(overlay, "OP11-043", "opp_attack")["do"]:
        execute_effect(prim, st, me, opp, ichiji)
    _drain(st, [0])
    assert ichiji.power == power_before + 1000, \
        f"相手アタック時の +1000 が反映されていない: {ichiji.power}"
    assert len(me.trash) == trash_before + 2, "自デッキ上2枚がトラッシュに置かれていない"
    assert len(me.deck) == deck_before - 2, "デッキ枚数が2枚減っていない"


# --------------------------------------------------------------------------- #
#  OP11-044 ヴィンスモーク・ジャッジ: 【起動メイン】(手札1枚捨て) 自ジェルマ66 全員 +1000
# --------------------------------------------------------------------------- #
def test_op11_044_activate_main_pump_germa_ai():
    """起動メイン: (手札1枚捨て) 自ジェルマ66キャラすべて +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    judge = InPlay.of(repo.get("OP11-044"), sickness=False)   # ジェルマ66
    germa = InPlay.of(repo.get(_GERMA_C), sickness=False)     # ジェルマ66
    non_germa = InPlay.of(repo.get(_FISH_C), sickness=False)  # 魚人族 (非ジェルマ)
    me.characters = [judge, germa, non_germa]
    me.hand = [repo.get(_FILLER)]  # discard コスト用
    judge_before = judge.power
    germa_before = germa.power
    non_before = non_germa.power

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-044"]
    assert len(opts) == 1, f"OP11-044 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert judge.power == judge_before + 1000, "ジェルマ66 (ジャッジ自身) に +1000 されていない"
    assert germa.power == germa_before + 1000, "ジェルマ66 (ニジ) に +1000 されていない"
    assert non_germa.power == non_before, "非ジェルマ (魚人族) キャラに +1000 されてはいけない"
    assert len(me.hand) == 0, "起動メインコストで手札1枚が捨てられていない"


def test_op11_044_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    judge = InPlay.of(repo.get("OP11-044"), sickness=False)
    me.characters = [judge]
    me.hand = [repo.get(_FILLER), repo.get(_FILLER)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-044"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-044"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP11-046 ヴィンスモーク・ヨンジ: 自キャラがジェルマのみなら 相手効果で KO/レストされない
# --------------------------------------------------------------------------- #
def test_op11_046_static_protect_when_all_germa():
    """自キャラが全てジェルマ → ヨンジ自身に protect_from_opp_effect が付く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    yonji = InPlay.of(repo.get("OP11-046"), sickness=False)  # ジェルマ66
    germa = InPlay.of(repo.get(_GERMA_C), sickness=False)    # ジェルマ66
    me.characters = [yonji, germa]

    evaluate_static_effects(st, overlay)
    assert yonji.protect_from_opp_effect is True, \
        "自キャラが全てジェルマの時 ヨンジに protect_from_opp_effect が付いていない"


def test_op11_046_static_no_protect_with_non_germa():
    """自キャラに非ジェルマが混じる → 条件不成立 → protect が付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    yonji = InPlay.of(repo.get("OP11-046"), sickness=False)   # ジェルマ66
    non_germa = InPlay.of(repo.get(_FISH_C), sickness=False)  # 魚人族 (非ジェルマ)
    me.characters = [yonji, non_germa]

    evaluate_static_effects(st, overlay)
    assert yonji.protect_from_opp_effect is False, \
        "非ジェルマキャラが混じる時は protect が付いてはいけない (条件不成立)"


# --------------------------------------------------------------------------- #
#  OP11-047 ヴィンスモーク・レイジュ: 【登場時】デッキ上5枚 → ジェルマを含む特徴1枚を手札
# --------------------------------------------------------------------------- #
def test_op11_047_on_play_search_germa_ai():
    """【登場時】do: デッキ上5枚を見て ジェルマを含む特徴カード1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_VINSMOKE, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    trash_before = len(me.trash)
    # 上に ジェルマ66 カード、 残りは 麦わら (非ジェルマ) で埋める
    me.deck = [repo.get(_GERMA_C)] + [repo.get(_FILLER)] * 20

    for prim in _eff(overlay, "OP11-047", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-047"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == _GERMA_C for c in me.hand), \
        "デッキ上5枚から ジェルマを含む特徴カードが手札に加わっていない"
    # 残り 4 枚 (見た分) はトラッシュへ
    assert len(me.trash) == trash_before + 4, \
        "search 後の残り4枚がトラッシュに置かれていない"


def test_op11_047_on_play_search_human_pick():
    """人間 + デッキ上5枚に ジェルマ → search_top_n modal → resolve で手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_VINSMOKE, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_GERMA_C), repo.get(_FILLER), repo.get(_GERMA_C2)] \
        + [repo.get(_FILLER)] * 15

    execute_effect(_eff(overlay, "OP11-047", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-047"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (ニジ) を選択
    _drain(st, [])
    assert any(c.card_id == _GERMA_C for c in me.hand), \
        "人間が選んだ ジェルマ カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP11-048 カポネ・ベッジ: 【登場時】デッキ上4枚 → cost2+ の ファイアタンク/麦わら 1枚を手札
# --------------------------------------------------------------------------- #
def test_op11_048_on_play_search_ai():
    """【登場時】do: デッキ上4枚を見て コスト2以上の ファイアタンク/麦わら 1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # 上に cost2 麦わら (ST01-004)、 残りは cost1 魚人族 (対象外) で埋める
    me.deck = [repo.get(_FILLER)] + [repo.get(_FISH_C)] * 20

    for prim in _eff(overlay, "OP11-048", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-048"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == _FILLER for c in me.hand), \
        "デッキ上4枚から コスト2以上の 麦わら カードが手札に加わっていない"


def test_op11_048_on_play_ignores_cost1():
    """コスト1の 対象特徴カードは cost_ge 2 不成立 → 手札に来ない (対象外)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # _FIRETANK_C = カポネ cost1 ファイアタンク → cost_ge 2 で除外される
    me.deck = [repo.get(_FIRETANK_C)] * 4 + [repo.get(_FISH_C)] * 16

    for prim in _eff(overlay, "OP11-048", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-048"), sickness=True))
    _drain(st, [0])
    assert not any(c.card_id == _FIRETANK_C for c in me.hand), \
        "コスト1の ファイアタンク が手札に来てはいけない (cost_ge 2 対象外)"


def test_op11_048_on_play_search_human_pick():
    """人間 + デッキ上4枚に 対象カード → search_top_n modal → resolve で手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER), repo.get(_FISH_C), repo.get(_FILLER)] \
        + [repo.get(_FISH_C)] * 15

    execute_effect(_eff(overlay, "OP11-048", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-048"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (cost2 麦わら) を選択
    _drain(st, [])
    assert any(c.card_id == _FILLER for c in me.hand), \
        "人間が選んだ コスト2以上の対象カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP11-049 キャロット: 【登場時】デッキ上3枚 好きな順で上下 / 相手アタック時 自トラッシュ→自リーダー+1000
# --------------------------------------------------------------------------- #
def test_op11_049_on_play_look_top_reorder_ai():
    """【登場時】do: デッキ上3枚を見て並び替え (= カードを失わず deck の多重集合は保存)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    # 上3枚を コスト差のある 3 種にして、 昇順ヒューリスティックの並び替えを観察
    me.deck = [repo.get(_GERMA_C), repo.get(_FISH_C), repo.get(_FILLER)] \
        + [repo.get(_FILLER)] * 10  # cost 3 / 1 / 2 が上位
    deck_len_before = len(me.deck)
    top3_ids_before = sorted(c.card_id for c in me.deck[:3])

    for prim in _eff(overlay, "OP11-049", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-049"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_len_before, "look_top_reorder でデッキ枚数が変わってはいけない"
    assert sorted(c.card_id for c in me.deck[:3]) == top3_ids_before, \
        "上3枚の内容 (多重集合) が保存されていない"
    # to=choice = コスト昇順に並び替え → 先頭が最小コスト (魚人族 cost1)
    assert me.deck[0].card_id == _FISH_C, \
        "コスト昇順ヒューリスティックで 最小コスト札が上に来ていない"


def test_op11_049_opp_attack_trash_self_pump_leader_ai():
    """相手アタック時 do: 自リーダー1枚まで +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    carrot = InPlay.of(repo.get("OP11-049"), sickness=False)
    me.characters = [carrot]

    power_before = me.leader.power
    for prim in _eff(overlay, "OP11-049", "opp_attack")["do"]:
        execute_effect(prim, st, me, opp, carrot)
    _drain(st, [0])
    assert me.leader.power == power_before + 1000, \
        f"相手アタック時の 自リーダー +1000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP11-050 ゴッティ: 【アタック時】(手札ファイアタンク捨て) コスト1以下キャラ1枚を手札/デッキ下へ
# --------------------------------------------------------------------------- #
def test_op11_050_on_attack_optional_return_ai():
    """アタック時 optional_cost_then: ファイアタンク捨て → 相手コスト1以下キャラを手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    gotti = InPlay.of(repo.get("OP11-050"), sickness=False)
    me.characters = [gotti]
    me.hand = [repo.get(_FIRETANK_C)]  # ファイアタンク = discard コスト
    victim = InPlay.of(repo.get(_FISH_C), sickness=False)  # cost1 ≤ 1
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-050", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, gotti)
    _drain(st, [0])
    assert victim not in opp.characters, \
        "相手コスト1以下キャラが場から戻されていない"
    assert any(c.card_id == _FISH_C for c in opp.hand), \
        "戻された相手キャラが持ち主 (相手) の手札に来ていない"
    assert any(c.card_id == _FIRETANK_C for c in me.trash), \
        "discard コストの ファイアタンク がトラッシュに置かれていない"


def test_op11_050_on_attack_optional_cost_confirm_human():
    """人間 + 任意コスト → optional_cost_confirm modal → pay で効果解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    gotti = InPlay.of(repo.get("OP11-050"), sickness=False)
    me.characters = [gotti]
    me.hand = [repo.get(_FIRETANK_C)]
    victim = InPlay.of(repo.get(_FISH_C), sickness=False)  # cost1、 相手キャラは 1 体だけ
    opp.characters = [victim]

    execute_effect(_eff(overlay, "OP11-050", "on_attack")["do"][0], st, me, opp, gotti)
    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay (= コストを払って発動)
    _drain(st, [0])
    assert victim not in opp.characters, \
        "人間が任意コストを払った後、 相手コスト1以下キャラが戻されていない"


def test_op11_050_on_attack_no_firetank_no_fire():
    """手札に ファイアタンク が無い → 任意コスト払えず 効果不発 (相手キャラは残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    gotti = InPlay.of(repo.get("OP11-050"), sickness=False)
    me.characters = [gotti]
    me.hand = [repo.get(_FISH_C)]  # ファイアタンクでない → コスト払えない
    victim = InPlay.of(repo.get(_FISH_C), sickness=False)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-050", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, gotti)
    _drain(st, [0])
    assert victim in opp.characters, \
        "ファイアタンクが無いのに 相手キャラが戻された (任意コスト不能なら不発のはず)"
