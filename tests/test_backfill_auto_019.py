# -*- coding: utf-8 -*-
"""EB04 / OP01 弾 効果 回帰テスト バックフィル (自動生成 wave 019):
EB04-052 / EB04-054 / EB04-055 / EB04-057 / EB04-059 / EB04-060 /
OP01-004 / OP01-005 / OP01-007 / OP01-008 の 10 枚。

目的 (= test_backfill_auto_001〜018.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
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
        # ⚠ 2026-08-05: コロン後の条件を conditional / optional_cost_then の中へ移したため、
        #   目的の primitive が入れ子になっている。 平坦化して探す。
        def _flat(arr):
            out = []
            for _p in arr or []:
                if not isinstance(_p, dict):
                    continue
                if "conditional" in _p:
                    out += _flat((_p["conditional"] or {}).get("do"))
                elif "optional_cost_then" in _p:
                    out += _flat((_p["optional_cost_then"] or {}).get("effect"))
                else:
                    out.append(_p)
            return out
        for e in matches:
            if any(needle in prim for prim in _flat(e["do"])):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave19_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB04-052", "EB04-054", "EB04-055", "EB04-057", "EB04-059",
           "EB04-060", "OP01-004", "OP01-005", "OP01-007", "OP01-008"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB04-052 サンジ (CHARACTER 黄 cost4 power4000 エッグヘッド/麦わらの一味):
#    【アタック時】このキャラの元々のパワーは、このターン中、相手のリーダーと同じパワーになる /
#    【KO時】自分のライフが2枚以下の場合、自分の手札からパワー6000以下の黄のキャラカード
#           1枚までを、登場させる
# --------------------------------------------------------------------------- #
def test_eb04_052_sanji_attack_copy_leader_power_ai():
    """アタック時: 自身の元々パワーを 相手リーダーと同じにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)  # opp leader OP01-001 power5000
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("EB04-052"), sickness=False)  # 元々 4000
    me.characters = [attacker]
    power_before = attacker.power
    leader_power = opp.leader.power

    do, _ = _do(overlay, "EB04-052", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)

    assert leader_power != power_before, "テスト前提: 相手リーダーと元々パワーが同値だと差が測れない"
    assert attacker.power == leader_power, \
        f"元々パワーが相手リーダー ({leader_power}) と同じになっていない: {attacker.power}"


def test_eb04_052_sanji_on_ko_play_yellow_ai():
    """KO時: 手札からパワー6000以下の黄キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB04-055")]  # 黄 power5000 (<=6000)
    chars_before = len(me.characters)

    do, _ = _do(overlay, "EB04-052", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-052"), sickness=False))

    assert any(c.card.card_id == "EB04-055" for c in me.characters), \
        "手札の黄キャラ (パワー6000以下) が登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_eb04_052_sanji_on_ko_play_yellow_human_pick():
    """人間 + 手札に黄キャラ複数 → 登場先を選ぶ play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB04-055"), repo.get("EB04-058")]  # 黄 5000 / 黄 6000

    do, _ = _do(overlay, "EB04-052", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB04-052"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2枚でない: {len(cands)}"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert any(c.card.card_id in ("EB04-055", "EB04-058") for c in me.characters), \
        "人間が選んだ黄キャラが登場していない"


# --------------------------------------------------------------------------- #
#  EB04-054 バーソロミュー・くま (CHARACTER 黄 cost7 power7000):
#    【登場時】自分のライフが2枚以下の場合、自分のデッキの上から1枚までを、ライフの上に加える /
#    【KO時】相手のライフの上から1枚までを、持ち主の手札に加える
# --------------------------------------------------------------------------- #
def test_eb04_054_kuma_on_play_deck_to_life_ai():
    """登場時 (ライフ2以下): 自デッキ上1枚をライフへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2  # ライフ2 = 条件成立
    me.deck = [repo.get("ST01-004")] * 5
    deck_before = len(me.deck)
    life_before = len(me.life)

    assert eval_condition({"self_life_le": 2}, st, me) is True, \
        "テスト前提: ライフが2以下でない"
    do, _ = _do(overlay, "EB04-054", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-054"), sickness=True))

    assert len(me.deck) == deck_before - 1, "デッキ上1枚がライフに移っていない"
    assert len(me.life) == life_before + 1, "ライフが1枚増えていない"


def test_eb04_054_kuma_on_ko_steal_opp_life_ai():
    """KO時: 相手のライフ上1枚を相手の手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("ST01-004")]
    opp.hand = []
    life_before = len(opp.life)

    do, _ = _do(overlay, "EB04-054", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-054"), sickness=False))

    assert len(opp.life) == life_before - 1, "相手ライフ上1枚が減っていない"
    assert len(opp.hand) == 1, "相手手札にライフ1枚が加わっていない"


# --------------------------------------------------------------------------- #
#  EB04-055 バーソロミュー・くま (CHARACTER 黄 cost4 power5000 王下七武海/革命軍):
#    【KO時】自分の手札からコスト4以下の特徴《革命軍》を持つキャラカード1枚までを、登場させる /
#    【トリガー】自リーダー《革命軍》 + お互いライフ合計5以下 → このカードを登場
# --------------------------------------------------------------------------- #
def test_eb04_055_kuma_on_ko_play_revolutionary_ai():
    """KO時: 手札からコスト4以下の革命軍キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB04-045")]  # ジニー 黒 cost1 革命軍
    chars_before = len(me.characters)

    do, _ = _do(overlay, "EB04-055", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-055"), sickness=False))

    assert any(c.card.card_id == "EB04-045" for c in me.characters), \
        "手札のコスト4以下革命軍キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_eb04_055_kuma_on_ko_play_revolutionary_human_pick():
    """人間 + 手札に革命軍キャラ複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB04-045"), repo.get("EB03-042")]  # ジニー / コアラ (共に革命軍 cost<=4)

    do, _ = _do(overlay, "EB04-055", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB04-055"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2枚でない: {len(cands)}"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert any(c.card.card_id in ("EB04-045", "EB03-042") for c in me.characters), \
        "人間が選んだ革命軍キャラが登場していない"


def test_eb04_055_kuma_trigger_play_self_ai():
    """トリガー: このカードを登場 (play_self、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB04-055")]  # トリガーで公開されたこのカード
    st.current_source_card_id = "EB04-055"
    chars_before = len(me.characters)

    do, _ = _do(overlay, "EB04-055", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "EB04-055" for c in me.characters), \
        "トリガーで このカードが登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  EB04-057 ベガパンク (CHARACTER 黄 cost2 power- オハラ/科学者):
#    ライフ2以下 → 自分の黄《科学者》キャラすべては相手の効果で場を離れない (静的) /
#    【ドン!!×1】このキャラは【ブロッカー】を得る (静的)
# --------------------------------------------------------------------------- #
def test_eb04_057_vegapunk_static_protect_yellow_scientist_ai():
    """ライフ2以下: 自分の黄《科学者》キャラすべてが 相手効果で離脱不可 (静的、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me = st.players[0]
    me.life = [repo.get("ST01-004")] * 2  # ライフ2 = 条件成立
    vega = InPlay.of(repo.get("EB04-057"), sickness=False)  # 黄 科学者
    gasty = InPlay.of(repo.get("EB01-053"), sickness=False)  # ガスティーノ 黄 科学者
    me.characters = [vega, gasty]

    evaluate_static_effects(st, overlay)

    assert vega.protect_from_opp_effect is True, \
        "ライフ2以下でベガパンク自身が相手効果離脱不可になっていない"
    assert gasty.protect_from_opp_effect is True, \
        "ライフ2以下で他の黄科学者キャラが相手効果離脱不可になっていない"


def test_eb04_057_vegapunk_static_protect_off_when_life_high():
    """ライフ3以上では 離脱不可の静的効果が乗らない (= ライフ2以下条件)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me = st.players[0]
    me.life = [repo.get("ST01-004")] * 4  # ライフ4 = 条件不成立
    gasty = InPlay.of(repo.get("EB01-053"), sickness=False)
    vega = InPlay.of(repo.get("EB04-057"), sickness=False)
    me.characters = [vega, gasty]

    evaluate_static_effects(st, overlay)

    assert gasty.protect_from_opp_effect is False, \
        "ライフ3以上で離脱不可が乗ってはいけない"


def test_eb04_057_vegapunk_static_blocker_with_don_ai():
    """ドン!!×1: ベガパンク自身が【ブロッカー】を得る (静的、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me = st.players[0]
    vega = InPlay.of(repo.get("EB04-057"), sickness=False)
    vega.attached_dons = 1  # ドン!!×1 ゲート成立
    me.characters = [vega]

    evaluate_static_effects(st, overlay)

    assert "ブロッカー" in vega.static_granted_keywords, \
        "ドン!!×1でブロッカーが付与されていない"


def test_eb04_057_vegapunk_static_no_blocker_without_don():
    """ドン!! 未付与では【ブロッカー】が乗らない (= ドン!!×1 ゲート)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me = st.players[0]
    vega = InPlay.of(repo.get("EB04-057"), sickness=False)
    vega.attached_dons = 0
    me.characters = [vega]

    evaluate_static_effects(st, overlay)

    assert "ブロッカー" not in vega.static_granted_keywords, \
        "ドン!! 未付与でブロッカーが乗ってはいけない"


# --------------------------------------------------------------------------- #
#  EB04-059 黒縄・大龍巻 (EVENT 黄 cost6):
#    【メイン】自分のライフの上から1枚を表向きにできる：自分のキャラが相手のキャラより
#             少ない場合、相手のコスト6以下のキャラ1枚までとコスト5以下のキャラ1枚までをKO /
#    【トリガー】カード2枚を引き、自分の手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_eb04_059_kuronawa_main_ko_two_ai():
    """メイン: ライフ1枚表向き + 自キャラ<相手キャラ で 相手2体KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []            # 自キャラ 0
    me.life = [repo.get("ST01-004")] * 2  # 表向きにできるライフ
    a = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ cost3
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    opp.characters = [a, b]       # 相手キャラ 2 (= 自0 < 相手2)
    face_before = me.face_up_life_count

    assert eval_condition({"self_chara_count_lt_opp": True}, st, me) is True, \
        "テスト前提: 自キャラが相手キャラより少なくない"
    do, _ = _do(overlay, "EB04-059", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert a not in opp.characters, "相手のコスト6以下キャラがKOされていない"
    assert b not in opp.characters, "相手のコスト5以下キャラがKOされていない"
    assert me.face_up_life_count == face_before + 1, \
        "コストで自ライフ1枚が表向きになっていない"


def test_eb04_059_kuronawa_main_no_ko_when_not_fewer():
    """自キャラが相手キャラより少なくない場合はKOしない (= 条件節)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    mine = InPlay.of(repo.get("ST01-013"), sickness=False)
    me.characters = [mine]        # 自1
    me.life = [repo.get("ST01-004")] * 2
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]     # 相手1 (= 自1 は 相手1 より少なくない)

    do, _ = _do(overlay, "EB04-059", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim in opp.characters, \
        "自キャラが相手キャラより少なくないのにKOされてはいけない"


def test_eb04_059_kuronawa_trigger_draw_discard_ai():
    """トリガー: 2ドロー + 手札1捨て (AI)。 手札 net +1、 デッキ -2、 トラッシュ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]
    me.deck = [repo.get("ST01-004")] * 5
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    do, _ = _do(overlay, "EB04-059", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, f"手札 net (+2-1) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキから2枚引かれていない"
    assert len(me.trash) == trash_before + 1, "手札1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  EB04-060 ゴムゴムの鷹銃乱打 (EVENT 黄 cost2):
#    【メイン】自分のライフの上か下から1枚を手札に加えることができる：自分の手札から
#             特徴《エッグヘッド》キャラ1枚までをライフの上に表向きで加える。その後、
#             相手のキャラ1枚までを、このターン中、パワー-1000 /
#    【トリガー】カード2枚を引き、自分の手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_eb04_060_takaju_main_life_swap_and_debuff_ai():
    """メイン: ライフ1手札 + エッグヘッドキャラをライフへ + 相手キャラ -1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    me.hand = [repo.get("EB04-052")]  # サンジ エッグヘッド 黄 キャラ
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ power3000
    opp.characters = [victim]
    power_before = victim.power

    do, _ = _do(overlay, "EB04-060", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim.power == power_before - 1000, \
        f"相手キャラの -1000 が反映されていない: {victim.power} (before {power_before})"
    assert any(c.card_id == "EB04-052" for c in me.life), \
        "エッグヘッドキャラがライフの上に加えられていない"


def test_eb04_060_takaju_trigger_draw_discard_ai():
    """トリガー: 2ドロー + 手札1捨て (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-099", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]
    me.deck = [repo.get("ST01-004")] * 5
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    do, _ = _do(overlay, "EB04-060", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, f"手札 net (+2-1) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキから2枚引かれていない"
    assert len(me.trash) == trash_before + 1, "手札1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  OP01-004 ウソップ (CHARACTER 赤 cost2 power3000 麦わらの一味):
#    【ドン!!×1】【自分のターン中】【ターン1回】相手がイベントを発動した時、カード1枚を引く
# --------------------------------------------------------------------------- #
def test_op01_004_usopp_draw_on_opp_event_ai():
    """相手イベント発動時: カード1枚を引く (AI)。 手札 +1、 デッキ -1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 5
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    do, _ = _do(overlay, "OP01-004", "opp_event_or_trigger_fired")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-004"), sickness=False))

    assert len(me.hand) == hand_before + 1, "相手イベント発動時に1枚引けていない"
    assert len(me.deck) == deck_before - 1, "デッキから1枚引かれていない"


# --------------------------------------------------------------------------- #
#  OP01-005 ウタ (CHARACTER 赤 cost4 power4000 FILM):
#    【登場時】自分のトラッシュの「ウタ」以外のコスト3以下の赤のキャラカード1枚までを、手札に加える
# --------------------------------------------------------------------------- #
def test_op01_005_uta_on_play_trash_to_hand_ai():
    """登場時: トラッシュの「ウタ」以外の赤コスト3以下キャラを手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # トラッシュに ウタ (= 除外) と ナミ (赤 cost1、 対象)
    me.trash = [repo.get("OP01-005"), repo.get("OP01-016")]
    me.hand = []

    do, _ = _do(overlay, "OP01-005", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-005"), sickness=True))

    assert any(c.card_id == "OP01-016" for c in me.hand), \
        "赤コスト3以下キャラ (ナミ) が手札に加わっていない"
    assert any(c.card_id == "OP01-005" for c in me.trash), \
        "「ウタ」は除外条件によりトラッシュに残るべき"
    assert not any(c.card_id == "OP01-005" for c in me.hand), \
        "除外対象の「ウタ」が手札に加わってはいけない"


# --------------------------------------------------------------------------- #
#  OP01-007 カリブー (CHARACTER 赤 cost3 power4000 超新星/カリブー海賊団):
#    【KO時】相手のパワー4000以下のキャラ1枚までを、KOする
# --------------------------------------------------------------------------- #
def test_op01_007_caribou_on_ko_ko_low_power_ai():
    """KO時: 相手のパワー4000以下キャラ1枚をKO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ power3000
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-007", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-007"), sickness=False))

    assert victim not in opp.characters, "相手のパワー4000以下キャラがKOされていない"


def test_op01_007_caribou_on_ko_no_target_high_power():
    """相手キャラがパワー4000超なら対象外 → KOされない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ power5000 (>4000)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-007", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-007"), sickness=False))

    assert victim in opp.characters, "パワー4000超のキャラがKOされてはいけない (対象外)"


def test_op01_007_caribou_on_ko_human_pick():
    """人間 + 相手のパワー4000以下キャラ複数 → target_pick modal が立ち resolve でKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-007", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-007"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP01-008 キャベンディッシュ (CHARACTER 赤 cost4 power5000 超新星/美しき海賊団):
#    【登場時】自分のライフ1枚を手札に加えることができる：このキャラは、このターン中、
#             【速攻】を得る
# --------------------------------------------------------------------------- #
def test_op01_008_cavendish_on_play_life_to_hand_rush_ai():
    """登場時: ライフ1枚を手札 + 自身が【速攻】を得る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    me.hand = []
    cavendish = InPlay.of(repo.get("OP01-008"), sickness=True)
    me.characters = [cavendish]
    life_before = len(me.life)

    do, _ = _do(overlay, "OP01-008", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, cavendish)

    assert "速攻" in cavendish.granted_keywords, \
        "登場時の任意コスト支払いで【速攻】が付与されていない"
    assert len(me.life) == life_before - 1, "ライフ1枚が手札に移っていない"
    assert len(me.hand) == 1, "手札にライフ1枚が加わっていない"


def test_op01_008_cavendish_on_play_human_optional_confirm():
    """人間: 任意コスト確認 modal (optional_cost_confirm) が立ち、 承諾で【速攻】が付く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    me.hand = []
    cavendish = InPlay.of(repo.get("OP01-008"), sickness=True)
    me.characters = [cavendish]

    do, _ = _do(overlay, "OP01-008", "on_play")
    execute_effect(do[0], st, me, opp, cavendish)

    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 払う)
    _drain(st, pick=[1])
    assert "速攻" in cavendish.granted_keywords, \
        "人間承諾後に【速攻】が付与されていない"
    assert len(me.hand) == 1, "承諾後にライフ1枚が手札へ移っていない"
