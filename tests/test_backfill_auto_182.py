# -*- coding: utf-8 -*-
"""ST21 / ST22 弾 効果 回帰テスト バックフィル (自動生成 wave 182):
ST21-002 / ST21-009 / ST21-010 / ST21-011 / ST21-012 / ST21-014 /
ST21-015 / ST21-016 / ST21-017 / ST22-001 の 10 枚。

  ST21-002 ウソップ (CHARACTER 赤) = 【ドン‼×2】【相手のターン中】このキャラのパワー+2000
     (on_attached_don n=2, if opp_turn, power_pump self static)
  ST21-009 ナミ (CHARACTER 赤) = 【起動メイン】【ターン1回】自麦わらの一味リーダーかキャラ1枚に
     レストのドン‼2枚まで付与 (activate_main, attach_rested_don filter 麦わらの一味 count2)
  ST21-010 ニコ・ロビン (CHARACTER 赤) = 【ドン‼×2】【アタック時】相手パワー4000以下キャラ1枚KO
     (on_attack, if self_attached_don_ge=2, ko power_le_4000)
  ST21-011 フランキー (CHARACTER 赤) = 【ドン‼×2】【相手のターン中】自元々パワー4000以下の
     麦わらの一味キャラすべて +1000 (on_attached_don n=2, if opp_turn, power_pump all_self_chara_filtered)
  ST21-012 ブルック (CHARACTER 赤) = 【アタック時】自リーダーかキャラ1枚に レストのドン‼2枚まで付与
     (on_attack, attach_rested_don self_inplay_choice count2)
  ST21-014 モンキー・D・ルフィ (CHARACTER 赤) = 【速攻】【アタック時】自リーダーかキャラ1枚に
     レストのドン‼1枚まで付与 (on_attack, attach_rested_don self_inplay_choice count1)
  ST21-015 ロロノア・ゾロ (CHARACTER 赤) = 【ドン‼×2】速攻獲得 /【KO時】手札から「ゾロ」以外の
     赤パワー6000以下キャラ1枚まで登場 (on_attached_don give_keyword 速攻, on_ko play_from_hand)
  ST21-016 ゴムゴムの白い鞭 (EVENT 赤) = 【メイン】自1枚 +1000 → 相手パワー4000以下1枚ブロッカー無効 /
     トリガー パワー4000以下キャラ1枚KO (main power_pump + disable_blocker, trigger ko)
  ST21-017 ゴムゴムのモグラ銃 (EVENT 赤) = 【メイン】相手1枚 -5000 → 自パワー6000以上あれば相手2000以下KO /
     トリガー メイン効果を発動 (main power_pump -5000 + cond ko, trigger fire_self_effect)
  ST22-001 エース＆ニューゲート (LEADER 青) = 【起動メイン】【ターン1回】白ひげ海賊団カード公開：
     1枚引き公開カードをデッキ上へ (activate_main, if self_hand_has_feature, draw + discard_self_to_deck_top)

目的 (= test_backfill_auto_001〜181.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_RED = "OP01-001"     # ロロノア・ゾロ (超新星/麦わらの一味) — 赤の汎用リーダー
_FILLER = "OP01-016"         # ナミ cost1 power2000 麦わらの一味
_MUGI_C = "OP01-013"         # サンジ cost2 power3000 麦わらの一味
_BIG_C = "PRB02-013"         # ゲッコー・モリア cost6 power7000 (パワー6000超)
_SANJI4 = "ST01-004"         # サンジ cost2 power4000 麦わらの一味


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
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
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


def _total_attached(player) -> int:
    """リーダー + 全キャラ に付与されているドンの総数。"""
    return player.leader.attached_dons + sum(c.attached_dons for c in player.characters)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave182_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST21-002", "ST21-009", "ST21-010", "ST21-011", "ST21-012",
           "ST21-014", "ST21-015", "ST21-016", "ST21-017", "ST22-001"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST21-002 ウソップ: 【ドン‼×2】【相手のターン中】このキャラのパワー+2000
# --------------------------------------------------------------------------- #
def test_st21_002_static_pump_opp_turn():
    """静的 (on_attached_don n=2、 相手ターン中): 自身 static_buff +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay, turn_player=1)  # 相手 (P1) のターン
    me = st.players[0]
    usopp = InPlay.of(repo.get("ST21-002"), sickness=False)
    usopp.attached_dons = 2  # 【ドン‼×2】 ゲート成立
    me.characters = [usopp]

    assert eval_condition({"opp_turn": True}, st, me) is True, \
        "テスト前提: 相手ターンでない"
    evaluate_static_effects(st, overlay)
    assert usopp.static_buff == 2000, \
        f"相手ターン中 ドン2 で static_buff +2000 が乗っていない: {usopp.static_buff}"


def test_st21_002_static_no_pump_self_turn():
    """自分のターン中は【相手のターン中】条件不成立 → static_buff +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay, turn_player=0)  # 自分のターン
    me = st.players[0]
    usopp = InPlay.of(repo.get("ST21-002"), sickness=False)
    usopp.attached_dons = 2
    me.characters = [usopp]

    evaluate_static_effects(st, overlay)
    assert usopp.static_buff == 0, \
        f"自分のターンで +2000 が乗ってはいけない: {usopp.static_buff}"


def test_st21_002_static_no_pump_without_don():
    """ドン付与が 2 未満 なら【ドン‼×2】ゲート不成立 → static_buff +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay, turn_player=1)
    me = st.players[0]
    usopp = InPlay.of(repo.get("ST21-002"), sickness=False)
    usopp.attached_dons = 1  # ドン1 → ゲート不成立
    me.characters = [usopp]

    evaluate_static_effects(st, overlay)
    assert usopp.static_buff == 0, \
        f"ドン1 で +2000 が乗ってはいけない: {usopp.static_buff}"


# --------------------------------------------------------------------------- #
#  ST21-009 ナミ: 【起動メイン】【ターン1回】自麦わらの一味リーダーかキャラ1枚に
#                 レストのドン‼2枚まで付与
# --------------------------------------------------------------------------- #
def test_st21_009_activate_main_attach_rested_don_ai():
    """起動メイン: 自麦わらの一味の対象へ レストドン2枚付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)  # リーダー 麦わらの一味
    me, opp = st.players[0], st.players[1]
    nami = InPlay.of(repo.get("ST21-009"), sickness=False)
    me.characters = [nami]
    me.don_rested = 3

    attached_before = _total_attached(me)
    rested_before = me.don_rested
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST21-009"]
    assert len(opts) == 1, f"ST21-009 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert _total_attached(me) == attached_before + 2, \
        f"レストドン2枚が付与されていない: {_total_attached(me)}"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"


def test_st21_009_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    nami = InPlay.of(repo.get("ST21-009"), sickness=False)
    me.characters = [nami]
    me.don_rested = 4

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST21-009"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST21-009"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_st21_009_activate_main_human_target_pick():
    """人間 + 麦わらの一味リーダー + キャラ → 付与先 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    nami = InPlay.of(repo.get("ST21-009"), sickness=False)  # 麦わらの一味
    mugi = InPlay.of(repo.get(_MUGI_C), sickness=False)     # 麦わらの一味 サンジ
    me.characters = [nami, mugi]
    me.don_rested = 3

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST21-009"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    # リーダー (麦わら) + ナミ + サンジ = 3 候補
    assert len(cands) == 3, f"麦わらの一味 候補が3件でない: {len(cands)}"
    mugi_idx = next(i for i, c in enumerate(cands) if c["iid"] == mugi.instance_id)
    resolve_pending_choice(st, [mugi_idx])
    _drain(st, [0])
    assert mugi.attached_dons == 2, \
        f"人間が選んだキャラにレストドン2枚が付与されていない: {mugi.attached_dons}"


# --------------------------------------------------------------------------- #
#  ST21-010 ニコ・ロビン: 【ドン‼×2】【アタック時】相手パワー4000以下キャラ1枚KO
# --------------------------------------------------------------------------- #
def test_st21_010_on_attack_ko_power_le_4000_ai():
    """【アタック時】(ドン2ゲート) 相手パワー4000以下キャラ1体KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SANJI4), sickness=False)  # power 4000 (= 対象)
    opp.characters = [victim]

    eff = _eff(overlay, "ST21-010", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"
    attacker = InPlay.of(repo.get("ST21-010"), sickness=False)
    attacker.attached_dons = 2
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, attacker)
    _drain(st, [0])
    assert victim not in opp.characters, "相手のパワー4000以下キャラが KO されていない"


def test_st21_010_on_attack_high_power_survives():
    """相手キャラのパワーが 4000 超なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    tough = InPlay.of(repo.get(_BIG_C), sickness=False)  # power 7000 (対象外)
    opp.characters = [tough]

    for prim in _eff(overlay, "ST21-010", "on_attack")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST21-010"), sickness=False))
    _drain(st, [0])
    assert tough in opp.characters, "パワー4000超のキャラが KO されてはいけない (対象外)"


def test_st21_010_on_attack_human_target_pick():
    """人間 + パワー4000以下キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # power 2000
    b = InPlay.of(repo.get(_SANJI4), sickness=False)   # power 4000
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST21-010", "on_attack")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST21-010"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert len(opp.characters) == 1, "人間が選んだ相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  ST21-011 フランキー: 【ドン‼×2】【相手のターン中】自元々パワー4000以下の
#                       麦わらの一味キャラすべて +1000
# --------------------------------------------------------------------------- #
def test_st21_011_static_pump_all_mugi_le4000_opp_turn():
    """静的 (ドン2・相手ターン): 麦わらの一味 元々パワー4000以下 キャラすべてに +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay, turn_player=1)  # 相手ターン
    me = st.players[0]
    franky = InPlay.of(repo.get("ST21-011"), sickness=False)  # power 4000 麦わら
    franky.attached_dons = 2  # ドン2 ゲート成立
    nami = InPlay.of(repo.get(_FILLER), sickness=False)  # power 2000 麦わら (対象)
    me.characters = [franky, nami]

    evaluate_static_effects(st, overlay)
    # 元々パワー4000以下 の 麦わらの一味 = フランキー自身 + ナミ、 両方 +1000
    assert nami.static_buff == 1000, \
        f"ナミ (麦わら 2000) に +1000 が乗っていない: {nami.static_buff}"
    assert franky.static_buff == 1000, \
        f"フランキー自身 (麦わら 4000) に +1000 が乗っていない: {franky.static_buff}"


def test_st21_011_static_no_pump_self_turn():
    """自分のターン中は【相手のターン中】条件不成立 → +1000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay, turn_player=0)  # 自分のターン
    me = st.players[0]
    franky = InPlay.of(repo.get("ST21-011"), sickness=False)
    franky.attached_dons = 2
    nami = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [franky, nami]

    evaluate_static_effects(st, overlay)
    assert nami.static_buff == 0 and franky.static_buff == 0, \
        f"自ターンで +1000 が乗ってはいけない: {nami.static_buff}/{franky.static_buff}"


# --------------------------------------------------------------------------- #
#  ST21-012 ブルック: 【アタック時】自リーダーかキャラ1枚に レストのドン‼2枚まで付与
# --------------------------------------------------------------------------- #
def test_st21_012_on_attack_attach_rested_don_ai():
    """【アタック時】自リーダーかキャラに レストドン2枚付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    brook = InPlay.of(repo.get("ST21-012"), sickness=False)
    me.characters = [brook]
    me.don_rested = 3

    attached_before = _total_attached(me)
    rested_before = me.don_rested
    for prim in _eff(overlay, "ST21-012", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, brook)
    _drain(st, [0])

    assert _total_attached(me) == attached_before + 2, \
        f"レストドン2枚が付与されていない: {_total_attached(me)}"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"


def test_st21_012_on_attack_human_target_pick():
    """人間 + 自リーダー + 自キャラ → 付与先 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    brook = InPlay.of(repo.get("ST21-012"), sickness=False)
    me.characters = [brook]
    me.don_rested = 3

    execute_effect(_eff(overlay, "ST21-012", "on_attack")["do"][0], st, me, opp,
                   brook)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    # リーダー + ブルック自身 = 2 候補
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    brook_idx = next(i for i, c in enumerate(cands) if c["iid"] == brook.instance_id)
    resolve_pending_choice(st, [brook_idx])
    _drain(st, [0])
    assert brook.attached_dons == 2, \
        f"人間が選んだキャラにレストドン2枚が付与されていない: {brook.attached_dons}"


# --------------------------------------------------------------------------- #
#  ST21-014 モンキー・D・ルフィ: 【速攻】【アタック時】自リーダーかキャラ1枚に
#                               レストのドン‼1枚まで付与
# --------------------------------------------------------------------------- #
def test_st21_014_on_attack_attach_rested_don1_ai():
    """【アタック時】自リーダーかキャラに レストドン1枚付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("ST21-014"), sickness=False)
    me.characters = [luffy]
    me.don_rested = 2

    attached_before = _total_attached(me)
    rested_before = me.don_rested
    for prim in _eff(overlay, "ST21-014", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, luffy)
    _drain(st, [0])

    assert _total_attached(me) == attached_before + 1, \
        f"レストドン1枚が付与されていない: {_total_attached(me)}"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


# --------------------------------------------------------------------------- #
#  ST21-015 ロロノア・ゾロ: 【ドン‼×2】速攻獲得 /【KO時】手札から「ゾロ」以外の
#                          赤パワー6000以下キャラ1枚まで登場
# --------------------------------------------------------------------------- #
def test_st21_015_static_give_rush_don2():
    """【ドン‼×2】静的: 自身に 速攻 キーワードが付与される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me = st.players[0]
    zoro = InPlay.of(repo.get("ST21-015"), sickness=False)
    zoro.attached_dons = 2  # ドン2 ゲート成立
    me.characters = [zoro]

    evaluate_static_effects(st, overlay)
    assert "速攻" in zoro.static_granted_keywords, \
        f"ドン2 で 速攻 が付与されていない: {zoro.static_granted_keywords}"
    assert zoro.is_rush_now is True, "速攻 付与後 is_rush_now が True でない"


def test_st21_015_static_no_rush_without_don():
    """ドン付与が 2 未満 なら 速攻 は付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me = st.players[0]
    zoro = InPlay.of(repo.get("ST21-015"), sickness=False)
    zoro.attached_dons = 1  # ドン1 → ゲート不成立
    me.characters = [zoro]

    evaluate_static_effects(st, overlay)
    assert "速攻" not in zoro.static_granted_keywords, \
        f"ドン1 で 速攻 が付与されてはいけない: {zoro.static_granted_keywords}"


def test_st21_015_on_ko_play_from_hand_ai():
    """【KO時】手札の 赤パワー6000以下キャラ1枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("ST21-015"), sickness=False)
    me.hand = [repo.get(_MUGI_C)]  # サンジ 赤 power3000 (= 対象、 「ゾロ」以外)

    chars_before = len(me.characters)
    for prim in _eff(overlay, "ST21-015", "on_ko")["do"]:
        execute_effect(prim, st, me, opp, zoro)
    _drain(st, [0])

    assert len(me.characters) == chars_before + 1, \
        "KO時に手札の赤キャラが登場していない"
    assert any(c.card.card_id == _MUGI_C for c in me.characters), \
        "登場したキャラが手札から出した サンジ でない"
    assert len(me.hand) == 0, "登場したキャラが手札から取り除かれていない"


# --------------------------------------------------------------------------- #
#  ST21-016 ゴムゴムの白い鞭 (EVENT): 【メイン】自1枚 +1000 →
#            相手パワー4000以下1枚ブロッカー無効 / トリガー パワー4000以下1枚KO
# --------------------------------------------------------------------------- #
def test_st21_016_main_pump_then_disable_blocker_ai():
    """【メイン】自リーダー +1000 → 相手パワー4000以下キャラ1枚ブロッカー無効 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SANJI4), sickness=False)  # power 4000 (= 対象)
    opp.characters = [victim]

    leader_before = me.leader.power
    do = _eff(overlay, "ST21-016", "main")["do"]
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])

    assert me.leader.power == leader_before + 1000, \
        f"自リーダーへ +1000 が乗っていない: {me.leader.power}"
    assert victim.blocker_disabled_until_turn_end is True, \
        "相手パワー4000以下キャラの【ブロッカー】が無効化されていない"


def test_st21_016_trigger_ko_ai():
    """【トリガー】相手のパワー4000以下キャラ1枚をKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_SANJI4), sickness=False)  # power 4000 ≤ 4000
    opp.characters = [victim]

    for prim in _eff(overlay, "ST21-016", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "トリガーで相手パワー4000以下キャラがKOされていない"


# --------------------------------------------------------------------------- #
#  ST21-017 ゴムゴムのモグラ銃 (EVENT): 【メイン】相手1枚 -5000 →
#            自パワー6000以上あれば相手2000以下KO / トリガー メイン効果を発動
# --------------------------------------------------------------------------- #
def test_st21_017_main_debuff_then_conditional_ko_ai():
    """【メイン】相手キャラ -5000 → 自パワー6000以上あり → 相手パワー2000以下KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    # 自分側に パワー6000以上 のキャラを置いて条件を成立させる
    me.characters = [InPlay.of(repo.get(_BIG_C), sickness=False)]  # power 7000
    victim = InPlay.of(repo.get(_MUGI_C), sickness=False)  # power 3000
    opp.characters = [victim]

    base_power = repo.get(_MUGI_C).power  # 3000
    # main(1): power_pump -5000 (パワーは下限クランプなし → 3000 - 5000 = -2000)
    pump_eff = _eff(overlay, "ST21-017", "main", needle="power_pump")
    for prim in pump_eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.power == base_power - 5000, \
        f"-5000 後の power が base-5000 でない: {victim.power}"
    # main(2): 自パワー6000以上あれば 相手パワー2000以下キャラ1枚KO
    ko_eff = _eff(overlay, "ST21-017", "main", needle="ko")
    assert eval_condition(ko_eff.get("if", {}), st, me) is True, \
        "自パワー6000以上ありで 条件付きKO の gate が成立していない"
    for prim in ko_eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, \
        "自パワー6000以上ありで 相手パワー2000以下キャラがKOされていない"


def test_st21_017_main_conditional_ko_gate_off():
    """自パワー6000以上のキャラが 居ない 場合、 条件付きKO は発動しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    # 自分側は 低パワー のみ = 条件不成立
    me.characters = [InPlay.of(repo.get(_FILLER), sickness=False)]  # power 2000
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # power 2000 ≤ 2000
    opp.characters = [victim]

    eff = _eff(overlay, "ST21-017", "main", needle="ko")
    assert eval_condition(eff.get("if", {}), st, me) is False, \
        "自パワー6000以上が居ないのに 条件付きKO の gate が成立している"


def test_st21_017_trigger_fires_main_effect_ai():
    """【トリガー】自身の【メイン】効果を発動 → 相手キャラ -5000 (AI 自動、 crash しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    st.current_source_card_id = "ST21-017"
    victim = InPlay.of(repo.get(_MUGI_C), sickness=False)  # power 3000
    opp.characters = [victim]

    base_power = repo.get(_MUGI_C).power  # 3000
    for prim in _eff(overlay, "ST21-017", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim.power == base_power - 5000, \
        f"トリガー経由の メイン効果 -5000 が反映されていない: {victim.power}"


# --------------------------------------------------------------------------- #
#  ST22-001 エース＆ニューゲート (LEADER): 【起動メイン】【ターン1回】
#            白ひげ海賊団カード公開：1枚引き 公開カードをデッキ上へ
# --------------------------------------------------------------------------- #
def test_st22_001_leader_activate_main_draw_then_topdeck_ai():
    """起動メイン: 白ひげ海賊団を手札に持つ → 1枚引き 公開カードをデッキ上へ (AI 自動)。
    手札・デッキ枚数は 差引 変化なし (draw +1 / put back -1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST22-001", overlay, opp_leader_id="ST22-001")
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST22-002")]  # イゾウ (白ひげ海賊団) = 公開条件を満たす
    me.deck = [repo.get(_FILLER)] * 10

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST22-001"]
    assert len(opts) == 1, f"ST22-001 リーダーの起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert len(me.hand) == hand_before, \
        f"draw +1 / topdeck -1 で 手札枚数は不変のはず: {len(me.hand)}"
    assert len(me.deck) == deck_before, \
        f"draw -1 / topdeck +1 で デッキ枚数は不変のはず: {len(me.deck)}"


def test_st22_001_leader_activate_main_gate_needs_whitebeard_feature():
    """【白ひげ海賊団を公開できる】ゲート: 手札に該当特徴カードが無ければ legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST22-001", overlay, opp_leader_id="ST22-001")
    me = st.players[0]
    me.hand = [repo.get(_FILLER)]  # ナミ (麦わらの一味) = 白ひげ海賊団を持たない
    me.deck = [repo.get(_FILLER)] * 10

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST22-001"]
    assert len(opts) == 0, \
        "手札に白ひげ海賊団カードが無いのに起動メインが legal に出てはいけない"


def test_st22_001_leader_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST22-001", overlay, opp_leader_id="ST22-001")
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST22-002"), repo.get("ST22-002")]  # 白ひげ海賊団 2枚
    me.deck = [repo.get(_FILLER)] * 10

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST22-001"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST22-001"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"
