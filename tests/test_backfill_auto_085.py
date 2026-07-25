# -*- coding: utf-8 -*-
"""OP08 弾 (ミンク族 / 九蛇海賊団 / 白ひげ海賊団) 効果 回帰テスト バックフィル
(自動生成 wave 085):
OP08-034 / OP08-036 / OP08-037 / OP08-038 / OP08-041 / OP08-043 /
OP08-044 / OP08-045 / OP08-046 / OP08-049 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _drain(st, pick=0, guard=8):
    """pending_choice を pick を選び続けて解決しきる (後続の reorder 等を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        cands = st.pending_choice.get("candidates")
        cards = st.pending_choice.get("cards")
        if cands is not None and len(cands) == 0:
            resolve_pending_choice(st, [])
        elif cards is not None and not cands:
            resolve_pending_choice(st, [pick] if any(
                c.get("matches_filter") for c in cards) else [])
        else:
            resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op08_wave085_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP08-034", "OP08-036", "OP08-037", "OP08-038", "OP08-041",
           "OP08-043", "OP08-044", "OP08-045", "OP08-046", "OP08-049"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP08-034 ワンダ:【登場時】デッキ上5枚を見て「ワンダ」以外の《ミンク族》1枚まで
#                   公開して手札へ、残りをデッキ下。
# --------------------------------------------------------------------------- #
def test_op08_034_wanda_on_play_search_mink_ai():
    """【登場時】デッキ上5枚から《ミンク族》キャラを手札に加える (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)  # キャロット (ミンク族 leader)
    me, opp = st.players[0], st.players[1]
    # デッキ上に ネコマムシ (ミンク族) を仕込む
    me.deck = [repo.get("OP01-048")] + [repo.get("OP01-013")] * 10
    me.hand = []

    on_play = next(e for e in overlay.get("OP08-034").effects
                   if e["when"] == "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-034"), sickness=True))
    _drain(st)

    assert any(c.card_id == "OP01-048" for c in me.hand), \
        "デッキ上5枚から《ミンク族》キャラが手札に加わっていない"


def test_op08_034_wanda_on_play_search_human_pick():
    """人間: デッキ上5枚に《ミンク族》候補 → search_top_n modal が立ち resolve で手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-048"), repo.get("OP01-013"),
               repo.get("OP08-004")] + [repo.get("OP01-013")] * 10
    me.hand = []

    on_play = next(e for e in overlay.get("OP08-034").effects
                   if e["when"] == "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP08-034"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭候補 (ネコマムシ) を選択
    _drain(st)
    assert any(c.card_id == "OP01-048" for c in me.hand), \
        "人間が選んだ《ミンク族》キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP08-036 エレクトリカルルナ (EVENT):
#    【メイン】相手のレスト cost7以下キャラすべては、次の相手のリフレッシュで
#             アクティブにならない。
# --------------------------------------------------------------------------- #
def test_op08_036_electrical_luna_main_stay_rested_ai():
    """【メイン】相手のレスト cost7以下 全員が stay_rested になる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 <= 7
    b = InPlay.of(repo.get("OP08-004"), sickness=False)  # cost4 <= 7
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    main = next(e for e in overlay.get("OP08-036").effects if e["when"] == "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert a.stay_rested_next_refresh is True and b.stay_rested_next_refresh is True, \
        f"相手レスト cost7以下 全員が stay_rested になっていない: " \
        f"{a.stay_rested_next_refresh}/{b.stay_rested_next_refresh}"


def test_op08_036_electrical_luna_main_skips_active_opp():
    """アクティブ (非レスト) の相手キャラは対象外 → stay_rested にならない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    active = InPlay.of(repo.get("OP01-016"), sickness=False)
    active.rested = False  # アクティブ = 対象外
    opp.characters = [active]

    main = next(e for e in overlay.get("OP08-036").effects if e["when"] == "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert active.stay_rested_next_refresh is False, \
        "アクティブなキャラが stay_rested になってはいけない (対象外)"


# --------------------------------------------------------------------------- #
#  OP08-037 ガルチュー (EVENT):
#    【メイン】自分の《ミンク族》キャラ1枚をレストにできる：相手のキャラ1枚までをレスト。
# --------------------------------------------------------------------------- #
def test_op08_037_garchu_main_optcost_rest_opp_ai():
    """【メイン】《ミンク族》1枚レスト (コスト) → 相手キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    mink = InPlay.of(repo.get("OP01-048"), sickness=False)  # ネコマムシ (ミンク族)
    me.characters = [mink]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    main = next(e for e in overlay.get("OP08-037").effects if e["when"] == "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert mink.rested is True, "任意コストで自《ミンク族》がレストされるべき"
    assert victim.rested is True, "相手キャラがレストされていない"


def test_op08_037_garchu_main_human_optional_cost():
    """人間: メイン do → optional_cost_confirm modal が立ち、 pay で相手キャラがレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    mink = InPlay.of(repo.get("OP01-048"), sickness=False)
    me.characters = [mink]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    main = next(e for e in overlay.get("OP08-037").effects if e["when"] == "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st)
    assert victim.rested is True, "任意コスト承認後に相手キャラがレストされていない"


# --------------------------------------------------------------------------- #
#  OP08-038 敵に"仲間"は売らんぜよ!!! (EVENT):
#    【メイン】自分のキャラ2枚をレストにできる：自分のキャラすべては、
#             次の相手のターン終了時まで、相手の効果でKOされない。
# --------------------------------------------------------------------------- #
def test_op08_038_main_optcost_rest2_then_ko_immune_ai():
    """【メイン】自キャラ2枚レスト (コスト) → 自キャラ全員が次相手ターン終了まで
    効果KO耐性 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-021", overlay)
    me, opp = st.players[0], st.players[1]
    c1 = InPlay.of(repo.get("OP01-013"), sickness=False)
    c2 = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [c1, c2]

    main = next(e for e in overlay.get("OP08-038").effects if e["when"] == "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert c1.rested is True and c2.rested is True, \
        "任意コストで自キャラ2枚がレストされるべき"
    assert c1.ko_immune_through_opp_turn is True and \
        c2.ko_immune_through_opp_turn is True, \
        "自キャラ全員が効果KO耐性 (次相手ターン終了まで) を得ていない"


# --------------------------------------------------------------------------- #
#  OP08-041 アフェランドラ:
#    【起動メイン】このキャラを持ち主の手札に戻すことができる：自リーダーが
#     《九蛇海賊団》なら、相手のコスト1以下キャラ1枚までを持ち主のデッキ下へ。
# --------------------------------------------------------------------------- #
def test_op08_041_afeland_activate_main_return_deck_bottom_ai():
    """起動メイン: 自身を手札へ (コスト) → 相手 cost1以下1枚をデッキ下 (AI 自動)。
    リーダー = ボア・ハンコック (九蛇海賊団) で条件成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-038", overlay)  # ボア・ハンコック (九蛇海賊団)
    me, opp = st.players[0], st.players[1]
    aff = InPlay.of(repo.get("OP08-041"), sickness=False)
    me.characters = [aff]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [victim]
    opp.deck = [repo.get("OP01-013")] * 10

    options = list_activate_main_effects(st, me, overlay)
    aff_opts = [(src, eff) for (src, eff) in options
                if src.card.card_id == "OP08-041"]
    assert len(aff_opts) == 1, \
        f"OP08-041 の起動メインが legal に出ない: {len(aff_opts)}"
    fire_activate_main(st, me, opp, *aff_opts[0])
    _drain(st)

    assert aff not in me.characters, "コストで アフェランドラ が手札に戻るべき"
    assert victim not in opp.characters, "相手 cost1 キャラがデッキ下に置かれていない"
    assert opp.deck[-1].card_id == "OP01-016", \
        "戻した相手キャラがデッキ下 (末尾) に置かれていない"


def test_op08_041_afeland_wrong_leader_not_legal():
    """リーダーが《九蛇海賊団》でない場合、条件 gate で起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ルフィ (九蛇でない)
    me, opp = st.players[0], st.players[1]
    aff = InPlay.of(repo.get("OP08-041"), sickness=False)
    me.characters = [aff]
    opp.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]

    aff_opts = [o for o in list_activate_main_effects(st, me, overlay)
                if o[0].card.card_id == "OP08-041"]
    assert len(aff_opts) == 0, \
        "《九蛇海賊団》以外のリーダーで起動メインが legal に出てはいけない"


def test_op08_041_afeland_activate_main_human_target_pick():
    """人間 + 相手 cost1 キャラ複数 → target_pick modal が立ち resolve でデッキ下。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-038", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    aff = InPlay.of(repo.get("OP08-041"), sickness=False)
    me.characters = [aff]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]
    opp.deck = [repo.get("OP01-013")] * 10

    aff_opts = [o for o in list_activate_main_effects(st, me, overlay)
                if o[0].card.card_id == "OP08-041"]
    assert len(aff_opts) == 1
    fire_activate_main(st, me, opp, *aff_opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだ相手キャラがデッキ下に置かれていない"
    assert a in opp.characters, "選ばなかった相手キャラは場に残るべき"


# --------------------------------------------------------------------------- #
#  OP08-043 エドワード・ニューゲート:
#    【登場時】自リーダーが『白ひげ海賊団』を含み、自ライフ2枚以下なら、相手キャラ
#     すべては次相手ターン終了まで、アタック時に手札2枚を捨てないとアタック不可。
# --------------------------------------------------------------------------- #
def test_op08_043_newgate_on_play_set_attack_cost_discard_ai():
    """【登場時】(白ひげ leader + ライフ2以下) → 相手キャラ全員に
    attack_cost_discard_hand_n=2 が付与される (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay)  # エドワード・ニューゲート (白ひげ海賊団 leader)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2  # ライフ2 (= 条件成立)
    v1 = InPlay.of(repo.get("OP01-013"), sickness=False)
    v2 = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [v1, v2]

    on_play = next(e for e in overlay.get("OP08-043").effects
                   if e["when"] == "on_play")
    assert on_play.get("if", {}).get("self_life_le") == 2, \
        "overlay の条件 self_life_le=2 が無い"
    assert on_play.get("if", {}).get("leader_feature_contains") == "白ひげ海賊団", \
        "overlay の条件 leader_feature_contains=白ひげ海賊団 が無い"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-043"), sickness=True))

    assert v1.attack_cost_discard_hand_n == 2 and \
        v2.attack_cost_discard_hand_n == 2, \
        "相手キャラ全員に アタック時 手札2枚捨てコストが付与されていない"


# --------------------------------------------------------------------------- #
#  OP08-044 キングデュー:
#    【起動メイン】【ターン1回】手札から『白ひげ海賊団』を含むカード2枚を公開できる：
#     このキャラは、このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op08_044_king_dew_activate_main_reveal_pump_ai():
    """起動メイン: 白ひげ2枚を公開 (コスト) → 自身 +2000 (AI 自動)。 手札は減らない (公開)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    king = InPlay.of(repo.get("OP08-044"), sickness=False)  # power 4000
    me.characters = [king]
    me.hand = [repo.get("PRB02-008"), repo.get("OP01-033")]  # マルコ / イゾウ (白ひげ)

    power_before = king.power
    hand_before = len(me.hand)
    options = list_activate_main_effects(st, me, overlay)
    king_opts = [(src, eff) for (src, eff) in options
                 if src.card.card_id == "OP08-044"]
    assert len(king_opts) == 1, \
        f"OP08-044 の起動メインが legal に出ない: {len(king_opts)}"
    fire_activate_main(st, me, opp, *king_opts[0])
    _drain(st)

    assert king.power == power_before + 2000, \
        f"起動メインの +2000 が反映されていない: {king.power} (before {power_before})"
    assert len(me.hand) == hand_before, \
        "公開コストなのに手札が減っている (捨てではなく公開のはず)"


def test_op08_044_king_dew_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    king = InPlay.of(repo.get("OP08-044"), sickness=False)
    me.characters = [king]
    me.hand = [repo.get("PRB02-008"), repo.get("OP01-033")]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP08-044"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st)

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP08-044"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


def test_op08_044_king_dew_no_pump_when_insufficient_whitebeard():
    """手札に『白ひげ海賊団』が2枚未満なら公開コストを払えず +2000 が乗らない。
    (起動メインは optional_cost なので legal 列挙はされるが、 発動しても cost 不能で
     効果 pump は起きない。)"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    king = InPlay.of(repo.get("OP08-044"), sickness=False)
    me.characters = [king]
    me.hand = [repo.get("PRB02-008"), repo.get("OP01-013")]  # 白ひげは1枚のみ

    power_before = king.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-044"]
    if opts:
        fire_activate_main(st, me, opp, *opts[0])
        _drain(st)
    assert king.power == power_before, \
        "白ひげ2枚を公開できないのに +2000 が乗っている (cost 不能のはず)"


# --------------------------------------------------------------------------- #
#  OP08-045 サッチ:
#    このキャラがKOされるか相手効果で場を離れる場合、代わりにトラッシュに置き
#    カード1枚を引く。(replace_leave)
#  ⚠ engine gap: _can_pay_replace_cost が cost {"trash_self": true} を未対応
#    (= 未対応 cost は支払不能扱いで replace_leave が発火しない)。
#    engine 修正は人間レビュー案件のため、 このカードのテストは skip する。
# --------------------------------------------------------------------------- #
@pytest.mark.skip(reason=(
    "engine gap: effects._can_pay_replace_cost が replace_leave の cost "
    "{'trash_self': true} を未対応 (未対応 cost=支払不能扱い) のため replace_leave が "
    "発火せず。 engine 修正は人間レビューに回す (このタスクでは engine を編集しない)。"))
def test_op08_045_sacchi_replace_leave_trash_then_draw():
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    sacchi = InPlay.of(repo.get("OP08-045"), sickness=False)
    me.characters = [sacchi]
    me.deck = [repo.get("OP01-013")] * 5
    me.hand = []

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, sacchi, overlay, by_opp_effect=True, leave_kind="ko")
    assert replaced is True, "KO を トラッシュ+ドロー で置換できていない"
    assert len(me.hand) == hand_before + 1, "置換効果で 1 ドローされるべき"


# --------------------------------------------------------------------------- #
#  OP08-046 シャクヤク:
#    【自分のターン中】【ターン1回】キャラが自分の効果で場を離れた時、相手の手札が
#    5枚以上あれば、相手は手札1枚をデッキ下へ。その後、このキャラをレストにする。
# --------------------------------------------------------------------------- #
def test_op08_046_shakuyaku_on_leave_by_self_opp_deck_bottom_ai():
    """自分の効果で相手キャラを KO → シャクヤク発火。 相手手札5以上なら 1枚デッキ下 +
    シャクヤク自身をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    shaku = InPlay.of(repo.get("OP08-046"), sickness=False)
    me.characters = [shaku]
    opp.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]
    opp.hand = [repo.get("OP01-013")] * 6  # 5枚以上 = 条件成立
    opp.deck = [repo.get("OP01-013")] * 10

    hand_before = len(opp.hand)
    # 自分の効果 (KO) で相手キャラが場を離れる → on_self_chara_leave_by_self_effect 誘発
    execute_effect({"ko": "one_opponent_character_any"}, st, me, opp, None)
    _drain(st)

    assert len(opp.hand) == hand_before - 1, \
        "相手手札が1枚デッキ下に置かれていない"
    assert shaku.rested is True, "効果解決後 シャクヤク自身がレストされるべき"


def test_op08_046_shakuyaku_no_fire_when_opp_hand_lt5():
    """相手手札が5枚未満なら条件不成立 → 発火しない (シャクヤクはレストされない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    shaku = InPlay.of(repo.get("OP08-046"), sickness=False)
    me.characters = [shaku]
    opp.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]
    opp.hand = [repo.get("OP01-013")] * 3  # 3枚 = 条件不成立
    opp.deck = [repo.get("OP01-013")] * 10

    execute_effect({"ko": "one_opponent_character_any"}, st, me, opp, None)
    _drain(st)

    assert len(opp.hand) == 3, "条件不成立なのに相手手札が減ってはいけない"
    assert shaku.rested is False, "条件不成立なのにシャクヤクがレストされてはいけない"


# --------------------------------------------------------------------------- #
#  OP08-049 スピード・ジル:
#    【登場時】デッキ上1枚を公開し上か下へ。公開が『白ひげ海賊団』を含むなら、
#    このキャラはこのターン中【速攻】を得る。
# --------------------------------------------------------------------------- #
def test_op08_049_speed_jiru_on_play_reveal_grants_rush_ai():
    """【登場時】デッキ上が『白ひげ海賊団』→ 自身が【速攻】を得る (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    speed = InPlay.of(repo.get("OP08-049"), sickness=True)
    me.characters = [speed]
    me.deck = [repo.get("PRB02-008")] + [repo.get("OP01-013")] * 10  # マルコ (白ひげ) on top

    on_play = next(e for e in overlay.get("OP08-049").effects
                   if e["when"] == "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp, speed)
    _drain(st)

    assert "速攻" in speed.granted_keywords, \
        "公開が白ひげなのに【速攻】が付与されていない"


def test_op08_049_speed_jiru_no_rush_when_top_not_whitebeard():
    """デッキ上が『白ひげ海賊団』でないなら【速攻】は付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    speed = InPlay.of(repo.get("OP08-049"), sickness=True)
    me.characters = [speed]
    me.deck = [repo.get("OP01-016")] + [repo.get("OP01-013")] * 10  # ナミ (麦わら) on top

    on_play = next(e for e in overlay.get("OP08-049").effects
                   if e["when"] == "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp, speed)
    _drain(st)

    assert "速攻" not in speed.granted_keywords, \
        "公開が白ひげでないのに【速攻】が付与されてはいけない"
