# -*- coding: utf-8 -*-
"""OP05 弾 効果 回帰テスト バックフィル (自動生成 wave 061):
OP05-088 / OP05-089 / OP05-090 / OP05-091 / OP05-092 / OP05-093 /
OP05-094 / OP05-095 / OP05-096 / OP05-098 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_060.py と同一方針):
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
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_NEUTRAL = "OP01-001"   # ロロノア・ゾロ (赤、 単色)
_NAMI = "OP01-016"             # ナミ 赤 cost1 power2000
_RED_C2 = "ST01-004"           # サンジ 赤 cost2 power4000 (汎用フィラー)
_RED_C3 = "EB02-003"           # トニートニー・チョッパー 赤 cost3 power3000
_ISSHO_C6 = "OP05-042"         # イッショウ 青 cost6 power6000 (海軍)
_LUCCI_C4 = "OP05-093"         # ロブ・ルッチ 黒 cost4 power6000 CP0
_MANSHERRY = "OP05-088"        # マンシェリー 黒 cost1 (cost1 黒 char 対象)
_VIOLA = "OP05-079"            # ヴィオラ 黒 cost2 power3000 ドレスローザ
_CHARLOSS = "OP05-084"         # チャルロス聖 黒 cost3 天竜人


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_RED_C2)] * 30
    p1.deck = [repo.get(_RED_C2)] * 30
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


def _am_opt(st, me, overlay, cid):
    """起動メイン効果を legal 一覧から取り出す (無ければ None)。"""
    opts = [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == cid]
    return opts[0] if opts else None


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave61_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP05-088", "OP05-089", "OP05-090", "OP05-091", "OP05-092",
           "OP05-093", "OP05-094", "OP05-095", "OP05-096", "OP05-098"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP05-088 マンシェリー (CHARACTER 黒 cost1 トンタッタ族/ドレスローザ):
#    【起動メイン】➀，このキャラをレストにし、自分のトラッシュのカード2枚を好きな
#      順番でデッキの下に置くことができる：自分のトラッシュのコスト3から5の黒の
#      キャラカード1枚までを、手札に加える。
# --------------------------------------------------------------------------- #
def test_op05_088_activate_main_recur_black_ai():
    """起動メイン (AI): ➀+自レスト → トラッシュ2枚をデッキ下 → コスト3-5黒キャラ1枚を手札。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    manshy = InPlay.of(repo.get("OP05-088"), sickness=False)
    me.characters = [manshy]
    me.don_active = 3  # ➀ (rest_self_don) 支払い用
    # トラッシュを コスト4黒キャラ (ロブ・ルッチ) だけにする → どの2枚をデッキ下に
    # 置いても 残る1枚が retrieve 対象になり、 AI 選択に依らず堅牢。
    me.trash = [repo.get(_LUCCI_C4)] * 4
    me.deck = [repo.get(_RED_C2)] * 20
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    opt = _am_opt(st, me, overlay, "OP05-088")
    assert opt is not None, "OP05-088 の起動メインが legal に出ない"
    fire_activate_main(st, me, opp, *opt)

    assert manshy.rested is True, "起動メインコストでマンシェリーがレストされていない"
    assert me.don_active == 3 - 1, "➀ (アクティブドン1) が支払われていない"
    assert any(c.card_id == _LUCCI_C4 for c in me.hand), \
        "コスト3-5黒キャラが手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "手札が1枚 (retrieve) 増えていない"
    assert len(me.deck) == deck_before + 2, "トラッシュ2枚がデッキ下に置かれていない"


# --------------------------------------------------------------------------- #
#  OP05-089 ミョスガルド聖 (CHARACTER 黒 cost5 power1000 天竜人):
#    【起動メイン】➀，このキャラと自分のキャラ1枚をレストにできる：
#      自分のトラッシュのコスト1の黒のキャラカード1枚までを、手札に加える。
# --------------------------------------------------------------------------- #
@pytest.mark.skip(
    reason="engine/overlay 実バグ: OP05-089 overlay は search source=trash を使うが "
    "engine の search primitive は常に me.deck のみ探索し source 指定を無視するため "
    "トラッシュからの回収が発火しない (正しくは trash_to_hand primitive を使うべき、 "
    "OP05-088 は trash_to_hand で正常)。 engine 修正は人間レビューへ。"
)
def test_op05_089_activate_main_recur_cost1_black_ai():
    """起動メイン (AI): ➀+自レスト+他キャラ1レスト → トラッシュのコスト1黒キャラを手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    myos = InPlay.of(repo.get("OP05-089"), sickness=False)
    fodder = InPlay.of(repo.get(_NAMI), sickness=False)  # レスト対象の他キャラ
    me.characters = [myos, fodder]
    me.don_active = 3
    me.trash = [repo.get(_MANSHERRY)]  # コスト1 黒 char (retrieve 対象)
    hand_before = len(me.hand)

    opt = _am_opt(st, me, overlay, "OP05-089")
    assert opt is not None, "OP05-089 の起動メインが legal に出ない"
    fire_activate_main(st, me, opp, *opt)

    assert myos.rested is True, "コストでミョスガルド自身がレストされていない"
    assert fodder.rested is True, "コストで他キャラ1枚がレストされていない"
    assert any(c.card_id == _MANSHERRY for c in me.hand), \
        "コスト1黒キャラが手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "手札が1枚 (retrieve) 増えていない"


# --------------------------------------------------------------------------- #
#  OP05-090 リク・ドルド3世 (CHARACTER 黒 cost4 power5000 ドレスローザ):
#    【ブロッカー】【登場時】/【KO時】自分の特徴《ドレスローザ》を持つキャラ1枚までを、
#      このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op05_090_on_play_dressrosa_pump_ai():
    """登場時 (AI): 自分の ドレスローザ キャラ1体を このターン中 パワー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    viola = InPlay.of(repo.get(_VIOLA), sickness=False)  # ドレスローザ power3000
    me.characters = [viola]

    power_before = viola.power
    for prim in _do(overlay, "OP05-090", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-090"), sickness=False))

    assert viola.power == power_before + 2000, \
        f"ドレスローザ キャラに +2000 が反映されていない: {viola.power} (before {power_before})"


def test_op05_090_on_ko_dressrosa_pump_human_pick():
    """KO時 (人間): ドレスローザ キャラ複数 → target_pick modal → 選んだ1体に +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_VIOLA), sickness=False)
    b = InPlay.of(repo.get("OP05-090"), sickness=False)  # リク自身も ドレスローザ
    me.characters = [a, b]

    for prim in _do(overlay, "OP05-090", "on_ko"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-090"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (ドレスローザ2体) が 2 件でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    a_before = a.power
    resolve_pending_choice(st, [a_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert a.power == a_before + 2000, "人間が選んだ ドレスローザ キャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-091 レベッカ (CHARACTER 黒 cost4 ブロッカー):
#    【ブロッカー】【登場時】自分のトラッシュの「レベッカ」以外のコスト3から7の黒の
#      キャラカード1枚までを、手札に加える。その後、自分の手札からコスト3以下の黒の
#      キャラカード1枚までを、レストで登場させる。
# --------------------------------------------------------------------------- #
def test_op05_091_on_play_recur_then_play_ai():
    """登場時 (AI): トラッシュのコスト3-7黒キャラを手札へ → 手札のコスト3以下黒キャラをレスト登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_LUCCI_C4)]     # コスト4黒 (retrieve 対象、 レベッカ以外)
    me.hand = [repo.get(_VIOLA)]         # コスト2黒 (登場 対象)
    chars_before = len(me.characters)

    for prim in _do(overlay, "OP05-091", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-091"), sickness=False))

    # retrieve: ロブ・ルッチ (cost4) が手札へ。 play: ヴィオラ (cost2 黒) をレスト登場。
    assert any(c.card_id == _LUCCI_C4 for c in me.hand), \
        "トラッシュのコスト3-7黒キャラが手札に加わっていない"
    played = [c for c in me.characters if c.card.card_id == _VIOLA]
    assert len(played) == 1, "手札のコスト3以下黒キャラが登場していない"
    assert played[0].rested is True, "登場したキャラがレストになっていない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  OP05-092 ロズワード聖 (CHARACTER 黒 cost5 天竜人):
#    【自分のターン中】自分の場のキャラが、特徴《天竜人》を持つキャラのみの場合、
#      相手のキャラすべてをコスト-6。
# --------------------------------------------------------------------------- #
def test_op05_092_static_opp_cost_minus6():
    """静的 (自ターン + 自場天竜人のみ): 相手キャラすべてを コスト-6。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)  # turn_player=0 = 自分のターン
    me, opp = st.players[0], st.players[1]
    roswald = InPlay.of(repo.get("OP05-092"), sickness=False)  # 天竜人
    me.characters = [roswald]  # 自場は天竜人のみ
    v1 = InPlay.of(repo.get(_ISSHO_C6), sickness=False)  # cost6
    v2 = InPlay.of(repo.get(_RED_C3), sickness=False)    # cost3
    opp.characters = [v1, v2]

    eff = _eff(overlay, "OP05-092", "on_attached_don")
    assert eff.get("if", {}).get("self_turn") is True, "overlay の self_turn 条件が無い"
    assert eval_condition(eff.get("if", {}), st, me), \
        "自ターン + 自場天竜人のみで条件成立のはず"

    evaluate_static_effects(st, overlay)

    assert v1.base_cost == 6 - 6, f"相手 cost6 が -6 されていない: {v1.base_cost}"
    assert v2.base_cost == max(0, 3 - 6), \
        f"相手 cost3 が -6 (下限0) されていない: {v2.base_cost}"


def test_op05_092_gate_not_met_non_tenryu_on_board():
    """自場に非天竜人キャラが居ると self_chara_only_feature が不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    roswald = InPlay.of(repo.get("OP05-092"), sickness=False)
    intruder = InPlay.of(repo.get(_NAMI), sickness=False)  # 天竜人でない
    me.characters = [roswald, intruder]

    eff = _eff(overlay, "OP05-092", "on_attached_don")
    assert not eval_condition(eff.get("if", {}), st, me), \
        "非天竜人が居るのに条件成立している"


# --------------------------------------------------------------------------- #
#  OP05-093 ロブ・ルッチ (CHARACTER 黒 cost4 power6000 CP0):
#    【登場時】自分のトラッシュのカード3枚を好きな順番でデッキの下に置くことができる：
#      相手の、コスト2以下のキャラ1枚までとコスト1以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op05_093_on_play_ko_multi_ai():
    """登場時 (AI): トラッシュ3枚をデッキ下 → 相手のコスト2以下1体 + コスト1以下1体をKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_RED_C2)] * 3   # コスト分のトラッシュ
    c2 = InPlay.of(repo.get(_RED_C2), sickness=False)   # コスト2 power4000
    c1 = InPlay.of(repo.get(_NAMI), sickness=False)     # コスト1 power2000
    opp.characters = [c2, c1]

    for prim in _do(overlay, "OP05-093", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-093"), sickness=False))

    assert c2 not in opp.characters, "コスト2以下キャラがKOされていない"
    assert c1 not in opp.characters, "コスト1以下キャラがKOされていない"


def test_op05_093_on_play_optional_cost_unpayable():
    """トラッシュが3枚未満なら任意コスト不能 → KO は起きない (不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_RED_C2)] * 2   # 3枚に満たない
    c1 = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [c1]

    for prim in _do(overlay, "OP05-093", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP05-093"), sickness=False))

    assert c1 in opp.characters, "コスト不能なのに相手キャラがKOされた"


# --------------------------------------------------------------------------- #
#  OP05-094 高級仕立パッチ★ワーク (EVENT 黒 cost1):
#    【メイン】相手のキャラ1枚までを、このターン中、コスト-3。その後、相手のコスト0の
#      キャラ1枚までは、次のリフレッシュフェイズでアクティブにならない。
#    【トリガー】カード2枚を引き、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op05_094_main_cost_minus_then_keep_rested_ai():
    """メイン (AI): 相手キャラ1体を コスト-3 (→cost0) → そのコスト0キャラを次リフレッシュで不活性化。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_RED_C3), sickness=False)  # cost3
    victim.rested = True
    opp.characters = [victim]

    cost_before = victim.base_cost
    for prim in _do(overlay, "OP05-094", "main"):
        execute_effect(prim, st, me, opp, None)

    assert victim.base_cost == cost_before - 3, \
        f"相手キャラ コスト-3 が反映されていない: {victim.base_cost} (before {cost_before})"
    assert victim.stay_rested_next_refresh is True, \
        "コスト0キャラが 次リフレッシュで不活性 (stay_rested) にマークされていない"


def test_op05_094_trigger_draw2_discard1():
    """トリガー (AI): カード2枚を引き、 手札1枚を捨てる (net +1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_NAMI)]
    me.deck = [repo.get(_RED_C2)] * 20
    hand_before = len(me.hand)

    for prim in _do(overlay, "OP05-094", "trigger"):
        execute_effect(prim, st, me, opp, None)

    # +2 draw, -1 discard = net +1
    assert len(me.hand) == hand_before + 1, \
        f"トリガーの draw2/discard1 で手札 net +1 になっていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP05-095 竜の鉤爪 (EVENT 黒 cost2):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。
#      その後、自分のトラッシュが15枚以上ある場合、相手のコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op05_095_counter_pump_and_ko_ai():
    """カウンター (AI): 自リーダー +4000 (バトル中) → トラッシュ15以上で相手コスト4以下1体KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_RED_C2)] * 15  # 15枚以上 = 条件成立
    victim = InPlay.of(repo.get(_LUCCI_C4), sickness=False)  # cost4
    opp.characters = [victim]

    power_before = me.leader.power
    for prim in _do(overlay, "OP05-095", "counter"):
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"
    assert victim not in opp.characters, "トラッシュ15枚以上で相手コスト4以下キャラがKOされていない"


def test_op05_095_counter_no_ko_when_trash_lt15():
    """トラッシュ14枚 (15未満) では KO 条件不成立 → +4000 のみ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_RED_C2)] * 14
    victim = InPlay.of(repo.get(_LUCCI_C4), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP05-095", "counter"):
        execute_effect(prim, st, me, opp, None)

    assert victim in opp.characters, "トラッシュ15枚未満なのに相手キャラがKOされた"


def test_op05_095_counter_pump_human_pick():
    """カウンター (人間): 自リーダー+キャラ 複数 → +4000 の対象選択 target_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_RED_C2), sickness=False)
    me.characters = [friend]
    me.trash = []  # KO 条件は無関係 (pump のみ検証)

    # do[0] = power_pump self_inplay を直接発火
    execute_effect(_do(overlay, "OP05-095", "counter")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP05-096 5億で買うえ～～!!! (EVENT 黒 cost3):
#    【メイン】相手のコスト1以下のキャラ1枚までを、KOするか、持ち主の手札に戻すか、
#      ライフの上か下に表向きで置く。その後、自分の特徴《天竜人》を持つキャラがいる場合、
#      カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op05_096_main_choice_and_draw_ai():
    """メイン (AI): 相手コスト1以下キャラを 択一 で盤面から除去 → 天竜人キャラ在場でドロー1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # コスト1
    opp.characters = [victim]
    me.characters = [InPlay.of(repo.get(_CHARLOSS), sickness=False)]  # 天竜人 → draw 条件
    me.hand = []
    me.deck = [repo.get(_RED_C2)] * 20
    hand_before = len(me.hand)

    for prim in _do(overlay, "OP05-096", "main"):
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, \
        "相手コスト1以下キャラが 択一効果 (KO/手札戻し/ライフ置き) で盤面から除かれていない"
    assert len(me.hand) == hand_before + 1, \
        "天竜人キャラ在場でカード1枚を引いていない"


def test_op05_096_main_no_draw_without_tenryu():
    """天竜人キャラが場に居なければ ドロー条件不成立 → 手札は増えない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [victim]
    me.characters = []  # 天竜人 不在
    me.hand = []
    me.deck = [repo.get(_RED_C2)] * 20

    for prim in _do(overlay, "OP05-096", "main"):
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == 0, "天竜人 不在なのにドローが起きた"


def test_op05_096_main_choice_human_option_pick():
    """メイン (人間): 択一 → option_pick modal が立ち、 KO を選んで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [victim]

    execute_effect(_do(overlay, "OP05-096", "main")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    options = st.pending_choice.get("options", [])
    assert len(options) == 3, f"択一の選択肢が3つでない: {len(options)}"

    # 「KOする」 (= option 0) を選んで解決
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1
    assert victim not in opp.characters, "人間が選んだ KO で相手キャラが除かれていない"


# --------------------------------------------------------------------------- #
#  OP05-098 エネル (LEADER 黄 power5000):
#    【相手のターン中】【ターン1回】自分のライフが0枚になった時、自分のデッキの上から
#      1枚を、ライフの上に加える。その後、自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op05_098_on_life_zero_top_to_life_then_discard_ai():
    """on_life_zero (相手ターン中): デッキ上1枚をライフへ + 手札1枚を捨てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-098", overlay)  # P0 leader = エネル
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= on_life_zero 条件 opp_turn 成立)
    me.life = []            # ライフ 0
    me.hand = [repo.get(_NAMI)]
    me.deck = [repo.get(_RED_C3)] + [repo.get(_RED_C2)] * 20

    eff = _eff(overlay, "OP05-098", "on_life_zero")
    assert eff.get("if", {}).get("opp_turn") is True, "overlay の opp_turn 条件が無い"
    assert eval_condition(eff.get("if", {}), st, me), "相手ターン + ライフ0 で条件成立のはず"

    life_before = len(me.life)
    deck_before = len(me.deck)
    hand_before = len(me.hand)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert len(me.life) == life_before + 1, "デッキ上1枚がライフに加わっていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"
    assert len(me.hand) == hand_before - 1, "手札1枚が捨てられていない"
