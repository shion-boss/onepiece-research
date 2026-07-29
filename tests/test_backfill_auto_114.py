# -*- coding: utf-8 -*-
"""OP11 弾 (紫 ビッグ・マム海賊団 / インペルダウン 系) 効果 回帰テスト
バックフィル (自動生成 wave 114):
OP11-067 / OP11-069 / OP11-071 / OP11-072 / OP11-073 /
OP11-074 / OP11-075 / OP11-076 / OP11-079 / OP11-080 の 10 枚。

目的 (= test_backfill_auto_001.py と同一方針):
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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の do リストを返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


# 各テストで使う定番カード (BM 系 leader / インペルダウン leader 等)
_BM_LEADER = "OP11-062"       # シャーロット・カタクリ (紫 / ビッグ・マム海賊団)
_IMPEL_LEADER = "EB01-021"    # ハンニャバル (青/紫 / インペルダウン)
_ROBIN_LEADER = "OP09-062"    # ニコ・ロビン (紫/黄)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op11_wave114_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP11-067", "OP11-069", "OP11-071", "OP11-072", "OP11-073",
           "OP11-074", "OP11-075", "OP11-076", "OP11-079", "OP11-080"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP11-067 シャーロット・カタクリ:
#    【自分のターン終了時】自分のコスト3以上《ビッグ・マム海賊団》キャラ2枚までを
#    アクティブにする。 その後、 ドンデッキからドン1枚までをレストで追加。
# --------------------------------------------------------------------------- #
def test_op11_067_katakuri_end_of_turn_untap_and_don_ai():
    """AI: レストの BM(コスト3+) キャラ2体をアクティブに + レストドン+1 (ドンデッキ-1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)  # 自リーダー = BM
    me, opp = st.players[0], st.players[1]
    # BM コスト3以上のキャラ 2 体 (どちらもレスト状態)
    c1 = InPlay.of(repo.get("EB03-033"), sickness=False)   # ブリュレ cost5 BM
    c2 = InPlay.of(repo.get("EB03-035"), sickness=False)   # プリン cost4 BM
    c1.rested = True
    c2.rested = True
    me.characters = [c1, c2]
    src = InPlay.of(repo.get("OP11-067"), sickness=False)

    don_rested_before = me.don_rested
    deck_don_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP11-067", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp, src)

    assert c1.rested is False and c2.rested is False, \
        "ターン終了時に BM(コスト3+) キャラ 2 体がアクティブになっていない"
    assert me.don_rested == don_rested_before + 1, \
        f"レストドン+1 が反映されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキから 1 枚供給されていない"


# --------------------------------------------------------------------------- #
#  OP11-069 シャーロット・ブリュレ:
#    【登場時】自分のライフ上1枚を手札に加えられる：自リーダーが BM なら
#    ドンデッキからドン1枚までをアクティブで追加。
# --------------------------------------------------------------------------- #
def test_op11_069_brulee_on_play_ai():
    """AI: 任意コスト (ライフ→手札) を払い、 ドン+1 (アクティブ) を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3

    life_before = len(me.life)
    hand_before = len(me.hand)
    don_active_before = me.don_active
    do, _ = _do(overlay, "OP11-069", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-069"), sickness=True))

    assert len(me.life) == life_before - 1, "ライフ 1 枚が手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "手札が 1 枚増えていない"
    assert me.don_active == don_active_before + 1, \
        f"アクティブドン+1 が反映されていない: {me.don_active}"


def test_op11_069_brulee_on_play_human_optional_confirm():
    """人間: 任意コストの optional_cost_confirm modal が立ち、 承諾で
    ライフ→手札 + ドン+1 を実行できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    src = InPlay.of(repo.get("OP11-069"), sickness=True)
    me.characters = [src]  # self_inplay を解決可能にするため場に置く

    life_before = len(me.life)
    hand_before = len(me.hand)
    don_active_before = me.don_active
    do, _ = _do(overlay, "OP11-069", "on_play")
    execute_effect(do[0], st, me, opp, src)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    assert st.pending_choice is None, "解決後も modal が残る"
    assert len(me.life) == life_before - 1, "承諾後 ライフ 1 枚が手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "承諾後 手札が 1 枚増えていない"
    assert me.don_active == don_active_before + 1, "承諾後 アクティブドン+1 が無い"


# --------------------------------------------------------------------------- #
#  OP11-071 シャーロット・ペロスペロー:
#    【起動メイン】【ターン1回】手札1枚を捨てられる：コスト宣言 → 相手デッキ上公開、
#    一致なら 1 ドロー + ドンデッキからドン1枚までをアクティブで追加。
# --------------------------------------------------------------------------- #
def test_op11_071_perospero_activate_main_ai():
    """AI: 手札 1 枚を捨てて宣言 → 一致 (相手デッキ全コスト同一) で 1 ドロー + ドン+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP11-071"), sickness=False)
    me.characters = [src]
    me.hand = [repo.get("OP01-016"), repo.get("OP01-013")]  # 捨てる用 2 枚
    me.deck = [repo.get("OP01-013")] * 10
    opp.deck = [repo.get("OP01-013")] * 10  # 全コスト 2 = 宣言確実に一致

    don_active_before = me.don_active
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-071"]
    assert len(opts) == 1, f"OP11-071 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.don_active == don_active_before + 1, \
        f"宣言一致で アクティブドン+1 が無い: {me.don_active}"
    assert len(me.deck) == deck_before - 1, "1 ドロー (デッキ-1) が起きていない"
    assert len(me.trash) == trash_before + 1, "手札 1 枚を捨てるコストが払われていない"


def test_op11_071_perospero_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP11-071"), sickness=False)
    me.characters = [src]
    me.hand = [repo.get("OP01-016"), repo.get("OP01-013")]
    me.deck = [repo.get("OP01-013")] * 10
    opp.deck = [repo.get("OP01-013")] * 10

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-071"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-071"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op11_071_perospero_activate_main_human_optional_confirm():
    """人間: 任意コスト (手札捨て) の optional_cost_confirm modal が立ち、
    承諾で ドン+1 まで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP11-071"), sickness=False)
    me.characters = [src]
    me.hand = [repo.get("OP01-016"), repo.get("OP01-013")]
    me.deck = [repo.get("OP01-013")] * 10
    opp.deck = [repo.get("OP01-013")] * 10

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-071"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    don_active_before = me.don_active
    trash_before = len(me.trash)
    resolve_pending_choice(st, [1])  # 承諾
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1
    assert me.don_active == don_active_before + 1, "承諾後 アクティブドン+1 が無い"
    assert len(me.trash) == trash_before + 1, "承諾後 手札 1 枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  OP11-072 シャーロット・モンドール:
#    【起動メイン】【ターン1回】ドン-1, 自レスト：相手はトラッシュ2枚をデッキ下へ、
#    その後 自分のライフ上1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op11_072_mondore_activate_main_ai():
    """AI: 相手トラッシュ 2 枚をデッキ下へ + 自ライフ 1 枚を手札へ (自身レスト + ドン-1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP11-072"), sickness=False)
    me.characters = [src]
    me.don_active = 2                     # ドン-1 コスト用
    me.life = [repo.get("OP01-013")] * 2
    opp.trash = [repo.get("OP01-013"), repo.get("OP01-016"), repo.get("OP01-013")]

    opp_trash_before = len(opp.trash)
    opp_deck_before = len(opp.deck)
    hand_before = len(me.hand)
    life_before = len(me.life)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-072"]
    assert len(opts) == 1, f"OP11-072 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert len(opp.trash) == opp_trash_before - 2, "相手トラッシュ 2 枚が動いていない"
    assert len(opp.deck) == opp_deck_before + 2, "相手デッキ下に 2 枚戻っていない"
    assert len(me.hand) == hand_before + 1, "自ライフ 1 枚が手札に加わっていない"
    assert len(me.life) == life_before - 1, "自ライフが 1 枚減っていない"
    assert src.rested is True, "起動メインコストで自身がレストされるべき"


# --------------------------------------------------------------------------- #
#  OP11-073 シャーロット・リンリン:
#    自リーダーが BM なら【速攻】。
#    【相手のアタック時】【ターン1回】ドン-5：コスト宣言 → 相手デッキ上公開、
#    一致なら自リーダー1枚までを このターン中 +2000。
# --------------------------------------------------------------------------- #
def test_op11_073_linlin_gains_rush_when_bm_leader():
    """自リーダーが BM のとき、 このキャラは【速攻】を得る (on_attached_don 経由)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP11-073"), sickness=False)
    me.characters = [src]

    do, _ = _do(overlay, "OP11-073", "on_attached_don")
    for prim in do:
        execute_effect(prim, st, me, opp, src)

    assert "速攻" in src.granted_keywords, \
        f"BM リーダー時に【速攻】が付与されていない: {src.granted_keywords}"


def test_op11_073_linlin_opp_attack_declare_leader_pump_ai():
    """【相手のアタック時】宣言一致 → 自リーダー +2000 (このターン中)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP11-073"), sickness=False)
    me.characters = [src]
    opp.deck = [repo.get("OP01-013")] * 10  # 全コスト同一 → 宣言確実に一致

    leader_power_before = me.leader.power
    do, _ = _do(overlay, "OP11-073", "opp_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, src)

    assert me.leader.power == leader_power_before + 2000, \
        f"宣言一致で自リーダー +2000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP11-074 シュトロイゼン:
#    【起動メイン】【ターン1回】ドン-1, 自レスト：コスト宣言 → 相手デッキ上公開、
#    一致なら相手コスト4以下キャラ1枚までをレストにする。
# --------------------------------------------------------------------------- #
def test_op11_074_streusen_activate_main_rest_opp_ai():
    """AI: 宣言一致 → 相手コスト4以下キャラ 1 体をレストにする (自身レスト + ドン-1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP11-074"), sickness=False)
    me.characters = [src]
    me.don_active = 2
    opp.deck = [repo.get("OP01-013")] * 10
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 (<=4)
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-074"]
    assert len(opts) == 1, f"OP11-074 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert victim.rested is True, "宣言一致で相手コスト4以下キャラがレストされていない"
    assert src.rested is True, "起動メインコストで自身がレストされるべき"


# --------------------------------------------------------------------------- #
#  OP11-075 ハグワール・D・サウロ:
#    【登場時】自リーダーが「ニコ・ロビン」で 場のドン7枚以上なら 2 ドロー。
#    【トリガー】このカードの【登場時】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op11_075_saul_on_play_draw_when_conditions_met():
    """条件成立 (リーダー=ニコ・ロビン & ドン7以上) → 2 ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROBIN_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 7
    src = InPlay.of(repo.get("OP11-075"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)
    assert len(me.hand) == hand_before + 2, \
        f"条件成立時に 2 ドローしていない: +{len(me.hand) - hand_before}"


def test_op11_075_saul_on_play_no_draw_when_wrong_leader():
    """リーダーが「ニコ・ロビン」でなければ ドローしない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 非 ニコ・ロビン
    me, opp = st.players[0], st.players[1]
    me.don_active = 7
    src = InPlay.of(repo.get("OP11-075"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)
    assert len(me.hand) == hand_before, "条件不成立 (リーダー違い) なのにドローした"


def test_op11_075_saul_on_play_no_draw_when_few_don():
    """場のドンが 7 枚未満なら ドローしない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROBIN_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    src = InPlay.of(repo.get("OP11-075"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)
    assert len(me.hand) == hand_before, "条件不成立 (ドン不足) なのにドローした"


def test_op11_075_saul_trigger_refires_on_play():
    """【トリガー】は自身の【登場時】効果を再発動する (条件成立で 2 ドロー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _ROBIN_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 7
    src = InPlay.of(repo.get("OP11-075"), sickness=True)

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP11-075", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, src)
    assert len(me.hand) == hand_before + 2, \
        f"トリガーで【登場時】が再発動せず 2 ドローしていない: +{len(me.hand) - hand_before}"


# --------------------------------------------------------------------------- #
#  OP11-076 ハンニャバル:
#    【ブロッカー】【登場時】自リーダーが インペルダウン なら、 手札から
#    コスト3以下《インペルダウン》キャラ1枚までを登場させる。
# --------------------------------------------------------------------------- #
def test_op11_076_hannyabaru_on_play_play_from_hand_ai():
    """AI: 手札からコスト3以下 インペルダウン キャラ 1 体を登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # バニラ (追加登場チェーンなし) の インペルダウン cost1 を 2 枚
    me.hand = [repo.get("OP16-023"), repo.get("OP02-084")]
    src = InPlay.of(repo.get("OP11-076"), sickness=True)
    me.characters = [src]

    chars_before = len(me.characters)
    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)

    assert len(me.characters) == chars_before + 1, \
        "手札から インペルダウン キャラ 1 体が登場していない"
    assert len(me.hand) == hand_before - 1, "登場コストで手札が 1 枚減っていない"


def test_op11_076_hannyabaru_on_play_human_pick():
    """人間 + 手札候補 2 枚 (>limit) → play_from_hand_pick modal が立ち、
    選んだ 1 体を登場させられる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _IMPEL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP16-023"), repo.get("OP02-084")]
    src = InPlay.of(repo.get("OP11-076"), sickness=True)
    me.characters = [src]

    trigger_on_play(st, me, opp, src, overlay)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"登場候補が 2 枚でない: {len(cands)}"

    chars_before = len(me.characters)
    resolve_pending_choice(st, [0])  # 1 体目を選択して登場
    assert st.pending_choice is None, "解決後も modal が残る"
    assert len(me.characters) == chars_before + 1, \
        "人間が選んだ インペルダウン キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP11-079 男の勝負に…!!!薄っぺらい援護などするな!!!! (EVENT):
#    【カウンター】コスト宣言 → 相手デッキ上公開、 一致なら自リーダー/キャラ1枚までを
#    このバトル中 +5000。 【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op11_079_counter_declare_pump_ai():
    """【カウンター】宣言一致 → 自リーダー (AI 自動選択) を +5000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.deck = [repo.get("OP01-013")] * 10  # 全コスト同一 → 宣言確実に一致
    ev = InPlay.of(repo.get("OP11-079"), sickness=False)

    leader_power_before = me.leader.power
    do, _ = _do(overlay, "OP11-079", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, ev)

    assert me.leader.power == leader_power_before + 5000, \
        f"宣言一致で自リーダー +5000 が反映されていない: {me.leader.power}"


def test_op11_079_trigger_draw():
    """【トリガー】カード 1 枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP11-079", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, InPlay.of(repo.get("OP11-079")))

    assert len(me.hand) == hand_before + 1, "トリガーで 1 ドローしていない"
    assert len(me.deck) == deck_before - 1, "デッキが 1 枚減っていない"


# --------------------------------------------------------------------------- #
#  OP11-080 ギア2 (EVENT):
#    【メイン】自ドン2枚レスト：自リーダーが青を含むなら ドンデッキからドン1枚までを
#    レストで追加。 【カウンター】自リーダー1枚までを このバトル中 +3000。
# --------------------------------------------------------------------------- #
def test_op11_080_gear2_main_add_rested_don():
    """【メイン】effect: ドンデッキからレストドン+1 (ドンデッキ-1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _IMPEL_LEADER, overlay)  # 青/紫 = 青を含む
    me, opp = st.players[0], st.players[1]

    don_rested_before = me.don_rested
    deck_don_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP11-080", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, InPlay.of(repo.get("OP11-080")))

    assert me.don_rested == don_rested_before + 1, \
        f"レストドン+1 が反映されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキから 1 枚供給されていない"


def test_op11_080_gear2_counter_leader_pump():
    """【カウンター】自リーダー +3000 (このバトル中)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _IMPEL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    leader_power_before = me.leader.power
    do, _ = _do(overlay, "OP11-080", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, InPlay.of(repo.get("OP11-080")))

    assert me.leader.power == leader_power_before + 3000, \
        f"カウンターで自リーダー +3000 が反映されていない: {me.leader.power}"
