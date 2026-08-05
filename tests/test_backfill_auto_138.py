# -*- coding: utf-8 -*-
"""OP14 弾 効果 回帰テスト バックフィル (自動生成 wave 138):
OP14-108 / OP14-109 / OP14-110 / OP14-111 / OP14-115 / OP14-116 /
OP14-117 / OP14-118 / OP14-119 / OP14-120 の 10 枚。

目的 (= test_backfill_auto_001〜137.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 を 持つカードは 人間 actor で pending_choice が
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
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


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


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do 配列, eff) を返す。"""
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
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op14_wave138_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP14-108", "OP14-109", "OP14-110", "OP14-111", "OP14-115",
           "OP14-116", "OP14-117", "OP14-118", "OP14-119", "OP14-120"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP14-108 シルバーズ・レイリー (CHARACTER 黄 cost6 power6000):
#    【登場時】自分のリーダーが多色で、 相手のライフが3枚以下の場合、
#             相手の元々のパワー7000以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op14_108_on_play_ko_condition_true_multicolor_life3():
    """多色リーダー + 相手ライフ3以下で 登場時条件が成立し、 P7000以下キャラをKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB04-001", overlay)  # ボニー (赤/黄 = 多色)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-016")] * 3  # ライフ 3 (= 条件成立)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000 ≤ 7000
    opp.characters = [victim]

    do, eff = _do(overlay, "OP14-108", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "多色リーダー + 相手ライフ3以下で登場時条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-108"), sickness=True))
    _drain(st, [0])
    assert victim not in opp.characters, "登場時に P7000以下の相手キャラがKOされていない"


def test_op14_108_on_play_condition_false_monocolor_leader():
    """単色リーダーでは登場時条件が不成立 (= 多色条件を満たさない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (赤 単色)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-016")] * 3
    _, eff = _do(overlay, "OP14-108", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "単色リーダーで登場時条件が成立してはいけない"


def test_op14_108_on_play_ko_human_pick():
    """人間 + P7000以下の相手キャラ 複数 → target_pick modal が立ち resolve で1枚KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-016")] * 3
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP14-108", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-108"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP14-109 ビクトリア・シンドリー (CHARACTER 黄 cost3 power1000):
#    【ブロッカー】 (intrinsic)。
#    【トリガー】自分のトラッシュからコスト4以下の《スリラーバーク海賊団》
#               キャラカード1枚までを、 レストで登場させる。
# --------------------------------------------------------------------------- #
def test_op14_109_is_blocker():
    """ビクトリアは【ブロッカー】を持つ (intrinsic)。"""
    repo = _repo()
    salome = InPlay.of(repo.get("OP14-109"), sickness=False)
    assert salome.is_blocker_now is True, \
        "ビクトリア・シンドリーが【ブロッカー】と判定されていない"


def test_op14_109_trigger_play_from_trash_ai():
    """【トリガー】自トラッシュから《スリラーバーク海賊団》cost4以下をレストで登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hildon = repo.get("EB02-046")  # スリラーバーク海賊団 cost3
    me.trash = [hildon]

    do, _ = _do(overlay, "OP14-109", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-109"), sickness=False))
    _drain(st, [0])
    played = [c for c in me.characters if c.card.card_id == "EB02-046"]
    assert len(played) == 1, \
        "トリガーで《スリラーバーク海賊団》キャラがトラッシュから登場していない"
    assert played[0].rested is True, "登場したキャラはレストであるべき"


# --------------------------------------------------------------------------- #
#  OP14-110 ドクトル・ホグバック (CHARACTER 黄 cost4 power5000):
#    【KO時】自分のトラッシュから「ドクトル・ホグバック」以外のコスト4以下の
#            【トリガー】を持つキャラカード1枚までを、 登場させる。
#    【トリガー】自トラッシュから コスト4以下の《スリラーバーク海賊団》1枚をレストで登場。
# --------------------------------------------------------------------------- #
def test_op14_110_on_ko_play_trigger_holder_ai():
    """【KO時】トラッシュのコスト4以下【トリガー】持ちキャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    ryuma = repo.get("OP14-089")  # cost3, 【トリガー】持ち
    me.trash = [ryuma]

    do, _ = _do(overlay, "OP14-110", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-110"), sickness=False))
    _drain(st, [0])
    assert any(c.card.card_id == "OP14-089" for c in me.characters), \
        "KO時に トラッシュの【トリガー】持ちキャラが登場していない"


def test_op14_110_trigger_play_from_trash_ai():
    """【トリガー】自トラッシュから《スリラーバーク海賊団》cost4以下をレストで登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("EB02-046")]  # スリラーバーク海賊団 cost3

    do, _ = _do(overlay, "OP14-110", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-110"), sickness=False))
    _drain(st, [0])
    played = [c for c in me.characters if c.card.card_id == "EB02-046"]
    assert len(played) == 1, "トリガーで《スリラーバーク海賊団》キャラが登場していない"
    assert played[0].rested is True, "登場したキャラはレストであるべき"


def test_op14_110_on_ko_human_pick():
    """人間 + トラッシュに【トリガー】持ちキャラ 複数 → play_from_trash modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP14-089"), repo.get("OP14-100")]  # 2 種【トリガー】持ち cost3

    do, _ = _do(overlay, "OP14-110", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-110"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_trash modal が立たない"
    assert "play_from_trash" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_trash 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in ("OP14-089", "OP14-100") for c in me.characters), \
        "人間が選んだ【トリガー】持ちキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP14-111 ペローナ (CHARACTER 黄 cost4 power5000):
#    【登場時】/【KO時】相手のコスト6以下のキャラ1枚までは、
#             次の相手のエンドフェイズ終了時まで、 アタックできない。
#    【トリガー】自トラッシュから コスト4以下の《スリラーバーク海賊団》1枚をレストで登場。
# --------------------------------------------------------------------------- #
def test_op14_111_on_play_set_cannot_attack_ai():
    """【登場時】相手のコスト6以下キャラを 次相手end まで アタック不可 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 ≤ 6
    opp.characters = [victim]

    do, _ = _do(overlay, "OP14-111", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-111"), sickness=True))
    _drain(st, [0])
    assert victim.cannot_attack_through_opp_turn is True, \
        "登場時に相手コスト6以下キャラが 次相手end までアタック不可になっていない"


def test_op14_111_on_ko_set_cannot_attack_ai():
    """【KO時】相手のコスト6以下キャラを 次相手end まで アタック不可 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    do, _ = _do(overlay, "OP14-111", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-111"), sickness=False))
    _drain(st, [0])
    assert victim.cannot_attack_through_opp_turn is True, \
        "KO時に相手コスト6以下キャラがアタック不可になっていない"


def test_op14_111_on_play_human_pick():
    """人間 + 相手コスト6以下キャラ 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP14-111", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-111"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.cannot_attack_through_opp_turn is True, \
        "人間が選んだ相手キャラがアタック不可になっていない"
    assert a.cannot_attack_through_opp_turn is False, \
        "選ばなかったキャラはアタック不可にならないべき"


# --------------------------------------------------------------------------- #
#  OP14-115 リンドウ (CHARACTER 黄 cost5 power5000):
#    【相手のターン中】【KO時】自分のデッキの上から1枚までを、 ライフの上に加える。
#             その後、 自分は1ダメージを受ける。
#    【トリガー】自分のリーダーが特徴《九蛇海賊団》を持つ場合、 このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op14_115_on_ko_life_then_self_damage_ai():
    """【KO時】デッキ上1枚をライフへ → 自分1ダメージ。 net: デッキ-1 / ライフ枚数不変 / トラッシュ+1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=1)  # 相手ターン中
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] * 10
    me.life = [repo.get("OP01-013")] * 3
    me.trash = []

    deck_before, life_before, trash_before = len(me.deck), len(me.life), len(me.trash)
    do, _ = _do(overlay, "OP14-115", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-115"), sickness=False))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 1, \
        f"デッキ上1枚がライフへ移っていない: {len(me.deck)}"
    assert len(me.life) == life_before, \
        f"ライフ+1 → 1ダメージ で ライフ枚数は不変であるべき: {len(me.life)}"
    assert len(me.trash) == trash_before + 1, \
        f"1ダメージでライフ上1枚がトラッシュへ移っていない: {len(me.trash)}"


def test_op14_115_trigger_play_self_when_kyuja_leader_ai():
    """【トリガー】《九蛇海賊団》リーダーで 自身を登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-038", overlay)  # ボア・ハンコック (九蛇海賊団)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.hand = [repo.get("OP14-115")]
    st.current_source_card_id = "OP14-115"

    do, eff = _do(overlay, "OP14-115", "trigger")
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "《九蛇海賊団》リーダーで トリガー条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card.card_id == "OP14-115" for c in me.characters), \
        "トリガーでリンドウが登場していない"


def test_op14_115_trigger_condition_false_non_kyuja_leader():
    """非《九蛇海賊団》リーダーでは トリガー条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (非 九蛇)
    me = st.players[0]
    _, eff = _do(overlay, "OP14-115", "trigger")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "非《九蛇海賊団》リーダーで トリガー条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP14-116 炎の蛇神 (EVENT 黄 cost4):
#    【カウンター】自分のリーダーかキャラ1枚までを、 このバトル中、 パワー+2000。
#             その後、 自分の手札からコスト4以下の、 特徴《アマゾン・リリー》か
#             《九蛇海賊団》を持つキャラカード1枚までを、 登場させる。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op14_116_counter_pump_and_play_from_hand_ai():
    """【カウンター】自リーダー+2000 → 手札のアマゾン/九蛇 cost4以下を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-038", overlay)  # ボア・ハンコック
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP14-113")]  # マーガレット アマゾン・リリー cost3

    power_before = me.leader.power
    do, _ = _do(overlay, "OP14-116", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 2000, \
        f"カウンター +2000 が自リーダーに反映されていない: {me.leader.power}"
    assert any(c.card.card_id == "OP14-113" for c in me.characters), \
        "手札のアマゾン・リリーキャラが登場していない"


def test_op14_116_trigger_draw_ai():
    """【トリガー】カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("OP01-016")] * 5

    do, _ = _do(overlay, "OP14-116", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == 1, "トリガーの draw が起きていない"


# --------------------------------------------------------------------------- #
#  OP14-117 欠片蝙蝠 (EVENT 黄 cost1):
#    【カウンター】自分の特徴《スリラーバーク海賊団》を持つ、 リーダーかキャラ1枚までを、
#             このバトル中、 パワー+3000。
#    【トリガー】自トラッシュから コスト4以下の《スリラーバーク海賊団》1枚をレストで登場。
# --------------------------------------------------------------------------- #
def test_op14_117_counter_pump_thriller_leader_ai():
    """【カウンター】《スリラーバーク海賊団》リーダーを +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-080", overlay)  # ゲッコー・モリア (スリラーバーク海賊団)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP14-117", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"カウンター +3000 が《スリラーバーク》リーダーに反映されていない: {me.leader.power}"


def test_op14_117_trigger_play_from_trash_ai():
    """【トリガー】自トラッシュから《スリラーバーク海賊団》cost4以下をレストで登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("EB02-046")]  # スリラーバーク海賊団 cost3

    do, _ = _do(overlay, "OP14-117", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    played = [c for c in me.characters if c.card.card_id == "EB02-046"]
    assert len(played) == 1, "トリガーで《スリラーバーク海賊団》キャラが登場していない"
    assert played[0].rested is True, "登場したキャラはレストであるべき"


# --------------------------------------------------------------------------- #
#  OP14-118 わらわ　こわい…♡ (EVENT 黄 cost1):
#    【カウンター】自分のライフが2枚以下の場合、 相手のアクティブのキャラ1枚までは、
#             このターン中、 アタックできない。
#    【トリガー】自分の手札からパワー6000以下の【トリガー】を持つキャラカード1枚までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op14_118_counter_set_cannot_attack_ai():
    """【カウンター】自ライフ2以下で 相手アクティブキャラをアタック不可 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016")] * 2  # ライフ2 (= 条件成立)
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    victim.rested = False  # アクティブ
    opp.characters = [victim]

    do, eff = _do(overlay, "OP14-118", "counter")
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "自ライフ2以下で カウンター条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.cannot_attack_until_turn_end is True, \
        "相手アクティブキャラが このターン中アタック不可になっていない"


def test_op14_118_counter_condition_false_life3():
    """自ライフ3枚では カウンター条件が不成立 (= 2枚以下でない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.life = [repo.get("OP01-016")] * 3
    _, eff = _do(overlay, "OP14-118", "counter")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "自ライフ3枚で カウンター条件が成立してはいけない"


def test_op14_118_trigger_play_from_hand_ai():
    """【トリガー】手札のP6000以下【トリガー】持ちキャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP14-100")]  # アブサロム power5000, 【トリガー】持ち

    do, _ = _do(overlay, "OP14-118", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card.card_id == "OP14-100" for c in me.characters), \
        "トリガーで手札のP6000以下【トリガー】持ちキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP14-119 ジュラキュール・ミホーク (CHARACTER 緑 cost9 power10000):
#    【自分のターン中】このキャラがレストになった時、 相手のコスト9以下のキャラ1枚までは、
#             次の相手のエンドフェイズ終了時まで、 レストにできない。
#    【相手のアタック時】【ターン1回】自分の手札1枚を捨てることができる：
#             自分のリーダーかキャラ1枚までを、 このバトル中、 パワー+2000。
# --------------------------------------------------------------------------- #
def test_op14_119_on_self_rested_set_cannot_rest_ai():
    """【自ターン中 レスト時】相手のコスト9以下キャラを レスト不能にする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 自分のターン (self_turn 成立)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 ≤ 9
    opp.characters = [victim]

    do, eff = _do(overlay, "OP14-119", "on_self_rested")
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "自分のターン中で on_self_rested 条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-119"), sickness=False))
    _drain(st, [0])
    assert victim.cannot_be_rested_buff is True, \
        "相手のコスト9以下キャラが レスト不能になっていない"


def test_op14_119_opp_attack_pump_ai():
    """【相手のアタック時】do (power_pump self_inplay +2000) が最高パワーの自軍に乗る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=1)  # 相手ターン
    me, opp = st.players[0], st.players[1]
    mihawk = InPlay.of(repo.get("OP14-119"), sickness=False)  # power10000 (最高)
    me.characters = [mihawk]

    power_before = mihawk.power
    do, _ = _do(overlay, "OP14-119", "opp_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, mihawk)
    _drain(st, [0])
    assert mihawk.power == power_before + 2000, \
        f"相手アタック時 +2000 が反映されていない: {mihawk.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP14-120 クロコダイル (CHARACTER 黒 cost8 power10000):
#    【登場時】相手のコスト9以下のキャラ1枚までは、 次の相手のエンドフェイズ終了時まで、
#             アタックできない。 その後、 相手のコスト0か8以上のキャラがいる場合、 カード1枚を引く。
#    【KO時】自分の手札1枚を捨てることができる：このキャラカードをトラッシュから登場させる。
# --------------------------------------------------------------------------- #
def test_op14_120_on_play_cannot_attack_and_conditional_draw_ai():
    """【登場時】相手コスト9以下キャラをアタック不可 → コスト8以上キャラ存在で1ドロー (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get("EB04-013"), sickness=False)  # cost8 (≤9 かつ ≥8)
    opp.characters = [big]
    me.hand = []
    me.deck = [repo.get("OP01-016")] * 5

    do, _ = _do(overlay, "OP14-120", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-120"), sickness=True))
    _drain(st, [0])
    assert big.cannot_attack_through_opp_turn is True, \
        "登場時に相手コスト9以下キャラがアタック不可になっていない"
    assert len(me.hand) == 1, \
        "相手にコスト8以上キャラがいるのに 1ドローが起きていない"


def test_op14_120_on_play_no_draw_without_cost0_or_ge8():
    """相手にコスト0/8以上キャラが不在なら 1ドローは起きない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    normal = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (0でも8以上でもない)
    opp.characters = [normal]
    me.hand = []
    me.deck = [repo.get("OP01-016")] * 5

    do, _ = _do(overlay, "OP14-120", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-120"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 0, \
        "コスト0/8以上キャラ不在なのに 1ドローが起きている"


def test_op14_120_on_ko_play_self_from_trash_ai():
    """【KO時】自身をトラッシュから登場させる (AI 自動、 コスト手札1捨ては別途 gate)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP14-120")]  # トラッシュにクロコダイル
    me.characters = []
    st.current_source_card_id = "OP14-120"

    do, _ = _do(overlay, "OP14-120", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card.card_id == "OP14-120" for c in me.characters), \
        "KO時に クロコダイルがトラッシュから登場していない"
    assert not any(c.card_id == "OP14-120" for c in me.trash), \
        "登場したクロコダイルがトラッシュから取り除かれていない"
