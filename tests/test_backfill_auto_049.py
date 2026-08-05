# -*- coding: utf-8 -*-
"""OP04 弾 効果 回帰テスト バックフィル (自動生成 wave 049):
OP04-057 / OP04-058 / OP04-059 / OP04-060 / OP04-061 / OP04-063 /
OP04-064 / OP04-065 / OP04-066 / OP04-067 の 10 枚。

目的 (= test_backfill_auto_001〜048.py と同一方針):
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
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_play,
    trigger_on_self_don_returned_to_deck,
)

ROOT = Path(__file__).resolve().parent.parent

# W7 リーダー (= 特徴《W7》条件成立用)
LEADER_W7 = "OP03-058"   # アイスバーグ (W7/GC)
# B・W リーダー (= 『B・W』を含む特徴条件成立用)
LEADER_BW = "OP04-058"   # クロコダイル (王下七武海/B・W)


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` / optional_cost_then 内 の三形対応)。

    ⚠ 2026-08-05: 公式は 「「：」以前が発動コスト」 (cardqa_st_06)。 コロン後の条件は **効果のみ**
    を gate するので、 overlay ではその条件を `conditional` の中へ移した。
    `optional_cost_then` を持つ効果では **cost を条件の外に出す** 必要があるため、
    conditional は `effect` 配列の中に入る。 条件自体は変わっていないので、
    テストはどの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    def _dig(arr):
        for _p in arr or []:
            if not isinstance(_p, dict):
                continue
            if "conditional" in _p:
                return (_p.get("conditional") or {}).get("if") or {}
            if "optional_cost_then" in _p:
                got = _dig((_p["optional_cost_then"] or {}).get("effect") or [])
                if got:
                    return got
        return {}
    return _dig(eff.get("do") or [])


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める (= サーチ/ドローの混入回避)。"""
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
    """指定 card_id の overlay から when 一致の効果の do 配列 + 効果 dict を返す。"""
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


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op04_wave49_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP04-057", "OP04-058", "OP04-059", "OP04-060", "OP04-061",
           "OP04-063", "OP04-064", "OP04-065", "OP04-066", "OP04-067"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP04-057 龍巻壊風 (EVENT):
#   【カウンター】自リーダー/キャラ1枚 +4000 → その後 コスト1以下キャラ1枚をデッキ下へ
#   【トリガー】コスト6以下のキャラ1枚を手札に戻す
# --------------------------------------------------------------------------- #
def test_op04_057_counter_pump_and_return_to_deck_bottom_ai():
    """AI: カウンター do → 自リーダー(最大パワー)を +4000、 相手コスト1以下キャラをデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 (<=1)
    opp.characters = [victim]
    opp_deck_before = len(opp.deck)
    leader_power_before = me.leader.power

    do, _ = _do(overlay, "OP04-057", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == leader_power_before + 4000, \
        f"カウンターの +4000 が自リーダーに乗っていない: {me.leader.power}"
    assert victim not in opp.characters, "コスト1以下キャラがデッキ下に戻っていない"
    assert len(opp.deck) == opp_deck_before + 1, "相手デッキ下に1枚戻っていない"
    assert opp.deck[-1].card_id == "OP01-016", "戻したカードがデッキ最下にない"


def test_op04_057_counter_power_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → power_pump の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP04-057", "counter")
    execute_effect(do[0], st, me, opp, None)  # power_pump self_inplay

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    power_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == power_before + 4000, "人間が選んだキャラに +4000 が乗っていない"


def test_op04_057_trigger_return_to_hand_ai():
    """トリガー do: 相手コスト6以下キャラ1枚を手札に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (<=6)
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)

    do, _ = _do(overlay, "OP04-057", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "トリガーで相手キャラが場から離れていない"
    assert len(opp.hand) == opp_hand_before + 1, "相手手札に1枚戻っていない"


# --------------------------------------------------------------------------- #
#  OP04-058 クロコダイル (LEADER):
#   【相手のターン中】【ターン1回】自分の場のドンが自分の効果でドンデッキに戻された時、
#     ドンデッキからドン1枚までをアクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op04_058_leader_don_returned_add_active_don_ai():
    """相手ターン中、 自ドンがドンデッキに戻った時 → ドン1枚をアクティブで追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_BW, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手 (P1) のターン中 (= opp_turn 成立)
    me.don_active = 0
    me.don_remaining_in_deck = 8

    trigger_on_self_don_returned_to_deck(st, me, opp, overlay, count=1)

    assert me.don_active == 1, \
        f"相手ターン中のドン返却で アクティブドンが追加されていない: {me.don_active}"
    assert me.don_remaining_in_deck == 7, "ドンデッキから1枚供給されていない"


def test_op04_058_leader_not_on_own_turn():
    """自分のターン中は発火しない (【相手のターン中】限定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_BW, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分 (P0) のターン → opp_turn 不成立
    me.don_active = 0
    me.don_remaining_in_deck = 8

    trigger_on_self_don_returned_to_deck(st, me, opp, overlay, count=1)

    assert me.don_active == 0, "自ターン中は【相手のターン中】効果が発火してはいけない"


# --------------------------------------------------------------------------- #
#  OP04-059 アイスバーグ (CHARACTER):
#   【相手のアタック時】ドン!!-1：自リーダーがW7を持つ場合、このキャラはこのターン中【ブロッカー】を得る
# --------------------------------------------------------------------------- #
def test_op04_059_iceburg_opp_attack_gain_blocker_ai():
    """AI: W7 リーダー時、 相手アタック時 do → 自身が【ブロッカー】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_W7, overlay)  # アイスバーグ (W7)
    me, opp = st.players[0], st.players[1]
    iceburg = InPlay.of(repo.get("OP04-059"), sickness=False)
    me.characters = [iceburg]
    assert "ブロッカー" not in iceburg.granted_keywords

    do, eff = _do(overlay, "OP04-059", "opp_attack")
    assert _cond_of(eff).get("leader_feature") == "W7", \
        "overlay の 条件 leader_feature=W7 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, iceburg)

    assert "ブロッカー" in iceburg.granted_keywords, \
        "相手アタック時に【ブロッカー】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP04-060 クロコダイル (CHARACTER):
#   【登場時】ドン!!-2：B・W リーダーなら デッキ上1枚をライフの上へ
#   【相手のアタック時】【ターン1回】ドン!!-1：1ドロー → 手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_op04_060_crocodile_on_play_put_top_to_life_ai():
    """AI: B・W リーダー時、 登場時 do → デッキ上1枚をライフへ (deck-1 / life+1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_BW, overlay)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    life_before = len(me.life)

    do, eff = _do(overlay, "OP04-060", "on_play", needle="put_top_to_life")
    assert _cond_of(eff).get("leader_feature") == "B・W", \
        "overlay の 条件 leader_feature=B・W が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-060"), sickness=True))

    assert len(me.deck) == deck_before - 1, f"デッキ上1枚がライフへ移っていない: {len(me.deck)}"
    assert len(me.life) == life_before + 1, f"ライフが1枚増えていない: {len(me.life)}"


def test_op04_060_crocodile_opp_attack_draw_then_discard_ai():
    """AI: 相手アタック時 do → 1ドロー後に手札1枚を捨てる (deck-1 / trash+1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_BW, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")]
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    do, _ = _do(overlay, "OP04-060", "opp_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-060"), sickness=False))

    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"
    assert len(me.trash) == trash_before + 1, "手札1枚の捨てが起きていない (trash+1)"


# --------------------------------------------------------------------------- #
#  OP04-061 トム (CHARACTER):
#   【起動メイン】このキャラをトラッシュに置く：W7 リーダーなら ドン1枚をレストで追加
# --------------------------------------------------------------------------- #
def test_op04_061_tom_activate_main_trash_self_add_rested_don_ai():
    """AI: 起動メイン → 自身をトラッシュ (コスト) し、 W7 なら レストドン1枚を追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_W7, overlay)
    me, opp = st.players[0], st.players[1]
    tom = InPlay.of(repo.get("OP04-061"), sickness=False)
    me.characters = [tom]
    me.don_rested = 0
    me.don_remaining_in_deck = 8

    options = list_activate_main_effects(st, me, overlay)
    tom_opts = [(src, eff) for (src, eff) in options
                if src.card.card_id == "OP04-061"]
    assert len(tom_opts) == 1, \
        f"OP04-061 の起動メインが legal に出ない: {len(tom_opts)}"
    src, eff = tom_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert me.don_rested == 1, f"レストドンが1枚追加されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == 7, "ドンデッキから1枚供給されていない"
    assert tom not in me.characters, "コストの自身トラッシュが起きていない (場に残存)"
    assert any(c.card_id == "OP04-061" for c in me.trash), "トラッシュにトムがいない"


# --------------------------------------------------------------------------- #
#  OP04-063 フランキー (CHARACTER):
#   【相手のアタック時】【ターン1回】ドン!!-1：W7 リーダーなら 自リーダー/キャラ1枚 +1000
# --------------------------------------------------------------------------- #
def test_op04_063_franky_opp_attack_pump_ai():
    """AI: W7 リーダー時、 相手アタック時 do → 自リーダー(最大パワー)を +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_W7, overlay)
    me, opp = st.players[0], st.players[1]
    franky = InPlay.of(repo.get("OP04-063"), sickness=False)  # power1000
    me.characters = [franky]
    leader_power_before = me.leader.power

    do, eff = _do(overlay, "OP04-063", "opp_attack")
    assert _cond_of(eff).get("leader_feature") == "W7", \
        "overlay の 条件 leader_feature=W7 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, franky)

    # self_inplay 対象は 自リーダー+キャラ から最大パワーを AI 自動選択 (leader 5000 > franky 1000)
    assert me.leader.power == leader_power_before + 1000, \
        f"相手アタック時の +1000 が乗っていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP04-064 ミス・オールサンデー (CHARACTER):
#   【登場時】ドン1枚をレストで追加 → その後 自場ドン6枚以上なら 1ドロー
# --------------------------------------------------------------------------- #
def test_op04_064_all_sunday_on_play_add_rested_don_then_draw_ai():
    """AI: 登場時 do → レストドン1枚追加、 自場ドン合計6枚以上で 1ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5           # +レストドン1 = 合計6 (= self_don_ge 6 成立)
    me.don_rested = 0
    me.don_remaining_in_deck = 3
    me.hand = []

    do, _ = _do(overlay, "OP04-064", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-064"), sickness=True))

    assert me.don_rested == 1, f"レストドンが1枚追加されていない: {me.don_rested}"
    assert len(me.hand) == 1, "自場ドン6枚以上なのに 1ドローが起きていない"


def test_op04_064_all_sunday_on_play_no_draw_under_6_don():
    """自場ドン合計が6枚未満なら ドローしない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2           # +レストドン1 = 合計3 (< 6)
    me.don_rested = 0
    me.don_remaining_in_deck = 3
    me.hand = []

    do, _ = _do(overlay, "OP04-064", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-064"), sickness=True))

    assert me.don_rested == 1, "レストドン追加は無条件で起きるべき"
    assert len(me.hand) == 0, "ドン6枚未満なのに ドローしている"


# --------------------------------------------------------------------------- #
#  OP04-065 ミス・ゴールデンウィーク(マリアンヌ) (CHARACTER):
#   【登場時】B・W リーダーなら 相手コスト5以下キャラ1枚は次の自分のターン開始時まで
#            アタックできない
# --------------------------------------------------------------------------- #
def test_op04_065_marianne_on_play_set_cannot_attack_ai():
    """AI: B・W リーダー時、 登場時 do → 相手コスト5以下キャラがアタック不能になる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_BW, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=5)
    opp.characters = [victim]
    assert not victim.cannot_attack_through_opp_turn

    do, eff = _do(overlay, "OP04-065", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-065"), sickness=True))

    assert victim.cannot_attack_through_opp_turn is True, \
        "相手コスト5以下キャラがアタック不能になっていない"


def test_op04_065_marianne_on_play_human_pick():
    """人間 + 相手コスト5以下キャラ複数 → target_pick modal が立ち resolve で1枚がアタック不能。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER_BW, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP04-065", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP04-065"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.cannot_attack_through_opp_turn is True, \
        "人間が選んだ相手キャラがアタック不能になっていない"


# --------------------------------------------------------------------------- #
#  OP04-066 ミス・バレンタイン(ミキータ) (CHARACTER):
#   【登場時】デッキ上5枚を見て『B・W』特徴カード1枚を公開し手札へ、 残りをデッキ下へ
# --------------------------------------------------------------------------- #
def test_op04_066_mikita_on_play_search_bw_to_hand_ai():
    """AI: 登場時 do → デッキ上5枚から『B・W』特徴カードを手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bw_card = repo.get("OP14-085")  # ミス・ゴールデンウィーク cost1 (features B・W)
    assert "B・W" in (bw_card.features or ""), "テスト前提: OP14-085 は B・W"
    me.deck = [repo.get("ST01-004")] * 2 + [bw_card] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "OP04-066", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-066"), sickness=True))
    _drain_choices(st)

    assert any(c.card_id == "OP14-085" for c in me.hand), \
        "デッキ上5枚の『B・W』カードが手札に加わっていない"


def test_op04_066_mikita_on_play_search_human_modal():
    """人間: search_top_n modal が立ち resolve で『B・W』カードを手札に加えられる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    bw_card = repo.get("OP14-085")
    me.deck = [bw_card] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "OP04-066", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP04-066"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (B・W カード) を選択
    _drain_choices(st)
    assert any(c.card_id == "OP14-085" for c in me.hand), \
        "人間が選んだ『B・W』カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP04-067 ミス・メリークリスマス(ドロフィー) (CHARACTER):
#   【ブロッカー】 / 【トリガー】ドン!!-1：このカードを登場させる (optional_cost_then→play_self)
# --------------------------------------------------------------------------- #
def test_op04_067_dorophy_trigger_play_self_ai():
    """AI: トリガー do → ドン1枚を払って自身を登場させる (play_self)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # ライフからめくれた自身を trash 相当に置き current_source_card_id で参照させる
    me.trash = [repo.get("OP04-067")]
    st.current_source_card_id = "OP04-067"
    me.don_active = 3  # ドン-1 コスト支払い可能

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP04-067", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP04-067" for c in me.characters), \
        "トリガー play_self で ドロフィー が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"
