# -*- coding: utf-8 -*-
"""OP04 弾 効果 回帰テスト バックフィル (自動生成 wave 051):
OP04-081 / OP04-082 / OP04-084 / OP04-085 / OP04-088 / OP04-090 /
OP04-091 / OP04-092 / OP04-093 / OP04-094 の 10 枚 (黒 ドレスローザ / CP 系)。

目的 (= test_backfill_auto_001〜050.py と同一方針):
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
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_REBECCA = "OP04-039"   # レベッカ (青/黒、 特徴 ドレスローザ)
_OPP_COST1 = "EB04-002"        # ジュエリー・ボニー cost1
_CP_COST1 = "EB04-042"         # アルファ CP8 cost1 (OP04-084 の search 対象)
_DRESSROSA_CHAR = "PRB02-014"  # サボ ドレスローザ/革命軍 cost6 (OP04-092/093 対象)
_OPP_COST4 = "PRB02-001"       # コビー cost4
_OPP_COST5 = "PRB02-011"       # ドフラミンゴ cost5


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
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
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _am(st, me, overlay, cid):
    """指定 card_id の legal な起動メイン (src, eff) を返す (無ければ空 list)。"""
    return [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == cid]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave51_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP04-081", "OP04-082", "OP04-084", "OP04-085", "OP04-088",
           "OP04-090", "OP04-091", "OP04-092", "OP04-093", "OP04-094"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP04-081 キャベンディッシュ (CHARACTER 黒 cost5):
#    【アタック時】自分のリーダーをレストにできる：相手のコスト1以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op04_081_cavendish_attack_ko_ai():
    """アタック時: 自リーダーをレスト (任意コスト) → 相手コスト1以下を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = False
    victim = InPlay.of(repo.get(_OPP_COST1), sickness=False)  # cost1
    opp.characters = [victim]

    do, _ = _do(overlay, "OP04-081", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-081"), sickness=False))

    assert victim not in opp.characters, "相手コスト1以下キャラが KO されていない"
    assert me.leader.rested is True, "任意コストで自リーダーがレストされるべき"


def test_op04_081_cavendish_attack_ko_human_confirm_and_pick():
    """人間: 任意コスト確認 modal → 承諾 → 相手コスト1以下 target_pick で 1 枚 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = False
    a = InPlay.of(repo.get(_OPP_COST1), sickness=False)   # cost1
    b = InPlay.of(repo.get(_CP_COST1), sickness=False)    # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP04-081", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-081"), sickness=False))

    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)

    assert st.pending_choice is not None, "承諾後に KO の target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "ko", "primitive_kind が ko でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert me.leader.rested is True, "承諾後 自リーダーがレストされるべき"


# --------------------------------------------------------------------------- #
#  OP04-082 キュロス (CHARACTER 黒 cost3):
#    KOされる場合、代わりに自リーダー/「コリーダコロシアム」をレストにできる (replace_ko)
#    【登場時】リーダー「レベッカ」なら 相手コスト1以下1枚KO + デッキ上1枚トラッシュ
# --------------------------------------------------------------------------- #
def test_op04_082_kyros_replace_ko_rest_leader_ai():
    """KO 置換: 自リーダーをレストにして KO を代替し、 キュロスは場に残る (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kyros = InPlay.of(repo.get("OP04-082"), sickness=False)
    me.characters = [kyros]
    me.leader.rested = False

    replaced = try_replace_ko(
        st, me, opp, kyros, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "リーダーをレストできるのに KO が置換されていない"
    assert kyros in me.characters, "置換成立時 キュロスは場に残るべき"
    assert me.leader.rested is True, "置換コストで自リーダーがレストされるべき"


def test_op04_082_kyros_on_play_rebecca_ko_and_mill_ai():
    """登場時 (リーダー「レベッカ」): 相手コスト1以下を KO + デッキ上1枚トラッシュ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REBECCA, overlay)  # レベッカ leader → 条件成立
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_COST1), sickness=False)
    opp.characters = [victim]
    me.deck = [repo.get("ST01-004")] * 10

    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP04-082", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-082"), sickness=True))

    assert victim not in opp.characters, "登場時 相手コスト1以下が KO されていない"
    assert len(me.trash) == trash_before + 1, "デッキ上1枚がトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP04-084 ステューシー (CHARACTER 黒 cost2):
#    【登場時】デッキ上3枚を見て「ステューシー」以外の CP 特徴 コスト2以下を1枚登場
# --------------------------------------------------------------------------- #
def test_op04_084_stussy_on_play_search_play_ai():
    """登場時: デッキ上3枚から CP コスト2以下キャラを1枚登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_CP_COST1)] + [repo.get("ST01-004")] * 10

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP04-084", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-084"), sickness=True))

    assert len(me.characters) == chars_before + 1, "CP キャラが登場していない"
    assert any(c.card.card_id == _CP_COST1 for c in me.characters), \
        "登場したのが CP コスト2以下キャラでない"


def test_op04_084_stussy_on_play_search_human_pick():
    """人間: デッキ上3枚に該当キャラあり → search_top_n modal が立ち resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_CP_COST1)] + [repo.get("ST01-004")] * 10

    do, _ = _do(overlay, "OP04-084", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP04-084"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id == _CP_COST1 for c in me.characters), \
        "人間が選んだ CP キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP04-085 スレイマン (CHARACTER 黒 cost3):
#    【登場時】/【アタック時】リーダー特徴《ドレスローザ》なら 相手キャラ1枚 コスト-2 + デッキ上1枚トラッシュ
# --------------------------------------------------------------------------- #
def test_op04_085_suleiman_on_play_cost_minus_and_mill_ai():
    """登場時 (ドレスローザ leader): 相手キャラ1枚 コスト-2 + デッキ上1枚トラッシュ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REBECCA, overlay)  # ドレスローザ leader
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_COST5), sickness=False)  # cost5
    opp.characters = [victim]
    me.deck = [repo.get("ST01-004")] * 10

    cost_before = victim.base_cost
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP04-085", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-085"), sickness=True))

    assert victim.base_cost == max(0, cost_before - 2), \
        f"相手キャラのコスト-2 が反映されていない: {cost_before} -> {victim.base_cost}"
    assert len(me.trash) == trash_before + 1, "デッキ上1枚がトラッシュに置かれていない"


def test_op04_085_suleiman_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → cost_minus target_pick modal → resolve で 1 枚 -2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REBECCA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_COST5), sickness=False)  # cost5
    b = InPlay.of(repo.get(_OPP_COST4), sickness=False)  # cost4
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP04-085", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP04-085"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で cost_minus modal が立たない"
    assert st.pending_choice.get("primitive_kind") == "cost_minus", \
        "primitive_kind が cost_minus でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.base_cost
    resolve_pending_choice(st, [a_idx])
    assert a.base_cost == max(0, a_before - 2), \
        f"人間 resolve で コスト-2 が適用されていない: {a_before} -> {a.base_cost}"
    assert b.base_cost == repo.get(_OPP_COST4).cost, \
        "選ばなかったキャラにコスト減が乗っている"


# --------------------------------------------------------------------------- #
#  OP04-088 ハイルディン (CHARACTER 黒 cost6):
#    【起動メイン】自リーダー1枚をレストにできる：相手キャラ1枚 コスト-4
# --------------------------------------------------------------------------- #
def test_op04_088_hajrudin_activate_main_cost_minus_ai():
    """起動メイン: 自リーダーをレスト (コスト) → 相手キャラ1枚 コスト-4 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hajrudin = InPlay.of(repo.get("OP04-088"), sickness=False)
    me.characters = [hajrudin]
    me.leader.rested = False
    victim = InPlay.of(repo.get(_OPP_COST5), sickness=False)  # cost5
    opp.characters = [victim]

    cost_before = victim.base_cost
    opts = _am(st, me, overlay, "OP04-088")
    assert len(opts) == 1, f"OP04-088 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.leader.rested is True, "起動メインコストで自リーダーがレストされるべき"
    assert victim.base_cost == max(0, cost_before - 4), \
        f"相手キャラのコスト-4 が反映されていない: {cost_before} -> {victim.base_cost}"


# --------------------------------------------------------------------------- #
#  OP04-090 モンキー・D・ルフィ (CHARACTER 黒 cost7):
#    常在: アクティブのキャラにもアタックできる
#    【起動メイン】【ターン1回】トラッシュ7枚をデッキ下に戻す：自身をアクティブに (次のリフレッシュで起きない)
# --------------------------------------------------------------------------- #
def test_op04_090_luffy_static_attack_active():
    """常在効果: このキャラは「アクティブアタック可」キーワードを得ている。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP04-090"), sickness=False)
    me.characters = [luffy]

    evaluate_static_effects(st, overlay)
    granted = luffy.granted_keywords | luffy.static_granted_keywords
    assert "アクティブアタック可" in granted, \
        f"常在の アクティブアタック可 付与が反映されていない: {granted}"


def test_op04_090_luffy_activate_main_untap_ai():
    """起動メイン: トラッシュ7枚をデッキ下に戻し (コスト) → 自身をアクティブに (AI 自動)。
    ⇒ 自身のレストが解除され、 トラッシュ-7 / デッキ+7、 次リフレッシュ休みフラグが立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP04-090"), sickness=False)
    luffy.rested = True  # アタック後の想定 (レスト状態)
    me.characters = [luffy]
    me.trash = [repo.get("ST01-004")] * 8

    trash_before = len(me.trash)
    deck_before = len(me.deck)
    opts = _am(st, me, overlay, "OP04-090")
    assert len(opts) == 1, f"OP04-090 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert luffy.rested is False, "起動メインで自身がアクティブにならない"
    assert len(me.trash) == trash_before - 7, "コストでトラッシュ7枚が戻されていない"
    assert len(me.deck) == deck_before + 7, "戻した7枚がデッキ下に加わっていない"
    assert luffy.stay_rested_next_refresh is True, \
        "「次のリフレッシュで起きない」フラグが立っていない"


# --------------------------------------------------------------------------- #
#  OP04-091 レオ (CHARACTER 黒 cost1):
#    【登場時】自リーダー1枚をレストにできる：リーダー特徴《ドレスローザ》なら 相手コスト1以下1枚KO
# --------------------------------------------------------------------------- #
def test_op04_091_leo_on_play_ko_ai():
    """登場時 (ドレスローザ leader): 自リーダーをレスト (任意コスト) → 相手コスト1以下 KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REBECCA, overlay)  # ドレスローザ leader
    me, opp = st.players[0], st.players[1]
    me.leader.rested = False
    victim = InPlay.of(repo.get(_OPP_COST1), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP04-091", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-091"), sickness=True))

    assert victim not in opp.characters, "相手コスト1以下キャラが KO されていない"
    assert me.leader.rested is True, "任意コストで自リーダーがレストされるべき"


def test_op04_091_leo_on_play_human_optional_confirm():
    """人間: 任意コスト確認 modal が立ち、 承諾するとコスト支払い (自リーダーレスト) に進む。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REBECCA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = False
    victim = InPlay.of(repo.get(_OPP_COST1), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP04-091", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP04-091"), sickness=True))

    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)

    # 承諾後、 条件成立 (ドレスローザ) で KO の target_pick modal が立つ
    assert st.pending_choice is not None, "承諾後に KO の target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "ko", "primitive_kind が ko でない"
    cands = st.pending_choice.get("candidates", [])
    v_idx = next(i for i, c in enumerate(cands) if c["iid"] == victim.instance_id)
    resolve_pending_choice(st, [v_idx])
    _drain(st)
    assert me.leader.rested is True, "承諾後 自リーダーがレストされるべき"
    assert victim not in opp.characters, "承諾後 相手コスト1以下が KO されていない"


# --------------------------------------------------------------------------- #
#  OP04-092 レベッカ (CHARACTER 黒 cost1):
#    【登場時】デッキ上3枚を見て「レベッカ」以外の特徴《ドレスローザ》1枚を手札へ
# --------------------------------------------------------------------------- #
def test_op04_092_rebecca_on_play_search_hand_ai():
    """登場時: デッキ上3枚から ドレスローザ カード1枚を手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_DRESSROSA_CHAR)] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "OP04-092", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-092"), sickness=True))

    assert any(c.card_id == _DRESSROSA_CHAR for c in me.hand), \
        "ドレスローザ カードが手札に加わっていない"


def test_op04_092_rebecca_on_play_search_human_pick():
    """人間: デッキ上3枚に該当カードあり → search_top_n modal が立ち resolve で手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_DRESSROSA_CHAR)] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "OP04-092", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP04-092"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card_id == _DRESSROSA_CHAR for c in me.hand), \
        "人間が選んだ ドレスローザ カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP04-093 ゴムゴムの大猿王銃 (EVENT 黒 cost3):
#    【メイン】ドレスローザ キャラ1枚 パワー+6000 / トラッシュ15枚以上で ダブルアタック付与
#    【トリガー】カード3枚を引き、手札2枚を捨てる
# --------------------------------------------------------------------------- #
def test_op04_093_event_main_power_pump_ai():
    """メイン: ドレスローザ キャラ1枚を このターン中 パワー+6000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    tgt = InPlay.of(repo.get(_DRESSROSA_CHAR), sickness=False)  # ドレスローザ
    me.characters = [tgt]

    power_before = tgt.power
    do, _ = _do(overlay, "OP04-093", "main", needle="power_pump")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert tgt.power == power_before + 6000, \
        f"ドレスローザ キャラの +6000 が反映されていない: {tgt.power} (before {power_before})"


def test_op04_093_event_main_double_attack_ai():
    """メイン (トラッシュ15枚以上): ドレスローザ キャラに ダブルアタック付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    tgt = InPlay.of(repo.get(_DRESSROSA_CHAR), sickness=False)
    me.characters = [tgt]
    me.trash = [repo.get("ST01-004")] * 15

    do, _ = _do(overlay, "OP04-093", "main", needle="give_keyword")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert "ダブルアタック" in tgt.granted_keywords, \
        f"ダブルアタック が付与されていない: {tgt.granted_keywords}"


def test_op04_093_event_trigger_draw_discard_ai():
    """トリガー: カード3枚を引き、手札2枚を捨てる → 手札正味 +1 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")] * 3
    me.deck = [repo.get("ST01-004")] * 10

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP04-093", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, \
        f"draw 3 - discard 2 = 正味 +1 になっていない: {hand_before} -> {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP04-094 雷の破壊剣 (EVENT 黒 cost4):
#    【メイン】相手コスト4以下1枚をKO (トラッシュ15枚以上ならコスト6以下)
#    【トリガー】自リーダーをレストにできる：相手コスト5以下1枚をKO
# --------------------------------------------------------------------------- #
def test_op04_094_event_main_ko_ai():
    """メイン: 相手コスト4以下のキャラ1枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_COST4), sickness=False)  # cost4
    opp.characters = [victim]

    do, _ = _do(overlay, "OP04-094", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手コスト4以下キャラが KO されていない"
    assert repo.get(_OPP_COST4) in opp.trash, "KO したキャラが相手トラッシュにない"


def test_op04_094_event_main_ko_human_pick():
    """人間 + 相手コスト4以下キャラ複数 → ko target_pick modal → resolve で1枚 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_COST4), sickness=False)  # cost4
    b = InPlay.of(repo.get(_CP_COST1), sickness=False)   # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP04-094", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で ko modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "ko", "primitive_kind が ko でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a not in opp.characters, "人間が選んだ相手キャラが KO されていない"


def test_op04_094_event_trigger_ko_ai():
    """トリガー: 自リーダーをレスト (任意コスト) → 相手コスト5以下1枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = False
    victim = InPlay.of(repo.get(_OPP_COST5), sickness=False)  # cost5
    opp.characters = [victim]

    do, _ = _do(overlay, "OP04-094", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手コスト5以下キャラが KO されていない"
    assert me.leader.rested is True, "任意コストで自リーダーがレストされるべき"
