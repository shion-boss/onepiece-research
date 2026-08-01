# -*- coding: utf-8 -*-
"""プロモ (P-*) 効果 回帰テスト バックフィル (自動生成 wave 159):
P-058 / P-059 / P-060 / P-062 / P-063 /
P-065 / P-066 / P-067 / P-068 / P-071 の 10 枚。

目的 (= test_backfill_auto_001〜158.py と同一方針):
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
NAMI = "OP01-016"            # ナミ (cost1 power2000) フィラー / 相手キャラ (cost1)
COST2 = "OP01-013"           # サンジ (cost2 power3000) フィラー
COST3 = "P-048"              # アーロン (cost3 power4000) 中コスト
COST4 = "OP11-015"           # モチャ (cost4 power6000) 中コスト (= cost4 対象)
BIG = "OP02-004"             # エドワード・ニューゲート (cost9 power10000) 高コスト
NEUTRAL_LEADER = "OP01-001"  # ロロノア・ゾロ (LEADER)
UTA_LEADER = "ST11-001"      # ウタ (緑 LEADER) = leader_name 条件用
UTA_FILM_CHARA = "OP09-002"  # ウタ (cost1 FILM CHARACTER) = P-058 FILM / P-060 rest コスト用
KYUJA = "PRB02-017"          # ボア・ハンコック (cost5 power7000, 九蛇海賊団)


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
def test_all_wave159_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["P-058", "P-059", "P-060", "P-062", "P-063",
           "P-065", "P-066", "P-067", "P-068", "P-071"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  P-058 風のゆくえ (EVENT):
#    【メイン】自分のリーダーが「ウタ」の場合、このターン終了時、
#    自分の特徴《FILM》を持つキャラすべてを、アクティブにする。
#    【トリガー】自分の特徴《FILM》を持つキャラすべてを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_p058_kaze_main_schedules_at_turn_end_ai():
    """【メイン】(leader=ウタ) → このターン終了時発動を予約 (scheduled_at_self_turn_end +1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    eff = _eff(overlay, "P-058", "main")
    assert eff.get("if", {}).get("leader_name") == "ウタ", \
        "overlay の leader_name=ウタ 条件が無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "リーダー ウタ で条件が成立していない"

    before = len(getattr(me, "scheduled_at_self_turn_end", []) or [])
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    after = len(getattr(me, "scheduled_at_self_turn_end", []) or [])
    assert after == before + 1, \
        f"このターン終了時の発動が予約されていない: {before} -> {after}"


def test_p058_kaze_main_condition_false_non_uta_leader():
    """リーダーが「ウタ」でなければ leader_name 条件 不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)  # ゾロ leader
    me = st.players[0]
    eff = _eff(overlay, "P-058", "main")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "ウタ以外の leader で条件が成立してはいけない"


def test_p058_kaze_trigger_untap_film_chara_ai():
    """【トリガー】自分の《FILM》キャラすべてをアクティブにする。 レストの FILM キャラが active に。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    film = InPlay.of(repo.get(UTA_FILM_CHARA), sickness=False)  # FILM
    film.rested = True
    non_film = InPlay.of(repo.get(COST2), sickness=False)  # FILM でない
    non_film.rested = True
    me.characters = [film, non_film]

    for prim in _eff(overlay, "P-058", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert film.rested is False, "《FILM》キャラがアクティブになっていない"
    assert non_film.rested is True, "《FILM》以外のキャラは対象外 (レストのまま)"


# --------------------------------------------------------------------------- #
#  P-059 世界のつづき (EVENT):
#    【カウンター】自分のリーダーが「ウタ」の場合、自分の場のキャラを任意の枚数手札に
#    戻してもよい。自分のリーダーかキャラ1枚までは、このバトル中、戻したキャラ1枚につき
#    パワー+2000。
# --------------------------------------------------------------------------- #
def test_p059_counter_return_charas_then_pump_ai():
    """【カウンター】(leader=ウタ) AI: pump 対象以外の自キャラを全戻し → 戻し枚数×2000 pump。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    pumper = InPlay.of(repo.get(COST4), sickness=False)   # pump 対象 (= self_inplay)
    extra1 = InPlay.of(repo.get(NAMI), sickness=False)
    extra2 = InPlay.of(repo.get(COST2), sickness=False)
    me.characters = [pumper, extra1, extra2]
    me.hand = []

    eff = _eff(overlay, "P-059", "counter")
    assert eff.get("if", {}).get("leader_name") == "ウタ", \
        "overlay の leader_name=ウタ 条件が無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "リーダー ウタ で条件が成立していない"

    power_before = pumper.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, pumper)  # self_inplay = pump 対象

    # extra1/extra2 (= 2 枚) を戻し → +2000 × 2 = +4000
    assert extra1 not in me.characters and extra2 not in me.characters, \
        "pump 対象以外の自キャラが手札に戻っていない"
    assert pumper in me.characters, "pump 対象キャラは場に残るべき"
    assert len(me.hand) == 2, f"戻したキャラ2枚が手札に加わっていない: {len(me.hand)}"
    assert pumper.power == power_before + 4000, \
        f"戻し2枚で +4000 が反映されていない: {pumper.power} (before {power_before})"


def test_p059_counter_condition_false_non_uta_leader():
    """リーダーが「ウタ」でなければ leader_name 条件 不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me = st.players[0]
    eff = _eff(overlay, "P-059", "counter")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "ウタ以外の leader で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-060 Tot Musica (EVENT):
#    【メイン】自分の「ウタ」1枚をレストにできる：相手のドン!!2枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_p060_totmusica_main_rest_uta_then_rest_opp_don_ai():
    """【メイン】 AI: 自「ウタ」1枚をレスト (コスト) → 相手アクティブドン2枚をレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    uta = InPlay.of(repo.get(UTA_FILM_CHARA), sickness=False)  # name = ウタ
    me.characters = [uta]
    opp.don_active = 3
    opp.don_rested = 0

    for prim in _eff(overlay, "P-060", "main")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert uta.rested is True, "コストで自「ウタ」がレストされていない"
    assert opp.don_active == 1, f"相手アクティブドン2枚がレストされていない: {opp.don_active}"
    assert opp.don_rested == 2, f"相手レストドンが2枚増えていない: {opp.don_rested}"


def test_p060_totmusica_main_cannot_pay_noop():
    """自場に「ウタ」がいなければ コスト不能 → 効果不発 (相手ドン不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get(COST2), sickness=False)]  # ウタでない
    opp.don_active = 3
    opp.don_rested = 0

    for prim in _eff(overlay, "P-060", "main")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert opp.don_active == 3 and opp.don_rested == 0, \
        "コスト不能なのに相手ドンがレストされてはいけない"


def test_p060_totmusica_main_human_optional_cost():
    """人間: 【メイン】 → optional_cost_confirm modal → pay ([1]) で ウタレスト + 相手ドンレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, UTA_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    uta = InPlay.of(repo.get(UTA_FILM_CHARA), sickness=False)
    me.characters = [uta]
    opp.don_active = 3
    opp.don_rested = 0

    for prim in _eff(overlay, "P-060", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st, [0])
    assert uta.rested is True, "承認後に 自「ウタ」がレストされていない"
    assert opp.don_active == 1, "承認後に 相手ドン2枚がレストされていない"


# --------------------------------------------------------------------------- #
#  P-062 ホーディ＆ヒョウゾウ (CHARACTER):
#    【起動メイン】【ターン1回】相手のコスト4以下のキャラ1枚までを、レストにし、
#    このキャラは、このターン中、パワー＋1000。その後、自分のライフの上から1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_p062_hordy_activate_main_rest_pump_life_to_hand_ai():
    """起動メイン: 相手コスト4以下1枚レスト + 自身+1000 + ライフ1枚を手札。 AI 自動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    hordy = InPlay.of(repo.get("P-062"), sickness=False)  # power 6000
    me.characters = [hordy]
    me.life = [repo.get(COST2)] * 2
    me.hand = []
    victim = InPlay.of(repo.get(COST4), sickness=False)  # cost4 (= 対象)
    opp.characters = [victim]

    power_before = hordy.power
    life_before = len(me.life)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "P-062"]
    assert len(opts) == 1, f"P-062 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert victim.rested is True, "相手コスト4以下キャラがレストされていない"
    assert hordy.power == power_before + 1000, \
        f"自身 +1000 が反映されていない: {hordy.power} (before {power_before})"
    assert len(me.life) == life_before - 1, "ライフ上1枚が手札に移っていない (life -1)"
    assert len(me.hand) == 1, "ライフ1枚が手札に加わっていない"


def test_p062_hordy_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    hordy = InPlay.of(repo.get("P-062"), sickness=False)
    me.characters = [hordy]
    me.life = [repo.get(COST2)] * 2

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "P-062"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "P-062"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  P-063 ジンベエ (CHARACTER):
#    【登場時】相手のコスト1以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_p063_jinbe_on_play_rest_cost1_ai():
    """【登場時】 AI: 相手コスト1以下キャラ1枚をレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(NAMI), sickness=False)  # cost1 (= 対象)
    opp.characters = [victim]

    for prim in _eff(overlay, "P-063", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-063"), sickness=True))
    _drain(st, [0])

    assert victim.rested is True, "相手コスト1以下キャラがレストされていない"


def test_p063_jinbe_on_play_high_cost_survives():
    """相手キャラが コスト1超のみなら 対象外 → レストされない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    tough = InPlay.of(repo.get(COST3), sickness=False)  # cost3 (= 対象外)
    opp.characters = [tough]

    for prim in _eff(overlay, "P-063", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-063"), sickness=True))
    _drain(st, [0])

    assert tough.rested is False, "コスト1超のキャラがレストされてはいけない (対象外)"


# --------------------------------------------------------------------------- #
#  P-065 トニートニー・チョッパー (CHARACTER):
#    【アタック時】相手のコスト0のキャラがいる場合、このキャラは、
#    次の自分のターン開始時まで、パワー+2000。
# --------------------------------------------------------------------------- #
def test_p065_chopper_on_attack_pump_when_opp_cost0_ai():
    """【アタック時】(相手コスト0キャラ有) → 自身 +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-065"), sickness=False)  # power 4000
    me.characters = [attacker]
    zero = InPlay.of(repo.get(NAMI), sickness=False)
    zero.base_cost_override = 0  # コスト0 (= 条件成立、 コスト減少で 0 になった状態)
    opp.characters = [zero]

    eff = _eff(overlay, "P-065", "on_attack")
    assert eff.get("if", {}).get("exists_opp_chara_cost_le") == 0, \
        "overlay の 条件 exists_opp_chara_cost_le=0 が無い"
    assert eval_condition(eff["if"], st, me, attacker) is True, \
        "相手コスト0キャラ有 で条件が成立していない"

    power_before = attacker.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, attacker)
    assert attacker.power == power_before + 2000, \
        f"アタック時 自己 +2000 が反映されていない: {attacker.power} (before {power_before})"


def test_p065_chopper_condition_false_no_cost0():
    """相手にコスト0キャラが居なければ 条件 不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("P-065"), sickness=False)
    me.characters = [attacker]
    other = InPlay.of(repo.get(NAMI), sickness=False)  # base_cost 1 (= コスト0でない)
    opp.characters = [other]

    eff = _eff(overlay, "P-065", "on_attack")
    assert eval_condition(eff["if"], st, me, attacker) is False, \
        "コスト0キャラ不在で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-066 ボア・ハンコック (CHARACTER):
#    【自分のターン中】自分の手札が5枚以下の場合、
#    自分の特徴《九蛇海賊団》を持つキャラすべては、パワー+1000。
# --------------------------------------------------------------------------- #
def test_p066_hancock_static_pump_kyuja_when_hand_le5():
    """静的 (自ターン + 手札5以下): 自《九蛇海賊団》キャラすべて +1000。 非該当は不変。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=0)  # 自ターン
    me, opp = st.players[0], st.players[1]
    hancock_def = repo.get("P-066")  # 九蛇, power 5000
    hancock = InPlay.of(hancock_def, sickness=False)
    kyuja2_def = repo.get(KYUJA)     # 九蛇, power 7000
    kyuja2 = InPlay.of(kyuja2_def, sickness=False)
    non_def = repo.get(NAMI)         # 九蛇でない
    non = InPlay.of(non_def, sickness=False)
    me.characters = [hancock, kyuja2, non]
    me.hand = [repo.get(COST2)] * 5  # 手札 5 (= 条件成立)

    evaluate_static_effects(st, overlay)
    assert hancock.power == hancock_def.power + 1000, \
        f"自身 (九蛇) に +1000 が乗っていない: {hancock.power}"
    assert kyuja2.power == kyuja2_def.power + 1000, \
        f"他の九蛇キャラに +1000 が乗っていない: {kyuja2.power}"
    assert non.power == non_def.power, \
        f"九蛇でないキャラに pump が乗ってはいけない: {non.power}"


def test_p066_hancock_static_no_pump_when_hand_high():
    """手札が6枚以上なら 条件不成立 → 九蛇キャラに pump なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay, turn=0)
    me, opp = st.players[0], st.players[1]
    hancock_def = repo.get("P-066")
    hancock = InPlay.of(hancock_def, sickness=False)
    me.characters = [hancock]
    me.hand = [repo.get(COST2)] * 6  # 手札 6 (= 条件不成立)

    evaluate_static_effects(st, overlay)
    assert hancock.power == hancock_def.power, \
        f"手札6枚で効果 pump が乗ってはいけない: {hancock.power}"


# --------------------------------------------------------------------------- #
#  P-067 ユースタス・キッド (CHARACTER):
#    このキャラがレストの場合、相手はキャラの「ユースタス・キッド」以外にアタックできない。
# --------------------------------------------------------------------------- #
def test_p067_kid_static_taunt_when_rested():
    """静的 (self_rested): このキャラがレスト → 「ユースタス・キッド」に attack_taunt。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    kid = InPlay.of(repo.get("P-067"), sickness=False)
    kid.rested = True  # レスト (= 条件成立)
    me.characters = [kid]

    evaluate_static_effects(st, overlay)
    assert kid.attack_taunt is True, \
        "レスト時に「ユースタス・キッド」へ attack_taunt が立っていない"


def test_p067_kid_static_no_taunt_when_active():
    """このキャラがアクティブなら self_rested 不成立 → attack_taunt なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    kid = InPlay.of(repo.get("P-067"), sickness=False)
    kid.rested = False  # アクティブ (= 条件不成立)
    me.characters = [kid]

    evaluate_static_effects(st, overlay)
    assert kid.attack_taunt is False, \
        "アクティブなのに attack_taunt が立ってはいけない"


# --------------------------------------------------------------------------- #
#  P-068 サンジ (CHARACTER):
#    【起動メイン】このキャラをトラッシュに置くことができる：
#    自分のデッキの上から5枚を見て、好きな順番に並び替え、デッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_p068_sanji_activate_main_trash_self_look_reorder_ai():
    """起動メイン: 自身をトラッシュ (コスト) → デッキ上5枚を コスト昇順に並び替え。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("P-068"), sickness=False)
    me.characters = [sanji]
    # 上5枚を コスト バラバラ (9,1,4,2,3) に仕込む → 昇順 (1,2,3,4,9) を期待
    top5 = [repo.get(BIG), repo.get(NAMI), repo.get(COST4),
            repo.get(COST2), repo.get(COST3)]
    me.deck = list(top5) + [repo.get(COST2)] * 15
    deck_before = len(me.deck)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "P-068"]
    assert len(opts) == 1, f"P-068 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert sanji not in me.characters, "コストで P-068 がトラッシュに置かれるべき"
    assert any(c.card_id == "P-068" for c in me.trash), \
        "コストで P-068 がトラッシュに移っていない"
    assert len(me.deck) == deck_before, \
        "look_top_reorder はデッキ枚数を変えてはいけない (見て並べ替えるだけ)"
    costs = [c.cost for c in me.deck[:5]]
    assert costs == sorted(costs), \
        f"デッキ上5枚が コスト昇順に並び替わっていない: {costs}"


# --------------------------------------------------------------------------- #
#  P-071 マルコ (CHARACTER):
#    【KO時】このキャラカードを手札に加えることができる。
# --------------------------------------------------------------------------- #
def test_p071_marco_on_ko_return_self_to_hand_ai():
    """【KO時】 KO された「マルコ」(= トラッシュ) を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # KO 済 = カードは トラッシュ に置かれている状態
    me.trash = [repo.get("P-071")]
    me.hand = []

    for prim in _eff(overlay, "P-071", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-071"), sickness=False))

    assert any(c.card_id == "P-071" for c in me.hand), \
        "KO 時に マルコ が手札へ加わっていない"
    assert not any(c.card_id == "P-071" for c in me.trash), \
        "手札へ加えた マルコ はトラッシュから除かれるべき"


def test_p071_marco_on_ko_no_marco_in_trash_noop():
    """トラッシュに「マルコ」が無ければ 手札に加わらない (filter 一致なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(COST2)]  # マルコでない
    me.hand = []

    for prim in _eff(overlay, "P-071", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-071"), sickness=False))

    assert not any(c.card_id == "P-071" for c in me.hand), \
        "トラッシュに マルコ が無いのに手札へ加わってはいけない"
