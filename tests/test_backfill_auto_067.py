# -*- coding: utf-8 -*-
"""OP06 弾 効果 回帰テスト バックフィル (自動生成 wave 067):
OP06-045 / OP06-046 / OP06-050 / OP06-051 / OP06-052 / OP06-053 /
OP06-054 / OP06-055 / OP06-056 / OP06-057 の 10 枚 (青 海軍中心 + 麦わら)。

目的 (= 永続的 pytest による担保、 test_backfill_auto_066.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 択一 / 任意コスト を 持つカードは 人間 actor で pending_choice が
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
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER = "OP01-001"      # ロロノア・ゾロ (赤、 汎用リーダー)
_FILLER = "OP01-013"      # サンジ cost2 power3000 (汎用フィラー / cost<=N 対象)
_NAMI = "OP01-016"        # ナミ cost1 power2000 (cost<=N 対象)
_NAVY = "OP06-045"        # クザン (海軍、 search 対象用)


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


def _drain(st, pick=0, guard=8):
    """pending_choice を pick で自動解決し切る (= 後続効果を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave67_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP06-045", "OP06-046", "OP06-050", "OP06-051", "OP06-052",
           "OP06-053", "OP06-054", "OP06-055", "OP06-056", "OP06-057"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP06-045 クザン (CHARACTER 青 cost3):
#    【登場時】カード2枚を引き、自分の手札2枚を好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op06_045_on_play_draw2_hand2_to_bottom_ai():
    """登場時 (AI): 2枚引いて 手札2枚をデッキ下へ (手札 net ±0、 デッキ net ±0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_NAMI)]        # 開始手札 1
    me.deck = [repo.get(_FILLER)] * 10
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP06-045", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-045"), sickness=True))
        _drain(st)

    # 手札: 1 + 2(draw) - 2(bottom) = 1、 デッキ: 10 - 2(draw) + 2(bottom) = 10
    assert len(me.hand) == hand_before + 2 - 2, \
        f"手札 net (draw+2 / bottom-2) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2 + 2, \
        f"デッキ net (draw-2 / bottom+2) が合わない: {len(me.deck)}"


def test_op06_045_on_play_human_deck_bottom_pick():
    """登場時 (人間): 引いた後 手札2枚をデッキ下に置く選択 modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_NAMI), repo.get(_FILLER)]
    me.deck = [repo.get(_FILLER)] * 10

    saw_pick_modal = False
    for prim in _do(overlay, "OP06-045", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-045"), sickness=True))
        # draw は即時、 self_hand_to_deck_bottom は 人間 pick modal を立てる
        if st.pending_choice is not None:
            saw_pick_modal = True
            assert "hand" in st.pending_choice.get("kind", "") \
                and "deck" in st.pending_choice.get("kind", ""), \
                f"kind が手札→デッキ下 系でない: {st.pending_choice.get('kind')}"
            _drain(st)

    assert saw_pick_modal, "人間 context で 手札→デッキ下の選択 modal が立たなかった"
    assert st.pending_choice is None, "解決後も modal が残る"
    # 手札: 2 + 2(draw) - 2(bottom) = 2、 デッキ: 10 - 2(draw) + 2(bottom) = 10
    assert len(me.hand) == 2, f"手札 net が合わない: hand={len(me.hand)}"
    assert len(me.deck) == 10, f"デッキ net が合わない: deck={len(me.deck)}"


# --------------------------------------------------------------------------- #
#  OP06-046 サカズキ (CHARACTER 青 cost5):
#    【登場時】コスト2以下のキャラ1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op06_046_on_play_return_cost_le2_ai():
    """登場時 (AI): 相手のコスト2以下キャラ1枚を持ち主のデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 2
    opp.characters = [victim]
    opp.deck = []

    for prim in _do(overlay, "OP06-046", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-046"), sickness=True))
        _drain(st)

    assert victim not in opp.characters, "相手コスト2以下キャラがデッキ下に置かれていない"
    assert len(opp.deck) == 1, "戻したキャラが持ち主のデッキ下に置かれていない"


def test_op06_046_on_play_human_target_pick():
    """登場時 (人間): コスト2以下 複数 → target_pick modal で選択してデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    opp.characters = [a, b]
    opp.deck = []

    execute_effect(_do(overlay, "OP06-046", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-046"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"コスト2以下候補が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラがデッキ下に置かれていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP06-050 たしぎ (CHARACTER 青 cost1):
#    【登場時】自分のデッキの上から5枚を見て、「たしぎ」以外の特徴《海軍》を持つ
#      カード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op06_050_on_play_search_navy_ai():
    """登場時 (AI): デッキ上5枚から《海軍》カード1枚を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    navy = repo.get(_NAVY)  # クザン 海軍
    assert "海軍" in (navy.features or ()), "テスト前提: OP06-045 は 海軍"
    me.deck = [navy] + [repo.get(_FILLER)] * 10
    me.hand = []

    for prim in _do(overlay, "OP06-050", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-050"), sickness=True))
        _drain(st)

    assert any(c.card_id == _NAVY for c in me.hand), \
        "デッキ上5枚から《海軍》カードが手札に加わっていない"


def test_op06_050_on_play_human_search_pick():
    """登場時 (人間): デッキ上5枚に《海軍》複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    navy = repo.get(_NAVY)
    me.deck = [navy, repo.get(_FILLER), navy] + [repo.get(_FILLER)] * 10
    me.hand = []

    execute_effect(_do(overlay, "OP06-050", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-050"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (海軍) を選択
    _drain(st)
    assert any(c.card_id == _NAVY for c in me.hand), \
        "人間が選んだ《海軍》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP06-051 つる (CHARACTER 青 cost5):
#    【登場時】自分の手札2枚を捨てることができる：
#      相手は自身のキャラ1枚を持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op06_051_on_play_optional_return_ai():
    """登場時 (AI): 手札2枚捨て → 相手キャラ1枚を持ち主の手札に戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_NAMI)]  # 捨てコスト用 2 枚
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]
    opp.hand = []
    me_hand_before = len(me.hand)

    for prim in _do(overlay, "OP06-051", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-051"), sickness=True))
        _drain(st)

    assert len(me.hand) == me_hand_before - 2, "任意コストの手札2枚捨てが起きていない"
    assert victim not in opp.characters, "相手キャラが手札に戻されていない"
    assert len(opp.hand) == 1, "戻したキャラが相手 (持ち主) の手札に加わっていない"


def test_op06_051_on_play_human_optional_confirm():
    """登場時 (人間): optional_cost_confirm modal → 承諾で手札2捨て + 相手キャラ選択して戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_NAMI)]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [a, b]
    opp.hand = []

    execute_effect(_do(overlay, "OP06-051", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-051"), sickness=True))

    assert st.pending_choice is not None, "任意コストの optional_cost_confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= 任意コストを払う)

    # コスト支払い後、 相手キャラを戻す target_pick が立つ
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        "承諾後に相手キャラを戻す target_pick modal が立たない"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"相手キャラ候補が 2 件でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)

    assert len(me.hand) == 0, "承諾後 手札2枚が捨てられていない"
    assert b not in opp.characters, "人間が選んだ相手キャラが手札に戻されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP06-052 トキカケ (CHARACTER 青 cost2):
#    【ドン!!×1】自分の手札が4枚以下の場合、このキャラはバトルでKOされない。
# --------------------------------------------------------------------------- #
def test_op06_052_static_battle_ko_immune_when_hand_le4():
    """静的 (ドン1 + 手札4以下): バトルKO耐性 (battle_ko_immune_static) が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    toki = InPlay.of(repo.get("OP06-052"), sickness=False)
    toki.attached_dons = 1                 # 【ドン!!×1】ゲート成立
    me.characters = [toki]
    me.hand = [repo.get(_FILLER)] * 3      # 手札3 <= 4 (条件成立)

    evaluate_static_effects(st, overlay)
    assert toki.battle_ko_immune_static is True, \
        "ドン1 + 手札4以下でバトルKO耐性が立っていない"


def test_op06_052_static_off_when_hand_gt4_or_no_don():
    """静的 OFF: 手札5枚 または ドン0 なら バトルKO耐性は立たない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    toki = InPlay.of(repo.get("OP06-052"), sickness=False)
    me.characters = [toki]

    # 手札5枚 (条件不成立)
    toki.attached_dons = 1
    me.hand = [repo.get(_FILLER)] * 5
    evaluate_static_effects(st, overlay)
    assert toki.battle_ko_immune_static is False, \
        "手札5枚 (条件不成立) でバトルKO耐性が立ってはいけない"

    # ドン0 (ゲート不成立)
    toki.attached_dons = 0
    me.hand = [repo.get(_FILLER)] * 3
    evaluate_static_effects(st, overlay)
    assert toki.battle_ko_immune_static is False, \
        "ドン0 (【ドン!!×1】不成立) でバトルKO耐性が立ってはいけない"


# --------------------------------------------------------------------------- #
#  OP06-053 ハグワール・D・サウロ (CHARACTER 青 cost2):
#    【KO時】コスト2以下のキャラ1枚までを、持ち主のデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op06_053_on_ko_return_cost_le2_ai():
    """KO時 (AI): 相手のコスト2以下キャラ1枚を持ち主のデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 2
    opp.characters = [victim]
    opp.deck = []

    for prim in _do(overlay, "OP06-053", "on_ko"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-053"), sickness=False))
        _drain(st)

    assert victim not in opp.characters, "KO時に相手コスト2以下キャラがデッキ下に置かれていない"
    assert len(opp.deck) == 1, "戻したキャラが持ち主のデッキ下に置かれていない"


def test_op06_053_on_ko_human_target_pick():
    """KO時 (人間): コスト2以下 複数 → target_pick modal で選択してデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1
    opp.characters = [a, b]
    opp.deck = []

    execute_effect(_do(overlay, "OP06-053", "on_ko")[0], st, me, opp,
                   InPlay.of(repo.get("OP06-053"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"コスト2以下候補が 2 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラがデッキ下に置かれていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP06-054 ボルサリーノ (CHARACTER 青 cost2):
#    自分の手札が5枚以下の場合、このキャラは【ブロッカー】を得る。(静的)
# --------------------------------------------------------------------------- #
def test_op06_054_static_blocker_when_hand_le5():
    """静的 (手札5以下): ブロッカーを得る (is_blocker_now)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    assert repo.get("OP06-054").is_blocker is False, \
        "テスト前提: ボルサリーノは innate ブロッカーではない"
    bols = InPlay.of(repo.get("OP06-054"), sickness=False)
    me.characters = [bols]
    me.hand = [repo.get(_FILLER)] * 5  # 手札5 <= 5 (条件成立)

    evaluate_static_effects(st, overlay)
    assert bols.is_blocker_now is True, \
        "手札5以下でボルサリーノが【ブロッカー】を得ていない"


def test_op06_054_static_no_blocker_when_hand_gt5():
    """静的 OFF: 手札6枚なら【ブロッカー】を得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    bols = InPlay.of(repo.get("OP06-054"), sickness=False)
    me.characters = [bols]
    me.hand = [repo.get(_FILLER)] * 6  # 手札6 > 5 (条件不成立)

    evaluate_static_effects(st, overlay)
    assert bols.is_blocker_now is False, \
        "手札6枚 (条件不成立) でボルサリーノが【ブロッカー】を得てはいけない"


# --------------------------------------------------------------------------- #
#  OP06-055 モンキー・D・ガープ (CHARACTER 青 cost5):
#    【ドン!!×2】【アタック時】自分の手札が4枚以下の場合、相手は、このバトル中、
#      【ブロッカー】を発動できない。
# --------------------------------------------------------------------------- #
def test_op06_055_on_attack_grants_block_disable_ai():
    """アタック時 (AI): (ドン2 + 手札4以下ゲート) 自身に「ブロック不可」を付与する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("OP06-055"), sickness=False)
    garp.attached_dons = 2
    me.characters = [garp]
    me.hand = [repo.get(_FILLER)] * 3  # 手札3 <= 4

    on_attack = _eff(overlay, "OP06-055", "on_attack")
    assert on_attack.get("if", {}).get("self_hand_count_le") == 4, \
        "overlay の 手札4以下条件 (self_hand_count_le=4) が無い"
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート (self_attached_don_ge=2) が無い"
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, garp)
        _drain(st)

    assert "ブロック不可" in garp.granted_keywords, \
        "アタック時に「ブロック不可」が付与されていない"


# --------------------------------------------------------------------------- #
#  OP06-056 天叢雲剣 (EVENT 青 cost2):
#    【メイン】相手の、コスト2以下のキャラ1枚までとコスト1以下のキャラ1枚までを、
#      持ち主のデッキの下に好きな順番で置く。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op06_056_main_return_multi_ai():
    """メイン (AI): 相手コスト2以下1枚 + コスト1以下1枚を持ち主のデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 (<=2 枠)
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1 (<=1 枠)
    opp.characters = [a, b]
    opp.deck = []

    for prim in _do(overlay, "OP06-056", "main"):
        execute_effect(prim, st, me, opp, None)
        _drain(st)

    assert a not in opp.characters and b not in opp.characters, \
        "相手のコスト2以下 + コスト1以下キャラがデッキ下に置かれていない"
    assert len(opp.deck) == 2, "戻した2枚が持ち主のデッキ下に置かれていない"


def test_op06_056_main_human_target_pick():
    """メイン (人間): コスト2以下枠の対象選択 target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [a, b]
    opp.deck = []

    execute_effect(_do(overlay, "OP06-056", "main")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"コスト2以下候補が 2 件でない: {len(cands)}"
    resolve_pending_choice(st, [0])
    _drain(st)
    # 少なくとも 1 枚は デッキ下へ移動している
    assert len(opp.deck) >= 1, "人間が選んだキャラがデッキ下に置かれていない"


def test_op06_056_trigger_fires_main():
    """トリガー (AI): 自身の【メイン】効果 (return_multi) を発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1
    opp.characters = [victim]
    opp.deck = []

    for prim in _do(overlay, "OP06-056", "trigger"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-056"), sickness=False))
        _drain(st)

    assert victim not in opp.characters, "トリガーからメイン効果 (デッキ下) が発動していない"


# --------------------------------------------------------------------------- #
#  OP06-057 おれは女の涙を疑わねェっ!!!! (EVENT 青 cost1):
#    【メイン】自分のリーダーかキャラ1枚までを、このターン中、パワー+1000。その後、
#      自分のデッキの上から1枚を公開し、コスト2のキャラカード1枚までを、登場させ、
#      残りをデッキの上か下に置く。
#    【トリガー】自分の手札からコスト2のキャラカード1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op06_057_main_pump_and_reveal_play_ai():
    """メイン (AI): リーダー +1000 + デッキ上1枚公開しコスト2キャラを登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    assert repo.get(_FILLER).cost == 2, "テスト前提: OP01-013 は cost2"
    me.deck = [repo.get(_FILLER)] + [repo.get(_NAMI)] * 10  # top = cost2 キャラ
    me.hand = []
    leader_before = me.leader.power
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP06-057", "main"):
        execute_effect(prim, st, me, opp, None)
        _drain(st)

    assert me.leader.power == leader_before + 1000, \
        f"リーダー +1000 が反映されていない: {me.leader.power} (before {leader_before})"
    assert len(me.characters) == chars_before + 1, \
        "デッキ上のコスト2キャラが登場していない"
    assert any(c.card.card_id == _FILLER for c in me.characters), \
        "登場したキャラが公開されたコスト2キャラでない"


def test_op06_057_main_human_pump_target_pick():
    """メイン (人間): +1000 の対象 (リーダー/キャラ) を選ぶ target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]
    me.deck = [repo.get(_NAMI)] * 10  # top は cost1 (登場対象なし)
    me.hand = []

    execute_effect(_do(overlay, "OP06-057", "main")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain(st)
    assert friend.power == friend_before + 1000, \
        "人間が選んだキャラに +1000 が反映されていない"


def test_op06_057_trigger_play_cost2_from_hand_ai():
    """トリガー (AI): 手札のコスト2キャラ1枚を登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # cost2 キャラ
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP06-057", "trigger"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP06-057"), sickness=False))
        _drain(st)

    assert len(me.characters) == chars_before + 1, \
        "トリガーで手札のコスト2キャラが登場していない"
    assert any(c.card.card_id == _FILLER for c in me.characters), \
        "登場したキャラが手札のコスト2キャラでない"
