# -*- coding: utf-8 -*-
"""プロモ (P-*) 効果 回帰テスト バックフィル (自動生成 wave 163):
P-111 / P-112 / P-113 / P-114 / P-115 /
P-116 / P-118 / P-120 / P-121 / P-135 の 10 枚。

目的 (= test_backfill_auto_001〜162.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)
from engine.game import _compute_in_hand_cost_minus

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"            # ナミ (cost1 power2000) フィラー / 相手キャラ
COST2 = "OP01-013"           # サンジ (cost2 power3000) フィラー
COST5 = "OP15-030"           # ヒョウゾウ (cost5 power6000) cost5 素材
STRAWHAT_CHARA = "PRB02-012"  # ナミ (cost2 麦わらの一味) P-111 の victim
NAMI_LEADER = "OP03-040"     # ナミ (青 LEADER) P-112 条件用
EGGHEAD_LEADER = "EB04-001"  # ジュエリー・ボニー (エッグヘッド LEADER) P-118 条件用
EGGHEAD_CHARA_A = "EB04-002"  # ジュエリー・ボニー (cost1 エッグヘッド)
EGGHEAD_CHARA_B = "EB04-026"  # ブルーグラス (cost4 エッグヘッド)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, turn=0,
           opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(COST2)] * 30
    p1.deck = [repo.get(COST2)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 (先頭) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    return matches[0]


def _drain(st, picks):
    """resolve 後続の連鎖 modal を流す (guard 付き)。"""
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, picks)
        guard += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave163_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["P-111", "P-112", "P-113", "P-114", "P-115",
           "P-116", "P-118", "P-120", "P-121", "P-135"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  P-111 ニコ・ロビン (CHARACTER 緑 cost3 power4000):
#    【ターン1回】自分の特徴《麦わらの一味》を持つキャラが相手の効果で場を離れる場合、
#    代わりに自分のドン‼1枚をレストにできる。 (replace_leave / 任意)
# --------------------------------------------------------------------------- #
def test_p111_robin_replace_leave_rest_own_don_ai():
    """自麦わらキャラが相手効果で離脱 → 代わりに自ドン1枚レスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    robin = InPlay.of(repo.get("P-111"), sickness=False)
    victim = InPlay.of(repo.get(STRAWHAT_CHARA), sickness=False)  # 麦わらの一味
    me.characters = [robin, victim]
    me.don_active = 2  # レストできるアクティブドン

    active_before = me.don_active
    rested_before = me.don_rested
    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "自麦わらキャラの相手効果離脱が置換されていない"
    assert victim in me.characters, "置換成立時 victim は場に残るべき"
    assert me.don_active == active_before - 1, \
        f"置換コストで自ドン1枚がレストされていない: active={me.don_active}"
    assert me.don_rested == rested_before + 1, "レストドンが1枚増えるべき"


def test_p111_robin_replace_leave_non_strawhat_no_replace():
    """麦わらの一味 を持たない自キャラは 対象外 (target_feature 不一致) → 置換されない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    robin = InPlay.of(repo.get("P-111"), sickness=False)
    non_sh = InPlay.of(repo.get(COST5), sickness=False)  # OP15-030 ヒョウゾウ (人魚族/魚人島)
    assert "麦わらの一味" not in (non_sh.card.features or ""), \
        "テスト前提: OP15-030 は 麦わらの一味 を持たない"
    me.characters = [robin, non_sh]
    me.don_active = 2

    replaced = try_replace_ko(
        st, me, opp, non_sh, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "麦わらの一味でないキャラに置換が成立してはいけない (対象外)"


def test_p111_robin_replace_leave_not_by_opp_no_replace():
    """相手の効果でない離脱 (by_opp_effect=False) は 対象外 → 置換されない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    robin = InPlay.of(repo.get("P-111"), sickness=False)
    victim = InPlay.of(repo.get(STRAWHAT_CHARA), sickness=False)
    me.characters = [robin, victim]
    me.don_active = 2

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, "相手効果でない離脱に置換が成立してはいけない (対象外)"


def test_p111_robin_replace_leave_human_context_resolves():
    """人間 文脈: P-111 の置換は overlay に optional 指定が無く 自動適用 (modal なし)。
    人間文脈でも crash せず 置換が成立し 自ドン1枚がレストされる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    robin = InPlay.of(repo.get("P-111"), sickness=False)
    victim = InPlay.of(repo.get(STRAWHAT_CHARA), sickness=False)
    me.characters = [robin, victim]
    me.don_active = 2

    active_before = me.don_active
    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間文脈でも置換が成立するべき (True)"
    assert victim in me.characters, "置換成立時 victim は場に残るべき"
    assert me.don_active == active_before - 1, "置換コストで自ドン1枚がレストされるべき"


# --------------------------------------------------------------------------- #
#  P-112 ナミ (CHARACTER 青 cost5 power6000):
#    【登場時】自分のリーダーが「ナミ」の場合、自分のリーダーにレストのドン‼1枚までを、
#    付与する。その後、自分の手札からコスト2以下のキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_p112_nami_on_play_attach_and_play_ai():
    """【登場時】(ナミ leader) 自リーダーにレストドン1付与 + 手札からコスト2以下を登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAMI_LEADER, overlay)  # ナミ leader → 条件成立
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    me.hand = [repo.get(COST2)]  # cost2 キャラ (登場対象)

    eff = _eff(overlay, "P-112", "on_play")
    assert eval_condition(eff["if"], st, me, None) is True, \
        "ナミ leader で条件が成立していない"

    don_before = me.leader.attached_dons
    chars_before = len(me.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-112"), sickness=True))
    _drain(st, [0])

    assert me.leader.attached_dons == don_before + 1, \
        "自リーダーにレストドンが付与されていない"
    assert me.don_rested == 1, "レストドンが1枚消費されるべき"
    assert len(me.characters) == chars_before + 1, \
        "手札からコスト2以下のキャラが登場していない"


def test_p112_nami_condition_false_non_nami_leader():
    """リーダーが「ナミ」でなければ 条件不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ルフィ leader
    me = st.players[0]
    eff = _eff(overlay, "P-112", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "非・ナミ leader で条件が成立してはいけない"


def test_p112_nami_on_play_human_play_pick():
    """人間 + 手札にコスト2以下 複数 → 登場先を選ぶ play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, NAMI_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    me.hand = [repo.get(COST2), repo.get(NAMI)]  # cost2 / cost1 の 2 種

    # do[0] = play_from_hand (対象選択)
    execute_effect(_eff(overlay, "P-112", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-112"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in (COST2, NAMI) for c in me.characters), \
        "人間が選んだコスト2以下キャラが登場していない"


# --------------------------------------------------------------------------- #
#  P-113 ジュエリー・ボニー (CHARACTER 黄 cost4 power4000):
#    【ドン‼×2】【相手のターン中】このキャラは【ブロッカー】を得て、パワー+2000。
#    【トリガー】相手のコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_p113_bonney_on_attached_don_blocker_and_pump_ai():
    """【ドン×2】【相手ターン中】このキャラは【ブロッカー】+ パワー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn=1)  # 相手ターン
    me, opp = st.players[0], st.players[1]
    bonney = InPlay.of(repo.get("P-113"), sickness=False)  # power 4000
    me.characters = [bonney]

    power_before = bonney.power
    for prim in _eff(overlay, "P-113", "on_attached_don")["do"]:
        execute_effect(prim, st, me, opp, bonney)

    assert "ブロッカー" in bonney.granted_keywords, \
        f"【ブロッカー】が付与されていない: {bonney.granted_keywords}"
    assert bonney.power == power_before + 2000, \
        f"パワー+2000 が反映されていない: {bonney.power} (before {power_before})"


def test_p113_bonney_trigger_ko_opp_cost_le_3_ai():
    """【トリガー】相手のコスト3以下のキャラ1枚をKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn=1)  # 相手ターン (conditions: opp_turn)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST2), sickness=False)  # cost2 (≤3)
    opp.characters = [victim]

    for prim in _eff(overlay, "P-113", "trigger")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-113"), sickness=False))

    assert victim not in opp.characters, "相手のコスト3以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  P-114 ロロノア・ゾロ (CHARACTER 緑 cost4 power5000):
#    【ブロッカー】【自分のターン終了時】自分のアクティブのドン‼がある場合、
#    このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_p114_zoro_end_of_turn_untap_self_ai():
    """【ターン終了時】(自アクティブドンあり) このキャラをアクティブにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    zoro = InPlay.of(repo.get("P-114"), sickness=False)
    zoro.rested = True  # アタック等でレスト済
    me.characters = [zoro]
    me.don_active = 1  # 条件成立

    eff = _eff(overlay, "P-114", "end_of_turn")
    assert eval_condition(eff["if"], st, me, None) is True, \
        "自アクティブドン1で条件が成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, zoro)

    assert zoro.rested is False, "ターン終了時効果で 自身がアクティブに戻っていない"


def test_p114_zoro_condition_false_no_active_don():
    """自アクティブドンが無ければ self_don_active_ge=1 が不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.don_active = 0
    eff = _eff(overlay, "P-114", "end_of_turn")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "自アクティブドン0で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-115 ボア・ハンコック (CHARACTER 黄 cost6 power7000):
#    【登場時】自分のリーダーかキャラ1枚にレストのドン‼1枚までを、付与する。
# --------------------------------------------------------------------------- #
def test_p115_hancock_on_play_attach_rested_don_ai():
    """【登場時】自リーダー (既定) にレストのドン1枚を付与する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    for prim in _eff(overlay, "P-115", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-115"), sickness=True))

    assert me.leader.attached_dons == don_before + 1, \
        "自リーダーにレストドンが付与されていない"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_p115_hancock_on_play_human_target_pick():
    """人間 + 自リーダー/キャラ 複数 → 付与先を選ぶ target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2
    friend = InPlay.of(repo.get(NAMI), sickness=False)
    me.characters = [friend]

    execute_effect(_eff(overlay, "P-115", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-115"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == friend.instance_id)
    resolve_pending_choice(st, [friend_idx])
    _drain(st, [friend_idx])
    assert friend.attached_dons == 1, "人間が選んだキャラにレストドンが付与されていない"


# --------------------------------------------------------------------------- #
#  P-116 ニコ・ロビン (CHARACTER 黒 cost2 power1000):
#    【ブロッカー】【KO時】自分のトラッシュが7枚以上ある場合、カード1枚を引き、
#    自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_p116_robin_on_ko_draw_and_discard_ai():
    """【KO時】(トラッシュ7枚以上) 1枚引き、手札1枚を捨てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(COST2)] * 7  # トラッシュ 7 枚 (= 条件成立)
    me.hand = [repo.get(NAMI)]
    me.deck = [repo.get(COST2)] * 10

    eff = _eff(overlay, "P-116", "on_ko")
    assert eval_condition(eff["if"], st, me, None) is True, \
        "トラッシュ7枚で条件が成立していない"

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-116"), sickness=False))

    assert len(me.deck) == deck_before - 1, "1枚ドローでデッキが1枚減っていない"
    # 手札1枚捨て = トラッシュへ (ドローしたカードか元の手札のいずれか、 いずれにせよ +1)
    assert len(me.trash) == trash_before + 1, \
        "手札1枚を捨ててトラッシュが1枚増えていない"


def test_p116_robin_condition_false_few_trash():
    """トラッシュが7枚未満なら self_trash_count_ge=7 が不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.trash = [repo.get(COST2)] * 6  # 6 枚 (7 未満)
    eff = _eff(overlay, "P-116", "on_ko")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "トラッシュ6枚で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  P-118 リリス (CHARACTER 黄 cost6 power6000):
#    【登場時】自分のリーダーが特徴《エッグヘッド》を持つ場合、自分の手札からコスト5以下の、
#    特徴《エッグヘッド》か【トリガー】を持つキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_p118_lilith_on_play_play_egghead_ai():
    """【登場時】(エッグヘッド leader) 手札からコスト5以下エッグヘッドキャラを登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, EGGHEAD_LEADER, overlay)  # エッグヘッド leader → 条件成立
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(EGGHEAD_CHARA_A)]  # cost1 エッグヘッド

    eff = _eff(overlay, "P-118", "on_play")
    assert eval_condition(eff["if"], st, me, None) is True, \
        "エッグヘッド leader で条件が成立していない"

    chars_before = len(me.characters)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-118"), sickness=True))
    _drain(st, [0])

    assert len(me.characters) == chars_before + 1, \
        "手札からエッグヘッドキャラが登場していない"
    assert any(c.card.card_id == EGGHEAD_CHARA_A for c in me.characters), \
        "登場したのがエッグヘッドキャラでない"


def test_p118_lilith_condition_false_non_egghead_leader():
    """リーダーが《エッグヘッド》を持たなければ 条件不成立 → 条件 False。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ルフィ leader
    me = st.players[0]
    eff = _eff(overlay, "P-118", "on_play")
    assert eval_condition(eff["if"], st, me, None) is False, \
        "非・エッグヘッド leader で条件が成立してはいけない"


def test_p118_lilith_on_play_human_play_pick():
    """人間 + 手札にエッグヘッド cost5以下 複数 → play_from_hand modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, EGGHEAD_LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(EGGHEAD_CHARA_A), repo.get(EGGHEAD_CHARA_B)]  # 2 種

    execute_effect(_eff(overlay, "P-118", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-118"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card.card_id in (EGGHEAD_CHARA_A, EGGHEAD_CHARA_B)
               for c in me.characters), \
        "人間が選んだエッグヘッドキャラが登場していない"


# --------------------------------------------------------------------------- #
#  P-120 サンジ (CHARACTER 黄 cost6 power6000):
#    手札のこのカードは、相手のライフが離れているターン中、コスト－2。
# --------------------------------------------------------------------------- #
def test_p120_sanji_in_hand_cost_minus_when_opp_life_lost():
    """相手が今ターン ライフを失っていれば 手札のこのカードはコスト-2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life_lost_this_turn = True  # 相手のライフが今ターン離れている
    assert _compute_in_hand_cost_minus(st, me, repo.get("P-120")) == 2, \
        "相手ライフ喪失時に 手札コスト -2 が計算されていない"


def test_p120_sanji_in_hand_no_reduction_when_opp_life_intact():
    """相手が今ターン ライフを失っていなければ コスト軽減は無い (0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life_lost_this_turn = False
    assert _compute_in_hand_cost_minus(st, me, repo.get("P-120")) == 0, \
        "相手ライフ無事でコスト軽減が発生してはいけない"


# --------------------------------------------------------------------------- #
#  P-121 ブルック (CHARACTER 黒 cost4 power5000):
#    【登場時】自分のデッキの上から3枚をトラッシュに置く。
#    【KO時】相手は自身の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_p121_brook_on_play_mill_self_top3_ai():
    """【登場時】自デッキの上から3枚をトラッシュに置く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(COST2)] * 10
    me.trash = []

    deck_before = len(me.deck)
    for prim in _eff(overlay, "P-121", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-121"), sickness=True))

    assert len(me.deck) == deck_before - 3, "デッキ上3枚がトラッシュに置かれていない"
    assert len(me.trash) == 3, f"トラッシュが3枚になっていない: {len(me.trash)}"


def test_p121_brook_on_ko_opp_discard_2_ai():
    """【KO時】相手は自身の手札2枚を捨てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(COST2), repo.get(NAMI), repo.get(COST5)]  # 3 枚

    hand_before = len(opp.hand)
    for prim in _eff(overlay, "P-121", "on_ko")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-121"), sickness=False))

    assert len(opp.hand) == hand_before - 2, \
        f"相手の手札が2枚捨てられていない: {len(opp.hand)} (before {hand_before})"


# --------------------------------------------------------------------------- #
#  P-135 モンキー・D・ルフィ (CHARACTER 緑 cost5 power5000):
#    【ブロッカー】【登場時】相手のコスト5以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_p135_luffy_on_play_rest_opp_cost_le_5_ai():
    """【登場時】相手のコスト5以下キャラ1枚をレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(COST5), sickness=False)  # cost5 (≤5)
    victim.rested = False
    opp.characters = [victim]

    for prim in _eff(overlay, "P-135", "on_play")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("P-135"), sickness=True))

    assert victim.rested is True, "相手のコスト5以下キャラがレストにされていない"


def test_p135_luffy_on_play_human_rest_pick():
    """人間 + 相手のコスト5以下キャラ 複数 → target_pick modal が立ち resolve でレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(COST5), sickness=False)   # cost5
    b = InPlay.of(repo.get(COST2), sickness=False)   # cost2
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    execute_effect(_eff(overlay, "P-135", "on_play")["do"][0], st, me, opp,
                   InPlay.of(repo.get("P-135"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, [b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"
