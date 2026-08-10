# -*- coding: utf-8 -*-
"""OP10 弾 黄 (キッド海賊団・超新星・ハートの海賊団) + OP11 弾 赤 (海軍・NEO海軍)
効果 回帰テスト バックフィル (自動生成 wave 109):
OP10-110 / OP10-113 / OP10-115 / OP10-116 / OP10-117 / OP10-119 /
OP11-002 / OP11-005 / OP11-006 / OP11-007 の 10 枚。

  OP10-110 ヒート＆ワイヤー (CHARACTER 黄) = 【登場時】相手のライフの枚数以下のコストを
     持つ相手のキャラ1枚までを、レストにする (rest cost_le_dynamic=opp_life_count)
  OP10-113 ロロノア・ゾロ (CHARACTER 黄) = 自ライフが相手より少ない場合、このキャラは
     【速攻】を得る (静的 give_keyword 速攻、 if self_life_lt_opp)
  OP10-115 “新世界”で会おうぜ (EVENT 黄) = 【カウンター】自リーダーかキャラ1枚 +4000。
     その後 自ライフ0枚なら 1ドロー / トリガー 相手キャラ1枚KO
  OP10-116 電磁砲 (EVENT 黄) = 【メイン】(ライフ操作) その後 相手のコスト5以下のキャラ
     1枚までをKO / トリガー 2枚引き手札1枚捨てる
  OP10-117 ROOM (EVENT 黄) = 【カウンター】自ライフ1枚以下の場合、 自リーダーかキャラ +3000。
     その後 自コスト5以下キャラ1枚をアクティブに (if self_life_le=1) / トリガー 1ドロー
  OP10-119 トラファルガー・ロー (CHARACTER 黄) = 【登場時】手札から超新星キャラ1枚までを
     ライフ上に裏向きで加える (hand_to_self_life filter=超新星 CHARACTER)
  OP11-002 アイン (CHARACTER 赤) = 【登場時】相手キャラ1枚 -1000。その後 相手のパワー0以下
     キャラ1枚をKO (power_pump -1000 → ko power_le_0)
  OP11-005 スモーカー (CHARACTER 赤) = 【ドン‼×1】属性(特)を持たないキャラの効果でKOされない
     (静的 set_ko_immune_from_non_attribute=特, n=1)
  OP11-006 ゼット (CHARACTER 赤) = 【ドン‼×1】【アタック時】相手の属性(特)キャラ1枚 -5000
     (on_attack power_pump filter attribute=特)
  OP11-007 たしぎ (CHARACTER 赤) = 【起動メイン】このキャラをレスト：自リーダー海軍なら
     自海軍キャラ1枚 +2000 (activate_main, cost rest_self once_per_turn, if leader_feature=海軍)

目的 (= test_backfill_auto_001〜108.py と同一方針):
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

_LEADER_GENERIC = "OP01-001"     # モンキー・D・ルフィ (超新星/麦わらの一味 — 汎用埋め)
_LEADER_SHINSEI = "OP13-001"     # モンキー・Ｄ・ルフィ (超新星/麦わらの一味)
_LEADER_NAVY = "OP16-060"        # センゴク (海軍)
_LEADER_NON_NAVY = "OP01-001"    # ルフィ (海軍を持たない)
_FILLER = "ST01-004"             # サンジ cost2 power4000 attr 打 (非特/非海軍/非超新星)
_FILLER_P1000 = "OP16-043"       # ウソップ cost2 power1000 attr 射
_SP_C = "PRB02-012"              # ナミ cost2 power2000 attr 特
_SHINSEI_C = "PRB02-004"         # ジュエリー・ボニー cost3 power3000 attr 特 超新星
_SHINSEI_C2 = "EB01-015"         # スクラッチメン・アプー cost1 power1000 超新星
_NAVY_C = "PRB02-001"            # コビー cost4 power5000 海軍
_COST5_C = "PRB02-011"           # ドフラミンゴ cost5 (王下七武海)
_COST6_C = "PRB02-013"           # ゲッコー・モリア cost6


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` の両対応)。

    ⚠ 2026-08-05: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を **効果のみ** の
    gate とする (cardqa_op_02 / cardqa_st_04)。 top-level `if` に置くと **任意コストの支払いごと
    消える** ので、 overlay ではこの形の条件を `conditional` の中に移した。
    条件そのものは変わっていないので、 テストはどちらの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    for _prim in eff.get("do") or []:
        if isinstance(_prim, dict) and "conditional" in _prim:
            return (_prim.get("conditional") or {}).get("if") or {}
    return {}


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
def test_all_wave109_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP10-110", "OP10-113", "OP10-115", "OP10-116", "OP10-117",
           "OP10-119", "OP11-002", "OP11-005", "OP11-006", "OP11-007"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP10-110 ヒート＆ワイヤー: 【登場時】相手ライフ枚数以下コストの相手キャラ1枚をレスト
# --------------------------------------------------------------------------- #
def test_op10_110_on_play_rest_within_life_count_ai():
    """【登場時】AI: 相手ライフ3枚 → コスト3以下の相手キャラ (cost2) をレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 3
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-110", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-110"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, \
        "相手ライフ枚数以下のコストを持つ相手キャラがレストにされていない"


def test_op10_110_on_play_no_rest_when_cost_above_life_count():
    """相手ライフ1枚 → コスト2の相手キャラは対象外 (レストされない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 1  # ライフ1 → cost≤1 のみ対象
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 > 1
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-110", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-110"), sickness=True))
    _drain(st, [0])
    assert victim.rested is False, \
        "ライフ枚数を超えるコストのキャラがレストされてはいけない (対象外)"


def test_op10_110_on_play_human_target_pick():
    """人間 + 対象の相手キャラ複数 → target_pick modal → resolve で1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get(_FILLER)] * 3
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)  # cost2
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP10-110", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP10-110"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはアクティブのままであるべき"


# --------------------------------------------------------------------------- #
#  OP10-113 ロロノア・ゾロ: 自ライフが相手より少ない場合【速攻】(静的)
# --------------------------------------------------------------------------- #
def test_op10_113_static_rush_when_self_life_lt_opp():
    """静的: 自ライフ<相手ライフ の場合、 このキャラは【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP10-113"), sickness=True)  # sick だが速攻付与で攻撃可
    me.characters = [zoro]
    me.life = [repo.get(_FILLER)] * 1   # 自ライフ 1
    opp.life = [repo.get(_FILLER)] * 3  # 相手ライフ 3 → self_life_lt_opp 成立

    evaluate_static_effects(st, overlay)
    # ⚠ has_keyword_active はテキスト部分一致 (「【速攻】を得る」の文字列) で常に True に
    #    なるため、 静的付与の実体である static_granted_keywords を直接検証する。
    assert "速攻" in zoro.static_granted_keywords, \
        "自ライフが相手より少ないのに【速攻】が静的付与されていない"


def test_op10_113_static_no_rush_when_self_life_ge_opp():
    """自ライフ>=相手ライフ の場合は【速攻】が付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP10-113"), sickness=True)
    me.characters = [zoro]
    me.life = [repo.get(_FILLER)] * 3   # 自ライフ 3
    opp.life = [repo.get(_FILLER)] * 1  # 相手ライフ 1 → 条件不成立

    evaluate_static_effects(st, overlay)
    assert "速攻" not in zoro.static_granted_keywords, \
        "自ライフが相手以上なのに【速攻】が静的付与されてはいけない"


# --------------------------------------------------------------------------- #
#  OP10-115 “新世界”で会おうぜ: 【カウンター】自リーダー/キャラ +4000、
#            その後自ライフ0で1ドロー / トリガー 相手キャラ1枚KO
# --------------------------------------------------------------------------- #
def test_op10_115_counter_pump_4000_ai():
    """【カウンター】AI: 自リーダーに +4000 (self_inplay 既定=リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # ライフ>0 → 条件付きドローは起きない

    power_before = me.leader.power
    counter_eff = _eff(overlay, "OP10-115", "counter")
    pump = counter_eff["do"][0]
    execute_effect(pump, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_op10_115_counter_conditional_draw_when_life_0():
    """その後 自ライフ0枚なら 1ドロー / ライフ>0では引かない。"""
    repo = _repo()
    overlay = _overlay()
    counter_eff = _eff(_overlay(), "OP10-115", "counter")
    cond_prim = counter_eff["do"][1]
    assert cond_prim["conditional"]["if"].get("self_life_le") == 0, \
        "overlay の 条件付きドロー if self_life_le=0 が無い"

    # ライフ0 → 1ドロー
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = []
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5
    execute_effect(cond_prim, st, me, opp, None)
    assert len(me.hand) == 1, "自ライフ0枚で 1ドローが起きていない"

    # ライフ1 → 引かない
    st2 = _state(repo, _LEADER_GENERIC, overlay)
    me2 = st2.players[0]
    me2.life = [repo.get(_FILLER)]
    me2.hand = []
    me2.deck = [repo.get(_FILLER)] * 5
    execute_effect(cond_prim, st2, me2, st2.players[1], None)
    assert len(me2.hand) == 0, "自ライフ1枚では ドローが起きてはいけない"


def test_op10_115_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ → +4000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    pump = _eff(overlay, "OP10-115", "counter")["do"][0]
    execute_effect(pump, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


def test_op10_115_trigger_ko_opponent_ai():
    """【トリガー】AI: 相手キャラ1枚を KO する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-115", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "トリガーで相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP10-116 電磁砲: 【メイン】相手コスト5以下キャラ1枚KO / トリガー 2枚引き1枚捨て
# --------------------------------------------------------------------------- #
def test_op10_116_main_ko_cost_le_5_ai():
    """【メイン】AI: 相手のコスト5以下のキャラ (cost5) を KO する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_COST5_C), sickness=False)  # cost5 ≤ 5
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-116", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "コスト5以下の相手キャラが KO されていない"


def test_op10_116_main_no_ko_cost_6():
    """コスト6の相手キャラは対象外 (KOされない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_COST6_C), sickness=False)  # cost6 > 5
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-116", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim in opp.characters, "コスト6のキャラが KO されてはいけない (対象外)"


def test_op10_116_main_human_ko_pick():
    """人間 + コスト5以下の相手キャラ複数 → target_pick modal → resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAVY_C), sickness=False)  # cost4
    b = InPlay.of(repo.get(_COST5_C), sickness=False)  # cost5
    opp.characters = [a, b]

    # ⚠ 2026-08-11: do[0] は 公式テキスト前半の scry_life (「ライフの上から1枚までを見て、
    #   ライフの上か下に置く」) になった。 このテストが見たいのは 「その後」 の KO なので、
    #   do から ko primitive を名指しで取る (index 依存にしない)。
    _do = _eff(overlay, "OP10-116", "main")["do"]
    _ko_prim = next(p for p in _do if "ko" in p)
    execute_effect(_ko_prim, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_op10_116_trigger_draw2_trash1():
    """【トリガー】カード2枚引き手札1枚捨てる → 手札 net +1、 デッキ -2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    me.deck = [repo.get(_FILLER)] * 5

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    for prim in _eff(overlay, "OP10-116", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == hand_before + 2 - 1, \
        f"手札 net (+2 -1) が合わない: {len(me.hand)} (before {hand_before})"
    assert len(me.deck) == deck_before - 2, \
        f"デッキが 2 枚減っていない: {len(me.deck)} (before {deck_before})"


# --------------------------------------------------------------------------- #
#  OP10-117 ROOM: 【カウンター】自ライフ1枚以下で 自リーダー/キャラ +3000、
#            その後 自コスト5以下キャラ1枚をアクティブに / トリガー 1ドロー
# --------------------------------------------------------------------------- #
def test_op10_117_counter_condition_gate():
    """カウンターは 自ライフ1枚以下ゲート。 life=1 成立 / life=2 不成立。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP10-117", "counter")
    assert _cond_of(eff).get("self_life_le") == 1, \
        "overlay の 条件 self_life_le=1 が無い"

    st = _state(repo, _LEADER_GENERIC, overlay)
    me = st.players[0]
    me.life = [repo.get(_FILLER)] * 1
    assert eval_all_conditions(eff, st, me, None) is True, \
        "自ライフ1枚で 条件が成立するべき"

    st2 = _state(repo, _LEADER_GENERIC, overlay)
    me2 = st2.players[0]
    me2.life = [repo.get(_FILLER)] * 2
    assert eval_all_conditions(eff, st2, me2, None) is False, \
        "自ライフ2枚では 条件が成立してはいけない"


def test_op10_117_counter_pump_3000_ai():
    """【カウンター】AI: 自リーダーに +3000 (self_inplay 既定=リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)]

    power_before = me.leader.power
    pump = _eff(overlay, "OP10-117", "counter")["do"][0]
    execute_effect(pump, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


def test_op10_117_counter_untap_cost_le_5_ai():
    """その後 自コスト5以下キャラ1枚をアクティブにする (rested→active)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)]
    friend = InPlay.of(repo.get(_NAVY_C), sickness=False)  # cost4 ≤ 5
    friend.rested = True
    me.characters = [friend]

    untap = _eff(overlay, "OP10-117", "counter")["do"][1]
    execute_effect(untap, st, me, opp, None)
    _drain(st, [0])
    assert friend.rested is False, \
        "コスト5以下の自キャラがアクティブにされていない"


def test_op10_117_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ → +3000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    pump = _eff(overlay, "OP10-117", "counter")["do"][0]
    execute_effect(pump, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 3000, \
        "人間が選んだキャラに +3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP10-119 トラファルガー・ロー: 【登場時】手札から超新星キャラ1枚をライフ上へ裏向き
# --------------------------------------------------------------------------- #
def test_op10_119_on_play_hand_to_life_ai():
    """【登場時】AI: 手札の超新星キャラ1枚をライフの上に加える (手札-1 / ライフ+1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHINSEI, overlay)
    me, opp = st.players[0], st.players[1]
    shinsei = repo.get(_SHINSEI_C)  # 超新星 CHARACTER
    me.hand = [shinsei]
    me.life = [repo.get(_FILLER)] * 2

    hand_before = len(me.hand)
    life_before = len(me.life)
    for prim in _eff(overlay, "OP10-119", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-119"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == hand_before - 1, "手札の超新星キャラが1枚減っていない"
    assert len(me.life) == life_before + 1, "ライフが1枚増えていない"
    assert any(c.card_id == _SHINSEI_C for c in me.life), \
        "加えた超新星キャラがライフに入っていない"


def test_op10_119_on_play_no_move_when_no_shinsei_in_hand():
    """手札に超新星キャラが無ければ 何も移動しない (対象0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHINSEI, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # 麦わらの一味 (非超新星)
    me.life = [repo.get(_FILLER)]

    hand_before = len(me.hand)
    life_before = len(me.life)
    for prim in _eff(overlay, "OP10-119", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP10-119"), sickness=True))
    _drain(st, [0])
    assert len(me.hand) == hand_before, "対象なしなのに手札が減っている"
    assert len(me.life) == life_before, "対象なしなのにライフが増えている"


def test_op10_119_on_play_human_hand_to_life_pick():
    """人間 + 手札に超新星キャラ複数 → hand_to_life_pick modal → resolve で1枚移動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHINSEI, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_SHINSEI_C), repo.get(_SHINSEI_C2)]  # 超新星 x2
    me.life = [repo.get(_FILLER)]

    execute_effect(_eff(overlay, "OP10-119", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP10-119"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で hand_to_life_pick modal が立たない"
    assert st.pending_choice.get("kind") == "hand_to_life_pick", \
        f"kind が hand_to_life_pick でない: {st.pending_choice.get('kind')}"
    life_before = len(me.life)
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert len(me.life) == life_before + 1, "人間が選んだ超新星キャラがライフに加わっていない"


# --------------------------------------------------------------------------- #
#  OP11-002 アイン: 【登場時】相手キャラ1枚 -1000 → 相手のパワー0以下キャラ1枚KO
# --------------------------------------------------------------------------- #
def test_op11_002_on_play_debuff_then_ko_ai():
    """【登場時】AI: 相手キャラ (power1000) を -1000 → power0 → KO される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER_P1000), sickness=False)  # power1000
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-002", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-002"), sickness=True))
    _drain(st, [0])
    assert victim not in opp.characters, \
        "power1000 → -1000 で power0 になった相手キャラが KO されていない"


def test_op11_002_on_play_survives_when_power_above_0():
    """相手キャラ (power2000) は -1000 で power1000 → 0以下でなく KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SP_C), sickness=False)  # power2000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _eff(overlay, "OP11-002", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-002"), sickness=True))
    _drain(st, [0])
    assert victim in opp.characters, "power1000 残りのキャラが KO されてはいけない"
    assert victim.power == power_before - 1000, \
        f"相手キャラの -1000 が反映されていない: {victim.power} (before {power_before})"


def test_op11_002_on_play_human_debuff_pick():
    """人間 + 相手キャラ複数 → -1000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_SP_C), sickness=False)
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP11-002", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-002"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before - 1000, "人間が選んだ相手キャラに -1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP11-005 スモーカー: 【ドン‼×1】属性(特)を持たないキャラの効果でKOされない (静的)
# --------------------------------------------------------------------------- #
def test_op11_005_static_ko_immune_from_non_attribute_with_don():
    """ドン1付与時: static_ko_immune_from_non_attribute = "特" がセットされる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me = st.players[0]
    smoker = InPlay.of(repo.get("OP11-005"), sickness=False)
    smoker.attached_dons = 1  # n=1 ゲート成立
    me.characters = [smoker]

    evaluate_static_effects(st, overlay)
    assert smoker.static_ko_immune_from_non_attribute == "特", \
        f"ドン1で 属性(特)非保持者からのKO耐性が立たない: {smoker.static_ko_immune_from_non_attribute!r}"


def test_op11_005_static_no_immune_without_don():
    """ドン0枚では n=1 ゲート不成立 → KO耐性はセットされない (空文字)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me = st.players[0]
    smoker = InPlay.of(repo.get("OP11-005"), sickness=False)
    smoker.attached_dons = 0
    me.characters = [smoker]

    evaluate_static_effects(st, overlay)
    assert smoker.static_ko_immune_from_non_attribute == "", \
        "ドン0枚では KO耐性がセットされてはいけない"


# --------------------------------------------------------------------------- #
#  OP11-006 ゼット: 【ドン‼×1】【アタック時】相手の属性(特)キャラ1枚 -5000
# --------------------------------------------------------------------------- #
def test_op11_006_on_attack_debuff_special_attr_ai():
    """【アタック時】AI: 相手の属性(特)キャラ (power2000) を -5000 する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SP_C), sickness=False)  # 属性 特 power2000
    opp.characters = [victim]
    attacker = InPlay.of(repo.get("OP11-006"), sickness=False)
    attacker.attached_dons = 1

    eff = _eff(overlay, "OP11-006", "on_attack")
    assert _cond_of(eff).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    power_before = victim.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])
    assert victim.power == power_before - 5000, \
        f"属性(特)キャラの -5000 が反映されていない: {victim.power} (before {power_before})"


def test_op11_006_on_attack_no_debuff_non_special_attr():
    """属性(特)を持たない相手キャラ (attr 打) は対象外 (power 不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # attr 打 = 対象外
    opp.characters = [victim]
    attacker = InPlay.of(repo.get("OP11-006"), sickness=False)
    attacker.attached_dons = 1

    power_before = victim.power
    for prim in _eff(overlay, "OP11-006", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])
    assert victim.power == power_before, \
        "属性(特)を持たないキャラの power が変化してはいけない (対象外)"


def test_op11_006_on_attack_human_pick():
    """人間 + 属性(特)キャラ複数 → -5000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_SP_C), sickness=False)      # 特
    b = InPlay.of(repo.get(_SHINSEI_C), sickness=False)  # 特 (ボニー)
    opp.characters = [a, b]
    attacker = InPlay.of(repo.get("OP11-006"), sickness=False)
    attacker.attached_dons = 1

    execute_effect(_eff(overlay, "OP11-006", "on_attack")["do"][0], st, me, opp, attacker)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before - 5000, "人間が選んだ属性(特)キャラに -5000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP11-007 たしぎ: 【起動メイン】自レスト → 自リーダー海軍なら 自海軍キャラ1枚 +2000
# --------------------------------------------------------------------------- #
def test_op11_007_activate_main_pump_navy_ai():
    """起動メイン: 海軍リーダー下で 自海軍キャラ1枚に +2000。 コストで自身レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay)  # センゴク (海軍)
    me, opp = st.players[0], st.players[1]
    tashigi = InPlay.of(repo.get("OP11-007"), sickness=False)
    kobby = InPlay.of(repo.get(_NAVY_C), sickness=False)  # 海軍 power5000
    me.characters = [tashigi, kobby]

    sum_before = tashigi.power + kobby.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-007"]
    assert len(opts) == 1, f"OP11-007 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    # 海軍キャラのどちらか 1 体に +2000 (= AI 自動選択)。 合計 +2000。
    assert tashigi.power + kobby.power == sum_before + 2000, \
        f"自海軍キャラへの +2000 が反映されていない: {tashigi.power + kobby.power} (before {sum_before})"
    assert tashigi.rested is True, "起動メインコストで たしぎ がレストされるべき"


def test_op11_007_activate_main_gated_by_non_navy_leader():
    """自リーダーが海軍でない場合、 起動メインは legal に出ない (leader_feature ゲート)。"""
    # ⚠ 2026-08-05 是正: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を
    #   **効果のみ** の gate とする。 任意コストは条件不成立でも支払える。
    #   一次情報 (cardqa_op_02): 「自分のリーダーが「エンポリオ・イワンコフ」ではない場合、
    #   この【起動メイン】効果を発動できますか？」 → 「はい、できます。 その場合、このカードを
    #   レストにしますが、 **その後の効果では何も起きません**」。
    #   → 「条件不成立なら legal に出ない」 は **行動の合法性ごと消す旧バグ** を固定していた。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NON_NAVY, overlay)  # 麦わら (非海軍)
    me = st.players[0]
    tashigi = InPlay.of(repo.get("OP11-007"), sickness=False)
    me.characters = [tashigi, InPlay.of(repo.get(_NAVY_C), sickness=False)]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-007"]
    assert len(opts) == 1, (
        "任意コストは条件不成立でも払えるので legal に残るべき (公式: cardqa_op_02)"
    )


def test_op11_007_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay)
    me, opp = st.players[0], st.players[1]
    tashigi = InPlay.of(repo.get("OP11-007"), sickness=False)
    me.characters = [tashigi, InPlay.of(repo.get(_NAVY_C), sickness=False)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-007"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-007"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op11_007_activate_main_human_pump_pick():
    """人間 + 自海軍キャラ複数 → target_pick modal → resolve で1枚 +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    tashigi = InPlay.of(repo.get("OP11-007"), sickness=False)  # 海軍 (自身も候補)
    kobby = InPlay.of(repo.get(_NAVY_C), sickness=False)       # 海軍
    me.characters = [tashigi, kobby]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-007"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) >= 2, f"候補 (海軍キャラ) が 2 件以上でない: {len(cands)}"
    kobby_idx = next(i for i, c in enumerate(cands) if c["iid"] == kobby.instance_id)
    kobby_before = kobby.power
    resolve_pending_choice(st, [kobby_idx])
    _drain(st, [0])
    assert kobby.power == kobby_before + 2000, \
        "人間が選んだ海軍キャラに +2000 が反映されていない"
