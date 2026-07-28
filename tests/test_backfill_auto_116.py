# -*- coding: utf-8 -*-
"""OP11 弾 (黄 魚人島 / しらほし + 黄 超新星 + 黄 麦わら イベント 系) 効果
回帰テスト バックフィル (自動生成 wave 116):
OP11-101 / OP11-102 / OP11-103 / OP11-104 / OP11-107 /
OP11-108 / OP11-109 / OP11-110 / OP11-112 / OP11-114 の 10 枚。

目的 (= test_backfill_auto_001.py と同一方針):
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
    """指定 card_id の overlay から when 一致の最初の効果の do リストを返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


# 定番 leader / helper カード
_NEUTRAL = "OP01-001"        # ゾロ (赤、 leader 条件が無い汎用)
_SHIRAHOSHI = "OP11-022"     # しらほし (緑/黄 / 人魚族/魚人島)
_VICTIM = "OP01-016"         # ナミ (cost1 / power2000) = KO 対象 (cost<=1/2/3/5 すべて満たす)
_SUPERNOVA = "EB04-005"      # トラファルガー・ロー (超新星 cost3) = OP11-101 の離脱対象
_KAIMII = "OP11-102"         # ケイミー (人魚族/魚人島) = OP11-109 条件 + OP11-104 サーチ対象
_FILLER = "OP01-013"         # サンジ (cost2 / power3000)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op11_wave116_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP11-101", "OP11-102", "OP11-103", "OP11-104", "OP11-107",
           "OP11-108", "OP11-109", "OP11-110", "OP11-112", "OP11-114"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP11-101 カポネ・ベッジ (CHARACTER 黄):
#    【ブロッカー】【ターン1回】自分の《超新星》(ベッジ以外) が相手の効果で場を
#      離れる場合、 代わりに自分のライフの上に加えることができる (replace_leave)。
# --------------------------------------------------------------------------- #
def test_op11_101_bege_replace_leave_supernova_to_life_ai():
    """AI: 相手効果で離脱する自《超新星》キャラを、 代わりに自ライフ上へ加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    bege = InPlay.of(repo.get("OP11-101"), sickness=False)     # holder
    victim = InPlay.of(repo.get(_SUPERNOVA), sickness=False)   # 超新星 (離脱対象)
    me.characters = [bege, victim]
    me.life = []

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "自《超新星》の相手効果離脱が置換されていない"
    assert victim not in me.characters, "置換時 離脱対象は場から取り除かれるべき"
    assert any(c.card_id == _SUPERNOVA for c in me.life), \
        "離脱対象が自ライフに加えられていない"


def test_op11_101_bege_replace_leave_excludes_self_by_battle():
    """バトルKO (by_opp_effect=False) は「相手の効果で」に該当しない → 置換しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    bege = InPlay.of(repo.get("OP11-101"), sickness=False)
    victim = InPlay.of(repo.get(_SUPERNOVA), sickness=False)
    me.characters = [bege, victim]
    me.life = []

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, "相手効果以外 (バトル等) の離脱を置換してはいけない"


def test_op11_101_bege_replace_leave_human_confirm():
    """人間 actor: replace_leave は 任意 → replace_ko_optional modal が立ち、 承諾すると
    離脱対象を自ライフへ加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    bege = InPlay.of(repo.get("OP11-101"), sickness=False)
    victim = InPlay.of(repo.get(_SUPERNOVA), sickness=False)
    me.characters = [bege, victim]
    me.life = []

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_leave の任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= 置換する)
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1
    assert victim not in me.characters, "人間承諾後 離脱対象は場から取り除かれるべき"
    assert any(c.card_id == _SUPERNOVA for c in me.life), \
        "人間承諾後 離脱対象が自ライフに加えられていない"


# --------------------------------------------------------------------------- #
#  OP11-102 ケイミー (CHARACTER 黄):
#    【自分のターン中】【ターン1回】相手がイベントか【トリガー】を発動した時、
#      相手ライフ2以上なら お互いのライフの上から1枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op11_102_kaimii_mill_both_lives_ai():
    """AI: お互いのライフ上 1 枚ずつをトラッシュに置く (自 -1 / 相手 -1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    opp.life = [repo.get(_FILLER)] * 3

    my_life_before = len(me.life)
    opp_life_before = len(opp.life)
    my_trash_before = len(me.trash)
    opp_trash_before = len(opp.trash)
    do, entry = _do(overlay, "OP11-102", "opp_event_or_trigger_fired")
    assert entry.get("if", {}).get("opp_life_ge") == 2, \
        "overlay の発動条件 opp_life_ge=2 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.life) == my_life_before - 1, "自ライフ 1 枚がトラッシュされていない"
    assert len(opp.life) == opp_life_before - 1, "相手ライフ 1 枚がトラッシュされていない"
    assert len(me.trash) == my_trash_before + 1, "自トラッシュに 1 枚追加されていない"
    assert len(opp.trash) == opp_trash_before + 1, "相手トラッシュに 1 枚追加されていない"


# --------------------------------------------------------------------------- #
#  OP11-103 シャクレ (CHARACTER 黄):
#    【起動メイン】自リーダーが「しらほし」なら このキャラをレストにし、 自ライフ上1枚を
#      裏向きにできる：相手のコスト3以下キャラ1枚までを KO。
# --------------------------------------------------------------------------- #
def test_op11_103_shakure_activate_main_ko_ai():
    """AI: しらほし leader → 自レスト + ライフ裏向き (コスト) → 相手コスト3以下を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    shakure = InPlay.of(repo.get("OP11-103"), sickness=False)
    me.characters = [shakure]
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 1
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=3)
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-103"]
    assert len(opts) == 1, f"OP11-103 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert shakure.rested is True, "起動メインコストで シャクレ がレストされていない"
    assert me.face_up_life_count == 0, "ライフ 1 枚が裏向きになっていない (コスト未払い)"
    assert victim not in opp.characters, "相手コスト3以下キャラが KO されていない"


def test_op11_103_shakure_no_activate_when_wrong_leader():
    """自リーダーが「しらほし」でなければ 起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # 非しらほし
    me, opp = st.players[0], st.players[1]
    shakure = InPlay.of(repo.get("OP11-103"), sickness=False)
    me.characters = [shakure]
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 1

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-103"]
    assert len(opts) == 0, "非しらほし leader で起動メインが legal に出てはいけない"


def test_op11_103_shakure_activate_main_human_optional_confirm():
    """人間: しらほし leader で 任意コストの optional_cost_confirm modal が立ち、
    承諾で 相手キャラを KO できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    shakure = InPlay.of(repo.get("OP11-103"), sickness=False)
    me.characters = [shakure]
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 1
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [victim]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-103"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert victim not in opp.characters, "承諾後 相手コスト3以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP11-104 シャーリー (CHARACTER 黄):
#    【ブロッカー】【登場時】自ライフ上1枚を裏向きにできる：デッキ上3枚を見て
#      特徴《魚人島》1枚までを公開し手札に加える。 残りを好きな順でデッキ上下へ。
# --------------------------------------------------------------------------- #
def test_op11_104_shirley_on_play_search_gyojinto_ai():
    """AI: ライフ裏向き (コスト) → デッキ上3枚から《魚人島》カードを手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_KAIMII)] + [repo.get(_FILLER)] * 10  # 上3枚に魚人島
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 1
    src = InPlay.of(repo.get("OP11-104"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)

    assert any(c.card_id == _KAIMII for c in me.hand), \
        "デッキ上3枚から《魚人島》カードが手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "手札が 1 枚増えていない"
    assert me.face_up_life_count == 0, "ライフ 1 枚が裏向きになっていない (コスト未払い)"


def test_op11_104_shirley_on_play_human_optional_confirm():
    """人間: 任意コストの optional_cost_confirm modal が立ち、 承諾で サーチ解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_KAIMII)] + [repo.get(_FILLER)] * 10
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 1
    src = InPlay.of(repo.get("OP11-104"), sickness=True)
    me.characters = [src]

    do, _ = _do(overlay, "OP11-104", "on_play")
    execute_effect(do[0], st, me, opp, src)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    hand_before = len(me.hand)
    resolve_pending_choice(st, [1])  # 承諾 → サーチ modal へ
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card_id == _KAIMII for c in me.hand), \
        "承諾後 《魚人島》カードが手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "承諾後 手札が 1 枚増えていない"


# --------------------------------------------------------------------------- #
#  OP11-107 チョンマゲ (CHARACTER 黄):
#    【ブロッカー】【起動メイン】【ターン1回】自リーダーが「しらほし」なら 自ライフ上1枚を
#      裏向きにできる：このターン終了時、 このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op11_107_chonmage_activate_main_schedule_untap_ai():
    """AI: しらほし leader → ライフ裏向き (コスト) → ターン終了時アクティブ化を予約。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    chon = InPlay.of(repo.get("OP11-107"), sickness=False)
    me.characters = [chon]
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 1

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-107"]
    assert len(opts) == 1, f"OP11-107 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.face_up_life_count == 0, "ライフ 1 枚が裏向きになっていない (コスト未払い)"
    scheduled = list(getattr(me, "scheduled_at_self_turn_end", None) or [])
    assert len(scheduled) >= 1, "ターン終了時アクティブ化が予約されていない"


def test_op11_107_chonmage_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    chon = InPlay.of(repo.get("OP11-107"), sickness=False)
    me.characters = [chon]
    me.life = [repo.get(_FILLER)] * 3
    me.face_up_life_count = 2

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-107"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP11-107"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP11-108 ネプチューン (CHARACTER 黄):
#    【登場時】自リーダーが「しらほし」なら 自ライフ上1枚を裏向きにできる：
#      カード2枚を引き、 自手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op11_108_neptune_on_play_draw2_discard1_ai():
    """AI: しらほし leader → ライフ裏向き (コスト) → 2 ドロー + 手札 1 枚捨て。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_VICTIM)]
    me.deck = [repo.get(_FILLER)] * 6
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 1
    src = InPlay.of(repo.get("OP11-108"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, src, overlay)

    # 手札: +2 (draw) -1 (discard) = +1
    assert len(me.hand) == hand_before + 1, \
        f"手札 net (+2 draw -1 discard) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが 2 枚減っていない (2 ドロー)"
    assert me.face_up_life_count == 0, "ライフ 1 枚が裏向きになっていない (コスト未払い)"


def test_op11_108_neptune_on_play_no_effect_when_wrong_leader():
    """自リーダーが「しらほし」でなければ 効果が発火しない (= 条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # 非しらほし
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_VICTIM)]
    me.deck = [repo.get(_FILLER)] * 6
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 1
    src = InPlay.of(repo.get("OP11-108"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)
    assert len(me.hand) == hand_before, "条件不成立 (リーダー違い) なのにドローした"


def test_op11_108_neptune_on_play_human_optional_confirm():
    """人間: しらほし leader で 任意コストの optional_cost_confirm modal が立ち、
    承諾すると 最終的に手札が +1 になる (2 ドロー - 1 捨て)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_VICTIM)]
    me.deck = [repo.get(_FILLER)] * 6
    me.life = [repo.get(_FILLER)] * 2
    me.face_up_life_count = 1
    src = InPlay.of(repo.get("OP11-108"), sickness=True)
    me.characters = [src]

    do, _ = _do(overlay, "OP11-108", "on_play")
    execute_effect(do[0], st, me, opp, src)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    hand_before = len(me.hand)
    resolve_pending_choice(st, [1])  # 承諾
    guard = 0
    while st.pending_choice is not None and guard < 6:
        pc = st.pending_choice
        if "discard" in pc.get("kind", ""):
            resolve_pending_choice(st, [0])  # 捨てる 1 枚を選択
        else:
            resolve_pending_choice(st, [1])
        guard += 1
    assert len(me.hand) == hand_before + 1, \
        f"承諾後 手札 net (+2 draw -1 discard) が合わない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP11-109 パッパグ (CHARACTER 黄):
#    【登場時】自分の「ケイミー」がいる場合、 カード2枚を引き、 自手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op11_109_pappag_on_play_draw2_discard2_when_kaimii_ai():
    """AI: 場に「ケイミー」あり → 2 ドロー + 手札 2 枚捨て (手札 net ±0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    kaimii = InPlay.of(repo.get(_KAIMII), sickness=False)
    me.characters = [kaimii]
    me.hand = [repo.get(_FILLER), repo.get(_VICTIM)]
    me.deck = [repo.get(_FILLER)] * 6
    src = InPlay.of(repo.get("OP11-109"), sickness=True)
    me.characters.append(src)

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    trigger_on_play(st, me, opp, src, overlay)

    # 手札: +2 (draw) -2 (discard) = ±0
    assert len(me.hand) == hand_before, \
        f"手札 net (+2 draw -2 discard) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが 2 枚減っていない (2 ドロー)"
    assert len(me.trash) == trash_before + 2, "トラッシュに 2 枚追加されていない"


def test_op11_109_pappag_on_play_no_effect_without_kaimii():
    """場に「ケイミー」がいなければ 効果が発火しない (= 条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_VICTIM)]
    me.deck = [repo.get(_FILLER)] * 6
    src = InPlay.of(repo.get("OP11-109"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)
    assert len(me.hand) == hand_before, "ケイミー不在なのにドロー/捨てが起きた"


def test_op11_109_pappag_on_play_human_discard_pick():
    """人間: 手札が 2 枚超 → 捨てる 2 枚を選ぶ self_hand_discard_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_VICTIM), repo.get(_KAIMII)]
    src = InPlay.of(repo.get("OP11-109"), sickness=True)
    me.characters = [src]

    # do[1] = trash_self_hand_random 2 (捨て) を直接発火 → 人間 modal
    do, _ = _do(overlay, "OP11-109", "on_play")
    execute_effect(do[1], st, me, opp, src)

    assert st.pending_choice is not None, "人間の手札捨て modal が立たない"
    assert st.pending_choice.get("kind") == "self_hand_discard_pick", \
        f"kind が self_hand_discard_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("limit") == 2, "捨てる枚数 limit が 2 でない"

    hand_before = len(me.hand)
    resolve_pending_choice(st, [0, 1])  # 手札 0,1 を捨てる
    assert st.pending_choice is None, "解決後も modal が残る"
    assert len(me.hand) == hand_before - 2, "人間が選んだ 2 枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  OP11-110 フカボシ (CHARACTER 黄):
#    (1) このキャラが KO される場合、 代わりに自分の「魚人島」かリーダー「しらほし」
#        1枚をレストにできる (replace_ko)。
#    (2) 【登場時】自ライフ上か下1枚を手札に加えることができる：相手のコスト1以下
#        キャラ1枚までを KO。
# --------------------------------------------------------------------------- #
def test_op11_110_fukaboshi_replace_ko_by_resting_leader_ai():
    """AI: フカボシが KO される → 代わりにリーダー (しらほし) をレストにして耐える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    fuka = InPlay.of(repo.get("OP11-110"), sickness=False)
    me.characters = [fuka]

    replaced = try_replace_ko(
        st, me, opp, fuka, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "リーダーをレストにできるのに KO が置換されていない"
    assert fuka in me.characters, "置換成立時 フカボシは場に残るべき"
    assert me.leader.rested is True, "置換コストでリーダーがレストされていない"


def test_op11_110_fukaboshi_replace_ko_no_active_leader():
    """レストにできるリーダー/ステージが無ければ (既にレスト) 置換できない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.rested = True  # 既にレスト = コスト不能
    fuka = InPlay.of(repo.get("OP11-110"), sickness=False)
    me.characters = [fuka]

    replaced = try_replace_ko(
        st, me, opp, fuka, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is False, "レスト可能な対象が無いのに置換が成立してはいけない"


def test_op11_110_fukaboshi_on_play_life_to_hand_then_ko_ai():
    """AI: ライフ1枚を手札 (コスト) → 相手コスト1以下キャラ1枚を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    src = InPlay.of(repo.get("OP11-110"), sickness=True)
    me.characters = [src]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=1)
    opp.characters = [victim]

    hand_before = len(me.hand)
    life_before = len(me.life)
    trigger_on_play(st, me, opp, src, overlay)

    assert len(me.life) == life_before - 1, "ライフ 1 枚が手札に移っていない (コスト未払い)"
    assert len(me.hand) == hand_before + 1, "手札が 1 枚増えていない"
    assert victim not in opp.characters, "相手コスト1以下キャラが KO されていない"


def test_op11_110_fukaboshi_on_play_human_optional_confirm():
    """人間: 登場時 任意コストの optional_cost_confirm modal が立ち、 承諾で KO まで解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    src = InPlay.of(repo.get("OP11-110"), sickness=True)
    me.characters = [src]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP11-110", "on_play")
    execute_effect(do[0], st, me, opp, src)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert victim not in opp.characters, "承諾後 相手コスト1以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP11-112 メガロ (CHARACTER 黄):
#    【ブロッカー】【相手のターン中】自リーダーが「しらほし」なら このキャラの
#      パワー+4000 (静的)。
# --------------------------------------------------------------------------- #
def test_op11_112_megalo_static_pump_on_opp_turn():
    """相手ターン中 + しらほし leader → メガロ +4000 (静的)。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(_SHIRAHOSHI), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(_NEUTRAL), sickness=False))
    megalo_def = repo.get("OP11-112")  # power 2000
    megalo = InPlay.of(megalo_def, sickness=False)
    p0.characters = [megalo]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    st.human_player_idx = None

    evaluate_static_effects(st, overlay)
    assert megalo.power == megalo_def.power + 4000, \
        f"相手ターン + しらほし で +4000 が乗っていない: {megalo.power} (base {megalo_def.power})"


def test_op11_112_megalo_no_pump_on_self_turn():
    """自ターン中は【相手のターン中】条件が不成立 → 効果 +0。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(_SHIRAHOSHI), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(_NEUTRAL), sickness=False))
    megalo_def = repo.get("OP11-112")
    megalo = InPlay.of(megalo_def, sickness=False)
    p0.characters = [megalo]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0  # 自ターン → opp_turn False
    st.human_player_idx = None

    evaluate_static_effects(st, overlay)
    assert megalo.power == megalo_def.power, \
        f"自ターンで効果 pump が乗ってはいけない: {megalo.power} (base {megalo_def.power})"


def test_op11_112_megalo_no_pump_when_wrong_leader():
    """相手ターンでも 自リーダーが「しらほし」でなければ 効果 +0。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get(_NEUTRAL), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(_NEUTRAL), sickness=False))
    megalo_def = repo.get("OP11-112")
    megalo = InPlay.of(megalo_def, sickness=False)
    p0.characters = [megalo]
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 1  # 相手ターン
    st.human_player_idx = None

    evaluate_static_effects(st, overlay)
    assert megalo.power == megalo_def.power, \
        f"非しらほし leader で pump が乗ってはいけない: {megalo.power}"


# --------------------------------------------------------------------------- #
#  OP11-114 ゴムゴムの火拳銃 (EVENT 黄):
#    【メイン】自ドン3枚レスト：お互いのライフ合計5枚以上なら 相手の元々コスト5以下
#      キャラ1枚までを KO。
#    【カウンター】自リーダー1枚までを このバトル中 パワー+3000。
# --------------------------------------------------------------------------- #
def test_op11_114_main_ko_when_total_life_ge5_ai():
    """AI: お互いライフ合計5枚以上 → 相手コスト5以下キャラ1体を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    opp.life = [repo.get(_FILLER)] * 3  # 合計 6 (>=5)
    me.don_active = 5
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=5)
    opp.characters = [victim]

    do, entry = _do(overlay, "OP11-114", "main")
    assert entry.get("cost", {}).get("rest_self_don") == 3, \
        "overlay の main コスト rest_self_don=3 が無い"
    assert entry.get("if", {}).get("total_life_ge") == 5, \
        "overlay の main 条件 total_life_ge=5 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手コスト5以下キャラが KO されていない"
    assert victim.card in opp.trash, "KO したキャラがトラッシュに置かれていない"


def test_op11_114_main_human_ko_target_pick():
    """人間: 相手キャラが複数 → KO 対象の target_pick modal が立ち、 選んで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    opp.life = [repo.get(_FILLER)] * 3
    v1 = InPlay.of(repo.get(_VICTIM), sickness=False)      # cost1
    v2 = InPlay.of(repo.get(_FILLER), sickness=False)      # cost2 (<=5)
    opp.characters = [v1, v2]

    do, _ = _do(overlay, "OP11-114", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で KO の target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"KO 候補が 2 件でない: {len(cands)}"

    pick_idx = next(i for i, c in enumerate(cands) if c["iid"] == v2.instance_id)
    resolve_pending_choice(st, [pick_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert v2 not in opp.characters, "人間が選んだキャラが KO されていない"
    assert v1 in opp.characters, "選ばなかったキャラまで KO された"


def test_op11_114_counter_leader_pump_ai():
    """【カウンター】自リーダーを このバトル中 パワー+3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP11-114", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"カウンターで自リーダー +3000 が反映されていない: {me.leader.power}"
