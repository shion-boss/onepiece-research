# -*- coding: utf-8 -*-
"""OP14 弾 効果 回帰テスト バックフィル (自動生成 wave 134):
OP14-036 / OP14-037 / OP14-038 / OP14-039 / OP14-042 / OP14-043 /
OP14-045 / OP14-046 / OP14-047 / OP14-048 の 10 枚。

目的 (= test_backfill_auto_001〜133.py と同一方針):
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
    デッキは効果の薄いカード (ST01-004 / OP01-016) で埋める (= サーチ/ドロー混入回避)。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-016")] * 30
    p1.deck = [repo.get("OP01-016")] * 30
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
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op14_wave134_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP14-036", "OP14-037", "OP14-038", "OP14-039", "OP14-042",
           "OP14-043", "OP14-045", "OP14-046", "OP14-047", "OP14-048"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP14-036 このおれを越えてみよロロノア!!! (EVENT 緑):
#    【カウンター】自カード1枚レスト可：自リーダー/キャラ1枚まで このバトル +4000
#    【トリガー】自カード1枚レスト可：相手の元々P7000以下キャラ1枚まで レスト
# --------------------------------------------------------------------------- #
def test_op14_036_counter_pump_leader_ai():
    """【カウンター】AI 既定: 自リーダーを このバトル中 +4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP14-036", "counter", needle="power_pump")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 4000, \
        f"カウンター +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_op14_036_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → target_pick modal が立ち キャラに +4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP14-036", "counter", needle="power_pump")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain(st)
    assert friend.power == before + 4000, "人間が選んだキャラに +4000 が反映されていない"


def test_op14_036_trigger_rest_opp_chara_ai():
    """【トリガー】自カード1枚レスト → 相手の元々P7000以下キャラをレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # コスト用に自キャラ1体 (active)
    me.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000 (<=7000)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP14-036", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-036"), sickness=False))
    assert victim.rested is True, "トリガーで相手のP7000以下キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP14-037 ヒマつぶし (EVENT 緑):
#    【メイン】自カード3枚レスト可：相手のレストの元々P7000以下キャラ1枚まで KO
#    【カウンター】自リーダー このバトル +3000
# --------------------------------------------------------------------------- #
def test_op14_037_main_ko_rested_opp_chara_ai():
    """【メイン】自カード3枚レスト → 相手のレストのP7000以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # レストコスト用に active 自キャラ3体
    me.characters = [InPlay.of(repo.get("OP01-013"), sickness=False) for _ in range(3)]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    victim.rested = True  # 「レストの」条件
    opp.characters = [victim]

    do, _ = _do(overlay, "OP14-037", "main")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-037"), sickness=True))
    assert victim not in opp.characters, \
        "メインで相手のレストP7000以下キャラが KO されていない"


def test_op14_037_main_needs_rested_victim():
    """相手キャラが active (レストでない) 場合は KO 対象にならない (= 場に残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP01-013"), sickness=False) for _ in range(3)]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # active のまま
    opp.characters = [victim]

    do, _ = _do(overlay, "OP14-037", "main")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-037"), sickness=True))
    assert victim in opp.characters, \
        "active な相手キャラが「レストの」条件に反して KO されている"


def test_op14_037_counter_pump_leader_ai():
    """【カウンター】自リーダー このバトル中 +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP14-037", "counter", needle="power_pump")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンター +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP14-038 虫ケラの顔など…!!! (EVENT 緑):
#    【メイン】自カード2枚レスト可：1ドロー + 相手の元々P7000以下キャラ1枚まで レスト
#    【カウンター】自リーダー このバトル +3000
# --------------------------------------------------------------------------- #
def test_op14_038_main_draw_and_rest_ai():
    """【メイン】自カード2枚レスト → 1ドロー + 相手P7000以下キャラをレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP01-013"), sickness=False) for _ in range(2)]
    me.hand = []
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    opp.characters = [victim]

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP14-038", "main")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-038"), sickness=True))
    assert len(me.hand) == hand_before + 1, "メインで1ドローされていない"
    assert victim.rested is True, "メインで相手のP7000以下キャラがレストされていない"


def test_op14_038_counter_pump_leader_ai():
    """【カウンター】自リーダー このバトル中 +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP14-038", "counter", needle="power_pump")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンター +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP14-039 棺船 (STAGE 緑):
#    【登場時】自リーダーが「ジュラキュール・ミホーク」なら 1ドロー
#    【自ターン終了時】同条件で 自ドン1枚まで アクティブに
# --------------------------------------------------------------------------- #
def test_op14_039_on_play_draw_when_mihawk_ai():
    """【登場時】ミホークリーダーで 1ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-020", overlay)  # ジュラキュール・ミホーク
    me, opp = st.players[0], st.players[1]
    assert eval_condition({"leader_name": "ジュラキュール・ミホーク"}, st, me) is True, \
        "ミホークリーダーで leader_name 条件が成立していない"

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP14-039", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-039"), sickness=True))
    assert len(me.hand) == hand_before + 1, "登場時 1ドローが反映されていない"


def test_op14_039_condition_false_for_non_mihawk():
    """非ミホークリーダーでは leader_name 条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # モンキー・D・ルフィ
    me = st.players[0]
    assert eval_condition({"leader_name": "ジュラキュール・ミホーク"}, st, me) is False, \
        "非ミホークリーダーで leader_name 条件が成立してはいけない"


def test_op14_039_end_of_turn_untap_don_ai():
    """【自ターン終了時】自ドン1枚をアクティブに (レストドン→アクティブ、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-020", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    me.don_active = 0

    active_before = me.don_active
    rested_before = me.don_rested
    do, _ = _do(overlay, "OP14-039", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-039"), sickness=False))
    assert me.don_active == active_before + 1, \
        f"ターン終了時 ドン1枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


# --------------------------------------------------------------------------- #
#  OP14-042 アーロン (CHARACTER 青):
#    【登場時】自リーダー特徴《魚人族》なら 上4枚見て コスト2以上1枚まで公開して手札、
#              残りは好きな順でデッキ下
# --------------------------------------------------------------------------- #
def test_op14_042_on_play_search_cost_ge2_ai():
    """【登場時】上4枚から コスト2以上1枚を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay)  # ジンベエ (魚人族 leader)
    me, opp = st.players[0], st.players[1]
    big = repo.get("EB01-049")  # cost5 (= コスト2以上)
    assert big.cost >= 2
    # top4 の中で コスト2以上は EB01-049 のみ (OP01-016 は cost1)
    me.deck = [big] + [repo.get("OP01-016")] * 10
    me.hand = []

    do, _ = _do(overlay, "OP14-042", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-042"), sickness=True))
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "上4枚から コスト2以上のカードが手札に加わっていない"


def test_op14_042_on_play_search_human_modal():
    """人間: 上4枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-040", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB01-049")] + [repo.get("OP01-016")] * 10
    me.hand = []

    do, _ = _do(overlay, "OP14-042", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-042"), sickness=True))
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "人間が選んだ コスト2以上カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP14-043 アラディン (CHARACTER 青):
#    【登場時】手札からコスト3以下の《魚人族》/《人魚族》キャラ1枚まで 登場
#    【KO時】1ドロー
# --------------------------------------------------------------------------- #
def test_op14_043_on_play_deploy_fishman_ai():
    """【登場時】手札の コスト3以下《魚人族》キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    aladdin = repo.get("EB02-011")  # アーロン cost3 魚人族
    assert aladdin.cost <= 3
    me.hand = [aladdin]

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP14-043", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-043"), sickness=True))
    assert any(c.card.card_id == "EB02-011" for c in me.characters), \
        "手札の コスト3以下《魚人族》キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_op14_043_on_ko_draw_ai():
    """【KO時】1ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP14-043", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-043"), sickness=False))
    assert len(me.hand) == hand_before + 1, "KO時 1ドローが反映されていない"


# --------------------------------------------------------------------------- #
#  OP14-045 クロオビ (CHARACTER 青):
#    効果で自分の手札が捨てられた時 このターン中【速攻】を得る / 【KO時】1ドロー
# --------------------------------------------------------------------------- #
def test_op14_045_hand_discarded_grants_rush_ai():
    """効果で自分の手札が捨てられた時、 このキャラは このターン中【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kurobi = InPlay.of(repo.get("OP14-045"), sickness=True)
    me.characters = [kurobi]

    assert "速攻" not in kurobi.granted_keywords, "初期状態で速攻を持っていてはいけない"
    do, _ = _do(overlay, "OP14-045", "on_self_hand_discarded")
    for prim in do:
        execute_effect(prim, st, me, opp, kurobi)
    assert "速攻" in kurobi.granted_keywords, \
        "手札が捨てられた時に【速攻】が付与されていない"


def test_op14_045_on_ko_draw_ai():
    """【KO時】1ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP14-045", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-045"), sickness=False))
    assert len(me.hand) == hand_before + 1, "KO時 1ドローが反映されていない"


# --------------------------------------------------------------------------- #
#  OP14-046 コアラ (CHARACTER 青):
#    【起動メイン】このキャラをトラッシュ可：自《魚人族》/《人魚族》リーダー/キャラ1枚まで
#      このターン中 +2000
# --------------------------------------------------------------------------- #
def test_op14_046_activate_main_trash_self_pump_ai():
    """起動メイン: コアラをトラッシュ → 自《魚人族》キャラを +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 非魚人族 leader → 対象はキャラのみ
    me, opp = st.players[0], st.players[1]
    coala = InPlay.of(repo.get("OP14-046"), sickness=False)
    friend = InPlay.of(repo.get("EB02-011"), sickness=False)  # アーロン 魚人族 power4000
    me.characters = [coala, friend]

    power_before = friend.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP14-046"]
    assert len(opts) == 1, f"OP14-046 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert friend.power == power_before + 2000, \
        f"起動メインで自《魚人族》キャラに +2000 が反映されていない: {friend.power}"
    assert coala not in me.characters, "コストで コアラ がトラッシュに置かれるべき"
    assert any(c.card_id == "OP14-046" for c in me.trash), \
        "コアラがトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP14-047 しらほし (CHARACTER 青):
#    【ブロッカー】【登場時】1ドロー + 手札からコスト3以下の《魚人族》/《人魚族》キャラ1枚まで 登場
# --------------------------------------------------------------------------- #
def test_op14_047_on_play_draw_and_deploy_ai():
    """【登場時】1ドロー + 手札の コスト3以下《魚人族》キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    fishman = repo.get("EB02-011")  # アーロン cost3 魚人族
    me.hand = [fishman]
    me.deck = [repo.get("OP01-016")] * 10  # ドロー用

    deck_before = len(me.deck)
    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP14-047", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-047"), sickness=True))
    assert len(me.deck) == deck_before - 1, "登場時 1ドローでデッキが1枚減っていない"
    assert any(c.card.card_id == "EB02-011" for c in me.characters), \
        "手札の コスト3以下《魚人族》キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP14-048 シリュウ (CHARACTER 青):
#    【登場時】相手のキャラ1枚まで 持ち主の手札に戻す。 その後 自分の手札すべてを捨てる
# --------------------------------------------------------------------------- #
def test_op14_048_on_play_bounce_and_discard_hand_ai():
    """【登場時】相手キャラを手札に戻し、 その後 自分の手札すべてを捨てる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]
    opp.hand = []
    me.hand = [repo.get("OP01-013"), repo.get("OP01-016"), repo.get("ST01-004")]

    do, _ = _do(overlay, "OP14-048", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-048"), sickness=True))
    assert victim not in opp.characters, "相手キャラが手札に戻っていない"
    assert any(c.card_id == "OP01-016" for c in opp.hand), \
        "戻された相手キャラが相手の手札に加わっていない"
    assert len(me.hand) == 0, "その後 自分の手札すべてが捨てられていない"


def test_op14_048_on_play_bounce_human_pick():
    """人間 + 相手キャラ複数 → return_to_hand の target_pick modal が立ち解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [a, b]
    opp.hand = []
    me.hand = [repo.get("ST01-004")]

    do, _ = _do(overlay, "OP14-048", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-048"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"相手キャラ候補が 2 件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだ相手キャラが手札に戻っていない"
