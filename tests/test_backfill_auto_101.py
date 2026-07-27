# -*- coding: utf-8 -*-
"""OP10 弾 赤 パンクハザード/海軍 軸 効果 回帰テスト バックフィル (自動生成 wave 101):
OP10-004 / OP10-005 / OP10-006 / OP10-007 / OP10-008 /
OP10-009 / OP10-010 / OP10-015 / OP10-016 / OP10-017 の 10 枚
(ヴェルゴ = デッキ上5枚サーチ / サンジ = 自ターン +3000 & KO時ドロー /
 シーザー・クラウン = スマイリーサーチ登場 / シーザー兵 = 手札からパンクハザード登場 /
 スコッチ・ロック = 相棒登場 / スマイリー = 相手 -3000 / チャドロス = 自己 +1000 /
 モチャ = 相手 -1000 / モネ = レストドン付与 + 相手 -1000)。

目的 (= test_backfill_auto_001〜100.py と同一方針):
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
_LEADER_PH = "OP10-002"       # シーザー・クラウン (leader、 科学者/パンクハザード)
_LEADER_MUGIWARA = "OP01-001"  # ロロノア・ゾロ (leader、 超新星/麦わらの一味 — 条件外し用)
_FILLER = "ST01-004"          # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_SMALL = "OP01-016"           # ナミ cost1 power2000 (バニラ、 パワー2000以下)
_BIG = "PRB02-018"            # エース cost5 power7000 (パワー7000以上)
_PH_VANILLA = "OP10-012"      # ドラゴン十三號 cost2 power2000 パンクハザード (効果なし = 登場対象に安全)
_ROCK = "OP10-017"            # ロック cost2 パンクハザード
_SCOTCH = "OP10-008"          # スコッチ cost2 パンクハザード (ブロッカー)
_SMILEY = "OP10-009"          # スマイリー cost5 生物兵器/パンクハザード


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
def test_all_wave101_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP10-004", "OP10-005", "OP10-006", "OP10-007", "OP10-008",
           "OP10-009", "OP10-010", "OP10-015", "OP10-016", "OP10-017"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP10-004 ヴェルゴ (CHARACTER): 【登場時】自分のデッキの上から5枚を見て、「ヴェルゴ」
#          以外の特徴《パンクハザード》を持つカード1枚までを公開し、手札に加える。
#          その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op10_004_on_play_search_punk_hazard_ai():
    """【登場時】上5枚から パンクハザードカードを手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PH, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_PH_VANILLA)] + [repo.get(_FILLER)] * 20  # 上に PH を仕込む
    me.hand = []

    for prim in _eff(overlay, "OP10-004", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-004"), sickness=True))
    _drain(st, [0])
    assert any(c.card_id == _PH_VANILLA for c in me.hand), \
        "上5枚から 特徴《パンクハザード》カードが手札に加わっていない"


def test_op10_004_on_play_search_human_pick():
    """人間 + 上5枚に パンクハザード 複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PH, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_PH_VANILLA), repo.get(_FILLER),
               repo.get(_ROCK)] + [repo.get(_FILLER)] * 15
    me.hand = []

    execute_effect(_eff(overlay, "OP10-004", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP10-004"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (パンクハザード) を選択
    _drain(st, [])
    assert any(c.card_id in (_PH_VANILLA, _ROCK) for c in me.hand), \
        "人間が選んだ 特徴《パンクハザード》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP10-005 サンジ (CHARACTER): 【自分のターン中】このキャラのパワー+3000。
#          【KO時】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op10_005_static_pump_on_self_turn():
    """【自分のターン中】このキャラ +3000 (静的効果)。 base 3000 → 6000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分のターン (= self_turn 条件成立)
    sanji_def = repo.get("OP10-005")  # power 3000
    sanji = InPlay.of(sanji_def, sickness=False)
    me.characters = [sanji]

    evaluate_static_effects(st, overlay)
    assert sanji.power == sanji_def.power + 3000, \
        f"自分のターン中に +3000 が乗っていない: {sanji.power} (base {sanji_def.power})"


def test_op10_005_static_no_pump_on_opp_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → 効果 +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン → self_turn False
    sanji_def = repo.get("OP10-005")
    sanji = InPlay.of(sanji_def, sickness=False)
    me.characters = [sanji]

    evaluate_static_effects(st, overlay)
    assert sanji.power == sanji_def.power, \
        f"相手ターンで static pump が乗ってはいけない: {sanji.power} (base {sanji_def.power})"


def test_op10_005_on_ko_draw_ai():
    """【KO時】カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5

    deck_before = len(me.deck)
    for prim in _eff(overlay, "OP10-005", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-005"), sickness=False))
    _drain(st, [0])
    assert len(me.hand) == 1, f"KO時の 1 ドローが起きていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP10-006 シーザー・クラウン (CHARACTER): 【登場時】自分のデッキの上から5枚を見て、
#          「スマイリー」1枚までを公開し、手札に加える。その後、残りを好きな順番で
#          デッキの下に置き、自分の手札から「スマイリー」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op10_006_on_play_search_and_summon_smiley_ai():
    """【登場時】上5枚から スマイリーを手札へ → 手札から スマイリーを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PH, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SMILEY)] + [repo.get(_FILLER)] * 20  # 上に スマイリー
    me.hand = []
    me.characters = []

    chars_before = len(me.characters)
    for prim in _eff(overlay, "OP10-006", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-006"), sickness=True))
    _drain(st, [0])
    assert len(me.characters) == chars_before + 1, \
        "デッキから引いた スマイリー が登場していない"
    assert any(c.card.name == "スマイリー" for c in me.characters), \
        "登場したのが スマイリー でない"


def test_op10_006_on_play_no_smiley_no_summon():
    """上5枚にも手札にも スマイリーが無ければ 登場は起きない (該当なし = 不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PH, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 20  # スマイリー 無し
    me.hand = []
    me.characters = []

    for prim in _eff(overlay, "OP10-006", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-006"), sickness=True))
    _drain(st, [0])
    assert not any(c.card.name == "スマイリー" for c in me.characters), \
        "スマイリー 不在なのに登場してはいけない"


# --------------------------------------------------------------------------- #
#  OP10-007 シーザー兵 (CHARACTER): 【登場時】自分の手札からコスト2以下の特徴
#          《パンクハザード》を持つキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op10_007_on_play_summon_ph_from_hand_ai():
    """【登場時】手札からコスト2以下パンクハザードキャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PH, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_PH_VANILLA)]  # ドラゴン十三號 cost2 パンクハザード
    me.characters = []

    chars_before = len(me.characters)
    for prim in _eff(overlay, "OP10-007", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-007"), sickness=True))
    _drain(st, [0])
    assert len(me.characters) == chars_before + 1, \
        "手札からコスト2以下パンクハザードキャラが登場していない"
    assert any(c.card.card_id == _PH_VANILLA for c in me.characters), \
        "登場したのが コスト2以下パンクハザードキャラでない"


def test_op10_007_on_play_summon_human_pick():
    """人間 + 手札にコスト2以下パンクハザード複数 → play_from_hand modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PH, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_PH_VANILLA), repo.get(_PH_VANILLA)]  # 2 体 → 選択
    me.characters = []

    execute_effect(_eff(overlay, "OP10-007", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP10-007"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id == _PH_VANILLA for c in me.characters), \
        "人間が選んだ パンクハザードキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP10-008 スコッチ (CHARACTER): 【ブロッカー】【登場時】自分の「ロック」がいない場合、
#          自分の手札から「ロック」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op10_008_on_play_summon_rock_ai():
    """【登場時】ロック不在 → 手札から「ロック」を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PH, overlay)
    me, opp = st.players[0], st.players[1]
    scotch = InPlay.of(repo.get("OP10-008"), sickness=True)
    me.characters = [scotch]
    me.hand = [repo.get(_ROCK)]

    for prim in _eff(overlay, "OP10-008", "on_play")["do"]:
        execute_effect(prim, st, me, opp, scotch)
    _drain(st, [0])
    assert any(c.card.card_id == _ROCK for c in me.characters), \
        "手札から「ロック」が登場していない"


def test_op10_008_on_play_condition_rock_unique():
    """条件 self_chara_unique_name「ロック」: 場に「ロック」がいると不成立。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP10-008", "on_play")
    assert eff.get("if", {}).get("self_chara_unique_name") == "ロック", \
        "overlay の 条件 self_chara_unique_name=ロック が無い"

    st = _state(repo, _LEADER_PH, overlay)
    me = st.players[0]
    scotch = InPlay.of(repo.get("OP10-008"), sickness=True)
    # ロック 不在 → 条件成立
    me.characters = [scotch]
    assert eval_all_conditions(eff, st, me, scotch) is True, \
        "「ロック」不在で 条件が成立するべき"
    # ロック が場にいる → 条件不成立
    me.characters = [scotch, InPlay.of(repo.get(_ROCK), sickness=False)]
    assert eval_all_conditions(eff, st, me, scotch) is False, \
        "「ロック」が場にいると 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP10-009 スマイリー (CHARACTER): 【登場時】自分のリーダーが特徴《パンクハザード》を
#          持つ場合、相手のキャラ1枚までを、このターン中、パワー-3000。
# --------------------------------------------------------------------------- #
def test_op10_009_on_play_debuff_opp_ai():
    """【登場時】相手キャラ1枚を このターン中 パワー-3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PH, overlay)  # パンクハザード leader
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # サンジ power 4000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _eff(overlay, "OP10-009", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-009"), sickness=True))
    _drain(st, [0])
    assert victim.power == power_before - 3000, \
        f"相手キャラの -3000 が反映されていない: {victim.power} (before {power_before})"


def test_op10_009_on_play_condition_leader_ph():
    """条件 leader_feature《パンクハザード》: パンクハザード leader で成立 / それ以外で不成立。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP10-009", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "パンクハザード", \
        "overlay の リーダー条件 (パンクハザード) が無い"

    st_ph = _state(repo, _LEADER_PH, overlay)
    assert eval_all_conditions(eff, st_ph, st_ph.players[0], None) is True, \
        "パンクハザード leader で 条件が成立するべき"
    st_mug = _state(repo, _LEADER_MUGIWARA, overlay)
    assert eval_all_conditions(eff, st_mug, st_mug.players[0], None) is False, \
        "パンクハザード でない leader で 条件が成立してはいけない"


def test_op10_009_on_play_debuff_human_pick():
    """人間 + 相手キャラ 複数 → -3000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PH, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    b = InPlay.of(repo.get(_SMALL), sickness=False)    # power 2000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP10-009", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP10-009"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b.power == b_before - 3000, "人間が選んだ相手キャラに -3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP10-010 チャドロス・ヒゲリゲス (CHARACTER): 【アタック時】自分のパワー6000以上の
#          キャラが1枚以下の場合、このキャラは、このターン中、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op10_010_on_attack_self_pump_ai():
    """【アタック時】このキャラ(自身)を このターン中 パワー+1000 (AI)。 base 5000 → 6000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP10-010"), sickness=False)  # power 5000
    me.characters = [attacker]

    power_before = attacker.power
    for prim in _eff(overlay, "OP10-010", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])
    assert attacker.power == power_before + 1000, \
        f"アタック時 自己 +1000 が反映されていない: {attacker.power} (before {power_before})"


def test_op10_010_on_attack_condition_power_6000_count():
    """条件 self_chara_power_ge_count_le (power6000 が 1枚以下): 大型2体で不成立。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP10-010", "on_attack")
    spec = eff.get("if", {}).get("self_chara_power_ge_count_le", {})
    assert spec.get("power") == 6000 and spec.get("count") == 1, \
        f"overlay の 条件 self_chara_power_ge_count_le が想定と違う: {spec}"

    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me = st.players[0]
    attacker = InPlay.of(repo.get("OP10-010"), sickness=False)  # power 5000 (<6000)
    # 大型 0 体 (attacker のみ、 6000以上=0) → 成立
    me.characters = [attacker]
    assert eval_all_conditions(eff, st, me, attacker) is True, \
        "パワー6000以上が0枚で 条件が成立するべき"
    # 大型 2 体 (6000以上=2 > 1) → 不成立
    me.characters = [attacker,
                     InPlay.of(repo.get(_BIG), sickness=False),   # power 7000
                     InPlay.of(repo.get(_BIG), sickness=False)]   # power 7000
    assert eval_all_conditions(eff, st, me, attacker) is False, \
        "パワー6000以上が2枚で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP10-015 モチャ (CHARACTER): 【登場時】相手のキャラ1枚までを、このターン中、
#          パワー-1000。
# --------------------------------------------------------------------------- #
def test_op10_015_on_play_debuff_opp_ai():
    """【登場時】相手キャラ1枚を このターン中 パワー-1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _eff(overlay, "OP10-015", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-015"), sickness=True))
    _drain(st, [0])
    assert victim.power == power_before - 1000, \
        f"相手キャラの -1000 が反映されていない: {victim.power} (before {power_before})"


def test_op10_015_on_play_debuff_human_pick():
    """人間 + 相手キャラ 複数 → -1000 の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    b = InPlay.of(repo.get(_SMALL), sickness=False)    # power 2000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP10-015", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP10-015"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b.power == b_before - 1000, "人間が選んだ相手キャラに -1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP10-016 モネ (CHARACTER): 【起動メイン】このキャラをレストにできる：自分のリーダーか
#          キャラ1枚にレストのドン‼2枚までを、付与する。その後、相手のキャラ1枚までを、
#          このターン中、パワー-1000。
# --------------------------------------------------------------------------- #
def test_op10_016_activate_main_attach_don_and_debuff_ai():
    """起動メイン: 自リーダー(既定)にレストドン2枚付与 → 相手キャラ -1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay)
    me, opp = st.players[0], st.players[1]
    mone = InPlay.of(repo.get("OP10-016"), sickness=False)
    me.characters = [mone]
    me.don_rested = 3
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    opp.characters = [victim]

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    power_before = victim.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-016"]
    assert len(opts) == 1, \
        f"OP10-016 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert me.leader.attached_dons == don_before + 2, \
        f"自リーダーへレストドン2枚が付与されていない: {me.leader.attached_dons}"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"
    assert mone.rested is True, "起動メインコストで モネ がレストされるべき"
    assert victim.power == power_before - 1000, \
        f"相手キャラの -1000 が反映されていない: {victim.power} (before {power_before})"


def test_op10_016_activate_main_attach_human_pick():
    """人間 + 付与先が自リーダー/キャラ 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_MUGIWARA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    mone = InPlay.of(repo.get("OP10-016"), sickness=False)
    me.characters = [mone]
    me.don_rested = 3
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-016"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    # 付与先候補 = 自リーダー + モネ の 2 件
    assert len(cands) == 2, f"付与先候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    leader_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == me.leader.instance_id)
    don_before = me.leader.attached_dons
    resolve_pending_choice(st, [leader_idx])
    _drain(st, [0])
    assert me.leader.attached_dons == don_before + 2, \
        "人間が選んだ自リーダーへレストドン2枚が付与されていない"


# --------------------------------------------------------------------------- #
#  OP10-017 ロック (CHARACTER): 【登場時】自分の「スコッチ」がいない場合、自分の手札から
#          「スコッチ」1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op10_017_on_play_summon_scotch_ai():
    """【登場時】スコッチ不在 → 手札から「スコッチ」を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_PH, overlay)
    me, opp = st.players[0], st.players[1]
    rock = InPlay.of(repo.get("OP10-017"), sickness=True)
    me.characters = [rock]
    me.hand = [repo.get(_SCOTCH)]

    for prim in _eff(overlay, "OP10-017", "on_play")["do"]:
        execute_effect(prim, st, me, opp, rock)
    _drain(st, [0])
    assert any(c.card.card_id == _SCOTCH for c in me.characters), \
        "手札から「スコッチ」が登場していない"


def test_op10_017_on_play_condition_scotch_unique():
    """条件 self_chara_unique_name「スコッチ」: 場に「スコッチ」がいると不成立。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP10-017", "on_play")
    assert eff.get("if", {}).get("self_chara_unique_name") == "スコッチ", \
        "overlay の 条件 self_chara_unique_name=スコッチ が無い"

    st = _state(repo, _LEADER_PH, overlay)
    me = st.players[0]
    rock = InPlay.of(repo.get("OP10-017"), sickness=True)
    me.characters = [rock]
    assert eval_all_conditions(eff, st, me, rock) is True, \
        "「スコッチ」不在で 条件が成立するべき"
    me.characters = [rock, InPlay.of(repo.get(_SCOTCH), sickness=False)]
    assert eval_all_conditions(eff, st, me, rock) is False, \
        "「スコッチ」が場にいると 条件が成立してはいけない"
