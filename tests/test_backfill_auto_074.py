# -*- coding: utf-8 -*-
"""OP07 弾 効果 回帰テスト バックフィル (自動生成 wave 074):
OP07-014 / OP07-015 / OP07-016 / OP07-017 / OP07-018 / OP07-019 /
OP07-020 / OP07-022 / OP07-023 / OP07-025 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_073.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"       # ロロノア・ゾロ (赤、 汎用リーダー・特徴なし前提)
_FILLER = "OP01-013"       # サンジ cost2 power3000 (汎用フィラー、 登場時なし)
_RED1 = "EB04-002"         # ジュエリー・ボニー cost1 power2000 赤 (コスト1赤キャラ用ヘルパー)
_ACE_LEADER = "OP03-001"   # ポートガス・D・エース (リーダー名条件用)
_KAKUMEI = "EB02-002"      # サボ 赤 革命軍 cost4 power5000 (革命軍キャラ用ヘルパー)
_KAKUMEI2 = "OP16-024"     # イナズマ 緑 革命軍 cost2 power1000 (革命軍キャラ 2 枚目)
_GYOJIN_LEADER = "OP11-021"  # ジンベエ 緑 魚人族/麦わらの一味 (魚人族リーダー)
_GYOJIN_CHAR = "OP16-023"    # アーロン 緑 cost1 power3000 魚人族 (魚人族キャラ cost≤3)
_WANO_GREEN = "EB03-016"     # 光月日和 緑 cost1 ワノ国 (お玉以外の緑ワノ国)
_CARIBOU = "OP07-023"        # カリブー 緑 cost4 (OP07-025 の登場対象)


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
def test_all_wave74_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP07-014", "OP07-015", "OP07-016", "OP07-017", "OP07-018",
           "OP07-019", "OP07-020", "OP07-022", "OP07-023", "OP07-025"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP07-014 モーダ (CHARACTER 赤 cost1):
#    【自分のターン中】【登場時】自分の「ポートガス・D・エース」1枚までを、
#      このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op07_014_on_play_pump_ace_leader_ai():
    """登場時 (自ターン): 名前「ポートガス・D・エース」のリーダーを +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ACE_LEADER, overlay)  # リーダー = ポートガス・D・エース
    me, opp = st.players[0], st.players[1]
    conds = _eff(overlay, "OP07-014", "on_play").get("conditions")
    assert eval_condition(conds[0], st, me) is True, "自ターン条件 (self_turn) が成立していない"
    leader_before = me.leader.power
    src = InPlay.of(repo.get("OP07-014"), sickness=True)

    for prim in _do(overlay, "OP07-014", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert me.leader.power == leader_before + 2000, \
        f"エース リーダーに +2000 が反映されていない: {me.leader.power} (before {leader_before})"


def test_op07_014_on_play_no_ace_no_pump():
    """登場時 negative: 「ポートガス・D・エース」 が居なければ対象なし → 何も変わらない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)  # 非エース リーダー
    me, opp = st.players[0], st.players[1]
    leader_before = me.leader.power
    src = InPlay.of(repo.get("OP07-014"), sickness=True)

    for prim in _do(overlay, "OP07-014", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert me.leader.power == leader_before, \
        "エース不在なのにパワーが変化している (対象外のはず)"


# --------------------------------------------------------------------------- #
#  OP07-015 モンキー・D・ドラゴン (CHARACTER 赤 cost8):
#    【速攻】【登場時】自分のリーダーかキャラ1枚にレストのドン!!2枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op07_015_on_play_attach_rested_don_ai():
    """登場時: 自リーダー (既定) にレストドン2枚を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3  # レストドン供給源
    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    src = InPlay.of(repo.get("OP07-015"), sickness=True)

    for prim in _do(overlay, "OP07-015", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert me.leader.attached_dons == don_before + 2, \
        f"自リーダーにレストドン2枚が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"


def test_op07_015_on_play_human_target_pick():
    """登場時 (人間): 自リーダー + キャラ 複数候補 → target_pick modal → キャラに付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]
    src = InPlay.of(repo.get("OP07-015"), sickness=True)

    execute_effect(_do(overlay, "OP07-015", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    _drain(st)
    assert friend.attached_dons == 2, "人間が選んだキャラにレストドン2枚が付与されていない"


# --------------------------------------------------------------------------- #
#  OP07-016 銀河・WINK (EVENT 赤 cost1):
#    【メイン】自分の特徴《革命軍》を持つキャラ1枚までを、このターン中、パワー+2000。
#      その後、相手のキャラ1枚までを、このターン中、パワー-1000。
# --------------------------------------------------------------------------- #
def test_op07_016_main_pump_and_debuff_ai():
    """メイン: 自革命軍キャラ +2000 → その後 相手キャラ -1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get(_KAKUMEI), sickness=False)  # 革命軍 power5000
    me.characters = [sabo]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000
    opp.characters = [victim]
    sabo_before, victim_before = sabo.power, victim.power

    for prim in _do(overlay, "OP07-016", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert sabo.power == sabo_before + 2000, \
        f"自革命軍キャラに +2000 が乗っていない: {sabo.power} (before {sabo_before})"
    assert victim.power == victim_before - 1000, \
        f"相手キャラに -1000 が乗っていない: {victim.power} (before {victim_before})"


def test_op07_016_main_human_target_pick():
    """メイン (人間): 革命軍キャラ 複数候補 → +2000 の target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_KAKUMEI), sickness=False)
    b = InPlay.of(repo.get(_KAKUMEI2), sickness=False)
    me.characters = [a, b]

    execute_effect(_do(overlay, "OP07-016", "main")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before + 2000, "人間が選んだ革命軍キャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP07-017 竜の息吹 (EVENT 赤 cost2):
#    【メイン】相手の、パワー3000以下のキャラ1枚までとコスト1以下のステージ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op07_017_main_ko_chara_and_stage_ai():
    """メイン: 相手のパワー3000以下キャラ + コスト1以下ステージを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000 <= 3000
    opp.characters = [victim]
    stage = InPlay.of(repo.get("EB01-011"), sickness=False)  # STAGE cost1
    opp.stages = [stage]

    for prim in _do(overlay, "OP07-017", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, "相手のパワー3000以下キャラが KO されていない"
    assert stage not in opp.stages, "相手のコスト1以下ステージが KO されていない"


def test_op07_017_main_no_ko_high_power_chara():
    """メイン negative: 相手キャラのパワーが3000超なら KO 対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_KAKUMEI), sickness=False)  # power5000 > 3000
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-017", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim in opp.characters, "パワー3000超のキャラが KO されてはいけない (対象外)"


def test_op07_017_main_human_ko_pick():
    """メイン (人間): 相手のパワー3000以下キャラ 複数 → target_pick modal → KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # power3000
    b = InPlay.of(repo.get(_RED1), sickness=False)    # power2000
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP07-017", "main")[0], st, me, opp, None)
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
#  OP07-018 KEEP OUT (EVENT 赤 cost1):
#    【カウンター】自分の特徴《革命軍》を持つキャラ1枚までを、次の自分のターン終了時まで、
#      パワー+2000。
# --------------------------------------------------------------------------- #
def test_op07_018_counter_pump_kakumei_ai():
    """カウンター: 自革命軍キャラ1枚を +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    sabo = InPlay.of(repo.get(_KAKUMEI), sickness=False)  # 革命軍
    me.characters = [sabo]
    before = sabo.power

    for prim in _do(overlay, "OP07-018", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert sabo.power == before + 2000, \
        f"カウンターの +2000 が革命軍キャラに反映されていない: {sabo.power} (before {before})"


def test_op07_018_counter_human_target_pick():
    """カウンター (人間): 革命軍キャラ 複数候補 → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_KAKUMEI), sickness=False)
    b = InPlay.of(repo.get(_KAKUMEI2), sickness=False)
    me.characters = [a, b]

    execute_effect(_do(overlay, "OP07-018", "counter")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before + 2000, "人間が選んだ革命軍キャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP07-019 ジュエリー・ボニー (LEADER 緑):
#    【相手のアタック時】【ターン1回】(1)(ドン!!1枚をレストにできる)：
#      相手の、リーダーかキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op07_019_opp_attack_rest_opponent_ai():
    """相手のアタック時: ドン1枚をレスト (コスト) → 相手キャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-019", overlay)  # リーダー = 緑ボニー
    me, opp = st.players[0], st.players[1]
    me.don_active = 2  # レスト用アクティブドン
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]
    assert victim.rested is False

    for prim in _do(overlay, "OP07-019", "opp_attack"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert me.don_active == 1, f"コストでドン1枚がレストされていない: don_active={me.don_active}"
    assert victim.rested is True, "相手キャラがレストされていない"


def test_op07_019_opp_attack_human_optional_cost_modal():
    """相手のアタック時 (人間): 任意コスト optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-019", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    execute_effect(_do(overlay, "OP07-019", "opp_attack")[0], st, me, opp, me.leader)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st)


# --------------------------------------------------------------------------- #
#  OP07-020 アラディン (CHARACTER 緑 cost5 power6000):
#    【ブロッカー】【KO時】自分のリーダーが特徴《魚人族》を持つ場合、自分の手札から
#      コスト3以下の特徴《魚人族》か《人魚族》を持つキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op07_020_on_ko_play_gyojin_when_gyojin_leader_ai():
    """KO時: 魚人族リーダーなら手札からコスト3以下の魚人族/人魚族キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _GYOJIN_LEADER, overlay)  # ジンベエ (魚人族)
    me, opp = st.players[0], st.players[1]
    cond = _eff(overlay, "OP07-020", "on_ko").get("if")
    assert eval_condition(cond, st, me) is True, "魚人族リーダーで条件が成立していない"
    me.hand = [repo.get(_GYOJIN_CHAR)]  # アーロン cost1 魚人族
    src = InPlay.of(repo.get("OP07-020"), sickness=False)

    for prim in _do(overlay, "OP07-020", "on_ko"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert any(c.card.card_id == _GYOJIN_CHAR for c in me.characters), \
        "手札から魚人族キャラが登場していない"


def test_op07_020_on_ko_no_effect_when_non_gyojin_leader():
    """KO時 negative: リーダーが魚人族でなければ条件不成立 → 登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)  # 非魚人族 リーダー
    me, opp = st.players[0], st.players[1]
    cond = _eff(overlay, "OP07-020", "on_ko").get("if")
    assert eval_condition(cond, st, me) is False, \
        "非魚人族 リーダーなのに条件が成立している"


def test_op07_020_on_ko_human_play_pick():
    """KO時 (人間): 手札に魚人族/人魚族 複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _GYOJIN_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_GYOJIN_CHAR), repo.get("EB02-011")]  # アーロン / アーロン cost3
    src = InPlay.of(repo.get("OP07-020"), sickness=False)

    execute_effect(_do(overlay, "OP07-020", "on_ko")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card.card_id in (_GYOJIN_CHAR, "EB02-011") for c in me.characters), \
        "人間が選んだ魚人族キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP07-022 お玉 (CHARACTER 緑 cost1):
#    【登場時】自分のデッキの上から5枚を見て、「お玉」以外の緑の特徴《ワノ国》を持つ
#      カード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op07_022_on_play_search_green_wano_ai():
    """登場時: デッキ上5枚から緑ワノ国 (お玉以外) を手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WANO_GREEN)] + [repo.get(_FILLER)] * 10  # 上に緑ワノ国
    me.hand = []
    src = InPlay.of(repo.get("OP07-022"), sickness=True)

    for prim in _do(overlay, "OP07-022", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert any(c.card_id == _WANO_GREEN for c in me.hand), \
        f"デッキ上5枚から緑ワノ国が手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op07_022_on_play_human_search_modal():
    """登場時 (人間): デッキ上5枚に候補が複数 → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WANO_GREEN), repo.get(_FILLER), repo.get(_WANO_GREEN)] \
        + [repo.get(_FILLER)] * 8
    me.hand = []
    src = InPlay.of(repo.get("OP07-022"), sickness=True)

    execute_effect(_do(overlay, "OP07-022", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == _WANO_GREEN for c in me.hand), \
        "人間が選んだ緑ワノ国が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP07-023 カリブー (CHARACTER 緑 cost4 power5000):
#    自分のレストのドン!!が6枚以上ある場合、このキャラはパワー+1000。【ブロッカー】
# --------------------------------------------------------------------------- #
def test_op07_023_static_pump_when_6_rested_don():
    """静的効果: 自分のレストドンが6枚以上なら パワー+1000。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(_LEADER), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(_LEADER), sickness=False))
    caribou_def = repo.get(_CARIBOU)  # power5000
    caribou = InPlay.of(caribou_def, sickness=False)
    p0.characters = [caribou]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    p0.don_rested = 6  # レストドン 6 → +1000
    evaluate_static_effects(st, overlay)

    assert caribou.power == caribou_def.power + 1000, \
        f"レストドン6で +1000 が反映されていない: {caribou.power} (base {caribou_def.power})"


def test_op07_023_static_no_pump_when_few_rested_don():
    """静的効果 negative: レストドンが6枚未満なら +0 (印刷値のまま)。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(_LEADER), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(_LEADER), sickness=False))
    caribou_def = repo.get(_CARIBOU)
    caribou = InPlay.of(caribou_def, sickness=False)
    p0.characters = [caribou]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    p0.don_rested = 5  # 6 枚未満 → 条件不成立
    evaluate_static_effects(st, overlay)

    assert caribou.power == caribou_def.power, \
        f"レストドン5で pump が乗ってはいけない: {caribou.power} (base {caribou_def.power})"


# --------------------------------------------------------------------------- #
#  OP07-025 コリブー (CHARACTER 緑 cost3 power3000):
#    【登場時】自分の手札からコスト4以下の「カリブー」1枚までを、レストで登場させる。
# --------------------------------------------------------------------------- #
def test_op07_025_on_play_play_caribou_rested_ai():
    """登場時: 手札からコスト4以下の「カリブー」をレストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_CARIBOU)]  # カリブー cost4
    src = InPlay.of(repo.get("OP07-025"), sickness=True)

    for prim in _do(overlay, "OP07-025", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    played = [c for c in me.characters if c.card.card_id == _CARIBOU]
    assert played, "手札からカリブーが登場していない"
    assert played[0].rested is True, "カリブーはレストで登場するべき"


def test_op07_025_on_play_human_play_pick():
    """登場時 (人間): 手札にカリブー 複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_CARIBOU), repo.get(_CARIBOU)]  # カリブー 2 枚
    src = InPlay.of(repo.get("OP07-025"), sickness=True)

    execute_effect(_do(overlay, "OP07-025", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card.card_id == _CARIBOU for c in me.characters), \
        "人間が選んだカリブーが登場していない"
