# -*- coding: utf-8 -*-
"""OP12 弾 (サンジ / 青紫 麦わらの一味・ヴィンスモーク家 系) 効果 回帰テスト
バックフィル (自動生成 wave 121):
OP12-059 / OP12-060 / OP12-063 / OP12-065 / OP12-066 /
OP12-069 / OP12-070 / OP12-071 / OP12-072 / OP12-074 の 10 枚。

目的 (= test_backfill_auto_001〜120.py と同一方針):
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
    trigger_on_play,
    try_replace_ko,
)

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


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の (do, entry) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


def _entry(overlay, cid, when, needle=None):
    """when 一致 (かつ needle が do 表現に含まれる) 最初の効果 entry を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") != when:
            continue
        if needle is None or any(needle in d for d in e.get("do", [])):
            return e
    raise AssertionError(f"{cid} に when={when} needle={needle} の効果がない")


def _drain(st, guard=14):
    """pending_choice を種別ごとに適切に選び続けて解決しきる。
    confirm 系は承諾 ([1])、 候補選択系は先頭 ([0]) を選ぶ。"""
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
_NEUTRAL = "OP01-001"       # ルフィ (赤、 leader 条件が無い汎用)
_SANJI_LEADER = "OP12-041"  # サンジ (青/紫 = 多色 / ヴィンスモーク家・麦わらの一味)
_EVENT = "EB04-008"         # 歪んだ未来 (EVENT、 トラッシュ充填用)
_VICTIM = "OP01-016"        # ナミ (赤 cost1 pow2000 / CHARACTER name=ナミ)
_FILLER = "OP01-013"        # サンジ (赤 cost2 / CHARACTER name=サンジ)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op12_wave121_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP12-059", "OP12-060", "OP12-063", "OP12-065", "OP12-066",
           "OP12-069", "OP12-070", "OP12-071", "OP12-072", "OP12-074"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP12-059 粗砕 (EVENT 青 cost1):
#    【メイン】自リーダーが「サンジ」なら カード1枚を引く。
#    【カウンター】自トラッシュにイベント4枚以上で 自リーダー1枚まで このバトル中 +4000。
# --------------------------------------------------------------------------- #
def test_op12_059_main_draw_when_sanji_leader():
    """【メイン】 サンジ leader → カード1枚を引く (deck -1 / hand +1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay)  # OP12-041 = サンジ
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_VICTIM)] + [repo.get(_FILLER)] * 9
    me.hand = []

    _, entry = _do(overlay, "OP12-059", "main")
    assert _cond_of(entry).get("leader_name") == "サンジ", \
        "overlay のメイン条件 leader_name=サンジ が無い"
    deck_before = len(me.deck)
    for prim in entry["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == 1, f"メインで 1 ドローされていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 1, "デッキが 1 枚減っていない"


def test_op12_059_counter_pump_leader_when_4_events_in_trash():
    """【カウンター】 トラッシュにイベント4枚 → 自リーダー このバトル中 +4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_EVENT)] * 4  # イベント 4 枚 = 条件成立

    entry = _entry(overlay, "OP12-059", "counter", needle="power_pump")
    assert _cond_of(entry).get("self_trash_event_count_ge") == 4, \
        "overlay のカウンター条件 self_trash_event_count_ge=4 が無い"
    power_before = me.leader.power
    for prim in entry["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert me.leader.power == power_before + 4000, \
        f"カウンターで自リーダーに +4000 されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP12-060 牛肉バースト (EVENT 青 cost3):
#    【メイン】自リーダーが多色の場合、以下から1つを選ぶ。
#      ・相手のコスト4以下のキャラ1枚までを持ち主の手札に戻す。
#      ・自分の手札が6枚以下ならカード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op12_060_main_choice_bounce_ai():
    """【メイン】 多色 leader + 手札7枚 (option2 無効) → AI は option1 (相手キャラ手札戻し)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay)  # 青/紫 = 多色
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)] * 7  # 7 枚 = option2 の self_hand_count_le:6 不成立
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=4)
    opp.characters = [victim]

    _, entry = _do(overlay, "OP12-060", "main")
    assert _cond_of(entry).get("leader_color_multi") is True, \
        "overlay のメイン条件 leader_color_multi=true が無い"
    opp_hand_before = len(opp.hand)
    for prim in entry["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim not in opp.characters, "コスト4以下の相手キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "相手の手札が 1 枚増えていない"


def test_op12_060_main_choice_draw_ai():
    """【メイン】 多色 leader + 手札少 + 相手キャラ無し → AI は option2 (2ドロー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []                       # 手札 0 枚 = self_hand_count_le:6 成立
    me.deck = [repo.get(_FILLER)] * 10
    opp.characters = []                # 相手キャラ無し = option1 は空回り

    _, entry = _do(overlay, "OP12-060", "main")
    hand_before = len(me.hand)
    for prim in entry["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert len(me.hand) == hand_before + 2, \
        f"option2 の 2 ドローが起きていない: {len(me.hand)}"


def test_op12_060_main_choice_human_option_pick():
    """人間 + 多色 leader → option_pick modal が立ち、 resolve で選択肢を解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []                       # option2 有効
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [victim]          # option1 も有効

    _, entry = _do(overlay, "OP12-060", "main")
    execute_effect(entry["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 多色で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    opts = st.pending_choice.get("options", [])
    assert len(opts) == 2, f"選択肢が 2 個でない: {len(opts)}"

    # option2 (= idx 1 = 2ドロー) を選択して解決
    hand_before = len(me.hand)
    resolve_pending_choice(st, [1])
    _drain(st)
    assert len(me.hand) == hand_before + 2, \
        "人間が選んだ option2 (2ドロー) が反映されていない"


# --------------------------------------------------------------------------- #
#  OP12-063 ヴィンスモーク・レイジュ (CHARACTER 紫 cost4 pow5000):
#    静的: 自トラッシュにイベント4枚以上で このキャラ +2000 / コスト+5。
# --------------------------------------------------------------------------- #
def test_op12_063_reiju_static_pump_and_cost_when_4_events():
    """静的: トラッシュにイベント4枚 → power 5000→7000 / cost 4→9。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    reiju_def = repo.get("OP12-063")
    reiju = InPlay.of(reiju_def, sickness=False)
    me.characters = [reiju]

    me.trash = [repo.get(_EVENT)] * 4  # イベント 4 枚 = 条件成立
    evaluate_static_effects(st, overlay)
    assert reiju.power == reiju_def.power + 2000, \
        f"イベント4枚で +2000 されていない: {reiju.power} (base {reiju_def.power})"
    assert reiju.base_cost == reiju_def.cost + 5, \
        f"イベント4枚で cost+5 されていない: {reiju.base_cost} (base {reiju_def.cost})"


def test_op12_063_reiju_static_no_pump_when_few_events():
    """負例: トラッシュのイベントが3枚以下なら 静的効果は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    reiju_def = repo.get("OP12-063")
    reiju = InPlay.of(reiju_def, sickness=False)
    me.characters = [reiju]

    me.trash = [repo.get(_EVENT)] * 3  # 3 枚 = 不成立
    evaluate_static_effects(st, overlay)
    assert reiju.power == reiju_def.power, \
        f"イベント3枚で power が上がってはいけない: {reiju.power}"
    assert reiju.base_cost == reiju_def.cost, \
        f"イベント3枚で cost が変わってはいけない: {reiju.base_cost}"


# --------------------------------------------------------------------------- #
#  OP12-065 エンポリオ・イワンコフ (CHARACTER 紫 cost6 pow7000):
#    静的: 自トラッシュにイベント4枚以上で【ブロッカー】を得る。
#    【KO時】自トラッシュからイベント1枚までを手札に加える。
# --------------------------------------------------------------------------- #
def test_op12_065_iva_static_gains_blocker_when_4_events():
    """静的: トラッシュにイベント4枚 → 【ブロッカー】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    iva = InPlay.of(repo.get("OP12-065"), sickness=False)
    me.characters = [iva]

    me.trash = [repo.get(_EVENT)] * 4
    evaluate_static_effects(st, overlay)
    assert iva.is_blocker_now is True, \
        f"イベント4枚で【ブロッカー】が付与されていない: {iva.static_granted_keywords}"


def test_op12_065_iva_on_ko_recover_event_ai():
    """【KO時】 AI: 自トラッシュのイベント1枚を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_EVENT), repo.get(_FILLER)]  # イベント1 + キャラ1
    me.hand = []

    do, _ = _do(overlay, "OP12-065", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-065"), sickness=False))
    _drain(st)

    assert any(c.card_id == _EVENT for c in me.hand), \
        f"KO時にトラッシュのイベントが手札に加わっていない: {[c.card_id for c in me.hand]}"


# --------------------------------------------------------------------------- #
#  OP12-066 カルネ (CHARACTER 紫 cost1 pow1000):
#    静的: 自トラッシュにイベント4枚以上で【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op12_066_carne_static_gains_blocker_when_4_events():
    """静的: トラッシュにイベント4枚 → 【ブロッカー】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    carne = InPlay.of(repo.get("OP12-066"), sickness=False)
    me.characters = [carne]

    me.trash = [repo.get(_EVENT)] * 4
    evaluate_static_effects(st, overlay)
    assert carne.is_blocker_now is True, \
        f"イベント4枚で【ブロッカー】が付与されていない: {carne.static_granted_keywords}"


def test_op12_066_carne_no_blocker_when_few_events():
    """負例: イベント3枚以下なら【ブロッカー】は付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    carne = InPlay.of(repo.get("OP12-066"), sickness=False)
    me.characters = [carne]

    me.trash = [repo.get(_EVENT)] * 3
    evaluate_static_effects(st, overlay)
    assert carne.is_blocker_now is False, \
        "イベント3枚で【ブロッカー】が付いてはいけない"


# --------------------------------------------------------------------------- #
#  OP12-069 クロコダイル (CHARACTER 紫 cost6 pow8000):
#    【相手のアタック時】【ターン1回】ドン-1: リーダーが『B・W』を含むなら
#      自リーダーかキャラ1枚まで このバトル中 +2000。
# --------------------------------------------------------------------------- #
def test_op12_069_crocodile_opp_attack_pump_ai():
    """【相手のアタック時】 do の power_pump で 自陣キャラ1体が このバトル中 +2000 (AI)。"""
    # ⚠ 公式は 「ドン‼-1：自分のリーダーが『B・W』を含む特徴を持つ場合、…」。
    #   条件は conditional の中なので、 満たさないリーダーだと何も起きない。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay)
    me, opp = st.players[0], st.players[1]
    ally = InPlay.of(repo.get(_FILLER), sickness=False)  # サンジ pow3000
    me.characters = [ally]

    do, entry = _do(overlay, "OP12-069", "opp_attack")
    assert entry.get("cost", {}).get("once_per_turn") is True, \
        "overlay の【ターン1回】gate (once_per_turn) が無い"
    assert entry.get("cost", {}).get("pay_don") == 1, \
        "overlay の ドン-1 コスト (pay_don=1) が無い"
    # self_inplay = 「自リーダーかキャラ1枚まで」。 AI は最高パワー (=リーダー) に +2000。
    total_before = me.leader.power + sum(c.power for c in me.characters)
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-069"), sickness=False))
    _drain(st)

    total_after = me.leader.power + sum(c.power for c in me.characters)
    assert total_after == total_before + 2000, \
        f"相手アタック時の +2000 が自陣に反映されていない: {total_after} (before {total_before})"


def test_op12_069_crocodile_opp_attack_human_pick():
    """人間 + 自リーダー/キャラ複数 → target_pick modal が立ち、 選んだ1体に +2000。"""
    # ⚠ 公式は 「ドン‼-1：自分のリーダーが『B・W』を含む特徴を持つ場合、…」。
    #   条件は conditional の中なので、 満たさないリーダーだと何も起きない。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    ally = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [ally]

    do, _ = _do(overlay, "OP12-069", "opp_attack")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP12-069"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    ally_idx = next(i for i, c in enumerate(cands) if c["iid"] == ally.instance_id)
    ally_before = ally.power
    resolve_pending_choice(st, [ally_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert ally.power == ally_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP12-070 サンジ (CHARACTER 紫 cost3 pow5000):
#    静的: 自トラッシュのイベント5枚につき +1000。
#    このキャラが相手効果で場を離れる場合、代わりに自分の場のドン1枚をドンデッキに戻せる。
# --------------------------------------------------------------------------- #
def test_op12_070_sanji_static_pump_per_5_events():
    """静的: トラッシュのイベント5枚 → power 5000→6000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    sanji_def = repo.get("OP12-070")
    sanji = InPlay.of(sanji_def, sickness=False)
    me.characters = [sanji]

    me.trash = [repo.get(_EVENT)] * 5  # 5 枚 → +1000
    evaluate_static_effects(st, overlay)
    assert sanji.power == sanji_def.power + 1000, \
        f"イベント5枚で +1000 されていない: {sanji.power} (base {sanji_def.power})"


def test_op12_070_sanji_replace_leave_return_don_ai():
    """AI: 相手効果で離脱 → 代わりに場のドン1枚をドンデッキへ戻して場に残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("OP12-070"), sickness=False)
    me.characters = [sanji]
    me.don_active = 2  # 場のドン (返却コスト用)

    don_before = me.don_active + me.don_rested
    replaced = try_replace_ko(
        st, me, opp, sanji, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "相手効果離脱が代替 (ドン返却) されていない"
    assert sanji in me.characters, "代替成立時 サンジは場に残るべき"
    assert (me.don_active + me.don_rested) == don_before - 1, \
        "代替コストで場のドンが1枚ドンデッキに戻るべき"


def test_op12_070_sanji_replace_leave_no_don():
    """負例: 場にドンが無ければ代替コストを払えず 離脱が代替されない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("OP12-070"), sickness=False)
    me.characters = [sanji]
    me.don_active = 0
    me.don_rested = 0

    replaced = try_replace_ko(
        st, me, opp, sanji, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "ドンが無いのに代替が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP12-071 シャーロット・プリン (CHARACTER 紫 cost1 pow2000):
#    【登場時】デッキ上4枚を見て「サンジ」かイベント1枚までを公開し手札に、
#      残りを好きな順番でデッキの下。
# --------------------------------------------------------------------------- #
def test_op12_071_pudding_on_play_search_event_ai():
    """【登場時】 AI: デッキ上4枚のイベントを手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-071"), sickness=True)
    me.characters = [src]
    # 上4枚に イベント 1 枚 + 非該当 (ナミ = CHARACTER name ナミ) を仕込む
    me.deck = [repo.get(_EVENT)] + [repo.get(_VICTIM)] * 6
    me.hand = []

    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    assert any(c.card_id == _EVENT for c in me.hand), \
        f"登場時にデッキ上のイベントが手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op12_071_pudding_on_play_search_sanji_ai():
    """【登場時】 AI: デッキ上4枚の「サンジ」を手札に加える (name 一致)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-071"), sickness=True)
    me.characters = [src]
    # 上4枚に サンジ (OP01-013) 1 枚 + 非該当 (ナミ)
    me.deck = [repo.get(_FILLER)] + [repo.get(_VICTIM)] * 6
    me.hand = []

    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    assert any(c.name == "サンジ" for c in me.hand), \
        f"登場時にデッキ上の「サンジ」が手札に加わっていない: {[c.card_id for c in me.hand]}"


# --------------------------------------------------------------------------- #
#  OP12-072 ゼフ (CHARACTER 紫 cost4 pow5000):
#    自分の場のドンがドンデッキに戻された時、リーダーが「サンジ」なら
#      このキャラは このターン中【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op12_072_zeff_gains_rush_on_don_returned_when_sanji():
    """【ドン返却時】 サンジ leader → このキャラは このターン中【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay)  # サンジ leader
    me, opp = st.players[0], st.players[1]
    zeff = InPlay.of(repo.get("OP12-072"), sickness=True)
    me.characters = [zeff]

    do, entry = _do(overlay, "OP12-072", "on_self_don_returned_to_deck")
    assert _cond_of(entry).get("leader_name") == "サンジ", \
        "overlay の条件 leader_name=サンジ が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, zeff)

    assert "速攻" in zeff.granted_keywords, \
        f"ドン返却時に【速攻】が付与されていない: {zeff.granted_keywords}"


# --------------------------------------------------------------------------- #
#  OP12-074 パティ (CHARACTER 紫 cost3 pow2000):
#    【登場時】自分の手札からイベント1枚を捨てられる：リーダーが「サンジ」なら
#      ドンデッキからドン1枚までをアクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op12_074_patty_on_play_discard_event_add_don_ai():
    """【登場時】 AI: 手札のイベント1枚を捨て → サンジ leader なら アクティブドン+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay)  # サンジ leader
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-074"), sickness=True)
    me.characters = [src]
    me.hand = [repo.get(_EVENT)]  # 捨てるコスト (イベント)
    me.don_active = 0
    me.don_remaining_in_deck = 10

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)
    _drain(st)

    assert me.don_active == 1, f"サンジ leader で アクティブドン+1 されていない: {me.don_active}"
    assert len(me.hand) == hand_before - 1, "コストで手札のイベントが1枚捨てられるべき"


def test_op12_074_patty_on_play_human_optional_cost():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で ドン+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SANJI_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP12-074"), sickness=True)
    me.characters = [src]
    me.hand = [repo.get(_EVENT)]
    me.don_active = 0
    me.don_remaining_in_deck = 10

    trigger_on_play(st, me, opp, src, overlay)
    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st)
    assert me.don_active == 1, "人間承諾後 アクティブドン+1 されていない"
