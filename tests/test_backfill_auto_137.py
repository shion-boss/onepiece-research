# -*- coding: utf-8 -*-
"""OP14 弾 効果 回帰テスト バックフィル (自動生成 wave 137):
OP14-087 / OP14-089 / OP14-090 / OP14-091 / OP14-092 / OP14-097 /
OP14-098 / OP14-099 / OP14-100 / OP14-106 の 10 枚。

目的 (= test_backfill_auto_001〜136.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 検索 を 持つカードは 人間 actor で pending_choice が
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
    try_replace_ko,
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
def test_all_op14_wave137_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP14-087", "OP14-089", "OP14-090", "OP14-091", "OP14-092",
           "OP14-097", "OP14-098", "OP14-099", "OP14-100", "OP14-106"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP14-087 ミス・バレンタイン(ミキータ) (CHARACTER 黒 cost1 power2000):
#    【登場時】自リーダーが《B・W》なら デッキ上4枚を見て 自身以外の《B・W》1枚を
#             手札に加え、 残りをトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op14_087_on_play_search_bw_ai():
    """【登場時】《B・W》リーダーで デッキ上4枚から《B・W》キャラを手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay)  # クロコダイル (王下七武海/B・W)
    me, opp = st.players[0], st.players[1]
    bw = repo.get("EB03-047")  # ミス・バレンタイン B・W cost2
    me.deck = [bw] + [repo.get("OP01-016")] * 20
    me.hand = []

    do, eff = _do(overlay, "OP14-087", "on_play")
    assert eff.get("if", {}).get("leader_features_any") == ["B・W"], \
        "overlay の leader_features_any=[B・W] ゲートが無い"
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "B・W リーダーで登場時条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-087"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == "EB03-047" for c in me.hand), \
        "デッキ上4枚から《B・W》キャラが手札に加わっていない"


def test_op14_087_on_play_condition_false_non_bw_leader():
    """非《B・W》リーダーでは登場時条件が不成立 (= 効果不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (非 B・W)
    me = st.players[0]
    _, eff = _do(overlay, "OP14-087", "on_play")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "非 B・W リーダーで登場時条件が成立してはいけない"


def test_op14_087_on_play_search_human_pick():
    """人間 + デッキ上4枚に《B・W》複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST03-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    bw = repo.get("EB03-047")
    me.deck = [bw, repo.get("OP01-016"), bw] + [repo.get("OP01-016")] * 15
    me.hand = []

    do, _ = _do(overlay, "OP14-087", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-087"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (B・W) を選択
    _drain(st, [])
    assert any(c.card_id == "EB03-047" for c in me.hand), \
        "人間が選んだ《B・W》キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP14-089 リューマ (CHARACTER 黒 cost3 power5000):
#    【KO時】カード2枚を引き、 自分の手札2枚を捨てる。
#    【トリガー】自分のトラッシュから コスト4以下の《スリラーバーク海賊団》
#               キャラ1枚までを、 レストで登場させる。
# --------------------------------------------------------------------------- #
def test_op14_089_on_ko_draw2_discard2_ai():
    """【KO時】2枚引いて手札2枚捨てる → 手札 net±0 / デッキ-2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] * 10
    me.hand = [repo.get("OP01-016")] * 3

    hand_before, deck_before = len(me.hand), len(me.deck)
    do, _ = _do(overlay, "OP14-089", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-089"), sickness=False))
    _drain(st, [0])
    assert len(me.hand) == hand_before, \
        f"KO時 (+2ドロー -2捨て) で手札 net が ±0 でない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, \
        f"KO時の 2 ドローでデッキが2枚減っていない: {len(me.deck)}"


def test_op14_089_trigger_play_from_trash_ai():
    """【トリガー】自トラッシュから《スリラーバーク海賊団》cost4以下をレストで登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hildon = repo.get("EB02-046")  # ヒルドン スリラーバーク海賊団 cost3
    me.trash = [hildon]

    do, _ = _do(overlay, "OP14-089", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-089"), sickness=False))
    _drain(st, [0])
    played = [c for c in me.characters if c.card.card_id == "EB02-046"]
    assert len(played) == 1, \
        "トリガーで《スリラーバーク海賊団》キャラがトラッシュから登場していない"
    assert played[0].rested is True, "登場したキャラはレストであるべき"


# --------------------------------------------------------------------------- #
#  OP14-090 Mr.1(ダズ・ボーネス) (CHARACTER 黒 cost5 power6000):
#    コスト0か8以上のキャラがいる場合、 このキャラは登場ターンにキャラへアタックできる。
#    【登場時】相手の現在コスト0のキャラ1枚までを、 レストにする。
# --------------------------------------------------------------------------- #
def test_op14_090_static_rush_chara_when_big_exists():
    """静的: コスト8以上のキャラがいると 自身に【速攻：キャラ】が付与される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    dazu = InPlay.of(repo.get("OP14-090"), sickness=False)
    big = InPlay.of(repo.get("EB04-013"), sickness=False)  # cost8
    me.characters = [dazu, big]

    evaluate_static_effects(st, overlay)
    assert "速攻：キャラ" in dazu.static_granted_keywords, \
        "コスト8以上のキャラ存在時に【速攻：キャラ】が付与されていない"
    assert dazu.is_rush_chara_only_now is True, \
        "is_rush_chara_only_now が True になっていない"


def test_op14_090_static_no_rush_without_big():
    """コスト0/8以上のキャラがいなければ【速攻：キャラ】は付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    dazu = InPlay.of(repo.get("OP14-090"), sickness=False)
    me.characters = [dazu]  # 通常コストのみ

    evaluate_static_effects(st, overlay)
    assert "速攻：キャラ" not in dazu.static_granted_keywords, \
        "条件不成立なのに【速攻：キャラ】が付与されている"


def test_op14_090_on_play_rest_cost0_ai():
    """【登場時】相手の現在コスト0キャラをレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    victim.base_cost_override = 0  # 現在コスト0 (= リーダー効果で下げられた想定)
    opp.characters = [victim]
    assert victim.base_cost == 0

    do, _ = _do(overlay, "OP14-090", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-090"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, "登場時に相手の現在コスト0キャラがレストされていない"


def test_op14_090_on_play_rest_human_pick():
    """人間 + 相手の現在コスト0キャラ 複数 → target_pick modal が立ち resolve でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    a.base_cost_override = 0
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    b.base_cost_override = 0
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP14-090", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-090"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだキャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP14-091 Mr.2・ボン・クレー(ベンサム) (CHARACTER 黒 cost4 power5000):
#    【KO時】自分の手札かトラッシュから 自身以外のコスト5以下の《B・W》
#            キャラ1枚までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op14_091_on_ko_play_from_hand_or_trash_ai():
    """【KO時】手札の《B・W》cost5以下キャラを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB03-047")]  # ミス・バレンタイン B・W cost2

    do, _ = _do(overlay, "OP14-091", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-091"), sickness=False))
    _drain(st, [0])
    assert any(c.card.card_id == "EB03-047" for c in me.characters), \
        "KO時に手札の《B・W》キャラが登場していない"
    assert not any(c.card_id == "EB03-047" for c in me.hand), \
        "登場した《B・W》キャラが手札から取り除かれていない"


def test_op14_091_on_ko_human_pick():
    """人間 + 手札に《B・W》cost5以下 複数 → play_from_hand_or_trash modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB03-047"), repo.get("EB03-046")]  # 2 種 B・W

    do, _ = _do(overlay, "OP14-091", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-091"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert "play_from_hand_or_trash" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand_or_trash 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭を選択
    _drain(st, [0])
    assert any(c.card.card_id in ("EB03-047", "EB03-046")
               for c in me.characters), \
        "人間が選んだ《B・W》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP14-092 Mr.3(ギャルディーノ) (CHARACTER 黒 cost4 power6000):
#    【相手のターン中】【ターン1回】このキャラがKOされる場合、 代わりに
#    自分のトラッシュからカード3枚を好きな順番でデッキの下に置くことができる。
# --------------------------------------------------------------------------- #
def test_op14_092_replace_ko_trash_to_deck_do():
    """replace_ko の do (trash_to_deck limit3 to bottom) がトラッシュ3枚をデッキ下へ移す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP01-016")] * 5
    me.deck = [repo.get("OP01-013")] * 3

    trash_before, deck_before = len(me.trash), len(me.deck)
    do, eff = _do(overlay, "OP14-092", "replace_ko")
    assert eff.get("if", {}).get("opp_turn") is True, \
        "overlay の【相手のターン中】(opp_turn) ゲートが無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-092"), sickness=False))
    assert len(me.trash) == trash_before - 3, \
        f"トラッシュが3枚減っていない: {len(me.trash)}"
    assert len(me.deck) == deck_before + 3, \
        f"デッキ下に3枚加わっていない: {len(me.deck)}"


def test_op14_092_replace_ko_ai_opp_turn():
    """相手ターン中に効果KOされる時、 AI が置換を選び 自身が場に残る (trash→デッキ下)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=1)  # 相手 (P1) のターン
    me, opp = st.players[0], st.players[1]
    giro = InPlay.of(repo.get("OP14-092"), sickness=False)
    me.characters = [giro]
    me.trash = [repo.get("OP01-016")] * 5

    replaced = try_replace_ko(
        st, me, opp, giro, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "相手ターン + トラッシュ3枚で KO 置換が成立していない"
    assert giro in me.characters, "置換成立時 ギャルディーノは場に残るべき"


# --------------------------------------------------------------------------- #
#  OP14-097 早くおれを海賊王にならせろ!!! (EVENT 黒 cost1):
#    【メイン】デッキ上3枚を見て 自身以外の《スリラーバーク海賊団》1枚を手札、 残りtrash。
# --------------------------------------------------------------------------- #
def test_op14_097_main_search_thriller_ai():
    """【メイン】デッキ上3枚から《スリラーバーク海賊団》を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hildon = repo.get("EB02-046")  # スリラーバーク海賊団
    me.deck = [hildon] + [repo.get("OP01-016")] * 20
    me.hand = []

    do, _ = _do(overlay, "OP14-097", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card_id == "EB02-046" for c in me.hand), \
        "デッキ上3枚から《スリラーバーク海賊団》カードが手札に加わっていない"


def test_op14_097_main_search_human_pick():
    """人間 + デッキ上3枚に《スリラーバーク海賊団》複数 → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hildon = repo.get("EB02-046")
    me.deck = [hildon, repo.get("OP01-016"), hildon] + [repo.get("OP01-016")] * 15
    me.hand = []

    do, _ = _do(overlay, "OP14-097", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id == "EB02-046" for c in me.hand), \
        "人間が選んだ《スリラーバーク海賊団》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP14-098 三日月形砂丘 (EVENT 黒 cost1):
#    【メイン】コスト0か8以上のキャラがいる場合、 自分の《B・W》キャラすべてを、
#             次の相手のエンドフェイズ終了時まで、 コスト+3。
#    【カウンター】自分のリーダーを、 このバトル中、 パワー+3000。
# --------------------------------------------------------------------------- #
def test_op14_098_main_cost_up_bw_ai():
    """【メイン】コスト8以上キャラ存在時、 自分の《B・W》キャラすべて コスト+3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bwc_def = repo.get("EB03-047")  # B・W cost2
    bwc = InPlay.of(bwc_def, sickness=False)
    big = InPlay.of(repo.get("EB04-013"), sickness=False)  # cost8 (条件成立用)
    me.characters = [bwc, big]

    do, eff = _do(overlay, "OP14-098", "main")
    assert eff.get("if", {}).get("exists_chara_cost_0_or_ge_8") is True, \
        "overlay の exists_chara_cost_0_or_ge_8 ゲートが無い"
    assert eval_condition(eff.get("if", {}), st, me) is True, \
        "コスト8以上キャラ存在で条件が成立していない"
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert bwc.base_cost == bwc_def.cost + 3, \
        f"《B・W》キャラのコスト+3 が反映されていない: {bwc.base_cost} (base {bwc_def.cost})"


def test_op14_098_main_condition_false_no_big():
    """コスト0/8以上キャラが不在なら【メイン】効果条件が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    bwc = InPlay.of(repo.get("EB03-047"), sickness=False)  # cost2 のみ
    me.characters = [bwc]
    _, eff = _do(overlay, "OP14-098", "main")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "コスト0/8以上キャラ不在なのに条件が成立している"


def test_op14_098_counter_pump_leader_ai():
    """【カウンター】自リーダーを このバトル中 +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP14-098", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンター +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP14-099 不服か？ (EVENT 黒 cost1):
#    【メイン】デッキ上3枚を見て 自身以外の《B・W》1枚を手札、 残りtrash。
# --------------------------------------------------------------------------- #
def test_op14_099_main_search_bw_ai():
    """【メイン】デッキ上3枚から《B・W》キャラを手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB03-047")] + [repo.get("OP01-016")] * 20
    me.hand = []

    do, _ = _do(overlay, "OP14-099", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card_id == "EB03-047" for c in me.hand), \
        "デッキ上3枚から《B・W》キャラが手札に加わっていない"


def test_op14_099_main_search_human_pick():
    """人間 + デッキ上3枚に《B・W》複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    bw = repo.get("EB03-047")
    me.deck = [bw, repo.get("OP01-016"), bw] + [repo.get("OP01-016")] * 15
    me.hand = []

    do, _ = _do(overlay, "OP14-099", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id == "EB03-047" for c in me.hand), \
        "人間が選んだ《B・W》キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP14-100 アブサロム (CHARACTER 黄 cost3 power5000):
#    【KO時】デッキ上3枚を見て《スリラーバーク海賊団》1枚を手札、 残りをデッキ下。
#    【トリガー】自トラッシュから コスト4以下の《スリラーバーク海賊団》キャラ1枚を
#               レストで登場させる。
# --------------------------------------------------------------------------- #
def test_op14_100_on_ko_search_thriller_ai():
    """【KO時】デッキ上3枚から《スリラーバーク海賊団》を手札、 残りデッキ下 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hildon = repo.get("EB02-046")  # スリラーバーク海賊団
    me.deck = [hildon] + [repo.get("OP01-016")] * 20
    me.hand = []
    deck_before = len(me.deck)

    do, _ = _do(overlay, "OP14-100", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-100"), sickness=False))
    _drain(st, [0])
    assert any(c.card_id == "EB02-046" for c in me.hand), \
        "デッキ上3枚から《スリラーバーク海賊団》カードが手札に加わっていない"
    # 手札に1枚 (= 見た3枚のうち1枚) → デッキは残り2枚がデッキ下に戻る = net -1
    assert len(me.deck) == deck_before - 1, \
        f"手札に加えた1枚分だけデッキが減っていない: {len(me.deck)}"


def test_op14_100_on_ko_search_human_pick():
    """人間 + デッキ上3枚に《スリラーバーク海賊団》複数 → search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hildon = repo.get("EB02-046")
    me.deck = [hildon, repo.get("OP01-016"), hildon] + [repo.get("OP01-016")] * 15
    me.hand = []

    do, _ = _do(overlay, "OP14-100", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP14-100"), sickness=False))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id == "EB02-046" for c in me.hand), \
        "人間が選んだ《スリラーバーク海賊団》カードが手札に加わっていない"


def test_op14_100_trigger_play_from_trash_ai():
    """【トリガー】自トラッシュから《スリラーバーク海賊団》cost4以下をレストで登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hildon = repo.get("EB02-046")  # スリラーバーク海賊団 cost3
    me.trash = [hildon]

    do, _ = _do(overlay, "OP14-100", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-100"), sickness=False))
    _drain(st, [0])
    played = [c for c in me.characters if c.card.card_id == "EB02-046"]
    assert len(played) == 1, \
        "トリガーで《スリラーバーク海賊団》キャラがトラッシュから登場していない"
    assert played[0].rested is True, "登場したキャラはレストであるべき"


# --------------------------------------------------------------------------- #
#  OP14-106 サロメ (CHARACTER 黄 cost3 power1000):
#    【ブロッカー】。 【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op14_106_is_blocker():
    """サロメは【ブロッカー】を持つ (intrinsic)。"""
    repo = _repo()
    salome = InPlay.of(repo.get("OP14-106"), sickness=False)
    assert salome.is_blocker_now is True, "サロメが【ブロッカー】と判定されていない"


def test_op14_106_trigger_play_self_ai():
    """【トリガー】自身を登場させる (= ライフから捲れた想定、 手札から場へ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.hand = [repo.get("OP14-106")]
    st.current_source_card_id = "OP14-106"  # トリガー発動源

    do, _ = _do(overlay, "OP14-106", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card.card_id == "OP14-106" for c in me.characters), \
        "トリガーでサロメが場に登場していない"
    assert not any(c.card_id == "OP14-106" for c in me.hand), \
        "登場したサロメが手札から取り除かれていない"
