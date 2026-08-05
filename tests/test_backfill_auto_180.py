# -*- coding: utf-8 -*-
"""ST16 / ST17 / ST18 / ST19 弾 効果 回帰テスト バックフィル (自動生成 wave 180):
ST16-004 / ST16-005 / ST17-002 / ST17-003 / ST17-005 / ST18-002 /
ST18-003 / ST18-004 / ST18-005 / ST19-001 の 10 枚。

目的 (= test_backfill_auto_001〜179.py と同一方針):
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
from engine.effects import (
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


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


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。
    デッキは効果の薄いカード (OP01-016 ナミ) で埋める。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
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
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave180_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST16-004", "ST16-005", "ST17-002", "ST17-003", "ST17-005",
           "ST18-002", "ST18-003", "ST18-004", "ST18-005", "ST19-001"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST16-004 シャンクス (CHARACTER 緑 cost9 power11000):
#    【登場時】相手のレストのキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_st16_004_on_play_ko_rested_ai():
    """【登場時】相手のレストキャラ1枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay)  # 緑 ウタ リーダー
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ
    victim.rested = True
    opp.characters = [victim]

    do, _ = _do(overlay, "ST16-004", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST16-004"), sickness=True))
    _drain(st, [0])
    assert victim not in opp.characters, "相手のレストキャラが KO されていない"


def test_st16_004_on_play_active_not_targeted():
    """相手キャラが アクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    do, _ = _do(overlay, "ST16-004", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST16-004"), sickness=True))
    _drain(st, [0])
    assert victim in opp.characters, "アクティブキャラが KO されてはいけない (対象外)"


def test_st16_004_on_play_ko_human_pick():
    """人間 + 相手レストキャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    do, _ = _do(overlay, "ST16-004", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("ST16-004"), sickness=True))
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
#  ST16-005 モンキー・D・ルフィ (CHARACTER 緑 cost2 power3000):
#    自分の「ウタ」がレストの場合、このキャラのパワー+1000 (静的)。
# --------------------------------------------------------------------------- #
def test_st16_005_static_pump_when_uta_rested():
    """静的: 自分の「ウタ」がレストなら このキャラ +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay)
    me = st.players[0]
    ruffy = InPlay.of(repo.get("ST16-005"), sickness=False)  # power 3000
    uta = InPlay.of(repo.get("ST16-001"), sickness=False)    # name ウタ
    uta.rested = True
    me.characters = [ruffy, uta]

    base = repo.get("ST16-005").power
    evaluate_static_effects(st, overlay)
    assert ruffy.power == base + 1000, \
        f"ウタ レスト時に +1000 が反映されていない: {ruffy.power} (印刷 {base})"


def test_st16_005_static_no_pump_uta_active():
    """自分の「ウタ」が アクティブなら +1000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay)
    me = st.players[0]
    ruffy = InPlay.of(repo.get("ST16-005"), sickness=False)
    uta = InPlay.of(repo.get("ST16-001"), sickness=False)
    uta.rested = False  # アクティブ = 条件不成立
    me.characters = [ruffy, uta]

    base = repo.get("ST16-005").power
    evaluate_static_effects(st, overlay)
    assert ruffy.power == base, \
        f"ウタ アクティブなのに +1000 が乗っている: {ruffy.power} (印刷 {base})"


def test_st16_005_static_no_pump_no_uta():
    """場に「ウタ」がいなければ +1000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST11-001", overlay)
    me = st.players[0]
    ruffy = InPlay.of(repo.get("ST16-005"), sickness=False)
    me.characters = [ruffy]  # ウタ なし

    base = repo.get("ST16-005").power
    evaluate_static_effects(st, overlay)
    assert ruffy.power == base, \
        f"ウタ 不在なのに +1000 が乗っている: {ruffy.power} (印刷 {base})"


# --------------------------------------------------------------------------- #
#  ST17-002 トラファルガー・ロー (CHARACTER 青 cost4 power5000):
#    【登場時】自分のキャラ1枚を持ち主の手札に戻すことができる：自分のリーダーが
#    特徴《王下七武海》を持つ場合、コスト4以下のキャラ1枚までを、持ち主の手札に戻す。
#    (overlay 解釈: コスト = このキャラ自身を手札に戻す / 効果 = 相手のコスト4以下キャラを
#     持ち主の手札に戻す)
# --------------------------------------------------------------------------- #
def test_st17_002_leader_feature_gate():
    """overlay の【王下七武海リーダー】(leader_feature) ゲートが 効果に付いている。"""
    repo = _repo()
    overlay = _overlay()
    # 王下七武海 リーダー (ST03-001 クロコダイル) で条件成立
    st = _state(repo, "ST03-001", overlay)
    _, eff = _do(overlay, "ST17-002", "on_play")
    assert eval_condition(_cond_of(eff), st, st.players[0]) is True, \
        "王下七武海 リーダーで on_play 条件が成立していない"
    # 非王下七武海 リーダー (OP01-001 ゾロ) で不成立
    st2 = _state(repo, "OP01-001", overlay)
    assert eval_condition(_cond_of(eff), st2, st2.players[0]) is False, \
        "非王下七武海 リーダーで条件が成立してはいけない"


def test_st17_002_on_play_bounce_ai():
    """【登場時】自身を手札に戻すコスト → 相手のコスト4以下キャラを 持ち主の手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay)  # 王下七武海 リーダー
    me, opp = st.players[0], st.players[1]
    law = InPlay.of(repo.get("ST17-002"), sickness=False)
    me.characters = [law]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1 ≤ 4
    opp.characters = [victim]
    victim_cid = victim.card.card_id

    do, _ = _do(overlay, "ST17-002", "on_play")
    execute_effect(do[0], st, me, opp, law)
    _drain(st, [0])

    # コスト: ロー自身が手札へ
    assert law not in me.characters, "コストで ロー自身が場から離れていない"
    assert any(c.card_id == "ST17-002" for c in me.hand), \
        "コストで ロー自身が手札に戻っていない"
    # 効果: 相手のコスト4以下キャラが 持ち主 (相手) の手札へ
    assert victim not in opp.characters, "相手のコスト4以下キャラが場から戻されていない"
    assert any(c.card_id == victim_cid for c in opp.hand), \
        "戻した相手キャラが 持ち主 (相手) の手札に加わっていない"


# --------------------------------------------------------------------------- #
#  ST17-003 バギー (CHARACTER 青 cost1 power2000):
#    【登場時】自分のデッキの上から3枚を見て、好きな順番に並び替え、デッキの上に置く。
#    (overlay: look_top_reorder depth3 to=top = デッキ上3枚の確認・並び替え。 公開情報のみで
#     決まる効果のため engine は順番維持で安全に解決する = 盤面破壊なし)
# --------------------------------------------------------------------------- #
def test_st17_003_on_play_look_top_reorder_ai():
    """【登場時】デッキ上3枚を見て並び替え。 AI: crash せず デッキ枚数・上位カードが保たれる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay)
    me, opp = st.players[0], st.players[1]
    # 上位を識別できるよう 3 種混在させる
    me.deck = ([repo.get("OP01-013"), repo.get("OP01-016"), repo.get("OP01-013")]
               + [repo.get("OP01-016")] * 20)
    deck_before = len(me.deck)
    top3_before = {c.card_id for c in me.deck[:3]}

    do, _ = _do(overlay, "ST17-003", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST17-003"), sickness=True))
    _drain(st, [0])

    assert len(me.deck) == deck_before, \
        f"デッキ枚数が変化した (並び替えのみのはず): {len(me.deck)} (before {deck_before})"
    assert {c.card_id for c in me.deck[:3]} == top3_before, \
        "並び替え対象 (上3枚) の集合が変わってはいけない"


# --------------------------------------------------------------------------- #
#  ST17-005 マーシャル・D・ティーチ (CHARACTER 青 cost2 power3000):
#    【起動メイン】【ターン1回】自分の手札1枚をデッキの上に置くことができる：
#    自分のリーダーかキャラ1枚にレストのドン‼2枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_st17_005_activate_main_hand_to_deck_attach_don_ai():
    """【起動メイン】手札1枚をデッキ上へ (コスト) → 自リーダーにレストドン2枚を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay)
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("ST17-005"), sickness=False)
    me.characters = [teach]
    me.hand = [repo.get("OP01-013")]  # デッキ上に置くコスト用
    me.don_rested = 3  # レストドン供給源

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST17-005"]
    assert len(opts) == 1, f"ST17-005 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert me.leader.attached_dons == don_before + 2, \
        f"自リーダーへ レストドン2枚が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"
    assert len(me.hand) == hand_before - 1, "手札1枚がデッキ上に置かれるべき (コスト)"
    assert len(me.deck) == deck_before + 1, "コストで手札1枚がデッキに戻るべき"


def test_st17_005_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay)
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("ST17-005"), sickness=False)
    me.characters = [teach]
    me.hand = [repo.get("OP01-013"), repo.get("OP01-013")]
    me.don_rested = 4

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST17-005"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST17-005"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST18-002 おナミ (CHARACTER 紫 cost4 power2000):
#    【ブロッカー】【登場時】自分の場のドン!!が8枚以上ある場合、自分の手札1枚を捨て、
#    カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_st18_002_on_play_discard_draw_ai():
    """【登場時】場ドン8以上 → 手札1枚捨てて 2枚引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-058", overlay)  # 紫 クロコダイル
    me, opp = st.players[0], st.players[1]
    me.don_active = 8  # 場のドン 8 (= 条件成立)
    me.hand = [repo.get("OP01-013"), repo.get("OP01-016")]  # 捨てるコスト用
    me.deck = [repo.get("OP01-016")] * 10

    do, eff = _do(overlay, "ST18-002", "on_play")
    assert _cond_of(eff).get("self_don_ge") == 8, \
        "overlay の 場ドン8以上 (self_don_ge=8) ゲートが無い"
    assert eval_condition(_cond_of(eff), st, me) is True, \
        "場ドン8で 登場時条件が成立していない"
    hand_before = len(me.hand)
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST18-002"), sickness=True))
    _drain(st, [0])
    # 手札: -1 (捨て) +2 (ドロー) = +1
    assert len(me.hand) == hand_before - 1 + 2, \
        f"手札 net (捨て -1 + ドロー +2) が合わない: {len(me.hand)} (before {hand_before})"
    assert len(me.trash) >= 1, "捨てたカードがトラッシュに置かれていない"


def test_st18_002_condition_false_few_don():
    """場のドンが8枚未満なら 登場時条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-058", overlay)
    me = st.players[0]
    me.don_active = 5  # 8 未満
    _, eff = _do(overlay, "ST18-002", "on_play")
    assert eval_condition(_cond_of(eff), st, me) is False, \
        "場ドン5で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  ST18-003 サン五郎 (CHARACTER 紫 cost5 power6000):
#    【アタック時】【ターン1回】自分の場のドン!!が8枚以上ある場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_st18_003_on_attack_draw_ai():
    """【アタック時】場ドン8以上 → 1 ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-058", overlay)
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("ST18-003"), sickness=False)
    me.characters = [sanji]
    me.don_active = 8
    me.hand = []
    me.deck = [repo.get("OP01-016")] * 10

    do, eff = _do(overlay, "ST18-003", "on_attack")
    assert _cond_of(eff).get("self_don_ge") == 8, \
        "overlay の 場ドン8以上 ゲートが無い"
    assert eval_condition(_cond_of(eff), st, me) is True, \
        "場ドン8で アタック時条件が成立していない"
    deck_before = len(me.deck)
    for prim in do:
        execute_effect(prim, st, me, opp, sanji)
    _drain(st, [0])
    assert len(me.hand) == 1, "アタック時の 1 ドローが起きていない"
    assert len(me.deck) == deck_before - 1, "1 ドローでデッキが1枚減っていない"


def test_st18_003_condition_false_few_don():
    """場のドンが8枚未満なら アタック時条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-058", overlay)
    me = st.players[0]
    me.don_active = 7
    _, eff = _do(overlay, "ST18-003", "on_attack")
    assert eval_condition(_cond_of(eff), st, me) is False, \
        "場ドン7で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  ST18-004 ゾロ十郎 (CHARACTER 紫 cost4 power6000):
#    【登場時】自分のデッキの上から5枚を見て、紫の特徴《麦わらの一味》を持つカード1枚まで
#    を公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_st18_004_on_play_search_purple_mugiwara_ai():
    """【登場時】デッキ上5枚から 紫麦わらキャラ1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-058", overlay)
    me, opp = st.players[0], st.players[1]
    target = repo.get("PRB02-012")  # ナミ 紫 麦わらの一味 cost2
    assert "麦わらの一味" in target.features and "紫" in target.color, \
        "テスト前提: PRB02-012 は 紫 麦わらの一味"
    # 上5枚のどこかに仕込む
    me.deck = ([repo.get("OP01-016")] * 2 + [target]
               + [repo.get("OP01-016")] * 17)
    me.hand = []

    do, _ = _do(overlay, "ST18-004", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST18-004"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == "PRB02-012" for c in me.hand), \
        "デッキ上5枚から 紫麦わらキャラが手札に加わっていない"


def test_st18_004_on_play_no_match_no_add():
    """デッキ上5枚に 紫麦わら が無ければ 手札に何も加わらない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-058", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] * 20  # 赤麦わら = 色不一致
    me.hand = []

    do, _ = _do(overlay, "ST18-004", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST18-004"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 0, "該当カードが無いのに手札が増えている"


def test_st18_004_on_play_search_human_pick():
    """人間 + デッキ上5枚に 紫麦わら 複数 → search 系 modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-058", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    target = repo.get("PRB02-012")
    me.deck = ([target, repo.get("OP01-016"), target]
               + [repo.get("OP01-016")] * 15)
    me.hand = []

    do, _ = _do(overlay, "ST18-004", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("ST18-004"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search modal が立たない"
    assert "search" in st.pending_choice.get("kind", ""), \
        f"kind が search 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭候補を選択
    _drain(st, [])
    assert any(c.card_id == "PRB02-012" for c in me.hand), \
        "人間が選んだ 紫麦わらキャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  ST18-005 ルフィ太郎 (CHARACTER 紫 cost7 power8000):
#    【登場時】ドン!!-1：自分の手札からコスト5以下の紫の特徴《麦わらの一味》を持つ
#    キャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_st18_005_on_play_play_from_hand_ai():
    """【登場時】手札から コスト5以下の紫麦わらキャラを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-058", overlay)
    me, opp = st.players[0], st.players[1]
    playable = repo.get("PRB02-012")  # ナミ 紫 麦わら cost2 ≤ 5
    me.hand = [playable]
    me.don_active = 5  # ドン-1 コスト源

    do, _ = _do(overlay, "ST18-005", "on_play")
    chars_before = len(me.characters)
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST18-005"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "PRB02-012" for c in me.characters), \
        "手札から 紫麦わらキャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"
    assert not any(c.card_id == "PRB02-012" for c in me.hand), \
        "登場させたカードが手札に残っている"


def test_st18_005_on_play_play_human_pick():
    """人間 + 手札に コスト5以下の紫麦わら 複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-058", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("PRB02-012"), repo.get("OP12-070")]  # 紫麦わら cost2 / cost3
    me.don_active = 5

    do, _ = _do(overlay, "ST18-005", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("ST18-005"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in ("PRB02-012", "OP12-070")
               for c in me.characters), \
        "人間が選んだ 紫麦わらキャラが登場していない"


# --------------------------------------------------------------------------- #
#  ST19-001 スモーカー (CHARACTER 黒 cost6 power8000):
#    【登場時】自分の手札から黒の特徴《海軍》を持つカード1枚を捨てることができる：
#    相手のコスト4以下のキャラ2枚までは、次の相手のターン終了時まで、アタックできない。
# --------------------------------------------------------------------------- #
def test_st19_001_on_play_discard_set_cannot_attack_ai():
    """【登場時】黒海軍1枚を捨てて 相手コスト4以下キャラ2枚をアタック不能に (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay)  # 黒 クロコダイル (王下七武海)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB04-046")]  # ドール 黒 海軍 = 捨てるコスト
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 ≤ 4
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 ≤ 4
    opp.characters = [a, b]

    hand_before = len(me.hand)
    do, _ = _do(overlay, "ST19-001", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("ST19-001"), sickness=True))
    _drain(st, [0])

    assert len(me.hand) == hand_before - 1, "黒海軍1枚が 捨てコストで手札から減っていない"
    assert any(c.card_id == "EB04-046" for c in me.trash), \
        "捨てた 黒海軍カードがトラッシュに置かれていない"
    blocked = [c for c in opp.characters if c.cannot_attack_through_opp_turn]
    assert len(blocked) == 2, \
        f"相手コスト4以下キャラ2枚がアタック不能になっていない: {len(blocked)}"


def test_st19_001_on_play_no_navy_no_effect():
    """手札に 黒海軍 が無ければ コスト不能 → 相手キャラは アタック不能にならない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 赤麦わら = 黒海軍でない
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "ST19-001", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("ST19-001"), sickness=True))
    _drain(st, [0])
    assert victim.cannot_attack_through_opp_turn is False, \
        "黒海軍が無いのに 相手キャラがアタック不能になっている"
    assert any(c.card_id == "OP01-013" for c in me.hand), \
        "コスト不能なら手札は捨てられないべき"


def test_st19_001_on_play_human_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で
    黒海軍を捨て 相手キャラをアタック不能にする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB04-046")]  # ドール 黒 海軍
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 ≤ 4
    opp.characters = [victim]

    do, _ = _do(overlay, "ST19-001", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("ST19-001"), sickness=True))
    assert st.pending_choice is not None, "人間 + 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st, [0])
    assert victim.cannot_attack_through_opp_turn is True, \
        "人間承諾後 相手コスト4以下キャラがアタック不能になっていない"
