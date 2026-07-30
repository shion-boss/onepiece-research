# -*- coding: utf-8 -*-
"""OP13 弾 効果 回帰テスト バックフィル (自動生成 wave 130):
OP13-078 / OP13-081 / OP13-087 / OP13-093 / OP13-094 / OP13-095 /
OP13-097 / OP13-102 / OP13-104 / OP13-105 の 10 枚。

目的 (= test_backfill_auto_001〜129.py と同一方針):
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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める (= サーチ/ドローの混入回避)。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("ST01-004")] * 30
    p1.deck = [repo.get("ST01-004")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。
    needle を指定した場合は do[0] に needle 文字列を含む効果を優先する。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op13_wave130_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP13-078", "OP13-081", "OP13-087", "OP13-093", "OP13-094",
           "OP13-095", "OP13-097", "OP13-102", "OP13-104", "OP13-105"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP13-078 オーロ・ジャクソン号 (STAGE):
#    自ロジャー特徴キャラが相手効果で場を離れた時 → ドンデッキからドン1レストで追加
# --------------------------------------------------------------------------- #
def test_op13_078_auro_jackson_add_rested_don_ai():
    """相手効果離脱トリガー: ドンデッキからレストドン1枚を追加する (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    rested_before = me.don_rested
    remaining_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP13-078", "on_self_chara_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-078"), sickness=False))

    assert me.don_rested == rested_before + 1, \
        "レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == remaining_before - 1, \
        "ドンデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP13-081 コアラ (CHARACTER):
#    【起動メイン】【ターン1回】トラッシュ1枚をデッキ下 → 自リーダー/キャラにレストドン1付与
# --------------------------------------------------------------------------- #
def test_op13_081_koala_activate_main_attach_rested_don_ai():
    """起動メイン: トラッシュ1枚をデッキ下 (コスト) → 自リーダー/キャラにレストドン1付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    koala = InPlay.of(repo.get("OP13-081"), sickness=False)
    me.characters = [koala]
    me.trash = [repo.get("OP01-013")]  # デッキ下に置くコスト用
    me.don_rested = 1                  # 付与ソース

    trash_before = len(me.trash)
    deck_before = len(me.deck)
    options = list_activate_main_effects(st, me, overlay)
    koala_opts = [(src, eff) for (src, eff) in options
                  if src.card.card_id == "OP13-081"]
    assert len(koala_opts) == 1, \
        f"OP13-081 の起動メインが legal に出ない: {len(koala_opts)}"
    fire_activate_main(st, me, opp, *koala_opts[0])
    _drain_choices(st, pick=[0])

    assert len(me.trash) == trash_before - 1, \
        "コストでトラッシュ1枚がデッキ下に置かれていない"
    assert len(me.deck) == deck_before + 1, "デッキが1枚増えていない (デッキ下へ)"
    attached_total = me.leader.attached_dons + sum(
        c.attached_dons for c in me.characters)
    assert attached_total >= 1, "レストドンがどこにも付与されていない"
    assert me.don_rested == 0, "レストドンが1枚消費されるべき"


def test_op13_081_koala_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    koala = InPlay.of(repo.get("OP13-081"), sickness=False)
    me.characters = [koala]
    me.trash = [repo.get("OP01-013"), repo.get("OP01-013")]
    me.don_rested = 2

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP13-081"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain_choices(st, pick=[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP13-081"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP13-087 チャルロス聖 (CHARACTER): 【ブロッカー】【登場時】自デッキ上1枚をトラッシュ
# --------------------------------------------------------------------------- #
def test_op13_087_charloss_on_play_mill_self_top_ai():
    """登場時: 自デッキの上から1枚をトラッシュに置く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-016")] + [repo.get("ST01-004")] * 5
    top_card = me.deck[0]

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP13-087", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-087"), sickness=True))

    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"
    assert len(me.trash) == trash_before + 1, "トラッシュが1枚増えていない"
    assert me.trash[-1].card_id == top_card.card_id, \
        "トラッシュに置かれたのはデッキ上のカードであるべき"


# --------------------------------------------------------------------------- #
#  OP13-093 モルガンズ (CHARACTER): 【ブロッカー】【登場時】2ドロー + 手札2捨て
# --------------------------------------------------------------------------- #
def test_op13_093_morgans_on_play_draw2_discard2_ai():
    """登場時: カード2枚を引き、 自分の手札2枚を捨てる (net 手札±0、 デッキ-2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 6
    me.hand = [repo.get("OP01-016"), repo.get("OP01-013")]  # 捨てる候補2枚

    deck_before = len(me.deck)
    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP13-093", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-093"), sickness=True))

    assert len(me.deck) == deck_before - 2, "2枚ドローでデッキが2枚減っていない"
    assert len(me.hand) == hand_before + 2 - 2, \
        f"net 手札 (+2 -2 = ±0) が合わない: {len(me.hand)} (before {hand_before})"


# --------------------------------------------------------------------------- #
#  OP13-094 ヨーク (CHARACTER):
#    【登場時】自分の特徴《天竜人》を持つキャラ1枚まで、 このターン中パワー+2000
# --------------------------------------------------------------------------- #
def test_op13_094_york_on_play_pump_tenryubito_ai():
    """登場時: 自天竜人キャラ1枚を +2000 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    tenryu = InPlay.of(repo.get("OP13-085"), sickness=False)  # ジャルマック聖 天竜人 4000
    me.characters = [tenryu]

    power_before = tenryu.power
    do, _ = _do(overlay, "OP13-094", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-094"), sickness=True))

    assert tenryu.power == power_before + 2000, \
        f"天竜人キャラに +2000 が反映されていない: {tenryu.power} (before {power_before})"


def test_op13_094_york_on_play_pump_human_pick():
    """人間 + 天竜人キャラ複数 → target_pick modal が立ち resolve で 1 枚に +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP13-085"), sickness=False)  # 天竜人 4000
    b = InPlay.of(repo.get("OP13-083"), sickness=False)  # 天竜人 5000
    me.characters = [a, b]

    do, _ = _do(overlay, "OP13-094", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP13-094"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (天竜人2枚) が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.power == b_before + 2000, "人間が選んだ天竜人キャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP13-095 ロズワード聖 (CHARACTER):
#    【登場時】手札1捨てる → 自キャラが天竜人のみなら 相手の元々コスト3以下2枚まで KO
# --------------------------------------------------------------------------- #
def test_op13_095_roswald_on_play_ko_two_ai():
    """登場時 (自キャラ天竜人のみ): 相手のコスト3以下キャラ2枚まで KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP13-085"), sickness=False)]  # 天竜人のみ
    v1 = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    v2 = InPlay.of(repo.get("ST01-005"), sickness=False)  # cost3
    opp.characters = [v1, v2]

    assert eval_condition({"self_all_chara_feature": "天竜人"}, st, me) is True, \
        "自キャラが天竜人のみの条件が成立していない"

    do, _ = _do(overlay, "OP13-095", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-095"), sickness=True))
    _drain_choices(st, pick=[0])

    assert v1 not in opp.characters and v2 not in opp.characters, \
        "相手のコスト3以下キャラ2枚が KO されていない"


def test_op13_095_roswald_on_play_ko_human_pick():
    """人間 + 相手キャラ複数 → KO target_pick modal が立ち resolve で KO される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP13-085"), sickness=False)]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP13-095", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP13-095"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    _drain_choices(st, pick=[0])
    assert len(opp.characters) < 2, "人間解決後に相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP13-097 世界の均衡など…永遠には保てぬのだ (EVENT):
#    【メイン】ドン5レスト → 自キャラ天竜人のみなら 相手の元々コスト6以下1枚まで KO
#    【カウンター】自リーダーを このバトル中 パワー+3000
# --------------------------------------------------------------------------- #
def test_op13_097_event_main_ko_ai():
    """メイン (自キャラ天竜人のみ): 相手のコスト6以下キャラ1枚まで KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP13-085"), sickness=False)]  # 天竜人のみ
    victim = InPlay.of(repo.get("OP01-025"), sickness=False)  # cost3
    opp.characters = [victim]

    do, _ = _do(overlay, "OP13-097", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st, pick=[0])

    assert victim not in opp.characters, "相手のコスト6以下キャラが KO されていない"


def test_op13_097_event_counter_pump_leader_ai():
    """カウンター: 自リーダーを このバトル中 パワー+3000 (対象選択なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP13-097", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"リーダー +3000 が反映されていない: {me.leader.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  OP13-102 エジソン (CHARACTER):
#    【起動メイン】自身トラッシュ → 自ライフ≤相手ライフなら 1ドロー + 相手コスト3以下1枚レスト
#    【トリガー】1ドロー + 相手コスト3以下1枚レスト
# --------------------------------------------------------------------------- #
def test_op13_102_edison_activate_main_draw_and_rest_ai():
    """起動メイン (自ライフ≤相手): 自身をトラッシュ (コスト) → 1ドロー + 相手コスト3以下1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    edison = InPlay.of(repo.get("OP13-102"), sickness=False)
    me.characters = [edison]
    me.life = [repo.get("ST01-004")]          # 自ライフ1
    opp.life = [repo.get("ST01-004")] * 3      # 相手ライフ3 (= 自 ≤ 相手 成立)
    me.deck = [repo.get("ST01-004")] * 5
    me.hand = []
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [victim]

    hand_before = len(me.hand)
    options = list_activate_main_effects(st, me, overlay)
    edison_opts = [(src, eff) for (src, eff) in options
                   if src.card.card_id == "OP13-102"]
    assert len(edison_opts) == 1, \
        f"OP13-102 の起動メインが legal に出ない: {len(edison_opts)}"
    fire_activate_main(st, me, opp, *edison_opts[0])
    _drain_choices(st, pick=[0])

    assert edison not in me.characters, "コストで自身がトラッシュに置かれていない"
    assert len(me.hand) == hand_before + 1, "1ドローが起きていない"
    assert victim.rested is True, "相手のコスト3以下キャラがレストされていない"


def test_op13_102_edison_trigger_rest_ai():
    """トリガー: 相手のコスト3以下キャラ1枚をレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [victim]

    do, _ = _do(overlay, "OP13-102", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-102"), sickness=False))
    _drain_choices(st, pick=[0])

    assert victim.rested is True, "トリガーで相手キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP13-104 光月日和 (CHARACTER):
#    【ブロッカー】【KO時】手札1捨てる → 自リーダーが多色なら 自デッキ上1枚までをライフの上へ
# --------------------------------------------------------------------------- #
def test_op13_104_hiyori_on_ko_put_top_to_life_ai():
    """KO時 (多色リーダー): 手札1枚を捨て → デッキ上1枚をライフの上に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB04-001", overlay)  # ジュエリー・ボニー (赤/黄 = 多色)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]        # 捨てるコスト用
    me.deck = [repo.get("ST01-004")] * 5
    me.life = [repo.get("ST01-004")]

    assert eval_condition({"leader_color": "多色"}, st, me) is True, \
        "リーダーが多色である前提が成立していない"

    hand_before = len(me.hand)
    life_before = len(me.life)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP13-104", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-104"), sickness=False))
    _drain_choices(st, pick=[0])

    assert len(me.hand) == hand_before - 1, "コストで手札1枚が捨てられていない"
    assert len(me.life) == life_before + 1, "デッキ上1枚がライフに加えられていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP13-105 光月モモの助 (CHARACTER): 【登場時】自ライフすべてを見て好きな順で置く
# --------------------------------------------------------------------------- #
def test_op13_105_momonosuke_on_play_scry_life_ai():
    """登場時 scry_life: 自ライフすべてを見て並べ替え (AI crash せず、 枚数不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-016"), repo.get("ST01-005"), repo.get("OP01-013")]

    life_before = len(me.life)
    do, _ = _do(overlay, "OP13-105", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP13-105"), sickness=True))
    _drain_choices(st, pick=[0])

    assert len(me.life) == life_before, "scry_life でライフ枚数が変わってはいけない"
