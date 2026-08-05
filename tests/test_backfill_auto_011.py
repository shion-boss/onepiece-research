# -*- coding: utf-8 -*-
"""EB03 弾 効果 回帰テスト バックフィル (自動生成 wave 011):
EB03-016 / EB03-017 / EB03-018 / EB03-020 / EB03-021 / EB03-022 /
EB03-023 / EB03-024 / EB03-025 / EB03-026 の 10 枚。

目的 (= test_backfill_auto_001〜010.py と同一方針):
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


def _am(st, me, overlay, cid):
    """指定 card_id の legal な起動メイン (src, eff) を返す (無ければ空 list)。"""
    return [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == cid]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_eb03_wave11_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB03-016", "EB03-017", "EB03-018", "EB03-020", "EB03-021",
           "EB03-022", "EB03-023", "EB03-024", "EB03-025", "EB03-026"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB03-016 光月日和: 【登場時】リーダーが「光月おでん」で 1ドロー /
#    【起動メイン】このキャラをトラッシュ:自《ワノ国》リーダーにレストドン1まで付与
# --------------------------------------------------------------------------- #
def test_eb03_016_hiyori_on_play_draw_ai():
    """登場時: リーダーが「光月おでん」の場合 1ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # 光月おでん (ワノ国)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 5

    assert eval_condition({"leader_name": "光月おでん"}, st, me) is True, \
        "光月おでんリーダーで leader_name 条件が成立していない"
    deck_before = len(me.deck)
    do, _ = _do(overlay, "EB03-016", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-016"), sickness=False))
    assert len(me.hand) == 1, "登場時のドローが起きていない"
    assert len(me.deck) == deck_before - 1, "ドローでデッキが1枚減っていない"


def test_eb03_016_hiyori_on_play_draw_negative_leader():
    """リーダーが「光月おでん」でない場合、 登場時ドロー条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ロロノア・ゾロ (光月おでんでない)
    me, _opp = st.players[0], st.players[1]
    assert eval_condition({"leader_name": "光月おでん"}, st, me) is False, \
        "非光月おでんリーダーで leader_name 条件が成立してはいけない"


def test_eb03_016_hiyori_activate_main_attach_don_ai():
    """起動メイン: 光月日和をトラッシュ (コスト) → 自《ワノ国》リーダーにレストドン1付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # 光月おでん (ワノ国)
    me, opp = st.players[0], st.players[1]
    hiyori = InPlay.of(repo.get("EB03-016"), sickness=False)
    me.characters = [hiyori]
    me.don_rested = 2

    assert eval_condition({"leader_feature": "ワノ国"}, st, me) is True, \
        "ワノ国リーダーで leader_feature 条件が成立していない"
    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    opts = _am(st, me, overlay, "EB03-016")
    assert len(opts) == 1, f"EB03-016 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert hiyori not in me.characters, "コストで光月日和がトラッシュに置かれるべき"
    assert me.leader.attached_dons == don_before + 1, \
        f"自リーダーへレストドン1枚が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


# --------------------------------------------------------------------------- #
#  EB03-017 ジュエリー・ボニー: 【登場時】自《超新星》リーダー時、 ドン1までアクティブ +
#    相手コスト8以下キャラ1枚まで 次相手エンド終了まで レスト不能
# --------------------------------------------------------------------------- #
def test_eb03_017_bonney_on_play_untap_and_cannot_rest_ai():
    """登場時 (超新星リーダー): レストドン1をアクティブに → 相手コスト8以下1枚レスト不能。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ロロノア・ゾロ (超新星)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 2
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=8)
    opp.characters = [victim]

    assert eval_condition({"leader_feature": "超新星"}, st, me) is True, \
        "超新星リーダーで leader_feature 条件が成立していない"
    do, _ = _do(overlay, "EB03-017", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-017"), sickness=False))

    assert me.don_active == 1, f"レストドン1がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 1, "レストドンが1枚アクティブ化で減るべき"
    assert victim.cannot_be_rested_buff is True, \
        "相手コスト8以下キャラがレスト不能になっていない"


def test_eb03_017_bonney_on_play_negative_leader():
    """非《超新星》リーダーでは 登場時条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # 光月おでん (超新星でない)
    me, _opp = st.players[0], st.players[1]
    assert eval_condition({"leader_feature": "超新星"}, st, me) is False, \
        "非超新星リーダーで 超新星条件が成立してはいけない"


def test_eb03_017_bonney_cannot_rest_human_pick():
    """人間 + 相手コスト8以下キャラ 複数 → set_cannot_rest の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB03-017", "on_play")
    # set_cannot_rest 単体を発火 (untap_don は先に流しても差し支えないが、 modal を分離する)
    cannot_rest_prim = next(p for p in do if "set_cannot_rest" in p)
    execute_effect(cannot_rest_prim, st, me, opp,
                   InPlay.of(repo.get("EB03-017"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.cannot_be_rested_buff is True, "人間が選んだ相手キャラがレスト不能になっていない"
    assert a.cannot_be_rested_buff is False, "選ばなかったキャラはレスト不能にならないべき"


# --------------------------------------------------------------------------- #
#  EB03-018 たしぎ: 【相手のターン中】相手効果でKOされず【ブロッカー】/
#    【自分のターン終了時】ドン1レスト + 手札1捨てる:このキャラをアクティブに
# --------------------------------------------------------------------------- #
def test_eb03_018_tashigi_static_blocker_opp_turn():
    """相手ターン中: ブロッカー付与 + 相手効果耐性 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    tashigi = InPlay.of(repo.get("EB03-018"), sickness=False)
    me.characters = [tashigi]

    evaluate_static_effects(st, overlay)
    assert tashigi.is_blocker_now is True, \
        "相手ターン中に ブロッカー が付与されていない"
    assert tashigi.protect_from_opp_effect is True, \
        "相手ターン中に 相手効果耐性 が付与されていない"


def test_eb03_018_tashigi_no_blocker_own_turn():
    """自分のターン中は【相手のターン中】条件不成立 → ブロッカーは乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分のターン
    tashigi = InPlay.of(repo.get("EB03-018"), sickness=False)
    me.characters = [tashigi]

    evaluate_static_effects(st, overlay)
    assert tashigi.is_blocker_now is False, \
        "自分ターンで ブロッカー が乗ってはいけない"


def test_eb03_018_tashigi_end_of_turn_untap_ai():
    """自ターン終了時 (任意): ドン1レスト + 手札1捨てる → このキャラをアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    tashigi = InPlay.of(repo.get("EB03-018"), sickness=False)
    tashigi.rested = True  # レスト状態 → アクティブ化を検証
    me.characters = [tashigi]
    me.don_active = 1
    me.hand = [repo.get("ST01-004")]

    hand_before = len(me.hand)
    do, _ = _do(overlay, "EB03-018", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp, tashigi)

    assert tashigi.rested is False, "自ターン終了時の任意コストで アクティブ化していない"
    assert len(me.hand) == hand_before - 1, "コストで手札1枚が捨てられるべき"


def test_eb03_018_tashigi_end_of_turn_human_confirm():
    """人間 actor: 任意コストの optional_cost_confirm modal が立ち、 承諾で解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    tashigi = InPlay.of(repo.get("EB03-018"), sickness=False)
    tashigi.rested = True
    me.characters = [tashigi]
    me.don_active = 1
    me.hand = [repo.get("ST01-004")]

    do, _ = _do(overlay, "EB03-018", "end_of_turn")
    execute_effect(do[0], st, me, opp, tashigi)
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= 払う)
    _drain(st, pick=[0])
    assert tashigi.rested is False, "人間承諾後 アクティブ化していない"


# --------------------------------------------------------------------------- #
#  EB03-020 出た!負け惜しみ～ (EVENT): 【カウンター】自リーダー/キャラ1枚まで +2000 /
#    【トリガー】自分のキャラ1枚をアクティブに
# --------------------------------------------------------------------------- #
def test_eb03_020_counter_pump_ai():
    """カウンター: 自リーダーかキャラ1枚 このバトル +2000 (AI 既定=リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    do, _ = _do(overlay, "EB03-020", "counter")
    power_before = me.leader.power
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_eb03_020_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "EB03-020", "counter")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


def test_eb03_020_trigger_untap_chara_ai():
    """トリガー: 自分のキャラ1枚をアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    friend.rested = True
    me.characters = [friend]

    do, _ = _do(overlay, "EB03-020", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert friend.rested is False, "トリガーの キャラ・アクティブ化が反映されていない"


# --------------------------------------------------------------------------- #
#  EB03-021 アルビダ: 【登場時】手札1捨てる:相手の元々P4000以下キャラ1枚まで +
#    コスト3以下キャラ1枚まで を 持ち主のデッキ下へ
# --------------------------------------------------------------------------- #
def test_eb03_021_alvida_on_play_return_two_ai():
    """登場時 (任意): 手札1捨てる → 相手 元々P4000以下1体 + コスト3以下1体 をデッキ下 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")]  # 捨てるコスト用
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # 元々P2000 / cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # 元々P3000 / cost2
    opp.characters = [a, b]

    hand_before = len(me.hand)
    chars_before = len(opp.characters)
    do, _ = _do(overlay, "EB03-021", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-021"), sickness=False))

    assert len(me.hand) == hand_before - 1, "任意コストで手札1枚が捨てられるべき"
    assert len(opp.characters) == chars_before - 2, \
        f"相手キャラ2体がデッキ下に置かれていない: {len(opp.characters)}"


def test_eb03_021_alvida_on_play_human_confirm():
    """人間 actor: 任意コストの optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [a]

    do, _ = _do(overlay, "EB03-021", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-021"), sickness=False))
    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, pick=[0])
    assert a not in opp.characters, "人間承諾後 相手キャラがデッキ下に置かれていない"


# --------------------------------------------------------------------------- #
#  EB03-022 イスカ: 【ブロッカー】【登場時】コスト4以下キャラ1枚まで を 持ち主のデッキ下へ
# --------------------------------------------------------------------------- #
def test_eb03_022_isuka_on_play_return_ai():
    """登場時: 相手コスト4以下キャラ1枚をデッキ下 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=4)
    opp.characters = [victim]

    do, _ = _do(overlay, "EB03-022", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-022"), sickness=False))
    assert victim not in opp.characters, "相手コスト4以下キャラがデッキ下に置かれていない"


def test_eb03_022_isuka_on_play_human_pick():
    """人間 + 相手コスト4以下キャラ 複数 → target_pick modal が立ち resolve でデッキ下。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB03-022", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-022"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラがデッキ下に置かれていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  EB03-023 カヤ: 【登場時】自デッキ上5枚を見て 好きな順に並び替え デッキ上か下へ
# --------------------------------------------------------------------------- #
def test_eb03_023_kaya_on_play_reorder_ai():
    """登場時: 上5枚を見て並び替え (AI ヒューリスティック=コスト昇順)。 デッキ枚数不変。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # 上5枚: 高コスト先頭 + 低コスト → 並び替え後は 低コストが上に来る
    me.deck = ([repo.get("EB03-019"),   # cost6
                repo.get("OP01-016")]   # cost1
               + [repo.get("ST01-004")] * 3   # cost2 x3
               + [repo.get("ST01-004")] * 10)
    deck_before = len(me.deck)

    do, _ = _do(overlay, "EB03-023", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-023"), sickness=False))

    assert len(me.deck) == deck_before, "並び替えでデッキ枚数が変化してはいけない"
    assert me.deck[0].card_id == "OP01-016", \
        f"コスト昇順並び替えで最低コストが上に来ていない: {me.deck[0].card_id}"


# --------------------------------------------------------------------------- #
#  EB03-024 ネフェルタリ・ビビ: 【ブロッカー】【登場時】手札から
#    《アラバスタ王国》か《麦わらの一味》 コスト5以下キャラ1枚まで登場 → その後 登場不可
# --------------------------------------------------------------------------- #
def test_eb03_024_vivi_on_play_play_from_hand_ai():
    """登場時: 手札の《麦わらの一味》cost5以下キャラを登場 → その後キャラ登場不可 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    nami = repo.get("OP01-016")  # 麦わらの一味 cost1 CHARACTER
    me.hand = [nami]

    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB03-024", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-024"), sickness=False))

    assert any(c.card.card_id == "OP01-016" for c in me.characters), \
        "手札の《麦わらの一味》キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"
    assert me.block_chara_play_until_turn_end is True, \
        "その後の【キャラ登場不可】が反映されていない"


def test_eb03_024_vivi_on_play_human_play_pick():
    """人間 + 手札に対象キャラ 複数 → play_from_hand modal が立ち resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 2 種の 対象 (麦わらの一味 cost5以下) キャラ を手札に
    me.hand = [repo.get("OP01-016"), repo.get("OP01-013")]

    do, _ = _do(overlay, "EB03-024", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-024"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert any(c.card.card_id in ("OP01-016", "OP01-013")
               for c in me.characters), \
        "人間が選んだキャラが登場していない"


# --------------------------------------------------------------------------- #
#  EB03-025 ヒナ: 【登場時】手札1捨てる:元々パワー6000のキャラ1枚まで を 持ち主の手札へ
# --------------------------------------------------------------------------- #
def test_eb03_025_hina_on_play_bounce_ai():
    """登場時 (任意): 手札1捨てる → 相手 元々パワー6000キャラ1枚を手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")]  # 捨てるコスト用
    victim = InPlay.of(repo.get("EB03-002"), sickness=False)  # 元々P6000
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)

    hand_before = len(me.hand)
    do, _ = _do(overlay, "EB03-025", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-025"), sickness=False))

    assert len(me.hand) == hand_before - 1, "任意コストで手札1枚が捨てられるべき"
    assert victim not in opp.characters, "元々パワー6000キャラが手札に戻されていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻したキャラが相手の手札に加わるべき"


def test_eb03_025_hina_on_play_no_target_power():
    """相手に 元々パワー6000キャラが居ない場合は 戻す対象が無い (盤面不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # P2000 (≠6000)
    opp.characters = [victim]

    do, _ = _do(overlay, "EB03-025", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-025"), sickness=False))
    assert victim in opp.characters, \
        "元々パワー6000でないキャラが手札に戻されてはいけない"


# --------------------------------------------------------------------------- #
#  EB03-026 ボア・ハンコック: 【登場時】相手手札5枚以上なら 相手手札1枚デッキ下 /
#    【起動メイン】【ターン1回】自キャラ1枚デッキ下:自リーダーとキャラ1枚にレストドン1ずつ付与
# --------------------------------------------------------------------------- #
def test_eb03_026_hancock_on_play_opp_hand_to_deck_ai():
    """登場時: 相手手札5枚以上 → 相手手札1枚をデッキ下へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get("ST01-004")] * 5  # 5 枚 (>=5 条件成立)
    opp.deck = [repo.get("ST01-004")] * 10

    assert eval_condition({"opp_hand_count_ge": 5}, st, me) is True, \
        "相手手札5枚以上で opp_hand_count_ge 条件が成立していない"
    hand_before = len(opp.hand)
    deck_before = len(opp.deck)
    do, _ = _do(overlay, "EB03-026", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-026"), sickness=False))

    assert len(opp.hand) == hand_before - 1, "相手手札が1枚デッキ下に置かれていない"
    assert len(opp.deck) == deck_before + 1, "相手デッキが1枚増えるべき"


def test_eb03_026_hancock_on_play_negative_hand():
    """相手手札が5枚未満なら 登場時条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get("ST01-004")] * 3  # 3 枚 (<5)
    assert eval_condition({"opp_hand_count_ge": 5}, st, me) is False, \
        "相手手札5枚未満で opp_hand_count_ge が成立してはいけない"


def test_eb03_026_hancock_activate_main_attach_don_ai():
    """起動メイン (自キャラ1枚デッキ下コスト): 自リーダー+キャラ1枚にレストドン1ずつ付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hancock = InPlay.of(repo.get("EB03-026"), sickness=False)
    fodder = InPlay.of(repo.get("OP01-016"), sickness=False)  # コストで捨てる用
    receiver = InPlay.of(repo.get("OP01-013"), sickness=False)  # ドン付与先候補
    me.characters = [hancock, fodder, receiver]
    me.don_rested = 3

    don_leader_before = me.leader.attached_dons
    chars_before = len(me.characters)
    opts = _am(st, me, overlay, "EB03-026")
    assert len(opts) == 1, f"EB03-026 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, pick=[0])

    assert len(me.characters) == chars_before - 1, \
        "コストで自キャラ1枚がデッキ下に置かれるべき"
    assert me.leader.attached_dons == don_leader_before + 1, \
        f"自リーダーへレストドン1枚が付与されていない: {me.leader.attached_dons}"
