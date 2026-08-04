# -*- coding: utf-8 -*-
"""プロモ (P-*) 効果 回帰テスト バックフィル (自動生成 wave 161):
P-085 / P-086 / P-088 / P-090 / P-091 /
P-093 / P-094 / P-095 / P-096 / P-097 の 10 枚。

目的 (= test_backfill_auto_001〜160.py と同一方針):
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
    eval_condition,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"            # ナミ (cost1 power2000) フィラー / 相手キャラ (cost1)
COST2 = "OP01-013"           # サンジ (cost2 power3000) フィラー
COST4 = "OP11-015"           # モチャ (cost4 power6000) 中コスト (= cost4 対象)
BIG = "OP02-004"             # エドワード・ニューゲート (cost9 power10000) 高コスト
SUPERNOVA_LEADER = "OP01-001"  # ロロノア・ゾロ (超新星/麦わらの一味 LEADER)
NON_SUPERNOVA_LEADER = "OP09-042"  # バギー (青 LEADER、 超新星なし)
HEART_C = "OP01-045"         # ジャンバール (ハートの海賊団 cost4 power6000 vanilla)
HEART_C2 = "ST02-012"        # ベポ (ハートの海賊団 cost1 power3000 vanilla)
FISHMAN_C = "OP15-030"       # ヒョウゾウ (人魚族/魚人島 cost5 power6000 vanilla)
KAIOURUI_C = "EB04-016"      # トリ (海王類 cost5 power7000)
EVENT_BLUE = "EB04-028"      # 青 EVENT (捨てコスト用)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, turn=0,
           opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(COST2)] * 30
    p1.deck = [repo.get(COST2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 (先頭) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    return matches[0]


def _drain(st, picks):
    """resolve 後続の連鎖 modal を流す (guard 付き)。"""
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, picks)
        guard += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave161_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["P-085", "P-086", "P-088", "P-090", "P-091",
           "P-093", "P-094", "P-095", "P-096", "P-097"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  P-085 ジュエリー・ボニー (CHARACTER cost5):
#    【登場時】自分のリーダーが特徴《超新星》を持ち、自分のライフの枚数が相手のライフの
#    枚数以下の場合、相手のコスト4以下のキャラ1枚までを、持ち主のライフの上か下に
#    表向きで加える。
# --------------------------------------------------------------------------- #
def test_p085_bonney_on_play_send_to_opp_life_ai():
    """【登場時】(超新星 leader + 自ライフ<=相手ライフ) 相手コスト4以下キャラ1枚を
    持ち主 (= 相手) のライフへ。 AI 自動選択。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(COST2)] * 2
    opp.life = [repo.get(COST2)] * 2  # 自ライフ (2) <= 相手ライフ (2) = 条件成立
    victim = InPlay.of(repo.get(COST4), sickness=False)  # cost4 (= 対象)
    opp.characters = [victim]

    eff = _eff(overlay, "P-085", "on_play")
    assert eval_condition({"leader_feature": "超新星"}, st, me, None) is True
    assert eval_condition({"self_life_le_opp": True}, st, me, None) is True

    life_before = len(opp.life)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-085"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手コスト4以下キャラが場から離れていない"
    assert len(opp.life) == life_before + 1, \
        f"相手キャラが持ち主ライフに加わっていない: {len(opp.life)} (before {life_before})"


def test_p085_bonney_condition_false_life_greater():
    """自ライフが相手ライフより多いと self_life_le_opp が不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(COST2)] * 3   # 自ライフ 3
    opp.life = [repo.get(COST2)] * 1  # 相手ライフ 1 (= 3 > 1 → 不成立)

    assert eval_condition({"self_life_le_opp": True}, st, me, None) is False, \
        "自ライフ > 相手ライフ で条件が成立してはいけない"


def test_p085_bonney_on_play_human_pick():
    """人間 + 相手コスト4以下 複数 → target_pick modal が立ち resolve でライフ送り。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(COST2)] * 2
    opp.life = [repo.get(COST2)] * 2
    a = InPlay.of(repo.get(COST4), sickness=False)   # cost4
    b = InPlay.of(repo.get(COST2), sickness=False)   # cost2
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "P-085", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-085"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b not in opp.characters, "人間が選んだ相手キャラが場から離れていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  P-086 トラファルガー・ロー (LEADER):
#    【起動メイン】【ターン1回】ドン!!-3,自分のパワー3000以上のキャラ1枚を、デッキの下に
#    置くことができる：自分の手札からコスト4以下の特徴《ハートの海賊団》を持つキャラ
#    カード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_p086_law_activate_main_bounce_then_play_ai():
    """起動メイン: ドン-3 + 自パワー3000以上キャラ1枚をデッキ下 (コスト) →
    手札からコスト4以下ハートの海賊団キャラ1枚を登場。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "P-086", overlay)  # リーダー = トラファルガー・ロー
    me, opp = st.players[0], st.players[1]
    me.don_active = 5  # ドン-3 コスト用
    big = InPlay.of(repo.get(BIG), sickness=False)  # power10000 (>=3000)
    me.characters = [big]
    me.hand = [repo.get(HEART_C)]  # ジャンバール ハートの海賊団 cost4

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "P-086"]
    assert len(opts) == 1, f"P-086 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert me.don_active == 2, f"ドン-3 が消費されていない: {me.don_active}"
    assert big not in me.characters, "コストで自パワー3000以上キャラがデッキ下に置かれていない"
    assert any(c.card.card_id == HEART_C for c in me.characters), \
        "手札からハートの海賊団キャラが登場していない"


def test_p086_law_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "P-086", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    me.characters = [InPlay.of(repo.get(BIG), sickness=False)]
    me.hand = [repo.get(HEART_C)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "P-086"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "P-086"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_p086_law_activate_main_noop_without_don():
    """ドン!!が3枚未満だと ドン-3 の任意コストが払えない → 列挙されない & 発動しても不発。

    ⚠ 列挙から外すのは **ルール上の制限ではなく 探索層の枝刈り** (`_optional_cost_payable_in_do`)。
      公式上は起動して任意コストを見送ることもできるが、 結果は 「何も起きない上に【ターン1回】を
      消費する」 だけで 自傷にしかならないので列挙しない。 発動経路そのものは下で直接叩いて
      盤面不変を確認する ([[project_approximation_hides_bugs]])。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "P-086", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2  # ドン-3 不能
    big = InPlay.of(repo.get(BIG), sickness=False)
    me.characters = [big]
    me.hand = [repo.get(HEART_C)]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "P-086"]
    assert len(opts) == 0, "任意コストが払えないのに起動メインが列挙されている"

    # 列挙を迂回して直接発動しても 盤面は一切変わらない (= 効果が不発)
    eff = next(e for e in overlay.get("P-086").effects if e.get("when") == "activate_main")
    fire_activate_main(st, me, opp, me.leader, eff)
    _drain(st, [0])

    assert me.don_active == 2, "コスト不能なのにドンが消費されてはいけない"
    assert big in me.characters, "コスト不能なのに自キャラがデッキ下に送られてはいけない"
    assert not any(c.card.card_id == HEART_C for c in me.characters), \
        "コスト不能なのにハートの海賊団キャラが登場してはいけない"


# --------------------------------------------------------------------------- #
#  P-088 トラファルガー・ロー (CHARACTER cost4):
#    【トリガー】自分のリーダーが特徴《超新星》を持ち、両者のライフ合計が5以下の場合、
#    このカードを登場させる (overlay: trigger / play_self)。
# --------------------------------------------------------------------------- #
def test_p088_law_trigger_play_self_ai():
    """【トリガー】(超新星 leader + total_life<=5) このカードを登場させる。
    ライフから捲れて trash に置かれた状態で play_self が場に出す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(COST2)] * 2
    opp.life = [repo.get(COST2)] * 2  # total_life = 4 <= 5 → 条件成立
    # トリガー発火の実文脈: カードは trash に置かれ current_source_card_id にスタック
    me.trash = [repo.get("P-088")]
    st.current_source_card_id = "P-088"

    eff = _eff(overlay, "P-088", "trigger")
    assert eval_condition(eff["if"], st, me,
                          InPlay.of(repo.get("P-088"), sickness=True)) is True, \
        "超新星 leader + total_life<=5 で条件が成立していない"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert any(c.card.card_id == "P-088" for c in me.characters), \
        "トリガーで P-088 自身が登場していない"


def test_p088_law_trigger_condition_false_life_over():
    """両者ライフ合計が5超なら 条件不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(COST2)] * 4
    opp.life = [repo.get(COST2)] * 4  # total_life = 8 > 5 → 不成立

    eff = _eff(overlay, "P-088", "trigger")
    assert eval_condition(eff["if"], st, me,
                          InPlay.of(repo.get("P-088"), sickness=True)) is False, \
        "ライフ合計5超で条件が成立してはいけない"


def test_p088_law_trigger_condition_false_no_supernova():
    """リーダーが《超新星》を持たなければ 条件不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NON_SUPERNOVA_LEADER, overlay)  # バギー (超新星なし)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(COST2)] * 2
    opp.life = [repo.get(COST2)] * 2

    eff = _eff(overlay, "P-088", "trigger")
    assert eval_condition(eff["if"], st, me,
                          InPlay.of(repo.get("P-088"), sickness=True)) is False, \
        "非超新星 leader で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-090 シャーロット・スムージー (CHARACTER cost7):
#    【相手のターン中】【KO時】ドン‼-1：自分の手札から「シャーロット・スムージー」以外の
#    相手の場のドン‼の枚数以下のコストを持ち、特徴《ビッグ・マム海賊団》を持つ
#    キャラカード1枚までを、登場させる。
#
#  ⚠ SKIP: overlay は play_from_hand_named_with_dynamic_cost に name_filter
#  (= feature ベース) を渡すが、 engine 実装 (effects.py:5266) は name (完全名) しか
#  参照せず name_filter を無視するため、 該当キャラが手札にあっても silent no-op になる
#  (= 特徴で手札を絞る動的コスト召喚が発火しない engine ギャップ)。 engine 修正は
#  人間レビュー案件 (このタスクでは engine を編集しない) のため skip。
# --------------------------------------------------------------------------- #
def test_p090_smoothie_on_ko_play_bigmom_ai():
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay, turn=1)  # 相手ターン
    me, opp = st.players[0], st.players[1]
    opp.don_active = 5  # 相手の場ドン 5 → cost<=5 が召喚可能
    me.hand = [repo.get("ST07-014")]  # ぺコムズ ビッグ・マム海賊団 cost3

    eff = _eff(overlay, "P-090", "on_ko")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-090"), sickness=False))
    _drain(st, [0])

    assert any("ビッグ・マム海賊団" in c.card.features for c in me.characters), \
        "手札からビッグ・マム海賊団キャラが登場していない"


# --------------------------------------------------------------------------- #
#  P-091 しらほし (CHARACTER cost4):
#    【登場時】自分の手札からコスト5以下の特徴《海王類》か《魚人島》を持つキャラカード
#    1枚までを、登場させる。
#    【起動メイン】このキャラをレストにできる：自分の特徴《海王類》を持つキャラ1枚までは、
#    登場したターンにキャラへアタックできる。
# --------------------------------------------------------------------------- #
def test_p091_shirahoshi_on_play_summon_ai():
    """【登場時】 AI: 手札からコスト5以下《海王類》か《魚人島》キャラ1枚を登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.hand = [repo.get(FISHMAN_C)]  # ヒョウゾウ 魚人島 cost5

    for prim in _eff(overlay, "P-091", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-091"), sickness=True))
    _drain(st, [0])

    assert any(c.card.card_id == FISHMAN_C for c in me.characters), \
        "手札から《魚人島》キャラが登場していない"
    assert not any(c.card_id == FISHMAN_C for c in me.hand), \
        "登場した《魚人島》キャラは手札から除かれるべき"


def test_p091_shirahoshi_activate_main_give_rush_to_kaiourui_ai():
    """起動メイン: 自身レスト (コスト) → 自《海王類》キャラ1枚に「速攻：キャラ」付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    shira = InPlay.of(repo.get("P-091"), sickness=False)
    tori = InPlay.of(repo.get(KAIOURUI_C), sickness=False)  # 海王類
    me.characters = [shira, tori]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "P-091"]
    assert len(opts) == 1, f"P-091 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert shira.rested is True, "起動メインコストで しらほし がレストされるべき"
    assert "速攻：キャラ" in tori.granted_keywords, \
        f"《海王類》キャラに『速攻：キャラ』が付与されていない: {tori.granted_keywords}"


# --------------------------------------------------------------------------- #
#  P-093 トラファルガー・ロー (CHARACTER cost4):
#    【ブロッカー】【登場時】自分の場のドン‼が相手の場のドン‼の枚数以下の場合、
#    ドン‼デッキからドン‼1枚までを、レストで追加する。
# --------------------------------------------------------------------------- #
def test_p093_law_on_play_add_rested_don_ai():
    """【登場時】(自ドン <= 相手ドン) ドン!!デッキからドン1枚をレストで追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1
    opp.don_active = 3   # 自ドン (1) <= 相手ドン (3) → 条件成立
    me.don_rested = 0
    me.don_remaining_in_deck = 5

    eff = _eff(overlay, "P-093", "on_play")
    assert eval_condition(eff["if"], st, me, None) is True, \
        "自ドン <= 相手ドン で条件が成立していない"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-093"), sickness=True))

    assert me.don_rested == 1, f"ドン!!デッキからレストドンが追加されていない: {me.don_rested}"


def test_p093_law_on_play_condition_false_don_lead():
    """自ドンが相手ドンより多いと don_diff_le=0 が不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 4
    opp.don_active = 1  # 自ドン (4) > 相手ドン (1) → 不成立

    eff = _eff(overlay, "P-093", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "自ドン > 相手ドン で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-094 ロロノア・ゾロ (CHARACTER cost4):
#    【登場時】相手のレストのコスト2以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_p094_zoro_on_play_ko_rested_cost2_ai():
    """【登場時】 AI: 相手のレストのコスト2以下キャラ1枚を KO する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1
    victim.rested = True  # レスト (= 対象)
    opp.characters = [victim]

    for prim in _eff(overlay, "P-094", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-094"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手のレストコスト2以下キャラが KO されていない"


def test_p094_zoro_on_play_active_survives():
    """相手のコスト2以下キャラが アクティブなら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    for prim in _eff(overlay, "P-094", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-094"), sickness=True))
    _drain(st, [0])

    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


def test_p094_zoro_on_play_human_ko_pick():
    """人間 + 相手のレストコスト2以下 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(COST2), sickness=False)  # cost2
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "P-094", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-094"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  P-095 サンジ (CHARACTER cost4):
#    【相手のアタック時】【ターン1回】自分の手札からイベント1枚を捨てることができる：
#    自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_p095_sanji_opp_attack_discard_event_pump_ai():
    """【相手のアタック時】手札イベント1捨て → 自リーダーかキャラ1枚 このバトル中 +2000。
    AI: 最高パワー (= リーダー) に +2000、 イベント1枚が捨てられる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay, turn=1)  # 相手ターン
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("P-095"), sickness=False)
    me.characters = [sanji]
    me.hand = [repo.get(EVENT_BLUE)]  # 捨てる EVENT コスト用
    me.trash = []

    leader_power_before = me.leader.power
    for prim in _eff(overlay, "P-095", "opp_attack")["do"]:
        execute_effect(prim, st, me, opp, sanji)
    _drain(st, [0])

    assert me.leader.power == leader_power_before + 2000, \
        f"自リーダーに +2000 が反映されていない: {me.leader.power} (before {leader_power_before})"
    assert len(me.hand) == 0, "コストで手札イベントが1枚捨てられていない"
    assert any(c.card_id == EVENT_BLUE for c in me.trash), \
        "捨てたイベントがトラッシュに移っていない"


def test_p095_sanji_opp_attack_no_event_noop():
    """手札にイベントが無ければ 任意コスト不能 → +2000 が乗らない (効果不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay, turn=1)
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("P-095"), sickness=False)
    me.characters = [sanji]
    me.hand = [repo.get(COST2)]  # CHARACTER のみ = 捨てられない

    leader_power_before = me.leader.power
    for prim in _eff(overlay, "P-095", "opp_attack")["do"]:
        execute_effect(prim, st, me, opp, sanji)
    _drain(st, [0])

    assert me.leader.power == leader_power_before, \
        "イベント不在なのに +2000 が乗ってはいけない"


def test_p095_sanji_opp_attack_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 対象選択の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay, human_idx=0, turn=1)
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("P-095"), sickness=False)
    friend = InPlay.of(repo.get(COST2), sickness=False)
    me.characters = [sanji, friend]
    me.hand = [repo.get(EVENT_BLUE)]

    for prim in _eff(overlay, "P-095", "opp_attack")["do"]:
        execute_effect(prim, st, me, opp, sanji)
        if st.pending_choice is not None:
            break

    # 任意コスト (イベント1捨て) の確認 modal → 承諾 ([1]) すると対象選択へ進む
    assert st.pending_choice is not None, "人間で 任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)

    assert st.pending_choice is not None, "承諾後に +2000 対象選択の modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 3, f"候補 (リーダー+キャラ2) が 3 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain(st, [friend_idx])
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  P-096 少女 (CHARACTER cost2):
#    【登場時】カード1枚を引き、自分の手札1枚を捨てる。
#    【起動メイン】【ターン1回】自分の「ナミ」1枚にレストのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_p096_shoujo_on_play_draw_discard_ai():
    """【登場時】 1ドロー + 手札1枚を捨てる (net 手札 ±0、 trash +1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(COST2)]
    me.deck = [repo.get(COST2)] * 10
    me.trash = []

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    for prim in _eff(overlay, "P-096", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-096"), sickness=True))
    _drain(st, [0])

    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"
    assert len(me.trash) == 1, "手札1枚が捨てられてトラッシュに移っていない"
    # 手札 net: 元1 + ドロー1 - 捨て1 = 1
    assert len(me.hand) == hand_before, \
        f"手札 net (ドロー+1 捨て-1) が合わない: {len(me.hand)}"


def test_p096_shoujo_activate_main_attach_don_to_nami_ai():
    """起動メイン: 自分の「ナミ」1枚にレストのドン1枚を付与。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    shoujo = InPlay.of(repo.get("P-096"), sickness=False)
    nami = InPlay.of(repo.get(NAMI), sickness=False)  # ナミ
    me.characters = [shoujo, nami]
    me.don_rested = 2

    don_before = nami.attached_dons
    rested_before = me.don_rested
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "P-096"]
    assert len(opts) == 1, f"P-096 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert nami.attached_dons == don_before + 1, \
        "自分の「ナミ」にレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_p096_shoujo_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    shoujo = InPlay.of(repo.get("P-096"), sickness=False)
    nami = InPlay.of(repo.get(NAMI), sickness=False)
    me.characters = [shoujo, nami]
    me.don_rested = 3

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "P-096"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "P-096"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  P-097 シャンクス (CHARACTER cost10):
#    【登場時】/【アタック時】相手は、このターン中、【ブロッカー】を発動できない。
# --------------------------------------------------------------------------- #
def test_p097_shanks_on_play_disable_blocker_ai():
    """【登場時】相手キャラ全体が このターン中【ブロッカー】を発動できない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(COST2), sickness=False)
    b = InPlay.of(repo.get(COST4), sickness=False)
    opp.characters = [a, b]

    for prim in _eff(overlay, "P-097", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-097"), sickness=True))

    assert a.blocker_disabled_until_turn_end is True, \
        "相手キャラ a のブロッカーが無効化されていない"
    assert b.blocker_disabled_until_turn_end is True, \
        "相手キャラ b のブロッカーが無効化されていない"


def test_p097_shanks_on_attack_disable_blocker_ai():
    """【アタック時】相手キャラ全体が このターン中【ブロッカー】を発動できない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, SUPERNOVA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(COST2), sickness=False)
    opp.characters = [a]

    for prim in _eff(overlay, "P-097", "on_attack")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-097"), sickness=False))

    assert a.blocker_disabled_until_turn_end is True, \
        "アタック時に相手キャラのブロッカーが無効化されていない"
