# -*- coding: utf-8 -*-
"""OP08 弾 (ドラム王国 / チョッパー) 効果 回帰テスト バックフィル (自動生成 wave 083):
OP08-007 / OP08-008 / OP08-010 / OP08-012 / OP08-013 / OP08-014 /
OP08-015 / OP08-016 / OP08-017 / OP08-018 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
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


def _drain(st, pick=0, guard=8):
    """pending_choice を pick を選び続けて解決しきる (後続の reorder 等を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        cands = st.pending_choice.get("candidates")
        cards = st.pending_choice.get("cards")
        if cands is not None and len(cands) == 0:
            resolve_pending_choice(st, [])
        elif cards is not None and not cands:
            # search_top_n 系: cards から選ぶ (reorder は空でも可)
            resolve_pending_choice(st, [pick] if any(
                c.get("matches_filter") for c in cards) else [])
        else:
            resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op08_wave083_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP08-007", "OP08-008", "OP08-010", "OP08-012", "OP08-013",
           "OP08-014", "OP08-015", "OP08-016", "OP08-017", "OP08-018"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP08-007 トニートニー・チョッパー:
#    【自分のターン中】【登場時】/【アタック時】デッキ上5枚から
#    パワー4000以下の《動物》キャラ1枚までをレストで登場、残りをデッキ下
# --------------------------------------------------------------------------- #
def test_op08_007_chopper_on_play_summon_animal_ai():
    """【登場時】(自ターン) デッキ上5枚から《動物》power4000以下を レストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    animal = repo.get("OP08-010")  # ハイキングベア 動物 power3000
    assert "動物" in (animal.features or "") and animal.power <= 4000
    me.deck = [animal] + [repo.get("OP01-013")] * 10

    on_play = next(e for e in overlay.get("OP08-007").effects
                   if e["when"] == "on_play")
    assert on_play.get("conditions", [{}])[0].get("self_turn") is True, \
        "overlay の 自ターン条件 self_turn が無い"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-007"), sickness=True))
    _drain(st)

    summoned = [c for c in me.characters if c.card.card_id == "OP08-010"]
    assert len(summoned) == 1, "《動物》キャラがデッキ上5枚から登場していない"
    assert summoned[0].rested is True, "登場したキャラはレストであるべき"


def test_op08_007_chopper_on_attack_same_effect_ai():
    """【アタック時】も 同一 effect (デッキ上5枚→《動物》レスト登場) が発火する (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP08-012")] + [repo.get("OP01-013")] * 10  # ラパーン 動物 3000
    chars_before = len(me.characters)

    on_attack = next(e for e in overlay.get("OP08-007").effects
                     if e["when"] == "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-007"), sickness=False))
    _drain(st)
    assert len(me.characters) == chars_before + 1, \
        "アタック時にデッキ上5枚から 1 体が登場していない"


def test_op08_007_chopper_on_play_human_search_modal():
    """人間 + デッキ上5枚に《動物》複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP08-010"), repo.get("OP08-012")] + [repo.get("OP01-013")] * 10

    on_play = next(e for e in overlay.get("OP08-007").effects
                   if e["when"] == "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-007"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    cards = st.pending_choice.get("cards", [])
    matches = [c for c in cards if c.get("matches_filter")]
    assert len(matches) >= 2, f"《動物》候補が2枚以上見えていない: {len(matches)}"
    _drain(st)
    assert any(c.card.card_id in ("OP08-010", "OP08-012") for c in me.characters), \
        "人間が選んだ《動物》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP08-008 ドルトン: 【登場時】相手キャラ1枚まで -1000 /
#    【ドン×1】【起動メイン】【ターン1回】ライフ上1枚を手札→自身に【速攻】
# --------------------------------------------------------------------------- #
def test_op08_008_dolton_on_play_debuff_ai():
    """【登場時】相手のキャラ1枚を このターン中 パワー-1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    opp.characters = [victim]

    before = victim.power
    on_play = next(e for e in overlay.get("OP08-008").effects
                   if e["when"] == "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-008"), sickness=True))
    _drain(st)
    assert victim.power == before - 1000, \
        f"登場時 -1000 が反映されていない: {victim.power} (before {before})"


def test_op08_008_dolton_on_play_human_target_pick():
    """人間 + 相手キャラ複数 → target_pick modal が立ち resolve で 1 体に -1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # 3000
    opp.characters = [a, b]

    on_play = next(e for e in overlay.get("OP08-008").effects
                   if e["when"] == "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-008"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before - 1000, "人間が選んだ相手キャラに -1000 が反映されていない"


def test_op08_008_dolton_activate_main_life_to_hand_rush_ai():
    """【起動メイン】(ドン1) ライフ上1枚を手札に加える → 自身が【速攻】(sickness 解除)。 AI。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    dolton = InPlay.of(repo.get("OP08-008"), sickness=True)  # 登場酔い状態
    dolton.attached_dons = 1
    me.characters = [dolton]
    me.life = [repo.get("OP01-013")] * 3
    life_before = len(me.life)
    hand_before = len(me.hand)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-008"]
    assert len(opts) == 1, f"OP08-008 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=1)  # optional コストは 承諾 (=1)

    assert len(me.life) == life_before - 1, "ライフ上1枚が手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "手札が1枚増えていない"
    assert dolton.summoning_sickness is False, "起動メイン後 自身が【速攻】を得ていない"


# --------------------------------------------------------------------------- #
#  OP08-010 ハイキングベア:
#    【ドン×1】【起動メイン】【ターン1回】このキャラ以外の自《動物》1枚まで +1000
# --------------------------------------------------------------------------- #
def test_op08_010_hiking_bear_activate_main_pump_ai():
    """【起動メイン】(ドン1) 自身以外の《動物》1枚を +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    bear = InPlay.of(repo.get("OP08-010"), sickness=False)
    bear.attached_dons = 1
    other = InPlay.of(repo.get("OP08-012"), sickness=False)  # ラパーン 動物
    me.characters = [bear, other]
    other_before = other.power

    eff = overlay.get("OP08-010").effects[0]
    assert _cond_of(eff).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-010"]
    assert len(opts) == 1, f"OP08-010 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)
    assert other.power == other_before + 1000, \
        f"自《動物》キャラに +1000 が反映されていない: {other.power}"


def test_op08_010_hiking_bear_excludes_self():
    """対象は「このキャラ以外」。 自身 (ハイキングベア) は候補から除外される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    bear = InPlay.of(repo.get("OP08-010"), sickness=False)
    bear.attached_dons = 1
    other = InPlay.of(repo.get("OP08-012"), sickness=False)
    me.characters = [bear, other]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-010"]
    fire_activate_main(st, me, opp, *opts[0])
    if st.pending_choice is not None:
        cands = st.pending_choice.get("candidates", [])
        assert all(c["iid"] != bear.instance_id for c in cands), \
            "自身 (ハイキングベア) が対象候補に含まれてはいけない"
        _drain(st)
    else:
        # 候補が other 1 体のみ → 自動適用。 自身 pump されていないこと。
        assert bear.power == repo.get("OP08-010").power, "自身が pump されてはいけない"


# --------------------------------------------------------------------------- #
#  OP08-012 ラパーン: 【ドン×2】【アタック時】自リーダーが《ドラム王国》なら
#    相手のパワー4000以下のキャラ1枚までを KO
# --------------------------------------------------------------------------- #
def test_op08_012_lapan_attack_ko_ai():
    """【アタック時】(ドン2 + 自リーダー ドラム王国) 相手 power4000以下1枚 KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)  # チョッパー = ドラム王国 leader
    me, opp = st.players[0], st.players[1]
    lapan = InPlay.of(repo.get("OP08-012"), sickness=False)
    lapan.attached_dons = 2
    me.characters = [lapan]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000 <= 4000
    opp.characters = [victim]

    eff = overlay.get("OP08-012").effects[0]
    assert _cond_of(eff).get("leader_feature") == "ドラム王国", \
        "overlay に leader_feature=ドラム王国 gate が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, lapan)
    _drain(st)
    assert victim not in opp.characters, "相手の power4000以下キャラが KO されていない"


def test_op08_012_lapan_attack_human_ko_pick():
    """人間 + 相手 power4000以下複数 → target_pick modal で 1 体 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    lapan = InPlay.of(repo.get("OP08-012"), sickness=False)
    lapan.attached_dons = 2
    me.characters = [lapan]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # 3000
    opp.characters = [a, b]

    eff = overlay.get("OP08-012").effects[0]
    execute_effect(eff["do"][0], st, me, opp, lapan)
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=0)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP08-013 ロブソン: 【ドン×2】このキャラは【速攻】を得る (静的)
# --------------------------------------------------------------------------- #
def test_op08_013_robson_static_rush_with_2_don():
    """ドン2枚付与で 静的に【速攻】(static_granted_keywords) を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    robson = InPlay.of(repo.get("OP08-013"), sickness=True)
    robson.attached_dons = 2
    me.characters = [robson]

    evaluate_static_effects(st, overlay)
    assert "速攻" in robson.static_granted_keywords, \
        "ドン2枚で【速攻】が static_granted に付与されていない"


def test_op08_013_robson_no_rush_with_1_don():
    """ドン1枚では【ドン×2】ゲート不成立 → 【速攻】は付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    robson = InPlay.of(repo.get("OP08-013"), sickness=True)
    robson.attached_dons = 1
    me.characters = [robson]

    evaluate_static_effects(st, overlay)
    assert "速攻" not in robson.static_granted_keywords, \
        "ドン1枚で【速攻】が付与されてはいけない (ゲート不成立)"


# --------------------------------------------------------------------------- #
#  OP08-014 ワポル: 【ドン×1】【アタック時】相手キャラ1枚 -2000 →
#    その後 自身は 次の相手ターン終了時まで +2000
# --------------------------------------------------------------------------- #
def test_op08_014_wapol_attack_debuff_and_self_pump_ai():
    """【アタック時】相手キャラ -2000 + 自身 +2000 (次相手ターン終了時まで) (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    wapol = InPlay.of(repo.get("OP08-014"), sickness=False)
    wapol.attached_dons = 1
    me.characters = [wapol]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    opp.characters = [victim]
    v_before, w_before = victim.power, wapol.power

    eff = overlay.get("OP08-014").effects[0]
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, wapol)
    _drain(st)
    assert victim.power == v_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power}"
    assert wapol.power == w_before + 2000, \
        f"自身 +2000 が反映されていない: {wapol.power}"


# --------------------------------------------------------------------------- #
#  OP08-015 Dr.くれは: 【登場時】デッキ上4枚から「Dr.くれは」以外の
#    《ドラム王国》 or「トニートニー・チョッパー」1枚まで 公開 → 手札、残りデッキ下
# --------------------------------------------------------------------------- #
def test_op08_015_kureha_on_play_search_hand_ai():
    """【登場時】デッキ上4枚から《ドラム王国》1枚を手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    drum = repo.get("OP08-010")  # ドラム王国
    assert "ドラム王国" in (drum.features or "")
    me.deck = [drum] + [repo.get("OP01-013")] * 10
    me.hand = []

    on_play = overlay.get("OP08-015").effects[0]
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-015"), sickness=True))
    _drain(st)
    assert any(c.card_id == "OP08-010" for c in me.hand), \
        "デッキ上4枚から《ドラム王国》カードが手札に加わっていない"


def test_op08_015_kureha_on_play_human_search_modal():
    """人間 + デッキ上4枚に候補複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP08-010"), repo.get("OP08-012")] + [repo.get("OP01-013")] * 10
    me.hand = []

    on_play = overlay.get("OP08-015").effects[0]
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-015"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    _drain(st)
    assert any(c.card_id in ("OP08-010", "OP08-012") for c in me.hand), \
        "人間が選んだ《ドラム王国》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP08-016 Dr.ヒルルク: 【起動メイン】このキャラをレストにできる：
#    自リーダーが「トニートニー・チョッパー」なら 自「トニートニー・チョッパー」全て +2000
# --------------------------------------------------------------------------- #
def test_op08_016_hiluluk_activate_main_pump_all_chopper_ai():
    """【起動メイン】(自レスト + リーダー チョッパー) 自チョッパー全員 +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)  # リーダー = トニートニー・チョッパー
    me, opp = st.players[0], st.players[1]
    hiluluk = InPlay.of(repo.get("OP08-016"), sickness=False)
    ch1 = InPlay.of(repo.get("OP08-007"), sickness=False)  # トニートニー・チョッパー
    ch2 = InPlay.of(repo.get("OP08-007"), sickness=False)
    me.characters = [hiluluk, ch1, ch2]
    b1, b2 = ch1.power, ch2.power

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-016"]
    assert len(opts) == 1, f"OP08-016 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)
    assert ch1.power == b1 + 2000 and ch2.power == b2 + 2000, \
        f"自チョッパー全員 +2000 が反映されていない: {ch1.power}/{ch2.power}"
    assert hiluluk.rested is True, "起動メインコストで ヒルルク がレストされるべき"


def test_op08_016_hiluluk_gate_wrong_leader():
    """自リーダーが「トニートニー・チョッパー」でない場合 起動メインが legal に出ない。"""
    # ⚠ 2026-08-05 是正: コロン後の条件は **効果のみ** を gate する (cardqa_op_02:
    #   「リーダーが「イワンコフ」ではない場合、この【起動メイン】効果を発動できますか？」
    #   → 「はい。 このカードをレストにしますが、 その後の効果では何も起きません」)。
    #   「条件不成立なら legal に出ない」 は行動の合法性ごと消す旧バグの固定だった。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # リーダー = シャンクス (非チョッパー)
    me, opp = st.players[0], st.players[1]
    hiluluk = InPlay.of(repo.get("OP08-016"), sickness=False)
    me.characters = [hiluluk, InPlay.of(repo.get("OP08-007"), sickness=False)]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-016"]
    assert len(opts) == 1, \
        "任意コストは条件不成立でも払えるので legal に残るべき (cardqa_op_02)"


# --------------------------------------------------------------------------- #
#  OP08-017 おれは決して お前を撃たねェ!!!! (EVENT):
#    【カウンター】自リーダー/キャラ1枚 +4000 (battle) → 相手1枚 -1000 (turn)
#    【トリガー】自リーダー/キャラ1枚 +1000 (turn)
# --------------------------------------------------------------------------- #
def test_op08_017_counter_pump_and_debuff_ai():
    """【カウンター】自リーダー +4000 (バトル中) + 相手キャラ -1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    opp.characters = [victim]
    leader_before, v_before = me.leader.power, victim.power

    counter = next(e for e in overlay.get("OP08-017").effects
                   if e["when"] == "counter")
    for prim in counter["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert me.leader.power == leader_before + 4000, \
        f"カウンターの自リーダー +4000 が反映されていない: {me.leader.power}"
    assert victim.power == v_before - 1000, \
        f"相手キャラ -1000 が反映されていない: {victim.power}"


def test_op08_017_trigger_self_pump_ai():
    """【トリガー】自リーダー/キャラ1枚 +1000 (AI 自動、 リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    leader_before = me.leader.power

    trigger = next(e for e in overlay.get("OP08-017").effects
                   if e["when"] == "trigger")
    for prim in trigger["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert me.leader.power == leader_before + 1000, \
        f"トリガーの +1000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP08-018 刻蹄『桜』 (EVENT):
#    【メイン】自キャラ3枚まで +1000 → その後 相手キャラ1枚 -2000
#    【トリガー】相手リーダー/キャラ1枚 -3000
# --------------------------------------------------------------------------- #
def test_op08_018_main_pump_and_debuff_ai():
    """【メイン】自キャラ最大3枚 +1000 + 相手キャラ1枚 -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    c1 = InPlay.of(repo.get("OP08-007"), sickness=False)
    c2 = InPlay.of(repo.get("OP08-010"), sickness=False)
    me.characters = [c1, c2]
    b1, b2 = c1.power, c2.power
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # 2000
    opp.characters = [victim]
    v_before = victim.power

    main = next(e for e in overlay.get("OP08-018").effects if e["when"] == "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert c1.power == b1 + 1000 and c2.power == b2 + 1000, \
        f"自キャラ +1000 が反映されていない: {c1.power}/{c2.power}"
    assert victim.power == v_before - 2000, \
        f"相手キャラ -2000 が反映されていない: {victim.power}"


def test_op08_018_main_human_target_pick():
    """人間 + 相手キャラ複数 → -2000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP08-007"), sickness=False)]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [a, b]

    main = next(e for e in overlay.get("OP08-018").effects if e["when"] == "main")
    execute_effect(main["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


def test_op08_018_trigger_opp_debuff_ai():
    """【トリガー】相手リーダー/キャラ1枚 -3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # 3000
    opp.characters = [victim]
    v_before = victim.power

    trigger = next(e for e in overlay.get("OP08-018").effects
                   if e["when"] == "trigger")
    for prim in trigger["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert victim.power == v_before - 3000, \
        f"トリガーの相手 -3000 が反映されていない: {victim.power}"
