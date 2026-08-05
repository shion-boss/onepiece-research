# -*- coding: utf-8 -*-
"""stale マーカー掃除の回帰テスト — 2026-07-24。

`db/_pending_review.md` の「近似・未実装マーカー」に載っていたが、 実は engine が既に効果を
忠実実装しており overlay の `_doc`/`_approx_note` 注記だけが取り残されていた (= stale) カードを、
「実際に正しく発火する」ことを assert してから注記を削除する。 ここに test がある = 効果が
faithful であることの永続担保。 注記削除は test green を確認してから行う (注記を鵜呑みにしない)。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import eval_condition, evaluate_static_effects, execute_effect, load_effect_overlay

ROOT = Path(__file__).resolve().parent.parent


def _find_char(repo, *, has_slash: bool):
    """属性に「斬」を含む/含まない CHARACTER の card_id を 1 つ返す。"""
    import json
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    cards = cards.get("cards", cards) if isinstance(cards, dict) else cards
    for c in cards:
        cd = repo.get(c["card_id"])
        cat = getattr(cd.category, "name", str(cd.category))
        if cat == "CHARACTER" and cd.attribute:
            if has_slash and "斬" in cd.attribute:
                return cd.card_id
            if not has_slash and "斬" not in cd.attribute:
                return cd.card_id
    return None


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _raw(cid):
    """db/card_effects.json の生 clause リスト (CardEffectBundle でなく dict 列)。"""
    import json
    d = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    return d.get(cid, [])


def _state(repo):
    me = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    return GameState(players=[me, opp], turn_player_idx=0, phase=Phase.MAIN,
                     rng=random.Random(0)), me, opp


def test_p104_protect_when_either_player_has_10_don():
    """P-104 シャンクス: 自分か相手の場のドン!!が10枚ある場合、相手の効果で場を離れない。
    = either_player_don_total_eq_10 条件が忠実 (自10/相手10 の両方で True、 それ以外 False)。"""
    repo = _repo()
    ov = _overlay()
    for self_don, opp_don, expect in [(10, 0, True), (0, 10, True), (6, 6, False), (9, 0, False)]:
        st, me, opp = _state(repo)
        p104 = InPlay.of(repo.get("P-104"), sickness=False)
        me.characters = [p104]
        me.don_active = self_don
        opp.don_active = opp_don
        evaluate_static_effects(st, ov)
        assert p104.protect_from_opp_effect is expect, (
            f"P-104 protect: 自don={self_don} 相手don={opp_don} → "
            f"{p104.protect_from_opp_effect} (期待 {expect})")


def test_op11_088_pump_only_when_attacker_is_slash():
    """OP11-088 シュウ: 相手キャラのアタック時、そのキャラが属性(斬)を持つ場合のみ、
    このバトル中パワー+5000。 opp_attacker_attribute 条件が忠実 (斬のみ発火、 非斬は不発)。"""
    repo = _repo()
    ov = _overlay()
    clause = next(c for c in _raw("OP11-088") if c.get("when") == "opp_attack_on_chara")
    cond = clause.get("if", {})
    pump = clause["do"][0]
    slash = _find_char(repo, has_slash=True)
    nonslash = _find_char(repo, has_slash=False)
    assert slash and nonslash
    for atk_id, should_fire in [(slash, True), (nonslash, False)]:
        st, me, opp = _state(repo)
        shu = InPlay.of(repo.get("OP11-088"), sickness=False)
        me.characters = [shu]
        atk = InPlay.of(repo.get(atk_id), sickness=False)
        opp.characters = [atk]
        st.current_attacker_iid = atk.instance_id
        fires = eval_condition(cond, st, me, opp)
        assert fires is should_fire, f"攻撃者 {atk_id}: 条件={fires} 期待={should_fire}"
        base = shu.power
        if fires:
            execute_effect(pump, st, me, opp, shu)
            assert shu.power == base + 5000, f"斬攻撃者で +5000 が乗っていない: {shu.power}"


def test_op06_048_includes_blocker_trigger_and_mills():
    """OP06-048 ゼフ: 相手がブロッカー『か』イベント発動時にデッキ上4枚トラッシュ。
    = ブロッカー反応 (on_opp_blocker_use) も含む (注記「含まず」は stale)。 mill も発火。"""
    ov = _overlay()
    whens = {c.get("when") for c in _raw("OP06-048")}
    assert "on_opp_blocker_use" in whens and "opp_event_played" in whens, \
        f"OP06-048 は両 trigger を持つべき: {whens}"
    repo = _repo()
    st, me, opp = _state(repo)
    # デッキ上 4 枚を trash する mill_self_top を直接実行して発火を確認
    me.deck = [repo.get("OP01-016") for _ in range(6)]
    me.trash = []
    clause = next(c for c in _raw("OP06-048") if c.get("when") == "on_opp_blocker_use")
    execute_effect(clause["do"][0], st, me, opp, None)
    assert len(me.trash) == 4 and len(me.deck) == 2, \
        f"mill 4 が発火していない: trash={len(me.trash)} deck={len(me.deck)}"


def _rested_char(repo, cost):
    """指定コスト前後の CHARACTER を rested で 1 枚生成。"""
    import json
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    cards = cards.get("cards", cards) if isinstance(cards, dict) else cards
    for c in cards:
        cd = repo.get(c["card_id"])
        cat = getattr(cd.category, "name", str(cd.category))
        if cat == "CHARACTER" and int(getattr(cd, "cost", 0) or 0) == cost:
            ip = InPlay.of(cd, sickness=False)
            ip.rested = True
            return ip
    raise AssertionError(f"cost={cost} の CHARACTER が見つからない")


def test_op14_035_keeps_only_cost_le_4_opp_rested_chara():
    """OP14-035 ヨサク: 相手のレストのコスト4以下のキャラ1枚までを次リフレッシュで非アクティブ化。
    = cost_le:4 が honored (cost5 は対象外)、 かつ don 付与を要求しない (公式は don 無関係)。"""
    repo = _repo()
    ov = _overlay()
    clause = next(c for c in _raw("OP14-035") if c.get("when") == "on_self_rested")
    prim = clause["do"][0]
    st, me, opp = _state(repo)
    low = _rested_char(repo, 3)   # cost3 (対象)
    high = _rested_char(repo, 6)  # cost6 (対象外)
    opp.characters = [high, low]  # high を先頭に置き、 filter が cost で選ぶことを確認
    execute_effect(prim, st, me, opp, None)
    assert low.stay_rested_next_refresh is True, "cost3 の相手キャラが非アクティブ化されていない"
    assert high.stay_rested_next_refresh is False, "cost6 の相手キャラが誤って対象になった (cost_le 無視)"


def test_op15_025_keep_still_requires_don_ge_3_no_regression():
    """OP15-025 (don_ge:3) は cost_le 追加後も回帰しない: don<3 のキャラは対象外。"""
    repo = _repo()
    _raw("OP15-025")  # 存在確認
    st, me, opp = _state(repo)
    c = _rested_char(repo, 3)  # don 未付与 (attached=0)
    opp.characters = [c]
    execute_effect({"keep_opp_rested_chara_with_don_ge_next_refresh": {"don_ge": 3, "limit": 1}},
                   st, me, opp, None)
    assert c.stay_rested_next_refresh is False, "don<3 なのに対象になった (don_ge 回帰)"


def test_op11_077_set_base_cost_timed_next_opp_turn_end():
    """OP11-077 ランドルフ: 次の相手のターン終了時まで コスト+2。
    = set_base_cost_timed の duration=next_opp_turn_end が期限付きで cost を変える (注記 stale)。
    期限解除は game.py:590 で保証済 (applier 追跡込み)。"""
    repo = _repo()
    st, me, opp = _state(repo)
    tgt = _rested_char(repo, 3)
    tgt.rested = False
    me.characters = [tgt]
    base = int(tgt.card.cost)
    execute_effect({"set_base_cost_timed": {"target": {"type": "one_self_chara_filtered",
                    "filter": {}}, "delta": 2, "duration": "next_opp_turn_end"}},
                   st, me, opp, None)
    assert tgt.next_opp_turn_end_base_cost_override == base + 2, (
        f"cost+2 (next_opp_turn_end) が反映されていない: "
        f"{tgt.next_opp_turn_end_base_cost_override} (期待 {base + 2})")
    assert tgt.next_opp_turn_end_base_cost_override_applier_idx >= 0, "期限解除用の applier 追跡が無い"


def test_op05_053_pump_on_effect_draw():
    """OP05-053 モザンビア: 自分がドローフェイズ以外で引いた時 +2000。
    = 効果ドロー (do-primitive draw) が on_self_draw_non_draw_phase を発火 → +2000 (注記 stale)。"""
    repo = _repo()
    ov = _overlay()
    st, me, opp = _state(repo)
    st.effects_overlay = ov          # trigger 発火に overlay が要る
    st.turn_player_idx = 0           # 自分のターン (if self_turn)
    moz = InPlay.of(repo.get("OP05-053"), sickness=False)
    me.characters = [moz]
    me.deck = [repo.get("OP01-016") for _ in range(3)]
    base = moz.power
    execute_effect({"draw": 1}, st, me, opp, None)
    assert moz.power == base + 2000, (
        f"効果ドローで OP05-053 に +2000 が乗らない: {moz.power} (期待 {base + 2000})")


def test_op15_026_attach_opp_rested_don_to_opp_chara():
    """OP15-026 ジャンゴ 起動メイン: 相手のキャラ1枚に相手のレストのドン1枚までを付与。
    = attach_rested_don to_opp (相手 don → 相手 char) が忠実 (旧: 自 don→相手 char で有害→無効化)。"""
    repo = _repo()
    clause = next(c for c in _raw("OP15-026") if c.get("when") == "activate_main")
    prim = clause["do"][0]
    assert "attach_rested_don" in prim and prim["attach_rested_don"].get("to_opp") is True
    st, me, opp = _state(repo)
    oc = _rested_char(repo, 3)
    oc.rested = False
    opp.characters = [oc]
    opp.don_rested = 2
    before = oc.attached_dons
    execute_effect(prim, st, me, opp, None)
    assert oc.attached_dons == before + 1, "相手キャラに相手 don が付与されていない"
    assert opp.don_rested == 1, "相手のレスト don が消費されていない (自 don を使っていないか)"


def test_op14_001_swap_self_base_power():
    """OP14-001 ロー 起動メイン: 自分の超新星/ハートの海賊団キャラ2枚の元々のパワーを入れ替える。
    = swap_self_power 新 primitive (turn_base_power_override を 2 枚で交換)。"""
    import json
    repo = _repo()
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    cards = cards.get("cards", cards) if isinstance(cards, dict) else cards
    sn = []
    for c in cards:
        cd = repo.get(c["card_id"])
        cat = getattr(cd.category, "name", str(cd.category))
        if cat == "CHARACTER" and getattr(cd, "features", None) and "超新星" in cd.features:
            sn.append(cd)
    a = sn[0]
    b = next(x for x in sn if int(x.power or 0) != int(a.power or 0))
    st, me, opp = _state(repo)
    ia = InPlay.of(a, sickness=False)
    ib = InPlay.of(b, sickness=False)
    me.characters = [ia, ib]
    pa, pb = ia.power, ib.power
    assert pa != pb
    prim = _raw("OP14-001")[0]["do"][0]
    execute_effect(prim, st, me, opp, None)
    assert {ia.power, ib.power} == {pa, pb} and ia.power == pb and ib.power == pa, (
        f"元々のパワーが入れ替わっていない: {pa},{pb} → {ia.power},{ib.power}")


def test_op07_001_move_attached_don_to_one_chara():
    """OP07-001: 自分の付与済ドン合計2枚までを自分のキャラ1枚に付与 (= 再配分)。
    付与先は選択、 source は付与済の他キャラから移動 (合計が保存)。"""
    repo = _repo()
    st, me, opp = _state(repo)
    tgt = _rested_char(repo, 4)
    tgt.rested = False
    tgt.attached_dons = 0
    me.characters = [tgt]          # 付与先 = 唯一のキャラ (target 一意)
    me.leader.attached_dons = 2    # source = leader の付与済ドン (leader は target になれない)
    prim = _raw("OP07-001")[0]["do"][0]
    execute_effect(prim, st, me, opp, None)
    assert tgt.attached_dons == 2, f"付与先に 2 枚移動していない: {tgt.attached_dons}"
    assert me.leader.attached_dons == 0, f"source(leader) から抜けていない: {me.leader.attached_dons}"


def _find_by_cat(repo, cat_name, *, power_le=None):
    import json
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    cards = cards.get("cards", cards) if isinstance(cards, dict) else cards
    for c in cards:
        cd = repo.get(c["card_id"])
        cat = getattr(cd.category, "name", str(cd.category))
        if cat == cat_name:
            if power_le is None:
                return cd.card_id
            p = int(getattr(cd, "power", 0) or 0)
            if 0 < p <= power_le:
                return cd.card_id
    return None


def test_op12_001_reveal_two_events_pump_low_power_chara():
    """OP12-001: 手札からイベント2枚を公開する(cost) → 元々パワー4000以下のキャラ+2000。
    = reveal_hand_with_filter cost + power_pump(power_le:4000)。 イベント不足なら不発。"""
    repo = _repo()
    ev = _find_by_cat(repo, "EVENT")
    lo = _find_by_cat(repo, "CHARACTER", power_le=4000)
    prim = _raw("OP12-001")[0]["do"][0]
    # (1) イベント2枚あり → 発火
    st, me, opp = _state(repo)
    chara = InPlay.of(repo.get(lo), sickness=False)
    me.characters = [chara]
    me.hand = [repo.get(ev), repo.get(ev)]
    base = chara.power
    execute_effect(prim, st, me, opp, None)
    assert chara.power == base + 2000, f"イベント2枚公開で +2000 が乗らない: {chara.power}"
    # (2) イベント1枚のみ → cost 払えず不発
    st2, me2, opp2 = _state(repo)
    ch2 = InPlay.of(repo.get(lo), sickness=False)
    me2.characters = [ch2]
    me2.hand = [repo.get(ev)]
    b2 = ch2.power
    execute_effect(prim, st2, me2, opp2, None)
    assert ch2.power == b2, f"イベント不足なのに発火した: {ch2.power}"


def test_op16_080_all_self_chara_cost_plus_1_only_on_opp_turn():
    """OP16-080 ティーチ(leader): 【相手のターン中】自分のキャラすべてをコスト+1。
    = set_base_cost_filtered_static(scope self, delta +1) を if opp_turn で静的評価 (相手ターン限定)。"""
    repo = _repo()
    ov = _overlay()
    chid = _find_by_cat(repo, "CHARACTER")
    for turn_idx, expect_plus in [(1, True), (0, False)]:
        me = Player(name="me", leader=InPlay.of(repo.get("OP16-080"), sickness=False))
        opp = Player(name="opp", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        st = GameState(players=[me, opp], turn_player_idx=turn_idx, phase=Phase.MAIN,
                       rng=random.Random(0))
        ch = InPlay.of(repo.get(chid), sickness=False)
        me.characters = [ch]
        base = int(ch.card.cost)
        evaluate_static_effects(st, ov)
        eff = ch.base_cost_override if ch.base_cost_override is not None else base
        assert (eff == base + 1) is expect_plus, (
            f"turn_idx={turn_idx}: cost {base}→{eff} (opp_turn 限定でない)")


def _straw_char(repo):
    import json
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    cards = cards.get("cards", cards) if isinstance(cards, dict) else cards
    for c in cards:
        cd = repo.get(c["card_id"])
        cat = getattr(cd.category, "name", str(cd.category))
        if cat == "CHARACTER" and getattr(cd, "features", None) and "麦わらの一味" in cd.features:
            return cd.card_id
    return None


def test_op09_080_stage_triggers_on_opp_non_ko_leave():
    """OP09-080 サニー号(stage): 自分の麦わらキャラが相手の効果で場を離れた時(KO以外も)、
    ステージをレストにして don!! デッキから 1 枚をレストで追加。
    = on_self_chara_leave_by_opp_effect trigger + _enqueue_field_when が stages を含む修正。"""
    repo = _repo()
    ov = _overlay()
    straw = _straw_char(repo)
    assert straw
    for kind in ["return_to_hand", "return_to_deck_bottom"]:
        me = Player(name="me", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        opp = Player(name="opp", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        st = GameState(players=[me, opp], turn_player_idx=1, phase=Phase.MAIN,
                       rng=random.Random(0))
        st.effects_overlay = ov
        stage = InPlay.of(repo.get("OP09-080"), sickness=False)
        me.stages = [stage]
        me.characters = [InPlay.of(repo.get(straw), sickness=False)]
        me.don_remaining_in_deck = 5
        d0 = me.don_rested
        # 相手 (actor=opp) が me の麦わらキャラを離脱させる
        execute_effect({kind: "one_opponent_character_any"}, st, opp, me, None)
        assert me.don_rested == d0 + 1, f"{kind}: 相手離脱で OP09-080 が発火せず (don +{me.don_rested - d0})"
        assert stage.rested is True, f"{kind}: コスト (ステージ rest) が払われていない"


def _pow8000_counter_char(repo):
    import json
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    cards = cards.get("cards", cards) if isinstance(cards, dict) else cards
    for c in cards:
        cd = repo.get(c["card_id"])
        cat = getattr(cd.category, "name", str(cd.category))
        if cat == "CHARACTER" and int(getattr(cd, "power", 0) or 0) == 8000 and int(getattr(cd, "counter", 0) or 0) > 0:
            return cd
    return None


def test_op16_118_hand_power8000_counter_plus_2000():
    """OP16-118 エース: 自分の手札のパワー8000のキャラカードすべては、カウンター+2000。
    = set_hand_counter_boost 静的 + _spend_counters が適用。 OP16-118 不在なら非適用。"""
    from engine.game import _spend_counters
    repo = _repo()
    ov = _overlay()
    c8 = _pow8000_counter_char(repo)
    assert c8 is not None
    base_counter = int(c8.counter or 0)
    # (1) OP16-118 が場 → +2000
    me = Player(name="me", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="opp", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    st = GameState(players=[me, opp], turn_player_idx=1, phase=Phase.MAIN, rng=random.Random(0))
    me.characters = [InPlay.of(repo.get("OP16-118"), sickness=False)]
    me.hand = [c8]
    evaluate_static_effects(st, ov)
    assert _spend_counters(me, (0,)) == base_counter + 2000
    # (2) OP16-118 不在 → 素の counter (boost なし)
    me2 = Player(name="me2", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp2 = Player(name="opp2", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    st2 = GameState(players=[me2, opp2], turn_player_idx=1, phase=Phase.MAIN, rng=random.Random(0))
    me2.hand = [c8]
    evaluate_static_effects(st2, ov)
    assert _spend_counters(me2, (0,)) == base_counter, "OP16-118 不在なのに boost された"


def test_op12_036_cannot_be_played_from_hand_via_effect():
    """OP12-036 ゾロ: 手札のこのカードは効果で登場できない。
    = play_from_hand / play_from_hand_or_trash の手札候補から除外 (通常登場は別経路で不変)。"""
    from engine.core import Category  # noqa: F401
    repo = _repo()
    ov = _overlay()
    st, me, opp = _state(repo)
    st.effects_overlay = ov
    me.hand = [repo.get("OP12-036")]
    # 効果で「手札からキャラ1枚を登場」 → OP12-036 は候補外
    execute_effect({"play_from_hand": {"filter": {}, "limit": 1}}, st, me, opp, None)
    assert not any(c.card.card_id == "OP12-036" for c in me.characters), \
        "OP12-036 が効果 (play_from_hand) で登場してしまった"
    # play_from_hand_or_trash の手札からも除外 (トラッシュからは可)
    st2, me2, opp2 = _state(repo)
    st2.effects_overlay = ov
    me2.hand = [repo.get("OP12-036")]
    execute_effect({"play_from_hand_or_trash": {"filter": {}, "limit": 1}}, st2, me2, opp2, None)
    assert not any(c.card.card_id == "OP12-036" for c in me2.characters), \
        "OP12-036 が play_from_hand_or_trash (手札) で登場してしまった"


def _char_of_cost(repo, cost):
    import json
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    cards = cards.get("cards", cards) if isinstance(cards, dict) else cards
    for c in cards:
        cd = repo.get(c["card_id"])
        cat = getattr(cd.category, "name", str(cd.category))
        if cat == "CHARACTER" and int(getattr(cd, "cost", 0) or 0) == cost:
            return cd.card_id
    return None


def test_op04_047_returns_only_battled_cost_le_5_char():
    """OP04-047 氷鬼: 自分のターンにコスト5以下のキャラとバトルしたバトル終了時、
    バトルした相手のキャラをデッキ下に置く。 = on_self_battled + opp_just_battled(cost≤5)。
    バトルした本人のみ対象、 cost6 は不発。"""
    from engine.effects import trigger_on_self_battled
    repo = _repo()
    ov = _overlay()
    for cost, expect_returned in [(3, True), (6, False)]:
        me = Player(name="me", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        opp = Player(name="opp", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
        st = GameState(players=[me, opp], turn_player_idx=0, phase=Phase.MAIN, rng=random.Random(0))
        st.effects_overlay = ov
        me.characters = [InPlay.of(repo.get("OP04-047"), sickness=False)]
        victim = InPlay.of(repo.get(_char_of_cost(repo, cost)), sickness=False)
        opp.characters = [victim]
        st.last_battled_opp_iid = victim.instance_id
        trigger_on_self_battled(st, me, opp, me.characters[0], ov)
        returned = (victim not in opp.characters
                    and any(c.card_id == victim.card.card_id for c in opp.deck))
        assert returned is expect_returned, (
            f"battled cost{cost}: デッキ底={returned} (期待 {expect_returned})")


def test_st13_002_face_up_life_add_and_trash_cycle():
    """ST13-002: デッキ上5からコスト5キャラをライフ上に表向きで加える → 表向きライフ全trash。
    = search_top_n(life_face_up) + trash_all_face_up_life (face-up-life subsystem)。"""
    repo = _repo()
    ov = _overlay()
    c5 = _char_of_cost(repo, 5)
    st, me, opp = _state(repo)
    st.effects_overlay = ov
    me.deck = [repo.get(c5)] + [repo.get("OP01-016") for _ in range(5)]
    me.life = [repo.get("OP01-016")]
    raw = _raw("ST13-002")
    execute_effect(raw[0]["do"][0], st, me, opp, None)
    assert len(me.life) == 2 and me.face_up_life_count == 1, "表向きライフが加わっていない"
    execute_effect(raw[1]["do"][0], st, me, opp, None)
    assert me.face_up_life_count == 0 and len(me.life) == 1, "表向きライフがトラッシュされていない"
    assert len(me.trash) >= 1


def test_st13_001_pay_chara_to_face_up_life_then_pump():
    """ST13-001 サボ(leader): コスト3+パワー7000+キャラをライフに表向きで加える(cost) → 自キャラ+2000。"""
    import json
    repo = _repo()
    ov = _overlay()
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    cards = cards.get("cards", cards) if isinstance(cards, dict) else cards
    sac = next(c["card_id"] for c in cards
               if getattr(repo.get(c["card_id"]).category, "name", "") == "CHARACTER"
               and int(getattr(repo.get(c["card_id"]), "cost", 0) or 0) >= 3
               and int(getattr(repo.get(c["card_id"]), "power", 0) or 0) >= 7000)
    tgt = next(c["card_id"] for c in cards
               if getattr(repo.get(c["card_id"]).category, "name", "") == "CHARACTER"
               and 0 < int(getattr(repo.get(c["card_id"]), "power", 0) or 0) < 3000)
    me = Player(name="me", leader=InPlay.of(repo.get("ST13-001"), sickness=False))
    opp = Player(name="opp", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    st = GameState(players=[me, opp], turn_player_idx=0, phase=Phase.MAIN, rng=random.Random(0))
    st.effects_overlay = ov
    me.leader.attached_dons = 2
    me.characters = [InPlay.of(repo.get(sac), sickness=False), InPlay.of(repo.get(tgt), sickness=False)]
    me.life = [repo.get("OP01-016")]
    prim = next(c["do"][0] for c in _raw("ST13-001") if c.get("when") == "activate_main")
    execute_effect(prim, st, me, opp, me.leader)
    assert any(c.card_id == sac for c in me.life) and me.face_up_life_count >= 1, \
        "cost キャラが表向きライフに加わっていない"
    assert any(c.power > c.card.power for c in me.characters), "残キャラに +2000 が乗っていない"


def test_op10_099_flip_life_face_up_cost_untaps_supernova():
    """OP10-099 キッド: ターン終了時 ライフ上1枚を表向きにできる(cost) → コスト3-8超新星をアクティブ化。"""
    from engine.effects import trigger_end_of_turn
    import json
    repo = _repo()
    ov = _overlay()
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    cards = cards.get("cards", cards) if isinstance(cards, dict) else cards
    sn = next(c["card_id"] for c in cards
              if getattr(repo.get(c["card_id"]).category, "name", "") == "CHARACTER"
              and getattr(repo.get(c["card_id"]), "features", None)
              and "超新星" in repo.get(c["card_id"]).features
              and 3 <= int(getattr(repo.get(c["card_id"]), "cost", 0) or 0) <= 8)
    st, me, opp = _state(repo)
    st.effects_overlay = ov
    me.characters = [InPlay.of(repo.get("OP10-099"), sickness=False),
                     InPlay.of(repo.get(sn), sickness=False)]
    me.characters[1].rested = True
    me.life = [repo.get("OP01-016")]      # 裏向きライフ1 (= flip cost 払える)
    trigger_end_of_turn(st, ov)
    assert me.face_up_life_count >= 1, "cost (ライフ表向き) が払われていない"
    assert me.characters[1].rested is False, "超新星キャラがアクティブ化されていない"


def test_p117_special_win_and_mill():
    """P-117 (leader): デッキ0で敗北の代わりに勝利 (set_deck_out_wins 静的) +
    【ドン×1】リーダーアタックで相手ライフダメージ時 自デッキ上1枚をトラッシュ (mill_self_top)。"""
    repo = _repo()
    ov = _overlay()
    me = Player(name="me", leader=InPlay.of(repo.get("P-117"), sickness=False))
    opp = Player(name="opp", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    st = GameState(players=[me, opp], turn_player_idx=0, phase=Phase.MAIN, rng=random.Random(0))
    st.effects_overlay = ov
    evaluate_static_effects(st, ov)
    assert me.deck_out_wins is True, "P-117 の特殊勝利フラグが立っていない"
    me.deck = [repo.get("OP01-016") for _ in range(3)]
    me.trash = []
    mill = next(c for c in _raw("P-117") if c.get("when") == "on_opp_life_taken")
    execute_effect(mill["do"][0], st, me, opp, None)
    assert len(me.deck) == 2 and len(me.trash) == 1, "mill (デッキ上1→トラッシュ) が発火していない"


def test_op13_119_opp_reward_gated_on_bounce():
    """OP13-119: 相手 cost5以下を手札に戻す → そうした場合のみ 相手が手札から cost4以下を登場。
    bounce対象が無ければ opp 報酬も発生しない (require_prior_bounce gate)。"""
    repo = _repo()
    ov = _overlay()
    c5 = _char_of_cost(repo, 5)
    c4 = next(_char_of_cost(repo, k) for k in (4, 3, 2, 1) if _char_of_cost(repo, k))
    bounce = next(c for c in _raw("OP13-119")
                  if c.get("do") and "force_opp_play_from_hand" in str(c["do"]))

    def run(opp_field_ids):
        st, me, opp = _state(repo)
        st.effects_overlay = ov
        opp.characters = [InPlay.of(repo.get(x), sickness=False) for x in opp_field_ids]
        opp.hand = [repo.get(c4)]
        for prim in bounce["do"]:
            if execute_effect(prim, st, me, opp, None) is False:
                break
        return [c.card.card_id for c in opp.characters]

    assert c4 in run([c5]), "bounce時に相手が手札から cost4以下を登場していない (報酬なし)"
    assert run([]) == [], "bounce対象なしなのに相手が登場した (gate 失敗)"


def test_op15_059_opp_returns_don_or_takes_debuff():
    """OP15-059: 相手はアクティブドン1枚を戻して -2000 回避、 戻さない(=戻せない)場合 -2000。
    = opp_may_return_active_don_else_debuff で二択ジレンマをモデル化。"""
    import json
    repo = _repo()
    ov = _overlay()
    _cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    _cards = _cards.get("cards", _cards) if isinstance(_cards, dict) else _cards
    ch = next(c["card_id"] for c in _cards
              if getattr(repo.get(c["card_id"]).category, "name", "") == "CHARACTER"
              and int(getattr(repo.get(c["card_id"]), "power", 0) or 0) >= 5000)
    prim = next(c["do"][0] for c in _raw("OP15-059") if c.get("when") == "opp_attack")
    # (1) ドンあり → 戻して -2000 なし
    st, me, opp = _state(repo)
    st.effects_overlay = ov
    st.turn_player_idx = 1
    atk = InPlay.of(repo.get(ch), sickness=False)
    opp.characters = [atk]
    opp.don_active = 2
    b = atk.power
    execute_effect(prim, st, me, opp, None)
    assert opp.don_active == 1 and atk.power == b, "ドンありで戻さず/-2000 が誤適用"
    # (2) ドンなし → -2000
    st2, me2, opp2 = _state(repo)
    st2.effects_overlay = ov
    st2.turn_player_idx = 1
    atk2 = InPlay.of(repo.get(ch), sickness=False)
    opp2.characters = [atk2]
    opp2.don_active = 0
    b2 = atk2.power
    execute_effect(prim, st2, me2, opp2, None)
    assert atk2.power == b2 - 2000, "ドンなしで -2000 が適用されていない"
