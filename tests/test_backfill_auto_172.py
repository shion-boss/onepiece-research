# -*- coding: utf-8 -*-
"""ST08 / ST09 弾 効果 回帰テスト バックフィル (自動生成 wave 172):
ST08-009 / ST08-013 / ST08-014 / ST08-015 / ST09-001 / ST09-002 /
ST09-004 / ST09-005 / ST09-007 / ST09-008 の 10 枚。

目的 (= test_backfill_auto_001〜171.py と同一方針):
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
    eval_all_conditions,
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# 汎用 埋めカード / 参照カード
_FILLER = "ST01-004"          # サンジ cost2 power4000 (バニラ気味)
_NEUTRAL_LEADER = "OP10-099"  # ユースタス・キッド (中立枠として利用)
_LINLIN_CHARA = "ST07-010"    # シャーロット・リンリン (CHARACTER cost7、 高コスト victim)
_NAMI = "OP01-016"            # ナミ (cost1 power2000)
_MAKINO = "ST08-009"          # マキノ (黒 cost2、 trash_to_hand 用 黒コスト2)
_WANO_COST4 = "ST09-002"      # 雨月天ぷら (ワノ国 黄 cost4 CHARACTER)
_WANO_COST1 = "OP06-108"      # 天狗山飛徹 (ワノ国 黄 cost1 CHARACTER)


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
    """指定 card_id の overlay から when 一致の効果 dict を返す (needle で do 内絞り込み)。"""
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
def test_all_wave172_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST08-009", "ST08-013", "ST08-014", "ST08-015", "ST09-001",
           "ST09-002", "ST09-004", "ST09-005", "ST09-007", "ST09-008"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST08-009 マキノ (CHARACTER 黒 cost2):
#    【登場時】コスト0のキャラがいる場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_st08_009_on_play_draw_when_cost0_present_ai():
    """【登場時】コスト0のキャラがいる → 条件成立し 1 ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # base_cost を 0 に落としたキャラ を場に置く (= 「コスト0のキャラがいる」 状態)。
    cost0 = InPlay.of(repo.get(_NAMI), sickness=False)
    cost0.base_cost_override = 0
    assert cost0.base_cost == 0, "前提: base_cost を 0 に設定"
    me.characters = [cost0]
    me.deck = [repo.get(_FILLER)] * 5
    me.hand = []

    eff = _eff(overlay, "ST08-009", "on_play")
    assert eval_all_conditions(eff, st, me) is True, \
        "コスト0キャラが居るのに 登場時条件が成立しない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST08-009"), sickness=True))
    assert len(me.hand) == 1, "登場時の 1 ドローが起きていない"


def test_st08_009_on_play_condition_false_without_cost0():
    """コスト0のキャラが居なければ 登場時条件は不成立 (= 引かない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me = st.players[0]
    # cost2 の通常キャラのみ (= コスト0キャラ 無し)
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]

    eff = _eff(overlay, "ST08-009", "on_play")
    assert eval_all_conditions(eff, st, me) is False, \
        "コスト0キャラが居ないのに 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  ST08-013 Mr.2・ボン・クレー (CHARACTER 黒 cost5):
#    【ドン!!×1】バトル終了時、 バトルした相手キャラを KO してもよい。
#      そうした場合、 このキャラを KO する。
# --------------------------------------------------------------------------- #
def test_st08_013_on_self_battled_ko_and_self_ko_ai():
    """バトルした相手キャラが場に残る → KO し、 そうしたら 自身も KO (トラッシュへ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bon = InPlay.of(repo.get("ST08-013"), sickness=False)
    bon.attached_dons = 1  # ドン!!×1 ゲート
    me.characters = [bon]
    victim = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)
    opp.characters = [victim]
    st.last_battled_opp_iid = victim.instance_id  # 直前バトル相手

    for prim in _eff(overlay, "ST08-013", "on_self_battled")["do"]:
        execute_effect(prim, st, me, opp, bon)

    assert victim not in opp.characters, "バトルした相手キャラが KO されていない"
    assert bon not in me.characters, "相手を KO したら 自身も KO されるべき"
    assert any(c.card_id == "ST08-013" for c in me.trash), \
        "自身が トラッシュ に置かれていない"


def test_st08_013_on_self_battled_no_ko_when_absent():
    """バトルした相手キャラが既に居ない (iid 未設定) → conditional 不発 = 自身も残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bon = InPlay.of(repo.get("ST08-013"), sickness=False)
    bon.attached_dons = 1
    me.characters = [bon]
    st.last_battled_opp_iid = None  # 直前バトル相手 不在

    for prim in _eff(overlay, "ST08-013", "on_self_battled")["do"]:
        execute_effect(prim, st, me, opp, bon)

    assert bon in me.characters, \
        "バトル相手不在なら conditional 不発 = 自身は KO されない"


# --------------------------------------------------------------------------- #
#  ST08-014 ゴムゴムの鐘 (EVENT 黒 cost2):
#    【メイン】自ライフ上1→手札できる：相手キャラ1枚まで このターン中 コスト-7。
#    【トリガー】自トラッシュの コスト2以下の黒キャラ1枚までを手札へ。
# --------------------------------------------------------------------------- #
def test_st08_014_main_cost_minus_7_ai():
    """【メイン】任意コスト (自ライフ上→手札) を払い、 相手キャラ1枚を コスト-7 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = []
    victim = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # cost7
    opp.characters = [victim]

    cost_before = victim.base_cost
    life_before = len(me.life)
    for prim in _eff(overlay, "ST08-014", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim.base_cost == cost_before - 7, \
        f"相手キャラの コスト-7 が反映されていない: {victim.base_cost} (before {cost_before})"
    assert len(me.life) == life_before - 1, "任意コストで 自ライフ上1枚が手札へ移るべき"
    assert len(me.hand) == 1, "自ライフ上1枚が手札に加わっていない"


def test_st08_014_trigger_trash_black_cost2_to_hand_ai():
    """【トリガー】自トラッシュの コスト2以下 黒キャラ1枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_MAKINO)]  # マキノ 黒 cost2 (= filter 一致)
    me.hand = []

    for prim in _eff(overlay, "ST08-014", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card_id == _MAKINO for c in me.hand), \
        "トラッシュの黒コスト2キャラが手札に加わっていない"
    assert not any(c.card_id == _MAKINO for c in me.trash), \
        "手札へ移った分 トラッシュから除かれるべき"


# --------------------------------------------------------------------------- #
#  ST08-015 ゴムゴムの銃 (EVENT 黒 cost3):
#    【メイン】相手のコスト2以下のキャラ1枚までを、 KOする。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_st08_015_main_ko_cost2_ai():
    """【メイン】相手のコスト2以下キャラ1枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=2)
    opp.characters = [victim]

    for prim in _eff(overlay, "ST08-015", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"


def test_st08_015_main_ko_cost3_not_target():
    """相手にコスト3以上のキャラしか居なければ 対象外 (KO されない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # cost7 (>2)
    opp.characters = [big]

    for prim in _eff(overlay, "ST08-015", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert big in opp.characters, "コスト3以上のキャラが KO されてはいけない (対象外)"


def test_st08_015_main_ko_human_pick():
    """人間 + 相手のコスト2以下キャラ複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)     # cost1
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST08-015", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_st08_015_trigger_draw_ai():
    """【トリガー】カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5

    for prim in _eff(overlay, "ST08-015", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == 1, "トリガーの 1 ドローが起きていない"


# --------------------------------------------------------------------------- #
#  ST09-001 ヤマト (LEADER 黄):
#    【ドン!!×1】【相手のターン中】自分のライフが2枚以下 → このリーダーはパワー+1000。
# --------------------------------------------------------------------------- #
def test_st09_001_leader_static_pump_opp_turn_life_le2():
    """相手ターン中 + ドン!!×1 + 自ライフ2以下 → リーダー static_buff +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST09-001", overlay)  # 自身が ヤマト leader
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    me = st.players[0]
    me.leader.attached_dons = 1        # ドン!!×1 ゲート
    me.life = [repo.get(_FILLER)] * 2  # ライフ 2 (<=2)

    evaluate_static_effects(st, overlay)
    assert me.leader.static_buff == 1000, \
        f"相手ターン中 ライフ2以下で +1000 (static) が乗っていない: {me.leader.static_buff}"


def test_st09_001_leader_static_no_pump_life_ge3():
    """自ライフが3枚 (>2) なら 条件不成立 → static_buff 0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST09-001", overlay)
    st.turn_player_idx = 1  # 相手ターン
    me = st.players[0]
    me.leader.attached_dons = 1
    me.life = [repo.get(_FILLER)] * 3  # ライフ 3 (>2) = 条件外れ

    evaluate_static_effects(st, overlay)
    assert me.leader.static_buff == 0, \
        f"ライフ3枚では効果 pump が乗ってはいけない: {me.leader.static_buff}"


def test_st09_001_leader_static_no_pump_self_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → static_buff 0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST09-001", overlay)
    st.turn_player_idx = 0  # 自ターン (= opp_turn False)
    me = st.players[0]
    me.leader.attached_dons = 1
    me.life = [repo.get(_FILLER)] * 2

    evaluate_static_effects(st, overlay)
    assert me.leader.static_buff == 0, \
        f"自ターン中は効果 pump が乗ってはいけない: {me.leader.static_buff}"


# --------------------------------------------------------------------------- #
#  ST09-002 雨月天ぷら (CHARACTER 黄 cost4):
#    【トリガー】相手のコスト2以下のキャラ1枚までを、 レストにし、 このカードを手札に加える。
# --------------------------------------------------------------------------- #
def test_st09_002_trigger_rest_and_keep_in_hand_ai():
    """【トリガー】相手のコスト2以下キャラ1枚を レスト + このカードを手札へ (keep flag)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    assert victim.rested is False, "前提: victim は アクティブ"
    opp.characters = [victim]

    for prim in _eff(overlay, "ST09-002", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim.rested is True, "相手のコスト2以下キャラが レストされていない"
    assert st.last_trigger_kept_in_hand is True, \
        "このカードを手札に加える (trigger keep) フラグが立っていない"


def test_st09_002_trigger_rest_human_pick():
    """人間 + 相手のコスト2以下キャラ複数 → target_pick modal が立ち resolve で レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)     # cost1
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST09-002", "trigger")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラが レストされていない"
    assert a.rested is False, "選ばなかったキャラは アクティブのままであるべき"


# --------------------------------------------------------------------------- #
#  ST09-004 カイドウ (CHARACTER 黄 cost4):
#    【ドン!!×1】自分のライフが2枚以下 → このキャラはバトルでKOされない (static)。
# --------------------------------------------------------------------------- #
def test_st09_004_static_battle_ko_immune_life_le2():
    """ドン!!×1 + 自ライフ2以下 → battle_ko_immune_static True。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me = st.players[0]
    kaido = InPlay.of(repo.get("ST09-004"), sickness=False)
    kaido.attached_dons = 1            # ドン!!×1 ゲート (n=1)
    me.characters = [kaido]
    me.life = [repo.get(_FILLER)] * 2  # ライフ 2 (<=2)

    assert kaido.battle_ko_immune_static is False, "前提: 静的評価前は False"
    evaluate_static_effects(st, overlay)
    assert kaido.battle_ko_immune_static is True, \
        "ライフ2以下でバトル KO 耐性 (静的) が付与されていない"


def test_st09_004_static_no_immune_life_ge3():
    """自ライフ3枚 (>2) なら 条件不成立 → バトル KO 耐性は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me = st.players[0]
    kaido = InPlay.of(repo.get("ST09-004"), sickness=False)
    kaido.attached_dons = 1
    me.characters = [kaido]
    me.life = [repo.get(_FILLER)] * 3  # ライフ 3 (>2)

    evaluate_static_effects(st, overlay)
    assert kaido.battle_ko_immune_static is False, \
        "ライフ3枚では KO 耐性が付いてはいけない"


# --------------------------------------------------------------------------- #
#  ST09-005 光月おでん (CHARACTER 黄 cost7):
#    【ドン!!×1】このキャラは【ダブルアタック】を得る。
#    【KO時】自分の手札2枚を捨てることができる：自デッキ上1枚までを、 ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_st09_005_static_double_attack_don1():
    """ドン!!×1 → overlay の on_attached_don が【ダブルアタック】を静的付与する。

    ⚠ このカードは engine の text パーサが 【ダブルアタック】 を innate 扱いするため
    has_keyword_active は 常時 True になる (別枠の engine text-parse 挙動)。 ここでは
    overlay の give_keyword 静的付与経路 (= ドン条件でゲートされる static_granted_keywords)
    を直接検証する。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me = st.players[0]
    oden = InPlay.of(repo.get("ST09-005"), sickness=False)
    me.characters = [oden]

    # ドン!!×0 (n=1 ゲート未成立) では 静的付与されない
    oden.attached_dons = 0
    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" not in oden.static_granted_keywords, \
        "ドン!!×0 では 静的付与 (static_granted_keywords) されてはいけない"

    # ドン!!×1 で overlay が【ダブルアタック】を静的付与する
    oden.attached_dons = 1
    evaluate_static_effects(st, overlay)
    assert "ダブルアタック" in oden.static_granted_keywords, \
        "ドン!!×1 で【ダブルアタック】が overlay 経由で静的付与されていない"


def test_st09_005_on_ko_discard2_put_top_to_life_ai():
    """【KO時】手札2枚を捨て (任意コスト) → 自デッキ上1枚を ライフへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_NAMI)]  # 捨てる 2 枚
    me.deck = [repo.get(_FILLER)] * 5
    me.life = [repo.get(_FILLER)] * 1

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    life_before = len(me.life)
    for prim in _eff(overlay, "ST09-005", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST09-005"), sickness=False))
    _drain(st, [0])

    assert len(me.hand) == hand_before - 2, "任意コストで手札2枚が捨てられるべき"
    assert len(me.deck) == deck_before - 1, "デッキ上1枚が移動するべき"
    assert len(me.life) == life_before + 1, "デッキ上1枚が ライフの上に加わるべき"


def test_st09_005_on_ko_no_effect_when_hand_lt2():
    """手札が1枚だけなら 任意コスト (手札2枚捨て) を払えず 発動しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # 1 枚のみ
    me.deck = [repo.get(_FILLER)] * 5
    me.life = [repo.get(_FILLER)] * 1

    life_before = len(me.life)
    for prim in _eff(overlay, "ST09-005", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST09-005"), sickness=False))
    _drain(st, [0])

    assert len(me.life) == life_before, "コスト不能なら ライフは増えない (不発)"
    assert len(me.hand) == 1, "コスト不能なら手札は消費されない"


# --------------------------------------------------------------------------- #
#  ST09-007 しのぶ (CHARACTER 黄 cost3):
#    【ブロッカー】【ブロック時】自ライフ上下1→手札できる：このキャラは このバトル中 +4000。
# --------------------------------------------------------------------------- #
def test_st09_007_is_blocker():
    """【ブロッカー】が intrinsic に付いている (公式テキスト忠実)。"""
    repo = _repo()
    shinobu = InPlay.of(repo.get("ST09-007"), sickness=False)
    assert shinobu.is_blocker_now, "ST09-007 は【ブロッカー】を持つべき"


def test_st09_007_on_block_pump_self_4000_ai():
    """【ブロック時】任意コスト (自ライフ上下→手札) を払い、 このキャラ +4000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    shinobu = InPlay.of(repo.get("ST09-007"), sickness=False)  # power 2000
    me.characters = [shinobu]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = []

    power_before = shinobu.power
    life_before = len(me.life)
    for prim in _eff(overlay, "ST09-007", "on_block")["do"]:
        execute_effect(prim, st, me, opp, shinobu)
    _drain(st, [0])

    assert shinobu.power == power_before + 4000, \
        f"ブロック時の +4000 が反映されていない: {shinobu.power} (before {power_before})"
    assert len(me.life) == life_before - 1, "任意コストで 自ライフ上下1枚が手札へ移るべき"
    assert len(me.hand) == 1, "自ライフ1枚が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  ST09-008 霜月牛マル (CHARACTER 黄 cost5):
#    【ドン!!×1】【アタック時】自ライフ上下1→手札できる：
#      手札からコスト4以下の黄の特徴《ワノ国》キャラ1枚までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_st09_008_on_attack_play_wano_from_hand_ai():
    """【アタック時】任意コスト (自ライフ→手札) を払い、 手札のワノ国 cost4以下を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    ushimaru = InPlay.of(repo.get("ST09-008"), sickness=False)
    ushimaru.attached_dons = 1  # ドン!!×1 ゲート
    me.characters = [ushimaru]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = [repo.get(_WANO_COST4)]  # 雨月天ぷら ワノ国 黄 cost4
    me.deck = [repo.get(_FILLER)] * 5

    life_before = len(me.life)
    for prim in _eff(overlay, "ST09-008", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, ushimaru)
    _drain(st, [0])

    assert any(c.card.card_id == _WANO_COST4 for c in me.characters), \
        "手札からワノ国 cost4以下キャラが登場していない"
    assert not any(c.card_id == _WANO_COST4 for c in me.hand), \
        "登場した分 手札から除かれるべき"
    assert len(me.life) == life_before - 1, "任意コストで 自ライフ上下1枚が手札へ移るべき"


def test_st09_008_on_attack_play_human_pick():
    """人間 + 手札にワノ国 cost4以下 複数 → 登場先を選ぶ play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    ushimaru = InPlay.of(repo.get("ST09-008"), sickness=False)
    ushimaru.attached_dons = 1
    me.characters = [ushimaru]
    me.hand = [repo.get(_WANO_COST4), repo.get(_WANO_COST1)]  # ワノ国 黄 cost4 / cost1
    me.deck = [repo.get(_FILLER)] * 5

    # optional_cost_then の内側 effect (= play_from_hand) を直接発火し、
    # 人間 の 登場先 選択 modal を検証する (任意コスト確認 modal は別段階)。
    inner = _eff(overlay, "ST09-008", "on_attack")["do"][0]["optional_cost_then"]
    play_prim = next(p for p in inner["effect"] if "play_from_hand" in p)
    execute_effect(play_prim, st, me, opp, ushimaru)

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in (_WANO_COST4, _WANO_COST1) for c in me.characters), \
        "人間が選んだワノ国キャラが登場していない"
