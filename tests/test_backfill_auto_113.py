# -*- coding: utf-8 -*-
"""OP11 弾 青 (麦わらの一味) / 紫 (インペルダウン・ビッグ・マム海賊団) 効果
回帰テスト バックフィル (自動生成 wave 113):
OP11-051 / OP11-054 / OP11-056 / OP11-057 / OP11-058 / OP11-060 /
OP11-061 / OP11-063 / OP11-065 / OP11-066 の 10 枚。

  OP11-051 サンジ (CHARACTER 青) = 相手効果でKO時 デッキ上5枚を見て cost5以下の
     麦わらの一味キャラ1枚を登場、 残りをデッキ下 / 【登場時】元々パワー5000以下の
     キャラ1枚までを持ち主の手札に戻す
     (on_ko by_opp_effect search_top_n depth5 destination:play / on_play return_to_hand power_le5000)
  OP11-054 ナミ (CHARACTER 青) = 【ブロッカー】【登場時】自リーダーが多色なら 3ドロー
     (on_play if leader_color 多色 draw 3)
  OP11-056 ブルック (CHARACTER 青) = 【ブロッカー】【登場時】元々コスト1のキャラ1枚までを
     持ち主のデッキの下に置く (on_play return_to_deck_bottom cost_eq_1)
  OP11-057 ペドロ (CHARACTER 青) = 自分の手札が4枚以下なら 【ブロッカー】を得る
     (static on_attached_don n=0 if self_hand_count_le 4 give_keyword ブロッカー)
  OP11-058 ルフィ (CHARACTER 青) = 自分の手札が5枚以上なら アタックできない / 【ブロッカー】
     (static on_attached_don n=0 if self_hand_count_ge 5 set_cannot_attack_static)
  OP11-060 式をブッ壊そう!!! (EVENT 青) = 【メイン】自リーダーが多色なら デッキ上5枚を見て
     「式をブッ壊そう!!!」以外の麦わらの一味カード1枚を手札 → 残りをデッキ下 /
     トリガーで【メイン】効果を発動 (main search_top_n depth5 exclude_name → hand / trigger fire_self)
  OP11-061 ゴムゴムのJET大蛇砲 (EVENT 青) = 【メイン】相手の元々コスト4以下のキャラ1枚までを
     持ち主のデッキの下に置く / トリガーはコスト1以下 (main return_to_deck_bottom cost_le4 / trigger cost_le1)
  OP11-063 サディちゃん (CHARACTER 紫) = 【登場時】ドン‼-1：自リーダーがインペルダウンなら
     相手コスト3以下のキャラ1枚までをレスト (on_play cost pay_don1 rest cost_le3)
  OP11-065 シャーロット・アナナ (CHARACTER 紫) = 「アナナ」以外の自分の紫のビッグ・マム海賊団
     キャラがいれば 【ブロッカー】を得る (static on_attached_don n=0 if self_chara_filtered_count_ge give ブロッカー)
  OP11-066 シャーロット・オーブン (CHARACTER 紫) = 【起動メイン】このキャラをレスト：任意コストを
     宣言し相手デッキ上を公開、 一致なら 相手コスト3以下キャラ1枚KO → レストドン1枚追加
     (activate_main cost rest_self declare_cost_reveal_then [ko cost_le3, add_rested_don 1])

目的 (= test_backfill_auto_001〜112.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_GENERIC = "OP01-001"     # ロロノア・ゾロ (単色 赤、 汎用埋め)
_LEADER_MULTI = "OP11-040"       # モンキー・D・ルフィ LEADER (青/紫 = 多色)
_LEADER_IMPEL = "OP02-071"       # マゼラン LEADER (紫、 インペルダウン)
_STRAW_C = "ST01-004"            # サンジ cost2 power4000 麦わらの一味 (非パラレル)
_COST1_C = "OP16-023"            # アーロン cost1 power3000 (魚人族、 vanilla overlay)
_BM_PURPLE_C = "EB03-032"        # シャーロット・フランペ cost1 紫 ビッグ・マム海賊団


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_STRAW_C)] * 30
    p1.deck = [repo.get(_STRAW_C)] * 30
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
def test_all_wave113_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP11-051", "OP11-054", "OP11-056", "OP11-057", "OP11-058",
           "OP11-060", "OP11-061", "OP11-063", "OP11-065", "OP11-066"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP11-051 サンジ: 相手効果KO時 デッキ上5枚→麦わら cost5以下 1枚登場 / 登場時 P5000以下手札戻し
# --------------------------------------------------------------------------- #
def test_op11_051_on_ko_search_summon_ai():
    """相手効果KO時 do: デッキ上5枚を見て cost5以下 麦わらの一味キャラ1枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    # 上に 麦わらの一味 cost2 (ST01-004) を仕込む。 destination:play で登場するはず。
    me.deck = [repo.get(_STRAW_C)] + [repo.get(_COST1_C)] * 20
    chars_before = len(me.characters)

    for prim in _eff(overlay, "OP11-051", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-051"), sickness=False))
    _drain(st, [0])
    assert any(c.card.card_id == _STRAW_C for c in me.characters), \
        "デッキ上5枚から 麦わらの一味 cost5以下キャラが登場していない"
    assert len(me.characters) == chars_before + 1, \
        "登場で自キャラが1体増えていない"


def test_op11_051_on_play_return_to_hand_ai():
    """【登場時】do: 元々パワー5000以下の相手キャラ1枚を持ち主の手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_STRAW_C), sickness=False)  # power 4000 ≤ 5000
    opp.characters = [victim]
    opp.hand = []

    for prim in _eff(overlay, "OP11-051", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-051"), sickness=False))
    _drain(st, [0])
    assert victim not in opp.characters, "元々パワー5000以下の相手キャラが場から戻されていない"
    assert any(c.card_id == _STRAW_C for c in opp.hand), \
        "戻された相手キャラが持ち主 (相手) の手札に来ていない"


def test_op11_051_on_play_return_human_pick():
    """人間 + 元々パワー5000以下の相手キャラ 複数 → target_pick modal → resolve で手札戻し。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_STRAW_C), sickness=False)   # power 4000
    b = InPlay.of(repo.get(_COST1_C), sickness=False)   # power 3000
    opp.characters = [a, b]
    opp.hand = []

    execute_effect(_eff(overlay, "OP11-051", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-051"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラが戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP11-054 ナミ: 【登場時】自リーダーが多色なら 3ドロー
# --------------------------------------------------------------------------- #
def test_op11_054_on_play_draw3_ai():
    """【登場時】do: 3ドロー (AI 自動)。 overlay は draw 3 のみモデル化。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MULTI, overlay)  # 多色リーダー = 条件成立
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_STRAW_C)] * 10
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    for prim in _eff(overlay, "OP11-054", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-054"), sickness=False))
    _drain(st, [0])
    assert len(me.hand) == hand_before + 3, "登場時の 3ドロー が反映されていない"
    assert len(me.deck) == deck_before - 3, "デッキが3枚減っていない"


# --------------------------------------------------------------------------- #
#  OP11-056 ブルック: 【登場時】元々コスト1のキャラ1枚までを持ち主のデッキの下に
# --------------------------------------------------------------------------- #
def test_op11_056_on_play_return_deck_bottom_ai():
    """【登場時】do: 元々コスト1の相手キャラ1枚を持ち主のデッキの下に置く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_COST1_C), sickness=False)  # cost 1
    opp.characters = [victim]
    opp.deck = [repo.get(_STRAW_C)] * 10
    deck_before = len(opp.deck)

    for prim in _eff(overlay, "OP11-056", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-056"), sickness=False))
    _drain(st, [0])
    assert victim not in opp.characters, "元々コスト1の相手キャラが場から離れていない"
    assert len(opp.deck) == deck_before + 1, "戻された相手キャラが持ち主のデッキ下に置かれていない"
    assert opp.deck[-1].card_id == _COST1_C, "デッキ下 (末尾) に戻ったカードが一致しない"


def test_op11_056_on_play_ignores_non_cost1():
    """元々コスト1でない相手キャラは対象外 → 場に残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_STRAW_C), sickness=False)  # cost 2 ≠ 1
    opp.characters = [victim]
    opp.deck = [repo.get(_COST1_C)] * 10

    for prim in _eff(overlay, "OP11-056", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-056"), sickness=False))
    _drain(st, [0])
    assert victim in opp.characters, "元々コスト1でないキャラが戻されてはいけない (対象外)"


# --------------------------------------------------------------------------- #
#  OP11-057 ペドロ: 手札4枚以下で 【ブロッカー】を得る (静的)
# --------------------------------------------------------------------------- #
def test_op11_057_static_blocker_when_hand_le4():
    """自分の手札が4枚以下 → ペドロ自身に 【ブロッカー】が付く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    pedro = InPlay.of(repo.get("OP11-057"), sickness=False)
    me.characters = [pedro]
    me.hand = [repo.get(_STRAW_C)] * 4  # 4 枚 (≤4 = 条件成立)

    evaluate_static_effects(st, overlay)
    assert pedro.is_blocker_now is True, \
        "手札4枚以下の時 ペドロに 【ブロッカー】が付いていない"


def test_op11_057_static_no_blocker_when_hand_ge5():
    """自分の手札が5枚以上 → 条件不成立 → 【ブロッカー】が付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    pedro = InPlay.of(repo.get("OP11-057"), sickness=False)
    me.characters = [pedro]
    me.hand = [repo.get(_STRAW_C)] * 5  # 5 枚 (>4 = 条件不成立)

    evaluate_static_effects(st, overlay)
    assert pedro.is_blocker_now is False, \
        "手札5枚以上では 【ブロッカー】が付いてはいけない (条件不成立)"


# --------------------------------------------------------------------------- #
#  OP11-058 ルフィ: 手札5枚以上で アタックできない (静的)
# --------------------------------------------------------------------------- #
def test_op11_058_static_cannot_attack_when_hand_ge5():
    """自分の手札が5枚以上 → ルフィ自身が アタックできない (cannot_attack_static)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP11-058"), sickness=False)
    me.characters = [luffy]
    me.hand = [repo.get(_STRAW_C)] * 5  # 5 枚 (≥5 = 条件成立)

    evaluate_static_effects(st, overlay)
    assert luffy.cannot_attack_static is True, \
        "手札5枚以上の時 ルフィに アタック不可 (cannot_attack_static) が付いていない"


def test_op11_058_static_can_attack_when_hand_le4():
    """自分の手札が4枚以下 → 条件不成立 → アタック制限が付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP11-058"), sickness=False)
    me.characters = [luffy]
    me.hand = [repo.get(_STRAW_C)] * 4  # 4 枚 (<5 = 条件不成立)

    evaluate_static_effects(st, overlay)
    assert luffy.cannot_attack_static is False, \
        "手札4枚以下では アタック制限が付いてはいけない (条件不成立)"


# --------------------------------------------------------------------------- #
#  OP11-060 式をブッ壊そう!!! (EVENT): 【メイン】デッキ上5枚→麦わら 1枚を手札
# --------------------------------------------------------------------------- #
def test_op11_060_main_search_ai():
    """【メイン】do: デッキ上5枚を見て 麦わらの一味カード1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MULTI, overlay)  # 多色リーダー
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # 上に 麦わらの一味 (ST01-004)、 残りは 非麦わら (アーロン 魚人族) で埋める
    me.deck = [repo.get(_STRAW_C)] + [repo.get(_COST1_C)] * 20

    for prim in _eff(overlay, "OP11-060", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card_id == _STRAW_C for c in me.hand), \
        "デッキ上5枚から 麦わらの一味カードが手札に加わっていない"


def test_op11_060_main_search_human_pick():
    """人間 + デッキ上5枚に 麦わらの一味 → search_top_n modal → resolve で手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MULTI, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_STRAW_C)] + [repo.get(_COST1_C)] * 20

    execute_effect(_eff(overlay, "OP11-060", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (麦わら) を選択
    _drain(st, [])
    assert any(c.card_id == _STRAW_C for c in me.hand), \
        "人間が選んだ 麦わらの一味カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP11-061 ゴムゴムのJET大蛇砲 (EVENT): 【メイン】相手コスト4以下→デッキ下 / トリガー コスト1以下
# --------------------------------------------------------------------------- #
def test_op11_061_main_return_deck_bottom_ai():
    """【メイン】do: 相手の元々コスト4以下キャラ1枚を持ち主のデッキ下に置く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_STRAW_C), sickness=False)  # cost 2 ≤ 4
    opp.characters = [victim]
    opp.deck = [repo.get(_COST1_C)] * 10
    deck_before = len(opp.deck)

    for prim in _eff(overlay, "OP11-061", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "相手コスト4以下キャラが場から離れていない"
    assert len(opp.deck) == deck_before + 1, "戻された相手キャラが持ち主のデッキ下に置かれていない"


def test_op11_061_trigger_return_deck_bottom_cost1_ai():
    """トリガー do: 相手の元々コスト1以下キャラ1枚を持ち主のデッキ下に置く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_COST1_C), sickness=False)  # cost 1
    opp.characters = [victim]
    opp.deck = [repo.get(_STRAW_C)] * 10
    deck_before = len(opp.deck)

    for prim in _eff(overlay, "OP11-061", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "トリガーで 相手コスト1以下キャラが場から離れていない"
    assert len(opp.deck) == deck_before + 1, "戻された相手キャラが持ち主のデッキ下に置かれていない"


def test_op11_061_main_return_human_pick():
    """人間 + 相手コスト4以下キャラ 複数 → target_pick modal → resolve でデッキ下。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_STRAW_C), sickness=False)   # cost 2
    b = InPlay.of(repo.get(_COST1_C), sickness=False)   # cost 1
    opp.characters = [a, b]
    opp.deck = [repo.get(_STRAW_C)] * 10

    execute_effect(_eff(overlay, "OP11-061", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラが戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP11-063 サディちゃん: 【登場時】ドン‼-1 (インペルダウンリーダー) 相手コスト3以下レスト
# --------------------------------------------------------------------------- #
def test_op11_063_on_play_rest_ai():
    """【登場時】do: 相手のコスト3以下キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_IMPEL, overlay)  # インペルダウンリーダー
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_STRAW_C), sickness=False)  # cost 2 ≤ 3
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-063", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-063"), sickness=False))
    _drain(st, [0])
    assert victim.rested is True, "相手コスト3以下キャラがレストにされていない"


def test_op11_063_on_play_rest_human_pick():
    """人間 + 相手コスト3以下キャラ 複数 → target_pick modal → resolve でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_IMPEL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_STRAW_C), sickness=False)   # cost 2
    b = InPlay.of(repo.get(_COST1_C), sickness=False)   # cost 1
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP11-063", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-063"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはアクティブのままであるべき"


# --------------------------------------------------------------------------- #
#  OP11-065 シャーロット・アナナ: 他の紫ビッグ・マム海賊団キャラがいれば 【ブロッカー】(静的)
# --------------------------------------------------------------------------- #
def test_op11_065_static_blocker_when_other_bm():
    """「アナナ」以外の 自分の紫ビッグ・マム海賊団キャラがいる → アナナに 【ブロッカー】が付く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    anana = InPlay.of(repo.get("OP11-065"), sickness=False)
    other = InPlay.of(repo.get(_BM_PURPLE_C), sickness=False)  # 紫 ビッグ・マム海賊団
    me.characters = [anana, other]

    evaluate_static_effects(st, overlay)
    assert anana.is_blocker_now is True, \
        "他の紫ビッグ・マム海賊団キャラがいる時 アナナに 【ブロッカー】が付いていない"


def test_op11_065_static_no_blocker_when_alone():
    """他に該当キャラがいない (アナナ単体) → 条件不成立 → 【ブロッカー】が付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    anana = InPlay.of(repo.get("OP11-065"), sickness=False)
    me.characters = [anana]

    evaluate_static_effects(st, overlay)
    assert anana.is_blocker_now is False, \
        "他の該当キャラがいない時は 【ブロッカー】が付いてはいけない (条件不成立)"


# --------------------------------------------------------------------------- #
#  OP11-066 シャーロット・オーブン: 【起動メイン】自レスト→宣言公開→一致で相手KO+レストドン
# --------------------------------------------------------------------------- #
def test_op11_066_activate_main_declare_ko_ai():
    """起動メイン: 自レスト (コスト) → 任意コスト宣言→相手デッキ上公開、 一致なら
    相手コスト3以下キャラ1枚KO → レストドン1枚追加 (AI 自動)。
    相手デッキを全て cost2 で埋め、 宣言=2/公開トップ cost2 で必ず一致させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    oven = InPlay.of(repo.get("OP11-066"), sickness=False)
    me.characters = [oven]
    victim = InPlay.of(repo.get(_STRAW_C), sickness=False)  # cost 2 ≤ 3
    opp.characters = [victim]
    opp.deck = [repo.get(_STRAW_C)] * 20  # 全 cost2 → 宣言=2、 公開トップ cost2 で一致
    don_before = me.don_rested

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-066"]
    assert len(opts) == 1, f"OP11-066 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert oven.rested is True, "起動メインコストで オーブン がレストされるべき"
    assert victim not in opp.characters, \
        "宣言一致時に 相手コスト3以下キャラが KO されていない"
    assert me.don_rested == don_before + 1, \
        "KO 後の レストドン1枚追加が反映されていない"


def test_op11_066_activate_main_once_per_turn():
    """起動メインは このキャラをレストするコスト → レスト後は再度 legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    oven = InPlay.of(repo.get("OP11-066"), sickness=False)
    me.characters = [oven]
    opp.deck = [repo.get(_STRAW_C)] * 20

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-066"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-066"]
    assert len(opts2) == 0, "レスト済み (コスト支払い済) の起動メインが再び legal に出てはいけない"
