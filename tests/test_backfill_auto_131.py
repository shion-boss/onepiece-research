# -*- coding: utf-8 -*-
"""OP13 弾 効果 回帰テスト バックフィル (自動生成 wave 131):
OP13-106 / OP13-108 / OP13-109 / OP13-110 / OP13-112 / OP13-113 /
OP13-114 / OP13-115 / OP13-116 / OP13-117 の 10 枚。

目的 (= test_backfill_auto_001〜130.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める (= サーチ/ドローの混入回避)。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("ST01-004")] * 30
    p1.deck = [repo.get("ST01-004")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _entries(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 entry を全件返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の do を返す。"""
    return _entries(overlay, cid, when)[0]["do"]


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# 定番 helper カード
_FILLER = "ST01-004"        # サンジ (cost2 pow4000 CHARACTER、 トリガー無し)
_TRIG_CHAR_A = "PRB02-012"  # ナミ (cost2 CHARACTER、 【トリガー】このカードを登場させる)
_TRIG_CHAR_B = "PRB02-017"  # ボア・ハンコック (cost5 CHARACTER、 【トリガー】持ち)
_SS_CHAR_A = "PRB02-005"    # モンキー・D・ルフィ (cost4 超新星/麦わらの一味)
_SS_CHAR_B = "PRB02-004"    # ジュエリー・ボニー (cost3 超新星/ボニー海賊団)
_EGG_LEADER = "OP13-100"    # ジュエリー・ボニー (LEADER 黄 エッグヘッド/ボニー海賊団)
_KAIOU = "OP11-027"         # ギョロ目 (cost4 pow6000 CHARACTER)
_COST3 = "ST01-005"         # ジンベエ (cost3 pow5000 CHARACTER = KO 対象 cost≤6)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op13_wave131_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP13-106", "OP13-108", "OP13-109", "OP13-110", "OP13-112",
           "OP13-113", "OP13-114", "OP13-115", "OP13-116", "OP13-117"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP13-106 コニー (CHARACTER 黄 cost1):
#    【相手のターン中】【トリガー】が発動した時、 このキャラは このターン中【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op13_106_konny_gain_blocker_ai():
    """相手ターン中の自トリガー発動時: 自身が【ブロッカー】を得る (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 文脈)
    me, opp = st.players[0], st.players[1]
    konny = InPlay.of(repo.get("OP13-106"), sickness=False)
    me.characters = [konny]

    assert konny.is_blocker_now is False, "前提: 発動前は【ブロッカー】でない"
    do = _entries(overlay, "OP13-106", "on_self_trigger_fired")[0]["do"]
    for prim in do:
        execute_effect(prim, st, me, opp, konny)

    assert konny.is_blocker_now is True, \
        "相手ターン中の自トリガー発動で【ブロッカー】を得ていない"


# --------------------------------------------------------------------------- #
#  OP13-108 ジュエリー・ボニー (CHARACTER 黄 cost9):
#    【登場時】自リーダーが特徴《エッグヘッド》を持つ場合、 このキャラは このターン中【速攻】を
#    得る。 その後、 相手は自身のライフの上から1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op13_108_boni_on_play_speed_and_mill_ai():
    """登場時 (エッグヘッド leader): 自身【速攻】 + 相手ライフ上1枚を相手手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _EGG_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    boni = InPlay.of(repo.get("OP13-108"), sickness=True)
    me.characters = [boni]
    opp.life = [repo.get(_FILLER)] * 2
    opp.hand = []

    assert eval_condition({"leader_feature": "エッグヘッド"}, st, me) is True, \
        "前提: 自リーダーがエッグヘッドの条件が成立していない"

    life_before = len(opp.life)
    hand_before = len(opp.hand)
    for prim in _do(overlay, "OP13-108", "on_play"):
        execute_effect(prim, st, me, opp, boni)

    assert boni.is_rush_now is True, "登場時に自身が【速攻】を得ていない"
    assert len(opp.life) == life_before - 1, "相手ライフが1枚減っていない"
    assert len(opp.hand) == hand_before + 1, "相手手札が1枚増えていない"


def test_op13_108_boni_on_play_gate_off_when_not_egghead():
    """負例: 自リーダーがエッグヘッドでなければ 登場時条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 非エッグヘッド leader
    me = st.players[0]
    assert eval_condition({"leader_feature": "エッグヘッド"}, st, me) is False, \
        "非エッグヘッド leader で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP13-109 ジュエリー・ボニー (CHARACTER 黄 cost5):
#    このキャラが相手の効果で場を離れる場合、 代わりに自ライフ上1枚を表向きにできる (replace_leave)。
#    【トリガー】2ドロー + 手札1捨て。
# --------------------------------------------------------------------------- #
def test_op13_109_boni_trigger_draw2_discard1_ai():
    """トリガー: 2枚引き + 手札1枚捨て (net 手札 +1、 デッキ -2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 6
    me.hand = [repo.get("OP01-016")]  # 捨てる候補

    deck_before = len(me.deck)
    hand_before = len(me.hand)
    for prim in _do(overlay, "OP13-109", "trigger"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-109"), sickness=False))

    assert len(me.deck) == deck_before - 2, "2枚ドローでデッキが2枚減っていない"
    assert len(me.hand) == hand_before + 2 - 1, \
        f"net 手札 (+2 -1 = +1) が合わない: {len(me.hand)} (before {hand_before})"


def test_op13_109_boni_replace_leave_flip_life_ai():
    """相手効果離脱の代替 = 自ライフ上1枚を表向きにする。 これは **置換のコスト**。

    ⚠ 2026-08-12 是正: 従来 overlay は `do` に flip_life_face_up_effect を置いており、
      一番上が既に表向きでも **置換が成立して KO を免れて** いた。 公式 (cardqa_op_13) は
      「一番上が表向きの場合…できますか？」 → 「**いいえ**」。 cost に移して payability
      (pos:top) で gate する形に変えたので、 本テストも **cost 側** を見る。
    """
    import json as _json
    repo = _repo()
    overlay = _overlay()
    eff = next(e for e in overlay.get("OP13-109").effects
               if e.get("when") == "replace_leave")
    assert eff.get("cost") == [{"flip_life_face_up": {"pos": "top"}}], \
        f"置換の代償が cost に無い (do のままだとタダで置換できる): {eff.get('cost')}"
    assert not (eff.get("do") or []), "do 側に代償が残っている (二重に表向きになる)"

    # 一番上が裏向き → 代償を払えて 表向きになる
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.life = [repo.get(_FILLER)] * 2
    me.life_face_up = [False, False]
    from engine.effects import _can_pay_replace_cost, _pay_replace_cost
    assert _can_pay_replace_cost(st, me, eff["cost"], "OP13-109", None), \
        "一番上が裏向きなのに代償を払えない"
    _pay_replace_cost(st, me, eff["cost"], "OP13-109", None)
    assert me.life_face_up == [True, False], \
        f"ライフの一番上が表向きになっていない: {me.life_face_up}"

    # 一番上が既に表向き → 代償を払えない = 置換を選べない (公式 「いいえ」)
    st2 = _state(repo, "OP01-001", overlay)
    me2 = st2.players[0]
    me2.life = [repo.get(_FILLER)] * 2
    me2.life_face_up = [True, False]
    assert not _can_pay_replace_cost(st2, me2, eff["cost"], "OP13-109", None), \
        "一番上が既に表向きなのに置換の代償を払えることになっている"


# --------------------------------------------------------------------------- #
#  OP13-110 ステューシー (CHARACTER 黄 cost7):
#    【ブロッカー】【登場時】自リーダーが特徴《エッグヘッド》を持つ場合、 自分の手札から
#    コスト5以下の【トリガー】を持つキャラカード1枚までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op13_110_stussy_on_play_deploy_trigger_char_ai():
    """登場時 (エッグヘッド leader): 手札のコスト5以下トリガーキャラ1枚を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _EGG_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_TRIG_CHAR_A)]  # ナミ (cost2 トリガー持ち)

    assert eval_condition({"leader_feature": "エッグヘッド"}, st, me) is True, \
        "前提: 自リーダーがエッグヘッドの条件が成立していない"

    chars_before = len(me.characters)
    for prim in _do(overlay, "OP13-110", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-110"), sickness=True))
    _drain_choices(st, pick=[0])

    assert len(me.characters) == chars_before + 1, \
        "手札のトリガーキャラが登場していない"
    assert any(c.card.card_id == _TRIG_CHAR_A for c in me.characters), \
        "登場したのがトリガー持ちキャラでない"
    # 登場したキャラは手札から離れている (= 登場先の自身の登場時効果で手札枚数は
    # 増減しうるため net 枚数でなく「手札から出た」ことを検証)
    assert not any(c.card_id == _TRIG_CHAR_A for c in me.hand), \
        "登場したトリガーキャラが手札に残っている"


def test_op13_110_stussy_on_play_human_play_pick():
    """人間 + 手札にコスト5以下トリガーキャラ複数 → play_from_hand modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _EGG_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_TRIG_CHAR_A), repo.get(_TRIG_CHAR_B)]  # トリガー持ち 2 種

    execute_effect(_do(overlay, "OP13-110", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP13-110"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[0])
    assert any(c.card.card_id in (_TRIG_CHAR_A, _TRIG_CHAR_B)
               for c in me.characters), \
        "人間が選んだトリガーキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP13-112 ベガパンク (CHARACTER 黄 cost1):
#    自分の付与されているドン‼が合計2枚以上ある場合、 このキャラは【ブロッカー】を得る。 (静的)
# --------------------------------------------------------------------------- #
def test_op13_112_vegapunk_static_blocker_when_2_dons():
    """静的: 付与ドン2枚以上 → 【ブロッカー】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    vega = InPlay.of(repo.get("OP13-112"), sickness=False)
    vega.attached_dons = 2
    me.characters = [vega]

    evaluate_static_effects(st, overlay)
    assert vega.is_blocker_now is True, \
        "付与ドン2枚で【ブロッカー】を得ていない"


def test_op13_112_vegapunk_static_no_blocker_when_1_don():
    """負例: 付与ドン1枚では条件不成立 → 【ブロッカー】を得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    vega = InPlay.of(repo.get("OP13-112"), sickness=False)
    vega.attached_dons = 1
    me.characters = [vega]

    evaluate_static_effects(st, overlay)
    assert vega.is_blocker_now is False, \
        "付与ドン1枚で【ブロッカー】を得てはいけない"


# --------------------------------------------------------------------------- #
#  OP13-113 リリス (CHARACTER 黄 cost1):
#    【登場時】自デッキ上4枚を見て、「リリス」以外の【トリガー】を持つカード1枚までを公開手札へ、
#    残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op13_113_lilith_on_play_search_trigger_ai():
    """登場時: 上4枚から【トリガー】持ちカードを手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_TRIG_CHAR_A)] + [repo.get(_FILLER)] * 10
    me.hand = []

    for prim in _do(overlay, "OP13-113", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-113"), sickness=True))
    _drain_choices(st, pick=[0])

    assert any(c.card_id == _TRIG_CHAR_A for c in me.hand), \
        "上4枚から【トリガー】持ちカードが手札に加わっていない"


def test_op13_113_lilith_on_play_search_human_pick():
    """人間 + 上4枚に【トリガー】持ち複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_TRIG_CHAR_A), repo.get(_FILLER),
               repo.get(_TRIG_CHAR_B)] + [repo.get(_FILLER)] * 10
    me.hand = []

    execute_effect(_do(overlay, "OP13-113", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP13-113"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[])
    assert any(c.card_id in (_TRIG_CHAR_A, _TRIG_CHAR_B) for c in me.hand), \
        "人間が選んだ【トリガー】持ちカードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP13-114 S-スネーク (CHARACTER 黄 cost4):
#    【登場時】/【アタック時】自ライフ上1枚を表向きにできる：相手キャラ1枚までを
#    このターン中 パワー-2000。
# --------------------------------------------------------------------------- #
def test_op13_114_ssnake_on_play_debuff_ai():
    """登場時 (ライフ表向きコスト): 相手キャラ1枚を -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    # 2026-08-11: 表向きライフは per-card フラグ (life_face_up) で持つ
    me.life_face_up = [i < (0) for i in range(len(me.life))]
    victim = InPlay.of(repo.get(_KAIOU), sickness=False)  # pow6000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _do(overlay, "OP13-114", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-114"), sickness=True))
    _drain_choices(st, pick=[0])

    assert me.face_up_life_count == 1, "任意コストで自ライフ上1枚が表向きになっていない"
    assert victim.power == power_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power} (before {power_before})"


def test_op13_114_ssnake_on_play_human_optional_confirm():
    """人間: 任意コスト (ライフ表向き) の optional_cost_confirm modal が立ち、 承諾で -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    # 2026-08-11: 表向きライフは per-card フラグ (life_face_up) で持つ
    me.life_face_up = [i < (0) for i in range(len(me.life))]
    victim = InPlay.of(repo.get(_KAIOU), sickness=False)  # pow6000
    opp.characters = [victim]

    power_before = victim.power
    execute_effect(_do(overlay, "OP13-114", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP13-114"), sickness=True))

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain_choices(st, pick=[0])
    assert victim.power == power_before - 2000, \
        "人間承諾後に相手キャラ -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP13-115 「紙絵」“残身” (EVENT 黄 cost2):
#    【カウンター】自リーダーかキャラ1枚まで このバトル中 +3000。 その後、 相手ライフ2枚以下なら
#    自リーダーかキャラ1枚まで このターン中 +1000。 【トリガー】1ドロー。
# --------------------------------------------------------------------------- #
def test_op13_115_counter_pump_3000_ai():
    """カウンター(1): 自リーダーを このバトル中 +3000 (対象なし → リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    entries = _entries(overlay, "OP13-115", "counter")
    pump3000 = next(e for e in entries
                    if e["do"][0].get("power_pump", {}).get("amount") == 3000)
    for prim in pump3000["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"カウンター +3000 が自リーダーに反映されていない: {me.leader.power}"


def test_op13_115_counter_pump_1000_when_opp_life_le2():
    """カウンター(2): 相手ライフ2枚以下 → 自リーダーを +1000 (条件成立時)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 2  # 相手ライフ 2 (= 条件成立)

    entries = _entries(overlay, "OP13-115", "counter")
    pump1000 = next(e for e in entries
                    if e["do"][0].get("power_pump", {}).get("amount") == 1000)
    assert pump1000.get("if", {}).get("opp_life_le") == 2, \
        "overlay の条件 opp_life_le=2 が無い"
    assert eval_condition({"opp_life_le": 2}, st, me) is True, \
        "相手ライフ2枚以下の条件が成立していない"

    power_before = me.leader.power
    for prim in pump1000["do"]:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 1000, \
        f"カウンター +1000 が自リーダーに反映されていない: {me.leader.power}"


def test_op13_115_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ複数 → +3000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    entries = _entries(overlay, "OP13-115", "counter")
    pump3000 = next(e for e in entries
                    if e["do"][0].get("power_pump", {}).get("amount") == 3000)
    execute_effect(pump3000["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 3000, \
        "人間が選んだキャラに +3000 が反映されていない"


def test_op13_115_trigger_draw_ai():
    """トリガー: カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 5
    me.hand = []

    hand_before = len(me.hand)
    for prim in _do(overlay, "OP13-115", "trigger"):
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == hand_before + 1, "トリガーで1ドローが起きていない"


# --------------------------------------------------------------------------- #
#  OP13-116 この海で一番自由な奴が海賊王だ!!! (EVENT 黄 cost1):
#    【メイン】自デッキ上5枚を見て、 特徴《超新星》を持つキャラカード1枚までを公開手札へ、
#    残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op13_116_event_main_search_supernova_ai():
    """メイン: 上5枚から 超新星 キャラを手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SS_CHAR_A)] + [repo.get(_FILLER)] * 10
    me.hand = []

    for prim in _do(overlay, "OP13-116", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st, pick=[0])

    assert any(c.card_id == _SS_CHAR_A for c in me.hand), \
        "上5枚から 超新星 キャラが手札に加わっていない"


def test_op13_116_event_main_search_human_pick():
    """人間 + 上5枚に 超新星 複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SS_CHAR_A), repo.get(_FILLER),
               repo.get(_SS_CHAR_B)] + [repo.get(_FILLER)] * 10
    me.hand = []

    execute_effect(_do(overlay, "OP13-116", "main")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[])
    assert any(c.card_id in (_SS_CHAR_A, _SS_CHAR_B) for c in me.hand), \
        "人間が選んだ 超新星 キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP13-117 ゴムゴムの白いスタンプ (EVENT 黄 cost5):
#    【メイン】自ライフ上1枚を表向きにできる：相手の元々コスト6以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op13_117_event_main_ko_cost_le6_ai():
    """メイン (ライフ表向きコスト): 相手のコスト6以下キャラ1枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    # 2026-08-11: 表向きライフは per-card フラグ (life_face_up) で持つ
    me.life_face_up = [i < (0) for i in range(len(me.life))]
    victim = InPlay.of(repo.get(_COST3), sickness=False)  # cost3 (= ≤6)
    opp.characters = [victim]

    for prim in _do(overlay, "OP13-117", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st, pick=[0])

    assert me.face_up_life_count == 1, "任意コストで自ライフ上1枚が表向きになっていない"
    assert victim not in opp.characters, "相手のコスト6以下キャラが KO されていない"


def test_op13_117_event_main_ko_human_optional_confirm():
    """人間: 任意コスト (ライフ表向き) の optional_cost_confirm modal が立ち、 承諾で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    # 2026-08-11: 表向きライフは per-card フラグ (life_face_up) で持つ
    me.life_face_up = [i < (0) for i in range(len(me.life))]
    victim = InPlay.of(repo.get(_COST3), sickness=False)
    opp.characters = [victim]

    execute_effect(_do(overlay, "OP13-117", "main")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain_choices(st, pick=[0])
    assert victim not in opp.characters, \
        "人間承諾後に相手のコスト6以下キャラが KO されていない"
