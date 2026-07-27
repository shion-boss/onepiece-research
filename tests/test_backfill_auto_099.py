# -*- coding: utf-8 -*-
"""OP09 弾 効果 回帰テスト バックフィル (自動生成 wave 099):
OP09-101 / OP09-102 / OP09-103 / OP09-104 / OP09-105 /
OP09-106 / OP09-107 / OP09-108 / OP09-109 / OP09-110 の 10 枚
(黄 革命軍 / ニコ・ロビン (紫黄) control — ライフ操作 / 手札破壊 / サーチ /
 トリガー自己登場 系)。

目的 (= test_backfill_auto_001〜098.py と同一方針):
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
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_ROBIN = "OP09-062"      # ニコ・ロビン (leader、 紫/黄。 leader_name=ニコ・ロビン)
_LEADER_REVO = "OP07-001"       # モンキー・D・ドラゴン (leader、 革命軍)
_LEADER_EGGHEAD = "OP07-097"    # ベガパンク (leader、 科学者/エッグヘッド)
_LEADER_MUGIWARA = "OP01-001"   # ロロノア・ゾロ (leader、 麦わらの一味 — 上記条件を外す用)
_FILLER = "ST01-004"            # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_SMALL = "OP01-016"             # ナミ cost1 power2000 (バニラ)
_SMALL_B = "OP01-077"           # ペローナ cost1 (バニラ、 相手キャラ 2 体目)
_REVO_CHAR = "OP05-006"         # コアラ cost2 (特徴《革命軍》、 手札登場対象)
_YELLOW_1 = "OP10-108"          # スクラッチメン・アプー cost1 (黄)
_YELLOW_3 = "OP10-114"          # X・ドレーク cost3 (黄)
_TRIGGER_CARD = "EB01-051"      # 指銃 (EVENT、 【トリガー】持ち — search filter 対象)
_TRIGGER_CARD_B = "EB01-038"    # オカマ道 (EVENT、 【トリガー】持ち 2 枚目)


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


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op09_wave099_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP09-101", "OP09-102", "OP09-103", "OP09-104", "OP09-105",
           "OP09-106", "OP09-107", "OP09-108", "OP09-109", "OP09-110"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP09-101 クザン (CHARACTER): 【登場時】相手のコスト3以下のキャラ1枚を、相手のライフの
#          上か下に表向きで置く：相手は自身の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op09_101_on_play_chara_to_life_and_discard_ai():
    """【登場時】相手コスト3以下キャラ1枚を相手ライフへ + 相手手札1枚を捨てさせる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SMALL), sickness=False)  # ナミ cost1 (≤3)
    opp.characters = [victim]
    opp.hand = [repo.get(_FILLER)] * 2

    life_before = len(opp.life)
    hand_before = len(opp.hand)
    for prim in _eff(overlay, "OP09-101", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-101"), sickness=True))
    _drain(st, [0])
    assert victim not in opp.characters, "相手コスト3以下キャラがライフへ移されていない"
    assert len(opp.life) == life_before + 1, \
        f"相手ライフが1枚増えていない: {len(opp.life)} (before {life_before})"
    assert len(opp.hand) == hand_before - 1, \
        f"相手手札が1枚捨てられていない: {len(opp.hand)} (before {hand_before})"


def test_op09_101_on_play_chara_to_life_human_pick():
    """人間 + 相手コスト3以下キャラ複数 → chara_to_opp_life の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_SMALL), sickness=False)     # cost1
    b = InPlay.of(repo.get(_SMALL_B), sickness=False)   # cost1
    opp.characters = [a, b]

    # do[1] = chara_to_opp_life (対象選択本体)
    execute_effect(_eff(overlay, "OP09-101", "on_play")["do"][1], st, me, opp,
                   InPlay.of(repo.get("OP09-101"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだ相手キャラがライフへ移されていない"
    assert a in opp.characters, "選ばなかった相手キャラは場に残るべき"


# --------------------------------------------------------------------------- #
#  OP09-102 クローバー博士 (CHARACTER): 【登場時】自リーダーが「ニコ・ロビン」の場合、
#          デッキ上3枚を見て【トリガー】を持つカード1枚までを公開し手札に加える。残りを
#          好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op09_102_on_play_search_trigger_card_ai():
    """【登場時】ニコ・ロビン leader: 上3枚から【トリガー】持ちカードを手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ROBIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_TRIGGER_CARD)] + [repo.get(_FILLER)] * 20
    me.hand = []

    for prim in _eff(overlay, "OP09-102", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-102"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == _TRIGGER_CARD for c in me.hand), \
        "上3枚から【トリガー】持ちカードが手札に加わっていない"


def test_op09_102_on_play_gated_by_leader_name():
    """自リーダーが「ニコ・ロビン」でない場合、 発火条件を満たさない (leader_name 条件)。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP09-102", "on_play")
    assert eff.get("if", {}).get("leader_name") == "ニコ・ロビン", \
        "overlay の リーダー名条件 (ニコ・ロビン) が無い"
    st_ok = _state(repo, _LEADER_ROBIN, overlay)
    assert eval_all_conditions(eff, st_ok, st_ok.players[0], None) is True, \
        "ニコ・ロビン leader で 条件が成立するべき"
    st_ng = _state(repo, _LEADER_MUGIWARA, overlay)
    assert eval_all_conditions(eff, st_ng, st_ng.players[0], None) is False, \
        "ニコ・ロビン でない leader で 条件が成立してはいけない"


def test_op09_102_on_play_search_human_pick():
    """人間 + 上3枚に【トリガー】持ち複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ROBIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_TRIGGER_CARD), repo.get(_FILLER),
               repo.get(_TRIGGER_CARD_B)] + [repo.get(_FILLER)] * 15
    me.hand = []

    execute_effect(_eff(overlay, "OP09-102", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-102"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (トリガー持ち) を選択
    _drain(st, [])
    assert any(c.card_id in (_TRIGGER_CARD, _TRIGGER_CARD_B) for c in me.hand), \
        "人間が選んだ【トリガー】持ちカードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP09-103 コアラ (CHARACTER): 【ブロッカー】【登場時】自分のライフの上か下から1枚を
#          手札に加えることができる：手札からコスト4以下の特徴《革命軍》キャラ1枚までを
#          登場させる。登場させた場合、カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_103_on_play_optional_play_revo_and_draw_ai():
    """【登場時】(任意: ライフ1→手札) 手札から 革命軍 cost4以下を登場 + 1ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = [repo.get(_REVO_CHAR)]  # コアラ cost2 (革命軍)
    me.deck = [repo.get(_FILLER)] * 10

    life_before = len(me.life)
    chars_before = len(me.characters)
    for prim in _eff(overlay, "OP09-103", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-103"), sickness=True))
    _drain(st, [0])
    assert len(me.life) == life_before - 1, \
        f"任意コストでライフ1枚が手札へ移っていない: {len(me.life)} (before {life_before})"
    assert any(c.card.card_id == _REVO_CHAR for c in me.characters), \
        "手札から 革命軍 cost4以下キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"
    # 手札 net: start 1 (+1 ライフ→手札 コスト) (-1 コアラ登場) (+1 ドロー) = 2
    assert len(me.hand) == 2, f"手札 net が合わない: {len(me.hand)}"


def test_op09_103_on_play_human_optional_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.hand = [repo.get(_REVO_CHAR)]
    me.deck = [repo.get(_FILLER)] * 10

    execute_effect(_eff(overlay, "OP09-103", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-103"), sickness=True))
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    chars_before = len(me.characters)
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert len(me.characters) == chars_before + 1, \
        "承諾後 革命軍キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP09-104 サボ (CHARACTER): 【登場時】自分の手札から特徴《革命軍》キャラ1枚までを、
#          ライフの上に表向きで加える。その後、自分のライフが2枚以上の場合、ライフの上か
#          下から1枚を手札に加える。
# --------------------------------------------------------------------------- #
def test_op09_104_on_play_hand_to_life_ai():
    """【登場時】(1) 手札の 革命軍キャラ1枚をライフの上へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = [repo.get(_REVO_CHAR)]  # 革命軍

    life_before = len(me.life)
    # do[0] = hand_to_self_life (革命軍 filter)
    execute_effect(_eff(overlay, "OP09-104", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-104"), sickness=True))
    _drain(st, [0])
    assert len(me.life) == life_before + 1, \
        f"手札の革命軍キャラがライフに加わっていない: {len(me.life)} (before {life_before})"
    assert any(c.card_id == _REVO_CHAR for c in me.life), \
        "ライフに加わったのが 革命軍キャラでない"
    assert not any(c.card_id == _REVO_CHAR for c in me.hand), \
        "ライフへ移した革命軍キャラが手札に残っている"


def test_op09_104_on_play_conditional_life_to_hand():
    """【登場時】(2) ライフ2枚以上の場合のみ、 ライフ1枚を手札へ (self_life_ge:2 gate)。"""
    repo = _repo()
    overlay = _overlay()
    do = _eff(overlay, "OP09-104", "on_play")["do"]
    # do[1] は conditional (if self_life_ge:2 → life_top_or_bottom_to_hand)
    cond = do[1].get("conditional", {})
    assert cond.get("if", {}).get("self_life_ge") == 2, \
        "overlay の 条件 self_life_ge=2 が無い"

    # ライフ2枚 → 成立: 手札+1 / ライフ-1
    st = _state(repo, _LEADER_REVO, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = []
    execute_effect(do[1], st, me, opp,
                   InPlay.of(repo.get("OP09-104"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 1 and len(me.life) == 1, \
        f"ライフ2枚で ライフ→手札 が起きていない: hand={len(me.hand)} life={len(me.life)}"

    # ライフ1枚 → 不成立: 変化なし
    st2 = _state(repo, _LEADER_REVO, overlay)
    me2, opp2 = st2.players[0], st2.players[1]
    me2.life = [repo.get(_FILLER)] * 1
    me2.hand = []
    execute_effect(do[1], st2, me2, opp2,
                   InPlay.of(repo.get("OP09-104"), sickness=True))
    _drain(st2, [0])
    assert len(me2.hand) == 0 and len(me2.life) == 1, \
        "ライフ1枚で 条件不成立のはずが 効果が起きている"


# --------------------------------------------------------------------------- #
#  OP09-105 サンジ (CHARACTER): 【トリガー】自リーダーが《エッグヘッド》なら、デッキの
#          上から1枚をライフに加え、自分の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op09_105_trigger_top_to_life_and_discard_ai():
    """【トリガー】エッグヘッド leader: デッキ上1枚をライフへ + 手札2枚を捨てる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_EGGHEAD, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 1
    me.hand = [repo.get(_FILLER)] * 3
    me.deck = [repo.get(_FILLER)] * 5

    life_before = len(me.life)
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    for prim in _eff(overlay, "OP09-105", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-105"), sickness=True))
    _drain(st, [0])
    assert len(me.life) == life_before + 1, \
        f"デッキ上1枚がライフへ加わっていない: {len(me.life)}"
    assert len(me.deck) == deck_before - 1, "デッキ上1枚が消費されていない"
    assert len(me.hand) == 1, f"手札2枚が捨てられていない: {len(me.hand)}"
    assert len(me.trash) == trash_before + 2, "捨てた手札2枚がトラッシュに置かれていない"


def test_op09_105_trigger_gated_by_leader_egghead():
    """自リーダーが《エッグヘッド》でない場合、 トリガー効果は発火条件を満たさない。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP09-105", "trigger")
    assert eff.get("if", {}).get("leader_feature") == "エッグヘッド", \
        "overlay の リーダー条件 (エッグヘッド) が無い"
    st_ok = _state(repo, _LEADER_EGGHEAD, overlay)
    assert eval_all_conditions(eff, st_ok, st_ok.players[0], None) is True, \
        "エッグヘッド leader で 条件が成立するべき"
    st_ng = _state(repo, _LEADER_MUGIWARA, overlay)
    assert eval_all_conditions(eff, st_ng, st_ng.players[0], None) is False, \
        "エッグヘッド でない leader で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP09-106 ニコ・オルビア (CHARACTER): 【登場時】自リーダーが「ニコ・ロビン」の場合、
#          自分のリーダーの「ニコ・ロビン」1枚までを、このターン中、パワー+3000。
# --------------------------------------------------------------------------- #
def test_op09_106_on_play_leader_pump_ai():
    """【登場時】ニコ・ロビン leader: 自リーダーを このターン中 パワー+3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ROBIN, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "OP09-106", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-106"), sickness=True))
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"自リーダーへの +3000 が反映されていない: {me.leader.power} (before {power_before})"


def test_op09_106_on_play_gated_by_leader_name():
    """自リーダーが「ニコ・ロビン」でない場合、 発火条件を満たさない (leader_name 条件)。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP09-106", "on_play")
    assert eff.get("if", {}).get("leader_name") == "ニコ・ロビン", \
        "overlay の リーダー名条件 (ニコ・ロビン) が無い"
    st_ng = _state(repo, _LEADER_MUGIWARA, overlay)
    assert eval_all_conditions(eff, st_ng, st_ng.players[0], None) is False, \
        "ニコ・ロビン でない leader で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP09-107 ニコ・ロビン (CHARACTER): 【登場時】相手のライフが3枚以上の場合、相手の
#          ライフの上から1枚までを、トラッシュに置く。 【トリガー】自分の手札からコスト3
#          以下の黄のキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op09_107_on_play_mill_opp_life_ai():
    """【登場時】相手ライフ3枚以上 → 相手ライフの上1枚をトラッシュへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3

    life_before = len(opp.life)
    trash_before = len(opp.trash)
    for prim in _eff(overlay, "OP09-107", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-107"), sickness=True))
    _drain(st, [0])
    assert len(opp.life) == life_before - 1, \
        f"相手ライフの上1枚がトラッシュへ移されていない: {len(opp.life)}"
    assert len(opp.trash) == trash_before + 1, \
        "捨てた相手ライフがトラッシュに置かれていない"


def test_op09_107_on_play_gated_by_opp_life():
    """相手ライフが2枚 (< 3) では【登場時】効果の条件を満たさない (opp_life_ge:3)。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP09-107", "on_play")
    assert eff.get("if", {}).get("opp_life_ge") == 3, \
        "overlay の 条件 opp_life_ge=3 が無い"
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 2
    assert eval_all_conditions(eff, st, me, None) is False, \
        "相手ライフ2枚で 条件が成立してはいけない"
    opp.life = [repo.get(_FILLER)] * 3
    assert eval_all_conditions(eff, st, me, None) is True, \
        "相手ライフ3枚で 条件が成立するべき"


def test_op09_107_trigger_play_yellow_human_pick():
    """【トリガー】人間 + 手札にコスト3以下の黄キャラ複数 → play_from_hand_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_YELLOW_1), repo.get(_YELLOW_3)]  # 黄 cost1 / cost3

    execute_effect(_eff(overlay, "OP09-107", "trigger")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-107"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in (_YELLOW_1, _YELLOW_3) for c in me.characters), \
        "人間が選んだ黄キャラが登場していない"


def test_op09_107_trigger_play_yellow_ai():
    """【トリガー】AI: 手札のコスト3以下黄キャラを crash せず登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_YELLOW_1)]  # 黄 cost1

    chars_before = len(me.characters)
    for prim in _eff(overlay, "OP09-107", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-107"), sickness=True))
    _drain(st, [0])
    assert len(me.characters) == chars_before + 1, \
        "トリガーで黄キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP09-108 バーソロミュー・くま (CHARACTER): 【トリガー】自リーダーが《革命軍》で
#          総ライフ5以下なら、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op09_108_trigger_self_play_ai():
    """【トリガー】革命軍 leader + 総ライフ5以下 → このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 4  # 総ライフ 4 (≤5)
    me.characters = []
    me.trash = [repo.get("OP09-108")]  # トリガー処理で trash から登場
    st.current_source_card_id = "OP09-108"

    for prim in _eff(overlay, "OP09-108", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-108"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "OP09-108" for c in me.characters), \
        "トリガーで バーソロミュー・くま が登場していない"


def test_op09_108_trigger_conditions():
    """トリガー条件 leader_feature《革命軍》 + total_life_le:5 の成立/不成立を検証。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP09-108", "trigger")
    assert eff.get("if", {}).get("leader_feature") == "革命軍", \
        "overlay の リーダー条件 (革命軍) が無い"
    assert eff.get("if", {}).get("total_life_le") == 5, \
        "overlay の 条件 total_life_le=5 が無い"

    st = _state(repo, _LEADER_REVO, overlay)
    st.players[0].life = [repo.get(_FILLER)] * 4
    assert eval_all_conditions(eff, st, st.players[0], None) is True, \
        "革命軍 + 総ライフ4 で 条件が成立するべき"
    st2 = _state(repo, _LEADER_MUGIWARA, overlay)
    st2.players[0].life = [repo.get(_FILLER)] * 4
    assert eval_all_conditions(eff, st2, st2.players[0], None) is False, \
        "革命軍でない leader で 条件が成立してはいけない"
    st3 = _state(repo, _LEADER_REVO, overlay)
    st3.players[0].life = [repo.get(_FILLER)] * 6
    assert eval_all_conditions(eff, st3, st3.players[0], None) is False, \
        "総ライフ6で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP09-109 ハグワール・D・サウロ (CHARACTER): 【ブロッカー】。 【トリガー】自リーダーが
#          「ニコ・ロビン」なら、このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op09_109_trigger_self_play_ai():
    """【トリガー】ニコ・ロビン leader → このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ROBIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.trash = [repo.get("OP09-109")]
    st.current_source_card_id = "OP09-109"

    for prim in _eff(overlay, "OP09-109", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-109"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "OP09-109" for c in me.characters), \
        "トリガーで ハグワール・D・サウロ が登場していない"


def test_op09_109_trigger_gated_by_leader_name():
    """自リーダーが「ニコ・ロビン」でない場合、 トリガー効果は発火条件を満たさない。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP09-109", "trigger")
    assert eff.get("if", {}).get("leader_name") == "ニコ・ロビン", \
        "overlay の リーダー名条件 (ニコ・ロビン) が無い"
    st_ng = _state(repo, _LEADER_MUGIWARA, overlay)
    assert eval_all_conditions(eff, st_ng, st_ng.players[0], None) is False, \
        "ニコ・ロビン でない leader で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP09-110 ピエール (CHARACTER): 【登場時】カード2枚を引き、自分の手札2枚を捨てる。
#          【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op09_110_on_play_draw2_discard2_ai():
    """【登場時】カード2枚を引き、 手札2枚を捨てる (AI、 net hand = ±0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 5
    me.hand = [repo.get(_FILLER)] * 3

    deck_before = len(me.deck)
    hand_before = len(me.hand)
    trash_before = len(me.trash)
    for prim in _eff(overlay, "OP09-110", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-110"), sickness=True))
    _drain(st, [0])
    assert len(me.deck) == deck_before - 2, f"カード2枚が引かれていない: {len(me.deck)}"
    assert len(me.trash) == trash_before + 2, "捨てた手札2枚がトラッシュに置かれていない"
    # net hand: +2 引き -2 捨て = ±0
    assert len(me.hand) == hand_before, \
        f"手札 net (+2 引き -2 捨て = ±0) が合わない: {len(me.hand)}"


def test_op09_110_trigger_self_play_ai():
    """【トリガー】このカードを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.trash = [repo.get("OP09-110")]
    st.current_source_card_id = "OP09-110"

    for prim in _eff(overlay, "OP09-110", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-110"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "OP09-110" for c in me.characters), \
        "トリガーで ピエール が登場していない"
