# -*- coding: utf-8 -*-
"""OP10 弾 赤/緑 効果 回帰テスト バックフィル (自動生成 wave 102):
OP10-018 / OP10-019 / OP10-020 / OP10-021 / OP10-022 /
OP10-023 / OP10-026 / OP10-027 / OP10-028 / OP10-029 の 10 枚
(カマクラ十草紙 = counter +3000/-2000 & trigger +1000 /
 神避 = ドン5レストで8000以下KO & counter リーダー+3000 /
 ゴムゴムのUFO = 相手 -4000 & ライフ2以下で +1000 / trigger 3000以下KO /
 パンクハザード(STAGE) = シーザー・クラウン限定 レストドン付与 /
 トラファルガー・ロー(LEADER) = キャラ手札戻し → ライフ超新星登場 /
 イッショウ = 海軍リーダーで相手コスト5以下2枚レスト /
 錦えもん(026/027) = 自身+トラッシュ錦えもんをデッキ下 → コスト6錦えもん登場 /
 光月モモの助 = ドン2レスト+トラッシュ → デッキ上5枚から赤鞘九人男2枚サーチ /
 ミホーク = レストキャラ2枚以上で ODYSSEY コスト5以下1枚アクティブ)。

目的 (= test_backfill_auto_001〜101.py と同一方針):
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
    eval_all_conditions,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード / リーダー (テキストの前提固定)
_LEADER_GREEN = "OP01-001"     # ロロノア・ゾロ (leader、 汎用)
_LEADER_NAVY = "OP10-001"      # スモーカー (leader、 パンクハザード/海軍)
_LEADER_CAESAR = "OP10-002"    # シーザー・クラウン (leader、 科学者/パンクハザード)
_LEADER_LAW = "OP10-022"       # トラファルガー・ロー (leader、 ドレスローザ/超新星/ハートの海賊団)
_FILLER = "ST01-004"           # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_SMALL = "OP01-016"            # ナミ cost1 power2000 (バニラ)


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
def test_all_wave102_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP10-018", "OP10-019", "OP10-020", "OP10-021", "OP10-022",
           "OP10-023", "OP10-026", "OP10-027", "OP10-028", "OP10-029"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP10-018 カマクラ十草紙 (EVENT): 【カウンター】自リーダーorキャラ +3000(battle)、
#          その後 相手リーダーorキャラ -2000(turn)。 【トリガー】自リーダーorキャラ +1000。
# --------------------------------------------------------------------------- #
def test_op10_018_counter_pump_and_debuff_ai():
    """【カウンター】自リーダー +3000 → 相手リーダー -2000 (AI、 相手キャラ不在で顔対象)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]

    my_before = me.leader.power
    opp_before = opp.leader.power
    for prim in _eff(overlay, "OP10-018", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert me.leader.power == my_before + 3000, \
        f"自リーダー +3000 が反映されていない: {me.leader.power} (before {my_before})"
    assert opp.leader.power == opp_before - 2000, \
        f"相手リーダー -2000 が反映されていない: {opp.leader.power} (before {opp_before})"


def test_op10_018_trigger_pump_ai():
    """【トリガー】自リーダー +1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]

    my_before = me.leader.power
    for prim in _eff(overlay, "OP10-018", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert me.leader.power == my_before + 1000, \
        f"トリガー 自リーダー +1000 が反映されていない: {me.leader.power}"


def test_op10_018_counter_debuff_human_pick():
    """人間 + 相手リーダー/キャラ 複数 → -2000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    opp.characters = [victim]

    # counter do[1] = 相手への -2000 (do[0] は自分 +3000)。 相手対象で modal が立つ。
    debuff_prim = _eff(overlay, "OP10-018", "counter")["do"][1]
    execute_effect(debuff_prim, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (相手リーダー+キャラ) が 2 件でない: {len(cands)}"
    vi = next(i for i, c in enumerate(cands) if c["iid"] == victim.instance_id)
    v_before = victim.power
    resolve_pending_choice(st, [vi])
    _drain(st, [vi])
    assert victim.power == v_before - 2000, \
        "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP10-019 神避 (EVENT): 【メイン】(ドン5レスト) 相手のパワー8000以下キャラ1枚KO。
#          【カウンター】自リーダー +3000(battle)。
# --------------------------------------------------------------------------- #
def test_op10_019_main_ko_power_le_8000_ai():
    """【メイン】相手のパワー8000以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000 (<=8000)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-019", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert victim not in opp.characters, "パワー8000以下の相手キャラが KO されていない"


def test_op10_019_main_ko_human_pick():
    """人間 + 相手8000以下キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    b = InPlay.of(repo.get(_SMALL), sickness=False)    # power 2000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP10-019", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_op10_019_counter_pump_leader_ai():
    """【カウンター】自リーダー +3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]

    before = me.leader.power
    for prim in _eff(overlay, "OP10-019", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert me.leader.power == before + 3000, \
        f"カウンター 自リーダー +3000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP10-020 ゴムゴムのUFO (EVENT): 【メイン】相手キャラ1枚 -4000(turn)。その後、
#          自分のライフ2以下なら 自リーダーorキャラ +1000(turn)。 【トリガー】相手3000以下KO。
# --------------------------------------------------------------------------- #
def test_op10_020_main_debuff_and_conditional_pump_ai():
    """【メイン】相手キャラ -4000 → ライフ2以下で 自リーダー +1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # ライフ 2 (= 条件成立)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    opp.characters = [victim]

    v_before = victim.power
    l_before = me.leader.power
    for prim in _eff(overlay, "OP10-020", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert victim.power == v_before - 4000, \
        f"相手キャラ -4000 が反映されていない: {victim.power} (before {v_before})"
    assert me.leader.power == l_before + 1000, \
        f"ライフ2以下で 自リーダー +1000 が乗っていない: {me.leader.power}"


def test_op10_020_main_conditional_skipped_when_life_high():
    """自分のライフ3枚なら その後の +1000 は乗らない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3  # ライフ 3 (= 条件不成立)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    l_before = me.leader.power
    for prim in _eff(overlay, "OP10-020", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert me.leader.power == l_before, \
        f"ライフ3枚で +1000 が乗ってはいけない: {me.leader.power}"


def test_op10_020_trigger_ko_power_le_3000_ai():
    """【トリガー】相手のパワー3000以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SMALL), sickness=False)  # power 2000 (<=3000)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-020", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert victim not in opp.characters, "パワー3000以下の相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP10-021 パンクハザード (STAGE): 【起動メイン】このステージをレストにできる：
#          自分のリーダーが「シーザー・クラウン」の場合、自リーダーorキャラ1枚に
#          レストのドン‼1枚までを付与。
# --------------------------------------------------------------------------- #
def test_op10_021_activate_main_attach_don_caesar_ai():
    """起動メイン: (シーザー・クラウン leader) 自リーダーにレストドン1付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CAESAR, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP10-021"), sickness=False)
    me.stages = [stage]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-021"]
    assert len(opts) == 1, \
        f"OP10-021 (ステージ) の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert me.leader.attached_dons == don_before + 1, \
        f"自リーダーへレストドンが付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"
    assert stage.rested is True, "起動メインコストでステージがレストされるべき"


def test_op10_021_activate_main_no_attach_non_caesar():
    """条件 leader_name「シーザー・クラウン」: 別リーダーでは 付与が起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)  # シーザー・クラウン でない
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP10-021"), sickness=False)
    me.stages = [stage]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-021"]
    if opts:
        fire_activate_main(st, me, opp, *opts[0])
        _drain(st, [0])
    assert me.leader.attached_dons == don_before, \
        "シーザー・クラウン でない leader でレストドンが付与されてはいけない"


# --------------------------------------------------------------------------- #
#  OP10-022 トラファルガー・ロー (LEADER): 【ドン‼×1】【起動メイン】【ターン1回】
#          自分のキャラのコスト合計5以上の場合、自キャラ1枚を手札に戻し、ライフ上1枚を公開し
#          コスト5以下の特徴《超新星》キャラなら登場させてもよい。
# --------------------------------------------------------------------------- #
def test_op10_022_activate_main_return_and_reveal_play_ai():
    """起動メイン: 自キャラ1枚を手札へ → ライフ上の 超新星 cost5以下を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LAW, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1  # 【ドン‼×1】ゲート
    # 自キャラ コスト合計 = 3 + 2 = 5 (>=5 で条件成立)
    boney = InPlay.of(repo.get("PRB02-004"), sickness=False)  # cost3 超新星
    filler = InPlay.of(repo.get(_FILLER), sickness=False)      # cost2
    me.characters = [boney, filler]
    # ライフ上 = 超新星 cost1 (= EB01-015 アプー)、 以降 filler
    me.life = [repo.get("EB01-015")] + [repo.get(_FILLER)] * 2

    hand_before = len(me.hand)
    life_before = len(me.life)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-022"]
    assert len(opts) == 1, \
        f"OP10-022 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert len(me.hand) == hand_before + 1, \
        f"自キャラ1枚が手札に戻っていない: hand={len(me.hand)}"
    assert len(me.life) == life_before - 1, \
        f"ライフ上の 超新星 が登場に使われてライフが1枚減るべき: life={len(me.life)}"
    assert any(c.card.card_id == "EB01-015" for c in me.characters), \
        "ライフから 超新星 cost5以下キャラが登場していない"


def test_op10_022_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_LAW, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1
    me.characters = [InPlay.of(repo.get("PRB02-004"), sickness=False),
                     InPlay.of(repo.get(_FILLER), sickness=False)]
    me.life = [repo.get("EB01-015")] + [repo.get(_FILLER)] * 2

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP10-022"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP10-022"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP10-023 イッショウ (CHARACTER): 【登場時】自分のリーダーが特徴《海軍》を持つ場合、
#          相手のコスト5以下のキャラ2枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op10_023_on_play_rest_two_opp_ai():
    """【登場時】(海軍 leader) 相手のコスト5以下キャラ2枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay)  # スモーカー (海軍)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_SMALL), sickness=False)    # cost1
    opp.characters = [a, b]

    for prim in _eff(overlay, "OP10-023", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-023"), sickness=True))
    _drain(st, [0])
    assert a.rested and b.rested, \
        f"相手コスト5以下キャラ2枚がレストされていない: a={a.rested} b={b.rested}"


def test_op10_023_on_play_condition_leader_navy():
    """条件 leader_feature《海軍》: 海軍 leader で成立 / それ以外で不成立。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP10-023", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "海軍", \
        "overlay の リーダー条件 (海軍) が無い"

    st_navy = _state(repo, _LEADER_NAVY, overlay)
    assert eval_all_conditions(eff, st_navy, st_navy.players[0], None) is True, \
        "海軍 leader で 条件が成立するべき"
    st_other = _state(repo, _LEADER_GREEN, overlay)
    assert eval_all_conditions(eff, st_other, st_other.players[0], None) is False, \
        "海軍 でない leader で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP10-026 錦えもん (CHARACTER, power1000): 【起動メイン】このキャラと自分のトラッシュから
#          パワー0の「錦えもん」1枚をデッキ下 → 自分の手札からコスト6の「錦えもん」1枚を登場。
# --------------------------------------------------------------------------- #
def test_op10_026_activate_main_recur_costcost6_nishiki_ai():
    """起動メイン: 自身+トラッシュのパワー0錦えもんをデッキ下 → 手札からコスト6錦えもん登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    nishi = InPlay.of(repo.get("OP10-026"), sickness=False)  # power1000 錦えもん
    me.characters = [nishi]
    me.trash = [repo.get("OP10-027")]      # トラッシュに パワー0 錦えもん
    me.hand = [repo.get("OP01-040")]       # 手札に コスト6 錦えもん
    me.deck = [repo.get(_FILLER)] * 20

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-026"]
    assert len(opts) == 1, \
        f"OP10-026 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert nishi not in me.characters, "コストで自身がデッキ下に置かれるべき"
    assert any(c.card.card_id == "OP01-040" for c in me.characters), \
        "手札からコスト6錦えもんが登場していない"
    assert repo.get("OP10-027") not in me.trash and \
        not any(c.card_id == "OP10-027" for c in me.trash), \
        "トラッシュのパワー0錦えもんがデッキに戻っていない"


# --------------------------------------------------------------------------- #
#  OP10-027 錦えもん (CHARACTER, power0): 【起動メイン】このキャラと自分のトラッシュから
#          パワー1000の「錦えもん」1枚をデッキ下 → 手札からコスト6の「錦えもん」1枚を登場。
# --------------------------------------------------------------------------- #
def test_op10_027_activate_main_recur_costcost6_nishiki_ai():
    """起動メイン: 自身+トラッシュのパワー1000錦えもんをデッキ下 → 手札からコスト6錦えもん登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    nishi = InPlay.of(repo.get("OP10-027"), sickness=False)  # power0 錦えもん
    me.characters = [nishi]
    me.trash = [repo.get("OP10-026")]      # トラッシュに パワー1000 錦えもん
    me.hand = [repo.get("OP01-040")]       # 手札に コスト6 錦えもん
    me.deck = [repo.get(_FILLER)] * 20

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-027"]
    assert len(opts) == 1, \
        f"OP10-027 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert nishi not in me.characters, "コストで自身がデッキ下に置かれるべき"
    assert any(c.card.card_id == "OP01-040" for c in me.characters), \
        "手札からコスト6錦えもんが登場していない"
    assert not any(c.card_id == "OP10-026" for c in me.trash), \
        "トラッシュのパワー1000錦えもんがデッキに戻っていない"


# --------------------------------------------------------------------------- #
#  OP10-028 光月モモの助 (CHARACTER): 【起動メイン】自分のドン‼2枚をレストにし、このキャラを
#          トラッシュに置く：デッキ上5枚を見て、特徴《赤鞘九人男》2枚までを公開し手札に加え、
#          残りをデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op10_028_activate_main_search_akazaya_ai():
    """起動メイン: ドン2レスト+自身トラッシュ → デッキ上5枚から赤鞘九人男2枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    momo = InPlay.of(repo.get("OP10-028"), sickness=False)
    me.characters = [momo]
    me.don_active = 2  # rest_self_don コストは アクティブドンを rest する (= don_active から支払う)
    me.hand = []
    # デッキ上 2 枚を 赤鞘九人男 に (= OP14-023 菊之丞 / OP12-025 錦えもん)
    me.deck = [repo.get("OP14-023"), repo.get("OP12-025")] + [repo.get(_FILLER)] * 15

    active_before = me.don_active
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-028"]
    assert len(opts) == 1, \
        f"OP10-028 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert momo not in me.characters, "起動メインコストで モモの助 がトラッシュに置かれるべき"
    assert me.don_active == active_before - 2, "アクティブドンが2枚レストされるべき"
    akazaya = [c for c in me.hand
               if "赤鞘九人男" in (c.features or "")]
    assert len(akazaya) == 2, \
        f"デッキ上5枚から 赤鞘九人男 2枚が手札に加わっていない: {[c.card_id for c in me.hand]}"


# --------------------------------------------------------------------------- #
#  OP10-029 ジュラキュール・ミホーク (CHARACTER): 【登場時】自分のレストのキャラが2枚以上いる
#          場合、自分のレストのコスト5以下の特徴《ODYSSEY》を持つキャラ1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op10_029_on_play_untap_odyssey_ai():
    """【登場時】(レストキャラ2枚以上) レストの ODYSSEY cost5以下1枚をアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    mihawk = InPlay.of(repo.get("OP10-029"), sickness=True)
    nami = InPlay.of(repo.get("OP10-033"), sickness=False)   # ODYSSEY cost2
    filler = InPlay.of(repo.get(_FILLER), sickness=False)
    nami.rested = True
    filler.rested = True
    me.characters = [mihawk, nami, filler]

    for prim in _eff(overlay, "OP10-029", "on_play")["do"]:
        execute_effect(prim, st, me, opp, mihawk)
    _drain(st, [0])
    assert nami.rested is False, \
        "レストの ODYSSEY cost5以下キャラがアクティブになっていない"


def test_op10_029_on_play_condition_rested_count():
    """条件 self_rested_chara_count_ge=2: レストキャラ1枚では不成立、 2枚で成立。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP10-029", "on_play")
    assert eff.get("if", {}).get("self_rested_chara_count_ge") == 2, \
        "overlay の 条件 self_rested_chara_count_ge=2 が無い"

    st = _state(repo, _LEADER_GREEN, overlay)
    me = st.players[0]
    mihawk = InPlay.of(repo.get("OP10-029"), sickness=True)
    nami = InPlay.of(repo.get("OP10-033"), sickness=False)
    nami.rested = True
    # レストキャラ 1 枚 (nami のみ) → 不成立
    me.characters = [mihawk, nami]
    assert eval_all_conditions(eff, st, me, mihawk) is False, \
        "レストキャラ1枚で 条件が成立してはいけない"
    # レストキャラ 2 枚 → 成立
    filler = InPlay.of(repo.get(_FILLER), sickness=False)
    filler.rested = True
    me.characters = [mihawk, nami, filler]
    assert eval_all_conditions(eff, st, me, mihawk) is True, \
        "レストキャラ2枚で 条件が成立するべき"
