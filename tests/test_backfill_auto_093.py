# -*- coding: utf-8 -*-
"""OP09 弾 効果 回帰テスト バックフィル (自動生成 wave 093):
OP09-023 / OP09-024 / OP09-025 / OP09-026 / OP09-027 /
OP09-028 / OP09-029 / OP09-030 / OP09-031 / OP09-032 の 10 枚
(緑 ODYSSEY 系: ドンアクティブ / レスト参照 grind / KO / 復活 / untap / ブロッカー)。

目的 (= test_backfill_auto_001〜092.py と同一方針):
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
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_ODYSSEY = "OP09-022"   # リム (leader、 特徴 ODYSSEY、 power5000)
_LEADER_NEUTRAL = "OP01-001"   # モンキー・D・ルフィ (中立 leader、 power5000)
_ODY_BROOK = "OP10-035"        # ブルック (CHARACTER cost3 ODYSSEY/麦わらの一味、 power?)
_ODY_ROSI = "OP09-032"         # ドンキホーテ・ロシナンテ (CHARACTER cost3 ODYSSEY/海軍…)
_OPP_C4 = "PRB02-006"          # ロロノア・ゾロ cost4 power4000 (cost5 以下 KO 対象)
_OPP_SMALL = "OP01-016"        # ナミ cost1 power2000 (小型 KO 対象)
_FILLER = "OP01-013"           # サンジ cost2 power3000 (デッキ/手札/場 埋め用、 vanilla)


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


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]


def _rested(repo, cid, n):
    """レストの vanilla キャラ n 体 (レスト参照条件のパディング用)。"""
    out = []
    for _ in range(n):
        c = InPlay.of(repo.get(cid), sickness=False)
        c.rested = True
        out.append(c)
    return out


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op09_wave093_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP09-023", "OP09-024", "OP09-025", "OP09-026", "OP09-027",
           "OP09-028", "OP09-029", "OP09-030", "OP09-031", "OP09-032"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP09-023 アディオ:
#   【登場時】自リーダー ODYSSEY なら 自ドン3枚までアクティブに
#   【相手のアタック時】【ターン1回】ドン1レスト → 自リーダー/キャラ1枚 +2000
# --------------------------------------------------------------------------- #
def test_op09_023_adio_on_play_untap_don_ai():
    """【登場時】ODYSSEY リーダー → レストドン3枚がアクティブに (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)  # ODYSSEY leader → 条件成立
    me, opp = st.players[0], st.players[1]
    me.don_rested, me.don_active = 5, 0

    eff = _eff(overlay, "OP09-023", "on_play")
    assert eff.get("if", {}).get("leader_feature") == "ODYSSEY", \
        "on_play の条件 leader_feature=ODYSSEY が overlay に無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-023"), sickness=True))

    assert me.don_active == 3 and me.don_rested == 2, \
        f"レストドン3枚がアクティブ化されていない: active={me.don_active} rested={me.don_rested}"


def test_op09_023_adio_opp_attack_pump_ai():
    """【相手のアタック時】ドン1レスト → 自リーダー(既定) +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active, me.don_rested = 3, 0

    lp = me.leader.power
    eff = _eff(overlay, "OP09-023", "opp_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-023"), sickness=False))

    assert me.leader.power == lp + 2000, \
        f"相手アタック時 自リーダー +2000 が反映されていない: {me.leader.power}"
    assert me.don_active == 2 and me.don_rested == 1, \
        f"コストでドン1枚がレストされるべき: active={me.don_active} rested={me.don_rested}"


def test_op09_023_adio_opp_attack_human_pick():
    """人間 + 自リーダー/キャラ 複数 → 任意コスト確認 → target_pick で +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    friend = InPlay.of(repo.get(_FILLER), sickness=False)  # power 3000
    me.characters = [friend]

    eff = _eff(overlay, "OP09-023", "opp_attack")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-023"), sickness=False))

    # 1) 任意コストの支払い確認 modal
    assert st.pending_choice is not None, "人間 optional で確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 支払う

    # 2) +2000 の対象選択 (リーダー + キャラ = 2 件)
    assert st.pending_choice is not None and \
        st.pending_choice.get("kind") == "target_pick", \
        f"target_pick modal が立たない: {st.pending_choice}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    fi = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    fb = friend.power
    resolve_pending_choice(st, [fi])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [fi])
        guard += 1
    assert friend.power == fb + 2000, "人間が選んだキャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP09-024 ウソップ: 【登場時】自レストキャラ2枚以上で カード2枚引き 手札2枚捨てる
# --------------------------------------------------------------------------- #
def test_op09_024_usopp_on_play_draw2_discard2_ai():
    """【登場時】レストキャラ2枚以上 → 2 ドロー + 手札2枚ランダム捨て (net ±0)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = _rested(repo, _FILLER, 2)  # レストキャラ 2 (条件成立)
    me.hand = [repo.get(_FILLER), repo.get(_OPP_SMALL)]
    me.deck = [repo.get(_FILLER)] * 10

    eff = _eff(overlay, "OP09-024", "on_play")
    assert eff.get("if", {}).get("self_rested_chara_count_ge") == 2, \
        "on_play の条件 self_rested_chara_count_ge=2 が overlay に無い"
    hand_before, deck_before = len(me.hand), len(me.deck)
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-024"), sickness=True))

    assert len(me.hand) == hand_before, \
        f"2 ドロー + 2 捨て で 手札 net ±0 のはず: {len(me.hand)} (before {hand_before})"
    assert len(me.deck) == deck_before - 2, \
        f"2 ドローでデッキが 2 枚減るべき: {len(me.deck)} (before {deck_before})"


# --------------------------------------------------------------------------- #
#  OP09-025 クロコダイル: 自リーダー ODYSSEY なら リーダーとのバトルでKOされない (静的)
# --------------------------------------------------------------------------- #
def test_op09_025_crocodile_static_ko_immune_vs_leader():
    """静的: ODYSSEY リーダー下では battle_ko_immune_vs_leader が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    croc = InPlay.of(repo.get("OP09-025"), sickness=False)
    me.characters = [croc]
    evaluate_static_effects(st, overlay)
    assert croc.battle_ko_immune_vs_leader is True, \
        "ODYSSEY リーダー下で リーダーバトルKO耐性が立っていない"


def test_op09_025_crocodile_static_no_immune_off_odyssey():
    """自リーダーが ODYSSEY を持たなければ 耐性は立たない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_NEUTRAL, overlay)  # 非 ODYSSEY leader
    me, opp = st.players[0], st.players[1]
    croc = InPlay.of(repo.get("OP09-025"), sickness=False)
    me.characters = [croc]
    evaluate_static_effects(st, overlay)
    assert croc.battle_ko_immune_vs_leader is False, \
        "非 ODYSSEY リーダー下で 耐性が立ってはいけない"


# --------------------------------------------------------------------------- #
#  OP09-026 サカズキ: 【登場時】自レストキャラ2枚以上で 相手コスト5以下1体KO
# --------------------------------------------------------------------------- #
def test_op09_026_sakazuki_on_play_ko_ai():
    """【登場時】レストキャラ2枚以上 → 相手コスト5以下キャラ1体を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = _rested(repo, _FILLER, 2)
    victim = InPlay.of(repo.get(_OPP_C4), sickness=False)  # cost4 (5以下)
    opp.characters = [victim]

    eff = _eff(overlay, "OP09-026", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-026"), sickness=True))
    assert victim not in opp.characters, "相手コスト5以下キャラが KO されていない"


def test_op09_026_sakazuki_on_play_ko_human_pick():
    """人間 + 相手コスト5以下 複数 → target_pick modal で 1 体を KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = _rested(repo, _FILLER, 2)
    a = InPlay.of(repo.get(_OPP_C4), sickness=False)     # cost4
    b = InPlay.of(repo.get(_OPP_SMALL), sickness=False)  # cost1
    opp.characters = [a, b]

    eff = _eff(overlay, "OP09-026", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-026"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が 2 体でない: {len(cands)}"

    bi = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [bi])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [bi])
        guard += 1
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP09-027 サボ: 【アタック時】【ターン1回】自レストキャラ3枚以上で 1 ドロー
# --------------------------------------------------------------------------- #
def test_op09_027_sabo_on_attack_draw_ai():
    """【アタック時】レストキャラ3枚以上 → 1 ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = _rested(repo, _FILLER, 3)  # レストキャラ 3 (条件成立)
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    eff = _eff(overlay, "OP09-027", "on_attack")
    assert eff.get("if", {}).get("self_rested_chara_count_ge") == 3, \
        "on_attack の条件 self_rested_chara_count_ge=3 が overlay に無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-027"), sickness=False))
    assert len(me.hand) == 1, f"アタック時 1 ドローが起きていない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP09-028 サンジ: 【KO時】ライフ上下1枚を手札に (任意コスト) →
#                   自トラッシュから ODYSSEY/麦 cost4以下 1枚をレスト登場
# --------------------------------------------------------------------------- #
def test_op09_028_sanji_on_ko_revive_ai():
    """【KO時】ライフ1枚を手札に → トラッシュの ODYSSEY/麦 cost4以下 をレスト登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER), repo.get(_OPP_SMALL)]  # ライフ 2
    me.trash = [repo.get(_ODY_BROOK)]  # ブルック cost3 ODYSSEY/麦
    me.hand = []

    life_before, hand_before = len(me.life), len(me.hand)
    eff = _eff(overlay, "OP09-028", "on_ko")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)  # KO 済 = self_inplay None

    assert len(me.life) == life_before - 1, "ライフ1枚が手札に加えられていない"
    assert len(me.hand) == hand_before + 1, "ライフ1枚分 手札が増えていない"
    played = [c for c in me.characters if c.card.card_id == _ODY_BROOK]
    assert played, "トラッシュから ODYSSEY/麦 キャラが登場していない"
    assert played[0].rested is True, "登場したキャラはレストのはず"


def test_op09_028_sanji_on_ko_human_confirm():
    """人間 actor: 任意コスト確認 modal が立ち、 承諾で 復活まで流せる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER), repo.get(_OPP_SMALL)]
    me.trash = [repo.get(_ODY_BROOK), repo.get("OP09-024")]  # 復活候補 2
    me.hand = []

    eff = _eff(overlay, "OP09-028", "on_ko")
    execute_effect(eff["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 optional で確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    guard = 0
    while st.pending_choice is not None and guard < 8:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.card_id in (_ODY_BROOK, "OP09-024")
               for c in me.characters), \
        "人間承諾後 トラッシュから ODYSSEY/麦 キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP09-029 チョッパー: 【自分のターン終了時】自 ODYSSEY cost4以下 1枚をアクティブに
# --------------------------------------------------------------------------- #
def test_op09_029_chopper_end_of_turn_untap_ai():
    """【ターン終了時】レストの ODYSSEY cost4以下キャラをアクティブ化 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get(_ODY_BROOK), sickness=False)  # ODYSSEY cost3
    target.rested = True
    chopper = InPlay.of(repo.get("OP09-029"), sickness=False)
    me.characters = [chopper, target]

    eff = _eff(overlay, "OP09-029", "end_of_turn")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, chopper)
    assert target.rested is False, "ODYSSEY キャラがアクティブ化されていない"


def test_op09_029_chopper_end_of_turn_human_pick():
    """人間 + ODYSSEY cost4以下 複数 → target_pick modal で 1 枚アクティブに。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    t1 = InPlay.of(repo.get(_ODY_BROOK), sickness=False)  # ODYSSEY cost3
    t1.rested = True
    chopper = InPlay.of(repo.get("OP09-029"), sickness=False)  # 自身も ODYSSEY cost3
    me.characters = [chopper, t1]

    eff = _eff(overlay, "OP09-029", "end_of_turn")
    execute_effect(eff["do"][0], st, me, opp, chopper)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    ti = next(i for i, c in enumerate(cands) if c["iid"] == t1.instance_id)
    resolve_pending_choice(st, [ti])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [ti])
        guard += 1
    assert t1.rested is False, "人間が選んだ ODYSSEY キャラがアクティブ化されていない"


# --------------------------------------------------------------------------- #
#  OP09-030 トラファルガー・ロー: 【登場時】自キャラ1枚を手札に戻す (任意コスト) →
#            手札から「ロー」以外の ODYSSEY cost3以下 1枚を登場
# --------------------------------------------------------------------------- #
def test_op09_030_law_on_play_bounce_play_ai():
    """【登場時】自キャラ1枚戻し → 手札の ODYSSEY cost3以下キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    law = InPlay.of(repo.get("OP09-030"), sickness=False)
    sacrifice = InPlay.of(repo.get(_FILLER), sickness=False)  # 戻すコスト候補
    me.characters = [law, sacrifice]
    me.hand = [repo.get(_ODY_ROSI)]  # ロシナンテ cost3 ODYSSEY
    me.deck = [repo.get(_FILLER)] * 10

    eff = _eff(overlay, "OP09-030", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, law)

    assert any(c.card.card_id == _ODY_ROSI for c in me.characters), \
        "手札から ODYSSEY cost3以下キャラ (ロシナンテ) が登場していない"
    assert any(c.card_id == _FILLER for c in me.hand), \
        "コストで戻したキャラが手札に無い"


def test_op09_030_law_on_play_human_flow():
    """人間 actor: 任意コスト確認 → 戻すキャラ選択 → 登場先選択 の modal 連鎖を流せる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    law = InPlay.of(repo.get("OP09-030"), sickness=False)
    sacrifice = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [law, sacrifice]
    me.hand = [repo.get(_ODY_ROSI), repo.get("OP09-029")]  # ODYSSEY cost3 x2
    me.deck = [repo.get(_FILLER)] * 10

    eff = _eff(overlay, "OP09-030", "on_play")
    execute_effect(eff["do"][0], st, me, opp, law)

    assert st.pending_choice is not None, "人間 optional で確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    guard = 0
    while st.pending_choice is not None and guard < 8:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.card_id in (_ODY_ROSI, "OP09-029") for c in me.characters), \
        "人間承諾後 ODYSSEY cost3以下キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP09-031 ドフラミンゴ: 【ブロッカー】【自分のターン終了時】
#            自レストキャラ2枚以上で このキャラをアクティブに
# --------------------------------------------------------------------------- #
def test_op09_031_doflamingo_end_of_turn_self_untap_ai():
    """【ターン終了時】レストキャラ2枚以上 → 自身をアクティブに。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    dofla = InPlay.of(repo.get("OP09-031"), sickness=False)
    dofla.rested = True
    me.characters = [dofla] + _rested(repo, _FILLER, 2)  # 他レストキャラ 2

    eff = _eff(overlay, "OP09-031", "end_of_turn")
    assert eff.get("if", {}).get("self_rested_chara_count_ge") == 2, \
        "end_of_turn の条件 self_rested_chara_count_ge=2 が overlay に無い"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, dofla)
    assert dofla.rested is False, "ターン終了時に自身がアクティブ化されていない"


# --------------------------------------------------------------------------- #
#  OP09-032 ロシナンテ: 【ブロッカー】【相手のアタック時】【ターン1回】
#            このキャラをアクティブに
# --------------------------------------------------------------------------- #
def test_op09_032_rosinante_opp_attack_self_untap_ai():
    """【相手のアタック時】自身 (ブロッカー) をアクティブに戻す。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODYSSEY, overlay)
    me, opp = st.players[0], st.players[1]
    rosi = InPlay.of(repo.get("OP09-032"), sickness=False)
    rosi.rested = True  # ブロック後を想定
    me.characters = [rosi]

    eff = _eff(overlay, "OP09-032", "opp_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, rosi)
    assert rosi.rested is False, "相手アタック時に自身がアクティブ化されていない"
