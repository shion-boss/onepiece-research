# -*- coding: utf-8 -*-
"""OP12 (黄 超新星) / OP13 (赤・赤黒 サボ / ルフィ・革命軍 系) 効果 回帰テスト
バックフィル (自動生成 wave 125):
OP12-117 / OP12-118 / OP13-004 / OP13-005 / OP13-006 /
OP13-007 / OP13-009 / OP13-013 / OP13-015 / OP13-017 の 10 枚。

目的 (= test_backfill_auto_001〜124.py と同一方針):
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
    """指定 card_id の overlay から when 一致の最初の効果の (do, entry) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


def _drain(st, guard=14):
    """pending_choice を種別ごとに適切に選び続けて解決しきる。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        kind = st.pending_choice.get("kind", "")
        if kind in ("optional_cost_confirm", "reveal_top_play_confirm",
                    "replace_ko_optional"):
            resolve_pending_choice(st, [1])
        else:
            cands = (st.pending_choice.get("candidates")
                     or st.pending_choice.get("cards")
                     or st.pending_choice.get("options") or [])
            resolve_pending_choice(st, [0] if len(cands) > 0 else [])
        g += 1


# 定番 leader / helper カード
_NEUTRAL = "OP01-001"       # モンキー・Ｄ・ルフィ (leader、 麦わらの一味)
_SS_LEADER = "OP07-019"     # ジュエリー・ボニー (超新星/ボニー海賊団)
_VICTIM = "OP01-016"        # ナミ (麦わらの一味 cost1 pow2000 CHARACTER)
_FILLER = "OP01-013"        # サンジ (麦わらの一味 cost2 pow3000 CHARACTER)
_LUFFY_C = "OP14-013"       # モンキー・Ｄ・ルフィ (CHARACTER 赤 cost1 pow-)
_SANZOKU = "OP02-010"       # ドグラ (山賊 CHARACTER 赤 cost1)
_COST8 = "OP12-107"         # ドンキホーテ・ドフラミンゴ (cost8 CHARACTER)
_ZERO_POW = "OP13-006"      # ウープ・スラップ (power 0 CHARACTER)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave125_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP12-117", "OP12-118", "OP13-004", "OP13-005", "OP13-006",
           "OP13-007", "OP13-009", "OP13-013", "OP13-015", "OP13-017"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP12-117 破壊弦 (EVENT 黄 cost1):
#    【メイン】ドン5レスト：自リーダーが超新星なら、 コスト9以下の相手キャラ1枚までを
#      持ち主 (相手) のライフに裏向きで加える。
#    【カウンター】自リーダーを このバトル中 パワー+3000。
# --------------------------------------------------------------------------- #
def test_op12_117_main_chara_to_life_ai():
    """【メイン】do: コスト9以下の相手キャラを 相手ライフへ加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SS_LEADER, overlay)  # 超新星 leader
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=9)
    opp.characters = [victim]

    life_before = len(opp.life)
    do, _ = _do(overlay, "OP12-117", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, "コスト9以下の相手キャラが場から取り除かれていない"
    assert len(opp.life) == life_before + 1, "取り除いたキャラが相手ライフに加わっていない"


def test_op12_117_main_chara_to_life_human_pick():
    """人間 + コスト9以下の相手キャラ複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SS_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP12-117", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが場から取り除かれていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_op12_117_counter_pump_leader():
    """【カウンター】 自リーダーを このバトル中 パワー+3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SS_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP12-117", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP12-118 ジュエリー・ボニー (CHARACTER 緑 cost5 pow6000):
#    【ブロッカー】【登場時】自分のレストのカードが8枚以上ある場合、カード2枚を引き、
#      自分の手札1枚を捨てる。その後、自分のドン‼1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op12_118_on_play_draw_discard_untap_ai():
    """【登場時】 レスト8枚以上 → 2ドロー + 手札1捨て + ドン1アクティブ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 8  # レスト8枚 = 条件成立
    me.hand = [repo.get(_FILLER)]
    me.deck = [repo.get(_VICTIM)] * 10
    boni = InPlay.of(repo.get("OP12-118"), sickness=True)
    me.characters = [boni]

    hand_before = len(me.hand)
    active_before = me.don_active
    trigger_on_play(st, me, opp, boni, overlay)
    _drain(st)

    # 手札: +2 ドロー -1 捨て = net +1
    assert len(me.hand) == hand_before + 1, \
        f"2ドロー+1捨ての net (+1) が合わない: {len(me.hand)} (before {hand_before})"
    assert me.don_active == active_before + 1, "ドン1枚がアクティブになっていない"
    assert me.don_rested == 7, "アクティブ化で レストドンが1枚減るべき"


def test_op12_118_on_play_no_trigger_when_few_rested():
    """負例: レストが8枚未満なら 効果条件不成立 → ドロー/捨て/アクティブ化なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3  # 8枚未満 = 条件不成立
    me.hand = [repo.get(_FILLER)]
    me.deck = [repo.get(_VICTIM)] * 10
    boni = InPlay.of(repo.get("OP12-118"), sickness=True)
    me.characters = [boni]

    hand_before = len(me.hand)
    active_before = me.don_active
    trigger_on_play(st, me, opp, boni, overlay)
    _drain(st)

    assert len(me.hand) == hand_before, "条件不成立でドロー/捨てが起きてはいけない"
    assert me.don_active == active_before, "条件不成立でドンがアクティブになってはいけない"


# --------------------------------------------------------------------------- #
#  OP13-004 サボ (LEADER 赤/黒 pow5000):
#    自ライフ4枚以上 → このリーダーのパワー-1000 (静的)。
#    【ドン‼×1】自分のコスト8以上のキャラがいる場合、自リーダーとキャラすべて +1000。
# --------------------------------------------------------------------------- #
def test_op13_004_static_minus_when_life_ge_4():
    """静的 (n=0): 自ライフ4枚以上 → リーダー -1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP13-004", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 4  # 4枚以上 = 条件成立

    base = repo.get("OP13-004").power  # 5000
    evaluate_static_effects(st, overlay)
    assert me.leader.power == base - 1000, \
        f"自ライフ4枚以上で リーダー -1000 が反映されていない: {me.leader.power}"


def test_op13_004_don1_team_pump_when_cost8_present():
    """【ドン‼×1】 コスト8以上キャラがいる → 自リーダーとキャラすべて +1000。
    (ライフ3枚 = -1000 条件は不成立、 don1付与 = +1000 も乗る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP13-004", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3  # <4 → -1000 は不成立
    me.leader.attached_dons = 1        # 【ドン‼×1】ゲート成立
    dofla = InPlay.of(repo.get(_COST8), sickness=False)  # cost8
    me.characters = [dofla]

    base = repo.get("OP13-004").power  # 5000
    dofla_base = dofla.power
    evaluate_static_effects(st, overlay)

    # リーダー = base 5000 + DON1(+1000) + 効果(+1000) = 7000
    assert me.leader.power == base + 1000 + 1000, \
        f"ドン1 + コスト8で リーダー +1000 が乗っていない: {me.leader.power}"
    assert dofla.power == dofla_base + 1000, \
        f"コスト8キャラ自身にも +1000 が乗るべき: {dofla.power} (base {dofla_base})"


def test_op13_004_no_team_pump_without_cost8():
    """負例: コスト8以上キャラ不在 → チーム +1000 は乗らない (don分のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP13-004", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.leader.attached_dons = 1
    small = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    me.characters = [small]

    base = repo.get("OP13-004").power
    evaluate_static_effects(st, overlay)
    # DON1(+1000) のみ、 効果 +1000 は乗らない
    assert me.leader.power == base + 1000, \
        f"コスト8不在で チーム +1000 が乗ってはいけない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP13-005 イナズマ (CHARACTER 赤 cost4 pow5000):
#    【登場時】自分のリーダーにレストのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op13_005_on_play_attach_rested_don_leader_ai():
    """【登場時】 自リーダーにレストドン1枚を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    inazuma = InPlay.of(repo.get("OP13-005"), sickness=True)
    me.characters = [inazuma]

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    trigger_on_play(st, me, opp, inazuma, overlay)
    _drain(st)

    assert me.leader.attached_dons == don_before + 1, \
        "登場時に自リーダーへレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


# --------------------------------------------------------------------------- #
#  OP13-006 ウープ・スラップ (CHARACTER 赤 cost1 pow-):
#    【登場時】自分の「モンキー・Ｄ・ルフィ」1枚にレストのドン‼2枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_op13_006_on_play_attach_rested_don_luffy_ai():
    """【登場時】 自「モンキー・Ｄ・ルフィ」にレストドン2枚を付与 (AI 単一候補で自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    luffy = InPlay.of(repo.get(_LUFFY_C), sickness=False)
    slap = InPlay.of(repo.get("OP13-006"), sickness=True)
    me.characters = [luffy, slap]

    don_before = luffy.attached_dons
    rested_before = me.don_rested
    trigger_on_play(st, me, opp, slap, overlay)
    _drain(st)

    assert luffy.attached_dons == don_before + 2, \
        f"ルフィにレストドン2枚が付与されていない: {luffy.attached_dons}"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"


def test_op13_006_on_play_human_luffy_pick():
    """人間 + ルフィ 複数 → target_pick modal が立ち resolve で付与先を選べる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    a = InPlay.of(repo.get(_LUFFY_C), sickness=False)
    b = InPlay.of(repo.get(_LUFFY_C), sickness=False)
    slap = InPlay.of(repo.get("OP13-006"), sickness=True)
    me.characters = [a, b, slap]

    trigger_on_play(st, me, opp, slap, overlay)

    assert st.pending_choice is not None, "人間 + ルフィ複数で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (ルフィ2体) が 2 件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.attached_dons == 2, "人間が選んだルフィにレストドン2枚が付与されていない"


# --------------------------------------------------------------------------- #
#  OP13-007 エース＆サボ＆ルフィ (CHARACTER 赤 cost1 pow1000):
#    【起動メイン】自リーダーかキャラ1枚にアクティブのドン1付与し、このキャラを
#      トラッシュに置ける：相手のキャラ1枚までを、このターン中、パワー-3000。
# --------------------------------------------------------------------------- #
def test_op13_007_activate_main_debuff_ai():
    """起動メイン: 自身をトラッシュ (コスト) → 相手キャラ1体 -3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("OP13-007"), sickness=False)
    me.characters = [ace]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # pow2000
    opp.characters = [victim]

    power_before = victim.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP13-007"]
    assert len(opts) == 1, \
        f"OP13-007 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert ace not in me.characters, "コストで このキャラがトラッシュに置かれるべき"
    assert victim.power == power_before - 3000, \
        f"相手キャラ -3000 が反映されていない: {victim.power} (before {power_before})"


def test_op13_007_activate_main_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1体に -3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    ace = InPlay.of(repo.get("OP13-007"), sickness=False)
    me.characters = [ace]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)   # pow2000
    b = InPlay.of(repo.get(_FILLER), sickness=False)   # pow3000
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP13-007"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP13-009 カーリー・ダダン (CHARACTER 赤 cost1 pow2000):
#    このカード以外の特徴《山賊》を持つキャラがいる場合、
#    このキャラは【ダブルアタック】を得る。 (静的)
# --------------------------------------------------------------------------- #
def test_op13_009_static_double_attack_with_bandit():
    """静的: 他の《山賊》キャラがいる → 【ダブルアタック】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    dada = InPlay.of(repo.get("OP13-009"), sickness=False)
    other_bandit = InPlay.of(repo.get(_SANZOKU), sickness=False)  # 山賊
    me.characters = [dada, other_bandit]

    evaluate_static_effects(st, overlay)
    assert dada.is_double_attack_now is True, \
        "他の《山賊》キャラがいるのに【ダブルアタック】を得ていない"


def test_op13_009_static_no_double_attack_alone():
    """負例: 他に《山賊》がいなければ【ダブルアタック】を得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    dada = InPlay.of(repo.get("OP13-009"), sickness=False)
    me.characters = [dada]  # 単独 (自分は exclude_name で除外)

    evaluate_static_effects(st, overlay)
    assert dada.is_double_attack_now is False, \
        "他に《山賊》がいないのに【ダブルアタック】を得てはいけない"


# --------------------------------------------------------------------------- #
#  OP13-013 ヒグマ (CHARACTER 赤 cost1 pow3000):
#    【登場時】相手のパワー0以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op13_013_on_play_ko_power_le_0_ai():
    """【登場時】 相手のパワー0以下キャラを KO、 パワーあるキャラは残る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    zero = InPlay.of(repo.get(_ZERO_POW), sickness=False)  # power 0 (<=0)
    alive = InPlay.of(repo.get(_VICTIM), sickness=False)   # power 2000 (対象外)
    opp.characters = [zero, alive]
    higuma = InPlay.of(repo.get("OP13-013"), sickness=True)
    me.characters = [higuma]

    trigger_on_play(st, me, opp, higuma, overlay)
    _drain(st)

    assert zero not in opp.characters, "パワー0以下の相手キャラが KO されていない"
    assert alive in opp.characters, "パワーがある相手キャラは KO 対象外で残るべき"


def test_op13_013_on_play_no_ko_when_no_zero_power():
    """負例: 相手にパワー0以下キャラがいなければ KO は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    alive = InPlay.of(repo.get(_VICTIM), sickness=False)  # power 2000
    opp.characters = [alive]
    higuma = InPlay.of(repo.get("OP13-013"), sickness=True)
    me.characters = [higuma]

    trigger_on_play(st, me, opp, higuma, overlay)
    _drain(st)
    assert alive in opp.characters, "パワー0以下でないキャラが KO されてはいけない"


# --------------------------------------------------------------------------- #
#  OP13-015 マキノ (CHARACTER 赤 cost1 pow-):
#    【起動メイン】このキャラをレストにできる：自分の「モンキー・Ｄ・ルフィ」1枚までを、
#      このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op13_015_activate_main_pump_luffy_ai():
    """起動メイン: 自身をレスト (コスト) → 自ルフィ +2000 (AI 単一候補で自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    makino = InPlay.of(repo.get("OP13-015"), sickness=False)
    luffy = InPlay.of(repo.get(_LUFFY_C), sickness=False)
    me.characters = [makino, luffy]

    power_before = luffy.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP13-015"]
    assert len(opts) == 1, \
        f"OP13-015 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert luffy.power == power_before + 2000, \
        f"ルフィへの +2000 が反映されていない: {luffy.power} (before {power_before})"
    assert makino.rested is True, "起動メインコストで マキノ がレストされるべき"


def test_op13_015_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    makino = InPlay.of(repo.get("OP13-015"), sickness=False)
    luffy = InPlay.of(repo.get(_LUFFY_C), sickness=False)
    me.characters = [makino, luffy]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP13-015"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP13-015"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op13_015_activate_main_human_luffy_pick():
    """人間 + ルフィ 複数 → target_pick modal が立ち resolve で 1体に +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    makino = InPlay.of(repo.get("OP13-015"), sickness=False)
    a = InPlay.of(repo.get(_LUFFY_C), sickness=False)
    b = InPlay.of(repo.get(_LUFFY_C), sickness=False)
    me.characters = [makino, a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP13-015"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + ルフィ複数で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (ルフィ2体) が 2 件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.power == b_before + 2000, "人間が選んだルフィに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP13-017 モンキー・Ｄ・ドラゴン (CHARACTER 赤 cost6 pow7000):
#    【ターン1回】自分の《革命軍》キャラが相手の効果で場を離れる場合、代わりに
#      このキャラを、このターン中、パワー-2000できる。 (replace_leave)
# --------------------------------------------------------------------------- #
def test_op13_017_replace_leave_self_debuff():
    """replace_leave の do (power_pump self -2000): 代わりに このキャラ (ドラゴン) が -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    dragon = InPlay.of(repo.get("OP13-017"), sickness=False)  # pow7000
    me.characters = [dragon]

    power_before = dragon.power
    do, _ = _do(overlay, "OP13-017", "replace_leave")
    for prim in do:
        execute_effect(prim, st, me, opp, dragon)

    assert dragon.power == power_before - 2000, \
        f"replace_leave で ドラゴン自身の -2000 が反映されていない: {dragon.power} (before {power_before})"
    assert dragon in me.characters, "replace (代替) 成立時 ドラゴンは場に残るべき"
