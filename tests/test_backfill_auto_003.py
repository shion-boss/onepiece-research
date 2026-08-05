# -*- coding: utf-8 -*-
"""EB01 弾 効果 回帰テスト バックフィル (自動生成 wave 003):
EB01-034 / EB01-035 / EB01-036 / EB01-037 / EB01-038 / EB01-039 /
EB01-040 / EB01-042 / EB01-043 / EB01-045 の 10 枚。

目的 (= test_backfill_auto_001/002.py と同一方針):
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
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _cond_of(eff: dict) -> dict:
    """効果の発動条件を取り出す (top-level `if` / `conditional` / optional_cost_then 内 の三形対応)。

    ⚠ 2026-08-05: 公式は 「「：」以前が発動コスト」 (cardqa_st_06)。 コロン後の条件は **効果のみ**
    を gate するので、 overlay ではその条件を `conditional` の中へ移した。
    `optional_cost_then` を持つ効果では **cost を条件の外に出す** 必要があるため、
    conditional は `effect` 配列の中に入る。 条件自体は変わっていないので、
    テストはどの位置でも読めればよい。
    """
    if isinstance(eff.get("if"), dict):
        return eff["if"]
    def _dig(arr):
        for _p in arr or []:
            if not isinstance(_p, dict):
                continue
            if "conditional" in _p:
                return (_p.get("conditional") or {}).get("if") or {}
            if "optional_cost_then" in _p:
                got = _dig((_p["optional_cost_then"] or {}).get("effect") or [])
                if got:
                    return got
        return {}
    return _dig(eff.get("do") or [])


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    # デッキは対象カード以外のバニラで埋める (= draw/mill の混入を避ける)
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


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の (do, effect) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave3_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB01-034", "EB01-035", "EB01-036", "EB01-037", "EB01-038",
           "EB01-039", "EB01-040", "EB01-042", "EB01-043", "EB01-045"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB01-034 ミス・ウェンズデー: 【相手のアタック時】【ターン1回】ドン!!-1：
#    リーダーが『B・W』を含む → ドン!!デッキからドン!!1枚までをアクティブで追加
# --------------------------------------------------------------------------- #
def test_eb01_034_wednesday_opp_attack_add_don_ai():
    """AI: 相手アタック時 do → ドンデッキからドン!!1枚をアクティブ追加。"""
    # ⚠ 2026-08-05: コロン後の条件は効果のみを gate するため overlay では conditional の中。
    #   条件を満たさない盤面で do を直接実行すると何も起きない (以前は top-level if が
    #   skip していたので露見しなかった)。 条件を満たすリーダーを使う。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay)  # マゼラン (B・W ではないが do を直接検証)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    me.don_remaining_in_deck = 8

    do, eff = _do(overlay, "EB01-034", "opp_attack")
    # overlay 条件: リーダー『B・W』/ ターン1回 / ドン-1
    assert "B・W" in _cond_of(eff).get("leader_features_any", []), \
        "overlay の条件 leader_features_any=B・W が無い"
    assert eff.get("cost", {}).get("once_per_turn") is True, "ターン1回 制約が無い"
    assert eff.get("cost", {}).get("pay_don") == 1, "ドン-1 コストが無い"

    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-034"), sickness=False))

    assert me.don_active == 3, f"ドン+1 (アクティブ) が反映されていない: {me.don_active}"
    assert me.don_remaining_in_deck == 7, "ドンデッキから1枚供給されていない"


# --------------------------------------------------------------------------- #
#  EB01-035 ミス・マンデー: 【登場時】リーダー『B・W』→
#    自リーダーかキャラ1枚まで、 このターン中 +1000
# --------------------------------------------------------------------------- #
def test_eb01_035_monday_on_play_pump_ai():
    """AI: 登場時 do → 自リーダー/キャラ1枚に +1000 (このターン)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-071", overlay)
    me, opp = st.players[0], st.players[1]
    ch = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [ch]
    leader_before = me.leader.power

    do, eff = _do(overlay, "EB01-035", "on_play")
    assert "B・W" in _cond_of(eff).get("leader_features_any", []), \
        "overlay の条件 leader_features_any=B・W が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-035"), sickness=True))

    # AI は自リーダーを +1000 (最有力対象)
    pumped = (me.leader.power == leader_before + 1000) or (ch.power == 2000 + 1000)
    assert pumped, \
        f"自リーダー/キャラのいずれにも +1000 が乗っていない: L={me.leader.power} C={ch.power}"


def test_eb01_035_monday_on_play_pump_human_pick():
    """人間: 登場時 → power_pump target_pick modal が立ち、 選んだキャラに +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-071", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    ch = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    me.characters = [ch]

    do, _ = _do(overlay, "EB01-035", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB01-035"), sickness=True))

    assert st.pending_choice is not None, "人間 + 対象複数で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "power_pump", \
        "primitive_kind が power_pump でない"
    cands = st.pending_choice.get("candidates", [])
    ch_idx = next(i for i, c in enumerate(cands) if c["iid"] == ch.instance_id)
    resolve_pending_choice(st, [ch_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert ch.power == 2000 + 1000, f"人間が選んだキャラに +1000 が乗っていない: {ch.power}"


# --------------------------------------------------------------------------- #
#  EB01-036 ミノチワワ: 【KO時】リーダー《インペルダウン》→
#    ドン!!デッキからドン!!1枚までを、 レストで追加
# --------------------------------------------------------------------------- #
def test_eb01_036_minochihuahua_on_ko_add_rested_don_ai():
    """AI: KO時 do → ドンデッキからドン!!1枚をレストで追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-071", overlay)  # マゼラン (インペルダウン)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 0
    me.don_remaining_in_deck = 8

    do, eff = _do(overlay, "EB01-036", "on_ko")
    assert _cond_of(eff).get("leader_feature") == "インペルダウン", \
        "overlay の条件 leader_feature=インペルダウン が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-036"), sickness=False))

    assert me.don_rested == 1, f"ドン+1 (レスト) が反映されていない: {me.don_rested}"
    assert me.don_remaining_in_deck == 7, "ドンデッキから1枚供給されていない"


# --------------------------------------------------------------------------- #
#  EB01-037 Mr.9: 【相手のアタック時】【ターン1回】ドン!!-1：
#    相手のコスト2以下のキャラ1枚までを、 KOする
# --------------------------------------------------------------------------- #
def test_eb01_037_mr9_opp_attack_ko_ai():
    """AI: 相手アタック時 do → 相手コスト2以下キャラ1枚を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost2
    opp.characters = [victim]

    do, eff = _do(overlay, "EB01-037", "opp_attack")
    assert eff.get("cost", {}).get("once_per_turn") is True, "ターン1回 制約が無い"
    assert eff.get("cost", {}).get("pay_don") == 1, "ドン-1 コストが無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-037"), sickness=False))

    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"
    assert repo.get("OP01-016") in opp.trash, "KO したキャラが相手トラッシュにない"


def test_eb01_037_mr9_opp_attack_ko_human_pick():
    """人間 + 相手コスト2以下キャラ複数 → target_pick modal → resolve で1枚 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)   # cost2
    b = InPlay.of(repo.get("EB04-002"), sickness=False)   # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB01-037", "opp_attack")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB01-037"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "ko", "primitive_kind が ko でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert a not in opp.characters, "人間が選んだ相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  EB01-038 オカマ道 (EVENT):
#   【カウンター】ドン!!-1：リーダー『B・W』→ 自キャラ1枚を選び、
#     アタックの対象をそのキャラに変更する
#   【トリガー】ドン!!-1：カード2枚を引く
# --------------------------------------------------------------------------- #
def test_eb01_038_okamamichi_counter_redirect_human_pick():
    """人間: カウンター do → redirect_attack target_pick modal が自キャラで立つ。"""
    # ⚠ 2026-08-05: コロン後の条件は効果のみを gate するため overlay では conditional の中。
    #   条件を満たさない盤面で do を直接実行すると何も起きない (以前は top-level if が
    #   skip していたので露見しなかった)。 条件を満たすリーダーを使う。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP14-079", overlay, human_idx=0)  # マゼラン
    me, opp = st.players[0], st.players[1]
    ch = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters = [ch]

    do, eff = _do(overlay, "EB01-038", "counter")
    assert "B・W" in _cond_of(eff).get("leader_features_any", []), \
        "overlay の条件 leader_features_any=B・W が無い"
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 自キャラで redirect modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "redirect_attack", \
        "primitive_kind が redirect_attack でない"
    ch_idx = next(i for i, c in enumerate(st.pending_choice["candidates"])
                  if c["iid"] == ch.instance_id)
    resolve_pending_choice(st, [ch_idx])  # crash せず解決


def test_eb01_038_okamamichi_counter_redirect_ai_no_crash():
    """AI: カウンター do を回しても crash しない (自キャラ自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-071", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP01-016"), sickness=False)]
    do, _ = _do(overlay, "EB01-038", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert st.pending_choice is None, "AI 文脈で modal が残ってはいけない"


def test_eb01_038_okamamichi_trigger_draw2():
    """トリガー do: カード2枚を引く (手札 +2 / デッキ -2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    do, _ = _do(overlay, "EB01-038", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 2, f"2ドローで手札 +2 になっていない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減っていない"


# --------------------------------------------------------------------------- #
#  EB01-039 降三世 引奈落 (EVENT):
#   【メイン】ドン!!-1：相手のコスト8以下のキャラ1枚までを、 KOする
#   【トリガー】ドン!!1枚をアクティブで追加
# --------------------------------------------------------------------------- #
def test_eb01_039_main_ko8_ai():
    """AI: メイン do → ドン-1 を払い、 相手コスト8以下キャラ1枚を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    victim = InPlay.of(repo.get("OP11-015"), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "EB01-039", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == 4, f"ドン-1 が消費されていない: {me.don_active}"
    assert victim not in opp.characters, "相手コスト8以下キャラが KO されていない"


def test_eb01_039_main_ko8_human_pick():
    """人間 + 相手キャラ複数 → target_pick modal → resolve で1枚 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("EB04-002"), sickness=False)
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB01-039", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert a not in opp.characters, "人間が選んだ相手キャラが KO されていない"


def test_eb01_039_trigger_add_don():
    """トリガー do: ドン!!1枚をアクティブで追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1
    me.don_remaining_in_deck = 9

    do, _ = _do(overlay, "EB01-039", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == 2, f"ドン+1 (アクティブ) が反映されていない: {me.don_active}"
    assert me.don_remaining_in_deck == 8, "ドンデッキから1枚供給されていない"


# --------------------------------------------------------------------------- #
#  EB01-040 キュロス (LEADER):
#   【起動メイン】【ターン1回】自ライフ上から1枚を表向きにできる：
#     相手のコスト0のキャラ1枚までを、 KOする
# --------------------------------------------------------------------------- #
def test_eb01_040_kyros_activate_main_listed_and_once_per_turn():
    """起動メインが legal に出て、 発動後は【ターン1回】で再度出ない (AI, crash なし)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "EB01-040", overlay)
    me, opp = st.players[0], st.players[1]

    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB01-040"]
    assert len(mine) == 1, f"EB01-040 の起動メインが legal に出ない: {len(mine)}"

    src, eff = mine[0]
    fire_activate_main(st, me, opp, src, eff)  # 対象なし → no-op、 crash しない
    assert me.leader is not None, "発動で自リーダーが消えてはいけない"

    opts2 = list_activate_main_effects(st, me, overlay)
    mine2 = [(s, e) for (s, e) in opts2 if s.card.card_id == "EB01-040"]
    assert len(mine2) == 0, "【ターン1回】なのに同ターンで再度 起動メインが出る"


def test_eb01_040_kyros_ko_cost0_target():
    """コスト軽減で 実効0 になった相手キャラを KO できる (現在コスト参照)。

    公式 EB01-040 の平文「相手のコスト0のキャラ」 = 現在(実効)コスト。 印刷コスト0の
    キャラは存在しないため、 overlay を printed-cost の filter {cost_eq:0} のまま置くと
    KO が永久に不発だった。 filter を {current_cost_eq:0} に直し、
    one_opponent_character_filtered resolver が InPlay.base_cost を見るよう修正済み。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-040", overlay)  # ダミー起動元 (do を直接検証)
    me, opp = st.players[0], st.players[1]
    # コスト軽減で実効0 になった相手キャラ (印刷0キャラは存在しないため override で再現)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # 印刷 cost2
    victim.base_cost_override = 0
    # 実効コストが 0 でない別キャラ (= KO 対象外) も並べて選別を検証
    bystander = InPlay.of(repo.get("OP11-015"), sickness=False)  # 高コスト
    opp.characters = [victim, bystander]
    assert victim.base_cost == 0, "override が効いていない"

    do, _ = _do(overlay, "EB01-040", "activate_main")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-040"), sickness=False))

    assert victim not in opp.characters, "実効コスト0の相手キャラが KO されていない"
    assert repo.get("OP01-016") in opp.trash, "KO したキャラが相手トラッシュにない"
    assert bystander in opp.characters, "実効コスト0でないキャラまで KO されている"


def test_eb01_040_kyros_ko_ignores_printed_cost0_absent():
    """印刷コスト2 だが軽減されていない相手キャラは (現在コスト!=0 なので) KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-040", overlay)
    me, opp = st.players[0], st.players[1]
    normal = InPlay.of(repo.get("OP01-016"), sickness=False)  # 印刷 cost2、 軽減なし
    opp.characters = [normal]

    do, _ = _do(overlay, "EB01-040", "activate_main")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB01-040"), sickness=False))

    assert normal in opp.characters, "現在コスト0でないキャラが誤って KO された"


# --------------------------------------------------------------------------- #
#  EB01-042 スカーレット: 【起動メイン】このキャラをトラッシュに置く：
#    手札から「スカーレット」以外のコスト3以下《ドレスローザ》キャラ1枚までを
#    レストで登場。 その後、 相手キャラ1枚までを このターン中 コスト-2
# --------------------------------------------------------------------------- #
def test_eb01_042_scarlet_activate_main_ai():
    """AI: 起動メイン do → 手札の《ドレスローザ》cost3以下をレスト登場 + 相手キャラ cost-2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB03-048")]  # レベッカ (ドレスローザ, cost2)
    oppc = InPlay.of(repo.get("OP11-015"), sickness=False)
    opp.characters = [oppc]
    opp_cost_before = oppc.base_cost
    chars_before = len(me.characters)

    do, _ = _do(overlay, "EB01-042", "activate_main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.characters) == chars_before + 1, "手札の《ドレスローザ》キャラが登場していない"
    played = me.characters[-1]
    assert played.card.card_id == "EB03-048", "登場したのがレベッカ (EB03-048) でない"
    assert played.rested is True, "レストで登場していない"
    assert repo.get("EB03-048") not in me.hand, "登場元カードが手札に残っている"
    assert oppc.base_cost == max(0, opp_cost_before - 2), \
        f"相手キャラの コスト-2 が反映されていない: {opp_cost_before} -> {oppc.base_cost}"


def test_eb01_042_scarlet_cost_minus_human_pick():
    """人間 + 相手キャラ複数 → cost_minus target_pick modal → resolve で対象にコスト減。

    減少量そのもの (公式 -2) の検証は下の
    test_eb01_042_cost_minus_amount_carries_through_human_resolve で行う (engine 修正済:
    outer_value に spec 全体を載せ、 人間 resolve 再実行でも amount=-2 が保持される)。
    ここでは modal が正しく立ち、 人間の選んだ対象にコスト減が乗ることを assert する。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP11-015"), sickness=False)
    b = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [a, b]
    a_cost_before = a.base_cost

    do, _ = _do(overlay, "EB01-042", "activate_main")
    # 2 番目の primitive = cost_minus (1 番目は play_from_hand)
    execute_effect(do[1], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で cost_minus modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "cost_minus", \
        "primitive_kind が cost_minus でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert a.base_cost < a_cost_before, \
        f"人間が選んだ相手キャラにコスト減が乗っていない: {a_cost_before} -> {a.base_cost}"
    assert b.base_cost == repo.get("OP01-016").cost, "選ばなかったキャラにコスト減が乗っている"


def test_eb01_042_cost_minus_amount_carries_through_human_resolve():
    """人間 resolve でも 公式どおり コスト-2 が適用される (amount が pending_choice の
    primitive_value に載り、 再実行で復元される)。

    修正前は execute_effect が outer_value=target_spec (target 文字列のみ) を渡して
    いたため、 resolve_pending_choice の再実行時に amount=1 default に落ち、 公式 -2 が
    -1 になっていた (power_pump_multi と同型の bug)。 outer_value に spec 全体
    ({target, amount, duration}) を載せる修正で amount/duration が保持される。
    """
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP11-015"), sickness=False)   # 高コスト
    b = InPlay.of(repo.get("OP01-016"), sickness=False)    # cost2
    opp.characters = [a, b]
    a_cost_before = a.base_cost

    do, _ = _do(overlay, "EB01-042", "activate_main")
    # 2 番目の primitive = cost_minus (1 番目は play_from_hand)
    execute_effect(do[1], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で cost_minus modal が立たない"
    assert st.pending_choice.get("primitive_kind") == "cost_minus", \
        "primitive_kind が cost_minus でない"
    # 公式仕様の amount(=2、 コスト-2)/duration が primitive_value に保持されていること
    # (overlay は cost_minus の amount を正の数で表す = base_cost から差し引かれる量)。
    pv = st.pending_choice.get("primitive_value")
    assert isinstance(pv, dict) and pv.get("amount") == 2, \
        f"primitive_value に amount=2 (コスト-2) が載っていない: {pv}"

    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    # 公式 EB01-042 は コスト-2。 人間 resolve 経路でも -2 (max 0 clamp) が適用される。
    assert a.base_cost == max(0, a_cost_before - 2), \
        f"人間 resolve で 公式どおり コスト-2 が適用されていない: " \
        f"{a_cost_before} -> {a.base_cost} (期待 {max(0, a_cost_before - 2)})"
    assert b.base_cost == repo.get("OP01-016").cost, \
        "選ばなかったキャラにコスト減が乗っている"


# --------------------------------------------------------------------------- #
#  EB01-043 スパンダイン: 【登場時】自トラッシュの『CP』特徴カード3枚を
#    好きな順番でデッキ下に置く：自トラッシュから「スパンダイン」以外の
#    コスト4以下『CP』キャラ1枚までを、 レストで登場
# --------------------------------------------------------------------------- #
def _eb01_043_trash():
    """cost 用 CP カード 3 枚 + 登場対象の CP キャラ (OP07-084) を末尾に配置。"""
    repo = _repo()
    return [
        repo.get("EB01-044"),  # ファンクフリード (CP9)
        repo.get("OP08-081"),  # ゲルニカ (CP0)
        repo.get("OP07-080"),  # カク (CP0)
        repo.get("OP07-084"),  # ジスモンダ (CP0, cost2, 効果なし=登場対象)
    ]


def test_eb01_043_spandine_on_play_ai():
    """AI: 登場時 → CPカード3枚をデッキ下へ + 残る CP キャラ1枚をレスト登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = _eb01_043_trash()
    src = InPlay.of(repo.get("EB01-043"), sickness=True)
    me.characters = [src]
    deck_before = len(me.deck)

    do, _ = _do(overlay, "EB01-043", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, src)

    # 3 枚がデッキ下へ (= deck +3)、 1 枚が登場 → trash 空
    assert len(me.deck) == deck_before + 3, \
        f"CPカード3枚がデッキ下に置かれていない: deck {deck_before} -> {len(me.deck)}"
    assert me.deck[-3:][-1].card_id == "OP07-080", "デッキ最下 = 好きな順(先頭から)で置かれていない"
    played = [c for c in me.characters if c.card.card_id == "OP07-084"]
    assert len(played) == 1, "残る CP キャラ (OP07-084) が登場していない"
    assert played[0].rested is True, "レストで登場していない"
    assert len(me.trash) == 0, "コスト3枚 + 登場1枚 で トラッシュが空にならない"


def test_eb01_043_spandine_on_play_human_optional_cost():
    """人間: 登場時 → optional_cost_confirm modal → pay ([1]) で登場が解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = _eb01_043_trash()
    src = InPlay.of(repo.get("EB01-043"), sickness=True)
    me.characters = [src]

    do, _ = _do(overlay, "EB01-043", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, src)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    assert st.pending_choice is None, "解決後も modal が残る"
    assert any(c.card.card_id == "OP07-084" for c in me.characters), \
        "任意コスト承認後に CP キャラ (OP07-084) が登場していない"


# --------------------------------------------------------------------------- #
#  EB01-045 ブルック: 【登場時】相手のコスト0のキャラがいる場合、
#    このキャラは このターン中【速攻】を得る
# --------------------------------------------------------------------------- #
def test_eb01_045_brook_on_play_gains_rush_when_opp_cost0():
    """相手にコスト0のキャラがいる → 登場時 このキャラが【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    brook = InPlay.of(repo.get("EB01-045"), sickness=True)
    me.characters = [brook]
    # コスト軽減で 0 になった相手キャラ (印刷0キャラは存在しないため override で再現)
    ov = InPlay.of(repo.get("OP01-016"), sickness=False)
    ov.base_cost_override = 0
    opp.characters = [ov]

    trigger_on_play(st, me, opp, brook, overlay)

    assert brook.is_rush_now is True, "相手コスト0キャラ在で【速攻】を得ていない"


def test_eb01_045_brook_on_play_no_rush_without_opp_cost0():
    """相手にコスト0のキャラがいない → 【速攻】を得ない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    brook = InPlay.of(repo.get("EB01-045"), sickness=True)
    me.characters = [brook]
    opp.characters = [InPlay.of(repo.get("OP11-015"), sickness=False)]  # 高コスト (cost != 0)

    trigger_on_play(st, me, opp, brook, overlay)

    assert brook.is_rush_now is False, "条件不成立なのに【速攻】を得ている"
