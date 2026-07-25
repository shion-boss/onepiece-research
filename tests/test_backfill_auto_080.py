# -*- coding: utf-8 -*-
"""OP07 弾 効果 回帰テスト バックフィル (自動生成 wave 080):
OP07-088 / OP07-090 / OP07-092 / OP07-093 / OP07-094 / OP07-096 /
OP07-097 / OP07-098 / OP07-100 / OP07-101 の 10 枚
(黒 CP0/CP9/ジャーナリスト 除去・手札破壊 系 + 黄 ベガパンク/エッグヘッド 系)。

目的 (= 永続的 pytest による担保、 test_backfill_auto_079.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"     # ロロノア・ゾロ (赤、 直接 execute_effect なので色は無関係)
_FILLER = "OP01-013"     # サンジ cost2 power3000 (汎用フィラー)
_OPP_C = "OP01-013"      # サンジ cost2 power3000 (相手キャラ)
_OPP_C2 = "OP06-025"     # ケイミー cost1 (相手キャラ、 cost<=1 の KO 対象)
_LUCCI = "OP07-093"      # ロブ・ルッチ (name「ロブ・ルッチ」 CHARACTER cost5 power6000)
_CP_CARD1 = "OP07-088"   # ハットリ (特徴 動物/CP0 → feature に CP を含む)
_CP_CARD2 = "OP07-092"   # ヨセフ (特徴 CP0)
_EGGHEAD = "OP07-098"    # アトラス (特徴 科学者/エッグヘッド cost5、 on_play を持たない)


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
def test_all_wave80_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP07-088", "OP07-090", "OP07-092", "OP07-093", "OP07-094",
           "OP07-096", "OP07-097", "OP07-098", "OP07-100", "OP07-101"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP07-088 ハットリ (CHARACTER 黒 cost1):
#    【自分のターン中】【登場時】自分の「ロブ・ルッチ」1枚までを、このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op07_088_on_play_pump_lucci_ai():
    """登場時: 自分の「ロブ・ルッチ」1枚を +2000 (このターン中、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    lucci = InPlay.of(repo.get(_LUCCI), sickness=False)  # power 6000
    me.characters = [lucci]
    power_before = lucci.power

    for prim in _do(overlay, "OP07-088", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-088"), sickness=True))
    _drain(st)
    assert lucci.power == power_before + 2000, \
        f"「ロブ・ルッチ」に +2000 が反映されていない: {lucci.power} (before {power_before})"


def test_op07_088_self_turn_condition():
    """条件: 【自分のターン中】 = self_turn。 自ターンで成立、 相手ターンで不成立。"""
    repo = _repo()
    overlay = _overlay()
    cond = _eff(overlay, "OP07-088", "on_play").get("conditions")
    assert cond is not None, "OP07-088 に self_turn 条件がない"
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    assert eval_condition(cond[0], st, me) is True, "自ターンで self_turn が成立するべき"
    st.turn_player_idx = 1
    assert eval_condition(cond[0], st, me) is False, \
        "相手ターンで self_turn が成立してはいけない"


def test_op07_088_on_play_pump_human_pick():
    """登場時 (人間): 「ロブ・ルッチ」が2体 → target_pick modal → 選んだ方に +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_LUCCI), sickness=False)
    b = InPlay.of(repo.get(_LUCCI), sickness=False)
    me.characters = [a, b]

    execute_effect(_do(overlay, "OP07-088", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP07-088"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (ロブ・ルッチ 2体) が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before + 2000, "人間が選んだ「ロブ・ルッチ」に +2000 が反映されていない"
    assert a.power == repo.get(_LUCCI).power, "選ばなかった側は pump されないべき"


# --------------------------------------------------------------------------- #
#  OP07-090 モルガンズ (CHARACTER 黒 cost2):
#    【登場時】相手は自身の手札を1枚捨て、手札を公開する。その後、相手はカード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op07_090_on_play_opp_discard_then_draw_ai():
    """登場時: 相手が手札1枚を捨て (trash +1)、 その後カード1枚を引く (deck -1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER) for _ in range(3)]
    opp.deck = [repo.get(_FILLER)] * 10
    opp.trash = []
    hand_before = len(opp.hand)
    deck_before = len(opp.deck)

    for prim in _do(overlay, "OP07-090", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-090"), sickness=True))
    _drain(st)
    # 捨て -1 + ドロー +1 → 手札枚数は net 変わらず
    assert len(opp.hand) == hand_before, \
        f"相手手札の net が合わない (捨て1+ドロー1): {len(opp.hand)}"
    assert len(opp.trash) == 1, "相手が手札1枚を捨てていない (trash +1)"
    assert len(opp.deck) == deck_before - 1, "相手がカード1枚を引いていない (deck -1)"


# --------------------------------------------------------------------------- #
#  OP07-092 ヨセフ (CHARACTER 黒 cost1):
#    【登場時】自分のトラッシュの『CP』を含む特徴を持つカード2枚をデッキ下に置くことができる：
#      相手のコスト1以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op07_092_on_play_optional_ko_ai():
    """登場時: 任意コスト (CP特徴 2枚→デッキ下) を払い、 相手コスト1以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_CP_CARD1), repo.get(_CP_CARD2)]  # CP 特徴 2 枚
    victim = InPlay.of(repo.get(_OPP_C2), sickness=False)  # ケイミー cost1
    opp.characters = [victim]
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP07-092", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-092"), sickness=True))
    _drain(st)
    assert victim not in opp.characters, "相手コスト1以下キャラが KO されていない"
    assert len(me.trash) == 0, "コストの CP特徴 2枚がトラッシュから移動していない"
    assert len(me.deck) == deck_before + 2, "CP特徴 2枚がデッキ下に置かれていない"


def test_op07_092_on_play_human_optional_cost():
    """登場時 (人間): optional_cost_confirm modal → pay ([1]) で KO まで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_CP_CARD1), repo.get(_CP_CARD2)]
    victim = InPlay.of(repo.get(_OPP_C2), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-092", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-092"), sickness=True))
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st)
    assert victim not in opp.characters, "任意コスト承認後に KO が解決されていない"


# --------------------------------------------------------------------------- #
#  OP07-093 ロブ・ルッチ (CHARACTER 黒 cost5):
#    【登場時】自分のトラッシュのカード3枚をデッキ下に置くことができる：相手は自身の手札1枚
#      を捨てる。その後、相手のトラッシュのカード1枚までを、デッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op07_093_on_play_optional_hand_and_trash_disrupt_ai():
    """登場時: 任意コスト (自トラッシュ3枚→デッキ下) を払い、 相手手札1枚捨て +
    相手トラッシュ1枚をデッキ下 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_FILLER)] * 3
    opp.hand = [repo.get(_FILLER)]
    opp.trash = [repo.get("OP01-016")]
    opp_deck_before = len(opp.deck)

    for prim in _do(overlay, "OP07-093", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-093"), sickness=True))
    _drain(st)
    assert len(me.trash) == 0, "コストの自トラッシュ3枚が移動していない"
    assert len(opp.hand) == 0, "相手が手札1枚を捨てていない"
    # 相手トラッシュ1枚がデッキ下へ (= opp.deck +1)。 手札捨てで opp.trash に1枚戻る
    assert len(opp.deck) == opp_deck_before + 1, \
        "相手トラッシュ1枚がデッキ下に置かれていない (opp.deck +1)"


# --------------------------------------------------------------------------- #
#  OP07-094 剃 (EVENT 黒 cost1):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
#    【トリガー】自分のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op07_094_counter_pump_leader_ai():
    """カウンター: 自リーダー1枚を このバトル中 +2000 (AI、 自陣キャラなし → リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power

    for prim in _do(overlay, "OP07-094", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert me.leader.power == power_before + 2000, \
        f"カウンターの battle +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op07_094_trigger_return_self_chara_ai():
    """トリガー: 自分のキャラ1枚を持ち主の手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]
    hand_before = len(me.hand)

    for prim in _do(overlay, "OP07-094", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert friend not in me.characters, "トリガーで自キャラが場から戻っていない"
    assert len(me.hand) == hand_before + 1, "戻したキャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP07-096 嵐脚 (EVENT 黒 cost1):
#    【メイン】カード1枚を引く。その後、自分のトラッシュが10枚以上ある場合、相手のキャラ
#      1枚までを、このターン中、コスト-3。
#    【トリガー】相手のコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op07_096_main_draw_then_cost_minus_ai():
    """メイン: 1枚引く + (トラッシュ10以上) 相手キャラ1枚を コスト-3 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_FILLER)] * 10  # トラッシュ10 → 条件成立
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_LUCCI), sickness=False)  # cost5 (-3 で 2)
    opp.characters = [victim]
    hand_before = len(me.hand)
    cost_before = victim.base_cost

    for prim in _do(overlay, "OP07-096", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == hand_before + 1, "メインの draw が起きていない"
    assert victim.base_cost == cost_before - 3, \
        f"相手キャラの コスト-3 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_op07_096_main_no_cost_minus_when_trash_low():
    """トラッシュ10未満 → conditional 不成立。 draw はするが コスト減は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_FILLER)] * 3  # 10 未満
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_LUCCI), sickness=False)
    opp.characters = [victim]
    hand_before = len(me.hand)
    cost_before = victim.base_cost

    for prim in _do(overlay, "OP07-096", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == hand_before + 1, "draw は トラッシュ枚数に関係なく起きるべき"
    assert victim.base_cost == cost_before, \
        "トラッシュ10未満で コスト減が乗ってはいけない"


def test_op07_096_trigger_ko_cost3_ai():
    """トリガー: 相手のコスト3以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)  # cost2 (<=3)
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-096", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim not in opp.characters, "トリガーで相手コスト3以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP07-097 ベガパンク (LEADER 黄):
#    このリーダーはアタックできない。
#    【起動メイン】【ターン1回】①：自分の手札からコスト5以下の特徴《エッグヘッド》を持つ
#      カード1枚までを、ライフの上に表向きで加えるか登場させる。
# --------------------------------------------------------------------------- #
def test_op07_097_activate_main_play_or_life_ai():
    """起動メイン: レストドン1コストを払い、 手札のエッグヘッド cost5以下を登場 or ライフへ (AI)。
    (choice のどちらを選んでも 手札から1枚が消費される)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-097", overlay)  # リーダー = ベガパンク
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_EGGHEAD)]  # アトラス エッグヘッド cost5
    me.don_active = 2               # rest_self_don コスト用
    me.life = [repo.get(_FILLER)] * 3

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-097"]
    assert len(opts) == 1, \
        f"OP07-097 の起動メインが legal に出ない: {len(opts)}"
    chars_before = len(me.characters)
    life_before = len(me.life)
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert len(me.hand) == 0, "起動メインで手札のエッグヘッドが消費されていない"
    # 登場 (chars +1) か ライフ追加 (life +1) の どちらかが成立している
    assert len(me.characters) == chars_before + 1 or len(me.life) == life_before + 1, \
        "エッグヘッドが 登場も ライフ追加も されていない"


def test_op07_097_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-097", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_EGGHEAD)]
    me.don_active = 3
    me.life = [repo.get(_FILLER)] * 3

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP07-097"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP07-097"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP07-098 アトラス (CHARACTER 黄 cost5):
#    自分のライフの枚数が相手のライフの枚数より少ない場合、このキャラはバトルでKOされない。
#    【トリガー】自分のリーダーが「ベガパンク」の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op07_098_static_ko_immune_when_life_lt_opp():
    """静的: 自ライフ < 相手ライフ で バトルKO耐性 (battle_ko_immune_static)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    atlas = InPlay.of(repo.get("OP07-098"), sickness=False)
    me.characters = [atlas]
    me.life = [repo.get(_FILLER)] * 1
    opp.life = [repo.get(_FILLER)] * 3

    evaluate_static_effects(st, overlay)
    assert atlas.battle_ko_immune_static is True, \
        "自ライフ < 相手ライフ なのに バトルKO耐性 が付いていない"


def test_op07_098_static_no_immune_when_life_ge_opp():
    """自ライフ >= 相手ライフ なら 条件不成立 → バトルKO耐性は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    atlas = InPlay.of(repo.get("OP07-098"), sickness=False)
    me.characters = [atlas]
    me.life = [repo.get(_FILLER)] * 3
    opp.life = [repo.get(_FILLER)] * 3

    evaluate_static_effects(st, overlay)
    assert atlas.battle_ko_immune_static is False, \
        "自ライフ >= 相手ライフ なのに バトルKO耐性 が付いてはいけない"


def test_op07_098_trigger_play_self_ai():
    """トリガー: 自リーダーが「ベガパンク」なら このカードを登場 (play_self、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-097", overlay)  # リーダー = ベガパンク
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP07-098")]
    st.current_source_card_id = "OP07-098"
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP07-098", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card.card_id == "OP07-098" for c in me.characters), \
        "トリガー play_self で アトラス が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP07-100 エジソン (CHARACTER 黄 cost4):
#    【登場時】自分のライフが2枚以下の場合、カード2枚を引き、自分の手札2枚を捨てる。
#    【トリガー】自分のリーダーが「ベガパンク」の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op07_100_on_play_draw2_discard2_ai():
    """登場時: (ライフ2以下) カード2枚引き、 手札2枚を捨てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = [repo.get(_FILLER)] * 3
    me.deck = [repo.get(_FILLER)] * 10
    me.trash = []
    deck_before = len(me.deck)
    hand_before = len(me.hand)

    for prim in _do(overlay, "OP07-100", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-100"), sickness=True))
    _drain(st)
    # ドロー +2 / 捨て -2 → 手札 net 変わらず
    assert len(me.hand) == hand_before, \
        f"手札 net (ドロー2 - 捨て2) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "カード2枚を引いていない (deck -2)"
    assert len(me.trash) == 2, "手札2枚を捨てていない (trash +2)"


def test_op07_100_life_condition():
    """条件: 自ライフ2以下で成立、 3枚以上で不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    cond = _eff(overlay, "OP07-100", "on_play").get("if")
    assert cond is not None, "OP07-100 に self_life_le 条件がない"
    me.life = [repo.get(_FILLER)] * 2
    assert eval_condition(cond, st, me) is True, "ライフ2枚で条件が成立するべき"
    me.life = [repo.get(_FILLER)] * 3
    assert eval_condition(cond, st, me) is False, \
        "ライフ3枚で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP07-101 シャカ (CHARACTER 黄 cost5):
#    【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)
#    【トリガー】自分のリーダーが「ベガパンク」の場合、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op07_101_is_blocker_intrinsic():
    """【ブロッカー】は intrinsic キーワード → is_blocker() が True。"""
    repo = _repo()
    shaka_def = repo.get("OP07-101")
    assert shaka_def.is_blocker is True, "シャカ (CardDef) が【ブロッカー】を持たない"
    shaka = InPlay.of(shaka_def, sickness=False)
    assert shaka.is_blocker_now is True, "シャカ (場) が【ブロッカー】を発動できない"


def test_op07_101_trigger_play_self_ai():
    """トリガー: 自リーダーが「ベガパンク」なら このカードを登場 (play_self、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-097", overlay)  # リーダー = ベガパンク
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP07-101")]
    st.current_source_card_id = "OP07-101"
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP07-101", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card.card_id == "OP07-101" for c in me.characters), \
        "トリガー play_self で シャカ が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"
