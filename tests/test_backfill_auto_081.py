# -*- coding: utf-8 -*-
"""OP07 弾 効果 回帰テスト バックフィル (自動生成 wave 081):
OP07-102 / OP07-103 / OP07-104 / OP07-105 / OP07-106 / OP07-107 /
OP07-109 / OP07-110 / OP07-111 / OP07-112 の 10 枚
(黄 エッグヘッド/ベガパンク ライフ管理・トリガー登場 系 + 空島/革命軍 KO・rest 系)。

目的 (= 永続的 pytest による担保、 test_backfill_auto_080.py と同一方針):
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
    eval_condition,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"     # ロロノア・ゾロ (赤、 直接 execute_effect なので色は無関係)
_VEGAPUNK = "OP07-097"   # ベガパンク (LEADER 黄、 name「ベガパンク」 + 特徴 エッグヘッド)
_FILLER = "OP01-013"     # サンジ cost2 power3000 (汎用フィラー)
_OPP_C = "OP01-013"      # サンジ cost2 (相手 cost<=3/<=4 の KO 対象)
_OPP_C1 = "OP06-025"     # ケイミー cost1 (相手 cost<=2 の KO 対象)
_EGG_C = "OP07-104"      # ニコ・ロビン cost3 特徴 エッグヘッド (自陣 エッグヘッド キャラ)
_EGG_C2 = "OP07-110"     # ヨーク cost5 特徴 エッグヘッド (自陣 エッグヘッド キャラ 2)


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


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    return _eff(overlay, cid, when)["do"]


def _drain(st, pick=0, guard=15):
    """pending_choice を pick で自動解決し切る (= 後続効果を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave81_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP07-102", "OP07-103", "OP07-104", "OP07-105", "OP07-106",
           "OP07-107", "OP07-109", "OP07-110", "OP07-111", "OP07-112"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP07-102 ジンベエ (CHARACTER 黄 cost5):
#    【トリガー】相手のコスト4以下のキャラ1枚までを、持ち主の手札に戻す。
#                その後、このカードを手札に加える。
# --------------------------------------------------------------------------- #
def test_op07_102_trigger_return_opp_and_keep_self_ai():
    """トリガー: 相手コスト4以下キャラ1枚を持ち主の手札へ + 自身を手札に (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)  # サンジ cost2 (<=4)
    opp.characters = [victim]
    opp.hand = []

    for prim in _do(overlay, "OP07-102", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, "相手コスト4以下キャラが場から戻っていない"
    assert len(opp.hand) == 1, "戻したキャラが持ち主 (相手) の手札に加わっていない"
    assert st.last_trigger_kept_in_hand is True, \
        "to_hand_self_trigger で このカードを手札に加えるフラグが立っていない"


def test_op07_102_trigger_return_human_pick():
    """人間 + 相手コスト4以下キャラ 複数 → target_pick modal → 選んだ方を戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C1), sickness=False)   # ケイミー cost1
    b = InPlay.of(repo.get(_OPP_C), sickness=False)    # サンジ cost2
    opp.characters = [a, b]
    opp.hand = []

    execute_effect(_do(overlay, "OP07-102", "trigger")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (相手キャラ2体) が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが手札に戻っていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


# --------------------------------------------------------------------------- #
#  OP07-103 トニートニー・チョッパー (CHARACTER 黄 cost2):
#    【トリガー】自分の特徴《エッグヘッド》を持つキャラ1枚までを、このターン中、
#                【ブロッカー】にする。その後、このカードを手札に加える。
# --------------------------------------------------------------------------- #
def test_op07_103_trigger_give_blocker_to_egghead_ai():
    """トリガー: 自エッグヘッドキャラ1枚に【ブロッカー】(turn) 付与 + 自身手札 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    egg = InPlay.of(repo.get(_EGG_C), sickness=False)  # ロビン エッグヘッド (非ブロッカー)
    assert egg.is_blocker_now is False, "テスト前提: ロビンは元々ブロッカーでない"
    me.characters = [egg]

    for prim in _do(overlay, "OP07-103", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert "ブロッカー" in egg.granted_keywords, \
        "自エッグヘッドキャラに【ブロッカー】が付与されていない"
    assert egg.is_blocker_now is True, "付与後 is_blocker_now が True にならない"
    assert st.last_trigger_kept_in_hand is True, \
        "to_hand_self_trigger で このカードを手札に加えるフラグが立っていない"


def test_op07_103_trigger_give_blocker_human_pick():
    """人間 + エッグヘッドキャラ 複数 → target_pick modal → 選んだ方に【ブロッカー】。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_EGG_C), sickness=False)    # ロビン エッグヘッド
    b = InPlay.of(repo.get(_EGG_C2), sickness=False)   # ヨーク エッグヘッド
    me.characters = [a, b]

    execute_effect(_do(overlay, "OP07-103", "trigger")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (エッグヘッド2体) が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert "ブロッカー" in b.granted_keywords, "人間が選んだキャラに【ブロッカー】が付与されていない"
    assert "ブロッカー" not in a.granted_keywords, "選ばなかった側に付与されてはいけない"


# --------------------------------------------------------------------------- #
#  OP07-104 ニコ・ロビン (CHARACTER 黄 cost3):
#    【トリガー】自分のリーダーが特徴《エッグヘッド》を持つ場合、カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op07_104_trigger_draw2_ai():
    """トリガー: カード2枚を引く (AI、 do 直接発火で draw2 を検証)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _VEGAPUNK, overlay)  # エッグヘッド leader → 条件成立
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP07-104", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == 2, "トリガーの draw2 が起きていない"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減っていない"


def test_op07_104_leader_feature_condition():
    """条件: 自リーダーが特徴《エッグヘッド》を持つ場合のみ成立。"""
    repo = _repo()
    overlay = _overlay()
    cond = _eff(overlay, "OP07-104", "trigger").get("if")
    assert cond is not None and cond.get("leader_feature") == "エッグヘッド", \
        "OP07-104 に leader_feature=エッグヘッド 条件がない"
    st = _state(repo, _VEGAPUNK, overlay)  # ベガパンク (エッグヘッド)
    me = st.players[0]
    assert eval_condition(cond, st, me) is True, \
        "エッグヘッド リーダーで条件が成立するべき"
    st2 = _state(repo, _LEADER, overlay)  # ゾロ (非エッグヘッド)
    assert eval_condition(cond, st2, st2.players[0]) is False, \
        "非エッグヘッド リーダーで条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP07-105 ピタゴラス (CHARACTER 黄 cost5):
#    【KO時】自分のライフが2枚以下の場合、自分のトラッシュからコスト4以下の
#      特徴《エッグヘッド》を持つキャラカード1枚までを、レストで登場させる。
#    【トリガー】自分のリーダーが「ベガパンク」の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op07_105_on_ko_revive_egghead_from_trash_ai():
    """KO時: 自トラッシュのコスト4以下 エッグヘッド キャラ1枚を レストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # ライフ2以下 (= 条件成立)
    me.trash = [repo.get(_EGG_C)]      # ロビン cost3 エッグヘッド
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP07-105", "on_ko"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-105"), sickness=False))
    _drain(st)
    revived = [c for c in me.characters if c.card.card_id == _EGG_C]
    assert len(revived) == 1, "トラッシュから エッグヘッド キャラが登場していない"
    assert revived[0].rested is True, "レストで登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_op07_105_on_ko_life_condition():
    """条件: 自ライフ2枚以下で成立、 3枚以上で不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    cond = _eff(overlay, "OP07-105", "on_ko").get("if")
    assert cond is not None, "OP07-105 に self_life_le 条件がない"
    me.life = [repo.get(_FILLER)] * 2
    assert eval_condition(cond, st, me) is True, "ライフ2枚で条件が成立するべき"
    me.life = [repo.get(_FILLER)] * 3
    assert eval_condition(cond, st, me) is False, "ライフ3枚で条件が成立してはいけない"


def test_op07_105_trigger_play_self_ai():
    """トリガー: 自リーダーが「ベガパンク」なら このカードを登場 (play_self、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _VEGAPUNK, overlay)  # リーダー = ベガパンク
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP07-105")]
    st.current_source_card_id = "OP07-105"
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP07-105", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card.card_id == "OP07-105" for c in me.characters), \
        "トリガー play_self で ピタゴラス が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP07-106 フザ (CHARACTER 黄 cost4):
#    【ドン‼×1】【アタック時】自分のライフが1枚以下の場合、相手のコスト3以下の
#      キャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op07_106_on_attack_ko_cost3_ai():
    """アタック時: 相手コスト3以下キャラ1枚を KO (AI、 do 直接発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)  # サンジ cost2 (<=3)
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-106", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-106"), sickness=False))
    _drain(st)
    assert victim not in opp.characters, "アタック時に相手コスト3以下キャラが KO されていない"


def test_op07_106_don_and_life_gate():
    """条件: 【ドン‼×1】(self_attached_don_ge=1) + 自ライフ1以下 (self_life_le=1)。"""
    repo = _repo()
    overlay = _overlay()
    cond = _eff(overlay, "OP07-106", "on_attack").get("if")
    assert cond is not None, "OP07-106 に発動条件がない"
    assert cond.get("self_attached_don_ge") == 1, "ドンゲート self_attached_don_ge=1 が無い"
    assert cond.get("self_life_le") == 1, "ライフ条件 self_life_le=1 が無い"


def test_op07_106_on_attack_ko_human_pick():
    """人間 + 相手コスト3以下キャラ 複数 → target_pick modal → 選んだ方を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C1), sickness=False)  # ケイミー cost1
    b = InPlay.of(repo.get(_OPP_C), sickness=False)   # サンジ cost2
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP07-106", "on_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP07-106"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP07-107 フランキー (CHARACTER 黄 cost4):
#    【トリガー】カード1枚を引く。その後、自分のライフが1枚以下の場合、
#      このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op07_107_trigger_draw_then_play_self_when_low_life_ai():
    """トリガー: 1枚引く + (ライフ1以下) このカードを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 1  # ライフ1以下 → play_self 条件成立
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []
    me.trash = [repo.get("OP07-107")]  # 登場元 (trigger 後 self は trash に居る)
    st.current_source_card_id = "OP07-107"
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP07-107", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card.card_id == "OP07-107" for c in me.characters), \
        "ライフ1以下で フランキー が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_op07_107_trigger_no_play_self_when_high_life_ai():
    """ライフ2枚以上 → conditional 不成立。 draw はするが 登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3  # ライフ3枚 → 条件不成立
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []
    me.trash = [repo.get("OP07-107")]
    st.current_source_card_id = "OP07-107"
    hand_before = len(me.hand)

    for prim in _do(overlay, "OP07-107", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == hand_before + 1, "draw はライフに関係なく起きるべき"
    assert not any(c.card.card_id == "OP07-107" for c in me.characters), \
        "ライフ2枚以上で フランキー が登場してはいけない"


# --------------------------------------------------------------------------- #
#  OP07-109 モンキー・D・ルフィ (CHARACTER 黄 cost5):
#    【起動メイン】このキャラをトラッシュに置くことができる：自分のライフが2枚以下の場合、
#      相手のコスト4以下のキャラ1枚までを、KOする。その後、カード1枚を引く。
#    【トリガー】相手のコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op07_109_activate_main_trash_self_ko_draw_ai():
    """起動メイン: 自身をトラッシュ (コスト) → (ライフ2以下) 相手コスト4以下KO + 1ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP07-109"), sickness=False)
    me.characters = [luffy]
    me.life = [repo.get(_FILLER)] * 2  # ライフ2以下 (= 条件成立)
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)  # サンジ cost2 (<=4)
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-109"]
    assert len(opts) == 1, f"OP07-109 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert luffy not in me.characters, "コストで ルフィ自身がトラッシュに置かれるべき"
    assert victim not in opp.characters, "相手コスト4以下キャラが KO されていない"
    assert len(me.hand) == 1, "その後の 1ドロー が起きていない"


def test_op07_109_trigger_ko_cost4_ai():
    """トリガー: 相手コスト4以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-109", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, "トリガーで相手コスト4以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP07-110 ヨーク (CHARACTER 黄 cost5):
#    【登場時】自分のライフの上か下から1枚を手札に加えることができる：
#      相手のコスト2以下のキャラ1枚までを、KOする。
#    【トリガー】自分のリーダーが「ベガパンク」の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op07_110_on_play_optional_life_cost_ko_ai():
    """登場時: 任意コスト (ライフ上下1枚→手札) を払い、 相手コスト2以下キャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = []
    victim = InPlay.of(repo.get(_OPP_C1), sickness=False)  # ケイミー cost1 (<=2)
    opp.characters = [victim]
    life_before = len(me.life)

    for prim in _do(overlay, "OP07-110", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-110"), sickness=True))
    _drain(st)
    assert victim not in opp.characters, "任意コスト後に相手コスト2以下キャラが KO されていない"
    assert len(me.life) == life_before - 1, "コストで ライフが1枚減っていない"
    assert len(me.hand) == 1, "ライフ1枚が手札に加わっていない"


def test_op07_110_on_play_human_optional_cost():
    """登場時 (人間): optional_cost_confirm modal → pay ([1]) で KO まで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = []
    victim = InPlay.of(repo.get(_OPP_C1), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-110", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-110"), sickness=True))
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st)
    assert victim not in opp.characters, "任意コスト承認後に KO が解決されていない"


def test_op07_110_trigger_play_self_ai():
    """トリガー: 自リーダーが「ベガパンク」なら このカードを登場 (play_self、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _VEGAPUNK, overlay)  # リーダー = ベガパンク
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP07-110")]
    st.current_source_card_id = "OP07-110"
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP07-110", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card.card_id == "OP07-110" for c in me.characters), \
        "トリガー play_self で ヨーク が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP07-111 リリス (CHARACTER 黄 cost3):
#    【登場時】自分のデッキの上から5枚を見て、「リリス」以外の特徴《エッグヘッド》を持つ
#      カード1枚までを手札に加える。その後、残りを好きな順番でデッキの下に置く。
#    【トリガー】自分のリーダーが「ベガパンク」の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op07_111_on_play_search_egghead_ai():
    """登場時: デッキ上5枚から エッグヘッド (リリス以外) 1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    egg = repo.get(_EGG_C)  # ロビン エッグヘッド
    assert "エッグヘッド" in (egg.features or ""), "テスト前提: ロビンは エッグヘッド"
    me.deck = [egg] + [repo.get(_FILLER)] * 20  # 上5枚に エッグヘッド を仕込む
    me.hand = []

    for prim in _do(overlay, "OP07-111", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-111"), sickness=True))
    _drain(st)
    assert any(c.card_id == _EGG_C for c in me.hand), \
        "デッキ上5枚から エッグヘッド キャラが手札に加わっていない"


def test_op07_111_on_play_search_human_modal():
    """登場時 (人間): デッキ上5枚に エッグヘッド 複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    egg = repo.get(_EGG_C)
    me.deck = [egg, repo.get(_FILLER), egg] + [repo.get(_FILLER)] * 15
    me.hand = []

    execute_effect(_do(overlay, "OP07-111", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP07-111"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (エッグヘッド) を選択
    _drain(st, pick=0)
    assert any(c.card_id == _EGG_C for c in me.hand), \
        "人間が選んだ エッグヘッド キャラが手札に加わっていない"


def test_op07_111_trigger_play_self_ai():
    """トリガー: 自リーダーが「ベガパンク」なら このカードを登場 (play_self、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _VEGAPUNK, overlay)  # リーダー = ベガパンク
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP07-111")]
    me.deck = [repo.get(_FILLER)] * 10  # on_play (登場→search) が続けて発火しても走れるよう
    st.current_source_card_id = "OP07-111"
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP07-111", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card.card_id == "OP07-111" for c in me.characters), \
        "トリガー play_self で リリス が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP07-112 ルーシー (CHARACTER 黄 cost6):
#    【アタック時】【ターン1回】自分のライフの上か下から1枚を手札に加えることができる：
#      相手のコスト4以下のキャラ1枚までを、レストにできる。その後、自分のライフが1枚以下の
#      場合、デッキの上から1枚までを、ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op07_112_on_attack_optional_rest_then_life_ai():
    """アタック時: 任意コスト (ライフ上下1枚→手札) → 相手コスト4以下を レスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # 払うと1枚に → その後 put_top_to_life 条件成立
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)  # サンジ cost2 (<=4)
    victim.rested = False
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-112", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-112"), sickness=False))
    _drain(st)
    assert victim.rested is True, "任意コスト後に相手コスト4以下キャラが レストされていない"
    assert len(me.hand) == 1, "コストで ライフ1枚が手札に加わっていない"


def test_op07_112_on_attack_human_optional_cost():
    """アタック時 (人間): optional_cost_confirm modal → pay ([1]) で レストまで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)
    victim.rested = False
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-112", "on_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-112"), sickness=False))
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st)
    assert victim.rested is True, "任意コスト承認後に レストが解決されていない"
