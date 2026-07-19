# -*- coding: utf-8 -*-
"""EB03 弾 効果 回帰テスト バックフィル (自動生成 wave 012):
EB03-027 / EB03-028 / EB03-029 / EB03-031 / EB03-032 / EB03-033 /
EB03-034 / EB03-035 / EB03-036 / EB03-037 の 10 枚。

目的 (= test_backfill_auto_001〜011.py と同一方針):
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
        for e in matches:
            if any(needle in prim for prim in e["do"]):
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
def test_all_eb03_wave12_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB03-027", "EB03-028", "EB03-029", "EB03-031", "EB03-032",
           "EB03-033", "EB03-034", "EB03-035", "EB03-036", "EB03-037"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB03-027 マーガレット: 【登場時】元々のパワー7000のキャラ1枚までを、持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_eb03_027_margaret_on_play_return_power7000_ai():
    """登場時: 元々のパワー7000の相手キャラ1枚を持ち主の手札へ戻す (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("EB03-019"), sickness=False)  # ワンダ 元々P7000 (バニラ)
    opp.characters = [victim]

    hand_before = len(opp.hand)
    do, _ = _do(overlay, "EB03-027", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-027"), sickness=False))

    assert victim not in opp.characters, "元々P7000の相手キャラが場から戻されていない"
    assert len(opp.hand) == hand_before + 1, "戻したキャラが持ち主 (相手) の手札に加わっていない"


def test_eb03_027_margaret_on_play_no_power7000_target():
    """元々のパワーが7000でないキャラは対象外 → 手札に戻らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    other = InPlay.of(repo.get("OP01-016"), sickness=False)  # 元々P2000
    opp.characters = [other]

    do, _ = _do(overlay, "EB03-027", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-027"), sickness=False))
    assert other in opp.characters, "元々P7000でないキャラが戻されてはいけない (対象外)"


def test_eb03_027_margaret_on_play_human_pick():
    """人間 + 元々P7000の相手キャラ 複数 → target_pick modal が立ち resolve で戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("EB03-019"), sickness=False)  # 元々P7000
    b = InPlay.of(repo.get("EB03-019"), sickness=False)  # 元々P7000
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB03-027", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-027"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが手札に戻されていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


# --------------------------------------------------------------------------- #
#  EB03-028 ユウ: 【登場時】自分の手札1枚を捨てる /
#    【起動メイン】このキャラをトラッシュ:自分の手札が4枚以下の場合、カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_eb03_028_yuu_on_play_discard_ai():
    """登場時: 自分の手札1枚をランダムに捨てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]

    hand_before = len(me.hand)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "EB03-028", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-028"), sickness=False))
    assert len(me.hand) == hand_before - 1, "登場時に手札1枚が捨てられていない"
    assert len(me.trash) == trash_before + 1, "捨てた手札がトラッシュに置かれていない"


def test_eb03_028_yuu_activate_main_draw_ai():
    """起動メイン: このキャラをトラッシュ (コスト) → 手札4枚以下でカード2枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    yuu = InPlay.of(repo.get("EB03-028"), sickness=False)
    me.characters = [yuu]
    me.hand = [repo.get("ST01-004")]  # 手札 1 枚 (≤4 = 条件成立)
    me.deck = [repo.get("ST01-004")] * 5

    hand_before = len(me.hand)
    opts = _am(st, me, overlay, "EB03-028")
    assert len(opts) == 1, f"EB03-028 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert yuu not in me.characters, "コストで ユウ がトラッシュに置かれるべき"
    assert len(me.hand) == hand_before + 2, "手札4枚以下で 2 枚引けていない"


def test_eb03_028_yuu_activate_main_blocked_when_hand_full():
    """手札が5枚以上なら【手札4枚以下】条件が不成立 → 起動メインは legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _opp = st.players[0], st.players[1]
    yuu = InPlay.of(repo.get("EB03-028"), sickness=False)
    me.characters = [yuu]
    me.hand = [repo.get("ST01-004")] * 5  # 5 枚 = 条件不成立
    me.deck = [repo.get("ST01-004")] * 5

    assert eval_condition({"self_hand_count_le": 4}, st, me) is False, \
        "手札5枚で self_hand_count_le=4 が成立してはいけない"
    opts = _am(st, me, overlay, "EB03-028")
    assert len(opts) == 0, "手札5枚では起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  EB03-029 不届き者‼控えよ‼ (EVENT):
#    【メイン】ドン4レスト:ハンコックリーダー時、手札からコスト6以下の
#      《アマゾン・リリー》/《九蛇海賊団》キャラ1枚まで登場 /
#    【カウンター】自分の「ボア・ハンコック」1枚まで +3000
# --------------------------------------------------------------------------- #
def test_eb03_029_main_play_from_hand_ai():
    """メイン (ハンコックリーダー): 手札から《九蛇海賊団》コスト6以下キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-038", overlay)  # ボア・ハンコック (leader_name 成立)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP16-112")]  # 九蛇海賊団 cost6 (バニラ)

    assert eval_condition({"leader_name": "ボア・ハンコック"}, st, me) is True, \
        "ハンコックリーダーで leader_name 条件が成立していない"
    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB03-029", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert len(me.characters) == chars_before + 1, \
        "手札から《九蛇海賊団》キャラが登場していない"
    assert any(c.card.card_id == "OP16-112" for c in me.characters), \
        "登場したのが想定キャラでない"


def test_eb03_029_main_negative_leader():
    """リーダーが「ボア・ハンコック」でない場合、 メイン登場条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (ハンコックでない)
    me, _opp = st.players[0], st.players[1]
    assert eval_condition({"leader_name": "ボア・ハンコック"}, st, me) is False, \
        "非ハンコックリーダーで leader_name 条件が成立してはいけない"


def test_eb03_029_counter_pump_hancock_ai():
    """カウンター: 自分の「ボア・ハンコック」1枚を このバトル +3000 (AI = リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-038", overlay)  # リーダー名 = ボア・ハンコック
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "EB03-029", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 がハンコックリーダーに反映されていない: {me.leader.power}"


def test_eb03_029_main_play_from_hand_human_pick():
    """人間 + 手札に候補 複数 → play_from_hand modal が立ち resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-038", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP16-112"), repo.get("OP16-112")]  # 2 枚 (> limit=1)

    do, _ = _do(overlay, "EB03-029", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert any(c.card.card_id == "OP16-112" for c in me.characters), \
        "人間が選んだキャラが登場していない"


# --------------------------------------------------------------------------- #
#  EB03-031 ヴィンスモーク・レイジュ:
#    【自分のターン中】【登場時】ドン-1:サンジリーダー時、
#      自分のトラッシュのコスト7以下イベント1枚までの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_eb03_031_reiju_on_play_fire_event_from_trash_ai():
    """登場時 (サンジリーダー): トラッシュのコスト7以下イベントの【メイン】効果を発動 (AI)。
    トラッシュに「サンジのピラフ」(main: draw2) を仕込む → 2 枚引ける。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP12-041", overlay)  # サンジ (leader_name 成立)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-056")]  # サンジのピラフ (EVENT cost3, main draw2)
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 5

    assert eval_condition({"leader_name": "サンジ"}, st, me) is True, \
        "サンジリーダーで leader_name 条件が成立していない"
    hand_before = len(me.hand)
    do, _ = _do(overlay, "EB03-031", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-031"), sickness=False))
    assert len(me.hand) == hand_before + 2, \
        "トラッシュのイベント【メイン】(draw2) が発動していない"


def test_eb03_031_reiju_on_play_no_event_in_trash():
    """トラッシュに該当イベントが無ければ 不発 (手札は増えない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP12-041", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = []  # イベントなし
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 5

    do, _ = _do(overlay, "EB03-031", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-031"), sickness=False))
    assert len(me.hand) == 0, "トラッシュにイベントが無いのに手札が増えてはいけない"


# --------------------------------------------------------------------------- #
#  EB03-032 シャーロット・フランペ:
#    【自分のターン中】【登場時】自分の「シャーロット・カタクリ」1枚まで +2000
# --------------------------------------------------------------------------- #
def test_eb03_032_flampe_on_play_pump_katakuri_ai():
    """登場時 (自ターン): 自分の「シャーロット・カタクリ」1枚を +2000 (AI)。
    リーダーがカタクリ → self_chara_or_leader_named が リーダーを対象にする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-062", overlay)  # シャーロット・カタクリ (leader)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "EB03-032", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-032"), sickness=False))
    assert me.leader.power == power_before + 2000, \
        f"「シャーロット・カタクリ」への +2000 が反映されていない: {me.leader.power}"


def test_eb03_032_flampe_on_play_no_katakuri():
    """「シャーロット・カタクリ」が場に居なければ pump 対象なし (crash しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # カタクリでない
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    power_before = friend.power
    leader_before = me.leader.power
    do, _ = _do(overlay, "EB03-032", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-032"), sickness=False))
    assert friend.power == power_before and me.leader.power == leader_before, \
        "カタクリ不在で無関係なキャラ/リーダーが pump されてはいけない"


# --------------------------------------------------------------------------- #
#  EB03-033 シャーロット・ブリュレ:
#    【相手のターン中】【ターン1回】自分の場のドン‼が自分の効果でドンデッキに戻された時、
#      ビッグ・マム海賊団リーダー時、ドンデッキからドン1枚までをレストで追加する。
# --------------------------------------------------------------------------- #
def test_eb03_033_brulee_add_rested_don_ai():
    """トリガー本体 (do): ドンデッキからレストドン1枚を追加する (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-062", overlay)  # ビッグ・マム海賊団 leader
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 成立)

    rested_before = me.don_rested
    do, _ = _do(overlay, "EB03-033", "on_self_don_returned_to_deck")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-033"), sickness=False))
    assert me.don_rested == rested_before + 1, \
        f"ドンデッキからレストドン1枚が追加されていない: {me.don_rested}"


def test_eb03_033_brulee_conditions():
    """発火条件: 相手ターン中 かつ リーダーが《ビッグ・マム海賊団》。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-062", overlay)
    me, _opp = st.players[0], st.players[1]
    st.turn_player_idx = 1
    assert eval_condition({"opp_turn": True}, st, me) is True, \
        "相手ターンで opp_turn 条件が成立していない"
    assert eval_condition({"leader_feature": "ビッグ・マム海賊団"}, st, me) is True, \
        "ビッグ・マム海賊団リーダーで leader_feature 条件が成立していない"
    # 自分ターンでは opp_turn 不成立
    st.turn_player_idx = 0
    assert eval_condition({"opp_turn": True}, st, me) is False, \
        "自分ターンで opp_turn 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  EB03-034 シャーロット・リンリン:
#    【登場時】カード1枚を引き、自分の手札1枚をデッキの上に置く。その後ドン1をアクティブで追加 /
#    【KO時】ドン-1:自分のデッキの上から1枚までを、ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_eb03_034_linlin_on_play_draw_recycle_don_ai():
    """登場時: 1ドロー → 手札1枚をデッキ上へ → ドン1アクティブ追加 (AI)。
    net 手札 ±0 / net デッキ ±0 / ドンアクティブ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004"), repo.get("ST01-004")]
    me.deck = [repo.get("ST01-004")] * 5
    me.don_active = 0

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    don_before = me.don_active
    do, _ = _do(overlay, "EB03-034", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-034"), sickness=False))
    # 引く +1 → 手札1枚をデッキ上へ -1 = net ±0
    assert len(me.hand) == hand_before, \
        f"登場時 手札 net (draw+1, deckへ-1) が合わない: {len(me.hand)}"
    # 引く -1 → 手札をデッキ上へ +1 = net ±0
    assert len(me.deck) == deck_before, \
        f"登場時 デッキ net が合わない: {len(me.deck)}"
    assert me.don_active == don_before + 1, \
        f"ドン1枚がアクティブで追加されていない: {me.don_active}"


def test_eb03_034_linlin_on_ko_top_to_life_ai():
    """KO時: ドン-1 (コスト) → デッキ上から1枚をライフの上へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    me.life = []
    me.don_active = 3  # ドン-1 コスト用

    life_before = len(me.life)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "EB03-034", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-034"), sickness=False))
    assert len(me.life) == life_before + 1, "KO時にデッキ上1枚がライフに加わっていない"
    assert len(me.deck) == deck_before - 1, "ライフに加えた分デッキが1枚減るべき"


# --------------------------------------------------------------------------- #
#  EB03-035 シャーロット・プリン:
#    【ブロッカー】【登場時】自分の場のドン‼が相手の場のドン‼の枚数以下の場合、
#      ドンデッキからドン1枚までをレストで追加する。
# --------------------------------------------------------------------------- #
def test_eb03_035_pudding_on_play_add_rested_don_ai():
    """登場時 (自ドン ≤ 相手ドン): ドンデッキからレストドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1
    me.don_rested = 0
    opp.don_active = 3  # 相手ドンの方が多い = 条件成立

    assert eval_condition({"don_diff_le": 0}, st, me) is True, \
        "自ドン ≤ 相手ドン で don_diff_le=0 が成立していない"
    rested_before = me.don_rested
    do, _ = _do(overlay, "EB03-035", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-035"), sickness=False))
    assert me.don_rested == rested_before + 1, \
        f"条件成立時にレストドン1枚が追加されていない: {me.don_rested}"


def test_eb03_035_pudding_don_diff_negative():
    """自分の場のドンが相手より多い場合、 don_diff_le=0 は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    opp.don_active = 1  # 自分の方が多い
    assert eval_condition({"don_diff_le": 0}, st, me) is False, \
        "自ドン > 相手ドン で don_diff_le=0 が成立してはいけない"


# --------------------------------------------------------------------------- #
#  EB03-036 ベビー５:
#    【登場時】ドン-1:相手の元々のコスト3以下のキャラ2枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_eb03_036_baby5_on_play_ko_two_ai():
    """登場時: 相手の元々コスト3以下キャラ2枚までを KO (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("EB02-029"), sickness=False)  # cost3 (バニラ)
    b = InPlay.of(repo.get("EB01-017"), sickness=False)  # cost2 (バニラ)
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB03-036", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-036"), sickness=False))
    assert a not in opp.characters and b not in opp.characters, \
        "相手のコスト3以下キャラ2枚が KO されていない"


def test_eb03_036_baby5_on_play_cost4_survives():
    """コスト4のキャラは【コスト3以下】対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get("EB03-035"), sickness=False)  # プリン cost4
    opp.characters = [big]

    do, _ = _do(overlay, "EB03-036", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-036"), sickness=False))
    assert big in opp.characters, "コスト4キャラが KO されてはいけない (対象外)"


def test_eb03_036_baby5_on_play_human_pick():
    """人間 + 相手コスト3以下キャラ 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("EB02-029"), sickness=False)  # cost3
    b = InPlay.of(repo.get("EB01-017"), sickness=False)  # cost2
    c = InPlay.of(repo.get("EB01-005"), sickness=False)  # cost1
    opp.characters = [a, b, c]

    do, _ = _do(overlay, "EB03-036", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-036"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    chars_before = len(opp.characters)
    resolve_pending_choice(st, [0])
    _drain(st, pick=[0])
    assert len(opp.characters) < chars_before, "人間解決後 相手キャラが1枚も KO されていない"


# --------------------------------------------------------------------------- #
#  EB03-037 リム:
#    【登場時】自分の場のドン‼が7枚以上ある場合、自分の《ODYSSEY》リーダーとキャラすべてを、
#      次の相手のエンドフェイズ終了時まで、パワー+1000。
# --------------------------------------------------------------------------- #
def test_eb03_037_rim_on_play_team_pump_ai():
    """登場時 (自ドン7枚以上): 自《ODYSSEY》リーダー+キャラすべてを +1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP09-022", overlay)  # リム (ODYSSEY leader)
    me, opp = st.players[0], st.players[1]
    ody_char = InPlay.of(repo.get("OP10-024"), sickness=False)  # ODYSSEY char P6000
    me.characters = [ody_char]
    me.don_active = 7  # 7 枚以上 = 条件成立

    assert eval_condition({"self_don_ge": 7}, st, me) is True, \
        "自ドン7枚で self_don_ge=7 が成立していない"
    leader_before = me.leader.power
    char_before = ody_char.power
    do, _ = _do(overlay, "EB03-037", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-037"), sickness=False))
    assert me.leader.power == leader_before + 1000, \
        f"《ODYSSEY》リーダーへの +1000 が反映されていない: {me.leader.power}"
    assert ody_char.power == char_before + 1000, \
        f"《ODYSSEY》キャラへの +1000 が反映されていない: {ody_char.power}"


def test_eb03_037_rim_on_play_don_lt_7():
    """自分の場のドンが7枚未満なら self_don_ge=7 は不成立 (pump は乗らない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP09-022", overlay)
    me, _opp = st.players[0], st.players[1]
    me.don_active = 6  # 7 未満
    assert eval_condition({"self_don_ge": 7}, st, me) is False, \
        "自ドン6枚で self_don_ge=7 が成立してはいけない"
