# -*- coding: utf-8 -*-
"""OP11 弾 緑 (魚人族/人魚族/海王類・魚人島) 効果 回帰テスト
バックフィル (自動生成 wave 111):
OP11-024 / OP11-025 / OP11-028 / OP11-029 / OP11-030 / OP11-031 /
OP11-034 / OP11-035 / OP11-037 / OP11-038 の 10 枚。

  OP11-024 アラディン (CHARACTER 緑) = このキャラが相手の効果でKOされた時 (任意、 手札1捨て+
     ドン1レスト)：手札から コスト6以下の 魚人族/人魚族 キャラ1枚まで登場
     (on_ko by_opp_effect, do play_from_hand_choice filter feature_in cost_le6)
  OP11-025 イシリー (CHARACTER 緑) = 【相手のアタック時】【ターン1回】(ドン1+自レスト)：
     自リーダーかキャラ1枚まで このバトル中 +1000 (opp_attack, power_pump self_inplay +1000)
  OP11-028 近海の主 (CHARACTER 緑) = 【登場時】相手のレストキャラ1枚までは 次の相手リフレッシュで
     アクティブにならない / トリガー 相手レストのコスト3以下キャラ1枚KO
     (on_play stay_rested_next_refresh filter rested / trigger ko rested cost_le_3)
  OP11-029 シャーロット・プラリネ (CHARACTER 緑) = 【ブロッカー】【登場時】相手のコスト1以下キャラ
     1枚までをレスト (on_play rest one_opponent_character_cost_le_1cost)
  OP11-030 しらほし (CHARACTER 緑) = 【起動メイン】(ドン1+自レスト)：デッキ上5枚を見て
     海王類/魚人島 カード1枚を手札 → 残りデッキ下 (activate_main search_top_n depth5)
  OP11-031 ジンベエ (CHARACTER 緑) = 【登場時】自リーダー魚人族/人魚族なら 相手コスト5以下キャラ
     1枚レスト /【起動メイン】【ターン1回】自魚人族/人魚族キャラ1枚まで キャラへアタック可
     (on_play rest cost_le_5 / activate_main give_keyword 速攻：キャラ)
  OP11-034 はっちゃん (CHARACTER 緑) = 【起動メイン】(自レスト)：自リーダー魚人族/人魚族なら
     相手コスト3以下キャラ1枚まで 次相手ターン終了まで レスト不能
     (activate_main set_cannot_rest one_opponent_character_cost_le_3)
  OP11-035 フィッシャー・タイガー (CHARACTER 緑) = 相手効果KO時 (任意、 ドン1レスト)：手札から
     コスト4以下の 魚人族/人魚族 キャラ1枚まで登場 /【登場時】相手キャラ1枚までをレスト
     (on_ko by_opp_effect play_from_hand_choice cost_le4 / on_play rest one_opponent_character_any)
  OP11-037 “古代兵器”「ポセイドン」 (EVENT 緑) = 【メイン】デッキ上4枚を見て 海王類/魚人島 キャラ
     1枚を手札 → 残りデッキ下 / トリガー 1ドロー (main search_top_n depth4 / trigger draw1)
  OP11-038 ゴムゴムの象銃乱打 (EVENT 緑) = 【メイン】(ドン1レスト)：相手コスト5以下キャラ1枚まで
     レスト /【カウンター】自リーダー1枚まで このバトル中 +3000
     (main rest cost_le_5 / counter power_pump self_leader +3000)

目的 (= test_backfill_auto_001〜110.py と同一方針):
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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_GENERIC = "OP01-001"     # ロロノア・ゾロ (超新星/麦わらの一味 — 汎用埋め)
_LEADER_GYOJIN = "OP14-040"      # ジンベエ LEADER (魚人族/王下七武海/タイヨウの海賊団)
_FILLER = "ST01-004"             # サンジ cost2 power4000 (麦わらの一味、 非魚人族)
_FILLER_P1000 = "OP16-043"       # ウソップ cost2 power1000
_FISH_C = "OP16-023"             # アーロン cost1 power3000 魚人族 (vanilla overlay)
_FISH_C2 = "OP03-101"            # ケイミー cost1 power3000 人魚族 (vanilla overlay)
_SEA_C = "OP15-030"              # ヒョウゾウ cost5 power6000 人魚族/魚人島 (vanilla)
_SEA_C2 = "OP13-010"             # 近海の主 cost6 power8000 海王類/東の海 (vanilla)


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
def test_all_wave111_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP11-024", "OP11-025", "OP11-028", "OP11-029", "OP11-030",
           "OP11-031", "OP11-034", "OP11-035", "OP11-037", "OP11-038"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP11-024 アラディン: 相手効果KO時 (任意) → 手札から魚人族/人魚族 cost6以下を登場
# --------------------------------------------------------------------------- #
def test_op11_024_on_ko_play_from_hand_ai():
    """相手効果KO時 do: 手札の魚人族/人魚族 cost6以下キャラ1枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FISH_C)]  # アーロン 魚人族 cost1 (≤6)

    chars_before = len(me.characters)
    for prim in _eff(overlay, "OP11-024", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-024"), sickness=False))
    _drain(st, [0])
    assert any(c.card.card_id == _FISH_C for c in me.characters), \
        "手札から魚人族キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"
    assert not any(c.card_id == _FISH_C for c in me.hand), \
        "登場したキャラが手札に残っている"


def test_op11_024_on_ko_play_from_hand_human_pick():
    """人間 + 手札に魚人族/人魚族 複数 → play_from_hand_pick modal → resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FISH_C), repo.get(_FISH_C2)]  # アーロン / ケイミー

    execute_effect(_eff(overlay, "OP11-024", "on_ko")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-024"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2枚でない: {len(cands)}"

    ke_idx = next(i for i, c in enumerate(cands) if c["card_id"] == _FISH_C2)
    resolve_pending_choice(st, [ke_idx])
    _drain(st, [0])
    assert any(c.card.card_id == _FISH_C2 for c in me.characters), \
        "人間が選んだ人魚族キャラ (ケイミー) が登場していない"


# --------------------------------------------------------------------------- #
#  OP11-025 イシリー: 【相手のアタック時】自リーダーかキャラ1枚まで +1000
# --------------------------------------------------------------------------- #
def test_op11_025_opp_attack_pump_ai():
    """【相手のアタック時】do: 自リーダー (既定) を このバトル中 +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "OP11-025", "opp_attack")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-025"), sickness=False))
    _drain(st, [0])
    assert me.leader.power == power_before + 1000, \
        f"相手アタック時の自リーダー +1000 が反映されていない: {me.leader.power}"


def test_op11_025_opp_attack_pump_human_pick():
    """人間 + 自リーダー + 自キャラ → +1000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000 < leader 5000
    me.characters = [friend]

    execute_effect(_eff(overlay, "OP11-025", "opp_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-025"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 1000, \
        "人間が選んだキャラに +1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP11-028 近海の主: 【登場時】相手レストキャラ1枚 stay_rested / トリガー rested cost3以下 KO
# --------------------------------------------------------------------------- #
def test_op11_028_on_play_stay_rested_ai():
    """【登場時】相手のレストキャラ1枚まで 次の相手リフレッシュでアクティブにならない (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True  # レスト = 対象
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-028", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-028"), sickness=True))
    _drain(st, [0])
    assert victim.stay_rested_next_refresh is True, \
        "相手レストキャラに stay_rested_next_refresh が付与されていない"


def test_op11_028_on_play_ignores_active_target():
    """相手キャラが アクティブ (非レスト) なら 対象外 → stay_rested が付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    active = InPlay.of(repo.get(_FILLER), sickness=False)
    active.rested = False  # アクティブ = 対象外
    opp.characters = [active]

    for prim in _eff(overlay, "OP11-028", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-028"), sickness=True))
    _drain(st, [0])
    assert active.stay_rested_next_refresh is False, \
        "アクティブキャラに stay_rested が付いてはいけない (対象外)"


def test_op11_028_on_play_stay_rested_human_pick():
    """人間 + 相手レストキャラ複数 → target_pick modal → resolve で1枚に stay_rested。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP11-028", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-028"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.stay_rested_next_refresh is True, \
        "人間が選んだレストキャラに stay_rested が付いていない"
    assert a.stay_rested_next_refresh is False, "選ばなかったキャラには付かないべき"


def test_op11_028_trigger_ko_rested_cost3_ai():
    """トリガー: 相手のレストのコスト3以下キャラ1枚をKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 3
    victim.rested = True
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-028", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, \
        "トリガーで 相手レストのコスト3以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP11-029 シャーロット・プラリネ: 【登場時】相手コスト1以下キャラ1枚をレスト
# --------------------------------------------------------------------------- #
def test_op11_029_on_play_rest_cost1_ai():
    """【登場時】相手のコスト1以下キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FISH_C), sickness=False)  # cost1 ≤ 1
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-029", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-029"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, "登場時に 相手コスト1以下キャラがレストにされていない"


def test_op11_029_on_play_ignores_cost2():
    """相手のコスト2キャラは 対象外 (コスト1以下でない) → レストされない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 > 1
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-029", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-029"), sickness=True))
    _drain(st, [0])
    assert victim.rested is False, "コスト2キャラがレストされてはいけない (対象外)"


def test_op11_029_on_play_rest_human_pick():
    """人間 + 相手コスト1以下キャラ複数 → target_pick modal → resolve で1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FISH_C), sickness=False)   # cost1
    b = InPlay.of(repo.get(_FISH_C2), sickness=False)  # cost1
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP11-029", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-029"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP11-030 しらほし: 【起動メイン】デッキ上5枚 → 海王類/魚人島 1枚を手札
# --------------------------------------------------------------------------- #
def test_op11_030_activate_main_search_ai():
    """起動メイン: (自レスト+ドン1) デッキ上5枚を見て 海王類/魚人島 カード1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    shirahoshi = InPlay.of(repo.get("OP11-030"), sickness=False)
    me.characters = [shirahoshi]
    me.don_active = 2
    me.hand = []
    me.deck = [repo.get(_SEA_C)] + [repo.get(_FILLER)] * 20  # 上に 魚人島 キャラ

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-030"]
    assert len(opts) == 1, f"OP11-030 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert any(c.card_id == _SEA_C for c in me.hand), \
        "デッキ上5枚から 海王類/魚人島 カードが手札に加わっていない"
    assert shirahoshi.rested is True, "起動メインコストで しらほし がレストされるべき"


def test_op11_030_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    shirahoshi = InPlay.of(repo.get("OP11-030"), sickness=False)
    me.characters = [shirahoshi]
    me.don_active = 3
    me.deck = [repo.get(_SEA_C)] + [repo.get(_FILLER)] * 20

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-030"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-030"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op11_030_activate_main_search_human_pick():
    """人間 + デッキ上5枚に 海王類/魚人島 → search_top_n modal → resolve で手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    shirahoshi = InPlay.of(repo.get("OP11-030"), sickness=False)
    me.characters = [shirahoshi]
    me.don_active = 2
    me.hand = []
    me.deck = [repo.get(_SEA_C), repo.get(_FILLER), repo.get(_SEA_C2)] \
        + [repo.get(_FILLER)] * 15

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-030"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (ヒョウゾウ) を選択
    _drain(st, [])
    assert any(c.card_id == _SEA_C for c in me.hand), \
        "人間が選んだ 魚人島 カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP11-031 ジンベエ: 【登場時】相手コスト5以下レスト / 起動メイン 魚人族に速攻：キャラ
# --------------------------------------------------------------------------- #
def test_op11_031_on_play_rest_cost5_ai():
    """【登場時】相手のコスト5以下キャラ1枚をレスト (AI 自動、 魚人族リーダー前提)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay)  # 魚人族リーダー = 条件成立
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 5
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-031", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-031"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, "登場時に 相手コスト5以下キャラがレストにされていない"


def test_op11_031_on_play_rest_human_pick():
    """人間 + 相手コスト5以下キャラ複数 → target_pick modal → resolve で1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)       # cost2
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)  # cost2
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP11-031", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-031"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    a_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st, [0])
    assert a.rested is True, "人間が選んだ相手キャラがレストにされていない"


def test_op11_031_activate_main_give_rush_chara_ai():
    """起動メイン: 自魚人族/人魚族キャラ1枚まで 速攻：キャラ を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("OP11-031"), sickness=False)  # 魚人族
    me.characters = [jinbe]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-031"]
    assert len(opts) == 1, f"OP11-031 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert "速攻：キャラ" in jinbe.granted_keywords, \
        "自魚人族キャラに 速攻：キャラ が付与されていない"


def test_op11_031_activate_main_give_rush_human_pick():
    """人間 + 自魚人族/人魚族キャラ複数 → target_pick modal → resolve で1枚に付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    jinbe = InPlay.of(repo.get("OP11-031"), sickness=False)   # 魚人族 power8000
    aaron = InPlay.of(repo.get(_FISH_C), sickness=False)      # 魚人族 power3000
    me.characters = [jinbe, aaron]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-031"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    aaron_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                     if c["iid"] == aaron.instance_id)
    resolve_pending_choice(st, [aaron_idx])
    _drain(st, [0])
    assert "速攻：キャラ" in aaron.granted_keywords, \
        "人間が選んだ魚人族キャラに 速攻：キャラ が付与されていない"


# --------------------------------------------------------------------------- #
#  OP11-034 はっちゃん: 【起動メイン】相手コスト3以下キャラ1枚 レスト不能
# --------------------------------------------------------------------------- #
def test_op11_034_activate_main_set_cannot_rest_ai():
    """起動メイン: (自レスト) 相手コスト3以下キャラ1枚まで レスト不能 (AI 自動、 魚人族リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay)
    me, opp = st.players[0], st.players[1]
    hachi = InPlay.of(repo.get("OP11-034"), sickness=False)
    me.characters = [hachi]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 3
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-034"]
    assert len(opts) == 1, f"OP11-034 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert hachi.rested is True, "起動メインコストで はっちゃん がレストされるべき"
    assert victim.cannot_be_rested_buff is True, \
        "相手コスト3以下キャラに レスト不能 が付与されていない"


def test_op11_034_activate_main_set_cannot_rest_human_pick():
    """人間 + 相手コスト3以下キャラ複数 → target_pick modal → resolve で1枚に レスト不能。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hachi = InPlay.of(repo.get("OP11-034"), sickness=False)
    me.characters = [hachi]
    a = InPlay.of(repo.get(_FILLER), sickness=False)       # cost2
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)  # cost2
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-034"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.cannot_be_rested_buff is True, \
        "人間が選んだ相手キャラに レスト不能 が付与されていない"
    assert a.cannot_be_rested_buff is False, "選ばなかったキャラには付かないべき"


# --------------------------------------------------------------------------- #
#  OP11-035 フィッシャー・タイガー: 相手効果KO時 手札から魚人族 cost4以下登場 /
#                                    【登場時】相手キャラ1枚レスト
# --------------------------------------------------------------------------- #
def test_op11_035_on_ko_play_from_hand_ai():
    """相手効果KO時 do: 手札の魚人族/人魚族 cost4以下キャラ1枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FISH_C)]  # アーロン 魚人族 cost1 (≤4)

    chars_before = len(me.characters)
    for prim in _eff(overlay, "OP11-035", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-035"), sickness=False))
    _drain(st, [0])
    assert any(c.card.card_id == _FISH_C for c in me.characters), \
        "手札から魚人族キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"


def test_op11_035_on_play_rest_any_ai():
    """【登場時】相手キャラ1枚まで をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-035", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-035"), sickness=True))
    _drain(st, [0])
    assert victim.rested is True, "登場時に 相手キャラがレストにされていない"


def test_op11_035_on_play_rest_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal → resolve で1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP11-035", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-035"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  OP11-037 “古代兵器”「ポセイドン」 (EVENT): 【メイン】上4枚→海王類/魚人島キャラ手札 / トリガー draw1
# --------------------------------------------------------------------------- #
def test_op11_037_main_search_ai():
    """【メイン】デッキ上4枚を見て 海王類/魚人島 キャラ1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_SEA_C2)] + [repo.get(_FILLER)] * 20  # 上に 海王類 キャラ

    for prim in _eff(overlay, "OP11-037", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [])
    assert any(c.card_id == _SEA_C2 for c in me.hand), \
        "デッキ上4枚から 海王類/魚人島 キャラが手札に加わっていない"


def test_op11_037_main_search_human_pick():
    """人間 + デッキ上4枚に 海王類/魚人島 → search_top_n modal → resolve で手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_SEA_C), repo.get(_FILLER), repo.get(_SEA_C2)] \
        + [repo.get(_FILLER)] * 15

    execute_effect(_eff(overlay, "OP11-037", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [])
    assert any(c.card_id == _SEA_C for c in me.hand), \
        "人間が選んだ 海王類/魚人島 キャラが手札に加わっていない"


def test_op11_037_trigger_draw_ai():
    """トリガー: カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    hand_before = len(me.hand)
    for prim in _eff(overlay, "OP11-037", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, "トリガーの 1 ドローが起きていない"


# --------------------------------------------------------------------------- #
#  OP11-038 ゴムゴムの象銃乱打 (EVENT): 【メイン】相手コスト5以下レスト /【カウンター】自リーダー +3000
# --------------------------------------------------------------------------- #
def test_op11_038_main_rest_cost5_ai():
    """【メイン】(ドン1レスト) 相手のコスト5以下キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 5
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-038", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.rested is True, "メインで 相手コスト5以下キャラがレストにされていない"


def test_op11_038_main_rest_human_pick():
    """人間 + 相手コスト5以下キャラ複数 → target_pick modal → resolve で1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)       # cost2
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)  # cost2
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP11-038", "main")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


def test_op11_038_counter_pump_leader_ai():
    """【カウンター】自リーダー1枚まで このバトル中 +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "OP11-038", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"
