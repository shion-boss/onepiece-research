# -*- coding: utf-8 -*-
"""EB03/EB04 弾 効果 回帰テスト バックフィル (自動生成 wave 014):
EB03-054 / EB03-055 / EB03-056 / EB03-057 / EB03-058 / EB03-059 /
EB03-060 / EB03-061 / EB04-003 / EB04-004 の 10 枚。

目的 (= test_backfill_auto_001〜013.py と同一方針):
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


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いカード (ST01-004 サンジ cost2) で埋める。"""
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
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _am(st, me, overlay, cid):
    """指定 card_id の legal な起動メイン (src, eff) を返す (無ければ空 list)。"""
    return [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == cid]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave14_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB03-054", "EB03-055", "EB03-056", "EB03-057", "EB03-058",
           "EB03-059", "EB03-060", "EB03-061", "EB04-003", "EB04-004"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB03-054 ニコ・ロビン (CHARACTER 黄 cost3):
#    【登場時】自ライフ上1枚をトラッシュに置ける (任意コスト) → デッキ上1枚までをライフの上へ
# --------------------------------------------------------------------------- #
def test_eb03_054_robin_on_play_life_swap_ai():
    """登場時: 自ライフ1枚 trash (コスト) → デッキ上1枚をライフへ (AI 自動)。
    ライフ枚数は ±0 (=1 trash + 1 add)、 トラッシュ +1、 デッキ -1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    me.deck = [repo.get("ST01-004")] * 10

    life_before = len(me.life)
    trash_before = len(me.trash)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "EB03-054", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-054"), sickness=True))

    assert len(me.trash) == trash_before + 1, "ライフ1枚がトラッシュに置かれていない"
    assert len(me.deck) == deck_before - 1, "デッキ上1枚がライフへ移っていない"
    assert len(me.life) == life_before, \
        f"ライフ枚数が ±0 でない: {len(me.life)} (before {life_before})"


def test_eb03_054_robin_on_play_human_optional_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で 効果まで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    me.deck = [repo.get("ST01-004")] * 10

    trash_before = len(me.trash)
    do, _ = _do(overlay, "EB03-054", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-054"), sickness=True))
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st)
    assert len(me.trash) == trash_before + 1, "人間承諾後 ライフ1枚がトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  EB03-055 ニコ・ロビン (CHARACTER 黄 cost7):
#    【登場時】自ライフ上1枚 trash → リーダー麦わらの一味 なら デッキ上2枚までをライフへ /
#    【相手のターン中】【KO時】相手に1ダメージ
# --------------------------------------------------------------------------- #
def test_eb03_055_robin_on_play_conditional_life_add_ai():
    """登場時: 自ライフ1枚 trash (コスト) → リーダー麦わら なら デッキ上2枚をライフへ (AI)。
    ライフ net +1 (=1 trash + 2 add)、 デッキ -2、 トラッシュ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB01-001", overlay)  # サンジ (麦わらの一味 leader)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    me.deck = [repo.get("ST01-004")] * 10

    life_before = len(me.life)
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "EB03-055", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-055"), sickness=True))

    assert len(me.trash) == trash_before + 1, "コストで自ライフ1枚がトラッシュに置かれていない"
    assert len(me.deck) == deck_before - 2, "麦わらリーダーでデッキ上2枚がライフへ移っていない"
    assert len(me.life) == life_before + 1, \
        f"ライフ net が +1 でない: {len(me.life)} (before {life_before})"


def test_eb03_055_robin_on_ko_opp_turn_damage_ai():
    """【相手のターン中】【KO時】相手に1ダメージ (= 標準ダメージ: ライフ上1枚を相手の手札へ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB01-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    opp.life = [repo.get("OP01-013")] * 2

    opp_life_before = len(opp.life)
    opp_hand_before = len(opp.hand)
    eff = next(e for e in overlay.get("EB03-055").effects if e.get("when") == "on_ko")
    assert eval_condition({"opp_turn": True}, st, me) is True, \
        "相手ターン中の on_ko 条件 (opp_turn) が成立していない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-055"), sickness=False))

    assert len(opp.life) == opp_life_before - 1, "相手ライフが 1 減っていない (ダメージ未処理)"
    assert len(opp.hand) == opp_hand_before + 1, "ダメージ分のライフが相手の手札に加わっていない"


def test_eb03_055_robin_on_ko_kills_at_zero_life():
    """相手ライフ0で7ロビンが自KOされると【1ダメージで敗北】(pros02: 即ゲームエンド)。
    旧 bug: deal_opp_leader_damage が 0ライフで no-op = 詰められなかった。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "PRB01-001", overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手 (opp) のターン → opp_turn 成立
    opp.life = []           # ★ ダメージを受ける側 (opp) のライフ 0

    eff = next(e for e in overlay.get("EB03-055").effects if e.get("when") == "on_ko")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-055"), sickness=False))

    assert st.game_over is True, "ライフ0への効果ダメージが敗北を起こしていない"
    assert st.winner == st.players.index(me), "ダメージ源側 (me) が勝者になっていない"


# --------------------------------------------------------------------------- #
#  EB03-056 ベロ・ベティ (CHARACTER 黄 cost4):
#    【登場時】自ライフ上1枚を表向きにできる (任意コスト) → 相手の元々コスト3以下キャラ1枚 KO
# --------------------------------------------------------------------------- #
def test_eb03_056_bellobetty_on_play_ko_cost3_ai():
    """登場時: 自ライフ1枚を表向き (コスト) → 相手元々コスト3以下1枚 KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    me.face_up_life_count = 0
    victim = InPlay.of(repo.get("EB02-029"), sickness=False)  # cost3
    opp.characters = [victim]

    do, _ = _do(overlay, "EB03-056", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-056"), sickness=False))

    assert victim not in opp.characters, "相手の元々コスト3以下キャラが KO されていない"
    assert me.face_up_life_count == 1, "コストで自ライフ上1枚が表向きになっていない"


def test_eb03_056_bellobetty_on_play_human_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で KO まで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    me.face_up_life_count = 0
    victim = InPlay.of(repo.get("EB02-029"), sickness=False)  # cost3
    opp.characters = [victim]

    do, _ = _do(overlay, "EB03-056", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-056"), sickness=False))
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st, pick=[0])
    assert victim not in opp.characters, "人間承諾後 相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  EB03-057 ヤマト (CHARACTER 黄 cost5):
#    【登場時】自リーダー(ワノ国)にレストのドン3枚までを付与 /
#    【KO時】相手ライフ上1枚までをトラッシュへ
# --------------------------------------------------------------------------- #
def test_eb03_057_yamato_on_play_attach_rested_don_ai():
    """登場時: 自ワノ国リーダーにレストのドン3枚を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)  # 光月おでん (ワノ国 leader)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    do, _ = _do(overlay, "EB03-057", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-057"), sickness=True))

    assert me.leader.attached_dons == don_before + 3, \
        "登場時に自リーダーへレストのドン3枚が付与されていない"
    assert me.don_rested == rested_before - 3, "レストのドンが3枚消費されるべき"


def test_eb03_057_yamato_on_ko_mill_opp_life_ai():
    """【KO時】相手ライフ上1枚をトラッシュへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-013")] * 2

    opp_life_before = len(opp.life)
    opp_trash_before = len(opp.trash)
    do, _ = _do(overlay, "EB03-057", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-057"), sickness=False))

    assert len(opp.life) == opp_life_before - 1, "相手ライフ上1枚がトラッシュへ移っていない"
    assert len(opp.trash) == opp_trash_before + 1, "相手トラッシュが +1 されていない"


# --------------------------------------------------------------------------- #
#  EB03-058 リリス (CHARACTER 黄 cost5):
#    【自分のターン中】【登場時】自ライフが2枚以下なら カード1枚を引く
# --------------------------------------------------------------------------- #
def test_eb03_058_lilith_on_play_draw_when_life_le2_ai():
    """登場時 (自ターン中 + 自ライフ2枚以下): カード1枚を引く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2  # ライフ 2 (= 条件成立)
    me.deck = [repo.get("ST01-004")] * 10
    me.hand = []

    assert eval_condition({"self_life_le": 2}, st, me) is True, \
        "ライフ2枚で self_life_le=2 が成立していない"
    hand_before = len(me.hand)
    do, _ = _do(overlay, "EB03-058", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-058"), sickness=True))

    assert len(me.hand) == hand_before + 1, "登場時のドローが起きていない"


def test_eb03_058_lilith_condition_false_when_life_ge3():
    """自ライフ3枚では self_life_le=2 が不成立 (= 条件で発動しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.life = [repo.get("OP01-013")] * 3
    assert eval_condition({"self_life_le": 2}, st, me) is False, \
        "ライフ3枚で self_life_le=2 が成立してはいけない"


# --------------------------------------------------------------------------- #
#  EB03-059 S-スネーク (CHARACTER 黄 cost6):
#    【登場時】リーダー(エッグヘッド) かつ 自ライフ2枚以上なら 手札の【トリガー】持ちキャラ
#    1枚までを ライフの上に表向きで加える
# --------------------------------------------------------------------------- #
def test_eb03_059_ssnake_on_play_hand_to_life_ai():
    """登場時: 手札の【トリガー】持ちキャラ1枚をライフへ (AI 自動)。 手札 -1 / ライフ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB04-001", overlay)  # ジュエリー・ボニー (エッグヘッド leader)
    me, opp = st.players[0], st.players[1]
    trig_chara = repo.get("PRB02-012")  # ナミ (【トリガー】持ち CHARACTER)
    assert (trig_chara.trigger or ""), "テスト前提: PRB02-012 は【トリガー】を持つ"
    me.hand = [trig_chara]
    me.life = [repo.get("OP01-013")] * 2

    hand_before = len(me.hand)
    life_before = len(me.life)
    do, _ = _do(overlay, "EB03-059", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-059"), sickness=True))

    assert len(me.hand) == hand_before - 1, "手札の【トリガー】持ちキャラがライフへ移っていない"
    assert len(me.life) == life_before + 1, "ライフ上に1枚が加えられていない"


def test_eb03_059_ssnake_on_play_human_pick():
    """人間 + 手札に【トリガー】持ちキャラ 複数 → hand_to_life_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("PRB02-012"), repo.get("PRB02-016")]  # ナミ / お玉 (両方トリガー持ち)
    me.life = [repo.get("OP01-013")] * 2

    do, _ = _do(overlay, "EB03-059", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-059"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で hand_to_life_pick modal が立たない"
    assert st.pending_choice.get("kind") == "hand_to_life_pick", \
        f"kind が hand_to_life_pick でない: {st.pending_choice.get('kind')}"
    life_before = len(me.life)
    resolve_pending_choice(st, [0])  # 先頭候補を選択
    _drain(st, pick=[0])
    assert len(me.life) == life_before + 1, "人間が選んだキャラがライフへ加えられていない"


# --------------------------------------------------------------------------- #
#  EB03-060 私のしもべになる？ (EVENT 黄 cost1):
#    【メイン】リーダー「ナミ」なら デッキ上4枚を見て コスト2〜8 のカード1枚までを手札へ、
#    残りをデッキ下へ
# --------------------------------------------------------------------------- #
def test_eb03_060_shimobe_main_search_ai():
    """メイン: デッキ上4枚からコスト2〜8のカード1枚を手札へ (AI 自動)。 手札 +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-040", overlay)  # ナミ leader
    me, opp = st.players[0], st.players[1]
    # デッキ上4枚に コスト2〜8 の該当カード (ST01-004 サンジ cost2) を仕込む
    me.deck = [repo.get("ST01-004")] * 4 + [repo.get("OP01-013")] * 10
    me.hand = []

    hand_before = len(me.hand)
    do, _ = _do(overlay, "EB03-060", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, \
        "デッキ上4枚から コスト2〜8 のカードが手札に加わっていない"
    assert me.hand[0].card_id == "ST01-004", "手札に加わったのが該当カードでない"


def test_eb03_060_shimobe_main_human_pick():
    """人間: デッキ上4枚に該当カードあり → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-040", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 4 + [repo.get("OP01-013")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB03-060", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (該当カード) を選択
    _drain(st)
    assert any(c.card_id == "ST01-004" for c in me.hand), \
        "人間が選んだ該当カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB03-061 ウタ (CHARACTER 緑 cost7):
#    【起動メイン】【ターン1回】自ドン1枚をアクティブに → 相手のコスト4以下のキャラかドン1枚をレスト /
#    【自分のターン終了時】自ドン1枚レスト → 自分の特徴《FILM》キャラ1枚をアクティブに
# --------------------------------------------------------------------------- #
def test_eb03_061_uta_activate_main_untap_and_rest_ai():
    """起動メイン: 自ドン1アクティブ → 相手コスト4以下キャラ1枚をレスト (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    uta = InPlay.of(repo.get("EB03-061"), sickness=False)
    me.characters = [uta]
    me.don_rested = 1  # untap 対象
    me.don_active = 0
    victim = InPlay.of(repo.get("EB02-029"), sickness=False)  # cost3, アクティブ
    victim.rested = False
    opp.characters = [victim]

    opts = _am(st, me, overlay, "EB03-061")
    assert len(opts) == 1, f"EB03-061 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.don_active == 1 and me.don_rested == 0, "自ドン1枚がアクティブになっていない"
    assert victim.rested is True, "相手コスト4以下キャラがレストされていない"


def test_eb03_061_uta_activate_main_human_rest_pick():
    """人間 + 相手アクティブキャラ複数 → rest の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    uta = InPlay.of(repo.get("EB03-061"), sickness=False)
    me.characters = [uta]
    me.don_rested = 1
    a = InPlay.of(repo.get("EB02-029"), sickness=False)  # cost3
    b = InPlay.of(repo.get("EB04-002"), sickness=False)  # cost1
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    opts = _am(st, me, overlay, "EB03-061")
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかった相手キャラは残るべき"


def test_eb03_061_uta_end_of_turn_untap_film_ai():
    """【自分のターン終了時】自ドン1レスト (コスト) → 自 FILM キャラ1枚をアクティブに (AI)。
    盤面の FILM キャラはすべてレスト済 → 効果後にちょうど1枚がアクティブになる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    uta = InPlay.of(repo.get("EB03-061"), sickness=False)  # ウタ (FILM)
    film_chara = InPlay.of(repo.get("EB03-003"), sickness=False)  # ウタ (FILM)
    assert "FILM" in (uta.card.features or ""), "テスト前提: EB03-061 は FILM"
    assert "FILM" in (film_chara.card.features or ""), "テスト前提: EB03-003 は FILM"
    uta.rested = True
    film_chara.rested = True
    me.characters = [uta, film_chara]
    me.don_active = 1
    me.don_rested = 0

    rested_before = sum(1 for c in me.characters
                        if "FILM" in (c.card.features or "") and c.rested)
    assert rested_before == 2, "テスト前提: レスト済 FILM キャラが2枚"
    do, _ = _do(overlay, "EB03-061", "end_of_turn")
    for prim in do:
        execute_effect(prim, st, me, opp, uta)

    rested_after = sum(1 for c in me.characters
                       if "FILM" in (c.card.features or "") and c.rested)
    assert rested_after == rested_before - 1, \
        f"FILM キャラがちょうど1枚アクティブになっていない: rested {rested_after} (before {rested_before})"
    assert me.don_active == 0 and me.don_rested == 1, "コストで自ドン1枚がレストされるべき"


# --------------------------------------------------------------------------- #
#  EB04-003 スモーカー＆たしぎ (CHARACTER 赤 cost8):
#    【速攻】【相手のターン中】自分の特徴《海軍》を持つリーダーを 元々のパワー7000にする (常在)
# --------------------------------------------------------------------------- #
def test_eb04_003_smoker_tashigi_static_leader_power_opp_turn():
    """相手ターン中: 自海軍リーダーの元々パワーが 7000 になる (常在)。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP05-041"), sickness=False))  # サカズキ 海軍
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 成立)
    st.human_player_idx = None
    p0.characters = [InPlay.of(repo.get("EB04-003"), sickness=False)]

    assert p0.leader.card.power != 7000, "テスト前提: サカズキ の 印刷パワーは 7000 でない"
    evaluate_static_effects(st, overlay)
    assert p0.leader.power == 7000, \
        f"相手ターン中に海軍リーダーの元々パワーが 7000 になっていない: {p0.leader.power}"


def test_eb04_003_smoker_tashigi_static_no_effect_own_turn():
    """自分のターン中は【相手のターン中】条件が不成立 → 元々パワーは変わらない。"""
    repo = _repo()
    overlay = _overlay()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP05-041"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    st = GameState(players=[p0, p1], phase=Phase.MAIN, effects_overlay=overlay)
    st.turn_player_idx = 0  # 自分のターン → opp_turn False
    st.human_player_idx = None
    p0.characters = [InPlay.of(repo.get("EB04-003"), sickness=False)]

    base = p0.leader.card.power
    evaluate_static_effects(st, overlay)
    assert p0.leader.power == base, \
        f"自ターン中に元々パワーが変わってはいけない: {p0.leader.power} (base {base})"


# --------------------------------------------------------------------------- #
#  EB04-004 ゼフ (CHARACTER 赤 cost7):
#    【アタック時】自リーダーを 次の相手のエンドフェイズ終了時まで 元々のパワー7000にする
# --------------------------------------------------------------------------- #
def test_eb04_004_zeff_on_attack_set_leader_power_ai():
    """【アタック時】自リーダーの元々パワーを (期限付きで) 7000 にする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    assert me.leader.card.power != 7000, "テスト前提: リーダー の 印刷パワーは 7000 でない"
    do, _ = _do(overlay, "EB04-004", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-004"), sickness=False))

    assert me.leader.next_opp_turn_end_base_power_override == 7000, \
        "自リーダーへ期限付き 元々パワー7000 が設定されていない"
    assert me.leader.power == 7000, \
        f"自リーダーの現在パワーが 7000 になっていない: {me.leader.power}"
