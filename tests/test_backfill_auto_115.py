# -*- coding: utf-8 -*-
"""OP11 弾 (黒 海軍 / カリブー海賊団 + 紫 ビッグ・マム宣言 + 黄 魚人島 系) 効果
回帰テスト バックフィル (自動生成 wave 115):
OP11-081 / OP11-082 / OP11-083 / OP11-086 / OP11-091 /
OP11-095 / OP11-097 / OP11-098 / OP11-099 / OP11-100 の 10 枚。

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
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` の両対応)。

    ⚠ 2026-08-05: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を **効果のみ** の
    gate とする (cardqa_op_02 / cardqa_st_04)。 top-level `if` に置くと **任意コストの支払いごと
    消える** ので、 overlay ではこの形の条件を `conditional` の中に移した。
    条件そのものは変わっていないので、 テストはどちらの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    for _prim in eff.get("do") or []:
        if isinstance(_prim, dict) and "conditional" in _prim:
            return (_prim.get("conditional") or {}).get("if") or {}
    return {}


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


def _do_all(overlay, cid, when):
    """指定 card_id の overlay から when 一致の 全 効果 (do, entry) を返す。"""
    out = []
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            out.append((e["do"], e))
    if not out:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return out


# 定番 leader / helper カード
_NEUTRAL = "OP01-001"          # モンキー・D・ルフィ (赤、 leader 条件が無い event 用)
_NAVY_LEADER = "OP11-001"      # コビー (赤/黒 / 海軍/SWORD)
_SHIRAHOSHI = "OP11-022"       # しらほし (緑/黄 / 人魚族/魚人島)
_VICTIM = "OP01-016"           # ナミ (cost1) = KO 対象 (コスト<=8/7/2 すべて満たす)
_NAVY_CHAR = "OP03-089"        # ブランニュー (黒 cost2 / 海軍)
_BIG_CHAR = "OP02-121"         # クザン (cost10) = exists_chara_cost_ge 9 用
_BLACK_EVENT = "EB02-050"      # ココロのちず (黒 cost2 EVENT)
_BLACK_LOW = "EB04-046"        # ドール (黒 cost2 CHARACTER) = trash_to_hand 対象
_CARIBOU = "OP11-083"          # カリブー (黒 cost1) = play_from_trash 対象
_FILLER = "OP01-013"


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op11_wave115_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP11-081", "OP11-082", "OP11-083", "OP11-086", "OP11-091",
           "OP11-095", "OP11-097", "OP11-098", "OP11-099", "OP11-100"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP11-081 皇帝剣破々刃 (EVENT 紫):
#    【メイン】任意コスト宣言 → 相手デッキ上公開、 一致なら相手 元々コスト8以下
#             キャラ1枚までを KO。
#    【トリガー】ドンデッキからドン1枚までをアクティブで追加。
# --------------------------------------------------------------------------- #
def test_op11_081_hahaba_main_ko_on_declared_match_ai():
    """AI: 相手デッキ全コスト同一 → 宣言必中 → コスト8以下の相手キャラ1体を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    opp.deck = [repo.get(_FILLER)] * 10   # 全コスト同一 → 宣言確実に一致
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 <= 8
    opp.characters = [victim]

    do, _ = _do(overlay, "OP11-081", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)  # event = self_inplay None

    assert victim not in opp.characters, "宣言一致でコスト8以下の相手キャラが KO されていない"
    assert victim.card in opp.trash, "KO したキャラがトラッシュに置かれていない"


def test_op11_081_hahaba_main_no_ko_when_declare_miss():
    """相手デッキ上が宣言と不一致 (= 全て別コストが混在で最頻≠トップ) なら KO しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    # 最頻コスト = _FILLER のコスト。 トップだけ別コストカード (_BIG_CHAR cost10) に差し替え、
    # 残りを _FILLER 多数に → declare は最頻 (_FILLER コスト) だがトップは 10 → 不一致。
    opp.deck = [repo.get(_BIG_CHAR)] + [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP11-081", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim in opp.characters, "宣言不一致なのに相手キャラが KO された"


def test_op11_081_hahaba_main_human_ko_target_pick():
    """人間: 相手キャラが複数 → KO 対象の target_pick modal が立ち、 選んで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.deck = [repo.get(_FILLER)] * 10
    v1 = InPlay.of(repo.get(_VICTIM), sickness=False)      # cost1
    v2 = InPlay.of(repo.get(_NAVY_CHAR), sickness=False)   # cost2 (<=8)
    opp.characters = [v1, v2]

    do, _ = _do(overlay, "OP11-081", "main")
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


def test_op11_081_hahaba_trigger_add_don():
    """【トリガー】ドンデッキからドン1枚をアクティブで追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]

    don_before = me.don_active
    deck_don_before = me.don_remaining_in_deck
    do, _ = _do(overlay, "OP11-081", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == don_before + 1, f"トリガーで アクティブドン+1 が無い: {me.don_active}"
    assert me.don_remaining_in_deck == deck_don_before - 1, "ドンデッキから 1 枚供給されていない"


# --------------------------------------------------------------------------- #
#  OP11-082 アラマキ (CHARACTER 黒):
#    【起動メイン】このキャラをトラッシュに置く：自リーダーが《海軍》なら
#      自《海軍》1枚までをこのターン中アクティブキャラにもアタック可 + デッキ上2枚 trash。
# --------------------------------------------------------------------------- #
def test_op11_082_aramaki_activate_main_navy_leader_ai():
    """AI: 自身をトラッシュ (コスト) → 海軍 leader なら海軍対象にアクティブアタック可付与
    + デッキ上2枚をトラッシュ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NAVY_LEADER, overlay)  # コビー = 海軍 leader
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP11-082"), sickness=False)
    me.characters = [src]
    me.deck = [repo.get(_FILLER)] * 10

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-082"]
    assert len(opts) == 1, f"OP11-082 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    # コストで自身がトラッシュされた後、 残る海軍 = leader コビー が対象
    assert "アクティブアタック可" in me.leader.granted_keywords, \
        f"海軍 leader にアクティブアタック可が付与されていない: {me.leader.granted_keywords}"
    # デッキ上2枚 trash: 自身トラッシュ(1) + mill 2 = trash +3
    assert len(me.deck) == deck_before - 2, \
        f"デッキ上2枚がトラッシュされていない: {len(me.deck)} (before {deck_before})"
    assert len(me.trash) == trash_before + 3, \
        f"trash が 自身+デッキ2枚 = +3 でない: {len(me.trash)}"


def test_op11_082_aramaki_no_activate_when_non_navy_leader():
    """自リーダーが《海軍》でなければ 効果本体が発火しない (= if 条件不成立)。
    非海軍 leader では起動メイン発動後もアクティブアタック可が付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # ルフィ = 非海軍
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP11-082"), sickness=False)
    me.characters = [src]
    me.deck = [repo.get(_FILLER)] * 10

    on_play_entry = _do(overlay, "OP11-082", "activate_main")[1]
    assert _cond_of(on_play_entry).get("leader_feature") == "海軍", \
        "overlay の起動メイン条件 leader_feature=海軍 が無い"
    # 非海軍 leader にはアクティブアタック可が付かない (条件で gate)
    assert "アクティブアタック可" not in me.leader.granted_keywords


# --------------------------------------------------------------------------- #
#  OP11-083 カリブー (CHARACTER 黒):
#    【ブロッカー】【登場時】自分の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op11_083_caribou_on_play_discard_two_ai():
    """AI: 登場時 手札 2 枚をトラッシュに捨てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_VICTIM), repo.get(_NAVY_CHAR)]
    src = InPlay.of(repo.get("OP11-083"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    trash_before = len(me.trash)
    trigger_on_play(st, me, opp, src, overlay)

    assert len(me.hand) == hand_before - 2, f"手札 2 枚が捨てられていない: {len(me.hand)}"
    assert len(me.trash) == trash_before + 2, "トラッシュに 2 枚追加されていない"


def test_op11_083_caribou_on_play_human_discard_pick():
    """人間: 手札が 2 枚超 → 捨てる 2 枚を選ぶ self_hand_discard_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_VICTIM), repo.get(_NAVY_CHAR)]
    src = InPlay.of(repo.get("OP11-083"), sickness=True)
    me.characters = [src]

    do, _ = _do(overlay, "OP11-083", "on_play")
    execute_effect(do[0], st, me, opp, src)

    assert st.pending_choice is not None, "人間の手札捨て modal が立たない"
    assert st.pending_choice.get("kind") == "self_hand_discard_pick", \
        f"kind が self_hand_discard_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("limit") == 2, "捨てる枚数 limit が 2 でない"

    hand_before = len(me.hand)
    resolve_pending_choice(st, [0, 1])  # 手札 0,1 を捨てる
    assert st.pending_choice is None, "解決後も modal が残る"
    assert len(me.hand) == hand_before - 2, "人間が選んだ 2 枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  OP11-086 コリブー (CHARACTER 黒):
#    【登場時】自分の手札1枚を捨てる。
#    【起動メイン】このキャラをトラッシュに置く：トラッシュからコスト4以下の
#      「カリブー」1枚までを登場させる。
# --------------------------------------------------------------------------- #
def test_op11_086_coribou_on_play_discard_one_ai():
    """AI: 登場時 手札 1 枚を捨てる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_FILLER), repo.get(_VICTIM)]
    src = InPlay.of(repo.get("OP11-086"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    do, _ = _do(overlay, "OP11-086", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, src)

    assert len(me.hand) == hand_before - 1, f"手札 1 枚が捨てられていない: {len(me.hand)}"


def test_op11_086_coribou_activate_main_revive_caribou_ai():
    """AI: 自身をトラッシュ (コスト) → トラッシュのコスト4以下カリブーを登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    src = InPlay.of(repo.get("OP11-086"), sickness=False)
    me.characters = [src]
    me.trash = [repo.get(_CARIBOU)]  # カリブー cost1 (<=4)

    field_before = len(me.characters)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP11-086"]
    assert len(opts) == 1, f"OP11-086 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    names = [c.card.name for c in me.characters]
    assert "カリブー" in names, f"トラッシュからカリブーが登場していない: {names}"
    assert all(c.card_id != _CARIBOU for c in me.trash), \
        "登場させたカリブーがトラッシュに残っている"
    # 自身トラッシュ (-1) + カリブー登場 (+1) = 場のキャラ数は不変
    assert len(me.characters) == field_before, \
        f"場のキャラ数が想定外: {len(me.characters)} (before {field_before})"


# --------------------------------------------------------------------------- #
#  OP11-091 ベリーグッド (CHARACTER 黒):
#    【登場時】相手は自身のトラッシュからイベント3枚を好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op11_091_verygood_on_play_opp_event_to_deck_ai():
    """AI: 相手トラッシュのイベント 3 枚を相手デッキ下に戻す (相手デッキ +3)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    opp.trash = [repo.get(_BLACK_EVENT)] * 3 + [repo.get(_VICTIM)]  # EVENT3 + 非EVENT1
    src = InPlay.of(repo.get("OP11-091"), sickness=True)
    me.characters = [src]

    opp_trash_before = len(opp.trash)
    opp_deck_before = len(opp.deck)
    trigger_on_play(st, me, opp, src, overlay)

    assert len(opp.deck) == opp_deck_before + 3, "相手デッキ下にイベント 3 枚が戻っていない"
    assert len(opp.trash) == opp_trash_before - 3, "相手トラッシュから 3 枚が抜けていない"
    # 非イベント (ナミ) は残る
    assert any(c.card_id == _VICTIM for c in opp.trash), "非イベントまでデッキに戻されている"


# --------------------------------------------------------------------------- #
#  OP11-095 モンキー・D・ガープ (CHARACTER 黒):
#    【登場時】トラッシュの《海軍》3枚をデッキ下に置ける：自リーダーにレストドン1付与、
#      その後 コスト9以上のキャラがいれば相手のコスト7以下キャラ1枚までを KO。
# --------------------------------------------------------------------------- #
def test_op11_095_garp_on_play_optional_cost_full_ai():
    """AI: 海軍3枚をデッキ下 (コスト) → 自リーダーにレストドン+1 → コスト9以上いれば相手 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_NAVY_CHAR)] * 3    # 海軍 3 枚 (= コスト支払い)
    me.don_rested = 1                        # レストドン付与の供給源
    big = InPlay.of(repo.get(_BIG_CHAR), sickness=False)  # cost10 → exists_chara_cost_ge 9
    me.characters = [big]
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=7)
    opp.characters = [victim]

    leader_don_before = me.leader.attached_dons
    trash_before = len(me.trash)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP11-095", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-095"), sickness=True))

    assert me.leader.attached_dons == leader_don_before + 1, \
        f"自リーダーにレストドンが付与されていない: {me.leader.attached_dons}"
    assert len(me.trash) == trash_before - 3, "トラッシュの海軍 3 枚が抜けていない"
    assert len(me.deck) == deck_before + 3, "デッキ下に海軍 3 枚が戻っていない"
    assert victim not in opp.characters, "コスト9以上がいるのに相手コスト7以下が KO されていない"


def test_op11_095_garp_on_play_no_ko_without_big_chara():
    """コスト9以上のキャラがいなければ (条件不成立) 相手キャラは KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_NAVY_CHAR)] * 3
    me.don_rested = 1
    # コスト9以上のキャラを 場に置かない
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP11-095", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP11-095"), sickness=True))

    assert me.leader.attached_dons == 1, "レストドン付与自体は行われるべき"
    assert victim in opp.characters, "コスト9以上不在なのに相手キャラが KO された"


def test_op11_095_garp_on_play_human_optional_confirm():
    """人間: 任意コスト (海軍3枚デッキ下) の optional_cost_confirm modal が立ち、
    承諾でレストドン付与まで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get(_NAVY_CHAR)] * 3
    me.don_rested = 1
    src = InPlay.of(repo.get("OP11-095"), sickness=True)
    me.characters = [src]

    do, _ = _do(overlay, "OP11-095", "on_play")
    execute_effect(do[0], st, me, opp, src)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    leader_don_before = me.leader.attached_dons
    resolve_pending_choice(st, [1])  # 承諾
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1
    assert me.leader.attached_dons == leader_don_before + 1, \
        "承諾後 自リーダーにレストドンが付与されていない"


# --------------------------------------------------------------------------- #
#  OP11-097 すっかり衰えた……!!! (EVENT 黒):
#    【カウンター】自リーダーかキャラ1枚まで +1000。 その後、 自トラッシュ10枚以上なら
#      トラッシュのコスト3以下 黒キャラ1枚までを手札に加える。
# --------------------------------------------------------------------------- #
def test_op11_097_counter_power_pump_ai():
    """AI: カウンター効果 で 自リーダーを このバトル中 パワー+1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []  # 候補を leader のみに絞る

    power_before = me.leader.power
    do, _ = _do(overlay, "OP11-097", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 1000, \
        f"カウンターで自リーダー +1000 が反映されていない: {me.leader.power}"


def test_op11_097_counter_trash_to_hand_when_10plus():
    """トラッシュ10枚以上 → コスト3以下 黒キャラ1枚をトラッシュから手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    # トラッシュ 10 枚 (= 条件成立) のうち 1 枚を コスト3以下 黒キャラ (ドール)
    me.trash = [repo.get(_FILLER)] * 9 + [repo.get(_BLACK_LOW)]

    # 2 番目の counter 効果 (trash_to_hand) を取得
    entries = _do_all(overlay, "OP11-097", "counter")
    trash_entry = next(
        (do for do, e in entries if _cond_of(e).get("self_trash_count_ge") == 10),
        None,
    )
    assert trash_entry is not None, "self_trash_count_ge=10 の counter 効果が overlay に無い"

    hand_before = len(me.hand)
    for prim in trash_entry:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, "トラッシュから 1 枚が手札に加わっていない"
    assert any(c.card_id == _BLACK_LOW for c in me.hand), \
        "コスト3以下 黒キャラ (ドール) が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP11-098 海底落下 (EVENT 黒):
#    【メイン】デッキ上3枚をトラッシュに置ける：相手のコスト2以下キャラ1枚までを KO。
#    【トリガー】自リーダーかキャラ1枚までを このターン中 +1000。
# --------------------------------------------------------------------------- #
def test_op11_098_main_mill_then_ko_ai():
    """AI: デッキ上3枚を trash (コスト) → 相手コスト2以下キャラ1体を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=2)
    opp.characters = [victim]

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP11-098", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.deck) == deck_before - 3, "デッキ上3枚がトラッシュされていない"
    assert len(me.trash) == trash_before + 3, "trash に 3 枚追加されていない"
    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"


def test_op11_098_main_human_optional_confirm():
    """人間: 任意コスト (デッキ上3枚 trash) の optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    victim = InPlay.of(repo.get(_VICTIM), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP11-098", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= コスト支払い)
    # 承諾後に KO 対象の target_pick が連鎖する場合は先頭候補で解決
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert victim not in opp.characters, "承諾後 相手コスト2以下キャラが KO されていない"


def test_op11_098_trigger_power_pump_ai():
    """【トリガー】自リーダーを このターン中 +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []

    power_before = me.leader.power
    do, _ = _do(overlay, "OP11-098", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 1000, \
        f"トリガーで自リーダー +1000 が反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  OP11-099 ぼくは!!!海軍将校になる男です!!!! (EVENT 黒):
#    【メイン】デッキ上3枚を見て、 自身以外の《海軍》1枚までを公開し手札に加える。
#      その後 残りをトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op11_099_main_search_navy_to_hand_ai():
    """AI: デッキ上3枚から海軍カード1枚を手札に、 残り2枚をトラッシュへ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    # デッキ上3枚: 海軍1 + 非海軍2
    me.deck = [repo.get(_NAVY_CHAR), repo.get(_FILLER), repo.get(_FILLER)] \
        + [repo.get(_FILLER)] * 5

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "OP11-099", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, "海軍カードが手札に加わっていない"
    assert any(c.card_id == _NAVY_CHAR for c in me.hand), \
        "手札に加わったのが海軍カードでない"
    assert len(me.deck) == deck_before - 3, "デッキ上3枚が処理されていない"
    assert len(me.trash) == trash_before + 2, "残り 2 枚がトラッシュに置かれていない"


def test_op11_099_main_human_search_modal():
    """人間: デッキ上3枚に海軍候補あり → search_top_n modal が立ち、 選んで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_NAVY_CHAR), repo.get(_FILLER), repo.get(_FILLER)] \
        + [repo.get(_FILLER)] * 5

    do, _ = _do(overlay, "OP11-099", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間のサーチ modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"

    hand_before = len(me.hand)
    resolve_pending_choice(st, [0])  # 海軍 (idx0) を手札に
    # 解決後に残札のトラッシュ処理まで進む
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert len(me.hand) == hand_before + 1, "人間が選んだ海軍カードが手札に加わっていない"
    assert any(c.card_id == _NAVY_CHAR for c in me.hand), \
        "手札に加わったのが海軍カードでない"


# --------------------------------------------------------------------------- #
#  OP11-100 オトヒメ (CHARACTER 黄):
#    【登場時】自リーダーが「しらほし」なら ライフ上1枚を裏向きにできる：1 ドロー。
# --------------------------------------------------------------------------- #
def test_op11_100_otohime_on_play_draw_when_shirahoshi_ai():
    """AI: 自リーダー = しらほし → ライフ1枚を裏向き (コスト) → 1 ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.face_up_life_count = 1   # 表向きライフ 1 枚 (= 裏向きコストが払える)
    me.deck = [repo.get(_FILLER)] * 5
    src = InPlay.of(repo.get("OP11-100"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trigger_on_play(st, me, opp, src, overlay)

    assert len(me.hand) == hand_before + 1, "1 ドローが起きていない"
    assert len(me.deck) == deck_before - 1, "デッキが 1 枚減っていない"
    assert me.face_up_life_count == 0, "ライフ1枚が裏向きになっていない (コスト未払い)"


def test_op11_100_otohime_on_play_no_effect_when_wrong_leader():
    """自リーダーが「しらほし」でなければ 効果が発火しない (= 条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)  # 非しらほし
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.face_up_life_count = 1
    me.deck = [repo.get(_FILLER)] * 5
    src = InPlay.of(repo.get("OP11-100"), sickness=True)
    me.characters = [src]

    hand_before = len(me.hand)
    trigger_on_play(st, me, opp, src, overlay)

    assert len(me.hand) == hand_before, "条件不成立 (リーダー違い) なのにドローした"


def test_op11_100_otohime_on_play_human_optional_confirm():
    """人間: しらほし leader で 任意コストの optional_cost_confirm modal が立ち、
    承諾で 1 ドローできる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SHIRAHOSHI, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.face_up_life_count = 1
    me.deck = [repo.get(_FILLER)] * 5
    src = InPlay.of(repo.get("OP11-100"), sickness=True)
    me.characters = [src]

    do, _ = _do(overlay, "OP11-100", "on_play")
    execute_effect(do[0], st, me, opp, src)

    assert st.pending_choice is not None, "人間の任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    hand_before = len(me.hand)
    resolve_pending_choice(st, [1])  # 承諾
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1
    assert len(me.hand) == hand_before + 1, "承諾後 1 ドローが起きていない"
