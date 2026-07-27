# -*- coding: utf-8 -*-
"""OP09 弾 効果 回帰テスト バックフィル (自動生成 wave 094):
OP09-033 / OP09-034 / OP09-035 / OP09-036 / OP09-037 /
OP09-039 / OP09-040 / OP09-042 / OP09-043 / OP09-044 の 10 枚
(緑 ODYSSEY レスト参照 grind + 青 クロスギルド/白ひげ サーチ・登場系)。

目的 (= test_backfill_auto_001〜093.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

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

# よく使うテスト用カード (テキストの前提固定)
_LEADER_ODYSSEY = "OP09-022"   # リム (leader、 特徴 ODYSSEY)
_LEADER_CROSSGUILD = "OP09-042"  # バギー (leader、 四皇/クロスギルド)
_ODY_BROOK = "OP10-035"        # ブルック (CHARACTER cost3 ODYSSEY/麦わらの一味)
_SB_MORIA = "PRB02-013"        # ゲッコー・モリア (王下七武海/スリラーバーク海賊団)
_WANO = "EB01-018"             # ワノ国 特徴の CHARACTER
_CG_ALBIDA1 = "EB03-021"       # アルビダ (クロスギルド cost4)
_CG_ALBIDA2 = "OP12-042"       # アルビダ (クロスギルド cost4、 別レギュ)
_FILLER = "OP01-013"           # サンジ cost2 power3000 (vanilla、 埋め用)
_SMALL = "OP01-016"            # ナミ cost1 power2000 (vanilla)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]


def _rested(repo, n, cid=_FILLER):
    """レストの vanilla キャラ n 体 (レスト参照条件のパディング用)。"""
    out = []
    for _ in range(n):
        c = InPlay.of(repo.get(cid), sickness=False)
        c.rested = True
        out.append(c)
    return out


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op09_wave094_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP09-033", "OP09-034", "OP09-035", "OP09-036", "OP09-037",
           "OP09-039", "OP09-040", "OP09-042", "OP09-043", "OP09-044"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP09-033 ニコ・ロビン: 【登場時】自レストキャラ2枚以上で 自 ODYSSEY/麦わらの一味
#            すべては 次の相手ターン終了時まで 効果でKOされない
# --------------------------------------------------------------------------- #
def test_op09_033_robin_on_play_ko_immune_ai():
    """【登場時】レストキャラ2枚以上 → ODYSSEY/麦 キャラに KO 耐性 (次相手ターン終了時まで)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = _rested(repo, 2)  # レストキャラ 2 (条件成立)
    ody = InPlay.of(repo.get(_ODY_BROOK), sickness=False)  # ODYSSEY/麦
    plain = InPlay.of(repo.get(_CG_ALBIDA1), sickness=False)  # クロスギルド (非 ODYSSEY/麦)
    me.characters += [ody, plain]

    eff = _eff(overlay, "OP09-033", "on_play")
    assert eff.get("if", {}).get("self_rested_chara_count_ge") == 2, \
        "on_play の条件 self_rested_chara_count_ge=2 が overlay に無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-033"), sickness=True))

    assert ody.ko_immune_through_opp_turn is True, \
        "ODYSSEY/麦 キャラに KO 耐性 (through_opp_turn) が付いていない"
    assert plain.ko_immune_through_opp_turn is not True, \
        "非 ODYSSEY/麦 キャラに KO 耐性が付いてはいけない"


# --------------------------------------------------------------------------- #
#  OP09-034 ペローナ: 【登場時】デッキ上5枚から スリラーバーク海賊団/ミホーク 1枚公開手札
#                     → 残りデッキ下 → 手札1枚捨てる
# --------------------------------------------------------------------------- #
def test_op09_034_perona_on_play_search_ai():
    """【登場時】上5枚に スリラーバーク海賊団 (モリア) → 公開して手札に加える (search 部)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SB_MORIA)] + [repo.get(_FILLER)] * 20
    me.hand = []

    search_prim = _eff(overlay, "OP09-034", "on_play")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-034"), sickness=True))
    assert any(c.card_id == _SB_MORIA for c in me.hand), \
        "デッキ上5枚から スリラーバーク海賊団 が手札に加わっていない"


def test_op09_034_perona_on_play_discard_ai():
    """【登場時】search 後の 手札1枚捨て (trash_self_hand_random) で 手札が 1 枚減る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_SMALL)]

    hand_before = len(me.hand)
    discard_prim = _eff(overlay, "OP09-034", "on_play")["do"][1]
    execute_effect(discard_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-034"), sickness=True))
    assert len(me.hand) == hand_before - 1, \
        f"手札1枚捨てが起きていない: {len(me.hand)} (before {hand_before})"


def test_op09_034_perona_on_play_search_human_pick():
    """人間 + 上5枚に該当 複数 → search_top_n modal が立ち resolve で手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SB_MORIA), repo.get(_FILLER), repo.get(_SB_MORIA)] \
        + [repo.get(_FILLER)] * 15
    me.hand = []

    search_prim = _eff(overlay, "OP09-034", "on_play")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-034"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id == _SB_MORIA for c in me.hand), \
        "人間が選んだ スリラーバーク海賊団 が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP09-035 ポートガス・D・エース: 【登場時】自レストキャラ2枚以上で
#            相手のコスト5以下キャラ1枚までを レストにする
# --------------------------------------------------------------------------- #
def test_op09_035_ace_on_play_rest_opp_ai():
    """【登場時】レストキャラ2枚以上 → 相手コスト5以下キャラ1体を レスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = _rested(repo, 2)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (5以下)
    opp.characters = [victim]

    eff = _eff(overlay, "OP09-035", "on_play")
    assert eff.get("if", {}).get("self_rested_chara_count_ge") == 2, \
        "on_play の条件 self_rested_chara_count_ge=2 が overlay に無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-035"), sickness=True))
    assert victim.rested is True, "相手コスト5以下キャラが レストされていない"


def test_op09_035_ace_on_play_rest_human_pick():
    """人間 + 相手コスト5以下 複数 → target_pick modal で 1 体を レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = _rested(repo, 2)
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # power 3000
    b = InPlay.of(repo.get(_SMALL), sickness=False)    # power 2000
    opp.characters = [a, b]

    eff = _eff(overlay, "OP09-035", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-035"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"

    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [bi])
        guard += 1
    assert b.rested is True, "人間が選んだキャラが レストされていない"
    assert a.rested is False, "選ばなかったキャラは アクティブのままのはず"


# --------------------------------------------------------------------------- #
#  OP09-036 モンキー・D・ルフィ: 【登場時】自レストキャラ2枚以上で
#            相手のコスト6以下キャラ1枚かドン1枚までを レストにする
#  overlay 修正: {"rest": "one_opp_chara_or_don_cost_le_6"} という非標準 string form を
#     既存の標準 dict form {"rest": {"type": "one_opp_chara_or_don", "cost_le": 6}} に正規化
#     (= engine が既に cost_le 分岐で対応済、 他 4 カードが同 dict form を使用)。
#     「相手のコスト6以下のキャラ1枚かドン1枚までをレストにする」 を公式テキスト忠実に表現。
# --------------------------------------------------------------------------- #
def test_op09_036_luffy_on_play_rest_opp_chara_or_don():
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = _rested(repo, 2)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]
    eff = _eff(overlay, "OP09-036", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-036"), sickness=True))
    assert victim.rested is True


# --------------------------------------------------------------------------- #
#  OP09-037 リム: 【登場時】デッキ上5枚から リム以外の ODYSSEY 1枚公開手札 → 残りデッキ下
#           【自分のターン終了時】自レストキャラ3枚以上で このキャラをアクティブに
# --------------------------------------------------------------------------- #
def test_op09_037_rim_on_play_search_ai():
    """【登場時】上5枚に ODYSSEY (ブルック) → 手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_ODY_BROOK)] + [repo.get(_FILLER)] * 20
    me.hand = []

    eff = _eff(overlay, "OP09-037", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-037"), sickness=True))
    assert any(c.card_id == _ODY_BROOK for c in me.hand), \
        "デッキ上5枚から ODYSSEY キャラが手札に加わっていない"


def test_op09_037_rim_end_of_turn_untap_self_ai():
    """【ターン終了時】レストキャラ3枚以上 → このキャラ (リム) 自身をアクティブに。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    rim = InPlay.of(repo.get("OP09-037"), sickness=False)
    rim.rested = True
    me.characters = _rested(repo, 3) + [rim]  # 他レストキャラ 3

    eff = _eff(overlay, "OP09-037", "end_of_turn")
    assert eff.get("if", {}).get("self_rested_chara_count_ge") == 3, \
        "end_of_turn の条件 self_rested_chara_count_ge=3 が overlay に無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, rim)
    assert rim.rested is False, "ターン終了時に自身がアクティブ化されていない"


# --------------------------------------------------------------------------- #
#  OP09-039 ゴムゴムの「四本樹」…: EVENT
#   【カウンター】自リーダー ODYSSEY + 自レストキャラ2枚以上で 自リーダー/キャラ1枚 +2000
#   【トリガー】相手のレストのコスト4以下キャラ1枚までを KO
# --------------------------------------------------------------------------- #
def test_op09_039_counter_pump_ai():
    """【カウンター】自リーダー (既定) を このターン +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]

    lp = me.leader.power
    eff = _eff(overlay, "OP09-039", "counter", needle="power_pump")
    assert eff.get("if", {}).get("leader_feature") == "ODYSSEY", \
        "counter の条件 leader_feature=ODYSSEY が overlay に無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == lp + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op09_039_trigger_ko_rested_ai():
    """【トリガー】相手のレストのコスト4以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    victim.rested = True
    opp.characters = [victim]

    eff = _eff(overlay, "OP09-039", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert victim not in opp.characters, "相手のレストコスト4以下キャラが KO されていない"


def test_op09_039_trigger_ko_active_not_target():
    """アクティブ (非レスト) の相手キャラは トリガー KO の対象外 → 残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    eff = _eff(overlay, "OP09-039", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (レスト限定)"


def test_op09_039_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の target_pick modal で キャラを選ぶ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    eff = _eff(overlay, "OP09-039", "counter", needle="power_pump")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    fi = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    fb = friend.power
    resolve_pending_choice(st, [fi])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [fi])
        guard += 1
    assert friend.power == fb + 2000, "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP09-040 雷光槍…: EVENT
#   【メイン】自レストキャラ2枚以上で 相手のコスト4以下キャラ1枚までを KO
#   【トリガー】相手のコスト4以下キャラ1枚までを レストにする
# --------------------------------------------------------------------------- #
def test_op09_040_main_ko_ai():
    """【メイン】相手コスト4以下キャラ1体を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    eff = _eff(overlay, "OP09-040", "main")
    assert eff.get("if", {}).get("self_rested_chara_count_ge") == 2, \
        "main の条件 self_rested_chara_count_ge=2 が overlay に無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert victim not in opp.characters, "相手コスト4以下キャラが KO されていない"


def test_op09_040_trigger_rest_ai():
    """【トリガー】相手コスト4以下キャラ1体を レスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    eff = _eff(overlay, "OP09-040", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert victim.rested is True, "相手コスト4以下キャラが レストされていない"


def test_op09_040_main_ko_human_pick():
    """人間 + 相手コスト4以下 複数 → target_pick modal で 1 体を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_SMALL), sickness=False)
    opp.characters = [a, b]

    eff = _eff(overlay, "OP09-040", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"

    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [bi])
        guard += 1
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP09-042 バギー (LEADER): 【起動メイン】自ドン5レスト + 手札1捨て で
#            手札から クロスギルド キャラ1枚までを 登場
# --------------------------------------------------------------------------- #
def test_op09_042_buggy_activate_main_play_cg_ai():
    """起動メイン: コスト (ドン5レスト + 手札1捨て) → 手札から クロスギルド を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    # クロスギルド キャラ (高価値) + 低価値 fodder (= discard コストで fodder が捨てられる)。
    me.hand = [repo.get(_CG_ALBIDA1), repo.get(_SMALL)]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP09-042"]
    assert len(opts) == 1, f"OP09-042 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert any(c.card.card_id == _CG_ALBIDA1 for c in me.characters), \
        "手札から クロスギルド キャラが登場していない"
    assert me.don_active == 0 and me.don_rested == 5, \
        f"コストでドン5枚がレストされるべき: active={me.don_active} rested={me.don_rested}"


def test_op09_042_buggy_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    me.hand = [repo.get(_CG_ALBIDA1), repo.get(_SMALL)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP09-042"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP09-042"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op09_042_buggy_activate_main_human_flow():
    """人間 actor: 手札1捨ての discard_pick modal が立ち、 解決で クロスギルド を登場まで流せる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    # クロスギルド 2 種 + fodder → 捨てと登場の選択が発生
    me.hand = [repo.get(_CG_ALBIDA1), repo.get(_CG_ALBIDA2), repo.get(_SMALL)]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP09-042"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 で 手札捨て 選択 modal が立たない"
    assert st.pending_choice.get("kind") == "activate_main_discard_pick", \
        f"kind が activate_main_discard_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭を捨てる
    guard = 0
    while st.pending_choice is not None and guard < 8:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any("クロスギルド" in (c.card.features or "") for c in me.characters), \
        "人間解決後 クロスギルド キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP09-043 アルビダ: 【KO時】自リーダー クロスギルド なら 手札から アルビダ以外の
#            コスト5以下キャラ1枚までを 登場
# --------------------------------------------------------------------------- #
def test_op09_043_albida_on_ko_play_from_hand_ai():
    """【KO時】(クロスギルド leader) 手札の コスト5以下キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)  # バギー = クロスギルド leader
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # cost2 CHARACTER (アルビダ以外)

    eff = _eff(overlay, "OP09-043", "on_ko")
    assert eff.get("if", {}).get("leader_feature") == "クロスギルド", \
        "on_ko の条件 leader_feature=クロスギルド が overlay に無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)  # KO 済 = self_inplay None
    assert any(c.card.card_id == _FILLER for c in me.characters), \
        "手札から コスト5以下キャラが登場していない"


def test_op09_043_albida_on_ko_human_pick():
    """人間 + 手札に コスト5以下 複数 → play_from_hand_pick modal で 1 枚を登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_SMALL)]

    eff = _eff(overlay, "OP09-043", "on_ko")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.card_id in (_FILLER, _SMALL) for c in me.characters), \
        "人間が選んだ コスト5以下キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP09-044 イゾウ: 【アタック時】デッキ上5枚から ワノ国/白ひげ海賊団 1枚公開手札
#           → 残りデッキ下 → 手札1枚捨てる
# --------------------------------------------------------------------------- #
def test_op09_044_izou_on_attack_search_ai():
    """【アタック時】上5枚に ワノ国 → 手札に加える (search 部)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WANO)] + [repo.get(_FILLER)] * 20
    me.hand = []

    search_prim = _eff(overlay, "OP09-044", "on_attack")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-044"), sickness=False))
    assert any(c.card_id == _WANO for c in me.hand), \
        "デッキ上5枚から ワノ国 カードが手札に加わっていない"


def test_op09_044_izou_on_attack_discard_ai():
    """【アタック時】search 後の 手札1枚捨て で 手札が 1 枚減る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_SMALL)]

    hand_before = len(me.hand)
    discard_prim = _eff(overlay, "OP09-044", "on_attack")["do"][1]
    execute_effect(discard_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-044"), sickness=False))
    assert len(me.hand) == hand_before - 1, \
        f"手札1枚捨てが起きていない: {len(me.hand)} (before {hand_before})"


def test_op09_044_izou_on_attack_search_human_pick():
    """人間 + 上5枚に ワノ国 複数 → search_top_n modal が立ち resolve で手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WANO), repo.get(_FILLER), repo.get(_WANO)] \
        + [repo.get(_FILLER)] * 15
    me.hand = [repo.get(_FILLER)]

    search_prim = _eff(overlay, "OP09-044", "on_attack")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-044"), sickness=False))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id == _WANO for c in me.hand), \
        "人間が選んだ ワノ国 カードが手札に加わっていない"
