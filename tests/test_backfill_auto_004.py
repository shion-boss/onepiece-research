# -*- coding: utf-8 -*-
"""EB01 弾 効果 回帰テスト バックフィル (自動生成 wave 004):
EB01-047 / EB01-048 / EB01-049 / EB01-050 / EB01-051 / EB01-052 /
EB01-053 / EB01-054 / EB01-056 / EB01-057 の 10 枚。

目的 (= test_backfill_auto_001/002/003.py と同一方針):
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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
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
    # デッキは効果の薄いバニラ気味カードで埋める (= draw/mill の混入を避ける)
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


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の (do, effect) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave4_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB01-047", "EB01-048", "EB01-049", "EB01-050", "EB01-051",
           "EB01-052", "EB01-053", "EB01-054", "EB01-056", "EB01-057"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB01-047 ラブーン: 【ターン1回】キャラがKOされた時、 カード1枚を引き、
#                     自分の手札1枚を捨てる。 (on_opp_chara_ko / on_self_chara_ko)
# --------------------------------------------------------------------------- #
def test_eb01_047_laboon_ko_draw_discard_ai():
    """AI: 相手キャラKO時 do → 1 ドロー + 手札 1 枚をランダムに捨てる。
    draw で デッキ -1 / trash +1、 手札枚数は draw(+1)+discard(-1) で net 変化なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てる原資 (手札 1 枚)
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    hand_before = len(me.hand)

    do, eff = _do(overlay, "EB01-047", "on_opp_chara_ko")
    assert eff.get("cost", {}).get("once_per_turn") is True, "【ターン1回】制約が overlay に無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-047"), sickness=False))

    assert len(me.deck) == deck_before - 1, f"ドローでデッキが1枚減っていない: {len(me.deck)}"
    assert len(me.trash) == trash_before + 1, "捨てたカードがトラッシュに置かれていない"
    assert len(me.hand) == hand_before, \
        f"draw(+1)+discard(-1) で手札枚数は不変のはず: {len(me.hand)} (before {hand_before})"


def test_eb01_047_laboon_self_ko_variant_fires():
    """自キャラKO時 (on_self_chara_ko) の do も 同一 (draw1+discard1) で発火する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    deck_before = len(me.deck)

    do, eff = _do(overlay, "EB01-047", "on_self_chara_ko")
    assert eff.get("cost", {}).get("once_per_turn") is True, "【ターン1回】制約が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-047"), sickness=False))

    assert len(me.deck) == deck_before - 1, "自キャラKO 版でも ドローが起きるべき"


# --------------------------------------------------------------------------- #
#  EB01-048 ラブーン: 【起動メイン】このキャラをレストにできる：
#                     相手のキャラ1枚までを、 このターン中、 コスト-4。
# --------------------------------------------------------------------------- #
def test_eb01_048_laboon_activate_main_cost_minus_ai():
    """起動メイン: 自レスト → 相手キャラ1枚を このターン中 コスト-4 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    laboon = InPlay.of(repo.get("EB01-048"), sickness=False)
    me.characters = [laboon]
    victim = InPlay.of(repo.get("OP11-015"), sickness=False)  # cost4
    opp.characters = [victim]
    cost_before = victim.base_cost

    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB01-048"]
    assert len(mine) == 1, f"EB01-048 の起動メインが legal に出ない: {len(mine)}"
    fire_activate_main(st, me, opp, *mine[0])

    assert laboon.rested is True, "起動メインコストで ラブーン がレストされるべき"
    assert victim.base_cost == max(0, cost_before - 4), \
        f"相手キャラの コスト-4 が反映されていない: {cost_before} -> {victim.base_cost}"


def test_eb01_048_laboon_activate_main_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → cost_minus target_pick modal → resolve で対象に コスト-4。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    laboon = InPlay.of(repo.get("EB01-048"), sickness=False)
    me.characters = [laboon]
    a = InPlay.of(repo.get("OP11-015"), sickness=False)  # cost4
    b = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    opp.characters = [a, b]
    a_cost_before = a.base_cost

    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB01-048"]
    assert len(mine) == 1
    fire_activate_main(st, me, opp, *mine[0])

    assert st.pending_choice is not None, "人間 + 複数候補で cost_minus modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "cost_minus", \
        "primitive_kind が cost_minus でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert a.base_cost == max(0, a_cost_before - 4), \
        f"人間 resolve で 公式どおり コスト-4 が適用されていない: {a_cost_before} -> {a.base_cost}"
    assert b.base_cost == repo.get("ST01-004").cost, "選ばなかったキャラにコスト減が乗っている"


# --------------------------------------------------------------------------- #
#  EB01-049 Tボーン: 【登場時】相手のコスト2以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_eb01_049_tbone_on_play_ko_cost2_ai():
    """AI: 登場時 do → 相手コスト2以下キャラ1枚を KO (コスト3以上は対象外)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-004"), sickness=False)   # cost2 (対象)
    bystander = InPlay.of(repo.get("OP11-015"), sickness=False)  # cost4 (対象外)
    opp.characters = [victim, bystander]

    do, _ = _do(overlay, "EB01-049", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-049"), sickness=True))

    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"
    assert repo.get("ST01-004") in opp.trash, "KO したキャラが相手トラッシュにない"
    assert bystander in opp.characters, "コスト3以上のキャラまで KO されている (対象外のはず)"


def test_eb01_049_tbone_on_play_ko_human_pick():
    """人間 + 相手コスト2以下キャラ複数 → target_pick modal → resolve で1枚 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB01-049", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB01-049"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "ko", "primitive_kind が ko でない"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  EB01-050 生ぎたいっ!!!! (EVENT): 【カウンター】自分のトラッシュが30枚以上ある場合、
#           自分のデッキの上から1枚までを、 ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_eb01_050_ikitai_counter_put_top_to_life_ai():
    """AI: カウンター do → デッキ上1枚をライフの上へ (deck -1 / life +1)。
    overlay の 発動条件 (自トラッシュ30枚以上) は if 節に載っている。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("ST01-004")] * 30  # 条件 (30枚以上) を満たす
    deck_before = len(me.deck)
    life_before = len(me.life)

    do, eff = _do(overlay, "EB01-050", "counter")
    assert eff.get("if", {}).get("self_trash_count_ge") == 30, \
        "overlay の 発動条件 self_trash_count_ge=30 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.deck) == deck_before - 1, f"デッキ上1枚がライフへ移っていない: {len(me.deck)}"
    assert len(me.life) == life_before + 1, f"ライフが1枚増えていない: {len(me.life)}"


# --------------------------------------------------------------------------- #
#  EB01-051 指銃 (EVENT): 【メイン】自分のデッキの上から2枚をトラッシュに置くことが
#           できる：相手のコスト5以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_eb01_051_shigan_main_mill_then_ko_ai():
    """AI: メイン do → 任意コスト (デッキ上2枚トラッシュ) を払い、 相手コスト5以下キャラ KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    victim = InPlay.of(repo.get("OP11-015"), sickness=False)  # cost4 (≤5)
    opp.characters = [victim]

    do, _ = _do(overlay, "EB01-051", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.deck) == deck_before - 2, f"コストのデッキ上2枚トラッシュが起きていない: {len(me.deck)}"
    assert len(me.trash) == trash_before + 2, "トラッシュが2枚増えていない (mill コスト)"
    assert victim not in opp.characters, "相手コスト5以下キャラが KO されていない"


def test_eb01_051_shigan_main_human_optional_cost():
    """人間: メイン do → optional_cost_confirm modal → pay ([1]) で mill + KO が解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    victim = InPlay.of(repo.get("OP11-015"), sickness=False)  # cost4
    opp.characters = [victim]

    do, _ = _do(overlay, "EB01-051", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert len(me.deck) == deck_before - 2, "任意コスト承認後に デッキ上2枚トラッシュが起きていない"
    assert victim not in opp.characters, "任意コスト承認後に 相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  EB01-052 ヴィオラ: 【ブロッカー】【登場時】以下から1つを選ぶ。
#           ・相手のライフすべてを見て、 好きな順番で置く。
#           ・自分のライフすべてを裏向きにする。 (choice_effect)
# --------------------------------------------------------------------------- #
def test_eb01_052_viola_on_play_choice_ai_no_crash():
    """AI: 登場時 choice_effect do → 1 つ目 valid option を自動発動し crash しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 3
    opp.life = [repo.get("ST01-004")] * 3

    do, _ = _do(overlay, "EB01-052", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-052"), sickness=True))
    assert st.pending_choice is None, "AI 文脈で modal が残ってはいけない"


def test_eb01_052_viola_on_play_choice_human_pick():
    """人間: 登場時 → option_pick modal が 2 択で立ち、 option 0 を選んで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 3
    opp.life = [repo.get("ST01-004")] * 3

    do, _ = _do(overlay, "EB01-052", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB01-052"), sickness=True))

    assert st.pending_choice is not None, "人間 choice で modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    assert len(st.pending_choice.get("options", [])) == 2, \
        f"2 択の option が立っていない: {st.pending_choice.get('options')}"
    resolve_pending_choice(st, [0])  # 1 つ目 (相手ライフ並び替え) を選ぶ
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert st.pending_choice is None, "解決後も modal が残る"


# --------------------------------------------------------------------------- #
#  EB01-053 ガスティーノ: 【登場時】相手のコスト3以下のキャラ1枚までを、
#           相手のライフの上か下に表向きで置く。
#           【トリガー】相手のリーダーかキャラ合計2枚までを、 このターン中、 パワー-3000。
# --------------------------------------------------------------------------- #
def test_eb01_053_gastino_on_play_chara_to_opp_life_ai():
    """AI: 登場時 do → 相手コスト3以下キャラ1枚を 相手ライフへ (場から除去 + 相手ライフ +1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2 (≤3)
    opp.characters = [victim]
    opp_life_before = len(opp.life)

    do, _ = _do(overlay, "EB01-053", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-053"), sickness=True))

    assert victim not in opp.characters, "相手コスト3以下キャラが場から除去されていない"
    assert len(opp.life) == opp_life_before + 1, "相手ライフが1枚増えていない"
    assert opp.life[0].card_id == "ST01-004", "除去したキャラが相手ライフの上に置かれていない"


def test_eb01_053_gastino_on_play_human_pick():
    """人間 + 相手コスト3以下キャラ複数 → chara_to_opp_life target_pick modal → resolve。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB01-053", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB01-053"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "chara_to_opp_life", \
        "primitive_kind が chara_to_opp_life でない"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b not in opp.characters, "人間が選んだ相手キャラが 相手ライフへ移っていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


def test_eb01_053_gastino_trigger_power_debuff_ai():
    """【トリガー】do → 相手のリーダー(=候補のみの状況)を このターン中 パワー-3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = []  # 候補を相手リーダーのみに絞る (= 決定的に -3000)
    leader_before = opp.leader.power

    do, _ = _do(overlay, "EB01-053", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert opp.leader.power == leader_before - 3000, \
        f"相手リーダーの パワー-3000 が反映されていない: {opp.leader.power} (before {leader_before})"


# --------------------------------------------------------------------------- #
#  EB01-054 ガン・フォール: 【ブロッカー】【登場時】相手のライフが1枚以下の場合、
#           相手のコスト3以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_eb01_054_ganfall_on_play_ko_ai():
    """AI: 登場時 do → 相手コスト3以下キャラ1枚を KO。
    overlay の 発動条件 (相手ライフ1枚以下) は if 節に載っている。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("ST01-004")]  # ライフ1枚 (条件成立)
    victim = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2 (≤3)
    opp.characters = [victim]

    do, eff = _do(overlay, "EB01-054", "on_play")
    assert eff.get("if", {}).get("opp_life_le") == 1, \
        "overlay の 発動条件 opp_life_le=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-054"), sickness=True))

    assert victim not in opp.characters, "相手コスト3以下キャラが KO されていない"
    assert repo.get("ST01-004") in opp.trash, "KO したキャラが相手トラッシュにない"


def test_eb01_054_ganfall_on_play_ko_human_pick():
    """人間 + 相手コスト3以下キャラ複数 → target_pick modal → resolve で1枚 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("ST01-004")]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB01-054", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB01-054"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "ko", "primitive_kind が ko でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert a not in opp.characters, "人間が選んだ相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  EB01-056 シャーロット・フランぺ: 【登場時】自分のライフの上か下から1枚を
#           手札に加えることができる：カード1枚を引く。 (optional_cost_then)
# --------------------------------------------------------------------------- #
def test_eb01_056_frampe_on_play_life_to_hand_then_draw_ai():
    """AI: 登場時 do → 任意コスト (ライフ1枚を手札) を払い、 1 ドロー。
    手札 +2 (ライフ→手札 +1、 ドロー +1) / ライフ -1 / デッキ -1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    me.hand = []
    hand_before = len(me.hand)
    life_before = len(me.life)
    deck_before = len(me.deck)

    do, _ = _do(overlay, "EB01-056", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-056"), sickness=True))

    assert len(me.hand) == hand_before + 2, \
        f"手札が +2 (ライフ→手札 +ドロー) になっていない: {len(me.hand)}"
    assert len(me.life) == life_before - 1, f"ライフが1枚減っていない: {len(me.life)}"
    assert len(me.deck) == deck_before - 1, f"ドローでデッキが1枚減っていない: {len(me.deck)}"


def test_eb01_056_frampe_on_play_human_optional_cost():
    """人間: 登場時 → optional_cost_confirm modal → pay ([1]) で ライフ→手札 + ドロー解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    me.hand = []
    deck_before = len(me.deck)

    do, _ = _do(overlay, "EB01-056", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-056"), sickness=True))
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert len(me.hand) == 2, f"承認後に 手札 +2 になっていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 1, "承認後に ドローが起きていない"


# --------------------------------------------------------------------------- #
#  EB01-057 しらほし: このキャラが相手の効果でKOされた時、
#           自分のデッキの上から1枚までを、 ライフの上に加える。 (on_ko / opp_turn)
# --------------------------------------------------------------------------- #
def test_eb01_057_shirahoshi_on_ko_put_top_to_life_ai():
    """AI: 相手効果KO時 do → デッキ上1枚を自ライフの上へ (deck -1 / life +1)。
    overlay の 発動条件 (相手ターン = 相手効果KO) は if 節に載っている。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    deck_before = len(me.deck)
    life_before = len(me.life)

    do, eff = _do(overlay, "EB01-057", "on_ko")
    assert eff.get("if", {}).get("opp_turn") is True, \
        "overlay の 発動条件 opp_turn=True が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-057"), sickness=False))

    assert len(me.deck) == deck_before - 1, f"デッキ上1枚がライフへ移っていない: {len(me.deck)}"
    assert len(me.life) == life_before + 1, f"自ライフが1枚増えていない: {len(me.life)}"
