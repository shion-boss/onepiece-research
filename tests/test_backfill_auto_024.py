# -*- coding: utf-8 -*-
"""OP01 弾 効果 回帰テスト バックフィル (自動生成 wave 024):
OP01-080 / OP01-082 / OP01-083 / OP01-084 / OP01-085 / OP01-086 /
OP01-087 / OP01-088 / OP01-089 / OP01-093 の 10 枚。

目的 (= test_backfill_auto_001〜023.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent


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
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。
    needle を指定した場合は do[0] に needle 文字列を含む効果を優先する
    (= 同一 when が複数ある counter/on_play 等の弁別用)。"""
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
def test_all_op01_wave24_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP01-080", "OP01-082", "OP01-083", "OP01-084", "OP01-085",
           "OP01-086", "OP01-087", "OP01-088", "OP01-089", "OP01-093"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP01-080 ミス・ダブルフィンガー(ザラ): 【KO時】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op01_080_double_finger_on_ko_draw_ai():
    """【KO時】カード1枚を引く。 対象選択なし → デッキ-1 / 手札+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 5

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP01-080", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-080"), sickness=False))
    assert len(me.hand) == hand_before + 1, "KO時に1枚引けていない"
    assert len(me.deck) == deck_before - 1, "ドローでデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP01-082 モネ: 【トリガー】自身登場 (play_self)
# --------------------------------------------------------------------------- #
def test_op01_082_monet_trigger_play_self_ai():
    """【トリガー】ライフからめくれた自身を場に登場させる (play_self)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # トリガー発火時、 めくれた自身は trash 相当に置かれ current_source_card_id で参照される
    me.trash = [repo.get("OP01-082")]
    st.current_source_card_id = "OP01-082"

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP01-082", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card.card_id == "OP01-082" for c in me.characters), \
        "トリガー play_self で モネ が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP01-083 Mr.1(ダズ・ボーネス): 【ドン!!×1】【自分のターン中】自リーダー《B・W》なら
#    自トラッシュのイベント2枚につき +1000 (静的)
# --------------------------------------------------------------------------- #
def test_op01_083_mr1_static_power_per_trash_event():
    """静的 (on_attached_don n=1、 自ターン中、 B・W leader): トラッシュのイベント2枚で +1000。
    印刷 3000 + DON1枚(+1000) + 効果(イベント2枚で+1000) = 5000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay)  # クロコダイル (王下七武海/B・W)
    me, opp = st.players[0], st.players[1]
    mr1_def = repo.get("OP01-083")  # power 3000
    mr1 = InPlay.of(mr1_def, sickness=False)
    mr1.attached_dons = 1  # n=1 ゲート成立
    me.characters = [mr1]
    me.trash = [repo.get("OP01-086"), repo.get("OP01-087")]  # イベント2枚 → +1000

    evaluate_static_effects(st, overlay)
    assert mr1.power == mr1_def.power + 1000 + 1000, \
        f"トラッシュ イベント2枚で +1000 が反映されていない: {mr1.power} (base {mr1_def.power})"


def test_op01_083_mr1_static_no_pump_off_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → 効果 pump は乗らない (DON分のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン → self_turn False
    mr1_def = repo.get("OP01-083")
    mr1 = InPlay.of(mr1_def, sickness=False)
    mr1.attached_dons = 1
    me.characters = [mr1]
    me.trash = [repo.get("OP01-086"), repo.get("OP01-087")]

    evaluate_static_effects(st, overlay)
    assert mr1.power == mr1_def.power + 1000, \
        f"相手ターンで効果 pump が乗ってはいけない: {mr1.power} (base {mr1_def.power})"


def test_op01_083_mr1_static_no_pump_wrong_leader():
    """自リーダーが《B・W》でなければ効果不成立 → 効果 pump は乗らない (DON分のみ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # モンキー・D・ルフィ (B・W でない)
    me, opp = st.players[0], st.players[1]
    mr1_def = repo.get("OP01-083")
    mr1 = InPlay.of(mr1_def, sickness=False)
    mr1.attached_dons = 1
    me.characters = [mr1]
    me.trash = [repo.get("OP01-086"), repo.get("OP01-087")]

    evaluate_static_effects(st, overlay)
    assert mr1.power == mr1_def.power + 1000, \
        f"B・W でない leader で効果 pump が乗ってはいけない: {mr1.power}"


# --------------------------------------------------------------------------- #
#  OP01-084 Mr.2ボン・クレー: 【ドン!!×1】【アタック時】デッキ上5枚から《B・W》イベント
#    1枚までを公開手札 → 残りをデッキ下
# --------------------------------------------------------------------------- #
def test_op01_084_bon_clay_attack_search_bw_event_ai():
    """アタック時: デッキ上5枚から《B・W》イベント1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # OP01-088 (砂漠の宝刀) = EVENT / 王下七武海・B・W → 該当。 上5枚に仕込む
    me.deck = [repo.get("OP01-088")] + [repo.get("ST01-004")] * 10
    attacker = InPlay.of(repo.get("OP01-084"), sickness=False)
    attacker.attached_dons = 1  # ドンゲート成立
    me.characters = [attacker]

    do, eff = _do(overlay, "OP01-084", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    assert any(c.card_id == "OP01-088" for c in me.hand), \
        "デッキ上5枚から《B・W》イベントが手札に加わっていない"


def test_op01_084_bon_clay_attack_search_human_modal():
    """人間: デッキ上5枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-088")] + [repo.get("ST01-004")] * 10
    attacker = InPlay.of(repo.get("OP01-084"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]

    do, _ = _do(overlay, "OP01-084", "on_attack")
    execute_effect(do[0], st, me, opp, attacker)
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 該当イベントを選択
    _drain_choices(st)
    assert any(c.card_id == "OP01-088" for c in me.hand), \
        "人間が選んだ《B・W》イベントが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP01-085 Mr.3(ギャルディーノ): 【登場時】自リーダー《B・W》なら 相手コスト4以下キャラ
#    1枚まで、 次の相手ターン終了時までアタック不可
# --------------------------------------------------------------------------- #
def test_op01_085_mr3_on_play_set_cannot_attack_ai():
    """登場時 (B・W leader): 相手コスト4以下キャラを 次の相手ターン終了時まで アタック不可。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay)  # クロコダイル (B・W)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 (<=4)
    assert victim.card.cost <= 4
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-085", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-085"), sickness=True))
    assert victim.cannot_attack_through_opp_turn is True, \
        "相手コスト4以下キャラに 次相手ターン終了までのアタック不可が付与されていない"


def test_op01_085_mr3_on_play_human_target_pick():
    """人間 + 相手コスト4以下キャラ 複数 → target_pick modal が立ち resolve でアタック不可付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-085", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-085"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b.cannot_attack_through_opp_turn is True, \
        "人間が選んだキャラにアタック不可が付与されていない"
    assert a.cannot_attack_through_opp_turn is not True, \
        "選ばなかったキャラにアタック不可が付いてはいけない"


# --------------------------------------------------------------------------- #
#  OP01-086 超過鞭糸 (EVENT): 【カウンター】自リーダー/キャラ1枚 +4000 →
#    その後 アクティブのコスト3以下キャラ1枚まで 持ち主の手札に戻す
# --------------------------------------------------------------------------- #
def test_op01_086_whip_counter_pump_and_return_ai():
    """カウンター: (1) 自リーダー +4000 (AI 既定) (2) アクティブ cost3以下キャラを手札に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=3)
    victim.rested = False  # アクティブ = 対象
    opp.characters = [victim]

    power_before = me.leader.power
    opp_hand_before = len(opp.hand)
    do, _ = _do(overlay, "OP01-086", "counter", needle="power_pump")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
        _drain_choices(st, pick=[0])
    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"
    assert victim not in opp.characters, "アクティブ cost3以下キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻したキャラが持ち主の手札に加わっていない"


def test_op01_086_whip_counter_rested_not_returned():
    """レストのキャラは「アクティブの」対象外 → 手札に戻らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    victim.rested = True  # レスト = 対象外
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-086", "counter", needle="power_pump")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
        _drain_choices(st, pick=[0])
    assert victim in opp.characters, "レストのキャラが手札に戻ってはいけない (アクティブ対象外)"


def test_op01_086_whip_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP01-086", "counter", needle="power_pump")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain_choices(st)
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP01-087 オフィサーエージェント (EVENT): 【カウンター】手札からコスト3以下《B・W》
#    キャラ1枚までを登場
# --------------------------------------------------------------------------- #
def test_op01_087_officer_agent_counter_play_from_hand_ai():
    """カウンター: 手札のコスト3以下《B・W》キャラを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bw = repo.get("OP01-083")  # Mr.1 B・W cost2 (<=3)
    assert "B・W" in (bw.features or "") and bw.cost <= 3
    me.hand = [bw]

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP01-087", "counter", needle="play_from_hand")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-087"), sickness=False))
        _drain_choices(st, pick=[0])
    assert any(c.card.card_id == "OP01-083" for c in me.characters), \
        "手札のコスト3以下《B・W》キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_op01_087_officer_agent_counter_human_play_pick():
    """人間 + 手札にコスト3以下《B・W》複数 → play_from_hand_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-083"), repo.get("OP01-085")]  # ともに B・W cost<=3

    do, _ = _do(overlay, "OP01-087", "counter", needle="play_from_hand")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-087"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[0])
    assert any(c.card.card_id in ("OP01-083", "OP01-085") for c in me.characters), \
        "人間が選んだ《B・W》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP01-088 砂漠の宝刀 (EVENT): 【カウンター】自リーダー/キャラ1枚 +2000 →
#    デッキ上3枚を好きな順に並べ替えデッキ上か下 (look_top_reorder)
# --------------------------------------------------------------------------- #
def test_op01_088_desert_blade_counter_pump_and_reorder_ai():
    """カウンター: (1) 自リーダー +2000 (AI 既定) (2) デッキ上3枚並べ替え (枚数不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP01-088", "counter", needle="power_pump")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
        _drain_choices(st)
    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"
    assert len(me.deck) == deck_before, \
        "look_top_reorder でデッキ枚数が変わってはいけない"


def test_op01_088_desert_blade_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP01-088", "counter", needle="power_pump")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain_choices(st)
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP01-089 三日月形砂丘 (EVENT): 【カウンター】自リーダー《王下七武海》なら
#    コスト5以下のキャラ1枚まで 持ち主の手札に戻す
# --------------------------------------------------------------------------- #
def test_op01_089_crescent_dune_counter_return_ai():
    """カウンター (王下七武海 leader): 相手コスト5以下キャラを持ち主の手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay)  # クロコダイル (王下七武海)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=5)
    assert victim.card.cost <= 5
    opp.characters = [victim]

    opp_hand_before = len(opp.hand)
    do, _ = _do(overlay, "OP01-089", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
        _drain_choices(st, pick=[0])
    assert victim not in opp.characters, "コスト5以下キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻したキャラが持ち主の手札に加わっていない"


def test_op01_089_crescent_dune_counter_return_human_pick():
    """人間 + 相手コスト5以下キャラ 複数 → target_pick modal が立ち resolve で手札に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-089", "counter")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b not in opp.characters, "人間が選んだキャラが手札に戻っていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


# --------------------------------------------------------------------------- #
#  OP01-093 うるティ: 【登場時】①(ドン指定レスト)：ドンデッキからドン1枚までを
#    レストで追加する
# --------------------------------------------------------------------------- #
def test_op01_093_ulti_on_play_add_rested_don_ai():
    """登場時: ドンデッキからレストドン1枚をコストエリアに追加 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    rested_before = me.don_rested
    remaining_before = me.don_remaining_in_deck
    assert remaining_before >= 1, "テスト前提: ドンデッキに残りがある"
    do, _ = _do(overlay, "OP01-093", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-093"), sickness=True))
    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == remaining_before - 1, \
        "ドンデッキが1枚減っていない"
