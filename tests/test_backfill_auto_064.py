# -*- coding: utf-8 -*-
"""OP06 弾 効果 回帰テスト バックフィル (自動生成 wave 064):
OP06-009 / OP06-010 / OP06-011 / OP06-012 / OP06-013 / OP06-014 /
OP06-016 / OP06-017 / OP06-018 / OP06-020 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_063.py と同一方針):
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

# よく使うテスト用カード (テキストの前提固定)
_LEADER = "OP01-001"     # ロロノア・ゾロ (赤、 超新星/麦わらの一味)
_NAMI = "OP01-016"       # ナミ 赤 cost1 power2000 麦わらの一味
_RED_C2 = "ST01-004"     # サンジ 赤 cost2 power4000 麦わらの一味 (汎用フィラー)
_UTA1 = "OP09-002"       # ウタ 赤 cost1 power2000 FILM (rest コスト対象 / FILM 種)
_UTA4 = "OP01-005"       # ウタ 赤 cost4 power4000 FILM (FILM 手札/デッキ種)
_FILM_LEADER = "P-011"   # ウタ 赤 FILM (リーダー、 OP06-010 の FILM 条件成立用)
_BIGPOW = "EB03-003"     # ウタ 赤 cost5 power7000 FILM (元々パワー6000以上の脅威)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_RED_C2)] * 30
    p1.deck = [repo.get(_RED_C2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    return _eff(overlay, cid, when)["do"]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave64_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP06-009", "OP06-010", "OP06-011", "OP06-012", "OP06-013",
           "OP06-014", "OP06-016", "OP06-017", "OP06-018", "OP06-020"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP06-009 シュライヤ (CHARACTER 赤 cost3 power4000 FILM/造船の町 / ブロッカー):
#    【アタック時】/【ブロック時】【ターン1回】このキャラは、次の自分のターン開始時まで、
#      相手のリーダーと同じパワーになる。
# --------------------------------------------------------------------------- #
def test_op06_009_on_attack_base_power_copy_opp_leader():
    """アタック時: 自身の元々のパワーが 相手リーダーと同じになる (次自ターン開始まで)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    shrayer = InPlay.of(repo.get("OP06-009"), sickness=False)  # base 4000
    me.characters = [shrayer]
    assert shrayer.power == 4000, "前提: シュライヤ base power は 4000"

    for prim in _do(overlay, "OP06-009", "on_attack"):
        execute_effect(prim, st, me, opp, shrayer)

    assert shrayer.power == opp.leader.power, \
        f"アタック時に相手リーダーと同じパワーになっていない: {shrayer.power} vs {opp.leader.power}"
    assert shrayer.power != 4000, "元々のパワー 4000 が上書きされていない"


def test_op06_009_on_block_base_power_copy_opp_leader():
    """ブロック時: 同上 (相手リーダーと同じパワー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    shrayer = InPlay.of(repo.get("OP06-009"), sickness=False)
    me.characters = [shrayer]

    for prim in _do(overlay, "OP06-009", "on_block"):
        execute_effect(prim, st, me, opp, shrayer)

    assert shrayer.power == opp.leader.power, \
        f"ブロック時に相手リーダーと同じパワーになっていない: {shrayer.power}"


# --------------------------------------------------------------------------- #
#  OP06-010 ダグラス・バレット (CHARACTER 赤 cost6 power7000 FILM/海賊万博):
#    自分のリーダーが特徴《FILM》を持つ場合、このキャラは【ブロッカー】を得る。(静的)
# --------------------------------------------------------------------------- #
def test_op06_010_static_blocker_when_leader_film():
    """静的: リーダーが FILM なら【ブロッカー】付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _FILM_LEADER, overlay)  # ウタ (FILM リーダー)
    me, _ = st.players[0], st.players[1]
    barrett = InPlay.of(repo.get("OP06-010"), sickness=False)
    me.characters = [barrett]
    evaluate_static_effects(st, overlay)

    assert "ブロッカー" in barrett.static_granted_keywords, \
        "FILM リーダー下で【ブロッカー】が付与されていない"


def test_op06_010_static_no_blocker_when_leader_not_film():
    """静的: リーダーが FILM でなければ【ブロッカー】は付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)  # ゾロ (超新星/麦わらの一味 = FILM でない)
    me, _ = st.players[0], st.players[1]
    barrett = InPlay.of(repo.get("OP06-010"), sickness=False)
    me.characters = [barrett]
    evaluate_static_effects(st, overlay)

    assert "ブロッカー" not in barrett.static_granted_keywords, \
        "非 FILM リーダー下で【ブロッカー】が付与されてはいけない"


# --------------------------------------------------------------------------- #
#  OP06-011 トットムジカ (CHARACTER 赤 cost5 power6000 FILM):
#    【起動メイン】【ターン1回】自分の「ウタ」1枚をレストにできる：このキャラは、
#      このターン中、パワー+5000。
# --------------------------------------------------------------------------- #
def test_op06_011_activate_main_rest_uta_pump():
    """起動メイン: 自分の「ウタ」1枚をレスト (コスト) → 自身 +5000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    tot = InPlay.of(repo.get("OP06-011"), sickness=False)  # power 6000
    uta = InPlay.of(repo.get(_UTA1), sickness=False)        # 「ウタ」 コスト対象
    me.characters = [tot, uta]
    power_before = tot.power

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-011"]
    assert len(opts) == 1, f"OP06-011 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert tot.power == power_before + 5000, \
        f"起動メインで +5000 が乗っていない: {tot.power} (before {power_before})"
    assert uta.rested is True, "コストで「ウタ」がレストされるべき"

    # 【ターン1回】: 再発動不可
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP06-011"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op06_011_activate_main_no_uta_no_pump():
    """自場に「ウタ」がいなければ 任意コスト不能 → 発動しても pump は乗らない (no-op)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    tot = InPlay.of(repo.get("OP06-011"), sickness=False)
    me.characters = [tot]  # ウタ 不在
    power_before = tot.power

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-011"]
    # 起動メイン自体は legal に出る (= 任意コストの成否は fire 時に判定)。
    if opts:
        fire_activate_main(st, me, opp, *opts[0])
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
    assert tot.power == power_before, \
        f"「ウタ」不在なのに +5000 が乗った: {tot.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP06-012 ベアキング (CHARACTER 赤 cost5 power6000 FILM/トランプ海賊団):
#    相手の元々のパワー6000以上の、リーダーかキャラがいる場合、このキャラは
#    バトルでKOされない。(静的)
# --------------------------------------------------------------------------- #
def test_op06_012_static_battle_ko_immune_when_opp_bigpow():
    """静的: 相手に元々P6000以上のキャラがいれば バトルKO耐性 (battle_ko_immune_static)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bear = InPlay.of(repo.get("OP06-012"), sickness=False)
    me.characters = [bear]
    opp.characters = [InPlay.of(repo.get(_BIGPOW), sickness=False)]  # 元々P7000
    evaluate_static_effects(st, overlay)

    assert bear.battle_ko_immune_static is True, \
        "相手に元々P6000以上がいるのに バトルKO耐性が立っていない"


def test_op06_012_static_no_immune_when_no_bigpow():
    """静的: 相手に元々P6000以上がいなければ バトルKO耐性は立たない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bear = InPlay.of(repo.get("OP06-012"), sickness=False)
    me.characters = [bear]
    opp.characters = [InPlay.of(repo.get(_RED_C2), sickness=False)]  # 元々P4000
    evaluate_static_effects(st, overlay)

    assert bear.battle_ko_immune_static is False, \
        "相手に元々P6000以上がいないのに バトルKO耐性が立った"


# --------------------------------------------------------------------------- #
#  OP06-013 モンキー・D・ルフィ (CHARACTER 赤 cost2 power3000 FILM/麦わらの一味):
#    【登場時】自分のデッキの上から3枚を見て、特徴《FILM》を持つカード1枚までを公開し、
#      手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op06_013_on_play_search_film_to_hand_ai():
    """登場時 (AI): デッキ上3枚から FILM カード1枚を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_UTA1)] + [repo.get(_RED_C2)] * 10  # 上に FILM (ウタ) 1 枚

    for prim in _do(overlay, "OP06-013", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-013"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert any(c.card_id == _UTA1 for c in me.hand), \
        "デッキ上3枚から FILM カードが手札に加わっていない"


def test_op06_013_on_play_search_human_pick():
    """登場時 (人間): FILM 候補が複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # 上3枚のうち 2 枚を FILM (ウタ) に
    me.deck = [repo.get(_UTA1), repo.get(_RED_C2), repo.get(_UTA4)] \
        + [repo.get(_RED_C2)] * 10

    execute_effect(_do(overlay, "OP06-013", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-013"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [0])  # 先頭 (ウタ) を選択
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id in (_UTA1, _UTA4) for c in me.hand), \
        "人間が選んだ FILM カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP06-014 ラチェット (CHARACTER 赤 cost1 FILM/メカ島):
#    【相手のアタック時】自分の手札から特徴《FILM》を持つカードを任意の枚数捨ててもよい。
#      捨てたカード1枚につき、自分のリーダーかキャラ1枚は、このバトル中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op06_014_opp_attack_discard_film_buff_ai():
    """相手のアタック時 (AI): FILM を手札から捨て、 捨てた枚数×1000 を team に buff。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_UTA1), repo.get(_UTA4)]  # FILM 2 枚
    buff_before = me.leader.battle_buff

    for prim in _do(overlay, "OP06-014", "opp_attack"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-014"), sickness=False))
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert me.leader.battle_buff == buff_before + 2000, \
        f"FILM 2 枚捨てで +2000 が乗っていない: {me.leader.battle_buff}"
    assert len(me.hand) == 0, "捨てた FILM 2 枚が手札から消えていない"


def test_op06_014_opp_attack_discard_human_pick():
    """相手のアタック時 (人間): FILM 候補 → optional_discard_buff_pick modal が正しい kind +
    候補で立つ。 「捨ててもよい」= 任意なので、 人間が 見送り (0 枚) を選べば pump なしで
    クリーンに解決する (= 人間に決定権)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_UTA1), repo.get(_UTA4)]  # FILM 2 枚
    buff_before = me.leader.battle_buff
    hand_before = len(me.hand)

    execute_effect(_do(overlay, "OP06-014", "opp_attack")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-014"), sickness=False))

    assert st.pending_choice is not None, "人間 + FILM 候補で modal が立たない"
    assert st.pending_choice.get("kind") == "optional_discard_buff_pick", \
        f"kind が optional_discard_buff_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"捨て候補 (FILM 2 枚) が 2 件でない: {len(cands)}"

    resolve_pending_choice(st, [])  # 見送り (= 0 枚捨て、 「捨ててもよい」の任意行使)
    assert st.pending_choice is None, "見送り後も modal が残る"
    assert me.leader.battle_buff == buff_before, \
        f"見送りなのに buff が乗った: {me.leader.battle_buff}"
    assert len(me.hand) == hand_before, "見送りなのに手札が減った"


# --------------------------------------------------------------------------- #
#  OP06-016 レイズ・マックス (CHARACTER 赤 cost1 power2000 FILM/革命軍):
#    【起動メイン】このキャラを持ち主のデッキの下に置くことができる：相手のキャラ1枚までを、
#      このターン中、パワー-3000。
# --------------------------------------------------------------------------- #
def test_op06_016_activate_main_debuff_opp_ai():
    """起動メイン (AI): 相手キャラ1枚を このターン中 パワー-3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    rmax = InPlay.of(repo.get("OP06-016"), sickness=False)
    me.characters = [rmax]
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # power 4000
    opp.characters = [victim]
    power_before = victim.power

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-016"]
    assert len(opts) == 1, f"OP06-016 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])

    assert victim.power == power_before - 3000, \
        f"相手キャラ -3000 が反映されていない: {victim.power} (before {power_before})"


def test_op06_016_activate_main_debuff_human_pick():
    """起動メイン (人間): 相手キャラ複数 → target_pick modal で選択して -3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    rmax = InPlay.of(repo.get("OP06-016"), sickness=False)
    me.characters = [rmax]
    a = InPlay.of(repo.get(_RED_C2), sickness=False)  # power 4000
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # power 2000
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-016"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"相手キャラ候補が 2 件でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.power
    resolve_pending_choice(st, [a_idx])
    assert a.power == a_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP06-017 恋のメテオストライク (EVENT 赤 cost2 FILM/麦わらの一味):
#    【メイン】/【カウンター】自分のライフ1枚を手札に加えることができる：
#      自分のリーダーかキャラ1枚までを、このターン中、パワー+3000。
# --------------------------------------------------------------------------- #
def test_op06_017_main_life_to_hand_pump_ai():
    """メイン (AI): ライフ1枚を手札に加え (コスト) → 自リーダー +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_RED_C2)] * 3
    me.hand = []
    power_before = me.leader.power
    life_before = len(me.life)

    for prim in _do(overlay, "OP06-017", "main"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert me.leader.power == power_before + 3000, \
        f"メインで +3000 が乗っていない: {me.leader.power} (before {power_before})"
    assert len(me.life) == life_before - 1, "コストでライフが1枚減っていない"
    assert len(me.hand) == 1, "ライフ1枚が手札に加わっていない"


def test_op06_017_counter_life_to_hand_pump_ai():
    """カウンター (AI): 同じく ライフ1枚を手札に加え → 自リーダー +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_RED_C2)] * 3
    me.hand = []
    power_before = me.leader.power

    for prim in _do(overlay, "OP06-017", "counter"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert me.leader.power == power_before + 3000, \
        f"カウンターで +3000 が乗っていない: {me.leader.power}"


def test_op06_017_main_human_optional_cost_confirm():
    """メイン (人間): 任意コスト → optional_cost_confirm modal が立ち、 pay で +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_RED_C2)] * 3
    me.hand = []
    power_before = me.leader.power

    execute_effect(_do(overlay, "OP06-017", "main")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # pay (= コストを払って発動)
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert me.leader.power == power_before + 3000, \
        f"人間 pay 後 +3000 が乗っていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP06-018 ゴムゴムの大猿王銃乱打 (EVENT 赤 cost2 FILM/麦わらの一味):
#    【メイン】自分のリーダーかキャラ1枚までを、このターン中、パワー+3000。
#      その後、相手のパワー7000以上のキャラがいる場合、自分のリーダーかキャラ1枚までを、
#      このターン中、パワー+1000。
#    【トリガー】相手のパワー5000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op06_018_main_pump_and_conditional_extra_ai():
    """メイン (AI): 自リーダー +3000。 相手にP7000以上がいれば さらに +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(_BIGPOW), sickness=False)]  # P7000
    power_before = me.leader.power

    for prim in _do(overlay, "OP06-018", "main"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])
    # 2 番目の main 効果 (条件付き +1000) も同 when なので追加実行
    for eff in overlay.get("OP06-018").effects:
        if eff.get("when") == "main" and eff.get("if", {}).get("exists_opp_chara_power_ge"):
            assert eval_condition(eff["if"], st, me), "相手P7000で条件成立のはず"
            for prim in eff["do"]:
                execute_effect(prim, st, me, opp, None)
                while st.pending_choice is not None:
                    resolve_pending_choice(st, [0])

    assert me.leader.power == power_before + 3000 + 1000, \
        f"メイン +3000 と条件付き +1000 が両方乗っていない: {me.leader.power}"


def test_op06_018_trigger_ko_opp_power_le5000_ai():
    """トリガー (AI): 相手のパワー5000以下のキャラ1枚をKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # power 4000 <= 5000
    opp.characters = [victim]

    for prim in _do(overlay, "OP06-018", "trigger"):
        execute_effect(prim, st, me, opp, None)
        while st.pending_choice is not None:
            resolve_pending_choice(st, [0])

    assert victim not in opp.characters, "トリガーで相手のP5000以下キャラがKOされていない"


# --------------------------------------------------------------------------- #
#  OP06-020 ホーディ・ジョーンズ (LEADER 緑 power5000 魚人族/新魚人海賊団):
#    【起動メイン】このリーダーをレストにできる：相手の、コスト3以下のキャラかドン!!1枚までを、
#      レストにする。その後、自分は、このターン中、自分の効果でライフを手札に加えられない。
# --------------------------------------------------------------------------- #
def test_op06_020_leader_activate_main_rest_opp_and_lock_life():
    """起動メイン (AI): 相手コスト3以下キャラをレスト + ライフ→手札 禁止フラグ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP06-020", overlay)  # ホーディ (リーダー)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2 <= 3
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-020"]
    assert len(opts) == 1, f"OP06-020 リーダーの起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    while st.pending_choice is not None:
        resolve_pending_choice(st, [0])

    assert victim.rested is True, "相手のコスト3以下キャラがレストされていない"
    assert me.prevent_self_life_to_hand_until_turn_end is True, \
        "「自効果でライフを手札に加えられない」フラグが立っていない"
    assert me.leader.rested is True, "起動メインコストでリーダーがレストされるべき"

    # 【ターン1回】: 再発動不可
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP06-020"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op06_020_leader_activate_main_human_rest_pick():
    """起動メイン (人間): 相手コスト3以下キャラ複数 → target_pick modal で選択してレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP06-020", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_RED_C2), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-020"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"レスト候補が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [b_idx])
        guard += 1
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
