# -*- coding: utf-8 -*-
"""ST06 / ST07 弾 効果 回帰テスト バックフィル (自動生成 wave 170):
ST06-017 / ST07-001 / ST07-003 / ST07-004 / ST07-005 / ST07-007 /
ST07-008 / ST07-009 / ST07-010 / ST07-011 の 10 枚。

目的 (= test_backfill_auto_001〜169.py と同一方針):
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
    eval_all_conditions,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# 汎用 (効果の薄い) 埋めカード
_FILLER = "ST01-004"      # サンジ cost2 power4000 (バニラ気味)
_NEUTRAL_LEADER = "OP10-099"  # ユースタス・キッド (中立枠として利用)
_NAVY_LEADER = "ST06-001"     # サカズキ (海軍) → ST06-017 の 海軍条件成立用
_BM_LEADER = "ST07-001"       # シャーロット・リンリン (四皇/ビッグ・マム海賊団)
_LINLIN_CHARA = "ST07-010"    # シャーロット・リンリン (CHARACTER cost7)


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
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 dict を返す (needle で do 内絞り込み)。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave170_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST06-017", "ST07-001", "ST07-003", "ST07-004", "ST07-005",
           "ST07-007", "ST07-008", "ST07-009", "ST07-010", "ST07-011"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST06-017 海軍本部 (STAGE 黒 cost1 海軍):
#    【登場時】相手のキャラ1枚までを、このターン中、コスト-1。
#    【起動メイン】このステージをレストにできる：自リーダーが《海軍》なら 相手キャラ1枚 コスト-1。
# --------------------------------------------------------------------------- #
def test_st06_017_on_play_cost_minus_ai():
    """【登場時】相手キャラ1枚を このターン中 コスト-1 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [victim]

    cost_before = victim.base_cost
    for prim in _eff(overlay, "ST06-017", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST06-017"), sickness=True))
    assert victim.base_cost == cost_before - 1, \
        f"登場時のコスト-1が反映されていない: {victim.base_cost} (before {cost_before})"


def test_st06_017_on_play_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1 体を コスト-1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST06-017", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST06-017"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    assert b.base_cost == b_before - 1, "人間が選んだ相手キャラに コスト-1 が反映されていない"


def test_st06_017_activate_main_navy_leader_ai():
    """【起動メイン】海軍リーダー時: ステージをレスト → 相手キャラ1枚 コスト-1 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NAVY_LEADER, overlay)  # サカズキ (海軍) → 条件成立
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("ST06-017"), sickness=False)
    me.stages = [stage]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    cost_before = victim.base_cost
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST06-017"]
    assert len(opts) == 1, f"ST06-017 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])

    assert stage.rested is True, "起動メインの任意コストでステージがレストされるべき"
    assert victim.base_cost == cost_before - 1, \
        f"海軍リーダー時の コスト-1 が反映されていない: {victim.base_cost}"


# --------------------------------------------------------------------------- #
#  ST07-001 シャーロット・リンリン (LEADER 黄):
#    【ドン!!×2】【アタック時】自ライフ上下1枚を手札に加えることができる：
#      自ライフが2枚以下の場合、自分の手札1枚までを、ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_st07_001_on_attack_life_cycle_ai():
    """【アタック時】(don×2 gate) 任意で ライフ上下1→手札、 その後ライフ2以下なら手札1→ライフ。
    AI: cost で ライフ上1枚を手札へ → 条件成立 (ライフ1≤2) → 手札1枚をライフへ。
    net = ライフ枚数 復帰 (2) / 手札 枚数 維持 (1)、 手札札が ライフへ移動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 2  # 【ドン!!×2】ゲート
    me.life = [repo.get(_FILLER), repo.get(_FILLER)]  # 2 枚
    distinct = repo.get("OP01-016")  # ナミ (識別用の手札札)
    me.hand = [distinct]

    eff = _eff(overlay, "ST07-001", "on_attack")
    assert _cond_of(eff).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st, pick=[0])

    assert len(me.life) == 2, f"ライフ枚数が復帰していない (cost-1 + 効果+1): {len(me.life)}"
    assert len(me.hand) == 1, f"手札枚数が維持されていない: {len(me.hand)}"
    assert any(c.card_id == "OP01-016" for c in me.life), \
        "手札の札が【アタック時】効果でライフに加わっていない"


# --------------------------------------------------------------------------- #
#  ST07-003 シャーロット・カタクリ (CHARACTER 黄 cost4):
#    【登場時】自か相手ライフ上1枚を見て上下に置く。 その後 自ライフ枚数が相手より少ない場合
#      このキャラは このターン中【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_st07_003_on_play_grants_rush_when_life_fewer_ai():
    """自ライフ < 相手ライフ の条件付き【速攻】付与。 overlay の do を実行 → self に速攻。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 1
    opp.life = [repo.get(_FILLER)] * 3
    katakuri = InPlay.of(repo.get("ST07-003"), sickness=True)
    me.characters = [katakuri]

    # ⚠ ST07-003 は本文に「【速攻】を得る」を含むため has_keyword('速攻') が text 由来で
    #    True になる (engine の text 解析の癖)。 効果由来の付与は granted_keywords で判定する。
    assert "速攻" not in katakuri.granted_keywords, "前提: 効果付与前は granted に速攻なし"
    for prim in _eff(overlay, "ST07-003", "on_play")["do"]:
        execute_effect(prim, st, me, opp, katakuri)
    assert "速攻" in katakuri.granted_keywords, \
        "自ライフが相手より少ない条件で【速攻】が granted_keywords に付与されていない"


def test_st07_003_on_play_condition_flag():
    """条件 self_life_lt_opp が掛かるのは **【速攻】付与だけ** (scry は無条件)。

    公式: 「【登場時】自分か相手のライフの上から1枚までを見て、 ライフの上か下に置く。
    **その後**、 自分のライフの枚数が相手より少ない場合、 このキャラは、 このターン中、
    【速攻】を得る。」
    ⚠ 2026-08-11 是正: 旧 overlay は effect 全体を `if` で gate しており、 ライフが相手以上だと
      **scry ごと不発** だった。 さらに scry 自体が overlay から欠落していた。 このテストは
      その旧構造 (effect-level if) を assert していたので、 正しい構造に合わせて書き換える。
    """
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "ST07-003", "on_play")
    # ⚠ _cond_of は conditional の中まで見るヘルパーなので、 ここでは **top-level** を直接見る。
    assert not eff.get("if") and not eff.get("conditions"), \
        "effect 全体に条件が残っている (公式は scry 無条件 → 速攻だけが条件付き)"
    do = eff["do"]
    assert any("scry_life" in p for p in do), "公式テキスト前半の scry_life が無い"
    cond = next((p["conditional"] for p in do if "conditional" in p), None)
    assert cond is not None, "【速攻】を包む conditional が無い"
    assert cond["if"].get("self_life_lt_opp") is True, \
        "conditional の条件が self_life_lt_opp でない"
    assert any("give_keyword" in p for p in cond["do"]), \
        "conditional の中身が【速攻】付与でない"

    # 条件そのものの評価 (成立 / 不成立)
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    st.players[0].life = [repo.get(_FILLER)] * 1
    st.players[1].life = [repo.get(_FILLER)] * 3
    assert eval_condition(cond["if"], st, st.players[0], None) is True, \
        "自1 < 相手3 で 条件成立するべき"

    st2 = _state(repo, _NEUTRAL_LEADER, overlay)
    st2.players[0].life = [repo.get(_FILLER)] * 4
    st2.players[1].life = [repo.get(_FILLER)] * 2
    assert eval_condition(cond["if"], st2, st2.players[0], None) is False, \
        "自4 > 相手2 で 条件不成立のはず"


# --------------------------------------------------------------------------- #
#  ST07-004 シャーロット・スナック (CHARACTER 黄 cost5):
#    【ドン!!×1】【アタック時】自ライフ上下1→手札できる：
#      このキャラは このバトル中【バニッシュ】を得て パワー+1000。
# --------------------------------------------------------------------------- #
def test_st07_004_on_attack_banish_and_pump_ai():
    """AI: cost (ライフ上1→手札) を払い、 自身に バニッシュ + パワー+1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    attacker = InPlay.of(repo.get("ST07-004"), sickness=False)  # power 6000
    attacker.attached_dons = 1  # 【ドン!!×1】
    me.characters = [attacker]

    eff = _eff(overlay, "ST07-004", "on_attack")
    assert _cond_of(eff).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    life_before = len(me.life)
    power_before = attacker.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, pick=[0])

    # ST07-004 も本文に「バニッシュ」を含むため granted_keywords で効果由来の付与を判定。
    assert "バニッシュ" in attacker.granted_keywords, \
        "自身に【バニッシュ】が granted_keywords に付与されていない"
    assert attacker.power == power_before + 1000, \
        f"自身の パワー+1000 が反映されていない: {attacker.power} (before {power_before})"
    assert len(me.life) == life_before - 1, "任意コストで自ライフ上1枚が手札へ移っていない"


def test_st07_004_on_attack_human_optional_confirm():
    """人間: 任意コスト (自ライフ上下1→手札) の確認 modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    attacker = InPlay.of(repo.get("ST07-004"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]

    execute_effect(_eff(overlay, "ST07-004", "on_attack")["do"][0], st, me, opp,
                   attacker)
    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"


# --------------------------------------------------------------------------- #
#  ST07-005 シャーロット・ダイフク (CHARACTER 黄 cost4):
#    【ドン!!×1】【アタック時】自ライフ上下1→手札できる：デッキ上1枚をライフの上に加える。
# --------------------------------------------------------------------------- #
def test_st07_005_on_attack_life_swap_ai():
    """AI: cost (ライフ上1→手札 = life-1/hand+1) → デッキ上1枚をライフへ (deck-1/life+1)。
    net = ライフ枚数 維持、 デッキ-1、 手札+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = []
    attacker = InPlay.of(repo.get("ST07-005"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]

    eff = _eff(overlay, "ST07-005", "on_attack")
    assert _cond_of(eff).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    life_before = len(me.life)
    deck_before = len(me.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, pick=[0])

    assert len(me.hand) == 1, "任意コストで自ライフ上1枚が手札へ移っていない (hand+1)"
    assert len(me.deck) == deck_before - 1, "デッキ上1枚がライフへ移っていない (deck-1)"
    assert len(me.life) == life_before, \
        f"ライフ枚数が維持されていない (cost-1 + 効果+1): {len(me.life)}"


# --------------------------------------------------------------------------- #
#  ST07-007 シャーロット・ブリュレ (CHARACTER 黄 cost3):
#    【ブロッカー】。 overlay: 【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_st07_007_trigger_self_play_ai():
    """【トリガー】このカードを登場させる (AI)。 trash から場に出る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.trash = [repo.get("ST07-007")]
    st.current_source_card_id = "ST07-007"

    for prim in _eff(overlay, "ST07-007", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST07-007"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "ST07-007" for c in me.characters), \
        "トリガーで シャーロット・ブリュレ が登場していない"


def test_st07_007_is_blocker():
    """【ブロッカー】が intrinsic に付いている (公式テキスト忠実)。"""
    repo = _repo()
    brulee = InPlay.of(repo.get("ST07-007"), sickness=False)
    assert brulee.is_blocker_now, "ST07-007 は【ブロッカー】を持つべき"


# --------------------------------------------------------------------------- #
#  ST07-008 シャーロット・プリン (CHARACTER 黄 cost2):
#    【登場時】自か相手のライフ上1枚までを見て、上か下に置く (scry)。
# --------------------------------------------------------------------------- #
def test_st07_008_on_play_scry_ai():
    """AI: scry_life (self_or_opp depth1)。 ライフ枚数は不変 (見て上下に置くだけ)、 crash しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    opp.life = [repo.get(_FILLER)] * 2

    my_life_before = len(me.life)
    opp_life_before = len(opp.life)
    for prim in _eff(overlay, "ST07-008", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST07-008"), sickness=True))
    _drain(st, [0])
    assert len(me.life) == my_life_before, "scry で自ライフ枚数が変わってはいけない"
    assert len(opp.life) == opp_life_before, "scry で相手ライフ枚数が変わってはいけない"


# --------------------------------------------------------------------------- #
#  ST07-009 シャーロット・モンドール (CHARACTER 黄 cost3):
#    【起動メイン】このキャラをレスト + 自ライフ上下1→手札できる：相手コスト3以下1枚をKO。
#    【トリガー】手札1枚を捨てられる：このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_st07_009_activate_main_ko_ai():
    """起動メイン: 自レスト + ライフ上1→手札 (cost) → 相手コスト3以下1枚をKO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    mondor = InPlay.of(repo.get("ST07-009"), sickness=False)
    me.characters = [mondor]
    me.life = [repo.get(_FILLER)] * 2
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=3)
    opp.characters = [victim]

    life_before = len(me.life)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST07-009"]
    assert len(opts) == 1, f"ST07-009 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])

    assert victim not in opp.characters, "相手コスト3以下キャラがKOされていない"
    assert mondor.rested is True, "起動メインの任意コストで自身がレストされるべき"
    assert len(me.life) == life_before - 1, "任意コストで自ライフ上1枚が手札へ移っていない"


def test_st07_009_activate_main_no_valid_target():
    """相手にコスト4以上のキャラしか居ない場合、 KO 対象外 (KO されない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    mondor = InPlay.of(repo.get("ST07-009"), sickness=False)
    me.characters = [mondor]
    me.life = [repo.get(_FILLER)] * 2
    big = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # cost7 (>3)
    opp.characters = [big]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST07-009"]
    if opts:
        fire_activate_main(st, me, opp, *opts[0])
        _drain(st, pick=[0])
    assert big in opp.characters, "コスト4以上のキャラが KO されてはいけない (対象外)"


def test_st07_009_trigger_discard_then_play_self_ai():
    """【トリガー】手札1枚を捨てて (cost) このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.hand = [repo.get(_FILLER)]        # 捨てるコスト用
    me.trash = [repo.get("ST07-009")]    # トリガー処理で trash から登場
    st.current_source_card_id = "ST07-009"

    hand_before = len(me.hand)
    for prim in _eff(overlay, "ST07-009", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST07-009"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "ST07-009" for c in me.characters), \
        "トリガーで シャーロット・モンドール が登場していない"
    assert len(me.hand) == hand_before - 1, "登場コストで手札1枚が捨てられるべき"


# --------------------------------------------------------------------------- #
#  ST07-010 シャーロット・リンリン (CHARACTER 黄 cost7):
#    【登場時】相手は以下から1つを選ぶ。
#      ・相手のライフ上1枚をトラッシュに置く。 ・自デッキ上1枚をライフの上に加える。
# --------------------------------------------------------------------------- #
def test_st07_010_on_play_opp_choice_ai():
    """【登場時】相手 (opp=AI) が 2 択を自動解決。 いずれか一方のみが起きる:
    (A) 相手ライフ→トラッシュ (opp.life-1 / opp.trash+1)、 または
    (B) 自デッキ上→ライフ (me.deck-1 / me.life+1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 2
    me.life = [repo.get(_FILLER)] * 2

    opp_life_before = len(opp.life)
    opp_trash_before = len(opp.trash)
    my_life_before = len(me.life)
    my_deck_before = len(me.deck)
    for prim in _eff(overlay, "ST07-010", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST07-010"), sickness=True))
    _drain(st, [0])

    opt_a = (len(opp.life) == opp_life_before - 1
             and len(opp.trash) == opp_trash_before + 1)
    opt_b = (len(me.life) == my_life_before + 1
             and len(me.deck) == my_deck_before - 1)
    assert opt_a != opt_b, \
        ("相手選択の 2 択の いずれか一方 のみが起きるべき "
         f"(A={opt_a}, B={opt_b})")


# --------------------------------------------------------------------------- #
#  ST07-011 ゼウス (CHARACTER 黄 cost3 ビッグ・マム海賊団/ホーミーズ):
#    【起動メイン】このキャラをレストにできる：自分の「シャーロット・リンリン」1枚までは
#      このターン中【バニッシュ】を得る。
#    【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_st07_011_activate_main_grant_banish_to_linlin_ai():
    """起動メイン: 自レスト → 自分の「シャーロット・リンリン」に【バニッシュ】付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)  # 非リンリンleader → 候補はキャラ1体のみ
    me, opp = st.players[0], st.players[1]
    zeus = InPlay.of(repo.get("ST07-011"), sickness=False)
    linlin = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)  # シャーロット・リンリン
    me.characters = [zeus, linlin]

    assert not linlin.has_keyword_active("バニッシュ"), "前提: 付与前は バニッシュ 無し"
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST07-011"]
    assert len(opts) == 1, f"ST07-011 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert linlin.has_keyword_active("バニッシュ"), \
        "自分の「シャーロット・リンリン」に【バニッシュ】が付与されていない"
    assert zeus.rested is True, "起動メインコストで ゼウス がレストされるべき"


def test_st07_011_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    zeus = InPlay.of(repo.get("ST07-011"), sickness=False)
    linlin = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)
    me.characters = [zeus, linlin]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST07-011"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST07-011"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_st07_011_activate_main_human_pick():
    """人間 + 「シャーロット・リンリン」複数 (リーダー+キャラ) → target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _BM_LEADER, overlay, human_idx=0)  # リーダーも シャーロット・リンリン
    me, opp = st.players[0], st.players[1]
    zeus = InPlay.of(repo.get("ST07-011"), sickness=False)
    linlin = InPlay.of(repo.get(_LINLIN_CHARA), sickness=False)
    me.characters = [zeus, linlin]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST07-011"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数「リンリン」候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    char_idx = next(i for i, c in enumerate(cands) if c["iid"] == linlin.instance_id)
    resolve_pending_choice(st, [char_idx])
    _drain(st, [0])
    assert linlin.has_keyword_active("バニッシュ"), \
        "人間が選んだ「シャーロット・リンリン」に【バニッシュ】が付与されていない"


def test_st07_011_trigger_self_play_ai():
    """【トリガー】このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.trash = [repo.get("ST07-011")]
    st.current_source_card_id = "ST07-011"

    for prim in _eff(overlay, "ST07-011", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST07-011"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "ST07-011" for c in me.characters), \
        "トリガーで ゼウス が登場していない"
