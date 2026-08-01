# -*- coding: utf-8 -*-
"""プロモ (P-*) 効果 回帰テスト バックフィル (自動生成 wave 157):
P-033 / P-034 / P-035 / P-036 / P-037 /
P-038 / P-039 / P-042 / P-043 / P-046 の 10 枚。

目的 (= test_backfill_auto_001〜156.py と同一方針):
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

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"           # ナミ (麦わらの一味, cost1 power2000) フィラー / 相手キャラ
COST2 = "OP01-013"          # サンジ (cost2 power3000) フィラー
COST4 = "OP11-015"          # モチャ (cost4 power6000) 中コスト
BIG = "OP02-004"            # エドワード・ニューゲート (cost9 power10000) 高コスト・高パワー
NEUTRAL_LEADER = "OP01-001"  # ロロノア・ゾロ (LEADER)


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
def test_all_wave157_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["P-033", "P-034", "P-035", "P-036", "P-037",
           "P-038", "P-039", "P-042", "P-043", "P-046"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  P-033 モンキー・D・ルフィ:
#    【起動メイン】このキャラを持ち主のデッキの下に置くことができる：カード1枚を引く。
#    (overlay は draw1 のみモデル化 = デッキ下戻しコストは overlay 対象外)
# --------------------------------------------------------------------------- #
def test_p033_luffy_activate_main_draw_ai():
    """起動メイン: カード1枚を引く (AI 自動発動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("P-033"), sickness=False)
    me.characters = [luffy]
    me.hand = []
    me.deck = [repo.get(COST2)] * 10

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    options = list_activate_main_effects(st, me, overlay)
    luffy_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "P-033"]
    assert len(luffy_opts) == 1, \
        f"P-033 の起動メインが legal に出ない: {len(luffy_opts)}"
    fire_activate_main(st, me, opp, *luffy_opts[0])

    assert len(me.hand) == hand_before + 1, "起動メインの draw が起きていない"
    assert len(me.deck) == deck_before - 1, "ドローでデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  P-034 サンジ:
#    【ドン!!×1】【自分のターン中】自分のライフが2枚以下の場合、このキャラはパワー+2000。
# --------------------------------------------------------------------------- #
def test_p034_sanji_static_pump_when_life_le_2():
    """静的 (on_attached_don n=1, 自ターン, ライフ2以下): パワー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=0)  # 自ターン
    me, opp = st.players[0], st.players[1]
    sanji_def = repo.get("P-034")  # power 4000
    sanji = InPlay.of(sanji_def, sickness=False)
    sanji.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [sanji]
    me.life = [repo.get(COST2)] * 2  # ライフ 2 (= 条件成立)

    evaluate_static_effects(st, overlay)
    # 印刷 4000 + DON1枚(+1000) + 効果(+2000) = 7000
    assert sanji.power == sanji_def.power + 1000 + 2000, \
        f"ライフ2以下で +2000 が乗っていない: {sanji.power} (base {sanji_def.power})"


def test_p034_sanji_static_no_pump_when_life_high():
    """ライフが3枚以上なら 条件不成立 → 効果 pump なし (DON分のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=0)
    me, opp = st.players[0], st.players[1]
    sanji_def = repo.get("P-034")
    sanji = InPlay.of(sanji_def, sickness=False)
    sanji.attached_dons = 1
    me.characters = [sanji]
    me.life = [repo.get(COST2)] * 3  # ライフ 3 (= 条件不成立)

    evaluate_static_effects(st, overlay)
    assert sanji.power == sanji_def.power + 1000, \
        f"ライフ3枚で効果 pump が乗ってはいけない: {sanji.power} (base {sanji_def.power})"


# --------------------------------------------------------------------------- #
#  P-035 モンキー・D・ルフィ:
#    【ドン!!×1】【アタック時】自分の手札1枚を捨てることができる：
#    相手のコスト0のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_p035_luffy_on_attack_discard_ko_cost0_ai():
    """【アタック時】 AI: 手札1枚を捨て 相手のコスト0キャラを KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-035"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]
    me.hand = [repo.get(COST2)]  # 捨てるコスト用
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1
    victim.cost_minus_until_turn_end = 1  # 実効コスト 0 (= 対象)
    opp.characters = [victim]

    eff = _eff(overlay, "P-035", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    hand_before = len(me.hand)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])

    assert victim not in opp.characters, "相手のコスト0キャラが KO されていない"
    assert len(me.hand) == hand_before - 1, "任意コストで手札が1枚捨てられていない"


def test_p035_luffy_on_attack_cost1_survives():
    """相手キャラの実効コストが 0 でない (cost1) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-035"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]
    me.hand = [repo.get(COST2)]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 (= 対象外)
    opp.characters = [victim]

    for prim in _eff(overlay, "P-035", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])

    assert victim in opp.characters, "実効コスト1のキャラが KO されてはいけない (対象外)"


def test_p035_luffy_on_attack_human_optional_cost():
    """人間: 【アタック時】 → optional_cost_confirm modal → pay ([1]) で 捨て + KO 解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-035"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]
    me.hand = [repo.get(COST2)]
    victim = InPlay.of(repo.get(NAMI), sickness=False)
    victim.cost_minus_until_turn_end = 1  # 実効コスト 0
    opp.characters = [victim]

    for prim in _eff(overlay, "P-035", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, attacker)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st, [0])
    assert victim not in opp.characters, "承認後に 相手のコスト0キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  P-036 モンキー・D・ルフィ:
#    【アタック時】自分のライフの上か下から1枚を手札に加えることができる：
#    このキャラと自分のリーダー1枚までを、このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_p036_luffy_on_attack_life_to_hand_then_pump_ai():
    """【アタック時】 AI: ライフ1枚を手札 → 自身 + 自リーダー +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-036"), sickness=False)  # power 4000
    me.characters = [attacker]
    me.life = [repo.get(COST2)] * 2
    me.hand = []

    att_before = attacker.power
    leader_before = me.leader.power
    hand_before = len(me.hand)
    life_before = len(me.life)
    for prim in _eff(overlay, "P-036", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])

    assert attacker.power == att_before + 1000, \
        f"自身 +1000 が反映されていない: {attacker.power} (before {att_before})"
    assert me.leader.power == leader_before + 1000, \
        f"自リーダー +1000 が反映されていない: {me.leader.power} (before {leader_before})"
    assert len(me.hand) == hand_before + 1, "任意コストで ライフ→手札 が起きていない"
    assert len(me.life) == life_before - 1, "ライフが1枚減っていない"


def test_p036_luffy_on_attack_human_optional_cost():
    """人間: 【アタック時】 → optional_cost_confirm modal → pay ([1]) で ライフ→手札 + pump。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-036"), sickness=False)
    me.characters = [attacker]
    me.life = [repo.get(COST2)] * 2
    me.hand = []

    att_before = attacker.power
    for prim in _eff(overlay, "P-036", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, attacker)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st, [0])
    assert attacker.power == att_before + 1000, "承認後に 自身 +1000 が反映されていない"
    assert len(me.hand) == 1, "承認後に ライフ→手札 が起きていない"


# --------------------------------------------------------------------------- #
#  P-037 モンキー・D・ルフィ:
#    【アタック時】自分のレストのキャラが2枚以上いる場合、
#    このキャラは、このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_p037_luffy_on_attack_pump_condition():
    """条件 self_rested_chara_count_ge=2: レストキャラ2枚以上で成立、 1枚で不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    eff = _eff(overlay, "P-037", "on_attack")
    assert eff.get("if", {}).get("self_rested_chara_count_ge") == 2, \
        "overlay の 条件 self_rested_chara_count_ge=2 が無い"

    attacker = InPlay.of(repo.get("P-037"), sickness=False)  # power 4000
    r1 = InPlay.of(repo.get(NAMI), sickness=False)
    r2 = InPlay.of(repo.get(NAMI), sickness=False)
    r1.rested = True
    r2.rested = True
    me.characters = [attacker, r1, r2]

    assert eval_condition(eff["if"], st, me, attacker) is True, \
        "レストキャラ2枚で条件が成立していない"

    # レスト1枚にすると不成立
    r2.rested = False
    assert eval_condition(eff["if"], st, me, attacker) is False, \
        "レストキャラ1枚で条件が成立してはいけない"


def test_p037_luffy_on_attack_self_pump_ai():
    """条件成立時 do: このキャラ +1000 (AI 自動、 対象選択なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-037"), sickness=False)
    me.characters = [attacker]

    power_before = attacker.power
    for prim in _eff(overlay, "P-037", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, attacker)

    assert attacker.power == power_before + 1000, \
        f"アタック時 自己 +1000 が反映されていない: {attacker.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  P-038 トラファルガー・ロー:
#    【登場時】自分のリーダー1枚をレストにできる：相手のコスト1以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_p038_law_on_play_rest_leader_ko_cost_le_1_ai():
    """【登場時】 AI: 自リーダーをレストにし 相手のコスト1以下キャラを KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 (= 対象)
    opp.characters = [victim]
    assert me.leader.rested is False

    for prim in _eff(overlay, "P-038", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-038"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手のコスト1以下キャラが KO されていない"
    assert me.leader.rested is True, "任意コストで 自リーダーがレストされていない"


def test_p038_law_on_play_high_cost_survives():
    """相手キャラが コスト1超のみなら KO 対象外 (cost2以下ではなく cost1以下)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    tough = InPlay.of(repo.get(COST2), sickness=False)  # cost2 (= 対象外)
    opp.characters = [tough]

    for prim in _eff(overlay, "P-038", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-038"), sickness=True))
    _drain(st, [0])

    assert tough in opp.characters, "コスト2キャラが KO されてはいけない (対象外)"


def test_p038_law_on_play_human_optional_cost():
    """人間: 【登場時】 → optional_cost_confirm modal → pay ([1]) で レスト + KO 解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1
    opp.characters = [victim]

    for prim in _eff(overlay, "P-038", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-038"), sickness=True))
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st, [0])
    assert victim not in opp.characters, "承認後に 相手のコスト1以下キャラが KO されていない"
    assert me.leader.rested is True, "承認後に 自リーダーがレストされていない"


# --------------------------------------------------------------------------- #
#  P-039 ベラミー:
#    【バニッシュ】【ドン!!×2】自分のライフが0枚の場合、このキャラはパワー+2000。
# --------------------------------------------------------------------------- #
def test_p039_bellamy_static_pump_when_life_zero():
    """静的 (on_attached_don n=2, ライフ0枚): パワー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bellamy_def = repo.get("P-039")  # power 6000
    bellamy = InPlay.of(bellamy_def, sickness=False)
    bellamy.attached_dons = 2  # ドン!!×2 ゲート成立
    me.characters = [bellamy]
    me.life = []  # ライフ 0 (= 条件成立)

    evaluate_static_effects(st, overlay)
    # 印刷 6000 + DON2枚(+2000) + 効果(+2000) = 10000
    assert bellamy.power == bellamy_def.power + 2000 + 2000, \
        f"ライフ0枚で +2000 が乗っていない: {bellamy.power} (base {bellamy_def.power})"


def test_p039_bellamy_static_no_pump_when_life_positive():
    """ライフが1枚以上なら 条件不成立 → 効果 pump なし (DON分のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bellamy_def = repo.get("P-039")
    bellamy = InPlay.of(bellamy_def, sickness=False)
    bellamy.attached_dons = 2
    me.characters = [bellamy]
    me.life = [repo.get(COST2)] * 1  # ライフ 1 (= 条件不成立)

    evaluate_static_effects(st, overlay)
    assert bellamy.power == bellamy_def.power + 2000, \
        f"ライフ1枚で効果 pump が乗ってはいけない: {bellamy.power} (base {bellamy_def.power})"


# --------------------------------------------------------------------------- #
#  P-042 ロロノア・ゾロ:
#    【トリガー】相手のコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_p042_zoro_trigger_ko_cost_le_4_ai():
    """【トリガー】 AI: 相手のコスト4以下キャラ1体を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST4), sickness=False)  # cost4 (= 対象)
    opp.characters = [victim]

    for prim in _eff(overlay, "P-042", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert victim not in opp.characters, "相手のコスト4以下キャラが KO されていない"


def test_p042_zoro_trigger_high_cost_survives():
    """相手キャラが コスト4超のみなら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    tough = InPlay.of(repo.get(BIG), sickness=False)  # cost9 (= 対象外)
    opp.characters = [tough]

    for prim in _eff(overlay, "P-042", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert tough in opp.characters, "コスト4超のキャラが KO されてはいけない (対象外)"


def test_p042_zoro_trigger_ko_human_pick():
    """人間 + 相手のコスト4以下キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(COST4), sickness=False)  # cost4
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "P-042", "trigger")["do"][0], st, me, opp, None)

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


# --------------------------------------------------------------------------- #
#  P-043 モンキー・D・ルフィ:
#    【登場時】コスト3以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_p043_luffy_on_play_return_cost_le_3_ai():
    """【登場時】 AI: 相手のコスト3以下キャラ1体を 持ち主の手札に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST2), sickness=False)  # cost2 (= 対象)
    opp.characters = [victim]
    opp.hand = []

    for prim in _eff(overlay, "P-043", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-043"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手のコスト3以下キャラが手札に戻っていない"
    assert any(c.card_id == COST2 for c in opp.hand), \
        "戻したキャラが持ち主 (相手) の手札に加わっていない"


def test_p043_luffy_on_play_high_cost_survives():
    """相手キャラが コスト3超のみなら 対象外 → 戻らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    tough = InPlay.of(repo.get(COST4), sickness=False)  # cost4 (= 対象外)
    opp.characters = [tough]

    for prim in _eff(overlay, "P-043", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-043"), sickness=True))
    _drain(st, [0])

    assert tough in opp.characters, "コスト3超のキャラが戻ってはいけない (対象外)"


def test_p043_luffy_on_play_return_human_pick():
    """人間 + 相手のコスト3以下キャラ 複数 → target_pick modal が立ち resolve で 1 体を戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(NAMI), sickness=False)   # cost1
    b = InPlay.of(repo.get(COST2), sickness=False)  # cost2
    opp.characters = [a, b]
    opp.hand = []

    execute_effect(_eff(overlay, "P-043", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-043"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが手札に戻っていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  P-046 ヤマト:
#    【登場時】自分の手札すべてを好きな順番でデッキの下に置いてもよい。
#    そうした場合、置いた枚数分カードを引く。
# --------------------------------------------------------------------------- #
def test_p046_yamato_on_play_hand_to_deck_then_draw_ai():
    """【登場時】 AI: 手札すべてをデッキ下 → 同枚数ドロー (= 手札リフレッシュ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # 手札 = NAMI 2 枚、 デッキ top は別カード (= 引いたら手札が入れ替わる)
    me.hand = [repo.get(NAMI), repo.get(NAMI)]
    me.deck = [repo.get(COST2)] * 10
    hand_before = len(me.hand)

    for prim in _eff(overlay, "P-046", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-046"), sickness=True))

    assert len(me.hand) == hand_before, \
        f"置いた枚数分ドローで 手札枚数が保たれていない: {len(me.hand)} (before {hand_before})"
    # 引いたカードは デッキ top (= COST2)、 元手札 (NAMI) は デッキ下
    assert all(c.card_id == COST2 for c in me.hand), \
        "デッキ top から引き直せていない (手札が入れ替わっていない)"
    assert me.deck[-1].card_id == NAMI and me.deck[-2].card_id == NAMI, \
        "元の手札が デッキ「下」(末尾) に置かれていない"


def test_p046_yamato_on_play_empty_hand_noop():
    """手札が0枚なら 置くカードが無く 発動しない (crash せず、 デッキ不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(COST2)] * 10
    deck_before = len(me.deck)

    for prim in _eff(overlay, "P-046", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-046"), sickness=True))

    assert len(me.hand) == 0, "手札0枚では 手札が増えてはいけない"
    assert len(me.deck) == deck_before, "手札0枚では デッキ枚数が変わってはいけない"
