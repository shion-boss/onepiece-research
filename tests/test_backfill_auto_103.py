# -*- coding: utf-8 -*-
"""OP10 弾 緑/青 効果 回帰テスト バックフィル (自動生成 wave 103):
OP10-030 / OP10-032 / OP10-034 / OP10-036 / OP10-037 /
OP10-038 / OP10-039 / OP10-040 / OP10-041 / OP10-043 の 10 枚
(スモーカー = 起動メインでドン1アクティブ /
 たしぎ = 他の緑キャラの相手効果離脱を代わりに自レストで置換 /
 フランキー = バトルKOを代わりにライフ1枚手札で置換 (ターン1回 任意) /
 ペローナ = 自効果でキャラがレストした時ドン1アクティブ (自ターン中 ターン1回) /
 リム = 相手効果離脱を代わりにODYSSEY1枚レストで置換 & ターン終了時ODYSSEY1枚アクティブ /
 ロロノア・ゾロ = 相手ターン中 自レストキャラ2枚以上で +2000 (静的) /
 ゴムゴムの龍火炎銃巻き星 = ODYSSEYリーダーで上5枚からODYSSEYキャラ2枚サーチ / trigger 相手コスト5以下レスト /
 弱ェ奴は死に方も選べねェ = 相手レストのコスト7以下1枚KO (メイン/カウンター) /
 ラジオナイフ = 相手コスト6以下1枚レスト→レストのコスト5以下1枚KO / trigger 相手コスト4以下レスト /
 ウーシー = 登場時 ドレスローザのリーダー/ステージをレストして自ルフィにバニッシュ付与)。

目的 (= test_backfill_auto_001〜102.py と同一方針):
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
    trigger_end_of_turn,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード / リーダー (テキストの前提固定)
_LEADER_GREEN = "OP01-001"     # ロロノア・ゾロ (leader、 汎用)
_LEADER_ODYSSEY = "OP09-022"   # リム (leader、 ODYSSEY)
_LEADER_DRESSROSA = "EB01-040"  # キュロス (leader、 ドレスローザ)
_FILLER = "ST01-004"           # サンジ cost2 power4000 (バニラ、 埋め用/相手キャラ)
_ODY_BIG = "OP10-024"          # エドワード・ニューゲート (ODYSSEY 緑 cost5 power6000)
_ODY_SMALL = "OP10-033"        # ナミ (ODYSSEY 緑 cost2 power2000)
_GREEN_CHARA = "PRB02-004"     # ジュエリー・ボニー (緑 cost3、 たしぎ victim 用)
_LUFFY = "OP09-036"            # モンキー・D・ルフィ (緑 CHARACTER cost5)


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
def test_all_wave103_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP10-030", "OP10-032", "OP10-034", "OP10-036", "OP10-037",
           "OP10-038", "OP10-039", "OP10-040", "OP10-041", "OP10-043"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP10-030 スモーカー (CHARACTER): 【起動メイン】自分のドン‼1枚までをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op10_030_activate_main_untap_don_ai():
    """起動メイン: レストドン1枚をアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    smoker = InPlay.of(repo.get("OP10-030"), sickness=False)
    me.characters = [smoker]
    me.don_rested = 1
    me.don_active = 0

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP10-030"]
    assert len(opts) == 1, \
        f"OP10-030 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert me.don_active == 1, f"レストドンが1枚アクティブになっていない: {me.don_active}"
    assert me.don_rested == 0, f"レストドンが1枚消費されるべき: {me.don_rested}"


def test_op10_030_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    smoker = InPlay.of(repo.get("OP10-030"), sickness=False)
    me.characters = [smoker]
    me.don_rested = 3

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP10-030"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP10-030"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP10-032 たしぎ (CHARACTER): 「たしぎ」以外の自分の緑のキャラが相手の効果で
#          場を離れる場合、代わりにこのキャラをレストにできる。 (replace_ko)
# --------------------------------------------------------------------------- #
def test_op10_032_replace_ko_other_green_rests_self_ai():
    """他の緑キャラが相手効果でKOされる場合、代わりに たしぎ をレストして置換 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    tashigi = InPlay.of(repo.get("OP10-032"), sickness=False)
    victim = InPlay.of(repo.get(_GREEN_CHARA), sickness=False)  # 緑キャラ (たしぎ以外)
    me.characters = [tashigi, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "緑キャラの相手効果KOが たしぎ のレストで置換されていない"
    assert tashigi.rested is True, "置換で たしぎ がレストされるべき"


def test_op10_032_replace_ko_not_triggered_by_own_effect():
    """自分の効果 (by_opp_effect=False) で離れる場合は 置換対象外 (相手効果限定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    tashigi = InPlay.of(repo.get("OP10-032"), sickness=False)
    victim = InPlay.of(repo.get(_GREEN_CHARA), sickness=False)
    me.characters = [tashigi, victim]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, "自分の効果由来の離脱で置換が成立してはいけない"
    assert tashigi.rested is False, "置換不成立時 たしぎ はレストされない"


# --------------------------------------------------------------------------- #
#  OP10-034 フランキー (CHARACTER): 【ターン1回】このキャラがバトルでKOされる場合、
#          代わりに自分のライフの上から1枚を手札に加えてもよい。 (replace_ko)
# --------------------------------------------------------------------------- #
def test_op10_034_replace_battle_ko_life_to_hand_ai():
    """バトルKO を代わりにライフ1枚手札で置換 (AI、 任意だが自動発動でフランキーは残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    franky = InPlay.of(repo.get("OP10-034"), sickness=False)
    me.characters = [franky]
    me.life = [repo.get(_FILLER)] * 2
    me.hand = []

    hand_before = len(me.hand)
    life_before = len(me.life)
    # バトルKO = by_opp_effect=False (= 効果由来でない = by_battle)
    replaced = try_replace_ko(
        st, me, opp, franky, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is True, "バトルKO が置換されていない"
    assert franky in me.characters, "置換成立時 フランキー は場に残るべき"
    assert len(me.life) == life_before - 1, "ライフが1枚減るべき"
    assert len(me.hand) == hand_before + 1, "ライフ1枚が手札に加わるべき"


def test_op10_034_replace_battle_ko_once_per_turn():
    """【ターン1回】: 一度置換したら同一ターンに再置換できない (2度目は False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    franky = InPlay.of(repo.get("OP10-034"), sickness=False)
    me.characters = [franky]
    me.life = [repo.get(_FILLER)] * 3

    assert try_replace_ko(st, me, opp, franky, overlay,
                          by_opp_effect=False, leave_kind="ko") is True
    # 2 度目 = once_per_turn 使用済みで払えない → 置換不可
    assert try_replace_ko(st, me, opp, franky, overlay,
                          by_opp_effect=False, leave_kind="ko") is False, \
        "【ターン1回】なのに 同一ターンに再置換できてしまう"


# --------------------------------------------------------------------------- #
#  OP10-036 ペローナ (CHARACTER): 【自分のターン中】【ターン1回】キャラが自分の効果で
#          レストになった時、自分のドン‼1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op10_036_untap_don_on_self_chara_rested_ai():
    """自分の効果でキャラがレストになった時、レストドン1枚をアクティブにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    perona = InPlay.of(repo.get("OP10-036"), sickness=False)
    target = InPlay.of(repo.get(_ODY_BIG), sickness=False)  # power6000 (= rest 対象に選ばれる)
    me.characters = [perona, target]
    me.don_rested = 1
    me.don_active = 0

    # 自効果で 自陣キャラ1枚を rest → ペローナ の field-when が発火 → ドン1アクティブ
    execute_effect({"rest": {"count": 1, "target": "any_self_chara"}},
                   st, me, opp, perona)
    _drain(st, [0])

    assert me.don_active == 1, \
        f"自効果レストでドン1枚がアクティブになっていない: don_active={me.don_active}"
    assert me.don_rested == 0, "レストドンが1枚消費されるべき"


def test_op10_036_no_untap_on_opp_turn():
    """【自分のターン中】条件: 相手ターン中は 自効果レストでも untap が起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= self_turn False)
    perona = InPlay.of(repo.get("OP10-036"), sickness=False)
    target = InPlay.of(repo.get(_ODY_BIG), sickness=False)
    me.characters = [perona, target]
    me.don_rested = 1
    me.don_active = 0

    execute_effect({"rest": {"count": 1, "target": "any_self_chara"}},
                   st, me, opp, perona)
    _drain(st, [0])

    assert me.don_active == 0, \
        f"相手ターン中に untap が起きてはいけない: don_active={me.don_active}"


# --------------------------------------------------------------------------- #
#  OP10-037 リム (CHARACTER): 【ターン1回】相手の効果で場を離れる場合、代わりに自分の
#          特徴《ODYSSEY》キャラ1枚をレストにできる (replace_leave)。
#          【自分のターン終了時】自分の特徴《ODYSSEY》キャラ1枚までをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op10_037_replace_leave_rest_odyssey_ai():
    """相手効果離脱を代わりに ODYSSEY キャラ1枚レストで置換 (AI、 リム は残る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    rim = InPlay.of(repo.get("OP10-037"), sickness=False)
    ody = InPlay.of(repo.get(_ODY_BIG), sickness=False)  # ODYSSEY (rest される)
    me.characters = [rim, ody]

    replaced = try_replace_ko(
        st, me, opp, rim, overlay, by_opp_effect=True, leave_kind="return_to_hand",
    )
    assert replaced is True, "リム の相手効果離脱が ODYSSEY レストで置換されていない"
    assert rim in me.characters, "置換成立時 リム は場に残るべき"
    assert any(c.rested for c in me.characters if "ODYSSEY" in (c.card.features or "")), \
        "置換コストで ODYSSEY キャラ1枚がレストされるべき"


def test_op10_037_end_of_turn_untap_odyssey_ai():
    """【自分のターン終了時】レストの ODYSSEY キャラ1枚をアクティブにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    rim = InPlay.of(repo.get("OP10-037"), sickness=False)  # power - (0)
    ody = InPlay.of(repo.get(_ODY_BIG), sickness=False)    # ODYSSEY power6000
    ody.rested = True
    # レストの ODYSSEY を先頭に (= AI は候補先頭を untap 対象に選ぶ = レスト対象を復帰させる)
    me.characters = [ody, rim]

    trigger_end_of_turn(st, overlay)
    _drain(st, [0])

    assert ody.rested is False, \
        "ターン終了時に レストの ODYSSEY キャラがアクティブになっていない"


# --------------------------------------------------------------------------- #
#  OP10-038 ロロノア・ゾロ (CHARACTER): 【相手のターン中】自分のレストのキャラが2枚以上
#          いる場合、このキャラのパワー+2000。 (静的)
# --------------------------------------------------------------------------- #
def test_op10_038_static_pump_opp_turn_two_rested():
    """相手ターン中 + 自レストキャラ2枚以上 → ゾロ +2000 (静的、 evaluate_static_effects)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 成立)
    zoro_def = repo.get("OP10-038")  # power 6000
    zoro = InPlay.of(zoro_def, sickness=False)
    r1 = InPlay.of(repo.get(_FILLER), sickness=False)
    r2 = InPlay.of(repo.get(_ODY_SMALL), sickness=False)
    r1.rested = True
    r2.rested = True
    me.characters = [zoro, r1, r2]  # レストキャラ 2 枚 (ゾロ自身は active)

    evaluate_static_effects(st, overlay)
    assert zoro.power == zoro_def.power + 2000, \
        f"相手ターン中 レスト2枚で +2000 が乗っていない: {zoro.power} (base {zoro_def.power})"


def test_op10_038_static_no_pump_self_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)  # turn_player=0 (自分)
    me, opp = st.players[0], st.players[1]
    zoro_def = repo.get("OP10-038")
    zoro = InPlay.of(zoro_def, sickness=False)
    r1 = InPlay.of(repo.get(_FILLER), sickness=False)
    r2 = InPlay.of(repo.get(_ODY_SMALL), sickness=False)
    r1.rested = True
    r2.rested = True
    me.characters = [zoro, r1, r2]

    evaluate_static_effects(st, overlay)
    assert zoro.power == zoro_def.power, \
        f"自分のターン中に +2000 が乗ってはいけない: {zoro.power} (base {zoro_def.power})"


def test_op10_038_static_no_pump_one_rested():
    """相手ターン中でもレストキャラが1枚なら 条件不成立 → +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン
    zoro_def = repo.get("OP10-038")
    zoro = InPlay.of(zoro_def, sickness=False)
    r1 = InPlay.of(repo.get(_FILLER), sickness=False)
    r1.rested = True
    me.characters = [zoro, r1]  # レストキャラ 1 枚のみ

    evaluate_static_effects(st, overlay)
    assert zoro.power == zoro_def.power, \
        f"レストキャラ1枚では +2000 が乗ってはいけない: {zoro.power}"


# --------------------------------------------------------------------------- #
#  OP10-039 ゴムゴムの龍火炎銃巻き星 (EVENT): 【メイン】自リーダーが特徴《ODYSSEY》を持つ
#          場合、デッキ上5枚から特徴《ODYSSEY》キャラ2枚までを手札に、残りをデッキ下。
#          【トリガー】相手のコスト5以下のキャラ1枚までをレストにする。
# --------------------------------------------------------------------------- #
def test_op10_039_main_search_two_odyssey_ai():
    """【メイン】(ODYSSEY leader) 上5枚から ODYSSEY キャラ2枚を手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)  # リム (ODYSSEY leader)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    # 上2枚を ODYSSEY キャラに (= OP10-024 / OP10-033)、 残りは filler
    me.deck = [repo.get(_ODY_BIG), repo.get(_ODY_SMALL)] + [repo.get(_FILLER)] * 15

    for prim in _eff(overlay, "OP10-039", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    odyssey_in_hand = [c for c in me.hand if "ODYSSEY" in (c.features or "")]
    assert len(odyssey_in_hand) == 2, \
        f"上5枚から ODYSSEY キャラ2枚が手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op10_039_main_condition_leader_odyssey():
    """条件 leader_feature《ODYSSEY》: ODYSSEY leader で成立 / それ以外で不成立。"""
    repo = _repo()
    overlay = _overlay()
    eff = _eff(overlay, "OP10-039", "main")
    assert eff.get("if", {}).get("leader_feature") == "ODYSSEY", \
        "overlay の リーダー条件 (ODYSSEY) が無い"

    st_ody = _state(repo, _LEADER_ODYSSEY, overlay)
    assert eval_all_conditions(eff, st_ody, st_ody.players[0], None) is True, \
        "ODYSSEY leader で 条件が成立するべき"
    st_other = _state(repo, _LEADER_GREEN, overlay)  # OP01-001 は ODYSSEY でない
    assert eval_all_conditions(eff, st_other, st_other.players[0], None) is False, \
        "ODYSSEY でない leader で 条件が成立してはいけない"


def test_op10_039_trigger_rest_opp_cost5_ai():
    """【トリガー】相手のコスト5以下キャラ1枚をレストにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=5)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-039", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert victim.rested is True, "トリガーで相手のコスト5以下キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP10-040 弱ェ奴は死に方も選べねェ (EVENT): 【メイン】/【カウンター】相手のレストの
#          コスト7以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op10_040_main_ko_rested_cost_le7_ai():
    """【メイン】相手のレストのコスト7以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=7)
    victim.rested = True
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-040", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert victim not in opp.characters, "相手のレストのコスト7以下キャラが KO されていない"


def test_op10_040_main_no_ko_active_target():
    """アクティブな相手キャラは 対象外 (レスト限定) → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-040", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert victim in opp.characters, "アクティブな相手キャラが KO されてはいけない"


def test_op10_040_counter_ko_rested_human_pick():
    """人間 + 相手のレストコスト7以下キャラ 複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)   # cost2
    b = InPlay.of(repo.get(_GREEN_CHARA), sickness=False)  # cost3
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "OP10-040", "counter")["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    _drain(st, [bi])
    assert b not in opp.characters, "人間が選んだ相手キャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP10-041 ラジオナイフ (EVENT): 【メイン】相手のコスト6以下キャラ1枚までをレストにする。
#          その後、相手のレストのコスト5以下キャラ1枚までをKOする。
#          【トリガー】相手のコスト4以下キャラ1枚までをレストにする。
# --------------------------------------------------------------------------- #
def test_op10_041_main_rest_then_ko_ai():
    """【メイン】相手コスト6以下1枚レスト → その後レストのコスト5以下1枚KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=6 → rest、 rest後 <=5 → KO)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-041", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert victim not in opp.characters, \
        "レスト→KO の流れで相手のコスト5以下キャラが KO されていない"


def test_op10_041_trigger_rest_opp_cost4_ai():
    """【トリガー】相手のコスト4以下キャラ1枚をレストにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GREEN, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_GREEN_CHARA), sickness=False)  # cost3 (<=4)
    opp.characters = [victim]

    for prim in _eff(overlay, "OP10-041", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert victim.rested is True, "トリガーで相手のコスト4以下キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP10-043 ウーシー (CHARACTER): 【登場時】自分の特徴《ドレスローザ》を持つリーダーか
#          ステージ1枚を、レストにできる：自分のキャラの「モンキー・D・ルフィ」1枚までは、
#          このターン中、【バニッシュ】を得る。 (optional_cost_then)
# --------------------------------------------------------------------------- #
def test_op10_043_on_play_give_banish_to_luffy_ai():
    """【登場時】ドレスローザのリーダーをレストして 自ルフィに バニッシュ付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay)  # キュロス (ドレスローザ leader)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get(_LUFFY), sickness=False)  # モンキー・D・ルフィ
    me.characters = [luffy]
    ushi = InPlay.of(repo.get("OP10-043"), sickness=True)

    assert me.leader.rested is False
    for prim in _eff(overlay, "OP10-043", "on_play")["do"]:
        execute_effect(prim, st, me, opp, ushi)
    _drain(st, [0])

    assert me.leader.rested is True, \
        "コストで ドレスローザ リーダーがレストされるべき"
    assert "バニッシュ" in luffy.granted_keywords, \
        "自ルフィに バニッシュ が付与されていない"


def test_op10_043_on_play_optional_cost_human_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_DRESSROSA, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get(_LUFFY), sickness=False)
    me.characters = [luffy]
    ushi = InPlay.of(repo.get("OP10-043"), sickness=True)

    execute_effect(_eff(overlay, "OP10-043", "on_play")["do"][0], st, me, opp, ushi)
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 払って発動)
    _drain(st, [0])
    assert me.leader.rested is True, "承諾後 ドレスローザ リーダーがレストされるべき"
    assert "バニッシュ" in luffy.granted_keywords, \
        "承諾後 自ルフィに バニッシュ が付与されていない"
