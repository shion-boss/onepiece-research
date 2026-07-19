# -*- coding: utf-8 -*-
"""EB01 弾 効果 回帰テスト バックフィル (自動生成 wave 002):
EB01-021 / EB01-023 / EB01-024 / EB01-026 / EB01-027 / EB01-028 /
EB01-029 / EB01-030 / EB01-031 / EB01-033 の 10 枚。

目的 (= test_backfill_auto_001.py と同一方針):
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
    trigger_end_of_turn,
)

ROOT = Path(__file__).resolve().parent.parent


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
    """指定 card_id の overlay から when 一致の最初の効果の do リストを返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave2_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB01-021", "EB01-023", "EB01-024", "EB01-026", "EB01-027",
           "EB01-028", "EB01-029", "EB01-030", "EB01-031", "EB01-033"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB01-021 ハンニャバル (LEADER): 【自分のターン終了時】コスト2以上《インペルダウン》
#    キャラ1枚を手札に戻せる → ドンデッキからドン1枚をアクティブで追加
# --------------------------------------------------------------------------- #
def test_eb01_021_hannyabaru_end_of_turn_ai():
    """AI: ターン終了時、 コスト2+《インペルダウン》キャラを手札に戻して ドン+1 (アクティブ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-021", overlay)  # 自リーダー = インペルダウン
    me, opp = st.players[0], st.players[1]
    # コスト2+ インペルダウン キャラ 2 体 (= 1 体を手札に戻すコスト後も条件維持)。
    # EB02-038 マゼラン (cost3) + EB01-022 イナズマ (cost6/インペルダウン)
    magellan = InPlay.of(repo.get("EB02-038"), sickness=False)
    inazuma = InPlay.of(repo.get("EB01-022"), sickness=False)
    me.characters = [magellan, inazuma]
    me.don_active = 0
    don_active_before = me.don_active
    deck_don_before = me.don_remaining_in_deck
    chars_before = len(me.characters)

    trigger_end_of_turn(st, overlay)

    assert len(me.characters) == chars_before - 1, \
        "インペルダウン キャラ1体がターン終了コストで手札に戻っていない"
    assert me.don_active == don_active_before + 1, \
        f"ドン+1 (アクティブ) が反映されていない: {me.don_active}"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキから1枚供給されていない"


def test_eb01_021_hannyabaru_end_of_turn_human_optional_modal():
    """人間: ターン終了時任意効果として end_of_turn_optional modal が立ち EB01-021 を含む。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-021", overlay, human_idx=0)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get("EB02-038"), sickness=False)]

    trigger_end_of_turn(st, overlay)

    assert st.pending_choice is not None, "人間 ターン終了任意効果の modal が立たない"
    assert st.pending_choice.get("kind") == "end_of_turn_optional", \
        f"kind が end_of_turn_optional でない: {st.pending_choice.get('kind')}"
    avail = st.pending_choice.get("available", [])
    assert any(a.get("card_id") == "EB01-021" for a in avail), \
        "任意効果候補に EB01-021 (ハンニャバル) が無い"


# --------------------------------------------------------------------------- #
#  EB01-023 エドワード・ウィーブル: 【登場時】カード1枚を引く
# --------------------------------------------------------------------------- #
def test_eb01_023_weevle_on_play_draw():
    """【登場時】 手札 +1 / デッキ -1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    do, _ = _do(overlay, "EB01-023", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-023"), sickness=True))

    assert len(me.hand) == hand_before + 1, "登場時ドローで手札が1枚増えていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  EB01-024 ハムレット: 自手札4枚以下 → 自《SMILE》キャラ全て +1000 (static)
# --------------------------------------------------------------------------- #
def test_eb01_024_hamlet_static_smile_pump():
    """自手札4枚以下で 自陣《SMILE》キャラ全て +1000。 手札5枚以上で解除。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-061", overlay)  # カイドウ 百獣海賊団
    me, opp = st.players[0], st.players[1]
    hamlet = InPlay.of(repo.get("EB01-024"), sickness=False)   # SMILE, power 4000
    fortrix = InPlay.of(repo.get("EB01-025"), sickness=False)  # SMILE, power 5000
    me.characters = [hamlet, fortrix]
    me.hand = [repo.get("OP01-013")] * 3  # 手札 3 枚 (= 4 以下、 条件成立)

    evaluate_static_effects(st, overlay)
    assert fortrix.power == 5000 + 1000, \
        f"SMILE キャラに +1000 (static) が乗っていない: {fortrix.power}"
    assert hamlet.power == 4000 + 1000, \
        f"ハムレット自身 (SMILE) にも +1000 が乗っていない: {hamlet.power}"

    # 手札 5 枚 → 条件外れ → 解除
    me.hand = [repo.get("OP01-013")] * 5
    evaluate_static_effects(st, overlay)
    assert fortrix.power == 5000, "手札5枚で static +1000 が解除されていない"


# --------------------------------------------------------------------------- #
#  EB01-026 プリンス・ベレット: 【ドン1】【アタック時】自手札1枚以下 →
#    コスト3以下のキャラ1枚までを持ち主の手札に戻す
# --------------------------------------------------------------------------- #
def test_eb01_026_bellett_attack_bounce_ai():
    """AI: アタック時、 相手のコスト3以下キャラ1枚を手札に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost2
    opp.characters = [victim]

    do, _ = _do(overlay, "EB01-026", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-026"), sickness=False))

    assert victim not in opp.characters, "相手キャラが手札に戻っていない"
    assert repo.get("OP01-016") in opp.hand, "戻したキャラが相手の手札にない"


def test_eb01_026_bellett_attack_bounce_human_pick():
    """人間 + 相手コスト3以下キャラ複数 → target_pick modal → resolve で1枚戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost? (麦わらルフィ系)
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB01-026", "on_attack")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB01-026"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert a not in opp.characters, "人間が選んだ相手キャラが手札に戻っていない"


# --------------------------------------------------------------------------- #
#  EB01-027 Mr.1(ダズ・ボーネス): 【登場時】カード2枚を引き、 手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_eb01_027_mr1_on_play_draw2_discard1():
    """【登場時】 draw2 + discard1 → 手札 純増 +1 / デッキ -2 / トラッシュ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てる札の担保
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    do, _ = _do(overlay, "EB01-027", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-027"), sickness=True))

    assert len(me.hand) == hand_before + 1, \
        f"draw2+discard1 で手札が純増+1になっていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減っていない"
    assert len(me.trash) == trash_before + 1, "トラッシュが1枚増えていない"


# --------------------------------------------------------------------------- #
#  EB01-028 ゴムゴムのチャンピオン回転弾 (EVENT):
#   【カウンター】リーダー《インペルダウン》→ 自リーダー/キャラ +2000(battle) +
#     相手のアクティブキャラ1枚を手札に戻す
#   【トリガー】コスト3以下のキャラ1枚をデッキ下に戻す
# --------------------------------------------------------------------------- #
def test_eb01_028_counter_pump_and_bounce_ai():
    """カウンター do: 自リーダー +2000(battle) + 相手アクティブキャラ1枚を手札に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-071", overlay)  # マゼラン (インペルダウン) leader
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # アクティブ (rested=False)
    opp.characters = [victim]

    power_before = me.leader.power
    do, eff = _do(overlay, "EB01-028", "counter")
    assert eff.get("if", {}).get("leader_feature") == "インペルダウン", \
        "overlay の条件 leader_feature=インペルダウン が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 2000, \
        f"自リーダー +2000(battle) が乗っていない: {me.leader.power}"
    assert victim not in opp.characters, "相手アクティブキャラが手札に戻っていない"
    assert repo.get("OP01-016") in opp.hand, "戻したキャラが相手手札にない"


def test_eb01_028_trigger_return_to_deck_bottom():
    """トリガー do: 相手のコスト3以下キャラ1枚をデッキの下に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-071", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost2
    opp.characters = [victim]
    opp_deck_before = len(opp.deck)

    do, _ = _do(overlay, "EB01-028", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "トリガーで相手キャラが場から離れていない"
    assert len(opp.deck) == opp_deck_before + 1, "相手デッキ下に1枚戻っていない"
    assert opp.deck[-1].card_id == "OP01-016", "戻したカードがデッキ最下にない"


# --------------------------------------------------------------------------- #
#  EB01-029 わりいおれ死んだ (EVENT):
#   【カウンター】デッキ上1枚公開 → コスト4以上なら自キャラ1枚を手札に戻す。
#     その後 公開カードをデッキ下へ
#   【トリガー】コスト8以下のキャラ1枚を手札に戻す
# --------------------------------------------------------------------------- #
def test_eb01_029_counter_reveal_bounce_ai():
    """カウンター do: デッキ上=コスト4以上 → 自キャラ1枚手札戻し + 公開カードをデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # デッキ最上段に コスト4以上のカード (= EB01-023 cost4) を置く
    top = repo.get("EB01-023")
    me.deck = [top] + [repo.get("OP01-013")] * 20
    friend = InPlay.of(repo.get("OP01-016"), sickness=False)  # 自キャラ
    me.characters = [friend]
    deck_len_before = len(me.deck)

    do, _ = _do(overlay, "EB01-029", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert friend not in me.characters, "コスト4以上公開時に自キャラが手札に戻っていない"
    assert repo.get("OP01-016") in me.hand, "戻した自キャラが手札にない"
    # 公開カードは「その後デッキの下に置く」→ デッキ枚数は不変、 最上→最下へ移動
    assert len(me.deck) == deck_len_before, "公開後のデッキ枚数が不変でない (下に戻すため)"
    assert me.deck[-1].card_id == "EB01-023", "公開カードがデッキ最下に置かれていない"
    assert me.deck[0].card_id != "EB01-023", "公開カードがまだデッキ最上にある"


def test_eb01_029_trigger_return_opp_to_hand():
    """トリガー do: 相手のコスト8以下キャラ1枚を手札に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "EB01-029", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "トリガーで相手キャラが手札に戻っていない"
    assert repo.get("OP01-016") in opp.hand, "戻したキャラが相手手札にない"


# --------------------------------------------------------------------------- #
#  EB01-030 ローグタウン (STAGE):
#   【起動メイン】このカード+手札1枚をデッキ下に置ける：カード2枚を引く
# --------------------------------------------------------------------------- #
def test_eb01_030_rogue_town_activate_main_ai():
    """起動メイン: ステージ+手札1をデッキ下へ → 2枚ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("EB01-030"), sickness=False)
    me.stages = [stage]
    me.hand = [repo.get("OP01-013")] * 2
    hand_before = len(me.hand)

    options = list_activate_main_effects(st, me, overlay)
    rogue_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "EB01-030"]
    assert len(rogue_opts) == 1, \
        f"EB01-030 の起動メインが legal に出ない: {len(rogue_opts)}"
    src, eff = rogue_opts[0]
    fire_activate_main(st, me, opp, src, eff)

    assert stage not in me.stages, "ステージ自身がデッキ下に置かれていない"
    # cost: 手札1枚をデッキ下 (-1)、 effect: draw2 (+2) → 純増 +1
    assert len(me.hand) == hand_before + 1, \
        f"手札1枚をデッキ下→2ドローで手札が純増+1になっていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  EB01-031 カリファ: 【登場時】ドン-1：リーダー《W7》→
#    自トラッシュのコスト4以下キャラカード2枚までを手札に加える
# --------------------------------------------------------------------------- #
def test_eb01_031_kalifa_on_play_trash_to_hand_ai():
    """登場時 do: 自トラッシュのコスト4以下キャラ2枚までを手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-058", overlay)  # アイスバーグ (W7) leader
    me, opp = st.players[0], st.players[1]
    # トラッシュに コスト4以下 CHARACTER を 3 枚 (= 2 枚まで回収)
    me.trash = [repo.get("OP01-016"),   # cost2 CHARACTER
                repo.get("EB01-024"),   # cost3 CHARACTER
                repo.get("EB01-025")]   # cost3 CHARACTER
    hand_before = len(me.hand)

    do, eff = _do(overlay, "EB01-031", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "W7", \
        "overlay の条件 leader_feature=W7 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-031"), sickness=True))

    assert len(me.hand) == hand_before + 2, \
        f"トラッシュから2枚回収されていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  EB01-033 ブルーノ: 【登場時】ドン-1：リーダー《W7》→
#    手札/トラッシュから「ブルーノ」以外のコスト5《W7》キャラ1枚までを登場
# --------------------------------------------------------------------------- #
def test_eb01_033_bruno_on_play_play_from_hand_ai():
    """登場時 do: 手札のコスト5《W7》キャラ (≠ブルーノ) 1枚を登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-058", overlay)  # アイスバーグ (W7)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB01-031")]  # カリファ (W7, cost5)
    chars_before = len(me.characters)

    do, _ = _do(overlay, "EB01-033", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-033"), sickness=True))

    assert len(me.characters) == chars_before + 1, "手札のW7コスト5キャラが登場していない"
    assert any(c.card.card_id == "EB01-031" for c in me.characters), \
        "登場したのがカリファ (EB01-031) でない"
    assert repo.get("EB01-031") not in me.hand, "登場元カードが手札に残っている"


def test_eb01_033_bruno_on_play_human_pick():
    """人間 + 手札/トラッシュ 複数候補 → play_from_hand_or_trash_pick modal → resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-058", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB01-031")]      # カリファ (W7 cost5)
    me.trash = [repo.get("OP03-059")]     # カク (W7 cost5)
    chars_before = len(me.characters)

    do, _ = _do(overlay, "EB01-033", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB01-033"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_or_trash_pick", \
        f"kind が play_from_hand_or_trash_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2枚でない: {len(cands)}"
    kaku_idx = next(i for i, c in enumerate(cands) if c["card_id"] == "OP03-059")
    resolve_pending_choice(st, [kaku_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert len(me.characters) == chars_before + 1, "人間が選んだキャラが登場していない"
    assert any(c.card.card_id == "OP03-059" for c in me.characters), \
        "登場したのが人間選択のカク (OP03-059) でない"
