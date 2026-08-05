# -*- coding: utf-8 -*-
"""OP01 弾 効果 回帰テスト バックフィル (自動生成 wave 021):
OP01-032 / OP01-033 / OP01-034 / OP01-035 / OP01-037 / OP01-041 /
OP01-042 / OP01-044 / OP01-046 / OP01-048 の 10 枚。

目的 (= test_backfill_auto_001〜020.py と同一方針):
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
    eval_all_conditions,
    evaluate_static_effects,
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
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキ filler は OP01-020 (ワノ国、 麦わらの一味 でない) = search/draw フィルタ誤爆防止。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-020")] * 30
    p1.deck = [repo.get("OP01-020")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。"""
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
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave21_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP01-032", "OP01-033", "OP01-034", "OP01-035", "OP01-037",
           "OP01-041", "OP01-042", "OP01-044", "OP01-046", "OP01-048"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP01-032 アシュラ童子 (CHARACTER 緑 cost3 power4000):
#    【ドン‼×1】相手のレストのキャラが2枚以上いる場合、このキャラはパワー+2000。
# --------------------------------------------------------------------------- #
def test_op01_032_ashura_static_pump_with_two_rested_opp():
    """静的 (on_attached_don n=1、 相手レストキャラ2枚以上): 自身 static_buff +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    ashura = InPlay.of(repo.get("OP01-032"), sickness=False)
    ashura.attached_dons = 1  # ドン1 ゲート成立
    me.characters = [ashura]
    # 相手にレストキャラを 2 体 (= 条件成立)
    r1 = InPlay.of(repo.get("OP01-016"), sickness=False)
    r2 = InPlay.of(repo.get("OP01-013"), sickness=False)
    r1.rested = True
    r2.rested = True
    opp.characters = [r1, r2]

    evaluate_static_effects(st, overlay)
    assert ashura.static_buff == 2000, \
        f"相手レスト2枚で static_buff +2000 が乗っていない: {ashura.static_buff}"


def test_op01_032_ashura_no_pump_with_one_rested_opp():
    """相手のレストキャラが1枚しかなければ条件不成立 → static_buff +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    ashura = InPlay.of(repo.get("OP01-032"), sickness=False)
    ashura.attached_dons = 1
    me.characters = [ashura]
    r1 = InPlay.of(repo.get("OP01-016"), sickness=False)
    r1.rested = True
    active = InPlay.of(repo.get("OP01-013"), sickness=False)  # アクティブ = 数えない
    opp.characters = [r1, active]

    evaluate_static_effects(st, overlay)
    assert ashura.static_buff == 0, \
        f"相手レスト1枚で +2000 が乗ってはいけない: {ashura.static_buff}"


# --------------------------------------------------------------------------- #
#  OP01-033 イゾウ (CHARACTER 緑 cost3 power3000):
#    【登場時】相手のコスト4以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op01_033_izou_on_play_rest_cost4_ai():
    """登場時: 相手のコスト4以下キャラ1枚をレスト (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (≤4)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-033", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-033"), sickness=True))

    assert victim.rested is True, "相手のコスト4以下キャラがレストされていない"


def test_op01_033_izou_on_play_human_pick():
    """人間 + 相手コスト4以下キャラ → target_pick modal が立ち resolve でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-033", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-033"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (コスト4以下2体) が2件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされてはいけない"


# --------------------------------------------------------------------------- #
#  OP01-034 イヌアラシ (CHARACTER 緑 cost3 power4000):
#    【ドン‼×2】【アタック時】自分のドン‼1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op01_034_inuarashi_attack_untap_don_ai():
    """アタック時 (ドン2ゲート): 自分のレストドン1枚をアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 2

    do, eff = _do(overlay, "OP01-034", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-034"), sickness=False))

    assert me.don_active == 1, f"レストドン1枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, f"レストドンが1枚減っていない: {me.don_rested}"


# --------------------------------------------------------------------------- #
#  OP01-035 お菊 (CHARACTER 緑 cost3 power5000):
#    【ドン‼×1】【アタック時】【ターン1回】相手のコスト5以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op01_035_okiku_attack_rest_cost5_ai():
    """アタック時 (ドン1ゲート/ターン1回): 相手のコスト5以下キャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-014"), sickness=False)  # ジンベエ cost4 (≤5)
    opp.characters = [victim]

    do, eff = _do(overlay, "OP01-035", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    assert eff.get("cost", {}).get("once_per_turn") is True, \
        "overlay の【ターン1回】マーカーが無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-035"), sickness=False))

    assert victim.rested is True, "相手のコスト5以下キャラがレストされていない"


def test_op01_035_okiku_attack_rest_human_pick():
    """人間 + 相手コスト5以下キャラ複数 → target_pick modal が立ち resolve でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-014"), sickness=False)  # cost4
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-035", "on_attack")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-035"), sickness=False))

    assert st.pending_choice is not None, "人間 + 候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st, pick=[a_idx])
    assert a.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert b.rested is False, "選ばなかったキャラはレストされてはいけない"


# --------------------------------------------------------------------------- #
#  OP01-037 河松 (CHARACTER 緑 cost2 power3000):
#    【トリガー】このカードを登場させる (play_self)
# --------------------------------------------------------------------------- #
def test_op01_037_kawamatsu_trigger_play_self_ai():
    """トリガー: このカード (河松) を手札から登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-037")]
    st.current_source_card_id = "OP01-037"
    chars_before = len(me.characters)

    do, _ = _do(overlay, "OP01-037", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.characters) == chars_before + 1, "トリガーで河松が登場していない"
    assert any(c.card.card_id == "OP01-037" for c in me.characters), \
        "登場したキャラが河松 (OP01-037) でない"
    assert not any(c.card_id == "OP01-037" for c in me.hand), \
        "登場後も手札に河松が残っている"


# --------------------------------------------------------------------------- #
#  OP01-041 光月モモの助 (CHARACTER 緑 cost1):
#    【起動メイン】①+このキャラをレスト：デッキ上5枚から特徴《ワノ国》1枚までを手札、
#    残りを好きな順番でデッキの下。
# --------------------------------------------------------------------------- #
def test_op01_041_momonosuke_activate_main_search_wano_ai():
    """起動メイン: 自レスト + ドン1レスト → デッキ上5枚からワノ国1枚を手札 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    momo = InPlay.of(repo.get("OP01-041"), sickness=False)
    me.characters = [momo]
    me.don_active = 2  # rest_self_don 1 のコスト源
    me.don_rested = 0
    me.hand = []
    # 上5枚にワノ国 (ヒョウ五郎) を1枚仕込み、 残りも filler は ワノ国 だが limit=1 で1枚のみ
    me.deck = [repo.get("OP01-020")] + [repo.get("OP01-013")] * 10
    hand_before = len(me.hand)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP01-041"]
    assert len(opts) == 1, f"OP01-041 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert momo.rested is True, "起動メインコストで光月モモの助 がレストされるべき"
    assert me.don_active == 1 and me.don_rested == 1, \
        f"起動メインコストで ドン1枚がレストされていない: active={me.don_active}"
    assert len(me.hand) == hand_before + 1, "デッキ上5枚から1枚が手札に加わっていない"
    assert any(c.card_id == "OP01-020" for c in me.hand), \
        "手札に加わったのがワノ国キャラ (ヒョウ五郎) でない"


def test_op01_041_momonosuke_activate_main_human_search_pick():
    """人間 + デッキ上5枚にワノ国 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    momo = InPlay.of(repo.get("OP01-041"), sickness=False)
    me.characters = [momo]
    me.don_active = 2
    me.don_rested = 0
    me.hand = []
    me.deck = [repo.get("OP01-020"), repo.get("OP01-013"),
               repo.get("OP01-020")] + [repo.get("OP01-013")] * 10

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP01-041"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (ワノ国) を選択
    _drain(st)
    assert any(c.card_id == "OP01-020" for c in me.hand), \
        "人間が選んだワノ国キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP01-042 小紫 (CHARACTER 緑 cost1):
#    【登場時】③：自分のリーダーが「光月おでん」の場合、自分のコスト3以下の
#    特徴《ワノ国》を持つキャラ1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op01_042_kozuki_on_play_untap_wano_ai():
    """登場時 (リーダー光月おでん / ③ 任意コスト): ワノ国 cost3以下キャラ1枚をアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-031", overlay)  # リーダー = 光月おでん
    me, opp = st.players[0], st.players[1]
    me.don_active = 3  # rest_self_don 3 のコスト源
    me.don_rested = 0
    target = InPlay.of(repo.get("OP01-020"), sickness=False)  # ヒョウ五郎 ワノ国 cost2
    target.rested = True  # レスト状態 → アクティブ化の対象
    me.characters = [target]

    # overlay の if 条件 (leader_name 光月おでん) が成立している前提を確認
    _, eff = _do(overlay, "OP01-042", "on_play")
    assert eval_all_conditions(eff, st, me,
                               InPlay.of(repo.get("OP01-042"), sickness=True)) is True, \
        "テスト前提: リーダーが光月おでんで if 条件が成立していない"

    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-042"), sickness=True))

    assert me.don_active == 0 and me.don_rested == 3, \
        f"③ コスト (ドン3レスト) が支払われていない: active={me.don_active}"
    assert target.rested is False, "ワノ国 cost3以下キャラがアクティブになっていない"


def test_op01_042_kozuki_on_play_human_optional_confirm():
    """人間: ③ 任意コスト → optional_cost_confirm modal が立ち、 承諾でアクティブ化まで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-031", overlay, human_idx=0)  # リーダー = 光月おでん
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.don_rested = 0
    target = InPlay.of(repo.get("OP01-020"), sickness=False)  # ヒョウ五郎 ワノ国 cost2
    target.rested = True
    me.characters = [target]

    do, _ = _do(overlay, "OP01-042", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-042"), sickness=True))

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, pick=[0])
    assert me.don_active == 0, f"人間承諾後 ③ コストが支払われていない: {me.don_active}"
    assert target.rested is False, "人間承諾後 ワノ国キャラがアクティブになっていない"


# --------------------------------------------------------------------------- #
#  OP01-044 シャチ (CHARACTER 緑 cost3 power4000、 ブロッカー):
#    【登場時】自分の「ペンギン」がいない場合、自分の手札から「ペンギン」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op01_044_sachi_on_play_play_penguin_ai():
    """登場時: 場に「ペンギン」不在 → 手札の「ペンギン」を登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-050")]  # ペンギン

    sachi = InPlay.of(repo.get("OP01-044"), sickness=True)
    me.characters = [sachi]
    chars_before = len(me.characters)  # = 1 (シャチ本体)
    _, eff = _do(overlay, "OP01-044", "on_play")
    assert eval_all_conditions(eff, st, me, sachi) is True, \
        "テスト前提: 場にペンギン不在で if 条件が成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, sachi)

    assert any(c.card.card_id == "OP01-050" for c in me.characters), \
        "手札の「ペンギン」が登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体 (ペンギン) 増えていない"
    assert not any(c.card_id == "OP01-050" for c in me.hand), \
        "登場後も手札にペンギンが残っている"


def test_op01_044_sachi_on_play_human_play_pick():
    """人間 + 手札に「ペンギン」複数 → play_from_hand modal が立ち resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-050"), repo.get("OP01-050")]  # ペンギン 2 枚 → 選択が生じる
    sachi = InPlay.of(repo.get("OP01-044"), sickness=True)
    me.characters = [sachi]

    do, _ = _do(overlay, "OP01-044", "on_play")
    execute_effect(do[0], st, me, opp, sachi)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert any(c.card.card_id == "OP01-050" for c in me.characters), \
        "人間が選んだ「ペンギン」が登場していない"


# --------------------------------------------------------------------------- #
#  OP01-046 傳ジロー (CHARACTER 緑 cost5 power7000):
#    【ドン‼×1】【アタック時】自分のリーダーが「光月おでん」の場合、
#    自分のドン‼2枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op01_046_denjiro_attack_untap_don_ai():
    """アタック時 (リーダー光月おでん / ドン1ゲート): レストドン2枚をアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-031", overlay)  # リーダー = 光月おでん
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 3

    do, eff = _do(overlay, "OP01-046", "on_attack")
    assert eff.get("if", {}).get("leader_name") == "光月おでん", \
        "overlay の リーダー条件 leader_name=光月おでん が無い"
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-046"), sickness=False))

    assert me.don_active == 2, f"レストドン2枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, f"レストドンが2枚減っていない: {me.don_rested}"


# --------------------------------------------------------------------------- #
#  OP01-048 ネコマムシ (CHARACTER 緑 cost2 power3000):
#    【登場時】相手のコスト3以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op01_048_nekomamushi_on_play_rest_cost3_ai():
    """登場時: 相手のコスト3以下キャラ1枚をレスト (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2 (≤3)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP01-048", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP01-048"), sickness=True))

    assert victim.rested is True, "相手のコスト3以下キャラがレストされていない"


def test_op01_048_nekomamushi_on_play_human_pick():
    """人間 + 相手コスト3以下キャラ複数 → target_pick modal が立ち resolve でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP01-048", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP01-048"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (コスト3以下2体) が2件でない: {len(cands)}"
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st, pick=[a_idx])
    assert a.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert b.rested is False, "選ばなかったキャラはレストされてはいけない"
