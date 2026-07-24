# -*- coding: utf-8 -*-
"""OP07 弾 効果 回帰テスト バックフィル (自動生成 wave 073):
OP07-003 / OP07-004 / OP07-005 / OP07-006 / OP07-008 / OP07-009 /
OP07-010 / OP07-011 / OP07-012 / OP07-013 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_072.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 択一 / 任意コスト を 持つカードは 人間 actor で pending_choice が
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

_LEADER = "OP01-001"    # ロロノア・ゾロ (赤、 汎用リーダー・特徴なし前提)
_FILLER = "OP01-013"    # サンジ cost2 power3000 (汎用フィラー、 登場時なし)
_RED1 = "EB04-002"      # ジュエリー・ボニー cost1 power2000 赤 (コスト1赤キャラ用ヘルパー)
_ACE_LEADER = "OP03-001"  # ポートガス・D・エース (リーダー名条件用)
_RED_EVENT = "EB04-008"   # 歪んだ未来 (赤イベント、 OP07-013 サーチ対象用)


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
def test_all_wave73_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP07-003", "OP07-004", "OP07-005", "OP07-006", "OP07-008",
           "OP07-009", "OP07-010", "OP07-011", "OP07-012", "OP07-013"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP07-003 アウトルック3世 (CHARACTER 赤 cost2):
#    【起動メイン】このキャラをトラッシュに置くことができる：
#      相手のキャラ2枚までを、このターン中、パワー-2000。
# --------------------------------------------------------------------------- #
def test_op07_003_activate_main_debuff_two_opp_ai():
    """起動メイン: 自身をトラッシュに置き → 相手キャラ2枚まで -2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    outlook = InPlay.of(repo.get("OP07-003"), sickness=False)
    me.characters = [outlook]
    v1 = InPlay.of(repo.get(_FILLER), sickness=False)  # power 3000
    v2 = InPlay.of(repo.get(_FILLER), sickness=False)  # power 3000
    opp.characters = [v1, v2]
    p1_before, p2_before = v1.power, v2.power

    options = list_activate_main_effects(st, me, overlay)
    outlook_opts = [(src, eff) for (src, eff) in options
                    if src.card.card_id == "OP07-003"]
    assert len(outlook_opts) == 1, \
        f"OP07-003 の起動メインが legal に出ない: {len(outlook_opts)}"
    fire_activate_main(st, me, opp, *outlook_opts[0])
    _drain(st)

    assert outlook not in me.characters, "コストで アウトルック3世 がトラッシュに置かれていない"
    assert v1.power == p1_before - 2000 and v2.power == p2_before - 2000, \
        f"相手キャラ2枚が -2000 されていない: {v1.power}/{v2.power}"


def test_op07_003_activate_main_single_opp_ai():
    """起動メイン: 相手キャラ1枚のみでも (2枚まで) -2000 が乗る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    outlook = InPlay.of(repo.get("OP07-003"), sickness=False)
    me.characters = [outlook]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]
    before = victim.power

    fire_activate_main(st, me, opp, *[o for o in list_activate_main_effects(st, me, overlay)
                                      if o[0].card.card_id == "OP07-003"][0])
    _drain(st)
    assert victim.power == before - 2000, \
        f"相手キャラ1枚に -2000 が乗っていない: {victim.power}"


# --------------------------------------------------------------------------- #
#  OP07-004 カーリー・ダダン (CHARACTER 赤 cost2 power3000):
#    【登場時】自分の手札1枚を捨てることができる：自分のデッキの上から5枚を見て、
#      パワー2000以下のキャラカード1枚までを公開し、手札に加える。
#      その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op07_004_on_play_search_power_le2000_ai():
    """登場時: 手札1捨て → デッキ上5枚からパワー2000以下キャラを手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # 捨てるコスト用
    me.deck = [repo.get(_RED1)] + [repo.get(_FILLER)] * 10  # 上に power2000 キャラ
    src = InPlay.of(repo.get("OP07-004"), sickness=True)

    for prim in _do(overlay, "OP07-004", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert any(c.card_id == _RED1 for c in me.hand), \
        f"デッキ上5枚から power2000以下キャラが手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op07_004_on_play_human_optional_cost_modal():
    """登場時 (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    me.deck = [repo.get(_RED1)] + [repo.get(_FILLER)] * 10
    src = InPlay.of(repo.get("OP07-004"), sickness=True)

    execute_effect(_do(overlay, "OP07-004", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP07-005 カリーナ (CHARACTER 赤 cost3):
#    【ブロッカー】【登場時】相手のキャラ1枚までを、このターン中、パワー-2000。
# --------------------------------------------------------------------------- #
def test_op07_005_on_play_debuff_ai():
    """登場時: 相手キャラ1枚を このターン中 -2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 3000
    opp.characters = [victim]
    before = victim.power
    src = InPlay.of(repo.get("OP07-005"), sickness=True)

    for prim in _do(overlay, "OP07-005", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert victim.power == before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {before})"


def test_op07_005_on_play_human_target_pick():
    """登場時 (人間): 相手キャラ 複数候補 → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]
    src = InPlay.of(repo.get("OP07-005"), sickness=True)

    execute_effect(_do(overlay, "OP07-005", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP07-006 ステリー (CHARACTER 赤 cost1 power1000):
#    【登場時】自分のアクティブのリーダー1枚を、このターン中、パワー-5000する
#      ことができる：カード1枚を引き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op07_006_on_play_leader_debuff_draw_discard_ai():
    """登場時: 自リーダーを -5000 (コスト) → 1ドロー + 手札1捨て (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]          # 捨てる用 (ドロー後に捨てる)
    me.deck = [repo.get(_FILLER)] * 10
    leader_before = me.leader.power
    hand_before = len(me.hand)
    src = InPlay.of(repo.get("OP07-006"), sickness=True)

    for prim in _do(overlay, "OP07-006", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert me.leader.power == leader_before - 5000, \
        f"コストで自リーダーが -5000 されていない: {me.leader.power} (before {leader_before})"
    # 1 ドロー + 1 捨て = 手札 net ±0
    assert len(me.hand) == hand_before, \
        f"ドロー1+捨て1 の net が合わない: {len(me.hand)} (before {hand_before})"


def test_op07_006_on_play_human_optional_cost_modal():
    """登場時 (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    me.deck = [repo.get(_FILLER)] * 10
    src = InPlay.of(repo.get("OP07-006"), sickness=True)

    execute_effect(_do(overlay, "OP07-006", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP07-008 タナカさん (CHARACTER 赤 cost3 power3000):
#    【ブロッカー】【トリガー】自身を登場させる (play_self)。
# --------------------------------------------------------------------------- #
def test_op07_008_trigger_play_self_ai():
    """トリガー: このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP07-008")]
    st.current_source_card_id = "OP07-008"

    for prim in _do(overlay, "OP07-008", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    ids = [c.card.card_id for c in me.characters]
    assert "OP07-008" in ids, "トリガーでこのカードが登場していない"


# --------------------------------------------------------------------------- #
#  OP07-009 ドグラ＆マグラ (CHARACTER 赤 cost2 power3000):
#    【登場時】自分のコスト1の赤のキャラ1枚までは、このターン中、【ダブルアタック】を得る。
# --------------------------------------------------------------------------- #
def test_op07_009_on_play_grant_double_attack_ai():
    """登場時: 自分のコスト1赤キャラ1枚に【ダブルアタック】を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get(_RED1), sickness=False)  # cost1 赤
    me.characters = [target]
    src = InPlay.of(repo.get("OP07-009"), sickness=True)

    for prim in _do(overlay, "OP07-009", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert "ダブルアタック" in target.granted_keywords, \
        f"コスト1赤キャラに ダブルアタック が付与されていない: {target.granted_keywords}"


def test_op07_009_on_play_human_target_pick():
    """登場時 (人間): コスト1赤キャラ 複数候補 → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_RED1), sickness=False)
    b = InPlay.of(repo.get(_RED1), sickness=False)
    me.characters = [a, b]
    src = InPlay.of(repo.get("OP07-009"), sickness=True)

    execute_effect(_do(overlay, "OP07-009", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert "ダブルアタック" in b.granted_keywords, \
        "人間が選んだキャラに ダブルアタック が付与されていない"


# --------------------------------------------------------------------------- #
#  OP07-010 バカラ (CHARACTER 赤 cost3 power4000):
#    【ブロッカー】【相手のアタック時】【ターン1回】自分の手札1枚を捨てることが
#      できる：自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op07_010_opp_attack_pump_self_ai():
    """相手のアタック時: 手札1捨て → 自リーダー/キャラ1枚を +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    bakara = InPlay.of(repo.get("OP07-010"), sickness=False)
    me.characters = [bakara]
    leader_before = me.leader.power
    hand_before = len(me.hand)

    for prim in _do(overlay, "OP07-010", "opp_attack"):
        execute_effect(prim, st, me, opp, bakara)
    _drain(st)

    assert len(me.hand) == hand_before - 1, "コストの手札1枚が捨てられていない"
    # 自リーダー or 自キャラ のいずれかが +2000 されている
    pumped = (me.leader.power == leader_before + 2000) or \
        any(c.power >= (c.card.power or 0) + 2000 for c in me.characters)
    assert pumped, "自リーダーまたはキャラに +2000 が反映されていない"


def test_op07_010_opp_attack_human_optional_cost_modal():
    """相手のアタック時 (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    bakara = InPlay.of(repo.get("OP07-010"), sickness=False)
    me.characters = [bakara]

    execute_effect(_do(overlay, "OP07-010", "opp_attack")[0], st, me, opp, bakara)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP07-011 ブルージャム (CHARACTER 赤 cost4 power5000):
#    【ドン!!×1】【アタック時】相手のパワー2000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op07_011_on_attack_ko_power_le2000_ai():
    """アタック時: (ドン1ゲート) 相手のパワー2000以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bluejam = InPlay.of(repo.get("OP07-011"), sickness=False)
    bluejam.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [bluejam]
    victim = InPlay.of(repo.get(_RED1), sickness=False)  # power 2000 <= 2000
    opp.characters = [victim]

    on_attack = _eff(overlay, "OP07-011", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    assert eval_condition(on_attack.get("if"), st, me, bluejam) is True, \
        "ドン1 でゲート条件が成立していない"
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, bluejam)
    _drain(st)

    assert victim not in opp.characters, "相手のパワー2000以下キャラが KO されていない"


def test_op07_011_on_attack_no_ko_high_power():
    """アタック時: 相手キャラのパワーが2000超なら KO 対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bluejam = InPlay.of(repo.get("OP07-011"), sickness=False)
    bluejam.attached_dons = 1
    me.characters = [bluejam]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 3000 > 2000
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-011", "on_attack"):
        execute_effect(prim, st, me, opp, bluejam)
    _drain(st)

    assert victim in opp.characters, "パワー2000超のキャラが KO されてはいけない (対象外)"


def test_op07_011_on_attack_human_ko_pick():
    """アタック時 (人間): 相手のパワー2000以下キャラ 複数 → target_pick modal → KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    bluejam = InPlay.of(repo.get("OP07-011"), sickness=False)
    bluejam.attached_dons = 1
    me.characters = [bluejam]
    a = InPlay.of(repo.get(_RED1), sickness=False)  # power 2000
    b = InPlay.of(repo.get(_RED1), sickness=False)  # power 2000
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP07-011", "on_attack")[0], st, me, opp, bluejam)
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
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
#  OP07-012 ポルシェーミ (CHARACTER 赤 cost2 power3000):
#    【登場時】相手のキャラ1枚までを、このターン中、パワー-1000。
# --------------------------------------------------------------------------- #
def test_op07_012_on_play_debuff_ai():
    """登場時: 相手キャラ1枚を このターン中 -1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 3000
    opp.characters = [victim]
    before = victim.power
    src = InPlay.of(repo.get("OP07-012"), sickness=True)

    for prim in _do(overlay, "OP07-012", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert victim.power == before - 1000, \
        f"相手キャラ -1000 が反映されていない: {victim.power} (before {before})"


def test_op07_012_on_play_human_target_pick():
    """登場時 (人間): 相手キャラ 複数候補 → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]
    src = InPlay.of(repo.get("OP07-012"), sickness=True)

    execute_effect(_do(overlay, "OP07-012", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before - 1000, "人間が選んだ相手キャラに -1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP07-013 マスクド・デュース (CHARACTER 赤 cost1 power2000):
#    【登場時】自分のリーダーが「ポートガス・D・エース」の場合、自分のデッキの上から
#      5枚を見て、「ポートガス・D・エース」か赤のイベント1枚までを公開し、手札に加える。
#      その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op07_013_on_play_search_when_ace_leader_ai():
    """登場時: リーダーがエースなら デッキ上5枚から赤イベントを手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ACE_LEADER, overlay)  # ポートガス・D・エース leader
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_RED_EVENT)] + [repo.get(_FILLER)] * 10  # 上に赤イベント
    me.hand = []
    cond = _eff(overlay, "OP07-013", "on_play").get("if")
    assert eval_condition(cond, st, me) is True, "エース リーダーで条件が成立していない"
    src = InPlay.of(repo.get("OP07-013"), sickness=True)

    for prim in _do(overlay, "OP07-013", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert any(c.card_id == _RED_EVENT for c in me.hand), \
        f"デッキ上5枚から赤イベントが手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op07_013_on_play_no_search_when_non_ace_leader():
    """登場時 negative: リーダーがエース以外なら条件不成立 → サーチしない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)  # 非エース リーダー
    me, opp = st.players[0], st.players[1]
    cond = _eff(overlay, "OP07-013", "on_play").get("if")
    assert eval_condition(cond, st, me) is False, \
        "非エース リーダーなのに条件が成立している"


def test_op07_013_on_play_human_search_modal():
    """登場時 (人間): デッキ上5枚に候補が複数 → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ACE_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_RED_EVENT), repo.get(_FILLER), repo.get(_RED_EVENT)] \
        + [repo.get(_FILLER)] * 8
    me.hand = []
    src = InPlay.of(repo.get("OP07-013"), sickness=True)

    execute_effect(_do(overlay, "OP07-013", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == _RED_EVENT for c in me.hand), \
        "人間が選んだ赤イベントが手札に加わっていない"
