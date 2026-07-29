# -*- coding: utf-8 -*-
"""OP13 (緑 FILM/麦わらの一味・ドン加速 系 / 青 白ひげ海賊団・ワノ国 系) 効果 回帰テスト
バックフィル (自動生成 wave 127):
OP13-033 / OP13-035 / OP13-037 / OP13-039 / OP13-040 /
OP13-041 / OP13-043 / OP13-044 / OP13-046 / OP13-047 の 10 枚。

目的 (= test_backfill_auto_001〜126.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_ko,
    trigger_on_play,
    try_replace_ko,
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


def _do(overlay, cid, when, must_contain=None):
    """指定 card_id の overlay から when 一致 (+ do[0] に must_contain キー) の効果の do を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") != when:
            continue
        if must_contain is not None and must_contain not in e["do"][0]:
            continue
        return e["do"], e
    raise AssertionError(f"{cid} に when={when} (contain={must_contain}) の効果がない")


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
_NEUTRAL = "OP01-001"        # ロロノア・ゾロ (leader、 超新星/麦わらの一味)
_NONFILM_LEADER = "OP10-099"  # ユースタス・キッド (leader、 FILM/麦わらの一味 無し)
_WB_LEADER = "OP02-001"      # エドワード・ニューゲート (leader、 四皇/白ひげ海賊団)
_VICTIM = "OP01-016"         # ナミ (麦わらの一味 cost1 pow2000 CHARACTER)
_FILLER = "OP01-013"         # サンジ (麦わらの一味 cost2 pow3000 CHARACTER)
_WB_CHARA = "OP13-041"       # イゾウ (青 cost6 pow6000、 特徴 ワノ国/白ひげ海賊団)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave127_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP13-033", "OP13-035", "OP13-037", "OP13-039", "OP13-040",
           "OP13-041", "OP13-043", "OP13-044", "OP13-046", "OP13-047"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP13-033 フランキー (CHARACTER 緑 cost3 pow5000):
#    【KO時】相手のカード2枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op13_033_on_ko_rest_two_opp_ai():
    """【KO時】 相手のキャラ2枚をレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_VICTIM), sickness=False)
    a.rested = False
    b.rested = False
    opp.characters = [a, b]
    opp.don_active = 0
    opp.don_rested = 0

    trigger_on_ko(st, me, opp, repo.get("OP13-033"), overlay)
    _drain(st)

    rested_count = sum(1 for c in opp.characters if c.rested)
    assert rested_count == 2, \
        f"【KO時】に相手キャラ2枚がレストにされていない: rested={rested_count}"


def test_op13_033_rest_human_pick():
    """人間 + 相手キャラ複数 → rest の対象選択 target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [a, b]
    opp.don_active = 0
    opp.don_rested = 0

    do, _ = _do(overlay, "OP13-033", "on_ko")
    execute_effect(do[0], st, me, opp, None)  # 1 枚目の rest

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはアクティブのままであるべき"


# --------------------------------------------------------------------------- #
#  OP13-035 ベポ (CHARACTER 緑 cost5 pow7000):
#    【自分のターン終了時】このキャラか自分のドン‼1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op13_035_end_of_turn_untap_don_ai():
    """【自分のターン終了時】 自分のレストドン1枚をアクティブにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    bepo = InPlay.of(repo.get("OP13-035"), sickness=False)
    me.characters = [bepo]
    me.don_rested = 2
    me.don_active = 0

    do, _ = _do(overlay, "OP13-035", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp, bepo)
    _drain(st)

    assert me.don_active == 1, f"ターン終了時にドン1枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, f"アクティブ化でレストドンが1枚減るべき: {me.don_rested}"


# --------------------------------------------------------------------------- #
#  OP13-037 ロロノア・ゾロ (CHARACTER 緑 cost4 pow5000):
#    【登場時】自リーダーが特徴《FILM》か《麦わらの一味》を持つ場合、自ドン2までアクティブ。
#    【自分のターン終了時】このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op13_037_on_play_untap_two_when_condition_ai():
    """【登場時】 自リーダーが麦わらの一味 → レストドン2アクティブ (条件成立、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # ゾロ leader (麦わらの一味) → 条件成立
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    me.don_active = 0
    zoro = InPlay.of(repo.get("OP13-037"), sickness=True)
    me.characters = [zoro]

    trigger_on_play(st, me, opp, zoro, overlay)
    _drain(st)

    assert me.don_active == 2, f"条件成立でドン2枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, f"アクティブ化でレストドンが2枚減るべき: {me.don_rested}"


def test_op13_037_on_play_no_untap_when_condition_fails():
    """負例: 自リーダーが FILM/麦わらの一味 いずれも無し → ドンアクティブは起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NONFILM_LEADER, overlay)  # キッド (FILM/麦わら 無し)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    me.don_active = 0
    zoro = InPlay.of(repo.get("OP13-037"), sickness=True)
    me.characters = [zoro]

    trigger_on_play(st, me, opp, zoro, overlay)
    _drain(st)

    assert me.don_active == 0, "条件不成立でドンがアクティブになってはいけない"
    assert me.don_rested == 3, "条件不成立でレストドンは減ってはいけない"


def test_op13_037_end_of_turn_untap_self():
    """【自分のターン終了時】 このキャラ (ゾロ) をアクティブにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP13-037"), sickness=False)
    zoro.rested = True  # アタック等でレスト済
    me.characters = [zoro]

    do, _ = _do(overlay, "OP13-037", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp, zoro)

    assert zoro.rested is False, "ターン終了時に このキャラ (ゾロ) がアクティブになっていない"


# --------------------------------------------------------------------------- #
#  OP13-039 ゴムゴムの蛇銃 (EVENT 緑 cost2):
#    【カウンター】相手のレストのコスト4以下のキャラ1枚までを、KOする。
#    【トリガー】このカードの【カウンター】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op13_039_counter_ko_rested_cost4_ai():
    """【カウンター】 相手のレストのコスト4以下キャラ1枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (≤4)
    victim.rested = True
    opp.characters = [victim]

    do, _ = _do(overlay, "OP13-039", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, \
        "相手のレストのコスト4以下キャラが KO されていない"


def test_op13_039_counter_no_ko_when_active():
    """負例: 相手のコスト4以下キャラが アクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    do, _ = _do(overlay, "OP13-039", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


def test_op13_039_trigger_fires_counter_ai():
    """【トリガー】 fire_self_effect で【カウンター】(レスト cost4以下 KO) が発火する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True
    opp.characters = [victim]
    self_ip = InPlay.of(repo.get("OP13-039"), sickness=True)

    do, _ = _do(overlay, "OP13-039", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, self_ip)
    _drain(st)

    assert victim not in opp.characters, \
        "トリガーで【カウンター】(レスト cost4以下 KO) が発火していない"


def test_op13_039_counter_ko_human_pick():
    """人間 + 相手のレスト cost4以下 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP13-039", "counter")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP13-040 強ェとわかってんだから… 始めから全開だ!!! (EVENT 緑 cost1):
#    【メイン】自ドン2レスト：相手のレストのコスト7以下キャラ2枚までは、
#      次の相手のリフレッシュフェイズでアクティブにならない。
#    【カウンター】自リーダーを、このバトル中、パワー+3000。
# --------------------------------------------------------------------------- #
def test_op13_040_main_stay_rested_ai():
    """【メイン】do: 相手のレスト cost7以下キャラを 次リフレッシュで非アクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (≤7)
    victim.rested = True
    opp.characters = [victim]

    do, _ = _do(overlay, "OP13-040", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim.stay_rested_next_refresh is True, \
        "相手のレスト cost7以下キャラに 次リフレッシュ非アクティブ フラグが立っていない"


def test_op13_040_counter_pump_leader():
    """【カウンター】 自リーダーを このバトル中 パワー+3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP13-040", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP13-041 イゾウ (CHARACTER 青 cost6 pow6000):
#    【登場時】カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op13_041_on_play_draw_two_ai():
    """【登場時】 カード2枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    izou = InPlay.of(repo.get("OP13-041"), sickness=True)
    me.characters = [izou]

    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, izou, overlay)
    _drain(st)

    assert len(me.hand) == 2, f"【登場時】に2枚引けていない: hand={len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減っていない"


# --------------------------------------------------------------------------- #
#  OP13-043 お玉 (CHARACTER 青 cost1):
#    【登場時】自分のライフが3枚以下の場合、カード2枚を引き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op13_043_on_play_draw_discard_when_life_le3_ai():
    """【登場時】 自ライフ3以下 → 2ドロー + 手札1捨て (net 手札 +1、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3  # ライフ 3 (≤3、 条件成立)
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    otama = InPlay.of(repo.get("OP13-043"), sickness=True)
    me.characters = [otama]

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    trigger_on_play(st, me, opp, otama, overlay)
    _drain(st)

    # 2 ドロー → 手札 2 → 1 捨て → 手札 1
    assert len(me.hand) == 1, f"2ドロー+1捨て の net 手札 (+1) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減っていない"
    assert len(me.trash) == trash_before + 1, "手札1枚がトラッシュに捨てられていない"


def test_op13_043_on_play_no_effect_when_life_over3():
    """負例: 自ライフが4枚 (>3) なら 条件不成立 → ドロー/捨て は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 4  # ライフ 4 (>3)
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    otama = InPlay.of(repo.get("OP13-043"), sickness=True)
    me.characters = [otama]

    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, otama, overlay)
    _drain(st)

    assert len(me.hand) == 0, "ライフ4 (条件不成立) でドローが起きてはいけない"
    assert len(me.deck) == deck_before, "ライフ4 (条件不成立) でデッキは減ってはいけない"


# --------------------------------------------------------------------------- #
#  OP13-044 クリエル (CHARACTER 青 cost3 pow4000):
#    【アタック時】自分の『白ひげ海賊団』を含む特徴を持つリーダーかキャラ1枚に
#      レストのドン‼1枚までを、付与する。
#    【KO時】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op13_044_on_attack_attach_rested_don_ai():
    """【アタック時】 自 白ひげ リーダー/キャラにレストドン1付与 (AI = リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)  # 白ひげ leader → 候補になる
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    krieg = InPlay.of(repo.get("OP13-044"), sickness=False)
    me.characters = [krieg]

    rested_before = me.don_rested
    attached_before = me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
    do, _ = _do(overlay, "OP13-044", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, krieg)
    _drain(st)

    attached_after = me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
    assert attached_after == attached_before + 1, \
        "白ひげ リーダー/キャラ にレストドン1が付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_op13_044_on_attack_attach_human_pick():
    """人間 + 白ひげ リーダー + 白ひげ キャラ → 付与先を選ぶ target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    krieg = InPlay.of(repo.get("OP13-044"), sickness=False)  # 白ひげ海賊団
    izou = InPlay.of(repo.get(_WB_CHARA), sickness=False)    # イゾウ 白ひげ海賊団
    me.characters = [krieg, izou]

    do, _ = _do(overlay, "OP13-044", "on_attack")
    execute_effect(do[0], st, me, opp, krieg)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    # 候補 = 自リーダー (白ひげ) + イゾウ + クリエル (すべて白ひげ)
    assert len(cands) >= 2, f"白ひげ 付与候補が複数でない: {len(cands)}"
    izou_idx = next(i for i, c in enumerate(cands) if c["iid"] == izou.instance_id)
    resolve_pending_choice(st, [izou_idx])
    _drain(st)
    assert izou.attached_dons == 1, "人間が選んだイゾウにレストドンが付与されていない"


def test_op13_044_on_ko_draw_ai():
    """【KO時】 カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    trigger_on_ko(st, me, opp, repo.get("OP13-044"), overlay)
    _drain(st)

    assert len(me.hand) == 1, f"【KO時】に1枚引けていない: hand={len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP13-046 ビスタ (CHARACTER 青 cost6 pow8000):
#    【ダブルアタック】【ターン1回】このキャラがKOされるか相手の効果で場を離れる場合、
#      代わりに自分の手札から『白ひげ海賊団』を含む特徴を持つカード1枚を捨てることができる。
#      (= replace_leave / optional / cost = 白ひげ 1 枚捨て)
# --------------------------------------------------------------------------- #
def test_op13_046_replace_leave_discard_whitebeard_ai():
    """AI: KO 時、 手札の白ひげカード1枚を捨てて ビスタ が場に残る (置換成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bista = InPlay.of(repo.get("OP13-046"), sickness=False)
    me.characters = [bista]
    me.hand = [repo.get(_WB_CHARA)]  # イゾウ = 白ひげ海賊団 (捨てコスト用)

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, bista, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "白ひげカードを捨てられるのに KO が置換されていない"
    assert bista in me.characters, "置換成立時 ビスタ は場に残るべき"
    assert len(me.hand) == hand_before - 1, "置換コストで白ひげカードが1枚捨てられるべき"


def test_op13_046_replace_leave_no_whitebeard_in_hand():
    """負例: 手札に白ひげカードが無ければ cost 不能 → 置換できない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bista = InPlay.of(repo.get("OP13-046"), sickness=False)
    me.characters = [bista]
    me.hand = [repo.get(_FILLER)]  # サンジ 麦わらの一味 (白ひげ 無し) = 捨てられない

    replaced = try_replace_ko(
        st, me, opp, bista, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "白ひげカードが無いのに置換が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP13-047 フォッサ (CHARACTER 青 cost2 pow3000):
#    自分の『白ひげ海賊団』を含む特徴を持つキャラが相手の効果でKOされる場合、
#    代わりにこのキャラ (フォッサ) をトラッシュに置くことができる。 (= replace_ko / optional)
# --------------------------------------------------------------------------- #
def test_op13_047_replace_ko_protect_whitebeard_ai():
    """AI: 自 白ひげ キャラが相手効果KO → 代わりに フォッサ をトラッシュ (victim 生存)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    fossa = InPlay.of(repo.get("OP13-047"), sickness=False)     # holder
    victim = InPlay.of(repo.get(_WB_CHARA), sickness=False)     # イゾウ 白ひげ (被KO対象)
    me.characters = [fossa, victim]
    trash_before = len(me.trash)

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "自 白ひげ キャラの相手効果KOが置換されていない"
    assert victim in me.characters, "置換成立時 被KO対象 (イゾウ) は場に残るべき"
    assert fossa not in me.characters, "置換コストで フォッサ が場から取り除かれるべき"
    assert len(me.trash) == trash_before + 1, "フォッサ がトラッシュに置かれていない"


def test_op13_047_replace_ko_excludes_battle():
    """負例: バトルKO (by_opp_effect=False) は「相手の効果で」に該当しない → 置換しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    fossa = InPlay.of(repo.get("OP13-047"), sickness=False)
    victim = InPlay.of(repo.get(_WB_CHARA), sickness=False)
    me.characters = [fossa, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, "相手効果以外 (バトル等) のKOを置換してはいけない"


def test_op13_047_replace_ko_human_confirm():
    """人間 actor: replace_ko は 任意 → replace_ko_optional modal が立ち、
    承諾すると フォッサ をトラッシュにして 被KO対象を守る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    fossa = InPlay.of(repo.get("OP13-047"), sickness=False)
    victim = InPlay.of(repo.get(_WB_CHARA), sickness=False)
    me.characters = [fossa, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_ko の 任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 置換する)
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1
    assert victim in me.characters, "人間承諾後 被KO対象 (イゾウ) は場に残るべき"
    assert fossa not in me.characters, "人間承諾後 フォッサ がトラッシュに置かれるべき"
