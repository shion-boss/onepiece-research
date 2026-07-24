# -*- coding: utf-8 -*-
"""OP05 弾 効果 回帰テスト バックフィル (自動生成 wave 062):
OP05-099 / OP05-100 / OP05-101 / OP05-102 / OP05-103 / OP05-104 /
OP05-105 / OP05-106 / OP05-109 / OP05-111 の 10 枚 (黄・空島 系)。

目的 (= 永続的 pytest による担保、 test_backfill_auto_061.py と同一方針):
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
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_NEUTRAL = "OP01-001"   # ロロノア・ゾロ (赤、 単色)
_NAMI = "OP01-016"             # ナミ 赤 cost1 power2000
_RED_C2 = "ST01-004"           # サンジ 赤 cost2 power4000 (汎用フィラー)
_RED_C3 = "EB02-003"           # トニートニー・チョッパー 赤 cost3 power3000
_HOLY = "OP05-110"             # ホーリー 黄 cost3 power5000 (空島)
_STAGE = "EB02-060"            # ゴーイング・メリー号 黄 cost2 (ステージ)
_KOTORI = "OP05-103"           # コトリ 黄 cost3 (ホトリのコスト対象)
_HOTORI = "OP05-111"           # ホトリ 黄 cost3


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_RED_C2)] * 30
    p1.deck = [repo.get(_RED_C2)] * 30
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


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave62_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP05-099", "OP05-100", "OP05-101", "OP05-102", "OP05-103",
           "OP05-104", "OP05-105", "OP05-106", "OP05-109", "OP05-111"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP05-099 アマゾン (CHARACTER 黄 cost3 空島):
#    【相手のアタック時】このキャラをレストにできる：相手は自身のライフの上から1枚を、
#      トラッシュに置いてもよい。そうしなかった場合、相手のリーダーかキャラ1枚までを、
#      このターン中、パワー-2000。
#  overlay は debuff 側 (power_pump one_opponent_inplay_any -2000) を実装。
# --------------------------------------------------------------------------- #
def test_op05_099_opp_attack_power_minus_ai():
    """相手のアタック時 (AI): 相手のリーダーかキャラ1枚を このターン中 パワー-2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    amazon = InPlay.of(repo.get("OP05-099"), sickness=False)
    me.characters = [amazon]
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # power4000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _do(overlay, "OP05-099", "opp_attack"):
        execute_effect(prim, st, me, opp, amazon)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert victim.power == power_before - 2000, \
        f"相手キャラに -2000 が反映されていない: {victim.power} (before {power_before})"


def test_op05_099_opp_attack_power_minus_human_pick():
    """相手のアタック時 (人間): 相手リーダー+キャラ 複数 → target_pick modal で選択。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    amazon = InPlay.of(repo.get("OP05-099"), sickness=False)
    me.characters = [amazon]
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)
    opp.characters = [victim]

    execute_effect(_do(overlay, "OP05-099", "opp_attack")[0], st, me, opp, amazon)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (相手リーダー+キャラ) が 2 件でない: {len(cands)}"

    v_idx = next(i for i, c in enumerate(cands) if c["iid"] == victim.instance_id)
    v_before = victim.power
    resolve_pending_choice(st, [v_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert victim.power == v_before - 2000, \
        "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-100 エネル (CHARACTER 黄 cost7 power7000 空島):
#    【速攻】【ターン1回】このキャラが場を離れる場合、代わりに自分のライフの上から1枚を
#      トラッシュに置いてもよい。("ルフィ" 不在で有効、 overlay は mill_self_life_to_trash)
# --------------------------------------------------------------------------- #
def test_op05_100_replace_leave_mill_life_ai():
    """場を離れる代替 (AI): 自分のライフの上から1枚をトラッシュへ (life -1 / trash +1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_RED_C2)] * 3
    me.trash = []
    life_before = len(me.life)
    trash_before = len(me.trash)

    for prim in _do(overlay, "OP05-100", "replace_leave"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-100"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert len(me.life) == life_before - 1, "ライフの上から1枚がトラッシュに置かれていない"
    assert len(me.trash) == trash_before + 1, "トラッシュが1枚増えていない"


# --------------------------------------------------------------------------- #
#  OP05-101 オーム (CHARACTER 黄 cost4 power5000 空島/神官):
#    自分のライフが2枚以下の場合、このキャラはパワー+1000。
#    【登場時】自分のデッキの上から5枚を見て、「ホーリー」1枚までを公開し手札に加える。
#      その後、残りをデッキの下に置き、自分の手札から「ホーリー」1枚までを登場させる。
# --------------------------------------------------------------------------- #
def test_op05_101_static_power_when_life_le2():
    """静的: 自分のライフが2枚以下なら パワー+1000 / 3枚では乗らない。"""
    repo = _repo()
    overlay = _overlay()
    ohm_def = repo.get("OP05-101")  # power5000

    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, _ = st.players[0], st.players[1]
    me.life = [repo.get(_RED_C2)] * 2  # 2枚以下 = 条件成立
    ohm = InPlay.of(ohm_def, sickness=False)
    me.characters = [ohm]
    evaluate_static_effects(st, overlay)
    assert ohm.power == ohm_def.power + 1000, \
        f"ライフ2枚以下で +1000 が乗っていない: {ohm.power} (base {ohm_def.power})"

    st2 = _state(repo, _LEADER_NEUTRAL, overlay)
    me2, _ = st2.players[0], st2.players[1]
    me2.life = [repo.get(_RED_C2)] * 3  # 3枚 = 不成立
    ohm2 = InPlay.of(ohm_def, sickness=False)
    me2.characters = [ohm2]
    evaluate_static_effects(st2, overlay)
    assert ohm2.power == ohm_def.power, \
        f"ライフ3枚なのに +1000 が乗った: {ohm2.power} (base {ohm_def.power})"


def test_op05_101_on_play_search_and_play_holy_ai():
    """登場時 (AI): デッキ上から「ホーリー」を手札に → 手札の「ホーリー」を登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_HOLY)] + [repo.get(_RED_C2)] * 10  # 上に ホーリー
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP05-101", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-101"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card.card_id == _HOLY for c in me.characters), \
        "手札に加えた「ホーリー」が登場していない"
    assert len(me.deck) == deck_before - 1, "デッキから「ホーリー」1枚が抜けていない"


# --------------------------------------------------------------------------- #
#  OP05-102 ゲダツ (CHARACTER 黄 cost5 power6000 空島/神官):
#    【登場時】相手のライフの枚数以下のコストを持つ相手のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op05_102_on_play_ko_cost_le_opp_life_ai():
    """登場時 (AI): 相手ライフ枚数以下のコストの相手キャラをKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_RED_C2)] * 3       # ライフ3枚 → cost3以下がKO対象
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2 <= 3
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-102", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-102"), sickness=False))

    assert victim not in opp.characters, "コスト <= 相手ライフ枚数のキャラがKOされていない"


def test_op05_102_on_play_no_ko_when_cost_gt_life():
    """相手ライフ1枚 vs cost3キャラ → コスト超過でKO対象にならない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_RED_C2)] * 1       # ライフ1枚
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 > 1
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-102", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-102"), sickness=False))

    assert victim in opp.characters, "コストが相手ライフ枚数を超えるのにKOされた"


def test_op05_102_on_play_ko_human_pick():
    """登場時 (人間): KO対象が複数 → target_pick modal で選択して解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_RED_C2)] * 3
    a = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    opp.characters = [a, b]

    for prim in _do(overlay, "OP05-102", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-102"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数KO候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"KO候補が 2 件でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert a not in opp.characters, "人間が選んだキャラがKOされていない"


# --------------------------------------------------------------------------- #
#  OP05-103 コトリ (CHARACTER 黄 cost3 power3000 空島):
#    【登場時】自分の「ホトリ」がいる場合、相手のライフの枚数以下のコストを持つ
#      相手のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op05_103_on_play_ko_with_hotori_ai():
    """登場時 (AI): 自分の「ホトリ」が居れば 相手ライフ枚数以下コストの相手キャラをKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_HOTORI), sickness=False)]  # ホトリ 在場
    opp.life = [repo.get(_RED_C2)] * 3
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2
    opp.characters = [victim]

    eff = _eff(overlay, "OP05-103", "on_play")
    assert eval_condition(eff.get("if", {}), st, me), \
        "ホトリ 在場で条件成立のはず"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-103"), sickness=False))

    assert victim not in opp.characters, "ホトリ 在場でKOが発火していない"


def test_op05_103_gate_not_met_without_hotori():
    """自分の「ホトリ」が居なければ 登場時条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, _ = st.players[0], st.players[1]
    me.characters = []  # ホトリ 不在

    eff = _eff(overlay, "OP05-103", "on_play")
    assert not eval_condition(eff.get("if", {}), st, me), \
        "ホトリ 不在なのに条件成立している"


# --------------------------------------------------------------------------- #
#  OP05-104 コニス (CHARACTER 黄 cost1 空島):
#    【登場時】自分のステージ1枚をデッキの下に置くことができる：
#      カード1枚を引き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op05_104_on_play_stage_to_deck_then_draw_discard_ai():
    """登場時 (AI): 自ステージ1枚をデッキ下 → 1枚ドロー + 手札1枚捨て。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get(_STAGE), sickness=False)
    me.stages = [stage]
    me.hand = [repo.get(_NAMI)]
    me.deck = [repo.get(_RED_C2)] * 10
    stages_before = len(me.stages)

    for prim in _do(overlay, "OP05-104", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-104"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert len(me.stages) == stages_before - 1, "ステージがデッキ下に置かれていない"
    assert any(c.card_id == _STAGE for c in me.deck), \
        "デッキ下に置いたステージがデッキに存在しない"


# --------------------------------------------------------------------------- #
#  OP05-105 サトリ (CHARACTER 黄 cost5 power5000 空島/神官):
#    【トリガー】自分の手札1枚を捨てることができる：このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op05_105_trigger_discard_then_play_self_ai():
    """トリガー (AI): 手札1枚を捨てて 自身 (サトリ) を登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    # トリガー発火時、 めくれた自身は trash 相当 + current_source_card_id で参照される
    me.trash = [repo.get("OP05-105")]
    st.current_source_card_id = "OP05-105"
    me.hand = [repo.get(_NAMI)]  # コスト (捨て札) 用
    hand_before = len(me.hand)
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP05-105", "trigger"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card.card_id == "OP05-105" for c in me.characters), \
        "トリガー play_self で サトリ が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"
    assert len(me.hand) == hand_before - 1, "コストの手札1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  OP05-106 シュラ (CHARACTER 黄 cost2 power2000 空島/神官):
#    【登場時】自分のデッキの上から5枚を見て、「シュラ」以外の特徴《空島》を持つ
#      カード1枚までを公開し手札に加える。その後、残りをデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op05_106_on_play_search_sky_ai():
    """登場時 (AI): デッキ上5枚から 空島 カード1枚を手札に加える (deck -1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_HOLY)] + [repo.get(_RED_C2)] * 10  # 上に 空島 (ホーリー)
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP05-106", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-106"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card_id == _HOLY for c in me.hand), \
        "デッキ上の 空島 カードが手札に加わっていない"
    assert len(me.deck) == deck_before - 1, "手札に加えた分だけデッキが減っていない"


# --------------------------------------------------------------------------- #
#  OP05-109 パガヤ (CHARACTER 黄 cost1 power1000 空島):
#    【ターン1回】【トリガー】が発動した時、カード2枚を引き、自分の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op05_109_trigger_draw2_discard2_ai():
    """トリガー (AI): カード2枚を引き、 手札2枚を捨てる (deck -2 / trash +2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_NAMI), repo.get(_NAMI)]  # 捨てる2枚を確保
    me.deck = [repo.get(_RED_C2)] * 20
    me.trash = []
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    for prim in _do(overlay, "OP05-109", "trigger"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert len(me.deck) == deck_before - 2, "カード2枚を引いていない (deck -2)"
    assert len(me.trash) == trash_before + 2, "手札2枚が捨てられていない (trash +2)"


# --------------------------------------------------------------------------- #
#  OP05-111 ホトリ (CHARACTER 黄 cost3 power3000 空島):
#    【登場時】自分の手札から「コトリ」1枚を登場できる：相手のコスト3以下のキャラ1枚
#      までを、相手のライフの上か下に表向きで加える。
# --------------------------------------------------------------------------- #
def test_op05_111_on_play_play_kotori_then_chara_to_opp_life_ai():
    """登場時 (AI): 手札の「コトリ」を登場 → 相手のコスト3以下キャラを相手ライフへ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_KOTORI)]  # コスト (登場) 用の コトリ
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3 の相手キャラ
    opp.characters = [victim]
    opp.life = [repo.get(_RED_C2)] * 2
    opp_life_before = len(opp.life)

    for prim in _do(overlay, "OP05-111", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-111"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card.card_id == _KOTORI for c in me.characters), \
        "コスト支払いで「コトリ」が登場していない"
    assert victim not in opp.characters, "相手コスト3以下キャラが盤面から除かれていない"
    assert len(opp.life) == opp_life_before + 1, \
        "除いた相手キャラが相手ライフに加わっていない"
