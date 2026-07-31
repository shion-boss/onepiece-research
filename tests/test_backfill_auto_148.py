# -*- coding: utf-8 -*-
"""OP16 弾 (白ひげ海賊団 / インペルダウン / 緑) 効果 回帰テスト バックフィル (自動生成 wave 148):
OP16-020 / OP16-021 / OP16-025 / OP16-026 / OP16-027 /
OP16-029 / OP16-030 / OP16-031 / OP16-032 / OP16-033 の 10 枚。

目的 (= test_backfill_auto_001〜147.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 任意コスト / 対象選択 を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import GameState, InPlay, Phase, Player
from engine.effects import (
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 副作用のない) 素材カード。
# --------------------------------------------------------------------------- #
F8000 = "EB02-042"      # バニラ パワー8000 キャラ (reveal コスト素材)
GREEN2 = "EB01-017"     # ブルーノ 緑 cost2 power2000 (cost≤2 play_from_hand 素材)
RED1 = "OP01-016"       # ナミ 赤 cost1 power2000 (非緑 素材)
PRISONER = "OP16-042"   # インペルダウンの囚人 (named_set 登場 素材)
WB_LEADER = "OP16-001"  # ポートガス・Ｄ・エース (白ひげ海賊団 LEADER)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(RED1)] * 30
    p1.deck = [repo.get(RED1)] * 30
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
def test_all_op16_wave148_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP16-020", "OP16-021", "OP16-025", "OP16-026", "OP16-027",
           "OP16-029", "OP16-030", "OP16-031", "OP16-032", "OP16-033"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP16-020 おれと共に来る者は… (EVENT 赤):
#    【メイン】自分のドン!!1枚をレストにし、手札のパワー8000キャラ1枚を公開できる：1ドロー。
#    【カウンター】自分の手札1枚を捨てる：自リーダーかキャラ1枚まで、このバトル中 パワー+3000。
# --------------------------------------------------------------------------- #
def test_op16_020_main_rest_don_reveal_then_draw_ai():
    """【メイン】ドン1レスト + 手札8000公開 (任意コスト) → 1ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1
    me.don_rested = 0
    me.hand = [repo.get(F8000)]  # 公開素材 (捨てない)
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP16-020", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, \
        f"1ドローで手札が1枚増えていない (公開は捨てない): hand={len(me.hand)}"
    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"
    assert me.don_active == 0 and me.don_rested == 1, \
        f"コストのドン1レストが反映されていない: active={me.don_active} rested={me.don_rested}"


def test_op16_020_main_no_reveal_target_no_fire():
    """手札にパワー8000キャラが無い → 任意コスト払えず 不発 (ドローされない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1
    me.hand = [repo.get(RED1)]  # power 2000 (= 8000 でない)
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP16-020", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == hand_before and len(me.deck) == deck_before, \
        "公開できるキャラが無いのに ドロー が起きた (任意コスト不能なら不発のはず)"


def test_op16_020_main_human_pay_and_draw():
    """人間 → optional_cost_confirm で pay → 1ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1
    me.hand = [repo.get(F8000)]
    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP16-020", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"任意コスト確認 modal が立たない: {st.pending_choice}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, "人間が pay した後に 1ドローが起きていない"


def test_op16_020_counter_pump_leader_ai():
    """【カウンター】do の power_pump: 自リーダー(候補唯一)を このバトル中 +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power
    do, eff = _do(overlay, "OP16-020", "counter")
    assert eff.get("cost", {}).get("discard_hand") == 1, \
        "カウンターの discard_hand:1 コストが overlay に無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンターの自リーダー +3000 が反映されていない: {me.leader.power} (before {power_before})"


def test_op16_020_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → target_pick modal → 選んだキャラのみ +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(RED1), sickness=False)  # power 2000
    me.characters = [friend]
    do, _ = _do(overlay, "OP16-020", "counter")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    f_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    f_before = friend.power
    resolve_pending_choice(st, [f_idx])
    _drain(st, [f_idx])
    assert friend.power == f_before + 3000, "人間が選んだキャラに +3000 が入っていない"


# --------------------------------------------------------------------------- #
#  OP16-021 モビー・ディック号 (STAGE 赤 cost1):
#    【登場時】リーダーが《白ひげ海賊団》なら、デッキ上3を見て1枚を手札、残りをデッキ下。
#    【起動メイン】このステージをトラッシュ：自リーダーかキャラ1枚にレストのドン!!1枚まで付与。
# --------------------------------------------------------------------------- #
def test_op16_021_on_play_search_when_whitebeard_ai():
    """【登場時】白ひげ海賊団リーダー → デッキ上3見て1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(RED1)] * 5
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    do, eff = _do(overlay, "OP16-021", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "白ひげ海賊団", \
        "on_play の leader_feature 条件が overlay に無い"
    assert eval_condition(eff["if"], st, me, None) is True, \
        "白ひげ海賊団リーダーで条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-021"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, "デッキ上3から1枚が手札に加わっていない"
    assert len(me.deck) == deck_before - 1, "手札に加えた分 デッキが1枚減っていない"


def test_op16_021_on_play_condition_false_when_not_whitebeard():
    """非《白ひげ海賊団》リーダー → on_play の条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (麦わらの一味)
    me, _ = st.players[0], st.players[1]
    _, eff = _do(overlay, "OP16-021", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "非白ひげリーダーで leader_feature 条件が成立してはいけない"


def test_op16_021_on_play_search_human_modal():
    """人間 + 白ひげ → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(RED1)] * 5
    do, _ = _do(overlay, "OP16-021", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-021"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "search_top_n", \
        f"人間で search_top_n modal が立たない: {st.pending_choice}"


def test_op16_021_activate_main_trash_then_attach_don_ai():
    """【起動メイン】ステージをトラッシュ (コスト) → 自リーダーにレストドン1付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP16-021"), sickness=False)
    me.stages = [stage]
    me.don_rested = 1  # レストドン供給源
    don_before = me.leader.attached_dons
    trash_before = len(me.trash)
    options = list_activate_main_effects(st, me, overlay)
    stage_opts = [(src, e) for (src, e) in options
                  if src.card.card_id == "OP16-021"]
    assert len(stage_opts) == 1, \
        f"OP16-021 (ステージ) の起動メインが legal に出ない: {len(stage_opts)}"
    fire_activate_main(st, me, opp, *stage_opts[0])
    _drain(st, [0])
    assert stage not in me.stages, "コストでステージがトラッシュに置かれていない"
    assert len(me.trash) == trash_before + 1, "ステージがトラッシュへ移っていない"
    assert me.leader.attached_dons == don_before + 1, \
        "自リーダーにレストドン1枚が付与されていない"
    assert me.don_rested == 0, "付与コストでレストドンが1枚消費されるべき"


# --------------------------------------------------------------------------- #
#  OP16-025 ウサッコフ (CHARACTER 緑 cost2 power3000):
#    【アタック時】自分の「ツノッコフ」がいる場合、手札からコスト2以下のキャラ1枚までを登場。
# --------------------------------------------------------------------------- #
def test_op16_025_on_attack_play_from_hand_when_tsuno_ai():
    """【アタック時】「ツノッコフ」在場 → 手札のコスト2以下キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-025"), sickness=False)
    tsuno = InPlay.of(repo.get("OP16-029"), sickness=False)  # ツノッコフ
    me.characters = [attacker, tsuno]
    me.hand = [repo.get(GREEN2)]  # cost2 キャラ
    chars_before = len(me.characters)
    hand_before = len(me.hand)
    do, eff = _do(overlay, "OP16-025", "on_attack")
    assert eff.get("if", {}).get("self_chara_filtered_count_ge", {}).get(
        "filter", {}).get("name") == "ツノッコフ", \
        "アタック時条件 (ツノッコフ在場) が overlay に無い"
    assert eval_condition(eff["if"], st, me, attacker) is True, \
        "ツノッコフ在場で条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])
    assert len(me.characters) == chars_before + 1, "手札のコスト2以下キャラが登場していない"
    assert len(me.hand) == hand_before - 1, "登場で手札が1枚減っていない"


def test_op16_025_on_attack_condition_false_without_tsuno():
    """「ツノッコフ」不在 → アタック時条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _ = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-025"), sickness=False)
    me.characters = [attacker]  # ツノッコフ なし
    _, eff = _do(overlay, "OP16-025", "on_attack")
    assert eval_condition(eff["if"], st, me, attacker) is False, \
        "ツノッコフ不在で条件が成立してはいけない"


def test_op16_025_on_attack_human_play_pick():
    """人間 + 手札コスト2以下 複数 → play_from_hand_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-025"), sickness=False)
    me.characters = [attacker, InPlay.of(repo.get("OP16-029"), sickness=False)]
    me.hand = [repo.get(GREEN2), repo.get(RED1)]  # cost2 + cost1 = 2 候補
    do, _ = _do(overlay, "OP16-025", "on_attack")
    execute_effect(do[0], st, me, opp, attacker)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"人間で play_from_hand_pick modal が立たない: {st.pending_choice}"


# --------------------------------------------------------------------------- #
#  OP16-026 エンポリオ・イワンコフ (CHARACTER 緑 cost4 power4000):
#    【登場時】デッキ上3を見て《インペルダウン》1を手札、残りデッキ下。
#              その後、手札からコスト2以下のキャラ1枚までを登場。
# --------------------------------------------------------------------------- #
def test_op16_026_on_play_search_then_play_ai():
    """【登場時】デッキ上3から《インペルダウン》サーチ + 手札コスト2以下を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # デッキ上3枚に インペルダウン キャラを置く (= サーチ対象)
    me.deck = [repo.get("OP16-027")] + [repo.get(RED1)] * 4  # OP16-027=インペルダウン
    me.hand = [repo.get(GREEN2)]  # cost2 キャラ (= play_from_hand 対象)
    chars_before = len(me.characters)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP16-026", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-026"), sickness=True))
    _drain(st, [0])
    assert len(me.characters) == chars_before + 1, \
        "その後の 手札コスト2以下キャラ登場が起きていない"
    assert len(me.deck) < deck_before, "デッキサーチでデッキ枚数が減っていない"
    assert any(c.card.features and "インペルダウン" in c.card.features
               for c in me.characters) or \
        any(c.features and "インペルダウン" in c.features for c in me.hand), \
        "《インペルダウン》カードが手札 or 場に取り込まれていない"


# --------------------------------------------------------------------------- #
#  OP16-027 ジンベエ (CHARACTER 緑 cost2 power2000):
#    【ドン!!×1】このキャラのパワー+2000。
# --------------------------------------------------------------------------- #
def test_op16_027_don_static_pump_with_don():
    """【ドン!!×1】ドン1枚付与時、 静的に パワー+2000。
    実効 power = base 2000 + DON!!付与の +1000 (6-5-5、 自ターン) + 静的 +2000 = 5000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _ = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("OP16-027"), sickness=False)  # base 2000
    jinbe.attached_dons = 1
    me.characters = [jinbe]
    evaluate_static_effects(st, overlay)
    assert jinbe.power == 5000, \
        f"ドン1枚付与時の 実効パワー (2000+1000+静的2000) が合わない: {jinbe.power}"
    assert jinbe.static_buff == 2000, \
        f"静的 +2000 (static_buff) が反映されていない: {jinbe.static_buff}"


def test_op16_027_don_static_no_pump_without_don():
    """ドン0枚なら 静的 +2000 は乗らない (= 2000)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _ = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("OP16-027"), sickness=False)
    jinbe.attached_dons = 0
    me.characters = [jinbe]
    evaluate_static_effects(st, overlay)
    assert jinbe.power == 2000, \
        f"ドン0枚で 静的 +2000 が乗ってはいけない: {jinbe.power}"


# --------------------------------------------------------------------------- #
#  OP16-029 ツノッコフ (CHARACTER 緑 cost2 power3000):
#    【アタック時】自分の「ウサッコフ」がいる場合、手札からコスト2以下のキャラ1枚までを登場。
# --------------------------------------------------------------------------- #
def test_op16_029_on_attack_play_from_hand_when_usa_ai():
    """【アタック時】「ウサッコフ」在場 → 手札のコスト2以下キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-029"), sickness=False)
    usa = InPlay.of(repo.get("OP16-025"), sickness=False)  # ウサッコフ
    me.characters = [attacker, usa]
    me.hand = [repo.get(GREEN2)]
    chars_before = len(me.characters)
    hand_before = len(me.hand)
    do, eff = _do(overlay, "OP16-029", "on_attack")
    assert eval_condition(eff["if"], st, me, attacker) is True, \
        "ウサッコフ在場で条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])
    assert len(me.characters) == chars_before + 1, "手札のコスト2以下キャラが登場していない"
    assert len(me.hand) == hand_before - 1, "登場で手札が1枚減っていない"


def test_op16_029_on_attack_condition_false_without_usa():
    """「ウサッコフ」不在 → アタック時条件が成立しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _ = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP16-029"), sickness=False)
    me.characters = [attacker]
    _, eff = _do(overlay, "OP16-029", "on_attack")
    assert eval_condition(eff["if"], st, me, attacker) is False, \
        "ウサッコフ不在で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP16-030 トラファルガー・ロー (CHARACTER 緑 cost8 power9000):
#    【登場時】相手のレストのキャラ1枚まで、次の相手のリフレッシュでアクティブにならない。
#    【自分のターン終了時】自分のコスト5以下の緑のキャラすべてを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op16_030_on_play_keep_opp_rested_ai():
    """【登場時】相手レストキャラ1枚に stay_rested_next_refresh フラグ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(RED1), sickness=False)
    victim.rested = True
    opp.characters = [victim]
    do, _ = _do(overlay, "OP16-030", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-030"), sickness=True))
    _drain(st, [0])
    assert victim.stay_rested_next_refresh is True, \
        "相手レストキャラに stay_rested_next_refresh が付いていない"


def test_op16_030_on_play_keep_opp_rested_human_pick():
    """人間 + 相手レストキャラ 複数 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    v1 = InPlay.of(repo.get(RED1), sickness=False)
    v2 = InPlay.of(repo.get(GREEN2), sickness=False)
    v1.rested = True
    v2.rested = True
    opp.characters = [v1, v2]
    do, _ = _do(overlay, "OP16-030", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-030"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"


def test_op16_030_end_of_turn_untap_green_le5_ai():
    """【自分のターン終了時】自コスト5以下の緑キャラのみアクティブに戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    green = InPlay.of(repo.get("OP16-025"), sickness=False)  # 緑 cost2
    red = InPlay.of(repo.get(RED1), sickness=False)           # 赤 cost1 (対象外)
    green.rested = True
    red.rested = True
    me.characters = [green, red]
    do, _ = _do(overlay, "OP16-030", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-030"), sickness=False))
    _drain(st, [0])
    assert green.rested is False, "コスト5以下の緑キャラがアクティブに戻っていない"
    assert red.rested is True, "非緑キャラはアクティブにならないはず"


# --------------------------------------------------------------------------- #
#  OP16-031 バギー (CHARACTER 緑 cost4 power5000):
#    【KO時】自分の手札から「インペルダウンの囚人」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op16_031_on_ko_play_prisoner_ai():
    """【KO時】手札の「インペルダウンの囚人」を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(PRISONER)]  # インペルダウンの囚人
    chars_before = len(me.characters)
    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP16-031", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-031"), sickness=False))
    _drain(st, [0])
    assert any(c.card.name == "インペルダウンの囚人" for c in me.characters), \
        "手札の「インペルダウンの囚人」が登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"
    assert len(me.hand) == hand_before - 1, "登場で手札が1枚減っていない"


def test_op16_031_on_ko_no_prisoner_no_play():
    """手札に「インペルダウンの囚人」が無い → 登場は起きない (crash しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(RED1)]  # 該当なし
    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP16-031", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-031"), sickness=False))
    _drain(st, [0])
    assert len(me.characters) == chars_before, \
        "該当カードが無いのにキャラが増えた"


# --------------------------------------------------------------------------- #
#  OP16-032 ボア・ハンコック (CHARACTER 緑 cost7 power9000):
#    【登場時】相手の「モンキー・Ｄ・ルフィ」以外のキャラ1枚まで、
#              次の相手のエンドフェイズ終了時までレストにできない。
# --------------------------------------------------------------------------- #
def test_op16_032_on_play_set_cannot_rest_ai():
    """【登場時】相手キャラ1枚に レスト不能 buff (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(RED1), sickness=False)  # 非「モンキー・Ｄ・ルフィ」
    opp.characters = [victim]
    do, _ = _do(overlay, "OP16-032", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP16-032"), sickness=True))
    _drain(st, [0])
    assert victim.cannot_be_rested_buff is True, \
        "相手キャラに レスト不能 buff が付いていない"


def test_op16_032_on_play_set_cannot_rest_human_pick():
    """人間 + 相手キャラ 複数 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.characters = [
        InPlay.of(repo.get(RED1), sickness=False),
        InPlay.of(repo.get(GREEN2), sickness=False),
    ]
    do, _ = _do(overlay, "OP16-032", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP16-032"), sickness=True))
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"人間で target_pick modal が立たない: {st.pending_choice}"


# --------------------------------------------------------------------------- #
#  OP16-033 モーリー (CHARACTER 緑 cost4 power5000):
#    このキャラがKOされる場合、代わりに自分のカード2枚をレストにできる。【ブロック不可】
# --------------------------------------------------------------------------- #
def test_op16_033_replace_ko_rest_two_ai():
    """replace_ko: KOされる代わりに 自カード2枚をレストにして 場に残る (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    morley = InPlay.of(repo.get("OP16-033"), sickness=False)
    friend = InPlay.of(repo.get(RED1), sickness=False)
    me.characters = [morley, friend]
    # 供給: leader + morley + friend = 3 アクティブ → 2 枚 rest 可能
    rested_before = sum(1 for ip in [me.leader, *me.characters] if ip.rested)
    replaced = try_replace_ko(
        st, me, opp, morley, overlay, by_opp_effect=True, leave_kind="ko",
    )
    _drain(st, [1])
    assert replaced is True, "自カード2枚をレストできるのに KO が置換されていない"
    assert morley in me.characters, "置換成立時 モーリーは場に残るべき"
    rested_after = sum(1 for ip in [me.leader, *me.characters] if ip.rested)
    assert rested_after == rested_before + 2, \
        f"置換コストで自カードが2枚レストされるべき: {rested_before}→{rested_after}"


def test_op16_033_replace_ko_human_confirm():
    """人間 actor: replace_ko は 任意 → replace_ko_optional modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    morley = InPlay.of(repo.get("OP16-033"), sickness=False)
    me.characters = [morley, InPlay.of(repo.get(RED1), sickness=False)]
    replaced = try_replace_ko(
        st, me, opp, morley, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice}"
