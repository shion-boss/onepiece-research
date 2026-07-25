# -*- coding: utf-8 -*-
"""OP07 弾 効果 回帰テスト バックフィル (自動生成 wave 076):
OP07-039 / OP07-041 / OP07-042 / OP07-043 / OP07-044 / OP07-045 /
OP07-046 / OP07-047 / OP07-048 / OP07-049 の 10 枚 (王下七武海 軸 青)。

目的 (= 永続的 pytest による担保、 test_backfill_auto_075.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 択一 を 持つカードは 人間 actor で pending_choice が
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
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"        # ロロノア・ゾロ (赤、 汎用 leader。 直接 execute_effect なので色は無関係)
_SHICHI_LEADER = "OP14-040"  # ジンベエ (青、 特徴《王下七武海》を持つ leader)
_FILLER = "OP01-013"        # サンジ cost2 power3000 (汎用フィラー)
_KAMI = "OP06-025"          # ケイミー cost1 power2000 (低コスト)
_SELF4 = "EB02-002"         # サボ cost4 power5000 (高コスト)
_HANCOCK_A = "OP13-051"     # ボア・ハンコック cost3 power5000 (青、 OP07-043 対象)
_HANCOCK_B = "OP02-059"     # ボア・ハンコック cost4 power5000 (青、 OP07-043 2 体目)
_WEEVIL = "OP07-039"        # エドワード・ウィーブル cost4 王下七武海 (OP07-045/049 対象)
_WEEVIL2 = "OP08-042"       # エドワード・ウィーブル cost4 王下七武海 (OP07-045 2 体目)
_AMAZON = "PRB02-017"       # ボア・ハンコック cost5 (九蛇海賊団、 OP07-041 サーチ対象)


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


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    return _eff(overlay, cid, when)["do"]


def _drain(st, pick=0, guard=15):
    """pending_choice を pick で自動解決し切る (= 後続効果を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave76_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP07-039", "OP07-041", "OP07-042", "OP07-043", "OP07-044",
           "OP07-045", "OP07-046", "OP07-047", "OP07-048", "OP07-049"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP07-039 エドワード・ウィーブル (CHARACTER 青 cost4):
#    【ドン‼×1】【アタック時】自分のデッキの上から3枚を見て、好きな順番に並び替え、
#      デッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_op07_039_attack_look_top_reorder_ai():
    """アタック時: デッキ上3枚を並び替え (to=choice = コスト昇順で上に置く、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # 上3枚をコスト バラバラ (4,2,1) で積む → to=choice で 昇順 (1,2,4) に並ぶ
    me.deck = [repo.get(_SELF4), repo.get(_FILLER), repo.get(_KAMI)] \
        + [repo.get(_FILLER)] * 10
    src = InPlay.of(repo.get("OP07-039"), sickness=False)
    deck_len_before = len(me.deck)

    for prim in _do(overlay, "OP07-039", "on_attack"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert len(me.deck) == deck_len_before, "デッキ枚数が変わってはいけない (並び替えのみ)"
    top3_costs = [c.cost for c in me.deck[:3]]
    assert top3_costs == [1, 2, 4], \
        f"デッキ上3枚がコスト昇順に並び替えられていない: {top3_costs}"


def test_op07_039_don_gate_condition():
    """ドン‼×1 ゲート: 付与ドン 1 枚以上で条件成立、 0 枚で不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    cond = _eff(overlay, "OP07-039", "on_attack").get("if")
    assert cond is not None, "OP07-039 on_attack に don ゲート条件がない"
    me.leader.attached_dons = 0
    assert eval_condition(cond, st, me) is False, "付与ドン0で条件が成立してはいけない"
    me.leader.attached_dons = 1
    assert eval_condition(cond, st, me) is True, "付与ドン1で条件が成立するべき"


# --------------------------------------------------------------------------- #
#  OP07-041 グロリオーサ(ニョン婆) (CHARACTER 青 cost1):
#    【登場時】自分のデッキの上から5枚を見て、「グロリオーサ(ニョン婆)」以外の、特徴
#      《アマゾン・リリー》か《九蛇海賊団》を持つカード1枚までを公開し、手札に加える。
#      その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op07_041_on_play_search_amazon_or_kuja_ai():
    """登場時: デッキ上5枚から《九蛇海賊団》のカードを手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_AMAZON)] + [repo.get(_FILLER)] * 10  # 上に九蛇海賊団
    me.hand = []

    for prim in _do(overlay, "OP07-041", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card_id == _AMAZON for c in me.hand), \
        f"デッキ上5枚から九蛇海賊団カードが手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op07_041_on_play_human_search_modal():
    """登場時 (人間): デッキ上5枚に対象 複数 → search_top_n modal が立ち解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_AMAZON), repo.get(_FILLER), repo.get(_AMAZON)] \
        + [repo.get(_FILLER)] * 8
    me.hand = []

    execute_effect(_do(overlay, "OP07-041", "on_play")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == _AMAZON for c in me.hand), \
        "人間が選んだ九蛇海賊団カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP07-042 ゲッコー・モリア (CHARACTER 青 cost5):
#    【ターン1回】自分のリーダーが特徴《王下七武海》を持ち、このキャラが相手の効果で場を
#      離れる場合、代わりに自分の、「ゲッコー・モリア」以外のキャラ1枚を持ち主のデッキの
#      下に置いてもよい。(replace_leave)
# --------------------------------------------------------------------------- #
def test_op07_042_replace_leave_return_other_chara_ai():
    """replace_leave: 相手効果で離れる時、代わりに他の自キャラをデッキ下に置き モリアは残る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHICHI_LEADER, overlay)  # 王下七武海 リーダー
    me, opp = st.players[0], st.players[1]
    moria = InPlay.of(repo.get("OP07-042"), sickness=False)
    other = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [moria, other]
    deck_before = len(me.deck)

    replaced = try_replace_ko(
        st, me, opp, moria, overlay, by_opp_effect=True, leave_kind="ko",
    )
    _drain(st)
    assert replaced is True, "他の自キャラをデッキ下に置けるのに離脱が置換されていない"
    assert moria in me.characters, "置換成立時 モリアは場に残るべき"
    assert other not in me.characters, "代わりの他キャラがデッキ下へ置かれるべき"
    assert len(me.deck) == deck_before + 1, "他キャラ1枚がデッキ下に加わるべき"


def test_op07_042_replace_leave_condition_requires_shichibukai_leader():
    """replace_leave negative: リーダーが王下七武海でなければ置換されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)  # 超新星 リーダー (王下七武海 なし)
    me, opp = st.players[0], st.players[1]
    moria = InPlay.of(repo.get("OP07-042"), sickness=False)
    other = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [moria, other]

    replaced = try_replace_ko(
        st, me, opp, moria, overlay, by_opp_effect=True, leave_kind="ko",
    )
    _drain(st)
    assert replaced is False, "王下七武海でないリーダーで置換が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP07-043 サロメ (CHARACTER 青 cost1):
#    【自分のターン中】【登場時】自分の「ボア・ハンコック」1枚までを、このターン中、
#      パワー+2000。
# --------------------------------------------------------------------------- #
def test_op07_043_on_play_pump_hancock_ai():
    """登場時 (自ターン中): 自分の「ボア・ハンコック」を +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    hancock = InPlay.of(repo.get(_HANCOCK_A), sickness=False)  # power5000
    me.characters = [hancock]
    before = hancock.power

    for prim in _do(overlay, "OP07-043", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert hancock.power == before + 2000, \
        f"「ボア・ハンコック」に +2000 が反映されていない: {hancock.power} (before {before})"


def test_op07_043_self_turn_condition():
    """条件: 自分のターン中のみ発火 (self_turn)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    conds = _eff(overlay, "OP07-043", "on_play").get("conditions")
    assert conds, "OP07-043 に self_turn 条件がない"
    # turn_player=0 (= 自分) なので成立
    for c in conds:
        assert eval_condition(c, st, me) is True, "自分のターンで条件が成立していない"
    # 相手ターンにすると不成立
    st.turn_player_idx = 1
    assert any(eval_condition(c, st, me) is False for c in conds), \
        "相手のターンでも self_turn 条件が成立している"


def test_op07_043_on_play_human_pick_two_hancock():
    """登場時 (人間): 「ボア・ハンコック」が2体 → target_pick modal → 選んだ方に +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    ha = InPlay.of(repo.get(_HANCOCK_A), sickness=False)
    hb = InPlay.of(repo.get(_HANCOCK_B), sickness=False)
    me.characters = [ha, hb]

    execute_effect(_do(overlay, "OP07-043", "on_play")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 同名2体で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (ハンコック2体) が 2 件でない: {len(cands)}"
    hb_idx = next(i for i, c in enumerate(cands) if c["iid"] == hb.instance_id)
    hb_before = hb.power
    resolve_pending_choice(st, [hb_idx])
    _drain(st)
    assert hb.power == hb_before + 2000, "人間が選んだハンコックに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP07-044 ジュラキュール・ミホーク (CHARACTER 青 cost8):
#    【登場時】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op07_044_on_play_draw_ai():
    """登場時: カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 5
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP07-044", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == 1, "登場時の draw が起きていない"
    assert len(me.deck) == deck_before - 1, "デッキから1枚引かれるべき"


# --------------------------------------------------------------------------- #
#  OP07-045 ジンベエ (CHARACTER 青 cost4):
#    【登場時】自分の手札から「ジンベエ」以外のコスト4以下の特徴《王下七武海》を持つ
#      キャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op07_045_on_play_play_from_hand_ai():
    """登場時: 手札のコスト4以下《王下七武海》キャラを1体登場させる (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_WEEVIL)]  # エドワード・ウィーブル cost4 王下七武海
    me.characters = []

    for prim in _do(overlay, "OP07-045", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card.card_id == _WEEVIL for c in me.characters), \
        f"手札の王下七武海キャラが登場していない: {[c.card.card_id for c in me.characters]}"
    assert not any(c.card_id == _WEEVIL for c in me.hand), \
        "登場したキャラが手札に残っている"


def test_op07_045_on_play_human_play_from_hand_modal():
    """登場時 (人間): 対象キャラが手札に2体 → play_from_hand_pick modal → 1体登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_WEEVIL), repo.get(_WEEVIL2)]  # 王下七武海 cost4 が2体
    me.characters = []

    execute_effect(_do(overlay, "OP07-045", "on_play")[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補2体で play_from_hand_pick modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert len(me.characters) == 1, "人間の選択で1体だけ登場するべき"


# --------------------------------------------------------------------------- #
#  OP07-046 センゴク (CHARACTER 青 cost1):
#    【登場時】自分のデッキの上から5枚を見て、特徴《王下七武海》を持つカード1枚までを
#      公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op07_046_on_play_search_shichibukai_ai():
    """登場時: デッキ上5枚から《王下七武海》のカードを手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WEEVIL)] + [repo.get(_FILLER)] * 10  # 上に王下七武海
    me.hand = []

    for prim in _do(overlay, "OP07-046", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(c.card_id == _WEEVIL for c in me.hand), \
        f"デッキ上5枚から王下七武海カードが手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op07_046_on_play_search_negative_no_target():
    """登場時 negative: デッキ上5枚に《王下七武海》が無ければ手札は増えない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10  # 王下七武海 なし
    me.hand = []

    for prim in _do(overlay, "OP07-046", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == 0, "対象なしなのに手札が増えている"


# --------------------------------------------------------------------------- #
#  OP07-047 トラファルガー・ロー (CHARACTER 青 cost4):
#    【起動メイン】このキャラを持ち主の手札に戻すことができる：相手の手札が6枚以上ある
#      場合、相手は自身の手札1枚をデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op07_047_activate_opp_hand_to_deck_bottom_ai():
    """起動メイン: 相手手札1枚をデッキ下へ (AI、 do 部分)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(_FILLER)] * 6
    opp.deck = [repo.get(_FILLER)] * 5
    hand_before = len(opp.hand)
    deck_before = len(opp.deck)

    for prim in _do(overlay, "OP07-047", "activate_main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(opp.hand) == hand_before - 1, "相手手札が1枚減るべき"
    assert len(opp.deck) == deck_before + 1, "相手デッキ下に1枚加わるべき"


def test_op07_047_opp_hand_count_condition():
    """条件: 相手手札6枚以上で成立、 5枚では不成立 (opp_hand_count_ge)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    cond = _eff(overlay, "OP07-047", "activate_main").get("if")
    assert cond is not None, "OP07-047 に手札枚数条件がない"
    opp.hand = [repo.get(_FILLER)] * 5
    assert eval_condition(cond, st, me, opp) is False, "相手手札5枚で条件が成立してはいけない"
    opp.hand = [repo.get(_FILLER)] * 6
    assert eval_condition(cond, st, me, opp) is True, "相手手札6枚で条件が成立するべき"


# --------------------------------------------------------------------------- #
#  OP07-048 ドンキホーテ・ドフラミンゴ (CHARACTER 青 cost3):
#    【起動メイン】【ターン1回】➁(ドン!!を2枚レスト)：自分のデッキの一番上を公開し、
#      そのカードがコスト4以下の特徴《王下七武海》を持つキャラカードの場合、レストで
#      登場させてもよい。その後、残りをデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op07_048_activate_reveal_top_play_ai():
    """起動メイン: ドン2レストを払い デッキ上の王下七武海キャラをレストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    me.deck = [repo.get(_WEEVIL)] + [repo.get(_FILLER)] * 10  # 上に王下七武海 cost4
    me.characters = []
    don_before = me.don_active

    for prim in _do(overlay, "OP07-048", "activate_main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    played = [c for c in me.characters if c.card.card_id == _WEEVIL]
    assert played, f"デッキ上の王下七武海キャラがレスト登場していない: {[c.card.card_id for c in me.characters]}"
    assert played[0].rested is True, "登場したキャラはレスト状態であるべき"
    assert me.don_active < don_before, "任意コスト (ドン2レスト) が支払われていない"


def test_op07_048_reveal_top_non_matching_no_play():
    """起動メイン negative: デッキ上が対象外なら登場せずデッキ下に置かれる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    me.deck = [repo.get(_FILLER)] + [repo.get(_KAMI)] * 10  # 上は王下七武海でない
    me.characters = []

    for prim in _do(overlay, "OP07-048", "activate_main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert not any(c.card.card_id == _FILLER for c in me.characters), \
        "対象外カードが登場してはいけない"


# --------------------------------------------------------------------------- #
#  OP07-049 バッキン (CHARACTER 青 cost2):
#    【登場時】自分の手札からコスト4以下の「エドワード・ウィーブル」1枚までを、
#      レストで登場させる。
# --------------------------------------------------------------------------- #
def test_op07_049_on_play_play_weevil_rested_ai():
    """登場時: 手札のコスト4以下「エドワード・ウィーブル」をレストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_WEEVIL)]  # エドワード・ウィーブル cost4
    me.characters = []

    for prim in _do(overlay, "OP07-049", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    played = [c for c in me.characters if c.card.card_id == _WEEVIL]
    assert played, f"手札のエドワード・ウィーブルが登場していない: {[c.card.card_id for c in me.characters]}"
    assert played[0].rested is True, "エドワード・ウィーブルはレストで登場するべき"


def test_op07_049_on_play_negative_no_weevil():
    """登場時 negative: 手札に対象がなければ何も登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # エドワード・ウィーブルでない
    me.characters = []

    for prim in _do(overlay, "OP07-049", "on_play"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.characters) == 0, "対象なしなのにキャラが登場している"
