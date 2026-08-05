# -*- coding: utf-8 -*-
"""OP02 弾 効果 回帰テスト バックフィル (自動生成 wave 030):
OP02-047 / OP02-048 / OP02-049 / OP02-050 / OP02-051 / OP02-052 /
OP02-056 / OP02-057 / OP02-058 / OP02-059 の 10 枚
(= 緑 ワノ国 の レスト/KO イベント・ステージ + 青 インペルダウン/王下七武海 の
   ドロー・展開・サーチ・バウンス系)。

目的 (= test_backfill_auto_001〜029.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / サーチ / 任意コスト を 持つカードは 人間 actor で pending_choice が
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
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


# BLUE = 青 王下七武海 リーダー (OP01-060 ドフラミンゴ)。 end_of_turn / on_play を
# 汚染しない (= overlay の when は on_attack のみ) ので backfill 汎用 leader に安全。
BLUE_LEADER = "OP01-060"


def _state(repo, overlay, human_idx=None, leader_id=BLUE_LEADER,
           opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める。"""
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
    """指定 card_id の overlay から when 一致の効果 (do 配列, eff dict) を返す。"""
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


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op02_wave30_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP02-047", "OP02-048", "OP02-049", "OP02-050", "OP02-051",
           "OP02-052", "OP02-056", "OP02-057", "OP02-058", "OP02-059"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP02-047 桃源十拳 (EVENT): 【メイン】相手のコスト4以下のキャラ1枚までをレスト。
#    【トリガー】相手のレストのコスト3以下のキャラ1枚までを KO。
# --------------------------------------------------------------------------- #
def test_op02_047_main_rest_cost_le4_ai():
    """【メイン】相手のコスト4以下キャラをレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2 (<=4)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-047", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    assert victim.rested is True, "コスト4以下キャラがレストになっていない"


def test_op02_047_main_rest_human_pick():
    """人間 + 相手コスト4以下キャラ 複数 → rest の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP02-047", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b.rested is True, "人間が選んだキャラがレストになっていない"
    assert a.rested is False, "選ばなかったキャラはレストされない"


def test_op02_047_trigger_ko_rested_cost_le3_ai():
    """【トリガー】相手のレストのコスト3以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    victim.rested = True
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-047", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    assert victim not in opp.characters, "相手のレストのコスト3以下キャラが KO されていない"


def test_op02_047_trigger_ko_no_active_target():
    """相手のコスト3以下キャラが アクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-047", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


# --------------------------------------------------------------------------- #
#  OP02-048 ワノ国 (STAGE): 【起動メイン】手札から《ワノ国》1枚を捨て、このステージを
#    レストにできる：自分のドン!!1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op02_048_wanokuni_activate_main_untap_don_ai():
    """起動メイン: 手札の《ワノ国》1枚捨て + ステージレスト (コスト) → ドン1アクティブ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP02-048"), sickness=False)
    me.stages = [stage]
    me.hand = [repo.get("OP02-031")]  # 光月トキ (ワノ国) = 捨てるコスト
    me.don_active = 0
    me.don_rested = 2

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-048"]
    assert len(opts) == 1, f"OP02-048 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain_choices(st, pick=[1])  # optional_cost_confirm 等が残れば承諾

    assert me.don_active == 1, f"ドンが1枚アクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, f"レストドンが1枚消費されていない: {me.don_rested}"
    assert stage.rested is True, "コストでステージがレストされるべき"
    assert len(me.hand) == 0, "コストで《ワノ国》カードが1枚捨てられるべき"


def test_op02_048_wanokuni_activate_main_human_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP02-048"), sickness=False)
    me.stages = [stage]
    me.hand = [repo.get("OP02-031")]  # ワノ国 1 枚
    me.don_active = 0
    me.don_rested = 2

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-048"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 支払って発動)
    _drain_choices(st, pick=[0])
    assert me.don_active == 1, "承諾後 ドンが1枚アクティブになっていない"
    assert stage.rested is True, "承諾後 ステージがレストされていない"


# --------------------------------------------------------------------------- #
#  OP02-049 エンポリオ・イワンコフ (LEADER): 【自分のターン終了時】自分の手札が
#    0枚の場合、カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op02_049_ivankov_leader_end_of_turn_draw_when_empty():
    """自分のターン終了時: 手札0枚 → カード2枚を引く (条件成立、 AI/自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, leader_id="OP02-049")
    me = st.players[0]
    me.hand = []  # 手札 0 枚 = 条件成立
    me.deck = [repo.get("ST01-004")] * 10

    trigger_end_of_turn(st, overlay)
    _drain_choices(st)

    assert len(me.hand) == 2, f"手札0枚のターン終了時に2枚引けていない: {len(me.hand)}"


def test_op02_049_ivankov_leader_end_of_turn_no_draw_when_hand():
    """自分のターン終了時: 手札が0枚でない場合は 引かない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, leader_id="OP02-049")
    me = st.players[0]
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]  # 2 枚 = 条件不成立
    me.deck = [repo.get("ST01-004")] * 10

    trigger_end_of_turn(st, overlay)
    _drain_choices(st)

    assert len(me.hand) == 2, \
        f"手札が0枚でないのにドローが起きている: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP02-050 イナズマ (CHARACTER): 自分の手札が1枚以下の場合、このキャラはパワー+2000。
# --------------------------------------------------------------------------- #
def test_op02_050_inazuma_static_pump_when_hand_le1():
    """静的効果: 手札1枚以下 → パワー+2000 (evaluate_static_effects で検証)。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-060"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    inazuma_def = repo.get("OP02-050")  # power 5000
    inazuma = InPlay.of(inazuma_def, sickness=False)
    p0.characters = [inazuma]
    p0.hand = [repo.get("ST01-004")]  # 1 枚 (<=1) = 条件成立
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    evaluate_static_effects(st, overlay)
    assert inazuma.power == inazuma_def.power + 2000, \
        f"手札1枚以下で +2000 が反映されていない: {inazuma.power} (base {inazuma_def.power})"


def test_op02_050_inazuma_static_no_pump_when_hand_ge2():
    """静的効果: 手札2枚以上 → 効果は乗らない (base のまま)。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-060"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    inazuma_def = repo.get("OP02-050")
    inazuma = InPlay.of(inazuma_def, sickness=False)
    p0.characters = [inazuma]
    p0.hand = [repo.get("ST01-004")] * 3  # 3 枚 = 条件不成立
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0
    st.human_player_idx = None

    evaluate_static_effects(st, overlay)
    assert inazuma.power == inazuma_def.power, \
        f"手札2枚以上で効果 pump が乗ってはいけない: {inazuma.power} (base {inazuma_def.power})"


# --------------------------------------------------------------------------- #
#  OP02-051 エンポリオ・イワンコフ (CHARACTER): 【登場時】手札が3枚になるよう引き、
#    手札からコスト6以下の青の《インペルダウン》キャラ1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op02_051_ivankov_on_play_draw_and_summon_ai():
    """登場時: 手札3枚までドロー → 手札から 青《インペルダウン》cost6以下キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-050")]  # イナズマ 青 インペルダウン cost4
    me.deck = [repo.get("ST01-004")] * 10

    do, _ = _do(overlay, "OP02-051", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-051"), sickness=True))
    _drain_choices(st)

    # draw_to_hand_size 3 で ST01-004 が 2 枚引かれ、 その後 イナズマが登場
    assert any(c.card.card_id == "OP02-050" for c in me.characters), \
        "手札から 青《インペルダウン》キャラ (イナズマ) が登場していない"


def test_op02_051_ivankov_on_play_human_play_pick():
    """人間 + 手札に該当キャラ 複数 → 登場先を選ぶ play_from_hand_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 2 種の 青《インペルダウン》cost6以下 キャラ (どちらも on_play 無し)
    me.hand = [repo.get("OP02-050"), repo.get("OP02-059")]  # イナズマ / ハンコック
    me.deck = [repo.get("ST01-004")] * 10

    do, _ = _do(overlay, "OP02-051", "on_play", "play_from_hand")
    play_prim = next(p for p in do if "play_from_hand" in p)
    execute_effect(play_prim, st, me, opp,
                   InPlay.of(repo.get("OP02-051"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[0])
    assert any(c.card.card_id in ("OP02-050", "OP02-059") for c in me.characters), \
        "人間が選んだ 青《インペルダウン》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP02-052 カバジ (CHARACTER): 【登場時】自分の「モージ」がいる場合、カード2枚を引き、
#    自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op02_052_cabaji_on_play_draw_discard_with_moji_ai():
    """登場時: 自「モージ」がいる → 2枚引き1枚捨てる (条件成立、 trigger_on_play で検証)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    moji = InPlay.of(repo.get("OP02-060"), sickness=False)  # モージ
    cabaji = InPlay.of(repo.get("OP02-052"), sickness=True)
    me.characters = [moji, cabaji]
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]  # 2 枚
    me.deck = [repo.get("ST01-004")] * 10

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, cabaji, overlay)
    _drain_choices(st)

    # +2 ドロー -1 捨て = net +1
    assert len(me.hand) == hand_before + 1, \
        f"モージがいる場合の 2ドロー1捨て が反映されていない: {len(me.hand)} (before {hand_before})"


def test_op02_052_cabaji_on_play_no_moji_no_effect():
    """登場時: 「モージ」がいない場合は 効果不発 (手札変化なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    cabaji = InPlay.of(repo.get("OP02-052"), sickness=True)
    me.characters = [cabaji]  # モージ 不在
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]
    me.deck = [repo.get("ST01-004")] * 10

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, cabaji, overlay)
    _drain_choices(st)

    assert len(me.hand) == hand_before, \
        f"モージ不在なのに 2ドロー1捨て が起きている: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP02-056 ドンキホーテ・ドフラミンゴ (CHARACTER): 【登場時】デッキ上3枚を見て
#    好きな順に並び替えデッキの上か下に置く。 【ドン!!×1】【アタック時】手札1枚を捨てる
#    ことができる：相手のコスト1以下のキャラ1枚までを持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op02_056_doflamingo_on_play_look_reorder_ai():
    """登場時: デッキ上3枚を並び替え (choice ヒューリスティック = コスト昇順に上へ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    # 上3枚を コスト バラバラ に仕込む (4, 1, 3)
    me.deck = [repo.get("OP02-050"), repo.get("OP01-016"), repo.get("OP12-035")] \
        + [repo.get("ST01-004")] * 20

    do, _ = _do(overlay, "OP02-056", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-056"), sickness=True))
    _drain_choices(st)

    top3 = me.deck[:3]
    assert top3[0].cost <= top3[1].cost <= top3[2].cost, \
        f"デッキ上3枚がコスト昇順に並び替えられていない: {[c.cost for c in top3]}"


def test_op02_056_doflamingo_on_attack_bounce_cost_le1_ai():
    """アタック時 (ドン1ゲート): 手札1捨て → 相手コスト1以下キャラをデッキ下へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP02-056"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]
    me.hand = [repo.get("ST01-004")]  # 捨てるコスト
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=1)
    opp.characters = [victim]

    do, eff = _do(overlay, "OP02-056", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    deck_before = len(opp.deck)
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)
    _drain_choices(st)

    assert victim not in opp.characters, "相手コスト1以下キャラがデッキ下へ戻っていない"
    assert len(opp.deck) == deck_before + 1, "相手のデッキ下にカードが戻っていない"
    assert len(me.hand) == 0, "コストで手札1枚が捨てられるべき"


def test_op02_056_doflamingo_on_attack_human_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP02-056"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]
    me.hand = [repo.get("ST01-004")]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-056", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, attacker)

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain_choices(st, pick=[0])
    assert victim not in opp.characters, "承諾後 相手コスト1以下キャラがデッキ下へ戻っていない"


# --------------------------------------------------------------------------- #
#  OP02-057 バーソロミュー・くま (CHARACTER): 【登場時】デッキ上2枚を見て、《王下七武海》
#    1枚までを公開し手札に加える。残りを好きな順番でデッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_op02_057_kuma_on_play_search_shichibukai_ai():
    """登場時: デッキ上2枚から《王下七武海》を手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # OP02-056 ドフラミンゴ = 王下七武海
    me.deck = [repo.get("OP02-056")] + [repo.get("ST01-004")] * 29

    do, _ = _do(overlay, "OP02-057", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-057"), sickness=True))
    _drain_choices(st)

    assert any(c.card_id == "OP02-056" for c in me.hand), \
        "デッキ上2枚から《王下七武海》カードが手札に加わっていない"


def test_op02_057_kuma_search_human_pick():
    """人間 + デッキ上2枚に《王下七武海》 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP02-056"), repo.get("ST01-004")] \
        + [repo.get("ST01-004")] * 28

    do, _ = _do(overlay, "OP02-057", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP02-057"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補ありで search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    cards = st.pending_choice.get("cards", [])
    idx = next(c["idx"] for c in cards if c["card_id"] == "OP02-056")
    resolve_pending_choice(st, [idx])
    _drain_choices(st)
    assert any(c.card_id == "OP02-056" for c in me.hand), \
        "人間が選んだ《王下七武海》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP02-058 バギー (CHARACTER): 【登場時】デッキ上5枚を見て、「バギー」以外の青の
#    《インペルダウン》カード1枚までを公開し手札に加える。残りをデッキの下へ。
# --------------------------------------------------------------------------- #
def test_op02_058_buggy_on_play_search_impel_ai():
    """登場時: デッキ上5枚から 青《インペルダウン》(バギー以外) を手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # OP02-050 イナズマ = 青 インペルダウン (バギー以外)
    me.deck = [repo.get("OP02-050")] + [repo.get("ST01-004")] * 29

    do, _ = _do(overlay, "OP02-058", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-058"), sickness=True))
    _drain_choices(st)

    assert any(c.card_id == "OP02-050" for c in me.hand), \
        "デッキ上5枚から 青《インペルダウン》カードが手札に加わっていない"


def test_op02_058_buggy_on_play_excludes_buggy():
    """「バギー」自身は exclude_name で対象外 → 手札に加わらない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # 上5枚を バギー (OP02-058) のみ + バニラ に → 該当なし
    me.deck = [repo.get("OP02-058")] + [repo.get("ST01-004")] * 29

    do, _ = _do(overlay, "OP02-058", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-058"), sickness=True))
    _drain_choices(st)

    assert not any(c.card_id == "OP02-058" for c in me.hand), \
        "「バギー」が exclude_name を無視して手札に加わってはいけない"


def test_op02_058_buggy_search_human_pick():
    """人間 + デッキ上5枚に 青《インペルダウン》 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP02-050"), repo.get("ST01-004")] \
        + [repo.get("ST01-004")] * 28

    do, _ = _do(overlay, "OP02-058", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP02-058"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補ありで search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    cards = st.pending_choice.get("cards", [])
    idx = next(c["idx"] for c in cards if c["card_id"] == "OP02-050")
    resolve_pending_choice(st, [idx])
    _drain_choices(st)
    assert any(c.card_id == "OP02-050" for c in me.hand), \
        "人間が選んだ 青《インペルダウン》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP02-059 ボア・ハンコック (CHARACTER): 【アタック時】カード1枚を引き、自分の手札
#    1枚を捨てる。その後、自分の手札3枚までを捨てる。
# --------------------------------------------------------------------------- #
def test_op02_059_hancock_on_attack_draw_discard_ai():
    """アタック時: 1ドロー + 手札1捨て + さらに手札3枚まで捨て (AI 自動、 対象選択なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")] * 5  # 5 枚
    me.deck = [repo.get("ST01-004")] * 10

    do, _ = _do(overlay, "OP02-059", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-059"), sickness=False))
    _drain_choices(st)

    # +1 ドロー -1 捨て -3 捨て = net -3 → 5 - 3 = 2
    assert len(me.hand) == 2, \
        f"1ドロー + 手札1捨て + 手札3捨て の net が合わない: {len(me.hand)} (期待 2)"


def test_op02_059_hancock_on_attack_small_hand_ai():
    """手札が少ない場合: 手札3枚までの捨ては 上限 min で 打ち切られ crash しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")] * 2  # 2 枚
    me.deck = [repo.get("ST01-004")] * 10

    do, _ = _do(overlay, "OP02-059", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-059"), sickness=False))
    _drain_choices(st)

    # 2 + 1(draw) - 1 - min(3, 2) = 3 - 1 - 2 = 0
    assert len(me.hand) == 0, \
        f"少ない手札での 捨て切り が想定通りでない: {len(me.hand)} (期待 0)"
