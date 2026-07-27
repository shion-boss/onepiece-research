# -*- coding: utf-8 -*-
"""OP10 弾 青/紫 (ドレスローザ / ドンキホーテ海賊団) 効果 回帰テスト バックフィル
(自動生成 wave 105):
OP10-056 / OP10-057 / OP10-058 / OP10-059 / OP10-060 /
OP10-061 / OP10-062 / OP10-066 / OP10-069 / OP10-070 の 10 枚
(マンシェリー = 登場時 ドレスローザleader/stageレスト+コスト4以上ドレスローザ1枚を手札
   を任意コストに、 相手コスト4以下1枚を手札へ (optional_cost_then) /
 レオ = 登場時 leader/stageレスト：リーダーがウソップの場合 上5枚から「レオ」以外の
   ドレスローザ2枚まで手札+手札1枚捨て (search_top_n) /
 レベッカ = 登場時 コスト8以上いる場合 1ドロー + 手札からドレスローザを公開して登場
   [overlay が search from:hand を未サポート → engine bug で skip] /
 「おまえ…タチ…」= メイン 上5枚からドレスローザキャラ1枚を手札 (search_top_n) /
 バリバリの銃 = メイン 相手パワー6000以下1枚をデッキ下 (return_to_deck_bottom) /
 必殺!!遠距離“蓑虫星” = メイン 1ドロー + 相手コスト2以下1枚を手札へ /
 ヴァイオレット = KO時 ドン-1：リーダーがドンキホーテ海賊団なら紫イベント1枚を手札 (trash_to_hand) /
 ジョーラ = 相手アタック時 ドン2レスト：相手コスト4以下1枚をレスト (rest) /
 闘魚 = ドン1 アタック時 ドン-1：相手コスト1以下1枚をKO (ko) /
 トレーボル = 登場時 次相手ターン終了まで 自元々パワー1000以下は相手効果でKOされない)。

目的 (= test_backfill_auto_001〜104.py と同一方針):
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
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード / リーダー (テキストの前提固定)
_LEADER_GREEN = "OP01-001"       # ロロノア・ゾロ (leader、 汎用 = 特徴なし)
_LEADER_DRESSROSA = "EB01-040"   # キュロス (leader、 ドレスローザ)
_LEADER_USOPP = "OP10-042"       # ウソップ (leader、 OP10-057 の if 前提)
_LEADER_DONQ = "OP14-060"        # ドフラミンゴ (leader、 ドンキホーテ海賊団、 OP10-062 の if 前提)
_FILLER = "ST01-004"             # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_DR_CHARA_C4 = "OP10-049"        # サボ cost4 特徴ドレスローザ (コスト対象 / 検索対象)
_PURPLE_EVENT = "EB04-040"       # 紫イベント (OP10-062 の trash 回収対象)
_COST1_CHARA = "EB04-002"        # cost1 キャラ (OP10-069 の KO 対象)
_LOW_POWER = "EB04-032"          # cost1 power1000 キャラ (OP10-070 の KO 耐性対象)


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
def test_all_wave105_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP10-056", "OP10-057", "OP10-058", "OP10-059", "OP10-060",
           "OP10-061", "OP10-062", "OP10-066", "OP10-069", "OP10-070"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP10-056 マンシェリー (CHARACTER 青): 【登場時】自分の特徴《ドレスローザ》を持つ、
#          リーダーかステージ1枚をレストにし、自分のコスト4以上の特徴《ドレスローザ》を
#          持つキャラ1枚を持ち主の手札に戻すことができる：相手のコスト4以下のキャラ
#          1枚までを、持ち主の手札に戻す。 (optional_cost_then、 2段コスト)
# --------------------------------------------------------------------------- #
def test_op10_056_on_play_optional_cost_bounce_opp_cost_le4_ai():
    """任意コスト (ドレスローザleaderレスト + 自コスト4ドレスローザを手札) を払い
    相手コスト4以下1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)  # ドレスローザ leader
    me, opp = st.players[0], st.players[1]
    mansh = InPlay.of(repo.get("OP10-056"), sickness=True)
    sabo = InPlay.of(repo.get(_DR_CHARA_C4), sickness=False)  # cost4 ドレスローザ (コスト対象)
    me.characters = [mansh, sabo]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)     # cost2 (<=4)
    opp.characters = [victim]

    assert me.leader.rested is False
    for prim in _eff(overlay, "OP10-056", "on_play")["do"]:
        execute_effect(prim, st, me, opp, mansh)
        _drain(st, [0])

    assert me.leader.rested is True, "コストで ドレスローザ leader がレストされるべき"
    assert sabo not in me.characters, "コストの コスト4ドレスローザキャラは手札に戻るべき"
    assert any(c.card_id == _DR_CHARA_C4 for c in me.hand), \
        "コストで戻した自キャラは自分の手札に加わるべき"
    assert victim not in opp.characters, "相手のコスト4以下キャラが手札に戻っていない"
    assert any(c.card_id == _FILLER for c in opp.hand), \
        "戻した相手キャラは持ち主 (相手) の手札に加わるべき"


def test_op10_056_on_play_optional_cost_human_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    mansh = InPlay.of(repo.get("OP10-056"), sickness=True)
    sabo = InPlay.of(repo.get(_DR_CHARA_C4), sickness=False)
    me.characters = [mansh, sabo]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    execute_effect(_eff(overlay, "OP10-056", "on_play")["do"][0], st, me, opp, mansh)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 払って発動)
    _drain(st, [0])
    assert me.leader.rested is True, "承諾後 ドレスローザ leader がレストされるべき"
    assert victim not in opp.characters, "承諾後 相手のコスト4以下キャラが手札に戻るべき"


# --------------------------------------------------------------------------- #
#  OP10-057 レオ (CHARACTER 青): 【登場時】自分の、リーダーかステージ1枚をレストにできる：
#          自分のリーダーが「ウソップ」の場合、自分のデッキの上から5枚を見て、「レオ」以外の
#          特徴《ドレスローザ》を持つカード2枚までを公開し、手札に加える。その後、残りを
#          好きな順番でデッキの下に置き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op10_057_on_play_search_dressrosa_and_discard_ai():
    """ウソップleader前提: leaderレスト + 上5枚から「レオ」以外ドレスローザを手札 +
    手札1枚捨て (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_USOPP, overlay)
    me, opp = st.players[0], st.players[1]
    leo = InPlay.of(repo.get("OP10-057"), sickness=True)
    me.characters = [leo]
    me.hand = [repo.get(_FILLER)]  # 捨てる元手 1 枚
    # 上5枚の先頭に「レオ」以外のドレスローザ (= サボ) を仕込む
    me.deck = [repo.get(_DR_CHARA_C4)] + [repo.get(_FILLER)] * 14

    assert me.leader.rested is False
    for prim in _eff(overlay, "OP10-057", "on_play")["do"]:
        execute_effect(prim, st, me, opp, leo)
        _drain(st, [0])

    assert me.leader.rested is True, "コストで leader がレストされるべき"
    assert any(c.card_id == _DR_CHARA_C4 for c in me.hand), \
        "上5枚から「レオ」以外のドレスローザカードが手札に加わっていない"
    assert not any(c.card_id == _FILLER for c in me.hand), \
        "手札1枚捨て で 元の filler が捨てられているべき"


# --------------------------------------------------------------------------- #
#  OP10-058 レベッカ (CHARACTER 青): 【登場時】コスト8以上のキャラがいる場合、1ドロー。
#          その後、手札から「レベッカ」以外の特徴《ドレスローザ》コスト7以下のキャラ2枚まで
#          を公開し、うち1枚を登場、残りがコスト4以下ならレストで登場。
#
#  実装: overlay を `reveal_hand_play_split` primitive に更新 (engine/effects.py 新規)。
#     手札の filter 一致キャラを最大 reveal_limit 枚 公開し、 1 枚を登場・残りが
#     extra_rested_cost_le 以下ならレストで登場。 search primitive はデッキ検索専用の為 専用化。
#     人間 actor は reveal_hand_play_split_pick modal で公開カードを選ぶ (UI = PlayFromHandPickModal 流用)。
# --------------------------------------------------------------------------- #
_DR_CHARA_C3 = "OP10-054"        # ブルーギリー cost3 power5000 特徴ドレスローザ (バニラ)


def test_op10_058_on_play_draw_and_play_from_hand():
    """【登場時】手札のドレスローザ コスト7以下キャラ1枚を公開して登場 (AI 単体)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    reb = InPlay.of(repo.get("OP10-058"), sickness=True)
    me.characters = [reb]
    me.hand = [repo.get(_DR_CHARA_C4)]  # 手札の ドレスローザ コスト7以下キャラ
    for prim in _eff(overlay, "OP10-058", "on_play")["do"]:
        execute_effect(prim, st, me, opp, reb)
        _drain(st, [0])
    assert any(c.card.card_id == _DR_CHARA_C4 for c in me.characters), \
        "手札のドレスローザキャラが登場していない"


def test_op10_058_on_play_reveal_two_active_and_rested_ai():
    """公開2枚 → 1枚を登場、 残りがコスト4以下ならレストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    reb = InPlay.of(repo.get("OP10-058"), sickness=True)
    me.characters = [reb]
    # コスト4 (power5000) + コスト3 (power5000) の ドレスローザ 2 枚 (どちらも ≤4)
    me.hand = [repo.get(_DR_CHARA_C4), repo.get(_DR_CHARA_C3)]
    for prim in _eff(overlay, "OP10-058", "on_play")["do"]:
        execute_effect(prim, st, me, opp, reb)
        _drain(st, [0])
    board = {c.card.card_id: c for c in me.characters}
    assert _DR_CHARA_C4 in board, "公開キャラ (最良) が登場していない"
    assert _DR_CHARA_C3 in board, "公開2枚目 (コスト4以下) がレスト登場していない"
    # 最良 (コスト4) が active、 残り (コスト3) が rested
    assert board[_DR_CHARA_C4].rested is False, "1枚目はアクティブで登場のはず"
    assert board[_DR_CHARA_C3].rested is True, "残り (コスト4以下) はレストで登場のはず"


def test_op10_058_on_play_human_reveal_modal():
    """人間 actor は 公開候補を選ぶ modal (reveal_hand_play_split_pick) が立ち、
    resolve で登場する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    reb = InPlay.of(repo.get("OP10-058"), sickness=True)
    me.characters = [reb]
    me.hand = [repo.get(_DR_CHARA_C4), repo.get(_DR_CHARA_C3)]
    reveal_prim = _eff(overlay, "OP10-058", "on_play")["do"][1]
    execute_effect(reveal_prim, st, me, opp, reb)
    assert st.pending_choice is not None, "人間 + 手札公開で modal が立たない"
    assert st.pending_choice.get("kind") == "reveal_hand_play_split_pick", \
        f"kind が reveal_hand_play_split_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"公開候補が 2 枚でない: {cands}"
    resolve_pending_choice(st, [0, 1])  # 両方公開
    board_ids = {c.card.card_id for c in me.characters}
    assert _DR_CHARA_C4 in board_ids and _DR_CHARA_C3 in board_ids, \
        "人間が公開した2枚が登場していない"


# --------------------------------------------------------------------------- #
#  OP10-059 おまえ…タチ…わ…おれ…が…み…ち…び…く…!!! (EVENT 青): 【メイン】自分のデッキの
#          上から5枚を見て、特徴《ドレスローザ》を持つキャラカード1枚までを公開し、
#          手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op10_059_main_search_dressrosa_chara_to_hand_ai():
    """【メイン】上5枚からドレスローザキャラ1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_DR_CHARA_C4)] + [repo.get(_FILLER)] * 14

    for prim in _eff(overlay, "OP10-059", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    assert any(c.card_id == _DR_CHARA_C4 for c in me.hand), \
        f"上5枚からドレスローザキャラが手札に加わっていない: {[c.card_id for c in me.hand]}"


# --------------------------------------------------------------------------- #
#  OP10-060 バリバリの銃 (EVENT 青): 【メイン】相手のパワー6000以下のキャラ1枚までを、
#          持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op10_060_main_return_opp_power_le6000_to_deck_bottom_ai():
    """【メイン】相手のパワー6000以下1枚をデッキ下へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power4000 (<=6000)
    opp.characters = [victim]
    opp.deck = [repo.get(_FILLER)] * 5
    deck_before = len(opp.deck)

    for prim in _eff(overlay, "OP10-060", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    assert victim not in opp.characters, "パワー6000以下の相手キャラがデッキに戻っていない"
    assert len(opp.deck) == deck_before + 1, "相手デッキが1枚増えるべき"
    assert opp.deck[-1].card_id == _FILLER, "戻したキャラは持ち主のデッキ下に置かれるべき"


def test_op10_060_main_human_target_pick():
    """人間 + 複数候補 → target_pick modal が立ち、 resolve で選んだキャラをデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]
    opp.deck = [repo.get(_FILLER)] * 5

    execute_effect(_eff(overlay, "OP10-060", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだキャラがデッキに戻っていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP10-061 必殺!!遠距離“蓑虫星” (EVENT 青): 【メイン】カード1枚を引く。その後、相手の
#          コスト2以下のキャラ1枚までを、持ち主の手札に戻す。 【トリガー】コスト2以下1枚を手札。
# --------------------------------------------------------------------------- #
def test_op10_061_main_draw_and_bounce_opp_cost_le2_ai():
    """【メイン】1ドロー + 相手コスト2以下1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=2)
    opp.characters = [victim]
    deck_before = len(me.deck)

    for prim in _eff(overlay, "OP10-061", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    assert len(me.hand) == 1 and len(me.deck) == deck_before - 1, "1ドローが起きていない"
    assert victim not in opp.characters, "相手のコスト2以下キャラが手札に戻っていない"
    assert any(c.card_id == _FILLER for c in opp.hand), \
        "戻したキャラは持ち主 (相手) の手札に加わるべき"


def test_op10_061_trigger_bounce_opp_cost_le2_ai():
    """【トリガー】相手コスト2以下1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-061", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    assert victim not in opp.characters, "トリガーで相手のコスト2以下キャラが手札に戻っていない"


def test_op10_061_main_human_target_pick():
    """人間 + 複数候補 → target_pick modal が立ち、 選んだキャラを手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]

    # do[0]=draw, do[1]=bounce。 bounce prim で modal が立つ
    for prim in _eff(overlay, "OP10-061", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    ai = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [ai])
    _drain(st, [ai])
    assert a not in opp.characters, "人間が選んだキャラが手札に戻っていない"
    assert b in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP10-062 ヴァイオレット (CHARACTER 紫): 【ブロッカー】【KO時】ドン‼-1：自分のリーダーが
#          特徴《ドンキホーテ海賊団》を持つ場合、自分のトラッシュから紫のイベント1枚まで
#          を、手札に加える。
# --------------------------------------------------------------------------- #
def test_op10_062_on_ko_recover_purple_event_from_trash_ai():
    """【KO時】ドンキホーテ海賊団leader前提: トラッシュから紫イベント1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DONQ, overlay)
    me, opp = st.players[0], st.players[1]
    vio = InPlay.of(repo.get("OP10-062"), sickness=False)
    me.characters = [vio]
    me.trash = [repo.get(_PURPLE_EVENT), repo.get(_FILLER)]
    trash_before = len(me.trash)

    for prim in _eff(overlay, "OP10-062", "on_ko")["do"]:
        execute_effect(prim, st, me, opp, vio)
        _drain(st, [0])

    assert any(c.card_id == _PURPLE_EVENT for c in me.hand), \
        "KO時にトラッシュの紫イベントが手札に戻っていない"
    assert len(me.trash) == trash_before - 1, "トラッシュが1枚減るべき"


def test_op10_062_overlay_has_don_cost_and_leader_gate():
    """overlay に ドン‼-1 コスト (pay_don=1) と リーダー特徴 gate が登録されている。"""
    overlay = _overlay()
    eff = _eff(overlay, "OP10-062", "on_ko")
    assert eff.get("cost", {}).get("pay_don") == 1, \
        "overlay に ドン‼-1 (pay_don=1) コストが無い"
    assert eff.get("if", {}).get("leader_feature") == "ドンキホーテ海賊団", \
        "overlay に リーダー特徴《ドンキホーテ海賊団》 gate が無い"


# --------------------------------------------------------------------------- #
#  OP10-066 ジョーラ (CHARACTER 紫): 【相手のアタック時】【ターン1回】自分のドン!!2枚を
#          レストにできる：相手のコスト4以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op10_066_opp_attack_rest_opp_cost_le4_ai():
    """【相手のアタック時】相手コスト4以下1枚をレストにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    jora = InPlay.of(repo.get("OP10-066"), sickness=False)
    me.characters = [jora]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]

    assert victim.rested is False
    for prim in _eff(overlay, "OP10-066", "opp_attack")["do"]:
        execute_effect(prim, st, me, opp, jora)
        _drain(st, [0])

    assert victim.rested is True, "相手のコスト4以下キャラがレストされていない"


def test_op10_066_opp_attack_human_target_pick():
    """人間 + 複数候補 → target_pick modal が立ち、 選んだキャラをレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    jora = InPlay.of(repo.get("OP10-066"), sickness=False)
    me.characters = [jora]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP10-066", "opp_attack")["do"][0], st, me, opp, jora)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b.rested is True, "人間が選んだキャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP10-069 闘魚 (CHARACTER 紫): 【ドン‼×1】【アタック時】ドン‼-1：相手のコスト1以下の
#          キャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op10_069_on_attack_ko_opp_cost_le1_ai():
    """【アタック時】相手コスト1以下1枚をKOする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    gyo = InPlay.of(repo.get("OP10-069"), sickness=False)
    gyo.attached_dons = 1  # 【ドン‼×1】ゲート成立
    me.characters = [gyo]
    small = InPlay.of(repo.get(_COST1_CHARA), sickness=False)  # cost1 (<=1)
    opp.characters = [small]

    for prim in _eff(overlay, "OP10-069", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, gyo)
        _drain(st, [0])

    assert small not in opp.characters, "相手のコスト1以下キャラがKOされていない"
    assert any(c.card_id == _COST1_CHARA for c in opp.trash), \
        "KOされたキャラは持ち主のトラッシュに置かれるべき"


def test_op10_069_on_attack_don_gate_condition():
    """【ドン‼×1】ゲート: overlay に self_attached_don_ge=1 の if が登録されている。"""
    overlay = _overlay()
    eff = _eff(overlay, "OP10-069", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay に 【ドン‼×1】ゲート (self_attached_don_ge=1) が無い"
    assert eff.get("cost", {}).get("pay_don") == 1, \
        "overlay に ドン‼-1 (pay_don=1) コストが無い"


def test_op10_069_on_attack_no_ko_cost2_target():
    """コスト2の相手キャラは対象外 (コスト1以下限定) → KOされない (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    gyo = InPlay.of(repo.get("OP10-069"), sickness=False)
    gyo.attached_dons = 1
    me.characters = [gyo]
    big = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (対象外)
    opp.characters = [big]

    for prim in _eff(overlay, "OP10-069", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, gyo)
        _drain(st, [0])

    assert big in opp.characters, "コスト2の相手キャラはKOされてはいけない"


# --------------------------------------------------------------------------- #
#  OP10-070 トレーボル (CHARACTER 紫): 【ブロッカー】【登場時】次の相手のターン終了時まで、
#          自分の元々のパワー1000以下のキャラすべては、相手の効果でKOされない。
# --------------------------------------------------------------------------- #
def test_op10_070_on_play_ko_immune_low_power_self_charas_ai():
    """【登場時】自分の元々パワー1000以下のキャラすべてにKO耐性を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    treb = InPlay.of(repo.get("OP10-070"), sickness=True)
    low = InPlay.of(repo.get(_LOW_POWER), sickness=False)   # power1000 (<=1000)
    high = InPlay.of(repo.get(_FILLER), sickness=False)     # power4000 (対象外)
    me.characters = [treb, low, high]

    for prim in _eff(overlay, "OP10-070", "on_play")["do"]:
        execute_effect(prim, st, me, opp, treb)
        _drain(st, [0])

    assert low.ko_immune_through_opp_turn is True, \
        "元々パワー1000以下のキャラは相手効果KO耐性を得るべき"
    assert high.ko_immune_through_opp_turn is False, \
        "元々パワー1000超のキャラはKO耐性を得てはいけない"
