# -*- coding: utf-8 -*-
"""OP11 弾 赤 (海軍/SWORD・麦わらの一味) + 緑 (魚人族) 効果 回帰テスト
バックフィル (自動生成 wave 110):
OP11-008 / OP11-009 / OP11-010 / OP11-012 / OP11-014 / OP11-016 /
OP11-018 / OP11-019 / OP11-020 / OP11-023 の 10 枚。

  OP11-008 ドール (CHARACTER 赤) = 【ブロッカー】【登場時】手札1枚捨てる：自リーダー海軍なら
     相手キャラ1枚まで このターン中 パワー-6000 (on_play, cost discard_hand1, if leader_feature=海軍)
  OP11-009 ニコ・ロビン (CHARACTER 赤) = 【ドン‼×2】【アタック時】相手キャラ1枚まで
     次の相手ターン終了時まで パワー-2000 (on_attack, if self_attached_don_ge=2, duration next_opp_turn_end)
  OP11-010 ひばり (CHARACTER 赤) = 【登場時】相手キャラ1枚 -2000 /【アタック時】自身 +1000。
     その後 自海軍リーダー1枚まで アクティブキャラにもアタック可 (give_attack_active_chara)
  OP11-012 フランキー (CHARACTER 赤) = 【自分のターン中】【ターン1回】相手がイベントを発動した時
     自分のキャラすべて このターン中 +2000 (opp_event_played, all_self_characters)
  OP11-014 ボルサリーノ (CHARACTER 赤) = 【ブロッカー】【起動メイン】自レスト：自海軍のリーダーか
     キャラ1枚まで アクティブキャラにもアタック可 (activate_main, cost rest_self, filter feature=海軍)
  OP11-016 ロロノア・ゾロ (CHARACTER 赤) = 【起動メイン】【ターン1回】自リーダーかキャラ1枚に
     レストのドン‼1枚まで付与 (activate_main, attach_rested_don self_inplay_choice count1)
  OP11-018 実直拳骨 (EVENT 赤) = 【メイン】相手キャラ1枚 -4000。その後 相手のパワー6000以下キャラ
     1枚KO / トリガー パワー6000以下キャラ1枚KO (power_pump -4000 → ko power_le_6000)
  OP11-019 粘土の巣 (EVENT 赤) = 【カウンター】自リーダーかキャラ1枚 +2000。その後 相手パワー6000以上が
     いれば +1000 / トリガー +1000 (counter power_pump self_inplay, if exists_opp_chara_power_ge=6000)
  OP11-020 X狩場 (EVENT 赤) = 【メイン】相手キャラ2枚まで -2000。その後 自海軍キャラ1枚まで +1000 /
     トリガー パワー4000以下キャラ1枚KO (all_opponent_chara_filtered limit2 → one_self_chara_filtered 海軍)
  OP11-023 アーロン (CHARACTER 緑) = 手札のこのカードは 魚人族leader + 自ライフ3以下 + 相手レスト5枚以上で
     コスト-3 / トリガー 相手コスト4以下キャラ1枚レスト (in_hand cost_minus, trigger rest cost_le_4)

目的 (= test_backfill_auto_001〜109.py と同一方針):
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
from engine.game import _compute_in_hand_cost_minus

ROOT = Path(__file__).resolve().parent.parent

_LEADER_GENERIC = "OP01-001"     # ロロノア・ゾロ (超新星/麦わらの一味 — 汎用埋め)
_LEADER_NAVY = "OP16-060"        # センゴク (海軍)
_LEADER_GYOJIN = "OP14-040"      # ジンベエ (魚人族/王下七武海/タイヨウの海賊団)
_FILLER = "ST01-004"             # サンジ cost2 power4000 (麦わらの一味、 非海軍)
_FILLER_P1000 = "OP16-043"       # ウソップ cost2 power1000
_NAVY_C = "PRB02-001"            # コビー cost4 power5000 海軍
_BIG_C = "PRB02-013"             # ゲッコー・モリア cost6 power7000 (パワー6000以上)


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
def test_all_wave110_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP11-008", "OP11-009", "OP11-010", "OP11-012", "OP11-014",
           "OP11-016", "OP11-018", "OP11-019", "OP11-020", "OP11-023"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP11-008 ドール: 【登場時】(手札1捨て + 海軍リーダー) 相手キャラ1枚 -6000
# --------------------------------------------------------------------------- #
def test_op11_008_on_play_debuff_ai():
    """【登場時】AI: 相手キャラ1枚を このターン中 パワー-6000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay)  # 海軍リーダー (条件成立)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAVY_C), sickness=False)  # power 5000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _eff(overlay, "OP11-008", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-008"), sickness=True))
    _drain(st, [0])
    assert victim.power == power_before - 6000, \
        f"登場時の -6000 が反映されていない: {victim.power} (before {power_before})"


def test_op11_008_on_play_human_target_pick():
    """人間 + 相手キャラ複数 → target_pick modal → resolve で1枚に -6000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAVY_C), sickness=False)   # power 5000
    b = InPlay.of(repo.get(_FILLER), sickness=False)   # power 4000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP11-008", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-008"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert b.power == b_before - 6000, "人間が選んだ相手キャラに -6000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP11-009 ニコ・ロビン: 【ドン‼×2】【アタック時】相手キャラ1枚 -2000 (次相手ターン終了まで)
# --------------------------------------------------------------------------- #
def test_op11_009_on_attack_debuff_ai():
    """【アタック時】(ドン2ゲート) 相手キャラ1枚を -2000。 AI 自動選択。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    opp.characters = [victim]

    on_attack = _eff(overlay, "OP11-009", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"
    power_before = victim.power
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-009"), sickness=False))
    _drain(st, [0])
    assert victim.power == power_before - 2000, \
        f"アタック時の -2000 が反映されていない: {victim.power} (before {power_before})"


def test_op11_009_on_attack_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal → resolve で1枚 -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)       # 4000
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)  # 1000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP11-009", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP11-009"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    a_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == a.instance_id)
    a_before = a.power
    resolve_pending_choice(st, [a_idx])
    assert a.power == a_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP11-010 ひばり: 【登場時】相手1枚 -2000 /【アタック時】自身 +1000 + 自リーダー アクティブアタック可
# --------------------------------------------------------------------------- #
def test_op11_010_on_play_debuff_ai():
    """【登場時】AI: 相手キャラ1枚を このターン中 -2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAVY_C), sickness=False)  # 5000
    opp.characters = [victim]

    power_before = victim.power
    for prim in _eff(overlay, "OP11-010", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-010"), sickness=True))
    _drain(st, [0])
    assert victim.power == power_before - 2000, \
        f"登場時の -2000 が反映されていない: {victim.power}"


def test_op11_010_on_attack_self_pump_and_leader_active_attack():
    """【アタック時】自身 +1000 + 自リーダーが アクティブアタック可 を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay)
    me, opp = st.players[0], st.players[1]
    hibari = InPlay.of(repo.get("OP11-010"), sickness=False)  # power 6000
    me.characters = [hibari]

    power_before = hibari.power
    for prim in _eff(overlay, "OP11-010", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, hibari)
    _drain(st, [0])
    assert hibari.power == power_before + 1000, \
        f"アタック時の自己 +1000 が反映されていない: {hibari.power}"
    assert "アクティブアタック可" in me.leader.granted_keywords, \
        "自リーダーに アクティブアタック可 が付与されていない"


# --------------------------------------------------------------------------- #
#  OP11-012 フランキー: 相手がイベントを発動した時 自分のキャラすべて +2000
# --------------------------------------------------------------------------- #
def test_op11_012_all_self_characters_pump_ai():
    """相手イベント発動時: 自分のキャラすべてを このターン中 +2000。 対象選択なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    c1 = InPlay.of(repo.get(_FILLER), sickness=False)       # 4000
    c2 = InPlay.of(repo.get(_FILLER_P1000), sickness=False)  # 1000
    me.characters = [c1, c2]

    b1, b2 = c1.power, c2.power
    eff = _eff(overlay, "OP11-012", "opp_event_played")
    assert eff.get("if", {}).get("self_turn") is True, \
        "overlay の 自ターン中条件 self_turn=true が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-012"), sickness=False))
    _drain(st, [0])
    assert c1.power == b1 + 2000 and c2.power == b2 + 2000, \
        f"自分のキャラ全員 +2000 が反映されていない: {c1.power}/{c2.power}"


# --------------------------------------------------------------------------- #
#  OP11-014 ボルサリーノ: 【起動メイン】自レスト → 自海軍のリーダーかキャラ アクティブアタック可
# --------------------------------------------------------------------------- #
def test_op11_014_activate_main_grant_active_attack_ai():
    """起動メイン: 自レスト (コスト) → 自海軍リーダーに アクティブアタック可 を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay)  # リーダーが海軍 = 唯一の候補
    me, opp = st.players[0], st.players[1]
    boru = InPlay.of(repo.get("OP11-014"), sickness=False)
    me.characters = [boru]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-014"]
    assert len(opts) == 1, f"OP11-014 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert boru.rested is True, "起動メインコストで ボルサリーノ がレストされるべき"
    assert "アクティブアタック可" in me.leader.granted_keywords, \
        "自海軍リーダーに アクティブアタック可 が付与されていない"


def test_op11_014_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay)
    me, opp = st.players[0], st.players[1]
    boru = InPlay.of(repo.get("OP11-014"), sickness=False)
    me.characters = [boru]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-014"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-014"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op11_014_activate_main_human_target_pick():
    """人間 + 海軍リーダー + 海軍キャラ (2候補) → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    boru = InPlay.of(repo.get("OP11-014"), sickness=False)
    navy_c = InPlay.of(repo.get(_NAVY_C), sickness=False)  # コビー 海軍
    me.characters = [boru, navy_c]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-014"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    # リーダー (海軍) + ボルサリーノ自身 (FILM/海軍) + コビー (海軍) = 3 候補
    assert len(cands) == 3, f"海軍 候補が3件でない: {len(cands)}"
    navy_idx = next(i for i, c in enumerate(cands) if c["iid"] == navy_c.instance_id)
    resolve_pending_choice(st, [navy_idx])
    _drain(st, [0])
    assert "アクティブアタック可" in navy_c.granted_keywords, \
        "人間が選んだ海軍キャラに アクティブアタック可 が付与されていない"


# --------------------------------------------------------------------------- #
#  OP11-016 ロロノア・ゾロ: 【起動メイン】自リーダーかキャラに レストドン1まで付与
# --------------------------------------------------------------------------- #
def test_op11_016_activate_main_attach_rested_don_ai():
    """起動メイン: 自リーダーに レストドン1付与 (AI 自動、 リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP11-016"), sickness=False)
    me.characters = [zoro]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-016"]
    assert len(opts) == 1, f"OP11-016 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])
    assert me.leader.attached_dons == don_before + 1, \
        "起動メインで自リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_op11_016_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP11-016"), sickness=False)
    me.characters = [zoro]
    me.don_rested = 3

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-016"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-016"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op11_016_activate_main_human_target_pick():
    """人間 + 自リーダー + 自キャラ → 付与先選択 target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("OP11-016"), sickness=False)
    me.characters = [zoro]
    me.don_rested = 2

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-016"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    # リーダー + ゾロ自身 = 2 候補
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    zoro_idx = next(i for i, c in enumerate(cands) if c["iid"] == zoro.instance_id)
    resolve_pending_choice(st, [zoro_idx])
    _drain(st, [0])
    assert zoro.attached_dons == 1, "人間が選んだキャラにレストドンが付与されていない"


# --------------------------------------------------------------------------- #
#  OP11-018 実直拳骨 (EVENT): 【メイン】相手1枚 -4000 → パワー6000以下キャラ1枚KO
# --------------------------------------------------------------------------- #
def test_op11_018_main_debuff_then_ko_ai():
    """【メイン】相手キャラ1枚 -4000 → その後 パワー6000以下キャラ1枚KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000
    opp.characters = [victim]

    do = _eff(overlay, "OP11-018", "main")["do"]
    # (1) power_pump -4000
    execute_effect(do[0], st, me, opp, None)
    _drain(st, [0])
    assert victim.power == 0, f"-4000 後の power が 0 でない: {victim.power}"
    # (2) ko power_le_6000 → KO
    execute_effect(do[1], st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "パワー6000以下キャラが KO されていない"


def test_op11_018_trigger_ko_ai():
    """トリガー: 相手のパワー6000以下キャラ1枚をKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAVY_C), sickness=False)  # power 5000 ≤ 6000
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-018", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "トリガーで パワー6000以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP11-019 粘土の巣 (EVENT): 【カウンター】自 +2000 / 相手6000以上あれば +1000 / トリガー +1000
# --------------------------------------------------------------------------- #
def test_op11_019_counter_pump_ai():
    """【カウンター】(1) 自リーダーorキャラ1枚 +2000。 AI 自動 (リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]

    counter_pump = _eff(overlay, "OP11-019", "counter", needle="power_pump")
    power_before = me.leader.power
    for prim in counter_pump["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op11_019_counter_conditional_extra_pump_ai():
    """【カウンター】(2) 相手にパワー6000以上のキャラがいる場合 +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    big = InPlay.of(repo.get(_BIG_C), sickness=False)  # power 7000 ≥ 6000
    opp.characters = [big]

    # 条件付き第2効果 (exists_opp_chara_power_ge=6000)
    cond_eff = next(e for e in overlay.get("OP11-019").effects
                    if e.get("when") == "counter"
                    and e.get("if", {}).get("exists_opp_chara_power_ge") == 6000)
    power_before = me.leader.power
    for prim in cond_eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 1000, \
        f"相手パワー6000以上時の +1000 が反映されていない: {me.leader.power}"


def test_op11_019_counter_pump_human_pick():
    """人間 + 自リーダー + 自キャラ → +2000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    counter_pump = _eff(overlay, "OP11-019", "counter", needle="power_pump")
    execute_effect(counter_pump["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


def test_op11_019_trigger_pump_ai():
    """トリガー: 自リーダーかキャラ1枚 +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _eff(overlay, "OP11-019", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == power_before + 1000, \
        f"トリガーの +1000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP11-020 X狩場 (EVENT): 【メイン】相手2枚 -2000 → 自海軍キャラ1枚 +1000 / トリガー KO
# --------------------------------------------------------------------------- #
def test_op11_020_main_mass_debuff_then_navy_pump_ai():
    """【メイン】相手キャラ2枚 -2000 → その後 自海軍キャラ1枚 +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NAVY, overlay)
    me, opp = st.players[0], st.players[1]
    v1 = InPlay.of(repo.get(_FILLER), sickness=False)       # 4000
    v2 = InPlay.of(repo.get(_FILLER_P1000), sickness=False)  # 1000
    opp.characters = [v1, v2]
    navy_c = InPlay.of(repo.get(_NAVY_C), sickness=False)   # コビー 海軍 5000
    me.characters = [navy_c]

    b1, b2, bn = v1.power, v2.power, navy_c.power
    do = _eff(overlay, "OP11-020", "main")["do"]
    # (1) 相手2枚 -2000
    execute_effect(do[0], st, me, opp, None)
    _drain(st, [0])
    assert v1.power == b1 - 2000 and v2.power == b2 - 2000, \
        f"相手キャラ2枚 -2000 が反映されていない: {v1.power}/{v2.power}"
    # (2) 自海軍キャラ1枚 +1000
    execute_effect(do[1], st, me, opp, None)
    _drain(st, [0])
    assert navy_c.power == bn + 1000, \
        f"自海軍キャラ +1000 が反映されていない: {navy_c.power}"


def test_op11_020_trigger_ko_ai():
    """トリガー: 相手のパワー4000以下キャラ1枚をKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 4000 ≤ 4000
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-020", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "トリガーで パワー4000以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP11-023 アーロン: 手札コスト-3 (魚人族leader+自ライフ3以下+相手レスト5以上) / トリガー レスト
# --------------------------------------------------------------------------- #
def test_op11_023_in_hand_cost_minus_condition_met():
    """魚人族leader + 自ライフ3以下 + 相手レスト5枚以上 → 手札の アーロン は コスト-3。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay)  # ジンベエ (魚人族)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3   # 自ライフ 3 (≤ 3)
    opp.don_rested = 5                   # 相手レストカード 5 枚 (≥ 5)

    aaron = repo.get("OP11-023")
    minus = _compute_in_hand_cost_minus(st, me, aaron)
    assert minus == 3, f"条件成立時に手札コスト-3 が適用されない: {minus}"


def test_op11_023_in_hand_cost_minus_condition_unmet():
    """条件未成立 (相手レスト不足) → コスト軽減なし (0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GYOJIN, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    opp.don_rested = 2  # 相手レスト 2 枚 (< 5) = 条件未成立

    aaron = repo.get("OP11-023")
    minus = _compute_in_hand_cost_minus(st, me, aaron)
    assert minus == 0, f"条件未成立なのに手札コスト軽減が乗っている: {minus}"


def test_op11_023_in_hand_cost_minus_non_gyojin_leader():
    """魚人族でないリーダー → 条件未成立 → コスト軽減なし (0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)  # 麦わらの一味 (非魚人族)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    opp.don_rested = 5

    aaron = repo.get("OP11-023")
    minus = _compute_in_hand_cost_minus(st, me, aaron)
    assert minus == 0, f"非魚人族リーダーで手札コスト軽減が乗ってはいけない: {minus}"


def test_op11_023_trigger_rest_ai():
    """トリガー: 相手のコスト4以下キャラ1枚をレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 ≤ 4
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "OP11-023", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.rested is True, "トリガーで 相手コスト4以下キャラがレストにされていない"


def test_op11_023_trigger_rest_human_pick():
    """人間 + 相手コスト4以下キャラ複数 → target_pick modal → resolve で1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GENERIC, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)       # cost2
    b = InPlay.of(repo.get(_FILLER_P1000), sickness=False)  # cost2
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP11-023", "trigger")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    b_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                 if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"
