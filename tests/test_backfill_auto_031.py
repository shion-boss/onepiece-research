# -*- coding: utf-8 -*-
"""OP02 弾 効果 回帰テスト バックフィル (自動生成 wave 031):
OP02-061 / OP02-062 / OP02-063 / OP02-064 / OP02-065 / OP02-069 /
OP02-070 / OP02-072 / OP02-073 / OP02-074 の 10 枚
(= 青 インペルダウン/王下七武海 の アタック/カウンター/起動 系 +
   紫 インペルダウン の 展開/静的付与 + 紫黒 ゼット リーダー)。

目的 (= test_backfill_auto_001〜030.py と同一方針):
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


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` の両対応)。

    ⚠ 2026-08-05: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を **効果のみ** の
    gate とする (cardqa_op_02 / cardqa_st_04)。 top-level `if` に置くと **任意コストの支払いごと
    消える** ので、 overlay ではこの形の条件を `conditional` の中に移した。
    条件そのものは変わっていないので、 テストはどちらの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    for _prim in eff.get("do") or []:
        if isinstance(_prim, dict) and "conditional" in _prim:
            return (_prim.get("conditional") or {}).get("if") or {}
    return {}


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


# BLUE = 青 王下七武海 リーダー (OP01-060 ドフラミンゴ)。 backfill 汎用 leader に安全。
BLUE_LEADER = "OP01-060"


def _state(repo, overlay, human_idx=None, leader_id=BLUE_LEADER,
           opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める。"""
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


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 (do 配列, eff dict) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op02_wave31_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP02-061", "OP02-062", "OP02-063", "OP02-064", "OP02-065",
           "OP02-069", "OP02-070", "OP02-072", "OP02-073", "OP02-074"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP02-061 モーリー (CHARACTER): 【アタック時】自分の手札が1枚以下の場合、相手は
#    このバトル中、 コスト5以下のキャラの【ブロッカー】を発動できない。
# --------------------------------------------------------------------------- #
def test_op02_061_morley_on_attack_prevent_blocker_cost_le5():
    """アタック時 (手札1枚以下ゲート): 相手コスト5以下キャラに「ブロック不可」を付与。
    コスト6のキャラは対象外 (ブロック不可にならない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")]  # 手札1枚 = 条件成立
    small = InPlay.of(repo.get("ST01-004"), sickness=False)   # cost2 (<=5)
    big = InPlay.of(repo.get("OP02-062"), sickness=False)     # cost6 (>5)
    opp.characters = [small, big]

    do, eff = _do(overlay, "OP02-061", "on_attack")
    assert _cond_of(eff).get("self_hand_count_le") == 1, \
        "overlay の トリガー条件 self_hand_count_le=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-061"), sickness=False))
    _drain_choices(st)

    assert "ブロック不可" in small.granted_keywords, \
        "コスト5以下キャラに ブロック不可 が付与されていない"
    assert "ブロック不可" not in big.granted_keywords, \
        "コスト6のキャラに ブロック不可 が付与されてはいけない (対象外)"


# --------------------------------------------------------------------------- #
#  OP02-062 モンキー・D・ルフィ (CHARACTER): 【登場時】/【アタック時】手札2枚を捨てる
#    ことができる：コスト4以下のキャラ1枚までを持ち主の手札に戻す。 その後このターン中
#    【ダブルアタック】を得る。
# --------------------------------------------------------------------------- #
def test_op02_062_luffy_on_play_pay_cost_double_attack_ai():
    """登場時: 手札2枚捨て (任意コスト) → その後このターン中ダブルアタックを得る (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP02-062"), sickness=False)
    me.characters = [luffy]
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]  # 捨てる 2 枚

    do, _ = _do(overlay, "OP02-062", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, luffy)
    _drain_choices(st, pick=[1])

    assert len(me.hand) == 0, "任意コストで手札2枚が捨てられるべき"
    assert "ダブルアタック" in luffy.granted_keywords, \
        "コスト支払い後 このターン中 ダブルアタックを得ていない"


def test_op02_062_luffy_on_play_human_optional_cost_confirm():
    """人間 actor: 任意コスト (手札2捨て) → optional_cost_confirm modal が立ち、
    承諾で発動しダブルアタックを得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP02-062"), sickness=False)
    me.characters = [luffy]
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]

    do, _ = _do(overlay, "OP02-062", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, luffy)

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain_choices(st, pick=[0])
    assert "ダブルアタック" in luffy.granted_keywords, \
        "承諾後 このターン中 ダブルアタックを得ていない"


# --------------------------------------------------------------------------- #
#  OP02-063 Mr.1(ダズ・ボーネス) (CHARACTER): 【登場時】自分のトラッシュからコスト1の
#    青のイベント1枚までを、 手札に加える。
# --------------------------------------------------------------------------- #
def test_op02_063_mr1_on_play_trash_to_hand_ai():
    """登場時: 自トラッシュのコスト1青イベントを手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP07-056")]  # 虜の矢 = コスト1 青 EVENT
    me.hand = []

    do, _ = _do(overlay, "OP02-063", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-063"), sickness=True))
    _drain_choices(st)

    assert any(c.card_id == "OP07-056" for c in me.hand), \
        "トラッシュのコスト1青イベントが手札に加わっていない"
    assert not any(c.card_id == "OP07-056" for c in me.trash), \
        "手札に加えたイベントがトラッシュに残っている"


def test_op02_063_mr1_on_play_no_matching_event():
    """トラッシュに コスト1青イベントが無ければ 手札は増えない (該当なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("ST01-004")]  # CHARACTER のみ = 対象外
    me.hand = []

    do, _ = _do(overlay, "OP02-063", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-063"), sickness=True))
    _drain_choices(st)

    assert len(me.hand) == 0, "該当イベントが無いのに手札が増えている"


# --------------------------------------------------------------------------- #
#  OP02-064 Mr.2・ボン・クレー (CHARACTER): 【ドン!!×1】【アタック時】手札1枚を捨てる
#    ことができる：コスト2以下のキャラ1枚までを持ち主のデッキの下に置く。 その後、この
#    バトル終了時、 このキャラを持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op02_064_bentham_on_attack_bounce_and_schedule_ai():
    """アタック時 (ドン1ゲート): 手札1捨て → 相手コスト2以下キャラをデッキ下 +
    このキャラをバトル終了時デッキ下に置くスケジュールが立つ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    bentham = InPlay.of(repo.get("OP02-064"), sickness=False)
    bentham.attached_dons = 1
    me.characters = [bentham]
    me.hand = [repo.get("ST01-004")]  # 捨てるコスト
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=2)
    opp.characters = [victim]

    do, eff = _do(overlay, "OP02-064", "on_attack")
    assert _cond_of(eff).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    deck_before = len(opp.deck)
    for prim in do:
        execute_effect(prim, st, me, opp, bentham)
    _drain_choices(st, pick=[0])

    assert victim not in opp.characters, "相手コスト2以下キャラがデッキ下へ戻っていない"
    assert len(opp.deck) == deck_before + 1, "相手のデッキ下にカードが戻っていない"
    assert len(me.hand) == 0, "任意コストで手札1枚が捨てられるべき"
    assert bentham.return_to_deck_bottom_at_battle_end is True, \
        "バトル終了時に自身をデッキ下に置くスケジュールが立っていない"


def test_op02_064_bentham_on_attack_human_optional_cost_confirm():
    """人間 actor: 任意コスト (手札1捨て) → optional_cost_confirm modal が立ち、 承諾で発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    bentham = InPlay.of(repo.get("OP02-064"), sickness=False)
    bentham.attached_dons = 1
    me.characters = [bentham]
    me.hand = [repo.get("ST01-004")]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-064", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, bentham)

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain_choices(st, pick=[0])
    assert victim not in opp.characters, "承諾後 相手コスト2以下キャラがデッキ下へ戻っていない"


# --------------------------------------------------------------------------- #
#  OP02-065 Mr.3(ギャルディーノ) (CHARACTER): 【ブロッカー】【自分のターン終了時】
#    自分の手札1枚を捨てることができる：このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op02_065_mr3_end_of_turn_untap_self_ai():
    """自分のターン終了時: 手札1捨て (任意コスト) → このキャラをアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    mr3 = InPlay.of(repo.get("OP02-065"), sickness=False)
    mr3.rested = True  # ブロックで レスト済 を想定
    me.characters = [mr3]
    me.hand = [repo.get("ST01-004")]  # 捨てるコスト

    do, _ = _do(overlay, "OP02-065", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp, mr3)
    _drain_choices(st, pick=[1])

    assert mr3.rested is False, "ターン終了時に自身がアクティブになっていない"
    assert len(me.hand) == 0, "任意コストで手札1枚が捨てられるべき"


def test_op02_065_mr3_end_of_turn_human_optional_cost_confirm():
    """人間 actor: 任意コスト (手札1捨て) → optional_cost_confirm modal が立ち、 承諾でアクティブ化。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    mr3 = InPlay.of(repo.get("OP02-065"), sickness=False)
    mr3.rested = True
    me.characters = [mr3]
    me.hand = [repo.get("ST01-004")]

    do, _ = _do(overlay, "OP02-065", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp, mr3)

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain_choices(st, pick=[0])
    assert mr3.rested is False, "承諾後 自身がアクティブになっていない"


# --------------------------------------------------------------------------- #
#  OP02-069 DEATH WINK (EVENT): 【カウンター】自分のリーダーかキャラ1枚までを、
#    このバトル中、 パワー+6000。 その後、 自分の手札が2枚になるようにカードを引く。
#    【トリガー】コスト7以下のキャラ1枚までを、 持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op02_069_death_wink_counter_pump_and_draw_ai():
    """カウンター: 自リーダーに +6000 + 手札が2枚になるようドロー (AI 自動、 リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []  # 0 枚 → 2 枚になるまで引く
    me.deck = [repo.get("ST01-004")] * 10

    power_before = me.leader.power
    do, _ = _do(overlay, "OP02-069", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    assert me.leader.power == power_before + 6000, \
        f"カウンターの +6000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.hand) == 2, f"手札が2枚になるようドローされていない: {len(me.hand)}"


def test_op02_069_death_wink_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +6000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("ST01-004"), sickness=False)
    me.characters = [friend]
    me.deck = [repo.get("ST01-004")] * 10

    do, _ = _do(overlay, "OP02-069", "counter")
    execute_effect(do[0], st, me, opp, None)  # power_pump のみ

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 6000, \
        "人間が選んだキャラに +6000 が反映されていない"


def test_op02_069_death_wink_trigger_bounce_cost_le7_ai():
    """トリガー: 相手のコスト7以下キャラ1枚を持ち主の手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=7)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-069", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    assert victim not in opp.characters, "相手コスト7以下キャラが手札に戻っていない"
    assert len(opp.hand) == 1, "戻した相手キャラが持ち主の手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP02-070 ニューカマーランド (STAGE): 【起動メイン】このステージをレストにできる：
#    自分のリーダーが「エンポリオ・イワンコフ」の場合、 カード1枚を引き、 自分の手札1枚を
#    捨てる。 その後、 自分の手札3枚までを捨てる。
# --------------------------------------------------------------------------- #
def test_op02_070_newkama_land_activate_main_with_ivankov_ai():
    """起動メイン (リーダーがイワンコフ): ステージレスト → 1ドロー1捨て + 手札3捨て (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, leader_id="OP02-049")  # エンポリオ・イワンコフ (LEADER)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP02-070"), sickness=False)
    me.stages = [stage]
    me.hand = [repo.get("ST01-004")] * 4  # 4 枚
    me.deck = [repo.get("ST01-004")] * 10

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-070"]
    assert len(opts) == 1, f"OP02-070 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain_choices(st, pick=[0])

    assert stage.rested is True, "起動メインコストでステージがレストされるべき"
    # +1 ドロー -1 捨て -3 捨て = net -3 → 4 - 3 = 1
    assert len(me.hand) == 1, \
        f"1ドロー1捨て + 手札3捨て の net が合わない: {len(me.hand)} (期待 1)"


def test_op02_070_newkama_land_activate_main_no_ivankov():
    """起動メイン: リーダーがイワンコフでなければ 条件不成立 → legal に出ない。"""
    # ⚠ 2026-08-05 是正: コロン後の条件は **効果のみ** を gate する (cardqa_op_02:
    #   「リーダーが「イワンコフ」ではない場合、この【起動メイン】効果を発動できますか？」
    #   → 「はい。 このカードをレストにしますが、 その後の効果では何も起きません」)。
    #   「条件不成立なら legal に出ない」 は行動の合法性ごと消す旧バグの固定だった。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, leader_id=BLUE_LEADER)  # イワンコフでない
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP02-070"), sickness=False)
    me.stages = [stage]
    me.hand = [repo.get("ST01-004")] * 4
    me.deck = [repo.get("ST01-004")] * 10

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-070"]
    assert len(opts) == 1, \
        "任意コストは条件不成立でも払えるので legal に残るべき (cardqa_op_02)"


# --------------------------------------------------------------------------- #
#  OP02-072 ゼット (LEADER): 【アタック時】ドン!!-4：相手のコスト3以下のキャラ1枚
#    までを、 KOする。 その後、 このリーダーは、 このターン中、 パワー+1000。
# --------------------------------------------------------------------------- #
def test_op02_072_z_leader_on_attack_ko_and_pump_ai():
    """アタック時 (ドン4支払い): 相手コスト3以下キャラを KO + 自リーダー +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, leader_id="OP02-072")
    me, opp = st.players[0], st.players[1]
    me.don_active = 4  # ドン-4 コスト用
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=3)
    opp.characters = [victim]

    do, eff = _do(overlay, "OP02-072", "on_attack")
    assert eff.get("cost", {}).get("pay_don") == 4, \
        "overlay の ドンコスト pay_don=4 が無い"
    power_before = me.leader.power
    for prim in do:
        execute_effect(prim, st, me, opp, me.leader)
    _drain_choices(st)

    assert victim not in opp.characters, "相手コスト3以下キャラが KO されていない"
    assert me.leader.power == power_before + 1000, \
        f"その後の 自リーダー +1000 が反映されていない: {me.leader.power}"


def test_op02_072_z_leader_on_attack_no_ko_target_still_pumps():
    """対象 (コスト3以下) が無くても「1枚まで」なので不発扱い → その後の +1000 は発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, leader_id="OP02-072")
    me, opp = st.players[0], st.players[1]
    me.don_active = 4
    big = InPlay.of(repo.get("OP02-062"), sickness=False)  # cost6 (>3) = 対象外
    opp.characters = [big]

    do, _ = _do(overlay, "OP02-072", "on_attack")
    power_before = me.leader.power
    for prim in do:
        execute_effect(prim, st, me, opp, me.leader)
    _drain_choices(st)

    assert big in opp.characters, "コスト3超のキャラが KO されてはいけない (対象外)"
    assert me.leader.power == power_before + 1000, \
        f"KO 対象が無くても その後の +1000 は発動するべき: {me.leader.power}"


def test_op02_072_z_leader_on_attack_human_ko_pick():
    """人間 + 相手コスト3以下キャラ 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, leader_id="OP02-072", human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 4
    a = InPlay.of(repo.get("OP01-016"), sickness=False)   # cost1
    b = InPlay.of(repo.get("ST01-004"), sickness=False)   # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP02-072", "on_attack")
    execute_effect(do[0], st, me, opp, me.leader)  # ko のみ

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP02-073 サディちゃん (CHARACTER): 【登場時】自分の手札から特徴《獄卒獣》を持つ
#    キャラカード1枚までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op02_073_sadi_on_play_summon_gokusotsu_ai():
    """登場時: 手札から《獄卒獣》キャラを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    minokoala = repo.get("OP02-086")  # ミノコアラ (インペルダウン/獄卒獣)
    assert "獄卒獣" in (minokoala.features or ()), "テスト前提: OP02-086 は 獄卒獣"
    me.hand = [minokoala]

    do, _ = _do(overlay, "OP02-073", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-073"), sickness=True))
    _drain_choices(st, pick=[0])

    assert any(c.card.card_id == "OP02-086" for c in me.characters), \
        "手札から《獄卒獣》キャラ (ミノコアラ) が登場していない"
    assert not any(c.card_id == "OP02-086" for c in me.hand), \
        "登場した《獄卒獣》キャラが手札に残っている"


def test_op02_073_sadi_on_play_human_play_pick():
    """人間 + 手札に《獄卒獣》複数 → 登場先を選ぶ play_from_hand_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-086"), repo.get("OP02-087")]  # 2 種の 獄卒獣

    do, _ = _do(overlay, "OP02-073", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP02-073"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[0])
    assert any(c.card.card_id in ("OP02-086", "OP02-087") for c in me.characters), \
        "人間が選んだ《獄卒獣》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP02-074 サルデス (CHARACTER): 自分の「ブルゴリ」は【ブロッカー】を得る。 (静的効果)
# --------------------------------------------------------------------------- #
def test_op02_074_sardes_static_grants_blocker_to_burugori():
    """静的効果: 自分の「ブルゴリ」に【ブロッカー】を付与する (evaluate_static_effects)。
    名前が「ブルゴリ」でないキャラには付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    sardes = InPlay.of(repo.get("OP02-074"), sickness=False)
    burugori = InPlay.of(repo.get("OP02-084"), sickness=False)  # ブルゴリ
    other = InPlay.of(repo.get("ST01-004"), sickness=False)     # 別名キャラ
    me.characters = [sardes, burugori, other]

    evaluate_static_effects(st, overlay)

    assert "ブロッカー" in burugori.static_granted_keywords, \
        "自分の「ブルゴリ」に ブロッカー が付与されていない"
    assert "ブロッカー" not in other.static_granted_keywords, \
        "「ブルゴリ」以外のキャラに ブロッカー が付与されてはいけない"
