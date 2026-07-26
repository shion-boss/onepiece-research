# -*- coding: utf-8 -*-
"""OP09 弾 効果 回帰テスト バックフィル (自動生成 wave 095):
OP09-045 / OP09-046 / OP09-047 / OP09-048 / OP09-050 /
OP09-051 / OP09-052 / OP09-053 / OP09-056 / OP09-057 の 10 枚
(青 クロスギルド/バギー海賊団 サーチ・登場・KO耐性・デッキ下バウンス系)。

目的 (= test_backfill_auto_001〜094.py と同一方針):
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
_LEADER_CROSSGUILD = "OP09-042"  # バギー (leader、 四皇/クロスギルド)
_CG_ALBIDA = "EB03-021"          # アルビダ (CHARACTER cost4 クロスギルド)
_RICHIE = "OP09-054"             # リッチー (CHARACTER cost2 動物/クロスギルド)
_BLUE_EVENT = "OP09-057"         # クロスギルド (EVENT cost1 青)
_BAGGY_C = "OP09-051"            # バギー (CHARACTER cost10 四皇/クロスギルド、 name=バギー)
_COST5 = "OP09-045"              # カバジ (CHARACTER cost5、 cost5以上パディング用)
_FILLER = "OP01-013"             # サンジ cost2 power3000 (vanilla、 埋め用)
_SMALL = "OP01-016"              # ナミ cost1 power2000 (vanilla)


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


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op09_wave095_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP09-045", "OP09-046", "OP09-047", "OP09-048", "OP09-050",
           "OP09-051", "OP09-052", "OP09-053", "OP09-056", "OP09-057"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP09-045 カバジ: 自分のキャラに「バギー」か「モージ」がいる場合、
#                   このキャラはバトルでKOされない (静的 = battle_ko_immune_static)
# --------------------------------------------------------------------------- #
def test_op09_045_kabaji_static_ko_immune_with_baggy():
    """自キャラに バギー がいる → カバジ に battle_ko_immune_static が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    kabaji = InPlay.of(repo.get("OP09-045"), sickness=False)
    baggy = InPlay.of(repo.get(_BAGGY_C), sickness=False)  # name=バギー
    me.characters = [kabaji, baggy]

    eff = _eff(overlay, "OP09-045", "on_attached_don")
    assert eff.get("if", {}).get("self_chara_filtered_count_ge", {}) \
        .get("filter", {}).get("name_in") == ["バギー", "モージ"], \
        "overlay の 条件 (name_in バギー/モージ) が想定と違う"

    evaluate_static_effects(st, overlay)
    assert kabaji.battle_ko_immune_static is True, \
        "バギー在場で カバジ に バトルKO耐性 が立っていない"


def test_op09_045_kabaji_static_no_immune_without_baggy_moji():
    """自キャラに バギー/モージ がいない → 耐性は立たない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    kabaji = InPlay.of(repo.get("OP09-045"), sickness=False)
    other = InPlay.of(repo.get(_FILLER), sickness=False)  # 非 バギー/モージ
    me.characters = [kabaji, other]

    evaluate_static_effects(st, overlay)
    assert kabaji.battle_ko_immune_static is False, \
        "バギー/モージ 不在なのに バトルKO耐性 が立ってはいけない"


# --------------------------------------------------------------------------- #
#  OP09-046 クロコダイル: 【登場時】手札からコスト5以下の クロスギルド/B・W
#                        キャラ1枚までを 登場させる
# --------------------------------------------------------------------------- #
def test_op09_046_crocodile_on_play_play_from_hand_ai():
    """【登場時】手札の コスト5以下 クロスギルド キャラ (アルビダ) を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_CG_ALBIDA)]  # クロスギルド cost4

    chars_before = len(me.characters)
    eff = _eff(overlay, "OP09-046", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-046"), sickness=True))
    assert any(c.card.card_id == _CG_ALBIDA for c in me.characters), \
        "手札から クロスギルド キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場でキャラが1体増えるべき"


def test_op09_046_crocodile_on_play_human_pick():
    """人間 + 手札に該当 複数 → play_from_hand modal が立ち resolve で登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # クロスギルド cost5以下 を 2 種 (アルビダ / リッチー)
    me.hand = [repo.get(_CG_ALBIDA), repo.get(_RICHIE)]

    eff = _eff(overlay, "OP09-046", "on_play")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP09-046"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.card_id in (_CG_ALBIDA, _RICHIE) for c in me.characters), \
        "人間が選んだ クロスギルド キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP09-047 光月おでん: 【ダブルアタック】【KO時】カード2枚を引き、自分の手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_op09_047_oden_on_ko_draw2_discard1_ai():
    """【KO時】2枚引いて1枚捨てる → 手札 net +1、 デッキ -2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    eff = _eff(overlay, "OP09-047", "on_ko")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == hand_before + 2 - 1, \
        f"手札 net (+2 -1) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, \
        f"デッキが2枚減っていない: {len(me.deck)}"


# --------------------------------------------------------------------------- #
#  OP09-048 ジュラキュール・ミホーク: 【ブロッカー】【登場時】カード2枚を引き、
#                                      自分の手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_op09_048_mihawk_on_play_draw2_discard1_ai():
    """【登場時】2枚引いて1枚捨てる → 手札 net +1、 デッキ -2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10

    hand_before = len(me.hand)
    deck_before = len(me.deck)
    eff = _eff(overlay, "OP09-048", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP09-048"), sickness=True))
    assert len(me.hand) == hand_before + 2 - 1, \
        f"手札 net (+2 -1) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, \
        f"デッキが2枚減っていない: {len(me.deck)}"


# --------------------------------------------------------------------------- #
#  OP09-050 ナミ: 【アタック時】デッキ上5枚から 青のイベント1枚までを公開手札
#                → 残りデッキ下
# --------------------------------------------------------------------------- #
def test_op09_050_nami_on_attack_search_blue_event_ai():
    """【アタック時】上5枚に 青のイベント → 手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_BLUE_EVENT)] + [repo.get(_FILLER)] * 20  # 青 EVENT を上に
    me.hand = []

    search_prim = _eff(overlay, "OP09-050", "on_attack")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-050"), sickness=False))
    assert any(c.card_id == _BLUE_EVENT for c in me.hand), \
        "デッキ上5枚から 青のイベントが手札に加わっていない"


def test_op09_050_nami_on_attack_search_human_pick():
    """人間 + 上5枚に 青イベント 複数 → search_top_n modal が立ち resolve で手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_BLUE_EVENT), repo.get(_FILLER), repo.get(_BLUE_EVENT)] \
        + [repo.get(_FILLER)] * 15
    me.hand = []

    search_prim = _eff(overlay, "OP09-050", "on_attack")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-050"), sickness=False))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id == _BLUE_EVENT for c in me.hand), \
        "人間が選んだ 青のイベントが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP09-051 バギー: 【登場時】相手のキャラ1枚までを 持ち主のデッキの下に置く。
#          その後、自分のコスト5以上のキャラが5枚いない場合、このキャラをデッキの下に置く
# --------------------------------------------------------------------------- #
def test_op09_051_baggy_on_play_return_opp_to_deck_bottom_ai():
    """【登場時】相手キャラ1体を 相手デッキ下に置く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    opp.characters = [victim]
    opp.deck = []

    return_prim = _eff(overlay, "OP09-051", "on_play")["do"][0]
    execute_effect(return_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-051"), sickness=True))
    assert victim not in opp.characters, "相手キャラが場から消えていない"
    assert any(c.card_id == _FILLER for c in opp.deck), \
        "相手キャラが相手デッキに戻っていない"


def test_op09_051_baggy_on_play_self_return_when_not_5_cost5():
    """その後: 自コスト5以上が5枚いない → バギー自身を自デッキ下に置く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    baggy = InPlay.of(repo.get("OP09-051"), sickness=True)
    me.characters = [baggy]  # コスト5以上は バギー のみ = 1枚 (<5)
    me.deck = []

    self_prim = _eff(overlay, "OP09-051", "on_play")["do"][1]
    execute_effect(self_prim, st, me, opp, baggy)
    assert baggy not in me.characters, \
        "コスト5以上5枚未満なのに バギー が場に残っている"
    assert any(c.card_id == "OP09-051" for c in me.deck), \
        "バギー が自デッキ下に戻っていない"


def test_op09_051_baggy_on_play_self_stays_when_5_cost5():
    """その後: 自コスト5以上が5枚いる → バギー自身は場に残る (デッキ下戻し不発)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    baggy = InPlay.of(repo.get("OP09-051"), sickness=True)  # cost10 (5以上)
    # バギー + カバジ4体 = コスト5以上 が 5 枚
    fillers5 = [InPlay.of(repo.get(_COST5), sickness=False) for _ in range(4)]
    me.characters = [baggy] + fillers5
    me.deck = []

    self_prim = _eff(overlay, "OP09-051", "on_play")["do"][1]
    execute_effect(self_prim, st, me, opp, baggy)
    assert baggy in me.characters, \
        "コスト5以上5枚在場なら バギー は場に残るべき"


def test_op09_051_baggy_on_play_return_opp_human_pick():
    """人間 + 相手キャラ 複数 → return_to_deck_bottom の target_pick modal で 1 体を選ぶ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)
    b = InPlay.of(repo.get(_SMALL), sickness=False)
    opp.characters = [a, b]
    opp.deck = []

    return_prim = _eff(overlay, "OP09-051", "on_play")["do"][0]
    execute_effect(return_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-051"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
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
    assert b not in opp.characters, "人間が選んだ相手キャラが場から消えていない"
    assert a in opp.characters, "選ばなかった相手キャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP09-052 マルコ: 【相手のターン中】手札1枚を捨てられる：このキャラが相手の効果で
#          KOされた時、このキャラカードをトラッシュからレストで登場させる (play_from_trash)
# --------------------------------------------------------------------------- #
def test_op09_052_marco_play_from_trash_rested_ai():
    """トラッシュの マルコ を レストで登場させる (do の play_from_trash、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP09-052")]  # トラッシュに マルコ 1 枚
    me.characters = []

    play_prim = _eff(overlay, "OP09-052", "on_ko")["do"][0]
    execute_effect(play_prim, st, me, opp, None)
    played = [c for c in me.characters if c.card.card_id == "OP09-052"]
    assert len(played) == 1, "トラッシュから マルコ が登場していない"
    assert played[0].rested is True, "マルコ は レスト で登場するべき"


def test_op09_052_marco_play_from_trash_human_pick():
    """人間 + トラッシュに マルコ 複数 → play_from_trash modal が立ち resolve で 1 体登場。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP09-052"), repo.get("OP09-052")]  # マルコ 2 枚
    me.characters = []

    play_prim = _eff(overlay, "OP09-052", "on_ko")["do"][0]
    execute_effect(play_prim, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_trash modal が立たない"
    assert "play_from_trash" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_trash 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.card_id == "OP09-052" for c in me.characters), \
        "人間が選んだ マルコ が登場していない"


# --------------------------------------------------------------------------- #
#  OP09-053 モージ: 【登場時】デッキ上5枚から「リッチー」1枚公開手札 → 残りデッキ下、
#          その後 自分の手札から「リッチー」1枚までを 登場させる
# --------------------------------------------------------------------------- #
def test_op09_053_moji_on_play_search_richie_ai():
    """【登場時】上5枚に リッチー → 手札に加える (search 部、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_RICHIE)] + [repo.get(_FILLER)] * 20
    me.hand = []

    search_prim = _eff(overlay, "OP09-053", "on_play")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-053"), sickness=True))
    assert any(c.card_id == _RICHIE for c in me.hand), \
        "デッキ上5枚から リッチー が手札に加わっていない"


def test_op09_053_moji_on_play_play_richie_from_hand_ai():
    """【登場時】手札の リッチー を 登場させる (play_from_hand 部、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_RICHIE)]

    play_prim = _eff(overlay, "OP09-053", "on_play")["do"][1]
    execute_effect(play_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-053"), sickness=True))
    assert any(c.card.card_id == _RICHIE for c in me.characters), \
        "手札から リッチー が登場していない"


def test_op09_053_moji_on_play_search_human_pick():
    """人間 + 上5枚に リッチー 複数 → search_top_n modal が立ち resolve で手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_RICHIE), repo.get(_FILLER), repo.get(_RICHIE)] \
        + [repo.get(_FILLER)] * 15
    me.hand = []

    search_prim = _eff(overlay, "OP09-053", "on_play")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-053"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id == _RICHIE for c in me.hand), \
        "人間が選んだ リッチー が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP09-056 Mr.3(ギャルディーノ): 【登場時】デッキ上4枚から Mr.3以外の
#          クロスギルド/B・W カード1枚公開手札 → 残りデッキ下
# --------------------------------------------------------------------------- #
def test_op09_056_mr3_on_play_search_ai():
    """【登場時】上4枚に クロスギルド (アルビダ) → 手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_CG_ALBIDA)] + [repo.get(_FILLER)] * 20
    me.hand = []

    search_prim = _eff(overlay, "OP09-056", "on_play")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-056"), sickness=True))
    assert any(c.card_id == _CG_ALBIDA for c in me.hand), \
        "デッキ上4枚から クロスギルド カードが手札に加わっていない"


def test_op09_056_mr3_on_play_search_human_pick():
    """人間 + 上4枚に クロスギルド 複数 → search_top_n modal が立ち resolve で手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_CG_ALBIDA), repo.get(_FILLER), repo.get(_RICHIE)] \
        + [repo.get(_FILLER)] * 15
    me.hand = []

    search_prim = _eff(overlay, "OP09-056", "on_play")["do"][0]
    execute_effect(search_prim, st, me, opp,
                   InPlay.of(repo.get("OP09-056"), sickness=True))
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id in (_CG_ALBIDA, _RICHIE) for c in me.hand), \
        "人間が選んだ クロスギルド カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP09-057 クロスギルド (EVENT): 【メイン】デッキ上4枚から クロスギルド 1枚公開手札
#          → 残りデッキ下。 【トリガー】この【メイン】効果を発動する
# --------------------------------------------------------------------------- #
def test_op09_057_crossguild_main_search_ai():
    """【メイン】上4枚に クロスギルド → 手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_CG_ALBIDA)] + [repo.get(_FILLER)] * 20
    me.hand = []

    search_prim = _eff(overlay, "OP09-057", "main")["do"][0]
    execute_effect(search_prim, st, me, opp, None)
    assert any(c.card_id == _CG_ALBIDA for c in me.hand), \
        "デッキ上4枚から クロスギルド カードが手札に加わっていない"


def test_op09_057_crossguild_trigger_fires_main_ai():
    """【トリガー】fire_self_effect で【メイン】(search) を再発火 → 手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_CG_ALBIDA)] + [repo.get(_FILLER)] * 20
    me.hand = []
    # fire_self_effect は self_inplay=None 時 state.current_source_card_id を参照する
    st.current_source_card_id = "OP09-057"

    trig_prim = _eff(overlay, "OP09-057", "trigger")["do"][0]
    execute_effect(trig_prim, st, me, opp, None)
    assert any(c.card_id == _CG_ALBIDA for c in me.hand), \
        "トリガーからの メイン効果 再発火で クロスギルド が手札に加わっていない"


def test_op09_057_crossguild_main_search_human_pick():
    """人間 + 上4枚に クロスギルド 複数 → search_top_n modal が立ち resolve で手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_CROSSGUILD, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_CG_ALBIDA), repo.get(_FILLER), repo.get(_RICHIE)] \
        + [repo.get(_FILLER)] * 15
    me.hand = []

    search_prim = _eff(overlay, "OP09-057", "main")["do"][0]
    execute_effect(search_prim, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id in (_CG_ALBIDA, _RICHIE) for c in me.hand), \
        "人間が選んだ クロスギルド カードが手札に加わっていない"
