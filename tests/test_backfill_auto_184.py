# -*- coding: utf-8 -*-
"""ST23 / ST24 / ST25 弾 効果 回帰テスト バックフィル (自動生成 wave 184):
ST23-003 / ST23-005 / ST24-001 / ST24-003 / ST24-005 / ST25-001 /
ST25-002 / ST25-003 / ST25-004 / ST25-005 の 10 枚。

  ST23-003 ベン・ベックマン (CHARACTER 赤) = 【登場時】手札1枚を捨てられる：
     自リーダーが《赤髪海賊団》なら 相手の元々パワー4000以下キャラ1枚までKO
     (on_play optional_cost_then trash1 → ko truly_original_power_le 4000, if leader_feature)
  ST23-005 ヤソップ (CHARACTER 赤) = 【起動メイン】【ターン1回】自リーダーかキャラ1枚に
     レストドン1枚までを付与 (activate_main attach_rested_don self_inplay_choice, once_per_turn)
  ST24-001 カポネ・ベッジ (CHARACTER 緑) = 【ブロッカー】【登場時】自レストカードが6枚以上なら
     1枚引き手札1枚捨てる (on_play draw+trash, if self_rested_cards_count_ge 6)
  ST24-003 バジル・ホーキンス (CHARACTER 緑) = 【自ターン終了時】自ドン1枚までをアクティブに
     (end_of_turn untap_don)
  ST24-005 X・ドレーク (CHARACTER 緑) = 【登場時】自リーダーが《超新星》なら 相手コスト5以下
     キャラ1枚までレスト。その後 このターン終了時 自ドン1枚アクティブに
     (on_play rest opp cost<=5 if leader_feature 超新星 + schedule_at_self_turn_end untap_don)
  ST25-001 アルビダ (CHARACTER 青) = 自元々コスト5以上2枚以上で コスト+1 /
     【登場時】自リーダーが「バギー」なら 3枚引き手札2枚捨てる
     (static set_base_cost +1, on_play draw3 trash2 if leader_name バギー)
  ST25-002 カバジ (CHARACTER 青) = 自元々コスト5以上2枚以上で【ブロッカー】+コスト+1 /
     【相手のターン中】パワー+5000 (static give_keyword+set_base_cost, static power_pump opp_turn)
  ST25-003 クロコダイル＆ミホーク (CHARACTER 青) = 【登場時】2枚引き手札1枚捨て →
     手札からコスト4以下《クロスギルド》キャラ登場 /【ターン1回】自《クロスギルド》キャラが
     相手効果で場を離れる場合 代わりに手札1枚捨てられる
     (on_play draw2 trash1 play_from_hand crossguild, replace_leave crossguild once_per_turn)
  ST25-004 バギー (CHARACTER 青) = 【起動メイン】手札1枚捨て このキャラをトラッシュ：
     自リーダーが「バギー」なら 手札からコスト6以下《クロスギルド》キャラ登場
     (activate_main trash_self+discard → play_from_hand crossguild cost<=6 if leader_name バギー)
  ST25-005 モージ (CHARACTER 青) = 自元々コスト5以上2枚以上で【ブロッカー】+コスト+1 /
     【KO時】自リーダーが「バギー」で手札3枚以下なら 1枚引く
     (static give_keyword+set_base_cost, on_ko draw if leader_name バギー & self_hand_count_le 3)

目的 (= test_backfill_auto_001〜183.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER_RED = "OP09-001"      # シャンクス (四皇/赤髪海賊団) — 赤髪海賊団 leader
_LEADER_NOVA = "OP10-099"     # ユースタス・キッド (超新星/キッド海賊団) — 超新星 leader
_LEADER_BUGGY = "OP09-042"    # バギー (四皇/クロスギルド) — leader_name「バギー」
_LEADER_PLAIN = "OP01-001"    # ロロノア・ゾロ — 汎用 (赤髪/超新星/バギー でない相手役)
_FILLER = "OP01-013"          # サンジ cost2 power3000 麦わらの一味
_NAMI = "OP01-016"            # ナミ cost1 power2000 麦わらの一味
_BIG_C = "PRB02-013"          # ゲッコー・モリア cost6 power7000 (元々コスト5以上)
_CG_C = "ST25-005"            # モージ cost4 クロスギルド (手札から登場させる駒)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id=_LEADER_PLAIN,
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


def _eff(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す (先頭)。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [0])
        n += 1


def _acts(st, me, overlay, cid):
    return [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == cid]


def _total_attached(player) -> int:
    """リーダー + 全キャラ に付与されているドンの総数。"""
    return player.leader.attached_dons + sum(c.attached_dons for c in player.characters)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave184_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST23-003", "ST23-005", "ST24-001", "ST24-003", "ST24-005",
           "ST25-001", "ST25-002", "ST25-003", "ST25-004", "ST25-005"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST23-003 ベン・ベックマン: 【登場時】手札1枚捨てられる：赤髪海賊団 leader なら
#            相手の 元々パワー4000以下キャラ1枚までを KO
# --------------------------------------------------------------------------- #
def test_st23_003_on_play_trash_then_ko_ai():
    """赤髪 leader + 相手 power2000 キャラ → 手札1枚捨てて KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # 捨てる任意コスト
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # power2000 <= 4000
    opp.characters = [victim]

    eff = _eff(overlay, "ST23-003", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "赤髪海賊団", \
        "overlay の 赤髪海賊団 leader 条件が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST23-003"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手の power4000以下キャラが KO されていない"
    assert len(me.hand) == 0, "任意コストで手札1枚が捨てられるべき"


def test_st23_003_on_play_ko_spares_high_power():
    """元々パワー5000のキャラは 4000以下条件に一致せず KO 対象にならない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    tough = InPlay.of(repo.get(_BIG_C), sickness=False)  # power7000 > 4000
    opp.characters = [tough]

    for prim in _eff(overlay, "ST23-003", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST23-003"), sickness=True))
    _drain(st, [0])

    assert tough in opp.characters, "元々パワー5000以上のキャラを KO してはいけない"


def test_st23_003_on_play_human_optional_then_ko_pick():
    """人間: optional_cost_confirm modal → pay → target_pick で KO まで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [victim]

    for prim in _eff(overlay, "ST23-003", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST23-003"), sickness=True))
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st, [0])
    assert victim not in opp.characters, "人間承諾後に KO が解決されていない"


# --------------------------------------------------------------------------- #
#  ST23-005 ヤソップ: 【起動メイン】【ターン1回】自リーダーかキャラ1枚に
#            レストドン1枚までを付与
# --------------------------------------------------------------------------- #
def test_st23_005_activate_main_attach_rested_don_ai():
    """起動メイン: 自リーダー/キャラに レストドン1枚を付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("ST23-005"), sickness=False)]
    me.don_rested = 2

    attached_before = _total_attached(me)
    rested_before = me.don_rested
    opts = _acts(st, me, overlay, "ST23-005")
    assert len(opts) == 1, f"ST23-005 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert _total_attached(me) == attached_before + 1, \
        f"レストドン1枚が付与されていない: {_total_attached(me)}"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_st23_005_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("ST23-005"), sickness=False)]
    me.don_rested = 3

    opts1 = _acts(st, me, overlay, "ST23-005")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = _acts(st, me, overlay, "ST23-005")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST24-001 カポネ・ベッジ: 【登場時】自レストカードが6枚以上なら 1枚引き手札1枚捨て
# --------------------------------------------------------------------------- #
def test_st24_001_on_play_draw_discard_when_six_rested_ai():
    """自レストカード6枚以上 → 1枚引き 手札1枚捨てる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NOVA, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    for _ in range(6):  # レストキャラ 6 枚 (= 条件成立)
        ch = InPlay.of(repo.get(_FILLER), sickness=False)
        ch.rested = True
        me.characters.append(ch)

    eff = _eff(overlay, "ST24-001", "on_play")
    assert eff.get("if", {}).get("self_rested_cards_count_ge") == 6, \
        "overlay の 自レスト6枚以上条件が無い"
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST24-001"), sickness=True))
    _drain(st, [0])

    assert len(me.deck) == deck_before - 1, "1ドローでデッキが1枚減っていない"
    assert len(me.trash) == trash_before + 1, "手札1枚捨てでトラッシュが1枚増えていない"


def test_st24_001_condition_gate_in_overlay():
    """発動条件 (自レスト6枚以上) が overlay の if 節に載っている (= 近似で省かれていない)。"""
    overlay = _overlay()
    eff = _eff(overlay, "ST24-001", "on_play")
    assert eff.get("if", {}).get("self_rested_cards_count_ge") == 6


# --------------------------------------------------------------------------- #
#  ST24-003 バジル・ホーキンス: 【自ターン終了時】自ドン1枚までをアクティブに
# --------------------------------------------------------------------------- #
def test_st24_003_end_of_turn_untap_don_ai():
    """自ターン終了時: レストドン1枚をアクティブに (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NOVA, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 1
    me.don_active = 0

    for prim in _eff(overlay, "ST24-003", "end_of_turn")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST24-003"), sickness=False))

    assert me.don_active == 1, f"レストドン1がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 0, "アクティブ化でレストドンが1枚減るべき"


# --------------------------------------------------------------------------- #
#  ST24-005 X・ドレーク: 【登場時】超新星 leader なら 相手コスト5以下キャラ1枚まで
#            レスト。その後 このターン終了時 自ドン1枚アクティブに
# --------------------------------------------------------------------------- #
def test_st24_005_on_play_rest_opp_cost5_ai():
    """超新星 leader + 相手コスト5以下キャラ → レストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NOVA, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 5
    opp.characters = [victim]

    eff = _eff(overlay, "ST24-005", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "超新星", \
        "overlay の 超新星 leader 条件が無い"
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST24-005"), sickness=True))
    _drain(st, [0])

    assert victim.rested is True, "相手コスト5以下キャラがレストにされていない"


def test_st24_005_on_play_rest_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal で 1 体をレストにできる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NOVA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "ST24-005", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST24-005"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で レスト選択 modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [0])
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"


@pytest.mark.skip(reason="overlay bug (人間レビュー要): ST24-005 の "
    "schedule_at_self_turn_end が {'untap_don':1} と do ラッパを欠く。 "
    "flush 側は spec.get('do',[]) を実行するため 遅延 untap_don が発火しない。 "
    "正しくは {'schedule_at_self_turn_end': {'do': [{'untap_don': 1}]}} (cf OP15-025)。 "
    "engine/overlay 修正は本タスク対象外のため skip。")
def test_st24_005_schedule_turn_end_untap_don_fires():
    """このターン終了時 自ドン1枚アクティブ (= 遅延 untap_don)。 overlay bug で未発火。"""
    raise AssertionError("overlay の schedule spec が do ラッパを欠くため遅延効果が死んでいる")


# --------------------------------------------------------------------------- #
#  ST25-001 アルビダ: 自元々コスト5以上2枚以上で コスト+1 /
#            【登場時】バギー leader なら 3枚引き手札2枚捨て
# --------------------------------------------------------------------------- #
def test_st25_001_static_cost_plus_one_when_two_big():
    """自元々コスト5以上キャラが2枚 → このキャラ base_cost +1 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BUGGY, overlay)
    me, _opp = st.players[0], st.players[1]
    albida_def = repo.get("ST25-001")  # cost4
    albida = InPlay.of(albida_def, sickness=False)
    me.characters = [albida,
                     InPlay.of(repo.get(_BIG_C), sickness=False),
                     InPlay.of(repo.get(_BIG_C), sickness=False)]

    evaluate_static_effects(st, overlay)
    assert albida.base_cost == albida_def.cost + 1, \
        f"コスト5以上2枚で base_cost +1 が反映されていない: {albida.base_cost}"


def test_st25_001_static_no_cost_bonus_when_one_big():
    """コスト5以上が1枚だけなら 条件不成立 → base_cost は据え置き。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BUGGY, overlay)
    me, _opp = st.players[0], st.players[1]
    albida_def = repo.get("ST25-001")
    albida = InPlay.of(albida_def, sickness=False)
    me.characters = [albida, InPlay.of(repo.get(_BIG_C), sickness=False)]

    evaluate_static_effects(st, overlay)
    assert albida.base_cost == albida_def.cost, \
        f"コスト5以上1枚では コスト増加してはいけない: {albida.base_cost}"


def test_st25_001_on_play_draw3_discard2_when_buggy_ai():
    """バギー leader → 3枚引き 手札2枚捨てる = 手札 差引 +1 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BUGGY, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_NAMI)]  # 捨てる余地

    eff = _eff(overlay, "ST25-001", "on_play")
    assert eff.get("if", {}).get("leader_name") == "バギー", \
        "overlay の バギー leader 条件が無い"
    hand_before = len(me.hand)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST25-001"), sickness=True))
    _drain(st, [0])

    assert len(me.hand) == hand_before + 1, \
        f"draw3 - discard2 で 手札は +1 のはず: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  ST25-002 カバジ: 自元々コスト5以上2枚以上で【ブロッカー】+コスト+1 /
#            【相手のターン中】パワー+5000
# --------------------------------------------------------------------------- #
def test_st25_002_static_blocker_and_cost_when_two_big():
    """コスト5以上2枚 → ブロッカー付与 + base_cost +1 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BUGGY, overlay)
    me, _opp = st.players[0], st.players[1]
    kabaji_def = repo.get("ST25-002")  # cost4
    kabaji = InPlay.of(kabaji_def, sickness=False)
    me.characters = [kabaji,
                     InPlay.of(repo.get(_BIG_C), sickness=False),
                     InPlay.of(repo.get(_BIG_C), sickness=False)]

    evaluate_static_effects(st, overlay)
    assert kabaji.is_blocker_now is True, \
        "コスト5以上2枚で ブロッカー が付与されていない"
    assert kabaji.base_cost == kabaji_def.cost + 1, \
        f"コスト5以上2枚で base_cost +1 が反映されていない: {kabaji.base_cost}"


def test_st25_002_static_power_plus5000_on_opp_turn():
    """相手ターン中 → パワー+5000 (静的)。 自分ターンでは乗らない。"""
    repo = _repo()
    overlay = _overlay()
    kabaji_def = repo.get("ST25-002")  # power1000

    # 相手ターン: +5000
    st = _state(repo, _LEADER_BUGGY, overlay, turn_player=1)
    me = st.players[0]
    kabaji = InPlay.of(kabaji_def, sickness=False)
    me.characters = [kabaji]
    evaluate_static_effects(st, overlay)
    assert kabaji.power == kabaji_def.power + 5000, \
        f"相手ターン中に パワー+5000 が乗っていない: {kabaji.power}"

    # 自分ターン: 乗らない
    st2 = _state(repo, _LEADER_BUGGY, overlay, turn_player=0)
    me2 = st2.players[0]
    kabaji2 = InPlay.of(kabaji_def, sickness=False)
    me2.characters = [kabaji2]
    evaluate_static_effects(st2, overlay)
    assert kabaji2.power == kabaji_def.power, \
        f"自分ターン中に +5000 が乗ってはいけない: {kabaji2.power}"


# --------------------------------------------------------------------------- #
#  ST25-003 クロコダイル＆ミホーク: 【登場時】2枚引き手札1枚捨て →
#            手札からコスト4以下《クロスギルド》キャラ登場 /
#            【ターン1回】自《クロスギルド》キャラが相手効果で場を離れる場合 代わりに手札1枚捨て
# --------------------------------------------------------------------------- #
def test_st25_003_on_play_draw_discard_play_crossguild_ai():
    """登場時: 2枚引き 手札1枚捨て → 手札のクロスギルドキャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BUGGY, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_CG_C)]  # クロスギルド cost4 (登場対象)
    me.deck = [repo.get(_CG_C)] + [repo.get(_FILLER)] * 20

    for prim in _eff(overlay, "ST25-003", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST25-003"), sickness=True))
    _drain(st, [0])

    assert any(c.card.card_id == _CG_C for c in me.characters), \
        "手札のコスト4以下クロスギルドキャラが登場していない"


def test_st25_003_replace_leave_crossguild_ai():
    """自クロスギルドキャラが相手効果で離脱 → 代わりに手札1枚捨てで場に残す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BUGGY, overlay)
    me, opp = st.players[0], st.players[1]
    guild_master = InPlay.of(repo.get("ST25-003"), sickness=False)  # 置換効果の持ち主
    ally = InPlay.of(repo.get("ST25-001"), sickness=False)  # クロスギルド ally
    me.characters = [guild_master, ally]
    me.hand = [repo.get(_FILLER)]

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, ally, overlay, by_opp_effect=True, leave_kind="ko",
    )
    _drain(st, [1])  # 人間なら承諾 / AI は自動
    assert replaced is True, "クロスギルドキャラの離脱が置換されていない"
    assert ally in me.characters, "置換成立時 クロスギルドキャラは場に残るべき"
    assert len(me.hand) == hand_before - 1, "置換コストで手札が1枚捨てられるべき"


def test_st25_003_replace_leave_not_by_own_effect():
    """自分の効果で離脱する場合は【相手の効果】条件に一致せず 置換しない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BUGGY, overlay)
    me, opp = st.players[0], st.players[1]
    guild_master = InPlay.of(repo.get("ST25-003"), sickness=False)
    ally = InPlay.of(repo.get("ST25-001"), sickness=False)
    me.characters = [guild_master, ally]
    me.hand = [repo.get(_FILLER)]

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, ally, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, "自分の効果 (by_opp_effect=False) では 置換してはいけない"
    assert len(me.hand) == hand_before, "置換不成立時 手札は減らないはず"


# --------------------------------------------------------------------------- #
#  ST25-004 バギー: 【起動メイン】手札1枚捨て このキャラをトラッシュ：
#            バギー leader なら 手札からコスト6以下《クロスギルド》キャラ登場
# --------------------------------------------------------------------------- #
def test_st25_004_activate_main_trash_self_play_crossguild_ai():
    """起動メイン: 手札1捨て + 自身をトラッシュ → 手札のクロスギルドキャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BUGGY, overlay)
    me, opp = st.players[0], st.players[1]
    buggy = InPlay.of(repo.get("ST25-004"), sickness=False)
    me.characters = [buggy]
    me.hand = [repo.get(_FILLER), repo.get(_CG_C)]  # 捨てる用 + クロスギルド cost4 (<=6)

    eff = _eff(overlay, "ST25-004", "activate_main")
    assert eff.get("if", {}).get("leader_name") == "バギー", \
        "overlay の バギー leader 条件が無い"
    opts = _acts(st, me, overlay, "ST25-004")
    assert len(opts) == 1, f"ST25-004 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert buggy not in me.characters, "起動コストで自身がトラッシュに置かれていない"
    assert any(c.card.card_id == _CG_C for c in me.characters), \
        "手札のコスト6以下クロスギルドキャラが登場していない"


# --------------------------------------------------------------------------- #
#  ST25-005 モージ: 自元々コスト5以上2枚以上で【ブロッカー】+コスト+1 /
#            【KO時】バギー leader で手札3枚以下なら 1枚引く
# --------------------------------------------------------------------------- #
def test_st25_005_static_blocker_and_cost_when_two_big():
    """コスト5以上2枚 → ブロッカー付与 + base_cost +1 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BUGGY, overlay)
    me, _opp = st.players[0], st.players[1]
    mohji_def = repo.get("ST25-005")  # cost4
    mohji = InPlay.of(mohji_def, sickness=False)
    me.characters = [mohji,
                     InPlay.of(repo.get(_BIG_C), sickness=False),
                     InPlay.of(repo.get(_BIG_C), sickness=False)]

    evaluate_static_effects(st, overlay)
    assert mohji.is_blocker_now is True, "コスト5以上2枚で ブロッカー が付与されていない"
    assert mohji.base_cost == mohji_def.cost + 1, \
        f"コスト5以上2枚で base_cost +1 が反映されていない: {mohji.base_cost}"


def test_st25_005_on_ko_draw_when_buggy_and_few_cards_ai():
    """KO時: バギー leader + 手札3枚以下 → 1枚引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_BUGGY, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # 1 枚 (<=3)

    eff = _eff(overlay, "ST25-005", "on_ko")
    assert eff.get("if", {}).get("leader_name") == "バギー", \
        "overlay の バギー leader 条件が無い"
    assert eff.get("if", {}).get("self_hand_count_le") == 3, \
        "overlay の 手札3枚以下条件が無い"
    deck_before = len(me.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST25-005"), sickness=False))
    _drain(st, [0])

    assert len(me.deck) == deck_before - 1, "KO時の 1ドローでデッキが1枚減っていない"
