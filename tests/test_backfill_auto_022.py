# -*- coding: utf-8 -*-
"""OP01 弾 効果 回帰テスト バックフィル (自動生成 wave 022):
OP01-049 / OP01-052 / OP01-054 / OP01-056 / OP01-057 / OP01-058 /
OP01-059 / OP01-062 / OP01-063 / OP01-064 の 10 枚。

目的 (= test_backfill_auto_001〜021.py と同一方針):
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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_self_event_played,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキ filler は OP01-020 (ワノ国、 麦わらの一味 でない) = search/draw フィルタ誤爆防止。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-020")] * 30
    p1.deck = [repo.get("OP01-020")] * 30
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
def test_all_wave22_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP01-049", "OP01-052", "OP01-054", "OP01-056", "OP01-057",
           "OP01-058", "OP01-059", "OP01-062", "OP01-063", "OP01-064"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP01-049 ベポ (CHARACTER 緑 cost4 power4000):
#    【ドン‼×1】【アタック時】自分の手札からコスト4以下の「ベポ」以外の
#    特徴《ハートの海賊団》を持つキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op01_049_bepo_attack_play_heart_pirate_ai():
    """アタック時 (ドン1ゲート): 手札のハートの海賊団 cost4以下キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # ジャンバール (ハートの海賊団 cost4、 バニラ) を手札に
    me.hand = [repo.get("OP01-045")]
    bepo = InPlay.of(repo.get("OP01-049"), sickness=False)
    me.characters = [bepo]
    chars_before = len(me.characters)

    do, eff = _do(overlay, "OP01-049", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, bepo)

    assert any(c.card.card_id == "OP01-045" for c in me.characters), \
        "手札のハートの海賊団キャラ (ジャンバール) が登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"
    assert not any(c.card_id == "OP01-045" for c in me.hand), \
        "登場後も手札にジャンバールが残っている"


def test_op01_049_bepo_attack_human_play_pick():
    """人間 + 手札にハートの海賊団 cost4以下 複数 → play_from_hand modal が立ち resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-045"), repo.get("OP01-045")]  # ジャンバール 2 枚
    bepo = InPlay.of(repo.get("OP01-049"), sickness=False)
    me.characters = [bepo]

    do, _ = _do(overlay, "OP01-049", "on_attack")
    execute_effect(do[0], st, me, opp, bepo)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert any(c.card.card_id == "OP01-045" for c in me.characters), \
        "人間が選んだハートの海賊団キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP01-052 雷ぞう (CHARACTER 緑 cost3 power4000):
#    【アタック時】【ターン1回】自分のレストのキャラが2枚以上いる場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op01_052_raizo_attack_draw_with_two_rested_ai():
    """アタック時 (ターン1回 / 自レストキャラ2枚以上): カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    raizo = InPlay.of(repo.get("OP01-052"), sickness=False)
    r1 = InPlay.of(repo.get("OP01-013"), sickness=False)
    r2 = InPlay.of(repo.get("OP01-016"), sickness=False)
    r1.rested = True
    r2.rested = True
    me.characters = [raizo, r1, r2]
    me.hand = []

    do, eff = _do(overlay, "OP01-052", "on_attack")
    assert eff.get("if", {}).get("self_rested_chara_count_ge") == 2, \
        "overlay の 条件 self_rested_chara_count_ge=2 が無い"
    assert eff.get("cost", {}).get("once_per_turn") is True, \
        "overlay の【ターン1回】マーカーが無い"
    assert eval_all_conditions(eff, st, me, raizo) is True, \
        "テスト前提: 自レストキャラ2枚で条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, raizo)

    assert len(me.hand) == 1, f"アタック時のドローが起きていない: {len(me.hand)}"


def test_op01_052_raizo_no_draw_with_one_rested():
    """自分のレストキャラが1枚しかなければ条件不成立 → ドローしない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    raizo = InPlay.of(repo.get("OP01-052"), sickness=False)
    r1 = InPlay.of(repo.get("OP01-013"), sickness=False)
    r1.rested = True
    active = InPlay.of(repo.get("OP01-016"), sickness=False)  # アクティブ = 数えない
    me.characters = [raizo, r1, active]

    _, eff = _do(overlay, "OP01-052", "on_attack")
    assert eval_all_conditions(eff, st, me, raizo) is False, \
        "自レストキャラ1枚で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP01-054 X・ドレーク (CHARACTER 緑 cost5 power6000):
#    【登場時】相手のレストのコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op01_054_drake_on_play_ko_rested_cost4_ai():
    """登場時: 相手のレストのコスト4以下キャラ1枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (≤4)
    victim.rested = True
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-054", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-054"), sickness=True))

    assert victim not in opp.characters, "相手のレストコスト4以下キャラが KO されていない"


def test_op01_054_drake_on_play_active_not_target():
    """相手のコスト4以下キャラが アクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-054", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-054"), sickness=True))
    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


def test_op01_054_drake_on_play_human_ko_pick():
    """人間 + 相手のレストコスト4以下キャラ複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-054", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-054"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP01-056 降魔の相 (EVENT 緑 cost6):
#    【メイン】相手のレストのコスト5以下のキャラ2枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op01_056_gouma_main_ko_two_rested_ai():
    """メイン: 相手のレストのコスト5以下キャラ2枚を KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-014"), sickness=False)  # ジンベエ cost4 (≤5)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (≤5)
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-056", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert a not in opp.characters, "相手のレストキャラ a が KO されていない"
    assert b not in opp.characters, "相手のレストキャラ b が KO されていない"


def test_op01_056_gouma_main_only_rested_cost5():
    """アクティブ or コスト6以上のキャラは 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    active = InPlay.of(repo.get("OP01-013"), sickness=False)  # rested でない
    active.rested = False
    opp.characters = [active]

    do, _ = _do(overlay, "OP01-056", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert active in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


# --------------------------------------------------------------------------- #
#  OP01-057 桃源白滝 (EVENT 緑 cost1):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
#    その後、自分のキャラ1枚までを、アクティブにする。
#    【トリガー】相手のレストのコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op01_057_tougen_counter_pump_ai():
    """【カウンター】(1) 自リーダー(既定)に このバトル中 +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP01-057", "counter", needle="power_pump")
    execute_effect(do[0], st, me, opp, None)

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op01_057_tougen_counter_untap_ai():
    """【カウンター】(2) 自分のレストキャラ1枚をアクティブにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    friend.rested = True
    me.characters = [friend]

    do, _ = _do(overlay, "OP01-057", "counter", needle="untap_chara")
    execute_effect(do[-1], st, me, opp, None)

    assert friend.rested is False, "自分のレストキャラがアクティブになっていない"


def test_op01_057_tougen_trigger_ko_rested_cost4_ai():
    """【トリガー】相手のレストのコスト4以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    victim.rested = True
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-057", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert victim not in opp.characters, "トリガーで相手レストキャラが KO されていない"


def test_op01_057_tougen_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP01-057", "counter", needle="power_pump")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP01-058 磁気弦 (EVENT 緑 cost2):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。
#    その後、相手のコスト4以下のキャラ1枚までを、レストにする。
#    【トリガー】相手のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op01_058_jikigen_counter_pump_ai():
    """【カウンター】(1) 自リーダー(既定)に このバトル中 +4000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP01-058", "counter", needle="power_pump")
    execute_effect(do[0], st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_op01_058_jikigen_counter_rest_opp_cost4_ai():
    """【カウンター】(2) 相手のコスト4以下キャラ1枚をレストにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (≤4)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-058", "counter", needle="rest")
    execute_effect(do[-1], st, me, opp, None)

    assert victim.rested is True, "相手のコスト4以下キャラがレストされていない"


def test_op01_058_jikigen_trigger_rest_opp_ai():
    """【トリガー】相手のキャラ1枚をレストにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-014"), sickness=False)  # cost4
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-058", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert victim.rested is True, "トリガーで相手キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP01-059 べべんっ‼ (EVENT 緑 cost3):
#    【メイン】自分の手札から特徴《ワノ国》を持つカード1枚を捨てることができる：
#    自分のコスト3以下の特徴《ワノ国》を持つキャラ1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op01_059_beben_main_optional_untap_wano_ai():
    """メイン: ワノ国1枚を捨てる (任意コスト) → ワノ国 cost3以下キャラをアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-020")]  # ヒョウ五郎 ワノ国 = 捨てるコスト
    target = InPlay.of(repo.get("OP01-020"), sickness=False)  # ワノ国 cost2 (≤3)
    target.rested = True
    me.characters = [target]

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP01-059", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before - 1, "任意コストでワノ国カードが1枚捨てられていない"
    assert target.rested is False, "ワノ国 cost3以下キャラがアクティブになっていない"


def test_op01_059_beben_main_human_optional_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾でアクティブ化まで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-020")]
    target = InPlay.of(repo.get("OP01-020"), sickness=False)
    target.rested = True
    me.characters = [target]

    do, _ = _do(overlay, "OP01-059", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, pick=[0])
    assert target.rested is False, "人間承諾後 ワノ国キャラがアクティブになっていない"


# --------------------------------------------------------------------------- #
#  OP01-062 クロコダイル (LEADER 青/紫):
#    【ドン‼×1】自分がイベントを発動した時、自分の手札が4枚以下でかつ、
#    このターン中、このリーダーの効果でカードを引いていない場合、カード1枚を引くことができる。
# --------------------------------------------------------------------------- #
def test_op01_062_crocodile_event_played_draw_ai():
    """自分がイベントを発動した時 (ドン1 / 手札4枚以下): カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)  # リーダー = クロコダイル
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1  # ドン1 ゲート成立
    me.hand = [repo.get("OP01-020")] * 2  # 手札 2 枚 (≤4)
    me.deck = [repo.get("OP01-020")] * 10
    hand_before = len(me.hand)

    trigger_self_event_played(st, me, opp, overlay)

    assert len(me.hand) == hand_before + 1, \
        f"イベント発動時のリーダードローが起きていない: {len(me.hand)}"


def test_op01_062_crocodile_no_draw_hand_over_4():
    """手札が5枚以上なら条件不成立 → ドローしない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-062", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1
    me.hand = [repo.get("OP01-020")] * 5  # 手札 5 枚 (>4)
    me.deck = [repo.get("OP01-020")] * 10
    hand_before = len(me.hand)

    trigger_self_event_played(st, me, opp, overlay)

    assert len(me.hand) == hand_before, \
        f"手札5枚でリーダードローが起きてはいけない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP01-063 アーロン (CHARACTER 青 cost4 power5000):
#    【ドン‼×1】【起動メイン】このキャラをレストにできる：相手の手札1枚を選び、公開する。
#    公開したカードがイベントの場合、相手のライフ1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op01_063_arlong_activate_main_reveal_event_mill_life_ai():
    """起動メイン (ドン1 / 自レストコスト): 相手手札公開 → EVENT なら相手ライフ1枚デッキ下 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    arlong = InPlay.of(repo.get("OP01-063"), sickness=False)
    arlong.attached_dons = 1  # ドン1 ゲート成立
    me.characters = [arlong]
    # 相手手札は EVENT のみ (= 公開したら必ず EVENT)
    opp.hand = [repo.get("OP01-056")] * 3  # 降魔の相 (EVENT)
    opp.life = [repo.get("OP01-020")] * 2
    opp.deck = [repo.get("OP01-020")] * 5

    life_before = len(opp.life)
    deck_before = len(opp.deck)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP01-063"]
    assert len(opts) == 1, f"OP01-063 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert arlong.rested is True, "起動メインコストで アーロン がレストされるべき"
    assert len(opp.life) == life_before - 1, \
        f"公開EVENT時 相手ライフが1枚減っていない: {len(opp.life)}"
    assert len(opp.deck) == deck_before + 1, \
        f"相手ライフがデッキ下に置かれていない: {len(opp.deck)}"


def test_op01_063_arlong_activate_main_non_event_no_mill():
    """公開したカードが非EVENT (CHARACTER) の場合はライフ操作しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    arlong = InPlay.of(repo.get("OP01-063"), sickness=False)
    arlong.attached_dons = 1
    me.characters = [arlong]
    opp.hand = [repo.get("OP01-020")] * 3  # CHARACTER のみ = 非EVENT
    opp.life = [repo.get("OP01-020")] * 2

    life_before = len(opp.life)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP01-063"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert len(opp.life) == life_before, \
        f"非EVENT公開で相手ライフが減ってはいけない: {len(opp.life)}"


# --------------------------------------------------------------------------- #
#  OP01-064 アルビダ (CHARACTER 青 cost2 power3000):
#    【ドン‼×1】【アタック時】自分の手札1枚を捨てることができる：
#    相手のコスト3以下のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op01_064_alvida_attack_optional_bounce_ai():
    """アタック時: 手札1枚捨てる (任意コスト) → 相手のコスト3以下キャラを持ち主の手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-020")]  # 捨てるコスト用
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (≤3)
    opp.characters = [victim]
    opp.hand = []

    hand_before = len(me.hand)
    do, eff = _do(overlay, "OP01-064", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-064"), sickness=False))

    assert victim not in opp.characters, "相手のコスト3以下キャラが場から戻されていない"
    assert any(c.card_id == "OP01-013" for c in opp.hand), \
        "戻したキャラが相手 (持ち主) の手札に加わっていない"
    assert len(me.hand) == hand_before - 1, "任意コストで自分の手札が1枚捨てられていない"


def test_op01_064_alvida_attack_human_optional_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾でバウンスまで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-020")]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]
    opp.hand = []

    do, _ = _do(overlay, "OP01-064", "on_attack")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-064"), sickness=False))

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, pick=[0])
    assert victim not in opp.characters, "人間承諾後 相手キャラが戻されていない"
