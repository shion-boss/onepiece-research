# -*- coding: utf-8 -*-
"""OP09 弾末尾 + OP10 弾リーダー 効果 回帰テスト バックフィル (自動生成 wave 100):
OP09-111 / OP09-112 / OP09-114 / OP09-115 / OP09-116 /
OP09-117 / OP09-119 / OP10-001 / OP10-002 / OP10-003 の 10 枚
(黄 エッグヘッド/革命軍 control・手札破壊・KO / 紫ルフィ 速攻 /
 OP10 三色リーダー = スモーカー(赤緑) / シーザー(赤青) / シュガー(赤紫) のドン加速・除去)。

目的 (= test_backfill_auto_001〜099.py と同一方針):
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

# よく使うテスト用カード (テキストの前提固定)
_LEADER_EGGHEAD = "OP07-097"    # ベガパンク (leader、 科学者/エッグヘッド)
_LEADER_REVO = "OP07-001"       # モンキー・D・ドラゴン (leader、 革命軍)
_LEADER_MUGIWARA = "OP01-001"   # ロロノア・ゾロ (leader、 麦わらの一味 — 上記条件を外す用)
_FILLER = "ST01-004"            # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_SMALL = "OP01-016"             # ナミ cost1 power2000 (バニラ、 パワー2000以下)
_REVO_CHAR = "OP05-006"         # コアラ cost2 (特徴《革命軍》、 手札登場対象)
_TRIG_CHAR_A = "PRB02-012"      # ナミ cost2 power2000 (【トリガー】持ち)
_TRIG_CHAR_B = "PRB02-016"      # お玉 cost2 (【トリガー】持ち 2 枚目)
_HAIGUN = "EB04-046"            # ドール cost2 power1000 (特徴《海軍》)
_BIG = "PRB02-018"              # エース cost5 power7000 (パワー7000以上)
_PH_CHAR = "EB03-010"           # モネ cost5 (特徴《パンクハザード》、 cost2 以上)


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
def test_all_wave100_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP09-111", "OP09-112", "OP09-114", "OP09-115", "OP09-116",
           "OP09-117", "OP09-119", "OP10-001", "OP10-002", "OP10-003"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP09-111 ブルック (CHARACTER): 【トリガー】自リーダーが特徴《エッグヘッド》を持ち、
#          相手の手札が6枚以上の場合、相手は自身の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op09_111_trigger_opp_discard2_ai():
    """【トリガー】エッグヘッド leader + 相手手札6枚以上 → 相手手札2枚を捨てさせる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_EGGHEAD, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER)] * 6

    hand_before = len(opp.hand)
    trash_before = len(opp.trash)
    for prim in _eff(overlay, "OP09-111", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-111"), sickness=True))
    _drain(st, [0])
    assert len(opp.hand) == hand_before - 2, \
        f"相手手札が2枚捨てられていない: {len(opp.hand)} (before {hand_before})"
    assert len(opp.trash) == trash_before + 2, \
        "捨てた相手手札2枚がトラッシュに置かれていない"


def test_op09_111_trigger_conditions():
    """トリガー条件 leader_feature《エッグヘッド》 + opp_hand_count_ge:6 の成立/不成立。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP09-111", "trigger")
    assert eff.get("if", {}).get("leader_feature") == "エッグヘッド", \
        "overlay の リーダー条件 (エッグヘッド) が無い"
    assert eff.get("if", {}).get("opp_hand_count_ge") == 6, \
        "overlay の 条件 opp_hand_count_ge=6 が無い"

    st = _state(repo, _LEADER_EGGHEAD, overlay)
    st.players[1].hand = [repo.get(_FILLER)] * 6
    assert eval_all_conditions(eff, st, st.players[0], None) is True, \
        "エッグヘッド + 相手手札6枚 で 条件が成立するべき"
    st2 = _state(repo, _LEADER_EGGHEAD, overlay)
    st2.players[1].hand = [repo.get(_FILLER)] * 5
    assert eval_all_conditions(eff, st2, st2.players[0], None) is False, \
        "相手手札5枚で 条件が成立してはいけない"
    st3 = _state(repo, _LEADER_MUGIWARA, overlay)
    st3.players[1].hand = [repo.get(_FILLER)] * 6
    assert eval_all_conditions(eff, st3, st3.players[0], None) is False, \
        "エッグヘッド でない leader で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP09-112 ベロ・ベティ (CHARACTER): 【登場時】自分のライフが2枚以下の場合、カード1枚
#          を引く。 【トリガー】(革命軍 leader + 総ライフ5以下で) このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op09_112_on_play_conditional_draw_ai():
    """【登場時】ライフ2枚以下 → カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5

    deck_before = len(me.deck)
    for prim in _eff(overlay, "OP09-112", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-112"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == 1, f"ライフ2枚以下で 1 ドローが起きていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"


def test_op09_112_on_play_draw_gated_by_life():
    """【登場時】ライフが3枚 (> 2) では 発火条件を満たさない (self_life_le:2)。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP09-112", "on_play")
    assert eff.get("if", {}).get("self_life_le") == 2, \
        "overlay の 条件 self_life_le=2 が無い"
    st = _state(repo, _LEADER_REVO, overlay)
    me = st.players[0]
    me.life = [repo.get(_FILLER)] * 3
    assert eval_all_conditions(eff, st, me, None) is False, \
        "ライフ3枚で 条件が成立してはいけない"
    me.life = [repo.get(_FILLER)] * 2
    assert eval_all_conditions(eff, st, me, None) is True, \
        "ライフ2枚で 条件が成立するべき"


def test_op09_112_trigger_self_play_ai():
    """【トリガー】このカードを登場させる (AI、 trash から場へ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []
    me.trash = [repo.get("OP09-112")]
    st.current_source_card_id = "OP09-112"

    for prim in _eff(overlay, "OP09-112", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-112"), sickness=True))
    _drain(st, [0])
    assert any(c.card.card_id == "OP09-112" for c in me.characters), \
        "トリガーで ベロ・ベティ が登場していない"


# --------------------------------------------------------------------------- #
#  OP09-114 リンドバーグ (CHARACTER): 【登場時】お互いのライフの合計枚数が5枚以下の場合、
#          相手のパワー2000以下のキャラ1枚までを、KOする。 【トリガー】(総ライフ5以下で)
#          このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op09_114_on_play_ko_power_le_2000_ai():
    """【登場時】総ライフ5以下 → 相手パワー2000以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    opp.life = [repo.get(_FILLER)] * 2  # 総ライフ 4 (≤5)
    victim = InPlay.of(repo.get(_SMALL), sickness=False)  # ナミ power 2000
    opp.characters = [victim]

    for prim in _eff(overlay, "OP09-114", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-114"), sickness=True))
    _drain(st, [0])
    assert victim not in opp.characters, "相手パワー2000以下キャラが KO されていない"


def test_op09_114_on_play_gated_by_total_life():
    """総ライフ6枚では 発火条件を満たさない (total_life_le:5)。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP09-114", "on_play")
    assert eff.get("if", {}).get("total_life_le") == 5, \
        "overlay の 条件 total_life_le=5 が無い"
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    opp.life = [repo.get(_FILLER)] * 3  # 総ライフ 6
    assert eval_all_conditions(eff, st, me, None) is False, \
        "総ライフ6で 条件が成立してはいけない"
    opp.life = [repo.get(_FILLER)] * 2  # 総ライフ 5
    assert eval_all_conditions(eff, st, me, None) is True, \
        "総ライフ5で 条件が成立するべき"


def test_op09_114_on_play_ko_human_pick():
    """人間 + 相手パワー2000以下キャラ複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2
    opp.life = [repo.get(_FILLER)] * 2
    a = InPlay.of(repo.get(_SMALL), sickness=False)  # power 2000
    b = InPlay.of(repo.get(_SMALL), sickness=False)  # power 2000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP09-114", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-114"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかった相手キャラは場に残るべき"


# --------------------------------------------------------------------------- #
#  OP09-115 アイス塊「両棘矛」 (EVENT): 【メイン】相手のコスト3以下の【トリガー】を持つ
#          キャラ1枚までを、KOする。 【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_115_main_ko_trigger_char_ai():
    """【メイン】相手のコスト3以下の【トリガー】持ちキャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_TRIG_CHAR_A), sickness=False)  # ナミ cost2 トリガー持ち
    opp.characters = [victim]

    for prim in _eff(overlay, "OP09-115", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, \
        "相手のコスト3以下【トリガー】持ちキャラが KO されていない"


def test_op09_115_main_ko_skips_non_trigger():
    """【トリガー】を持たないキャラは 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    safe = InPlay.of(repo.get(_SMALL), sickness=False)  # ナミ cost1 (トリガー無し)
    opp.characters = [safe]

    for prim in _eff(overlay, "OP09-115", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert safe in opp.characters, "【トリガー】を持たないキャラが KO されてはいけない (対象外)"


def test_op09_115_main_ko_human_pick():
    """人間 + 相手のコスト3以下【トリガー】持ち複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_TRIG_CHAR_A), sickness=False)  # ナミ cost2 トリガー
    b = InPlay.of(repo.get(_TRIG_CHAR_B), sickness=False)  # お玉 cost2 トリガー
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP09-115", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだ【トリガー】持ちキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_op09_115_trigger_draw_ai():
    """【トリガー】カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5

    for prim in _eff(overlay, "OP09-115", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == 1, f"トリガーの 1 ドローが起きていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP09-116 ”奇跡”ナメんじゃないよォ!!!! (EVENT): 【カウンター】自分のリーダーかキャラ
#          1枚までを、このバトル中、パワー+2000。 【トリガー】手札からコスト4以下の
#          特徴《革命軍》キャラ1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op09_116_counter_pump_ai():
    """【カウンター】自リーダー (既定) を このバトル中 パワー+2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "OP09-116", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op09_116_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    execute_effect(_eff(overlay, "OP09-116", "counter")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    fi = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [fi])
    _drain(st, [fi])
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


def test_op09_116_trigger_play_revo_ai():
    """【トリガー】手札からコスト4以下の 革命軍キャラを登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REVO, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_REVO_CHAR)]  # コアラ cost2 革命軍

    chars_before = len(me.characters)
    for prim in _eff(overlay, "OP09-116", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-116"), sickness=True))
    _drain(st, [0])
    assert len(me.characters) == chars_before + 1, \
        "トリガーで 革命軍キャラが登場していない"
    assert any(c.card.card_id == _REVO_CHAR for c in me.characters), \
        "登場したのが 革命軍キャラでない"


# --------------------------------------------------------------------------- #
#  OP09-117 デレシ!! (EVENT): 【メイン】自分のデッキの上から5枚を見て、「デレシ!!」以外の
#          【トリガー】を持つカード2枚までを公開し、手札に加える。その後、残りを好きな
#          順番でデッキの下に置く。 【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op09_117_main_search_trigger_cards_ai():
    """【メイン】上5枚から【トリガー】持ちカードを手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_TRIG_CHAR_A), repo.get(_FILLER)] + [repo.get(_FILLER)] * 10
    me.hand = []

    for prim in _eff(overlay, "OP09-117", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert any(c.card_id == _TRIG_CHAR_A for c in me.hand), \
        "上5枚から【トリガー】持ちカードが手札に加わっていない"


def test_op09_117_main_search_human_pick():
    """人間 + 上5枚に【トリガー】持ち複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_TRIG_CHAR_A), repo.get(_FILLER),
               repo.get(_TRIG_CHAR_B)] + [repo.get(_FILLER)] * 10
    me.hand = []

    execute_effect(_eff(overlay, "OP09-117", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id in (_TRIG_CHAR_A, _TRIG_CHAR_B) for c in me.hand), \
        "人間が選んだ【トリガー】持ちカードが手札に加わっていない"


def test_op09_117_trigger_draw_ai():
    """【トリガー】カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5

    for prim in _eff(overlay, "OP09-117", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == 1, f"トリガーの 1 ドローが起きていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP09-119 モンキー・D・ルフィ (CHARACTER 紫): 【登場時】自分の場のドン‼を1枚以上ドン‼
#          デッキに戻すことができる：カード1枚を引き、このキャラは、このターン中、
#          【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op09_119_on_play_draw_and_give_rush_ai():
    """【登場時】(ドン返却コスト後の効果本体) カード1枚を引き、 このキャラに【速攻】付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP09-119"), sickness=True)  # 登場直後 (summoning sickness)
    me.characters = [luffy]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5

    for prim in _eff(overlay, "OP09-119", "on_play")["do"]:
        execute_effect(prim, st, me, opp, luffy)
    _drain(st, [0])
    assert len(me.hand) == 1, f"効果本体の 1 ドローが起きていない: {len(me.hand)}"
    assert "速攻" in luffy.granted_keywords, "このキャラに【速攻】が付与されていない"


def test_op09_119_on_play_cost_is_pay_don():
    """overlay の コストが ドン返却 (pay_don) であることを sanity check。"""
    overlay = _overlay()
    eff = _eff(overlay, "OP09-119", "on_play")
    assert eff.get("cost", {}).get("pay_don") == 1, \
        f"overlay の コスト pay_don=1 が無い: {eff.get('cost')}"


# --------------------------------------------------------------------------- #
#  OP10-001 スモーカー (LEADER 赤/緑): 【相手のターン中】自分の特徴《海軍》か
#          《パンクハザード》キャラすべてを、パワー+1000。 【起動メイン】【ターン1回】
#          自分のパワー7000以上のキャラがいる場合、自分のドン‼2枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op10_001_static_pump_haigun_on_opp_turn():
    """【相手のターン中】自分の《海軍》キャラを パワー+1000 (静的効果)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    haigun = InPlay.of(repo.get(_HAIGUN), sickness=False)  # ドール 海軍 power1000
    me.characters = [haigun]

    evaluate_static_effects(st, overlay)
    assert haigun.power == 1000 + 1000, \
        f"相手ターン中に《海軍》キャラへ +1000 が乗っていない: {haigun.power}"


def test_op10_001_static_no_pump_on_self_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → 効果 +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分のターン → opp_turn False
    haigun = InPlay.of(repo.get(_HAIGUN), sickness=False)
    me.characters = [haigun]

    evaluate_static_effects(st, overlay)
    assert haigun.power == 1000, \
        f"自分のターンで 静的 pump が乗ってはいけない: {haigun.power}"


def test_op10_001_activate_untap_don_ai():
    """【起動メイン】パワー7000以上キャラがいる → 自分のドン‼2枚をアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-001", overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get(_BIG), sickness=False)  # power7000
    me.characters = [big]
    me.don_rested = 3
    me.don_active = 0

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-001"]
    assert len(opts) == 1, \
        f"OP10-001 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    assert me.don_active == 2 and me.don_rested == 1, \
        f"ドン2枚がアクティブになっていない: active={me.don_active} rested={me.don_rested}"


def test_op10_001_activate_gated_by_power_7000():
    """パワー7000以上のキャラがいなければ 起動メインは legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-001", overlay)
    me, opp = st.players[0], st.players[1]
    small = InPlay.of(repo.get(_SMALL), sickness=False)  # power2000
    me.characters = [small]
    me.don_rested = 3

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-001"]
    assert len(opts) == 0, \
        "パワー7000以上キャラ不在で 起動メインが legal に出てはいけない"


def test_op10_001_activate_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-001", overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get(_BIG), sickness=False)
    me.characters = [big]
    me.don_rested = 4

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP10-001"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP10-001"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP10-002 シーザー・クラウン (LEADER 赤/青): 【ドン‼×2】【アタック時】自分のコスト2以上
#          の特徴《パンクハザード》キャラ1枚を、持ち主の手札に戻すことができる：相手のパワー
#          4000以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op10_002_on_attack_bounce_then_ko_ai():
    """【アタック時】自パンクハザード(cost≥2)を手札へ戻し → 相手パワー4000以下を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-002", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 2  # ドン‼×2 ゲート
    mine = InPlay.of(repo.get(_PH_CHAR), sickness=False)  # モネ cost5 パンクハザード
    me.characters = [mine]
    victim = InPlay.of(repo.get(_SMALL), sickness=False)  # ナミ power2000 (≤4000)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-002", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st, [0])
    assert any(c.card_id == _PH_CHAR for c in me.hand), \
        "コストの 自パンクハザードキャラが手札に戻っていない"
    assert mine not in me.characters, "手札に戻したキャラが場に残っている"
    assert victim not in opp.characters, "相手パワー4000以下キャラが KO されていない"


def test_op10_002_on_attack_gate_don_ge_2():
    """overlay の アタック時効果に ドン‼×2 ゲート (self_attached_don_ge:2) がある。"""
    overlay = _overlay()
    eff = _eff(overlay, "OP10-002", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 2, \
        f"overlay の ドンゲート self_attached_don_ge=2 が無い: {eff.get('if')}"


def test_op10_002_on_attack_human_optional_confirm():
    """人間 + 任意コスト → optional_cost_confirm modal が立ち、 承諾すると KO まで解決する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-002", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 2
    mine = InPlay.of(repo.get(_PH_CHAR), sickness=False)
    me.characters = [mine]
    victim = InPlay.of(repo.get(_SMALL), sickness=False)
    opp.characters = [victim]

    execute_effect(_eff(overlay, "OP10-002", "on_attack")["do"][0], st, me, opp,
                   me.leader)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert victim not in opp.characters, "承諾後 相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP10-003 シュガー (LEADER 赤/紫): 【自分のターン終了時】自分のパワー6000以上の特徴
#          《ドンキホーテ海賊団》キャラがいる場合、自分のドン‼1枚までを、アクティブにする。
#          【相手のターン中】【ターン1回】自分がイベントを発動した時、ドン‼デッキから
#          ドン‼1枚までを、アクティブで追加する。
# --------------------------------------------------------------------------- #
def test_op10_003_event_played_add_don_ai():
    """【相手のターン中】自分がイベント発動時 → ドン‼デッキからドン‼1枚をアクティブで追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-003", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン中
    me.don_active = 0

    active_before = me.don_active
    deck_before = me.don_remaining_in_deck
    for prim in _eff(overlay, "OP10-003", "on_self_event_played")["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st, [0])
    assert me.don_active == active_before + 1, \
        f"ドン‼デッキから 1 枚がアクティブで追加されていない: {me.don_active}"
    assert me.don_remaining_in_deck == deck_before - 1, \
        "ドン‼デッキが 1 枚減っていない"


def test_op10_003_end_of_turn_untap_don_ai():
    """【ターン終了時】自分のドン‼1枚までを、アクティブにする (レストドン→アクティブ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP10-003", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    me.don_active = 0

    for prim in _eff(overlay, "OP10-003", "end_of_turn")["do"]:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st, [0])
    assert me.don_active == 1 and me.don_rested == 1, \
        f"レストドン1枚がアクティブになっていない: active={me.don_active} rested={me.don_rested}"
