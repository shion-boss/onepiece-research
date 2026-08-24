# -*- coding: utf-8 -*-
"""OP08 弾 (ビッグ・マム海賊団 / ペロスペローファミリー) 効果 回帰テスト
バックフィル (自動生成 wave 087):
OP08-062 / OP08-063 / OP08-064 / OP08-066 / OP08-067 / OP08-068 /
OP08-069 / OP08-070 / OP08-071 / OP08-073 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
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
    resolve_triggers,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_ko,
    trigger_on_self_don_returned_to_deck,
)

ROOT = Path(__file__).resolve().parent.parent

_BIGMOM_LEADER = "OP08-058"  # シャーロット・プリン (ビッグ・マム海賊団 leader)


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


def _state(repo, leader_id=_BIGMOM_LEADER, overlay=None, human_idx=None,
           opp_leader_id="OP01-001", turn_player_idx=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=turn_player_idx / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player_idx
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when):
    return [p for e in overlay.get(cid).effects if e["when"] == when for p in e["do"]]


def _drain(st, pick=0, guard=10):
    """pending_choice を pick を選び続けて解決しきる。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        cands = st.pending_choice.get("candidates")
        if cands is not None and len(cands) == 0:
            resolve_pending_choice(st, [])
        else:
            resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op08_wave087_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP08-062", "OP08-063", "OP08-064", "OP08-066", "OP08-067",
           "OP08-068", "OP08-069", "OP08-070", "OP08-071", "OP08-073"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP08-062 シャーロット・カタクリ (紫 CHARACTER cost2):
#    【起動メイン】このキャラをトラッシュに置くことができる：自分のリーダーが特徴
#      《ビッグ・マム海賊団》を持つ場合、自分の手札からコスト3以上でかつ、相手の場の
#      ドン‼の枚数以下のコストを持つ「シャーロット・カタクリ」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op08_062_activate_main_play_katakuri_ai():
    """起動メイン: 自身をトラッシュ + 手札のコスト条件を満たす「カタクリ」を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    katakuri = InPlay.of(repo.get("OP08-062"), sickness=False)
    me.characters = [katakuri]
    me.hand = [repo.get("OP08-063")]  # カタクリ cost6 (>=3)
    opp.don_active = 8  # 相手ドン 8 枚 → cost6 <= 8 で条件成立

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-062"]
    assert len(opts) == 1, f"OP08-062 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert any(c.card.card_id == "OP08-063" for c in me.characters), \
        f"手札の「カタクリ」が登場していない: {[c.card.card_id for c in me.characters]}"
    assert any(c.card_id == "OP08-062" for c in me.trash), \
        "自身 (コスト2 カタクリ) がトラッシュに置かれていない"


def test_op08_062_wrong_leader_not_legal():
    """negative: リーダーが《ビッグ・マム海賊団》でなければ 起動メインは legal に出ない。"""
    # ⚠ 2026-08-05 是正: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を
    #   **効果のみ** の gate とする。 任意コストは条件不成立でも支払える。
    #   一次情報 (cardqa_op_02): 「自分のリーダーが「エンポリオ・イワンコフ」ではない場合、
    #   この【起動メイン】効果を発動できますか？」 → 「はい、できます。 その場合、このカードを
    #   レストにしますが、 **その後の効果では何も起きません**」。
    #   → 「条件不成立なら legal に出ない」 は **行動の合法性ごと消す旧バグ** を固定していた。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, leader_id="OP01-001", overlay=overlay)  # 麦わら (非ビッグ・マム)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-062"), sickness=False)]
    me.hand = [repo.get("OP08-063")]
    opp.don_active = 8

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-062"]
    assert len(opts) == 1, (
        "任意コストは条件不成立でも払えるので legal に残るべき (公式: cardqa_op_02)"
    )


def test_op08_062_leader_feature_gate_in_overlay():
    """overlay の 発動条件に 自リーダー《ビッグ・マム海賊団》(leader_feature) がある。"""
    overlay = _overlay()
    eff = next(e for e in overlay.get("OP08-062").effects
               if e["when"] == "activate_main")
    assert _cond_of(eff).get("leader_feature") == "ビッグ・マム海賊団", \
        "OP08-062 に 自リーダー ビッグ・マム海賊団 条件が無い"


# --------------------------------------------------------------------------- #
#  OP08-063 シャーロット・カタクリ (紫 CHARACTER cost6):
#    【登場時】自分のライフの上から1枚を裏向きにできる：自分のドン‼デッキから
#      ドン‼1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op08_063_on_play_flip_life_add_active_don_ai():
    """【登場時】(ライフ1枚 裏向き) ドン‼1枚をアクティブで追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    # 2026-08-11: 表向きライフは per-card フラグ (life_face_up) で持つ  # 表向きライフ 2 → 1 枚 裏向きに できる
    me.life_face_up = [i < (2) for i in range(len(me.life))]
    me.don_active = 0
    me.don_remaining_in_deck = 10

    active_before = me.don_active
    faceup_before = me.face_up_life_count
    deck_before = me.don_remaining_in_deck
    for prim in _do(overlay, "OP08-063", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-063"), sickness=True))
    _drain(st)

    assert me.don_active == active_before + 1, \
        f"アクティブドンが1枚追加されていない: {me.don_active} (before {active_before})"
    assert me.face_up_life_count == faceup_before - 1, \
        f"ライフ1枚が裏向きになっていない: {me.face_up_life_count} (before {faceup_before})"
    assert me.don_remaining_in_deck == deck_before - 1, \
        "ドンデッキから1枚減っていない"


def test_op08_063_on_play_human_optional_cost_modal():
    """人間: 任意コスト (ライフ1枚裏向き) の optional_cost_confirm modal が立ち、
    [1] で承認 → ドン追加 が解決される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    # 2026-08-11: 表向きライフは per-card フラグ (life_face_up) で持つ
    me.life_face_up = [i < (2) for i in range(len(me.life))]
    me.don_active = 0

    execute_effect(_do(overlay, "OP08-063", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP08-063"), sickness=True))
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承認
    _drain(st)
    assert me.don_active == 1, "承認後 アクティブドンが1枚追加されていない"


# --------------------------------------------------------------------------- #
#  OP08-064 シャーロット・クラッカー (紫 CHARACTER cost4):
#    【起動メイン】【ターン1回】ドン‼-1：自分の手札から「ビスケット兵」1枚までを、登場。
# --------------------------------------------------------------------------- #
def test_op08_064_activate_main_play_biscuit_ai():
    """起動メイン: ドン‼-1、 手札の「ビスケット兵」を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-064"), sickness=False)]
    me.hand = [repo.get("OP08-072")]  # ビスケット兵
    me.don_active = 3

    don_before = me.don_active
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-064"]
    assert len(opts) == 1, f"OP08-064 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert any(c.card.card_id == "OP08-072" for c in me.characters), \
        f"「ビスケット兵」が登場していない: {[c.card.card_id for c in me.characters]}"
    assert me.don_active == don_before - 1, "ドン‼-1 が支払われていない"


def test_op08_064_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-064"), sickness=False)]
    me.hand = [repo.get("OP08-072"), repo.get("OP08-072")]
    me.don_active = 4

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP08-064"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP08-064"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op08_064_activate_main_human_play_pick():
    """人間 + 「ビスケット兵」複数 → play_from_hand_pick modal が立ち resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-064"), sickness=False)]
    me.hand = [repo.get("OP08-072"), repo.get("OP08-072")]
    me.don_active = 3

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-064"]
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("candidates", [])) == 2, \
        "候補 (ビスケット兵 2 枚) が 2 件でない"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card.card_id == "OP08-072" for c in me.characters), \
        "人間が選んだ「ビスケット兵」が登場していない"


# --------------------------------------------------------------------------- #
#  OP08-066 シャーロット・ブリュレ (紫 CHARACTER cost4):
#    【ブロッカー】【KO時】ドン‼デッキからドン‼1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op08_066_on_ko_add_rested_don_ai():
    """【KO時】ドンデッキからレストドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 0
    me.don_remaining_in_deck = 10

    rested_before = me.don_rested
    deck_before = me.don_remaining_in_deck
    trigger_on_ko(st, me, opp, repo.get("OP08-066"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    assert me.don_rested == rested_before + 1, \
        f"レストドンが1枚追加されていない: {me.don_rested} (before {rested_before})"
    assert me.don_remaining_in_deck == deck_before - 1, \
        "ドンデッキから1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP08-067 シャーロット・プリン (紫 CHARACTER cost3):
#    【自分のターン中】【ターン1回】自分の場のドン‼がドン‼デッキに戻された時、
#      ドン‼デッキからドン‼1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_op08_067_on_don_returned_add_rested_don_ai():
    """自分のターン中、 自分のドンがデッキに戻された時、 レストドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, turn_player_idx=0)  # 自分のターン
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-067"), sickness=False)]
    me.don_rested = 0
    me.don_remaining_in_deck = 10

    rested_before = me.don_rested
    trigger_on_self_don_returned_to_deck(st, me, opp, overlay)
    _drain(st)

    assert me.don_rested == rested_before + 1, \
        f"レストドンが1枚追加されていない: {me.don_rested} (before {rested_before})"


def test_op08_067_opp_turn_no_fire():
    """negative:【自分のターン中】限定 → 相手のターンでは発火しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, turn_player_idx=1)  # 相手のターン
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-067"), sickness=False)]
    me.don_rested = 0

    trigger_on_self_don_returned_to_deck(st, me, opp, overlay)
    _drain(st)

    assert me.don_rested == 0, "相手のターンではレストドンが追加されてはいけない"


# --------------------------------------------------------------------------- #
#  OP08-068 シャーロット・ペロスペロー (紫 CHARACTER cost3):
#    【KO時】ドン‼デッキからドン‼1枚までを、レストで追加する。
#    【トリガー】ドン‼-1：このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op08_068_on_ko_add_rested_don_ai():
    """【KO時】ドンデッキからレストドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 0
    me.don_remaining_in_deck = 10

    rested_before = me.don_rested
    trigger_on_ko(st, me, opp, repo.get("OP08-068"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    assert me.don_rested == rested_before + 1, \
        f"レストドンが1枚追加されていない: {me.don_rested} (before {rested_before})"


def test_op08_068_has_trigger_play_self():
    """overlay に【トリガー】(ドン‼-1 で自身登場、 play_self) が登録されている。"""
    overlay = _overlay()
    trig = next((e for e in overlay.get("OP08-068").effects
                 if e["when"] == "trigger"), None)
    assert trig is not None, "OP08-068 の【トリガー】効果が無い"
    assert any("play_self" in p for p in trig["do"]), \
        "【トリガー】に play_self (自身登場) が無い"


# --------------------------------------------------------------------------- #
#  OP08-069 シャーロット・リンリン (紫 CHARACTER cost9):
#    【登場時】ドン‼-1,自分の手札1枚を捨てることができる：自分のデッキの上から1枚まで
#      を、ライフの上に加える。その後、相手のコスト6以下のキャラ1枚までを、相手のライフ
#      の上か下に表向きで加える。
# --------------------------------------------------------------------------- #
def test_op08_069_on_play_put_life_and_chara_to_opp_life_ai():
    """【登場時】(ドン‼-1 + 手札1捨て) デッキ上をライフへ + 相手コスト6以下キャラを
    相手ライフへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.hand = [repo.get("OP01-016")]  # 捨てる 1 枚
    me.deck = [repo.get("OP01-013")] * 10
    me.life = [repo.get("OP01-013")] * 2
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 <= 6
    opp.characters = [victim]

    life_before = len(me.life)
    opp_char_before = len(opp.characters)
    opp_life_before = len(opp.life)
    for prim in _do(overlay, "OP08-069", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-069"), sickness=True))
    _drain(st)

    assert len(me.life) == life_before + 1, \
        f"デッキ上1枚が自ライフに加わっていない: {len(me.life)} (before {life_before})"
    assert len(opp.characters) == opp_char_before - 1, \
        "相手コスト6以下キャラが場から取り除かれていない"
    assert len(opp.life) == opp_life_before + 1, \
        f"相手キャラが相手ライフに加わっていない: {len(opp.life)} (before {opp_life_before})"


def test_op08_069_on_play_human_optional_cost_modal():
    """人間: 任意コスト (ドン‼-1 + 手札1捨て) の optional_cost_confirm modal が立ち、
    [1] で承認 → 効果が解決される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.hand = [repo.get("OP01-016")]
    me.deck = [repo.get("OP01-013")] * 10
    me.life = [repo.get("OP01-013")] * 2
    opp.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]

    life_before = len(me.life)
    execute_effect(_do(overlay, "OP08-069", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP08-069"), sickness=True))
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承認
    _drain(st)
    assert len(me.life) == life_before + 1, \
        "承認後 デッキ上1枚が自ライフに加わっていない"


# --------------------------------------------------------------------------- #
#  OP08-070 タマゴ男爵 (紫 CHARACTER cost3):
#    【ブロッカー】【KO時】ドン‼-1：自分の手札からコスト5以下の「ヒヨコ子爵」1枚まで
#      を、登場させる。
# --------------------------------------------------------------------------- #
def test_op08_070_on_ko_play_hiyoko_ai():
    """【KO時】(ドン‼-1) 手札からコスト5以下の「ヒヨコ子爵」を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.hand = [repo.get("OP08-073")]  # ヒヨコ子爵 cost5 <= 5

    don_before = me.don_active
    trigger_on_ko(st, me, opp, repo.get("OP08-070"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    assert any(c.card.card_id == "OP08-073" for c in me.characters), \
        f"「ヒヨコ子爵」が登場していない: {[c.card.card_id for c in me.characters]}"
    assert me.don_active == don_before - 1, "ドン‼-1 が支払われていない"


def test_op08_070_on_ko_human_optional_cost_modal():
    """人間: 【KO時】任意コスト (ドン‼-1) の optional_cost_confirm modal が立ち、
    [1] 承認 → ヒヨコ子爵 が登場する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.hand = [repo.get("OP08-073")]

    trigger_on_ko(st, me, opp, repo.get("OP08-070"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])
    _drain(st)
    assert any(c.card.card_id == "OP08-073" for c in me.characters), \
        "承認後「ヒヨコ子爵」が登場していない"


# --------------------------------------------------------------------------- #
#  OP08-071 ニワトリ伯爵 (紫 CHARACTER cost6):
#    【相手のターン中】【KO時】ドン‼-1：自分のデッキからコスト4以下の「タマゴ男爵」
#      1枚までを、登場させる。その後、デッキをシャッフルする。
# --------------------------------------------------------------------------- #
def test_op08_071_on_ko_summon_tamago_opp_turn_ai():
    """【相手のターン中】【KO時】(ドン‼-1) デッキからコスト4以下「タマゴ男爵」を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, turn_player_idx=1)  # 相手のターン
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.deck = [repo.get("OP08-070")] + [repo.get("OP01-013")] * 10  # タマゴ男爵 cost3

    don_before = me.don_active
    trigger_on_ko(st, me, opp, repo.get("OP08-071"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    assert any(c.card.card_id == "OP08-070" for c in me.characters), \
        f"デッキから「タマゴ男爵」が登場していない: {[c.card.card_id for c in me.characters]}"
    assert me.don_active == don_before - 1, "ドン‼-1 が支払われていない"


def test_op08_071_self_turn_no_fire():
    """negative:【相手のターン中】限定 → 自分のターンでは発火しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, turn_player_idx=0)  # 自分のターン
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.deck = [repo.get("OP08-070")] + [repo.get("OP01-013")] * 10

    trigger_on_ko(st, me, opp, repo.get("OP08-071"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    assert not any(c.card.card_id == "OP08-070" for c in me.characters), \
        "自分のターンでは「タマゴ男爵」が登場してはいけない"


# --------------------------------------------------------------------------- #
#  OP08-073 ヒヨコ子爵 (紫 CHARACTER cost5):
#    【相手のターン中】【KO時】ドン‼-1：自分のデッキからコスト6以下の「ニワトリ伯爵」
#      1枚までを、登場させる。その後、デッキをシャッフルする。
# --------------------------------------------------------------------------- #
def test_op08_073_on_ko_summon_niwatori_opp_turn_ai():
    """【相手のターン中】【KO時】(ドン‼-1) デッキからコスト6以下「ニワトリ伯爵」を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay=overlay, turn_player_idx=1)  # 相手のターン
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.deck = [repo.get("OP08-071")] + [repo.get("OP01-013")] * 10  # ニワトリ伯爵 cost6

    don_before = me.don_active
    trigger_on_ko(st, me, opp, repo.get("OP08-073"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    assert any(c.card.card_id == "OP08-071" for c in me.characters), \
        f"デッキから「ニワトリ伯爵」が登場していない: {[c.card.card_id for c in me.characters]}"
    assert me.don_active == don_before - 1, "ドン‼-1 が支払われていない"


def test_op08_073_opp_turn_condition_in_overlay():
    """overlay の 発動条件に【相手のターン中】(opp_turn) がある。"""
    overlay = _overlay()
    eff = next(e for e in overlay.get("OP08-073").effects if e["when"] == "on_ko")
    conds = eff.get("conditions", [])
    assert any(c.get("opp_turn") for c in conds), \
        "OP08-073 の on_ko に opp_turn (相手のターン中) 条件が無い"
