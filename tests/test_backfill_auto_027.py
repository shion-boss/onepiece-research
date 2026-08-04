# -*- coding: utf-8 -*-
"""OP02 弾 効果 回帰テスト バックフィル (自動生成 wave 027):
OP02-005 / OP02-008 / OP02-009 / OP02-010 / OP02-011 / OP02-014 /
OP02-015 / OP02-016 / OP02-017 / OP02-018 の 10 枚 (= 赤 白ひげ海賊団 系)。

目的 (= test_backfill_auto_001〜026.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / サーチ / 手札登場 を 持つカードは 人間 actor で pending_choice が
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
)

ROOT = Path(__file__).resolve().parent.parent


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` の両対応)。

    ⚠ 2026-08-05: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を **効果のみ** の
    gate とする (cardqa_op_02 / cardqa_st_04)。 top-level `if` に置くと **任意コストの支払いごと
    消える** ので、 overlay ではこの形の条件を `conditional` の中に移した。
    条件そのものは変わっていないので、 テストはどちらの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    for _prim in eff.get("do") or []:
        if isinstance(_prim, dict) and "conditional" in _prim:
            return (_prim.get("conditional") or {}).get("if") or {}
    return {}


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004、 cost2 赤) で埋める。"""
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
    """指定 card_id の overlay から when 一致の効果の do 配列を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# WB = 白ひげ海賊団 を含む 赤 リーダー (= OP02-008/009/018 の条件節を成立させる用)
WB_LEADER = "OP02-001"  # エドワード・ニューゲート (四皇/白ひげ海賊団, 赤)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op02_wave27_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP02-005", "OP02-008", "OP02-009", "OP02-010", "OP02-011",
           "OP02-014", "OP02-015", "OP02-016", "OP02-017", "OP02-018"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP02-005 カーリー・ダダン: 【登場時】自分のデッキの上から5枚までを見て、
#    コスト1の赤のキャラ1枚までを公開し、手札に加える。その後、残りをデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op02_005_dadan_on_play_search_cost1_red_char_ai():
    """登場時: デッキから コスト1 の 赤キャラ 1枚 を手札に加える (AI 自動)。
    デッキ先頭に ホワイティベイ (OP02-014, cost1 赤) を仕込み、 残りは cost2 の
    ST01-004 (= filter 非該当) で埋める → 唯一の候補が手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP02-014")] + [repo.get("ST01-004")] * 29

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP02-005", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-005"), sickness=True))

    assert len(me.hand) == hand_before + 1, \
        f"サーチで手札が1枚増えていない: {len(me.hand)}"
    assert any(c.card_id == "OP02-014" for c in me.hand), \
        "コスト1の赤キャラ (ホワイティベイ) が手札に加わっていない"


def test_op02_005_dadan_search_human_pick():
    """人間 + デッキに コスト1赤キャラ 複数 → search_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # 2 枚の cost1 赤キャラ (limit=1 を超える候補)
    me.deck = [repo.get("OP02-014"), repo.get("OP02-010")] + [repo.get("ST01-004")] * 28

    do, _ = _do(overlay, "OP02-005", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-005"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補超過で search_pick modal が立たない"
    assert st.pending_choice.get("kind") == "search_pick", \
        f"kind が search_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"cost1赤候補が2枚でない: {len(cands)}"

    dogla_idx = next(i for i, c in enumerate(cands) if c["card_id"] == "OP02-010")
    resolve_pending_choice(st, [dogla_idx])
    _drain_choices(st)
    assert any(c.card_id == "OP02-010" for c in me.hand), \
        "人間が選んだキャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP02-008 ジョズ: 【ドン!!×1】自分のライフが2枚以下でかつ、自分のリーダーが
#    『白ひげ海賊団』を含む特徴を持つ場合、このキャラは【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op02_008_jozu_on_attached_don_grants_rush():
    """ドン!!×1 条件成立 (ライフ2以下 + WB リーダー): 自身 (self) が【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2  # ライフ 2 (= 条件成立)
    jozu = InPlay.of(repo.get("OP02-008"), sickness=True)
    jozu.attached_dons = 1
    me.characters = [jozu]

    assert "速攻" not in jozu.granted_keywords
    do, eff = _do(overlay, "OP02-008", "on_attached_don")
    assert _cond_of(eff).get("leader_feature") == "白ひげ海賊団", \
        "overlay の リーダー特徴条件 (白ひげ海賊団) が無い"
    assert _cond_of(eff).get("self_life_le") == 2, \
        "overlay の ライフ2以下条件が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, jozu)

    assert "速攻" in jozu.granted_keywords, \
        "ドン!!×1 + 条件成立で【速攻】が付与されていない"


# --------------------------------------------------------------------------- #
#  OP02-009 スクアード: 【登場時】自分のリーダーが『白ひげ海賊団』を含む特徴を持つ場合、
#    相手のキャラ1枚までを、このターン中、パワー-4000し、自分のライフの上から1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op02_009_squard_on_play_debuff_and_life_to_hand_ai():
    """登場時 (WB リーダー): 相手キャラ -4000 + 自ライフ上1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.life = [repo.get("ST01-004")] * 3
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    opp.characters = [victim]

    power_before = victim.power
    hand_before = len(me.hand)
    life_before = len(me.life)
    do, eff = _do(overlay, "OP02-009", "on_play")
    assert "白ひげ海賊団" in _cond_of(eff).get("leader_features_any", []), \
        "overlay の リーダー特徴条件 (白ひげ海賊団) が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-009"), sickness=True))

    assert victim.power == power_before - 4000, \
        f"相手キャラの -4000 が反映されていない: {victim.power} (before {power_before})"
    assert len(me.hand) == hand_before + 1, "自ライフ上1枚が手札に加わっていない"
    assert len(me.life) == life_before - 1, "ライフが1枚減っていない"


def test_op02_009_squard_debuff_human_pick():
    """人間 + 相手キャラ 複数 → -4000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 3
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    b = InPlay.of(repo.get("OP02-010"), sickness=False)  # power 2000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP02-009", "on_play")
    pump_prim = next(p for p in do if "power_pump" in p)
    execute_effect(pump_prim, st, me, opp,
                   InPlay.of(repo.get("OP02-009"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b.power == b_before - 4000, "人間が選んだキャラに -4000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP02-010 ドグラ: 【起動メイン】このキャラをレストにできる：
#    自分の手札から「ドグラ」以外のコスト1の赤のキャラ1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op02_010_dogla_activate_main_play_from_hand_ai():
    """起動メイン: 自身をレスト → 手札から「ドグラ」以外の コスト1赤キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    dogla = InPlay.of(repo.get("OP02-010"), sickness=False)
    me.characters = [dogla]
    me.hand = [repo.get("OP02-014")]  # ホワイティベイ (cost1 赤, ≠ ドグラ)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-010"]
    assert len(opts) == 1, f"OP02-010 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain_choices(st)

    assert dogla.rested is True, "起動メインのコストで自身がレストになっていない"
    assert any(c.card.card_id == "OP02-014" for c in me.characters), \
        "手札のコスト1赤キャラが登場していない"


def test_op02_010_dogla_play_from_hand_human_pick():
    """人間 + 手札に候補 複数 → play_from_hand_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    dogla = InPlay.of(repo.get("OP02-010"), sickness=False)
    me.characters = [dogla]
    me.hand = [repo.get("OP02-014"), repo.get("OP02-015")]  # cost1 赤 2 枚

    do, _ = _do(overlay, "OP02-010", "activate_main")
    for prim in do:
        execute_effect(prim, st, me, opp, dogla)

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand_pick modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"手札候補が2枚でない: {len(cands)}"

    wbay_idx = next(i for i, c in enumerate(cands) if c["card_id"] == "OP02-014")
    resolve_pending_choice(st, [wbay_idx])
    _drain_choices(st)
    assert any(c.card.card_id == "OP02-014" for c in me.characters), \
        "人間が選んだキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP02-011 ビスタ: 【登場時】相手のパワー3000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op02_011_vista_on_play_ko_power_le3000_ai():
    """登場時: 相手のパワー3000以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000 (<=3000)
    assert victim.power <= 3000
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-011", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-011"), sickness=True))

    assert victim not in opp.characters, "パワー3000以下キャラが KO されていない"


def test_op02_011_vista_ko_human_pick():
    """人間 + 相手パワー3000以下キャラ 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    b = InPlay.of(repo.get("OP02-010"), sickness=False)  # power 2000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP02-011", "on_play")
    ko_prim = next(p for p in do if "ko" in p)
    execute_effect(ko_prim, st, me, opp,
                   InPlay.of(repo.get("OP02-011"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


# --------------------------------------------------------------------------- #
#  OP02-014 ホワイティベイ: 【ドン!!×1】このキャラは相手のアクティブのキャラにもアタックできる。
# --------------------------------------------------------------------------- #
def test_op02_014_whitey_bay_grants_active_attack():
    """ドン!!×1: 自身に「アクティブアタック可」キーワードが付与される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    wbay = InPlay.of(repo.get("OP02-014"), sickness=False)
    wbay.attached_dons = 1
    me.characters = [wbay]

    assert "アクティブアタック可" not in wbay.granted_keywords
    do, _ = _do(overlay, "OP02-014", "on_attached_don")
    for prim in do:
        execute_effect(prim, st, me, opp, wbay)

    assert "アクティブアタック可" in wbay.granted_keywords, \
        "ドン!!×1 で「アクティブアタック可」が付与されていない"


# --------------------------------------------------------------------------- #
#  OP02-015 マキノ: 【起動メイン】このキャラをレストにできる：
#    自分のコスト1の赤のキャラ1枚までを、このターン中、パワー+3000。
# --------------------------------------------------------------------------- #
def test_op02_015_makino_activate_main_pump_cost1_ai():
    """起動メイン相当の do: 自分のコスト1キャラを +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    makino = InPlay.of(repo.get("OP02-015"), sickness=False)
    target = InPlay.of(repo.get("OP02-014"), sickness=False)  # cost1 赤, power 2000
    me.characters = [makino, target]

    power_before = target.power
    do, eff = _do(overlay, "OP02-015", "activate_main")
    assert eff.get("cost", {}).get("rest_self") is True, \
        "overlay の起動メインコスト rest_self が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, makino)
    _drain_choices(st)

    assert target.power == power_before + 3000, \
        f"コスト1キャラへの +3000 が反映されていない: {target.power} (before {power_before})"


def test_op02_015_makino_activate_main_legal_and_rests():
    """起動メインが legal に出て、 発動で自身 (マキノ) がレストになる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    makino = InPlay.of(repo.get("OP02-015"), sickness=False)
    target = InPlay.of(repo.get("OP02-014"), sickness=False)
    me.characters = [makino, target]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-015"]
    assert len(opts) == 1, f"OP02-015 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain_choices(st)
    assert makino.rested is True, "起動メインのコストで自身がレストになっていない"


# --------------------------------------------------------------------------- #
#  OP02-016 マグラ: 【登場時】自分のコスト1の赤のキャラ1枚までを、このターン中、パワー+3000。
# --------------------------------------------------------------------------- #
def test_op02_016_magra_on_play_pump_cost1_red_ai():
    """登場時: 自分のコスト1赤キャラを +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get("OP02-014"), sickness=False)  # cost1 赤, power 2000
    me.characters = [target]

    power_before = target.power
    do, _ = _do(overlay, "OP02-016", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-016"), sickness=True))

    assert target.power == power_before + 3000, \
        f"コスト1赤キャラへの +3000 が反映されていない: {target.power}"


def test_op02_016_magra_pump_human_pick():
    """人間 + 自コスト1赤キャラ 複数 → +3000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP02-014"), sickness=False)  # cost1 赤
    b = InPlay.of(repo.get("OP02-010"), sickness=False)  # cost1 赤
    me.characters = [a, b]

    do, _ = _do(overlay, "OP02-016", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-016"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b.power == b_before + 3000, "人間が選んだキャラに +3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP02-017 マスクド・デュース: 【ドン!!×2】【アタック時】相手のパワー2000以下のキャラ
#    1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op02_017_masked_deuce_attack_ko_power_le2000_ai():
    """アタック時 (ドン!!×2 ゲート): 相手のパワー2000以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP02-017"), sickness=False)
    attacker.attached_dons = 2  # 【ドン!!×2】ゲート成立
    me.characters = [attacker]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000 (<=2000)
    assert victim.power <= 2000
    opp.characters = [victim]

    do, eff = _do(overlay, "OP02-017", "on_attack")
    assert _cond_of(eff).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)

    assert victim not in opp.characters, "パワー2000以下キャラが KO されていない"


def test_op02_017_masked_deuce_ko_human_pick():
    """人間 + 相手パワー2000以下キャラ 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP02-017"), sickness=False)
    attacker.attached_dons = 2
    me.characters = [attacker]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    b = InPlay.of(repo.get("OP02-010"), sickness=False)  # power 2000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP02-017", "on_attack")
    ko_prim = next(p for p in do if "ko" in p)
    execute_effect(ko_prim, st, me, opp, attacker)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP02-018 マルコ: 【ブロッカー】【KO時】自分の手札から『白ひげ海賊団』を含む特徴を持つ
#    カード1枚を捨てることができる：自分のライフが2枚以下の場合、このキャラカードを
#    トラッシュからレストで登場させる。
# --------------------------------------------------------------------------- #
def test_op02_018_marco_on_ko_revive_from_trash_rested_ai():
    """KO時: 条件成立 (ライフ2以下) で 自身をトラッシュからレストで登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # KO 済 = トラッシュに OP02-018、 self_inplay=None、 source を明示
    me.trash = [repo.get("OP02-018")]
    me.life = [repo.get("ST01-004")] * 2  # ライフ 2 (= 条件成立)
    st.current_source_card_id = "OP02-018"

    trash_before = len(me.trash)
    chars_before = len(me.characters)
    do, eff = _do(overlay, "OP02-018", "on_ko")
    assert _cond_of(eff).get("self_life_le") == 2, \
        "overlay の ライフ2以下条件が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.characters) == chars_before + 1, \
        "マルコがトラッシュから登場していない"
    revived = me.characters[-1]
    assert revived.card.card_id == "OP02-018", "登場したキャラがマルコでない"
    assert revived.rested is True, "レストで登場していない"
    assert len(me.trash) == trash_before - 1, "トラッシュからマルコが取り除かれていない"
