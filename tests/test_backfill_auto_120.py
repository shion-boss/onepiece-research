# -*- coding: utf-8 -*-
"""OP12 弾 (青 海軍 / 白ひげ海賊団 系) 効果 回帰テスト バックフィル (自動生成 wave 120):
OP12-043 / OP12-044 / OP12-046 / OP12-047 / OP12-048 /
OP12-051 / OP12-054 / OP12-056 / OP12-057 / OP12-058 の 10 枚。

目的 (= test_backfill_auto_001〜119.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_play,
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


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の (do, entry) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


def _drain(st, guard=14):
    """pending_choice を種別ごとに適切に選び続けて解決しきる。
    confirm 系は承諾 ([1])、 候補選択系は先頭 ([0]) を選ぶ。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        kind = st.pending_choice.get("kind", "")
        if kind in ("optional_cost_confirm", "reveal_top_play_confirm",
                    "replace_ko_optional"):
            resolve_pending_choice(st, [1])
        else:
            cands = (st.pending_choice.get("candidates")
                     or st.pending_choice.get("cards") or [])
            resolve_pending_choice(st, [0] if len(cands) > 0 else [])
        g += 1


# 定番 leader / helper カード
_NEUTRAL = "OP01-001"           # ルフィ (赤、 leader 条件が無い汎用)
_NAVY_LEADER = "OP11-001"       # コビー (赤/黒 / 海軍)
_SHICHI_LEADER = "OP14-040"     # ジンベエ (青 / 王下七武海)
_WB_LEADER = "OP08-002"         # マルコ (赤/青 / 白ひげ海賊団)
_WB_CHAR = "EB02-027"           # ビスタ (青 cost4 / 白ひげ海賊団)
_NAVY_CHAR_BLUE = "EB03-025"    # ヒナ (青 cost5 pow6000 / 海軍)
_NAVY_CHAR_BLACK = "OP03-089"   # ブランニュー (黒 cost2 / 海軍)
_KUZAN = "OP12-043"             # クザン (青 cost6 pow8000 / 海軍)
_VICTIM = "OP01-016"            # ナミ (赤 cost1 pow2000)
_FILLER = "OP01-013"            # サンジ (赤 cost2)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op12_wave120_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP12-043", "OP12-044", "OP12-046", "OP12-047", "OP12-048",
           "OP12-051", "OP12-054", "OP12-056", "OP12-057", "OP12-058"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP12-043 クザン (CHARACTER 青 cost6):
#    静的: 手札5以上で コスト+1
#    【登場時】手札1捨て → 相手キャラ1枚まで 次相手リフレッシュまで stay_rested
# --------------------------------------------------------------------------- #
def test_op12_043_kuzan_on_play_stay_rested_ai():
    """【登場時】 AI: 相手キャラ 1 体に stay_rested_next_refresh を付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP12-043", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get(_KUZAN), sickness=True))

    assert victim.stay_rested_next_refresh is True, \
        "相手キャラに stay_rested_next_refresh が付与されていない"


def test_op12_043_kuzan_on_play_human_target_pick():
    """人間 + 相手キャラ複数 → target_pick modal → 選んだ1体だけに stay_rested。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)
    b = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP12-043", "on_play")
    execute_effect(do[0], st, me, opp, InPlay.of(repo.get(_KUZAN), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.stay_rested_next_refresh is True, "人間が選んだキャラに stay_rested が付いていない"
    assert a.stay_rested_next_refresh is False, "選ばなかったキャラには付かないべき"


def test_op12_043_kuzan_static_cost_plus_when_hand_ge_5():
    """静的: 自分の手札 5 枚以上で このキャラ (場) の 元々コストが +1 (6→7)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    kuzan = InPlay.of(repo.get(_KUZAN), sickness=False)
    me.characters = [kuzan]

    me.hand = [repo.get(_FILLER)] * 5   # 手札 5 枚 = 条件成立
    evaluate_static_effects(st, overlay)
    assert kuzan.base_cost == 7, f"手札5枚で cost+1 (=7) にならない: {kuzan.base_cost}"

    me.hand = [repo.get(_FILLER)] * 4   # 手札 4 枚 = 条件不成立
    kuzan.base_cost_override = None     # 前回の override をリセット
    evaluate_static_effects(st, overlay)
    assert kuzan.base_cost == 6, f"手札4枚では cost が元の 6 のままであるべき: {kuzan.base_cost}"


# --------------------------------------------------------------------------- #
#  OP12-044 サカズキ (CHARACTER 青 cost7):
#    【登場時】リーダー《海軍》なら 2 ドロー
#    【起動メイン】【ターン1回】手札1捨て → 自リーダー/キャラにレストドン1まで付与
# --------------------------------------------------------------------------- #
def test_op12_044_sakazuki_on_play_draw_when_navy_leader():
    """【登場時】 海軍 leader → カード2枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NAVY_LEADER, overlay)  # コビー = 海軍
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    src = InPlay.of(repo.get("OP12-044"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, src, overlay)

    assert len(me.hand) == hand_before + 2, f"海軍 leader で 2 ドローされていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが 2 枚減っていない"


def test_op12_044_sakazuki_on_play_no_draw_non_navy_leader():
    """【登場時】 非海軍 leader なら ドローしない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # ルフィ = 非海軍
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    src = InPlay.of(repo.get("OP12-044"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    _, entry = _do(overlay, "OP12-044", "on_play")
    assert entry.get("if", {}).get("leader_feature") == "海軍", \
        "overlay の登場時条件 leader_feature=海軍 が無い"
    trigger_on_play(st, me, opp, src, overlay)
    assert len(me.hand) == hand_before, "非海軍 leader なのにドローした"


def test_op12_044_sakazuki_activate_main_attach_rested_don_ai():
    """【起動メイン】 手札1捨て → 自リーダー/キャラにレストドン1付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NAVY_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    sakazuki = InPlay.of(repo.get("OP12-044"), sickness=False)
    me.characters = [sakazuki]
    me.hand = [repo.get(_FILLER)]  # 捨てるコスト
    me.don_rested = 2

    total_before = me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
    rested_before = me.don_rested
    hand_before = len(me.hand)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-044"]
    assert len(opts) == 1, f"OP12-044 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    total_after = me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
    assert total_after == total_before + 1, \
        f"レストドンが自陣に1枚付与されていない: {total_after} (before {total_before})"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"
    assert len(me.hand) == hand_before - 1, "コストで手札1枚が捨てられるべき"


# --------------------------------------------------------------------------- #
#  OP12-046 ゼファー (CHARACTER 青 cost5):
#    【登場時】自分の手札2枚を捨てる
#    【起動メイン】自身をトラッシュ → コスト5以下のキャラ1枚まで 持ち主の手札へ
# --------------------------------------------------------------------------- #
def test_op12_046_zephyr_on_play_discard_two_ai():
    """【登場時】 AI: 手札 2 枚をトラッシュに捨てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_VICTIM), repo.get(_NAVY_CHAR_BLACK)]

    hand_before = len(me.hand)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP12-046", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-046"), sickness=True))

    assert len(me.hand) == hand_before - 2, f"手札が 2 枚減っていない: {len(me.hand)}"
    assert len(me.trash) == trash_before + 2, f"トラッシュが 2 枚増えていない: {len(me.trash)}"


def test_op12_046_zephyr_activate_main_bounce_ai():
    """【起動メイン】 AI: 自身をトラッシュ (コスト) → コスト5以下の相手キャラを手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    zephyr = InPlay.of(repo.get("OP12-046"), sickness=False)
    me.characters = [zephyr]
    victim = InPlay.of(repo.get(_NAVY_CHAR_BLUE), sickness=False)  # cost5 (<=5)
    opp.characters = [victim]

    opp_hand_before = len(opp.hand)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-046"]
    assert len(opts) == 1, f"OP12-046 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert victim not in opp.characters, "コスト5以下の相手キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "相手の手札が 1 枚増えていない"
    assert zephyr not in me.characters, "コスト (自身トラッシュ) が支払われていない"


def test_op12_046_zephyr_activate_main_human_pick():
    """人間 + 相手キャラ複数 (cost<=5) → target_pick modal → 選んだ1体を手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    zephyr = InPlay.of(repo.get("OP12-046"), sickness=False)
    me.characters = [zephyr]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)         # cost1
    b = InPlay.of(repo.get(_NAVY_CHAR_BLUE), sickness=False)  # cost5
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-046"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが手札に戻っていない"
    assert a in opp.characters, "選ばなかったキャラまで戻された"


# --------------------------------------------------------------------------- #
#  OP12-047 センゴク (CHARACTER 青 cost3):
#    【登場時】手札1捨て → デッキ上5枚を見て「センゴク」以外の《海軍》2枚まで手札へ、
#              残りをデッキの下
# --------------------------------------------------------------------------- #
def test_op12_047_sengoku_on_play_search_navy_ai():
    """【登場時】 AI: 手札1捨て → デッキ上の《海軍》2枚を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # 捨てるコスト
    # デッキ上に《海軍》を 2 枚仕込む
    me.deck = [repo.get(_NAVY_CHAR_BLACK), repo.get(_NAVY_CHAR_BLUE)] + \
        [repo.get(_FILLER)] * 8

    do, _ = _do(overlay, "OP12-047", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-047"), sickness=True))
    _drain(st)

    hand_ids = [c.card_id for c in me.hand]
    assert _NAVY_CHAR_BLACK in hand_ids and _NAVY_CHAR_BLUE in hand_ids, \
        f"デッキ上の《海軍》2枚が手札に加わっていない: {hand_ids}"


def test_op12_047_sengoku_on_play_human_flow():
    """人間: 任意コスト → 承諾すると search_top_n の流れで《海軍》を手札に加えられる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]
    me.deck = [repo.get(_NAVY_CHAR_BLUE)] + [repo.get(_FILLER)] * 9

    do, _ = _do(overlay, "OP12-047", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP12-047"), sickness=True))

    assert st.pending_choice is not None, "人間の任意コスト/選択 modal が立たない"
    _drain(st)
    hand_ids = [c.card_id for c in me.hand]
    assert _NAVY_CHAR_BLUE in hand_ids, \
        f"人間フローで《海軍》が手札に加わっていない: {hand_ids}"


# --------------------------------------------------------------------------- #
#  OP12-048 ドンキホーテ・ロシナンテ (CHARACTER 青 cost1):
#    【相手のターン中】自分の青《海軍》キャラが相手効果で離れる場合、代わりに
#      このキャラをレストにし、手札1捨てられる (replace_leave)
# --------------------------------------------------------------------------- #
def test_op12_048_rosinante_replace_leave_ai():
    """AI: 相手ターン中 青《海軍》が相手効果で離脱 → ロシナンテをレスト + 手札1捨てで代替。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手 (P1) のターン = opp_turn 成立
    rosinante = InPlay.of(repo.get("OP12-048"), sickness=False)
    victim = InPlay.of(repo.get(_KUZAN), sickness=False)  # 青《海軍》
    me.characters = [rosinante, victim]
    me.hand = [repo.get(_FILLER)]  # 捨てるコスト

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "青《海軍》の相手効果離脱が代替されていない"
    assert rosinante.rested is True, "代替でロシナンテがレストされていない"
    assert len(me.hand) == hand_before - 1, "代替コストで手札1枚が捨てられるべき"


def test_op12_048_rosinante_replace_leave_human_confirm():
    """人間: replace_leave は任意 → replace_ko_optional modal が立ち、承諾で代替する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1
    rosinante = InPlay.of(repo.get("OP12-048"), sickness=False)
    victim = InPlay.of(repo.get(_KUZAN), sickness=False)
    me.characters = [rosinante, victim]
    me.hand = [repo.get(_FILLER)]

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_ko の任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    _drain(st)
    assert rosinante.rested is True, "人間承諾後 ロシナンテがレストされていない"


# --------------------------------------------------------------------------- #
#  OP12-051 ヒナ (CHARACTER 青 cost3):
#    【起動メイン】自身レスト + 手札1捨て → 相手の元々コスト4以下キャラ1枚まで、
#      このターン中【ブロッカー】発動不可
# --------------------------------------------------------------------------- #
def test_op12_051_hina_activate_main_disable_blocker_ai():
    """【起動メイン】 AI: コスト支払い → 相手コスト4以下キャラのブロッカーを無効化。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    hina = InPlay.of(repo.get("OP12-051"), sickness=False)
    me.characters = [hina]
    me.hand = [repo.get(_FILLER)]  # 捨てるコスト
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=4)
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-051"]
    assert len(opts) == 1, f"OP12-051 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert victim.blocker_disabled_until_turn_end is True, \
        "相手コスト4以下キャラのブロッカーが無効化されていない"
    assert hina.rested is True, "起動メインコストでヒナがレストされるべき"


def test_op12_051_hina_activate_main_human_pick():
    """人間 + 相手コスト4以下キャラ複数 → target_pick modal → 選んだ1体を無効化。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    hina = InPlay.of(repo.get("OP12-051"), sickness=False)
    me.characters = [hina]
    me.hand = [repo.get(_FILLER)]
    a = InPlay.of(repo.get(_VICTIM), sickness=False)   # cost1
    b = InPlay.of(repo.get(_FILLER), sickness=False)   # cost2 (<=4)
    opp.characters = [a, b]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-051"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    # 任意コスト (自身レスト + 手札1捨て) の確認 modal → 承諾
    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾

    # 承諾後、 相手コスト4以下キャラの target_pick modal が立つ
    assert st.pending_choice is not None, "承諾後に target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.blocker_disabled_until_turn_end is True, \
        "人間が選んだキャラのブロッカーが無効化されていない"
    assert a.blocker_disabled_until_turn_end is False, "選ばなかったキャラは無効化されないべき"


# --------------------------------------------------------------------------- #
#  OP12-054 マーシャル・D・ティーチ (CHARACTER 青 cost1):
#    【登場時】リーダー《王下七武海》なら このキャラ以外のコスト1以下キャラ1枚まで
#      持ち主の手札へ
# --------------------------------------------------------------------------- #
def test_op12_054_teach_on_play_bounce_when_shichibukai_ai():
    """【登場時】 王下七武海 leader → 相手のコスト1以下キャラを持ち主の手札へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHICHI_LEADER, overlay)  # ジンベエ = 王下七武海
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("OP12-054"), sickness=True)
    me.characters = [teach]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1
    opp.characters = [victim]

    opp_hand_before = len(opp.hand)
    trigger_on_play(st, me, opp, teach, overlay)
    _drain(st)

    assert victim not in opp.characters, "コスト1以下キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "相手の手札が 1 枚増えていない"


def test_op12_054_teach_on_play_no_bounce_non_shichibukai():
    """【登場時】 非王下七武海 leader なら 戻さない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # ルフィ = 非王下七武海
    me, opp = st.players[0], st.players[1]
    teach = InPlay.of(repo.get("OP12-054"), sickness=True)
    me.characters = [teach]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [victim]

    _, entry = _do(overlay, "OP12-054", "on_play")
    assert entry.get("if", {}).get("leader_feature") == "王下七武海", \
        "overlay の登場時条件 leader_feature=王下七武海 が無い"
    trigger_on_play(st, me, opp, teach, overlay)
    _drain(st)
    assert victim in opp.characters, "非王下七武海 leader なのにキャラが戻された"


# --------------------------------------------------------------------------- #
#  OP12-056 モンキー・D・ガープ (CHARACTER 青 cost8):
#    【登場時】手札1捨て → 手札から「ガープ」以外の青《海軍》power8000以下1枚を登場
# --------------------------------------------------------------------------- #
def test_op12_056_garp_on_play_play_from_hand_ai():
    """【登場時】 AI: 手札の青《海軍》(power<=8000) を登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_NAVY_CHAR_BLUE), repo.get(_FILLER)]  # ヒナ (青海軍 6000)

    do, _ = _do(overlay, "OP12-056", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP12-056"), sickness=True))
    _drain(st)

    assert any(c.card.card_id == _NAVY_CHAR_BLUE for c in me.characters), \
        f"手札の青《海軍》が登場していない: {[c.card.card_id for c in me.characters]}"
    assert repo.get(_NAVY_CHAR_BLUE) not in me.hand, "登場したキャラが手札から取り除かれていない"


def test_op12_056_garp_on_play_human_pick():
    """人間 + 手札に対象複数 → play_from_hand 系 modal が立ち、選んで登場できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 対象 (青《海軍》power<=8000) を 2 種類 手札に
    me.hand = [repo.get(_NAVY_CHAR_BLUE), repo.get(_KUZAN)]  # ヒナ(6000) / クザン(8000)

    do, _ = _do(overlay, "OP12-056", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP12-056"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    _drain(st)
    assert len(me.characters) >= 1, "人間フローでキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP12-057 アイス塊暴雉嘴 (EVENT 青 cost1):
#    【カウンター】自リーダー/キャラ1枚まで +4000、その後手札1捨て
#    【トリガー】手札1捨てられる → 1 ドロー
# --------------------------------------------------------------------------- #
def test_op12_057_counter_power_pump_ai():
    """【カウンター】 AI: 自リーダーを このバトル中 +4000 (コスト手札1捨て)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # 捨てるコスト

    power_before = me.leader.power
    do, _ = _do(overlay, "OP12-057", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert me.leader.power == power_before + 4000, \
        f"カウンターで自リーダーに +4000 されていない: {me.leader.power} (before {power_before})"


def test_op12_057_trigger_optional_draw_ai():
    """【トリガー】 AI: 手札1捨てて 1 ドロー (deck が 1 枚減る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER)]  # 捨てるコスト
    me.deck = [repo.get(_VICTIM)] + [repo.get(_FILLER)] * 9

    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP12-057", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert len(me.deck) == deck_before - 1, f"トリガーで 1 ドローされていない: {len(me.deck)}"


# --------------------------------------------------------------------------- #
#  OP12-058 …おれは白ひげを王にする (EVENT 青 cost9):
#    【メイン】リーダーが『白ひげ海賊団』を含む場合、デッキ上1公開し
#      cost9以下『白ひげ海賊団』キャラなら登場、登場キャラは【速攻】
#    【トリガー】1 ドロー
# --------------------------------------------------------------------------- #
def test_op12_058_main_reveal_top_play_whitebeard_ai():
    """【メイン】 白ひげ海賊団 leader → デッキ上の『白ひげ海賊団』キャラを登場 + 速攻付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)  # マルコ = 白ひげ海賊団
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WB_CHAR)] + [repo.get(_FILLER)] * 10  # 上に ビスタ (白ひげ cost4)
    me.characters = []

    _, entry = _do(overlay, "OP12-058", "main")
    assert entry.get("if", {}).get("leader_feature_contains") == "白ひげ海賊団", \
        "overlay のメイン条件 leader_feature_contains=白ひげ海賊団 が無い"
    do = entry["do"]
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    played = [c for c in me.characters if c.card.card_id == _WB_CHAR]
    assert played, f"デッキ上の『白ひげ海賊団』キャラが登場していない: {[c.card.card_id for c in me.characters]}"
    assert "速攻" in played[0].granted_keywords, \
        f"登場した『白ひげ海賊団』キャラに【速攻】が付与されていない: {played[0].granted_keywords}"


def test_op12_058_main_reveal_non_matching_no_play():
    """negative: デッキ上が対象外 (白ひげでない) なら登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _WB_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10  # 上は麦わらの一味 (白ひげでない)
    me.characters = []

    do, _ = _do(overlay, "OP12-058", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert not me.characters, "対象外なのにキャラが登場した"


def test_op12_058_trigger_draw():
    """【トリガー】 カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_VICTIM)] + [repo.get(_FILLER)] * 9

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP12-058", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, f"トリガーで 1 ドローされていない: {len(me.hand)}"
