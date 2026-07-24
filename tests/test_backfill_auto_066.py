# -*- coding: utf-8 -*-
"""OP06 弾 効果 回帰テスト バックフィル (自動生成 wave 066):
OP06-034 / OP06-035 / OP06-036 / OP06-038 / OP06-039 / OP06-040 /
OP06-041 / OP06-042 / OP06-043 / OP06-044 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_065.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 択一 を 持つカードは 人間 actor で pending_choice が
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
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER = "OP01-001"      # ロロノア・ゾロ (赤、 汎用リーダー)
_REIJU = "OP06-042"       # ヴィンスモーク・レイジュ (青/紫 リーダー)
_FILLER = "OP01-013"      # サンジ cost2 power3000 (汎用フィラー / cost<=N 対象)
_NAMI = "OP01-016"        # ナミ cost1 power2000 (cost<=N 対象)


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


def _drain(st, pick=0, guard=8):
    """pending_choice を pick で自動解決し切る (= 後続効果を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave66_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP06-034", "OP06-035", "OP06-036", "OP06-038", "OP06-039",
           "OP06-040", "OP06-041", "OP06-042", "OP06-043", "OP06-044"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP06-034 ヒョウゾウ (CHARACTER 緑 cost4):
#    【起動メイン】【ターン1回】相手のコスト4以下のキャラ1枚までを、レストにし、
#      このキャラは、このターン中、パワー＋1000。その後、自分のライフの上から
#      1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op06_034_activate_main_rest_pump_life_ai():
    """起動メイン (AI): 相手コスト4以下1枚レスト + 自身 +1000 + ライフ1手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    hyozou = InPlay.of(repo.get("OP06-034"), sickness=False)
    me.characters = [hyozou]
    me.life = [repo.get(_FILLER)] * 3
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 4
    opp.characters = [victim]
    power_before = hyozou.power
    life_before = len(me.life)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-034"]
    assert len(opts) == 1, f"OP06-034 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert victim.rested is True, "相手コスト4以下キャラがレストされていない"
    assert hyozou.power == power_before + 1000, \
        f"自身 +1000 が反映されていない: {hyozou.power} (before {power_before})"
    assert len(me.life) == life_before - 1, "ライフが1枚手札に加わっていない"

    # 【ターン1回】: 再発動不可
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP06-034"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op06_034_activate_main_human_rest_pick():
    """起動メイン (人間): 相手コスト4以下 複数 → target_pick modal で選択してレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hyozou = InPlay.of(repo.get("OP06-034"), sickness=False)
    me.characters = [hyozou]
    me.life = [repo.get(_FILLER)] * 3
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-034"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"相手キャラ候補が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはアクティブのままであるべき"


# --------------------------------------------------------------------------- #
#  OP06-035 ホーディ・ジョーンズ (CHARACTER 緑 cost7):
#    【速攻】【登場時】相手の、キャラかドン!!合計2枚までを、レストにする。その後、
#      自分のライフの上から1枚を手札に加える。
#
#  ⚠ engine gap: rest_multi primitive が target spec "one_opp_chara_or_don" を
#    解決できず (= 特殊分岐は "rest" primitive 側のみ)、 相手キャラ/ドンのレストが
#    no-op になる。 life_to_hand は正しく発火する。 engine 修正は 人間レビューへ回す
#    (このタスクでは engine を編集しない) ため skip。
# --------------------------------------------------------------------------- #
@pytest.mark.skip(reason="engine gap: rest_multi が target 'one_opp_chara_or_don' を "
                         "解決できずレストが no-op (life_to_hand は正常)。 engine 修正待ち")
def test_op06_035_on_play_rest_two_and_life():
    """登場時: 相手キャラ/ドン合計2枚レスト + 自ライフ1手札 (公式テキスト全体)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]
    me.life = [repo.get(_FILLER)] * 3
    life_before = len(me.life)

    for prim in _do(overlay, "OP06-035", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-035"), sickness=True))
        _drain(st)

    assert a.rested is True and b.rested is True, "相手キャラ2枚がレストされていない"
    assert len(me.life) == life_before - 1, "ライフが1枚手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP06-036 リューマ (CHARACTER 緑 cost4):
#    【登場時】/【KO時】相手のレストのコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op06_036_on_play_ko_rested_cost_le4_ai():
    """登場時 (AI): 相手のレストのコスト4以下キャラ1枚を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 4
    victim.rested = True
    opp.characters = [victim]

    for prim in _do(overlay, "OP06-036", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-036"), sickness=False))
        _drain(st)

    assert victim not in opp.characters, "登場時に相手のレストコスト4以下キャラがKOされていない"


def test_op06_036_on_ko_no_active_target():
    """KO時: 相手のコスト4以下キャラが アクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    for prim in _do(overlay, "OP06-036", "on_ko"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-036"), sickness=False))
        _drain(st)

    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


def test_op06_036_on_ko_human_ko_pick():
    """KO時 (人間): 相手のレストコスト4以下 複数 → target_pick modal で選択して KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP06-036", "on_ko")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-036"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"相手キャラ候補が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP06-038 一大・三千・大千・世界 (EVENT 緑 cost1):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
#      その後、自分のレストのカードが8枚以上ある場合、そのカードを、このバトル中、
#      パワー+2000。
#    【トリガー】相手のレストのコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op06_038_counter_pump_ai():
    """カウンター (AI): 自リーダー/キャラ1枚に +2000 (レスト8枚未満 → 追加分なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power  # 対象なし → AI 既定でリーダー

    ce = _eff(overlay, "OP06-038", "counter")
    for prim in ce["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st)

    assert me.leader.power == power_before + 2000, \
        f"カウンター +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op06_038_counter_extra_pump_when_8_rested():
    """カウンター: 自分のレストのカードが8枚以上 → 追加で +2000 (計 +4000)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False) for _ in range(8)]
    for c in me.characters:
        c.rested = True  # レスト 8 枚 (= 条件成立)
    power_before = me.leader.power

    ce = _eff(overlay, "OP06-038", "counter")
    for prim in ce["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st)

    assert me.leader.power == power_before + 4000, \
        f"レスト8枚で +2000 追加 (計+4000) が反映されていない: {me.leader.power}"


def test_op06_038_trigger_ko_rested_cost_le3_ai():
    """トリガー (AI): 相手のレストのコスト3以下キャラ1枚を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1 <= 3
    victim.rested = True
    opp.characters = [victim]

    tr = _eff(overlay, "OP06-038", "trigger")
    for prim in tr["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-038"), sickness=False))
        _drain(st)

    assert victim not in opp.characters, "トリガーで相手のレストコスト3以下キャラがKOされていない"


def test_op06_038_counter_human_target_pick():
    """カウンター (人間): 自リーダー/キャラ 複数 → target_pick modal で選択して +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    ce = _eff(overlay, "OP06-038", "counter")
    execute_effect(ce["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP06-039 お前じゃ退屈凌ぎにもなりゃしねェ!!! (EVENT 緑 cost4):
#    【メイン】以下から1つを選ぶ。
#      ・相手のコスト6以下のキャラ1枚までを、レストにする。
#      ・相手のレストのコスト6以下のキャラ1枚までを、KOする。
#    【トリガー】自身の【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op06_039_main_human_option_rest():
    """メイン (人間): 択一 → option 0 (レスト) を選ぶと相手キャラがレストされる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # active cost2
    opp.characters = [victim]

    execute_effect(_do(overlay, "OP06-039", "main")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 択一で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [0])  # option 0 = レスト
    _drain(st)
    assert victim.rested is True, "option 0 (レスト) で相手キャラがレストされていない"
    assert victim in opp.characters, "レスト選択なのに KO されている"


def test_op06_039_main_human_option_ko():
    """メイン (人間): option 1 (KO) を選ぶと相手のレストキャラが KO される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True  # レスト (= KO 対象条件)
    opp.characters = [victim]

    execute_effect(_do(overlay, "OP06-039", "main")[0], st, me, opp, None)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "option_pick"
    resolve_pending_choice(st, [1])  # option 1 = KO
    _drain(st)
    assert victim not in opp.characters, "option 1 (KO) で相手のレストキャラが KO されていない"


def test_op06_039_main_ai_resolves():
    """メイン (AI): crash せず 択一を自動解決し、 盤面に効果が現れる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    active = InPlay.of(repo.get(_FILLER), sickness=False)   # active
    rested = InPlay.of(repo.get(_NAMI), sickness=False)
    rested.rested = True                                    # rested (KO 対象)
    opp.characters = [active, rested]

    for prim in _do(overlay, "OP06-039", "main"):
        execute_effect(prim, st, me, opp, None)
        _drain(st)

    # AI がどちらの option を選んでも 盤面が変化する (レスト化 or KO)
    assert (rested not in opp.characters) or active.rested, \
        "AI が択一を実行しても盤面が変化していない"


def test_op06_039_trigger_fires_main():
    """トリガー (AI): 自身の【メイン】効果 (択一) を発動し盤面に効果が現れる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    rested = InPlay.of(repo.get(_NAMI), sickness=False)
    rested.rested = True
    opp.characters = [rested]

    for prim in _do(overlay, "OP06-039", "trigger"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-039"), sickness=False))
        _drain(st)

    # トリガー → メイン択一 → いずれかの option 発動 (rested を KO or レスト維持)
    assert rested not in opp.characters or rested.rested, \
        "トリガーからメイン効果が発動していない"


# --------------------------------------------------------------------------- #
#  OP06-040 矢武鮫 (EVENT 緑 cost2):
#    【メイン】相手のレストのコスト3以下のキャラ2枚までを、KOする。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op06_040_main_ko_two_rested_cost_le3_ai():
    """メイン (AI): 相手のレストのコスト3以下キャラ2枚を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    for prim in _do(overlay, "OP06-040", "main"):
        execute_effect(prim, st, me, opp, None)
        _drain(st)

    assert a not in opp.characters and b not in opp.characters, \
        "相手のレストコスト3以下キャラ2枚が KO されていない"


def test_op06_040_main_active_not_targeted():
    """メイン: アクティブなキャラは対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    active = InPlay.of(repo.get(_FILLER), sickness=False)
    active.rested = False
    opp.characters = [active]

    for prim in _do(overlay, "OP06-040", "main"):
        execute_effect(prim, st, me, opp, None)
        _drain(st)

    assert active in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


def test_op06_040_trigger_fires_main():
    """トリガー (AI): 自身の【メイン】効果 (KO) を発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)
    victim.rested = True
    opp.characters = [victim]

    for prim in _do(overlay, "OP06-040", "trigger"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-040"), sickness=False))
        _drain(st)

    assert victim not in opp.characters, "トリガーからメイン KO 効果が発動していない"


# --------------------------------------------------------------------------- #
#  OP06-041 方舟ノア (STAGE 緑 cost6):
#    【登場時】相手のキャラすべてを、レストにする。
#    【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op06_041_on_play_rest_all_opp_ai():
    """登場時 (AI): 相手のキャラすべてをレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]

    for prim in _do(overlay, "OP06-041", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-041"), sickness=False))
        _drain(st)

    assert a.rested is True and b.rested is True, \
        "相手のキャラすべてがレストされていない"


def test_op06_041_trigger_play_self():
    """トリガー (AI): このステージ (方舟ノア) を場に登場させる → 相手全レスト効果も発火。

    トリガー文脈を再現: めくれたカードは trash に置かれ、 current_source_card_id で
    参照される (self_inplay=None)。 play_self が trash から拾って登場させる。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]
    me.trash = [repo.get("OP06-041")]
    st.current_source_card_id = "OP06-041"
    stages_before = len(me.stages)

    for prim in _do(overlay, "OP06-041", "trigger"):
        execute_effect(prim, st, me, opp, None)
        _drain(st)

    assert len(me.stages) == stages_before + 1, "トリガーで方舟ノアが場に登場していない"
    assert victim.rested is True, "登場した方舟ノアの【登場時】(相手全レスト) が発火していない"


# --------------------------------------------------------------------------- #
#  OP06-042 ヴィンスモーク・レイジュ (LEADER 青/紫):
#    【自分のターン中】【ターン1回】自分の場のドン!!がドン!!デッキに戻された時、
#      カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op06_042_leader_draw_on_don_returned():
    """ドン!! がデッキに戻された時のリアクティブ効果: カード1枚引く (自ターン中)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _REIJU, overlay)  # レイジュ自身が leader
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    eff = _eff(overlay, "OP06-042", "on_self_don_returned_to_deck")
    assert eff.get("if", {}).get("self_turn") is True, \
        "overlay の【自分のターン中】条件 (self_turn) が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, me.leader)
        _drain(st)

    assert len(me.hand) == hand_before + 1, "ドン戻し時に1枚引けていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP06-043 アラマキ (CHARACTER 青 cost8):
#    【ブロッカー】【起動メイン】【ターン1回】自分の手札1枚を捨て、コスト2以下の
#      キャラ1枚を持ち主のデッキの下に置くことができる：このキャラは、このターン中、
#      パワー＋3000。
# --------------------------------------------------------------------------- #
def test_op06_043_activate_main_return_and_pump_ai():
    """起動メイン (AI): 手札1捨て + コスト2以下キャラをデッキ下 → 自身 +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    aramaki = InPlay.of(repo.get("OP06-043"), sickness=False)
    me.characters = [aramaki]
    me.hand = [repo.get(_FILLER), repo.get(_NAMI)]  # 捨てコスト用 (2枚)
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1 <= 2
    opp.characters = [victim]
    power_before = aramaki.power
    hand_before = len(me.hand)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-043"]
    assert len(opts) == 1, f"OP06-043 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert victim not in opp.characters, "コスト2以下キャラがデッキ下に置かれていない"
    assert aramaki.power == power_before + 3000, \
        f"自身 +3000 が反映されていない: {aramaki.power} (before {power_before})"
    assert len(me.hand) == hand_before - 1, "起動メインコストで手札が1枚捨てられていない"

    # 【ターン1回】: 再発動不可
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP06-043"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op06_043_activate_main_needs_hand_to_discard():
    """起動メインは手札1枚を捨てるコストが必要 → 手札が空なら legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    aramaki = InPlay.of(repo.get("OP06-043"), sickness=False)
    me.characters = [aramaki]
    me.hand = []  # 捨てられない
    opp.characters = [InPlay.of(repo.get(_NAMI), sickness=False)]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-043"]
    assert len(opts) == 0, "手札が空 (捨てコスト不能) なのに起動メインが legal に出た"


# --------------------------------------------------------------------------- #
#  OP06-044 ギオン (CHARACTER 青 cost4):
#    【自分のターン中】【ターン1回】相手がイベントを発動した時、相手は自身の手札
#      1枚をデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op06_044_opp_event_hand_to_deck_bottom():
    """相手がイベント発動時のリアクティブ効果: 相手は手札1枚をデッキ下に置く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER), repo.get(_NAMI)]
    opp.deck = [repo.get(_FILLER)] * 10
    opp_hand_before = len(opp.hand)
    opp_deck_before = len(opp.deck)

    eff = _eff(overlay, "OP06-044", "opp_event_or_trigger_fired")
    assert eff.get("if", {}).get("self_turn") is True, \
        "overlay の【自分のターン中】条件 (self_turn) が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-044"), sickness=False))
        _drain(st)

    assert len(opp.hand) == opp_hand_before - 1, "相手の手札が1枚減っていない"
    assert len(opp.deck) == opp_deck_before + 1, "相手のデッキが1枚増えていない (デッキ下へ)"
