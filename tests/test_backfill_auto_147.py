# -*- coding: utf-8 -*-
"""OP16 弾 (白ひげ海賊団 / 赤髪海賊団) 効果 回帰テスト バックフィル (自動生成 wave 147):
OP16-007 / OP16-008 / OP16-009 / OP16-010 / OP16-011 /
OP16-012 / OP16-013 / OP16-014 / OP16-017 / OP16-019 の 10 枚。

目的 (= test_backfill_auto_001〜146.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 任意コスト / 対象選択 を 持つカードは 人間 actor で pending_choice が
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
    load_effect_overlay,
    resolve_pending_choice,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 副作用のない) 素材カード。 reveal / discard / KO コスト用途。
# --------------------------------------------------------------------------- #
F8000 = "EB02-042"   # バニラ パワー8000 キャラ (reveal/discard コスト素材)
F10000 = "EB02-004"  # バニラ 元々のパワー10000 キャラ (ko_self コスト素材)
SMALL = "EB01-017"   # バニラ 元々のパワー2000 キャラ (KO 対象、 ≤2000/≤8000)
MID = "EB03-002"     # バニラ パワー6000 キャラ (KO 対象 ≤8000、 -1000 対象)


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


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=10):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op16_wave147_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP16-007", "OP16-008", "OP16-009", "OP16-010", "OP16-011",
           "OP16-012", "OP16-013", "OP16-014", "OP16-017", "OP16-019"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP16-007 ジョズ (CHARACTER 赤 cost7 power8000):
#    【ブロッカー】【登場時】自分の手札からパワー8000のキャラカード1枚を公開できる：
#      相手のキャラ1枚までを、このターン中、パワー-1000。
# --------------------------------------------------------------------------- #
def test_op16_007_on_play_reveal_then_debuff_ai():
    """【登場時】手札8000公開コスト → 相手キャラ1体 -1000 (AI 自動、 公開なので手札不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(F8000)]
    hand_before = len(me.hand)
    victim = InPlay.of(repo.get(MID), sickness=False)  # power 6000
    opp.characters = [victim]
    power_before = victim.power
    do, _ = _do(overlay, "OP16-007", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-007"), sickness=True))
    _drain(st, [0])
    assert victim.power == power_before - 1000, \
        f"相手キャラのパワー-1000 が反映されていない: {victim.power} (before {power_before})"
    assert len(me.hand) == hand_before, \
        f"公開コストで手札が減ってはいけない (捨てない): hand={len(me.hand)}"


def test_op16_007_on_play_human_pay_and_pick():
    """人間 → optional_cost_confirm で pay → 相手キャラ target_pick → 選んだ1体のみ -1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(F8000)]
    big = InPlay.of(repo.get(MID), sickness=False)     # 6000
    small = InPlay.of(repo.get(SMALL), sickness=False)  # 2000
    opp.characters = [big, small]
    do, _ = _do(overlay, "OP16-007", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-007"), sickness=True))
    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"pay 後に相手キャラ target_pick が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"相手キャラ候補が2件でない: {len(cands)}"
    big_before = big.power
    small_before = small.power
    big_idx = next(i for i, c in enumerate(cands) if c["iid"] == big.instance_id)
    resolve_pending_choice(st, [big_idx])
    _drain(st, [big_idx])
    assert big.power == big_before - 1000, "人間が選んだ相手キャラに -1000 が入っていない"
    assert small.power == small_before, "選ばなかった相手キャラは変化してはいけない"


# --------------------------------------------------------------------------- #
#  OP16-008 スクアード (CHARACTER 赤 cost5 power7000):
#    【登場時】自分の元々のパワー10000のキャラ1枚をトラッシュに置くことができる：
#      相手のパワー8000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op16_008_on_play_sacrifice_then_ko_ai():
    """【登場時】自元々10000をトラッシュ (コスト) → 相手8000以下1体KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    sac = InPlay.of(repo.get(F10000), sickness=False)  # 元々10000
    me.characters = [sac]
    victim = InPlay.of(repo.get(MID), sickness=False)  # 6000 (≤8000)
    opp.characters = [victim]
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP16-008", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-008"), sickness=True))
    _drain(st, [0])
    assert sac not in me.characters, "コストの自元々10000キャラがトラッシュに置かれていない"
    assert len(me.trash) == trash_before + 1, "自キャラがトラッシュへ移っていない"
    assert victim not in opp.characters, "効果で相手8000以下キャラがKOされていない"


def test_op16_008_on_play_human_pay():
    """人間 → optional_cost_confirm で pay → 効果解決 (自犠牲 + 相手KO)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    sac = InPlay.of(repo.get(F10000), sickness=False)
    me.characters = [sac]
    victim = InPlay.of(repo.get(MID), sickness=False)
    opp.characters = [victim]
    do, _ = _do(overlay, "OP16-008", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-008"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"任意コスト確認 modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st, [0])
    assert sac not in me.characters, "pay 後に自犠牲キャラがトラッシュされていない"
    assert victim not in opp.characters, "pay 後に相手キャラがKOされていない"


# --------------------------------------------------------------------------- #
#  OP16-009 スピード・ジル (CHARACTER 赤 cost4 power5000):
#    【登場時】自分の手札からパワー8000のキャラカード1枚を捨てることができる：
#      このキャラは、次の相手のエンドフェイズ終了時まで、【速攻】を得て、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op16_009_on_play_discard_then_rush_pump_ai():
    """【登場時】手札8000捨てコスト → 自身 速攻 + パワー+2000 (次相手エンドまで、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(F8000)]
    jill = InPlay.of(repo.get("OP16-009"), sickness=True)
    me.characters = [jill]
    power_before = jill.power
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP16-009", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, jill)
    _drain(st, [0])
    assert len(me.hand) == 0, f"手札8000が捨てられていない: hand={len(me.hand)}"
    assert len(me.trash) == trash_before + 1, "捨てた手札がトラッシュへ移っていない"
    assert jill.power == power_before + 2000, \
        f"パワー+2000 が反映されていない: {jill.power} (before {power_before})"
    assert "速攻" in jill.granted_keywords_through_opp_turn, \
        f"【速攻】(次相手エンドまで) が付与されていない: {jill.granted_keywords_through_opp_turn}"


# --------------------------------------------------------------------------- #
#  OP16-010 ナミュール (CHARACTER 赤 cost1 power2000):
#    【登場時】自分の手札からパワー8000のキャラカード1枚を公開できる：
#      相手の元々のパワー2000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op16_010_on_play_reveal_then_ko_small_ai():
    """【登場時】手札8000公開 → 相手 元々2000以下1体のみKO (6000は対象外、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(F8000)]
    hand_before = len(me.hand)
    small = InPlay.of(repo.get(SMALL), sickness=False)  # 元々2000 (≤2000)
    big = InPlay.of(repo.get(MID), sickness=False)      # 元々6000 (>2000)
    opp.characters = [small, big]
    do, _ = _do(overlay, "OP16-010", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-010"), sickness=True))
    _drain(st, [0])
    assert small not in opp.characters, "相手 元々2000以下キャラがKOされていない"
    assert big in opp.characters, "元々2000超のキャラはKO対象外で残るべき"
    assert len(me.hand) == hand_before, "公開コストで手札が減ってはいけない"


def test_op16_010_on_play_human_pay_and_pick():
    """人間 → pay → 元々2000以下 target_pick が立ち、 選んだ1体をKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(F8000)]
    small = InPlay.of(repo.get(SMALL), sickness=False)
    opp.characters = [small]
    do, _ = _do(overlay, "OP16-010", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-010"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"任意コスト確認 modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st, [0])
    assert small not in opp.characters, "pay 後に相手 元々2000以下キャラがKOされていない"


# --------------------------------------------------------------------------- #
#  OP16-011 ビスタ (CHARACTER 赤 cost6 power8000):
#    【登場時】自分の手札からパワー8000のキャラカード1枚を公開できる：カード1枚を引く。
#    【ドン‼×1】【アタック時】相手の元々のパワー2000以下のキャラ2枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op16_011_on_play_reveal_then_draw_ai():
    """【登場時】手札8000公開 → 1ドロー (公開札は手札に残り、 net +1、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(F8000)]
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP16-011", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-011"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, \
        f"1ドローで手札が1枚増えていない (公開は捨てない): hand={len(me.hand)}"
    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"


def test_op16_011_on_attack_ko_two_small_with_don_ai():
    """【ドン‼×1】【アタック時】相手 元々2000以下2枚KO / 6000は残る (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    vista = InPlay.of(repo.get("OP16-011"), sickness=False)
    vista.attached_dons = 1  # ドンゲート成立
    me.characters = [vista]
    s1 = InPlay.of(repo.get(SMALL), sickness=False)
    s2 = InPlay.of(repo.get(SMALL), sickness=False)
    big = InPlay.of(repo.get(MID), sickness=False)  # 6000 (>2000)
    opp.characters = [s1, s2, big]
    do, _ = _do(overlay, "OP16-011", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, vista)
    _drain(st, [0])
    assert s1 not in opp.characters and s2 not in opp.characters, \
        "相手 元々2000以下2枚がKOされていない"
    assert big in opp.characters, "元々2000超のキャラはKO対象外で残るべき"


def test_op16_011_on_attack_no_don_no_ko():
    """ドン‼×1 未満 (attached_don=0) → アタック時KOは発火しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    vista = InPlay.of(repo.get("OP16-011"), sickness=False)
    vista.attached_dons = 0  # ドンゲート不成立
    me.characters = [vista]
    small = InPlay.of(repo.get(SMALL), sickness=False)
    opp.characters = [small]
    _, eff = _do(overlay, "OP16-011", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "ドンゲート self_attached_don_ge=1 が overlay に無い"
    assert eval_condition(eff.get("if", {}), st, me, vista) is False, \
        "attached_don=0 でドンゲート条件が成立してはいけない"


def test_op16_011_on_attack_human_pick():
    """人間 + 相手 元々2000以下 複数 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    vista = InPlay.of(repo.get("OP16-011"), sickness=False)
    vista.attached_dons = 1
    me.characters = [vista]
    opp.characters = [InPlay.of(repo.get(SMALL), sickness=False) for _ in range(3)]
    do, _ = _do(overlay, "OP16-011", "on_attack")
    execute_effect(do[0], st, me, opp, vista)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    assert len(st.pending_choice.get("candidates", [])) == 3, \
        "相手 元々2000以下候補が3件でない"
    before = len(opp.characters)
    _drain(st, [0])
    assert len(opp.characters) < before, "人間の選択でKOが1体以上起きていない"


# --------------------------------------------------------------------------- #
#  OP16-012 ベン・ベックマン (CHARACTER 赤 cost5 power6000):
#    【ブロッカー】【登場時】自分のドン‼1枚をレストにできる：自分のリーダーが特徴
#      《赤髪海賊団》を持ち、自分の場のドン‼が10枚ある場合、自分の手札から
#      「シャンクス」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op16_012_on_play_summon_shanks_when_akagami_10don_ai():
    """【登場時】赤髪海賊団リーダー + 場ドン10 → 手札「シャンクス」を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP09-001", overlay)  # シャンクス (赤髪海賊団) leader
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP16-006")]  # シャンクス (CHARACTER)
    me.don_active = 10
    me.don_rested = 0
    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP16-012", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-012"), sickness=True))
    _drain(st, [0])
    assert any(c.card.name == "シャンクス" for c in me.characters), \
        "手札の「シャンクス」が登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"
    assert me.don_rested >= 1, "コストのドン1枚レストが行われていない"


def test_op16_012_on_play_no_summon_when_not_akagami():
    """非《赤髪海賊団》リーダー → コストを払っても シャンクス は登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (麦わらの一味、 非赤髪)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP16-006")]
    me.don_active = 10
    me.don_rested = 0
    do, _ = _do(overlay, "OP16-012", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-012"), sickness=True))
    _drain(st, [0])
    assert not any(c.card.name == "シャンクス" for c in me.characters), \
        "非赤髪リーダーで シャンクス が登場してはいけない"


def test_op16_012_summon_condition_eval():
    """登場条件: 《赤髪海賊団》リーダー + 場ドン10 で成立、 非該当で不成立。"""
    repo = _repo()
    overlay = _overlay()
    _, eff = _do(overlay, "OP16-012", "on_play")
    cond = eff["do"][0]["optional_cost_then"]["effect"][0]["conditional"]["if"]
    st_ok = _state(repo, "OP09-001", overlay)   # 赤髪海賊団 leader
    st_ok.players[0].don_active = 10
    st_ng = _state(repo, "OP01-001", overlay)   # 麦わらの一味 leader
    st_ng.players[0].don_active = 10
    assert eval_condition(cond, st_ok, st_ok.players[0]) is True, \
        "赤髪海賊団 + ドン10 で登場条件が成立していない"
    assert eval_condition(cond, st_ng, st_ng.players[0]) is False, \
        "非赤髪リーダーで登場条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP16-013 マクガイ (CHARACTER 赤 cost6 power8000):
#    【KO時】相手の元々のパワー8000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op16_013_on_ko_ko_opp_le_8000_ai():
    """【KO時】相手 元々8000以下1体をKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(MID), sickness=False)  # 6000 (≤8000)
    opp.characters = [victim]
    do, _ = _do(overlay, "OP16-013", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-013"), sickness=True))
    _drain(st, [0])
    assert victim not in opp.characters, "KO時に相手 元々8000以下キャラがKOされていない"


def test_op16_013_on_ko_human_pick():
    """人間 + 相手 元々8000以下 複数 → target_pick modal → 選んだ1体のみKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(MID), sickness=False)    # 6000
    b = InPlay.of(repo.get(SMALL), sickness=False)  # 2000
    opp.characters = [a, b]
    do, _ = _do(overlay, "OP16-013", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-013"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP16-014 マルコ (CHARACTER 赤 cost6 power8000):
#    自分のキャラが相手の効果で場を離れる場合、代わりにこのキャラをKOできる。(replace_leave = 未実装、 fidelity note)
#    【KO時】自分の手札からパワー8000のキャラカード1枚を捨てることができる：
#      このキャラカードをトラッシュから登場させる。
# --------------------------------------------------------------------------- #
def test_op16_014_on_ko_discard_then_play_self_from_trash_ai():
    """【KO時】手札8000捨てコスト → トラッシュの自身を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(F8000)]
    me.trash = [repo.get("OP16-014")]  # KO 済み自身がトラッシュにある想定
    st.current_source_card_id = "OP16-014"  # on_ko の自身参照 (play_self_from_trash が使う)
    chars_before = len(me.characters)
    src = InPlay.of(repo.get("OP16-014"), sickness=True)
    do, _ = _do(overlay, "OP16-014", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp, src)
    _drain(st, [0])
    assert any(c.card.card_id == "OP16-014" for c in me.characters), \
        "トラッシュの自身 (マルコ) が登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"
    assert repo.get("OP16-014") not in me.trash, "登場した自身がトラッシュに残ってはいけない"
    assert any(t.card_id == F8000 for t in me.trash), "捨てた手札8000がトラッシュに無い"


def test_op16_014_replace_leave_implemented():
    """team-wide leave-redirect (replace_leave) は実装済: 自分のキャラが相手の効果で場を離れる
    代わりに、 このマルコ (OP16-014) を KO できる (optional / by_opp_effect / ko_self)。
    旧 fidelity-note 版 (未実装宣言) から実装に更新済 (本セッションで replace_leave 実装、 近似でなく忠実)。"""
    overlay = _overlay()
    effects = overlay.get("OP16-014").effects
    rl = [e for e in effects if e.get("when") == "replace_leave"]
    assert rl, "OP16-014 の replace_leave 効果が overlay に無い"
    e = rl[0]
    assert e.get("optional") is True, "replace_leave は任意 (optional=True)"
    assert e.get("if", {}).get("by_opp_effect") is True, "相手効果で離れる場合が条件 (by_opp_effect)"
    assert any("ko_self" in prim for prim in e.get("do", [])), "代替 = 自身 (マルコ) を KO (ko_self)"


# --------------------------------------------------------------------------- #
#  OP16-017 リトルオーズJr. (CHARACTER 赤 cost4 power8000):
#    自分のコスト8以上の『白ひげ海賊団』を含む特徴を持つキャラがいない場合、
#      このキャラのパワー-4000。(静的)【ブロッカー】
# --------------------------------------------------------------------------- #
def test_op16_017_static_minus_4000_when_no_big_whitebeard():
    """自軍にコスト8以上の《白ひげ海賊団》キャラがいない → 静的にパワー-4000 (8000→4000)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    oz_def = repo.get("OP16-017")
    oz = InPlay.of(oz_def, sickness=False)
    me.characters = [oz]
    evaluate_static_effects(st, overlay)
    assert oz.power == oz_def.power - 4000, \
        f"コスト8以上白ひげ不在で パワー-4000 が乗っていない: {oz.power} (base {oz_def.power})"


def test_op16_017_static_no_penalty_with_big_whitebeard():
    """自軍にコスト8以上の《白ひげ海賊団》キャラがいる → 減少なし (8000 のまま)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    oz_def = repo.get("OP16-017")
    oz = InPlay.of(oz_def, sickness=False)
    big = InPlay.of(repo.get("OP16-003"), sickness=False)  # cost10 白ひげ海賊団
    me.characters = [oz, big]
    evaluate_static_effects(st, overlay)
    assert oz.power == oz_def.power, \
        f"コスト8以上白ひげ存在で パワー-4000 が乗ってはいけない: {oz.power} (base {oz_def.power})"


# --------------------------------------------------------------------------- #
#  OP16-019 おれ達の力を見せてやれ!!! (EVENT 赤 cost9):
#    【メイン】自分の手札からパワー8000の『白ひげ海賊団』を含む特徴を持つ
#      キャラカード2枚までを、登場させる。
#    【トリガー】自リーダーを、このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op16_019_main_play_two_whitebeard_8000_ai():
    """【メイン】手札のパワー8000《白ひげ海賊団》キャラ2枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP16-004"), repo.get("OP16-016")]  # 2 枚とも 8000 白ひげ海賊団
    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP16-019", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.characters) == chars_before + 2, \
        f"パワー8000白ひげキャラ2枚が登場していない: chars={len(me.characters)}"
    assert any(c.card.card_id == "OP16-004" for c in me.characters), "OP16-004 が登場していない"
    assert any(c.card.card_id == "OP16-016" for c in me.characters), "OP16-016 が登場していない"


def test_op16_019_trigger_pump_leader_ai():
    """【トリガー】自リーダーを このターン中 パワー+1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power
    do, _ = _do(overlay, "OP16-019", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 1000, \
        f"トリガーの +1000 が自リーダーに反映されていない: {me.leader.power} (before {power_before})"
