# -*- coding: utf-8 -*-
"""カード効果 回帰テスト バックフィル (自動生成 wave 176):
ST12-011 / ST12-012 / ST12-013 / ST12-014 / ST12-016 / ST12-017 /
ST13-003 / ST13-004 / ST13-008 / ST13-009 の 10 枚
(= ST12 青「東の海 / ジェルマ」系 + 緑 獅子歌歌 + ST13 黒黄/黄「エース&白ひげ」系の効果カード群)。

目的 (= test_backfill_auto_001〜175.py と同一方針):
  (1) 各カードの効果が overlay / 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
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
)

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
#  効果の薄い (= 素材用) カード。
# --------------------------------------------------------------------------- #
NAMI = "OP01-016"       # ナミ (cost1 power2000 麦わらの一味) フィラー / cost1 char
SANJI = "OP01-013"      # サンジ (cost2 power3000 麦わらの一味) フィラー / cost2 char
LEADER = "OP01-001"     # モンキー・D・ルフィ (赤 LEADER)
COST5_CHAR = "ST13-008"  # サボ (cost5 power6000 CHARACTER 黄) — cost5 キャラ素材


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, turn=0,
           opp_leader_id=LEADER):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(SANJI)] * 30
    p1.deck = [repo.get(SANJI)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果を返す。
    needle 指定時は do[0] に needle キーを含む効果を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert matches, f"{cid} に when={when} の効果がない"
    if needle is not None:
        matches = [e for e in matches if needle in e["do"][0]]
        assert matches, f"{cid} の when={when} に do[0]={needle} の効果がない"
    return matches[0]


def _drain(st, picks=None, guard=8):
    """resolve 後続の連鎖 modal を流す (guard 付き)。"""
    if picks is None:
        picks = [0]
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, list(picks))
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave176_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST12-011", "ST12-012", "ST12-013", "ST12-014", "ST12-016",
           "ST12-017", "ST13-003", "ST13-004", "ST13-008", "ST13-009"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST12-011 サンジ (CHARACTER 青 cost2 power3000):
#    【ドン!!×1】【アタック時】自分の手札が5枚以下の場合、このキャラは、
#    次の自分のターン開始時まで、パワー+2000。
# --------------------------------------------------------------------------- #
def test_st12_011_on_attack_self_pump_ai():
    """【アタック時】(手札5以下 + ドン1ゲート) 自身 +2000 (次自ターン開始まで)。 target=self 単純 pump。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(NAMI)] * 3  # 3 枚 (<= 5)
    attacker = InPlay.of(repo.get("ST12-011"), sickness=False)  # power 3000
    attacker.attached_dons = 1
    me.characters = [attacker]

    eff = _eff(overlay, "ST12-011", "on_attack")
    assert eff.get("if", {}).get("self_hand_count_le") == 5, \
        "overlay の 条件 self_hand_count_le=5 が無い"
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    power_before = attacker.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, attacker)

    assert attacker.power == power_before + 2000, \
        f"アタック時 自己 +2000 が反映されていない: {attacker.power} (before {power_before})"


# --------------------------------------------------------------------------- #
#  ST12-012 シャーロット・プリン (CHARACTER 青 cost2 power2000):
#    【起動メイン】このキャラを持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_st12_012_activate_main_return_self_to_hand_ai():
    """起動メイン: このキャラを持ち主の手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    prin = InPlay.of(repo.get("ST12-012"), sickness=False)
    me.characters = [prin]
    me.hand = []

    options = list_activate_main_effects(st, me, overlay)
    prin_opts = [(src, eff) for (src, eff) in options
                 if src.card.card_id == "ST12-012"]
    assert len(prin_opts) == 1, \
        f"ST12-012 の起動メインが legal に出ない: {len(prin_opts)}"
    fire_activate_main(st, me, opp, *prin_opts[0])

    assert prin not in me.characters, "プリンが場から手札に戻っていない"
    assert any(c.card_id == "ST12-012" for c in me.hand), \
        "プリンが手札に戻っていない"


# --------------------------------------------------------------------------- #
#  ST12-013 ゼフ (CHARACTER 青 cost5 power5000):
#    【登場時】自分のデッキの上から3枚を見て、好きな順番に並び替え、デッキの上か下に置く。
#    【アタック時】自分のデッキの上から1枚を公開し、コスト2のキャラカード1枚までを、
#    レストで登場させる。その後、残りをデッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_st12_013_on_play_look_top_reorder_ai():
    """【登場時】デッキ上3枚を並び替え (AI choice = コスト昇順)。 枚数保存 + 昇順確認。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # 上3枚を コスト降順 (5,2,1) にして 昇順ソートを検証
    me.deck = [repo.get(COST5_CHAR), repo.get(SANJI), repo.get(NAMI)] \
        + [repo.get(SANJI)] * 15
    deck_before = len(me.deck)

    eff = _eff(overlay, "ST12-013", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST12-013"), sickness=True))

    assert len(me.deck) == deck_before, "並び替えでデッキ枚数が変わってはいけない"
    assert me.deck[0].cost == 1 and me.deck[1].cost == 2 and me.deck[2].cost == 5, \
        f"上3枚がコスト昇順に並び替えられていない: {[c.cost for c in me.deck[:3]]}"


def test_st12_013_on_attack_reveal_top_play_cost2_ai():
    """【アタック時】デッキ上1枚公開 → コスト2キャラなら レストで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(SANJI)] + [repo.get(NAMI)] * 20  # top = サンジ cost2 CHARACTER
    me.characters = []

    eff = _eff(overlay, "ST12-013", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST12-013"), sickness=False))
    _drain(st, [0])

    played = [c for c in me.characters if c.card.card_id == SANJI]
    assert played, "デッキ上のコスト2キャラが登場していない"
    assert played[0].rested is True, "登場したキャラはレスト状態であるべき"


def test_st12_013_on_attack_reveal_human_confirm():
    """人間 + デッキ上がコスト2キャラ → reveal_top_play_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(SANJI)] + [repo.get(NAMI)] * 20
    me.characters = []

    eff = _eff(overlay, "ST12-013", "on_attack")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST12-013"), sickness=False))

    assert st.pending_choice is not None, "人間で reveal_top_play modal が立たない"
    assert st.pending_choice.get("kind") == "reveal_top_play_confirm", \
        f"kind が reveal_top_play_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 登場させる
    _drain(st, [0])
    assert any(c.card.card_id == SANJI for c in me.characters), \
        "人間承諾後 コスト2キャラが登場していない"


# --------------------------------------------------------------------------- #
#  ST12-014 デュバル (CHARACTER 青 cost2 power1000):
#    【ブロッカー】【登場時】自分のデッキの上から3枚を見て、好きな順番に並び替え、
#    デッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_st12_014_on_play_look_top_reorder_ai():
    """【登場時】デッキ上3枚を並び替え (AI choice = コスト昇順)。 枚数保存 + 昇順確認。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(COST5_CHAR), repo.get(SANJI), repo.get(NAMI)] \
        + [repo.get(SANJI)] * 15
    deck_before = len(me.deck)

    eff = _eff(overlay, "ST12-014", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST12-014"), sickness=True))

    assert len(me.deck) == deck_before, "並び替えでデッキ枚数が変わってはいけない"
    assert me.deck[0].cost == 1 and me.deck[1].cost == 2 and me.deck[2].cost == 5, \
        f"上3枚がコスト昇順に並び替えられていない: {[c.cost for c in me.deck[:3]]}"


# --------------------------------------------------------------------------- #
#  ST12-016 獅子歌歌 (EVENT 緑 cost2):
#    【メイン】/【カウンター】相手のリーダーかコスト4以下のキャラ1枚までを、レストにする。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_st12_016_main_rest_opp_ai():
    """【メイン】相手のコスト4以下キャラ1枚をレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 (<=4) active
    victim.rested = False
    opp.characters = [victim]

    eff = _eff(overlay, "ST12-016", "main")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim.rested is True, "相手のコスト4以下キャラがレストされていない"


def test_st12_016_main_rest_human_pick():
    """人間 + 相手 リーダー + キャラ (= 2 候補) → rest の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 (<=4)
    victim.rested = False
    opp.characters = [victim]

    eff = _eff(overlay, "ST12-016", "main")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    victim_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == victim.instance_id)
    resolve_pending_choice(st, [victim_idx])
    _drain(st, [victim_idx])
    assert victim.rested is True, "人間が選んだ相手キャラがレストされていない"


def test_st12_016_trigger_fires_main_ai():
    """【トリガー】このカードの【メイン】効果を発動 → 相手コスト4以下キャラをレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(SANJI), sickness=False)
    victim.rested = False
    opp.characters = [victim]
    st.current_source_card_id = "ST12-016"  # fire_self_effect の source

    eff = _eff(overlay, "ST12-016", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert victim.rested is True, "トリガー経由の メイン効果 (レスト) が発火していない"


# --------------------------------------------------------------------------- #
#  ST12-017 整形ショット (EVENT 青 cost1):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
#    その後、自分のデッキの上から1枚を公開し、コスト2のキャラカード1枚までを、登場させる。
#    その後、残りをデッキの上か下に置く。
# --------------------------------------------------------------------------- #
def test_st12_017_counter_pump_leader_ai():
    """【カウンター】(1) 自リーダーorキャラ1枚 +2000。 AI (リーダーのみ = 既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _eff(overlay, "ST12-017", "counter", needle="power_pump")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_st12_017_counter_reveal_top_play_ai():
    """【カウンター】(2) デッキ上1枚公開 → コスト2キャラなら登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(SANJI)] + [repo.get(NAMI)] * 20  # top = cost2 CHARACTER
    me.characters = []

    eff = _eff(overlay, "ST12-017", "counter", needle="power_pump")
    # do[1] = reveal_top_play
    execute_effect(eff["do"][1], st, me, opp, None)
    _drain(st, [0])

    assert any(c.card.card_id == SANJI for c in me.characters), \
        "デッキ上のコスト2キャラが登場していない"


def test_st12_017_counter_pump_human_pick():
    """人間 + 自リーダー + キャラ (= 2 候補) → +2000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(SANJI), sickness=False)
    me.characters = [friend]

    eff = _eff(overlay, "ST12-017", "counter", needle="power_pump")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands)
                      if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  ST13-003 モンキー・D・ルフィ (LEADER 黒/黄):
#    【ドン!!×2】【起動メイン】【ターン1回】自分の手札1枚を捨てることができる：
#    自分のライフが0枚の場合、自分の手札かトラッシュのコスト5のキャラカード2枚までを、
#    自分のライフの上に表向きで加える。
# --------------------------------------------------------------------------- #
def test_st13_003_activate_main_hand_or_trash_to_life_ai():
    """起動メイン: 手札1捨て (コスト) → ライフ0の場合、 トラッシュの cost5 キャラ2枚をライフへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST13-003", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 2  # ドン!!×2 ゲート成立
    me.hand = [repo.get(NAMI)]   # 捨てコスト用 (= 最悪札)
    me.trash = [repo.get(COST5_CHAR), repo.get(COST5_CHAR)]  # cost5 キャラ 2 枚
    me.life = []                 # ライフ 0 (= do の条件 self_life_le 0 成立)

    eff = _eff(overlay, "ST13-003", "activate_main")
    assert eff.get("if", {}).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"

    options = list_activate_main_effects(st, me, overlay)
    luffy_opts = [(src, eff2) for (src, eff2) in options
                  if src.card.card_id == "ST13-003"]
    assert len(luffy_opts) == 1, \
        f"ST13-003 の起動メインが legal に出ない: {len(luffy_opts)}"
    fire_activate_main(st, me, opp, *luffy_opts[0])
    _drain(st)

    assert len(me.life) == 2, f"cost5 キャラ 2 枚がライフに加わっていない: {len(me.life)}"
    assert all(c.cost == 5 for c in me.life), \
        f"ライフに加わったのが cost5 キャラでない: {[c.cost for c in me.life]}"
    assert not any(c.card_id == COST5_CHAR for c in me.trash), \
        "トラッシュの cost5 キャラがライフへ移っていない"


def test_st13_003_activate_main_human_discard_pick():
    """人間: 起動メインの 手札1捨てコスト → activate_main_discard_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST13-003", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 2
    me.hand = [repo.get(NAMI), repo.get(SANJI)]  # 2 枚 (捨て対象を選ばせる)
    me.trash = [repo.get(COST5_CHAR), repo.get(COST5_CHAR)]
    me.life = []

    options = list_activate_main_effects(st, me, overlay)
    luffy_opts = [(src, eff2) for (src, eff2) in options
                  if src.card.card_id == "ST13-003"]
    assert len(luffy_opts) == 1
    fire_activate_main(st, me, opp, *luffy_opts[0])

    assert st.pending_choice is not None, "人間で 手札捨てコスト modal が立たない"
    assert st.pending_choice.get("kind") == "activate_main_discard_pick", \
        f"kind が activate_main_discard_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 手札 idx 0 (ナミ) を捨てる
    _drain(st)
    assert len(me.life) == 2, "承諾後 cost5 キャラ 2 枚がライフに加わっていない"


# --------------------------------------------------------------------------- #
#  ST13-004 エドワード・ニューゲート (CHARACTER 黄 cost6 power7000):
#    【登場時】自分のデッキの上から1枚をライフの上に加える。その後、自分のライフすべてを見て、
#    1枚を自分のデッキの上に置き、ライフを好きな順番で置く。
# --------------------------------------------------------------------------- #
def test_st13_004_on_play_put_top_to_life_and_scry_ai():
    """【登場時】デッキ上1枚をライフへ → ライフ全部見て価値最大1枚をデッキ上へ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    top_card = repo.get(SANJI)  # power3000 (= NAMI power2000 より価値大)
    me.deck = [top_card] + [repo.get(SANJI)] * 20
    me.life = [repo.get(NAMI)]  # 既存ライフ 1 枚 (低価値)
    life_before = len(me.life)

    eff = _eff(overlay, "ST13-004", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST13-004"), sickness=True))

    # put_top_to_life(+1) → scry で 価値最大 1 枚をデッキ上へ(-1) = ライフ枚数 不変
    assert len(me.life) == life_before, \
        f"ライフ枚数が put+scry で不変になっていない: {len(me.life)}"
    # 価値最大 (= サンジ power3000) がデッキトップに置かれる
    assert me.deck[0].card_id == SANJI, \
        f"scry で価値最大カードがデッキ上に置かれていない: {me.deck[0].card_id}"


def test_st13_004_on_play_scry_human_reorder():
    """人間 + ライフ >= 2 → scry_life_reorder modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(SANJI)] + [repo.get(NAMI)] * 20
    me.life = [repo.get(NAMI)]  # put_top_to_life 後に 2 枚 → scry modal

    eff = _eff(overlay, "ST13-004", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST13-004"), sickness=True))

    assert st.pending_choice is not None, "人間で scry_life_reorder modal が立たない"
    assert st.pending_choice.get("kind") == "scry_life_reorder", \
        f"kind が scry_life_reorder でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0, 1])  # 並び順 (1枚目をデッキへ)
    _drain(st, [0])
    assert st.pending_choice is None, "解決後も modal が残る"


# --------------------------------------------------------------------------- #
#  ST13-008 サボ (CHARACTER 黄 cost5 power6000):
#    【登場時】自分のライフの上か下から1枚をトラッシュに置くことができる：
#    相手のコスト5以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_st13_008_on_play_optional_cost_ko_ai():
    """【登場時】ライフ1枚をトラッシュ (任意コスト) → 相手 cost5以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(NAMI)]  # 支払いライフ 1 枚
    me.trash = []
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 (<=5)
    opp.characters = [victim]

    eff = _eff(overlay, "ST13-008", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST13-008"), sickness=True))
    _drain(st, [0])

    assert victim not in opp.characters, "相手の cost5以下キャラが KO されていない"
    assert len(me.life) == 0, "コストでライフ1枚がトラッシュへ移っていない"
    assert len(me.trash) == 1, "支払ったライフがトラッシュにない"


def test_st13_008_on_play_human_optional_cost_confirm():
    """人間 actor: 任意コストは optional_cost_confirm modal が立ち、 pay で相手を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(NAMI)]
    victim = InPlay.of(repo.get(SANJI), sickness=False)  # cost2 (<=5) 単体
    opp.characters = [victim]

    eff = _eff(overlay, "ST13-008", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("ST13-008"), sickness=True))

    assert st.pending_choice is not None, "人間で任意コスト modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # pay
    _drain(st, [0])
    assert victim not in opp.characters, "承諾後 相手の cost5以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  ST13-009 シャンクス (CHARACTER 黄 cost7 power7000):
#    【登場時】自分の表向きのライフ1枚を裏向きにできる：相手の手札が7枚以上ある場合、
#    相手のライフの上から1枚までをトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_st13_009_on_play_mill_opp_life_ai():
    """【登場時】相手手札7枚以上 → 相手ライフ上から1枚をトラッシュへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get(NAMI)] * 7  # 相手手札 7 枚 (= 条件成立)
    opp.life = [repo.get(SANJI)] * 3
    opp.trash = []
    life_before = len(opp.life)

    eff = _eff(overlay, "ST13-009", "on_play")
    assert eff.get("if", {}).get("opp_hand_count_ge") == 7, \
        "overlay の 条件 opp_hand_count_ge=7 が無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST13-009"), sickness=True))

    assert len(opp.life) == life_before - 1, \
        f"相手ライフが1枚減っていない: {len(opp.life)} (before {life_before})"
    assert len(opp.trash) == 1, "相手ライフ上の1枚がトラッシュへ移っていない"
