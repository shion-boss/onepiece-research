# -*- coding: utf-8 -*-
"""OP02 弾 効果 回帰テスト バックフィル (自動生成 wave 029):
OP02-034 / OP02-035 / OP02-036 / OP02-037 / OP02-040 / OP02-041 /
OP02-042 / OP02-044 / OP02-045 / OP02-046 の 10 枚
(= 緑 麦わらの一味/FILM/ミンク族/ワノ国 の 登場時 展開・レスト・KO・カウンター系)。

目的 (= test_backfill_auto_001〜028.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / サーチ / 任意コスト を 持つカードは 人間 actor で pending_choice が
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


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


# GREEN = 緑 ワノ国 リーダー (錦えもん)。 対象カードは全て緑なので realistic な文脈。
GREEN_LEADER = "OP02-025"


def _state(repo, overlay, human_idx=None, leader_id=GREEN_LEADER,
           opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める。"""
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
    """指定 card_id の overlay から when 一致の効果 (do 配列, eff dict) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        # ⚠ 2026-08-05: コロン後の条件を conditional / optional_cost_then の中へ移したため、
        #   目的の primitive が入れ子になっている。 平坦化して探す。
        def _flat(arr):
            out = []
            for _p in arr or []:
                if not isinstance(_p, dict):
                    continue
                if "conditional" in _p:
                    out += _flat((_p["conditional"] or {}).get("do"))
                elif "optional_cost_then" in _p:
                    out += _flat((_p["optional_cost_then"] or {}).get("effect"))
                else:
                    out.append(_p)
            return out
        for e in matches:
            if any(needle in prim for prim in _flat(e["do"])):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op02_wave29_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP02-034", "OP02-035", "OP02-036", "OP02-037", "OP02-040",
           "OP02-041", "OP02-042", "OP02-044", "OP02-045", "OP02-046"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP02-034 トニートニー・チョッパー: 【ドン!!×1】【アタック時】相手のコスト2以下の
#    キャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op02_034_chopper_attack_rest_cost_le2_ai():
    """アタック時 (ドン1ゲート): 相手のコスト2以下キャラをレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2 (<=2)
    opp.characters = [victim]

    do, eff = _do(overlay, "OP02-034", "on_attack")
    assert eff.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-034"), sickness=False))
    _drain_choices(st)

    assert victim.rested is True, "コスト2以下キャラがレストになっていない"


def test_op02_034_chopper_attack_no_target_cost3():
    """相手のコスト3キャラは コスト2以下の対象外 → レストにならない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP12-035"), sickness=False)  # cost3 (対象外)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-034", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-034"), sickness=False))
    _drain_choices(st)

    assert victim.rested is False, "コスト3キャラがレストされてはいけない (対象外)"


def test_op02_034_chopper_attack_rest_human_pick():
    """人間 + 相手コスト2以下キャラ 複数 → rest の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP02-034", "on_attack")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP02-034"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b.rested is True, "人間が選んだキャラがレストになっていない"
    assert a.rested is False, "選ばなかったキャラはレストされない"


# --------------------------------------------------------------------------- #
#  OP02-035 トラファルガー・ロー: 【起動メイン】①(ドンレスト) + このキャラを持ち主の
#    手札に戻す：自分の手札からコスト3のキャラ1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op02_035_law_activate_main_bounce_play_cost3_ai():
    """起動メイン: 自身を手札に戻し + ドン1レスト (コスト) → 手札からコスト3キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    law = InPlay.of(repo.get("OP02-035"), sickness=False)
    me.characters = [law]
    me.hand = [repo.get("OP12-035")]  # コスト3 キャラ (モーガン)
    me.don_active = 1
    me.don_rested = 0

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-035"]
    assert len(opts) == 1, f"OP02-035 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain_choices(st)

    # コスト: ロー自身が場から手札に戻る + ドン1レスト
    assert law not in me.characters, "コストで ロー が場から居なくなっていない"
    assert any(c.card_id == "OP02-035" for c in me.hand), \
        "コストで ロー が持ち主の手札に戻っていない"
    assert me.don_rested == 1, f"① コストで ドン1枚がレストされていない: {me.don_rested}"
    # 効果: 手札からコスト3キャラ (モーガン) を登場
    assert any(c.card.card_id == "OP12-035" for c in me.characters), \
        "手札からコスト3キャラが登場していない"


def test_op02_035_law_activate_main_human_play_pick():
    """人間 + 手札にコスト3キャラ 複数 → 登場先を選ぶ play_from_hand_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    law = InPlay.of(repo.get("OP02-035"), sickness=False)
    me.characters = [law]
    me.hand = [repo.get("OP12-035"), repo.get("EB01-025")]  # 2 種の コスト3 キャラ
    me.don_active = 1
    me.don_rested = 0

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP02-035"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[0])
    assert any(c.card.card_id in ("OP12-035", "EB01-025") for c in me.characters), \
        "人間が選んだコスト3キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP02-036 ナミ: 【登場時】/【アタック時】①：デッキ上3枚を見て、「ナミ」以外の
#    特徴《FILM》を持つカード1枚までを公開し手札に加える。残りをデッキの下へ。
# --------------------------------------------------------------------------- #
def test_op02_036_nami_on_play_search_film_ai():
    """登場時: デッキ上3枚から《FILM》カードを手札に加える (AI 自動)。
    デッキ先頭に ブルーノ (EB01-017, FILM) を仕込む。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("EB01-017")] + [repo.get("ST01-004")] * 29

    do, _ = _do(overlay, "OP02-036", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-036"), sickness=True))
    _drain_choices(st)

    assert any(c.card_id == "EB01-017" for c in me.hand), \
        "デッキ上3枚から《FILM》カードが手札に加わっていない"


def test_op02_036_nami_on_attack_search_film_ai():
    """アタック時: 同一効果 (デッキ上3枚から《FILM》を手札へ) が発火する (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("EB01-017")] + [repo.get("ST01-004")] * 29

    do, _ = _do(overlay, "OP02-036", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-036"), sickness=False))
    _drain_choices(st)

    assert any(c.card_id == "EB01-017" for c in me.hand), \
        "アタック時に《FILM》カードが手札に加わっていない"


def test_op02_036_nami_search_human_pick():
    """人間 + デッキ上3枚に《FILM》複数 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("EB01-017"), repo.get("EB03-002"), repo.get("ST01-004")] \
        + [repo.get("ST01-004")] * 27

    do, _ = _do(overlay, "OP02-036", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP02-036"), sickness=True))

    assert st.pending_choice is not None, "人間 + 候補ありで search_top_n modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    cards = st.pending_choice.get("cards", [])
    film_idx = next(c["idx"] for c in cards if c["card_id"] == "EB01-017")
    resolve_pending_choice(st, [film_idx])
    _drain_choices(st)
    assert any(c.card_id == "EB01-017" for c in me.hand), \
        "人間が選んだ《FILM》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP02-037 ニコ・ロビン: 【登場時】自分の手札からコスト2以下の《FILM》か
#    《麦わらの一味》を持つキャラ1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op02_037_robin_on_play_summon_cost_le2_ai():
    """登場時: 手札からコスト2以下の《FILM》/《麦わらの一味》キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP04-007")]  # サンジ cost1 麦わらの一味

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP02-037", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-037"), sickness=True))
    _drain_choices(st)

    assert len(me.characters) == chars_before + 1, "手札からキャラが登場していない"
    assert any(c.card.card_id == "OP04-007" for c in me.characters), \
        "コスト2以下の《麦わらの一味》キャラが登場していない"


def test_op02_037_robin_on_play_no_cost3_target():
    """手札がコスト3キャラのみなら コスト2以下の対象外 → 登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP13-034")]  # ブルック cost3 FILM/麦わら (コスト超過)

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP02-037", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-037"), sickness=True))
    _drain_choices(st)

    assert len(me.characters) == chars_before, \
        "コスト3キャラが コスト2以下の枠で登場してはいけない"


def test_op02_037_robin_on_play_human_pick():
    """人間 + 手札にコスト2以下の該当キャラ 複数 → play_from_hand_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP04-007"), repo.get("OP09-071")]  # 2 種 麦わら cost<=2

    do, _ = _do(overlay, "OP02-037", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP02-037"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[0])
    assert any(c.card.card_id in ("OP04-007", "OP09-071") for c in me.characters), \
        "人間が選んだキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP02-040 ブルック: 【登場時】自分の手札からコスト3以下の《FILM》か
#    《麦わらの一味》を持つキャラ1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op02_040_brook_on_play_summon_cost_le3_ai():
    """登場時: 手札からコスト3以下の《FILM》/《麦わらの一味》キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP09-071")]  # ニコ・ロビン cost2 麦わらの一味

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP02-040", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-040"), sickness=True))
    _drain_choices(st)

    assert len(me.characters) == chars_before + 1, "手札からキャラが登場していない"
    assert any(c.card.card_id == "OP09-071" for c in me.characters), \
        "コスト3以下の《麦わらの一味》キャラが登場していない"


def test_op02_040_brook_on_play_human_pick():
    """人間 + 手札にコスト3以下の該当キャラ 複数 → play_from_hand_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP04-007"), repo.get("OP09-071")]  # 2 種 麦わら cost<=3

    do, _ = _do(overlay, "OP02-040", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP02-040"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[0])
    assert any(c.card.card_id in ("OP04-007", "OP09-071") for c in me.characters), \
        "人間が選んだキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP02-041 モンキー・D・ルフィ: 【ブロッカー】【登場時】自分の手札からコスト4以下の
#    《FILM》か《麦わらの一味》を持つキャラ1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op02_041_luffy_on_play_summon_cost_le4_ai():
    """登場時: 手札からコスト4以下の《FILM》/《麦わらの一味》キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-043")]  # ゾロ cost4 FILM/麦わらの一味

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP02-041", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-041"), sickness=True))
    _drain_choices(st)

    assert len(me.characters) == chars_before + 1, "手札からキャラが登場していない"
    assert any(c.card.card_id == "OP02-043" for c in me.characters), \
        "コスト4以下の《FILM》キャラが登場していない"


def test_op02_041_luffy_on_play_human_pick():
    """人間 + 手札にコスト4以下の該当キャラ 複数 → play_from_hand_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-043"), repo.get("OP09-071")]  # cost4 + cost2 麦わら/FILM

    do, _ = _do(overlay, "OP02-041", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP02-041"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[0])
    assert any(c.card.card_id in ("OP02-043", "OP09-071") for c in me.characters), \
        "人間が選んだキャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP02-042 ヤマト: 【登場時】相手のコスト6以下のキャラ1枚までを、レストにする。
# --------------------------------------------------------------------------- #
def test_op02_042_yamato_on_play_rest_cost_le6_ai():
    """登場時: 相手のコスト6以下キャラをレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP02-043"), sickness=False)  # cost4 (<=6)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-042", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-042"), sickness=True))
    _drain_choices(st)

    assert victim.rested is True, "コスト6以下キャラがレストになっていない"


def test_op02_042_yamato_on_play_no_target_cost7():
    """相手のコスト7キャラは コスト6以下の対象外 → レストにならない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP02-041"), sickness=False)  # cost7 (対象外)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-042", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-042"), sickness=True))
    _drain_choices(st)

    assert victim.rested is False, "コスト7キャラがレストされてはいけない (対象外)"


def test_op02_042_yamato_on_play_rest_human_pick():
    """人間 + 相手コスト6以下キャラ 複数 → rest の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP02-043"), sickness=False)  # cost4
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP02-042", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP02-042"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b.rested is True, "人間が選んだキャラがレストになっていない"
    assert a.rested is False, "選ばなかったキャラはレストされない"


# --------------------------------------------------------------------------- #
#  OP02-044 ワンダ: 【登場時】自分の手札から「ワンダ」以外のコスト3以下の《ミンク族》
#    キャラ1枚までを、登場させる。
# --------------------------------------------------------------------------- #
def test_op02_044_wanda_on_play_summon_mink_ai():
    """登場時: 手札からコスト3以下の《ミンク族》キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP08-035")]  # BB cost2 ミンク族

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP02-044", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP02-044"), sickness=True))
    _drain_choices(st)

    assert len(me.characters) == chars_before + 1, "手札からキャラが登場していない"
    assert any(c.card.card_id == "OP08-035" for c in me.characters), \
        "コスト3以下の《ミンク族》キャラが登場していない"


def test_op02_044_wanda_on_play_human_pick():
    """人間 + 手札にコスト3以下の《ミンク族》キャラ 複数 → play_from_hand_pick modal。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP08-027"), repo.get("OP08-035")]  # 2 種 ミンク族 cost<=3

    do, _ = _do(overlay, "OP02-044", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("OP02-044"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st, pick=[0])
    assert any(c.card.card_id in ("OP08-027", "OP08-035") for c in me.characters), \
        "人間が選んだ《ミンク族》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  OP02-045 三刀流 鬼斬り (EVENT): 【カウンター】自リーダーかキャラ1枚 +6000、
#    その後手札からコスト3以下の元々効果なしキャラ1枚を登場。 【トリガー】相手1枚レスト。
# --------------------------------------------------------------------------- #
def test_op02_045_onigiri_counter_pump_ai():
    """【カウンター】(1) 自リーダーorキャラ1枚 +6000 (AI 自動、 リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "OP02-045", "counter", "power_pump")
    pump_prim = next(p for p in do if "power_pump" in p)
    execute_effect(pump_prim, st, me, opp, None)
    _drain_choices(st)

    assert me.leader.power == power_before + 6000, \
        f"カウンターの +6000 が自リーダーに反映されていない: {me.leader.power}"


def test_op02_045_oniigiri_counter_play_no_effect_ai():
    """【カウンター】(2) 手札からコスト3以下の 元々効果のないキャラ1枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP12-035")]  # モーガン cost3 元々効果なし

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP02-045", "counter", "play_from_hand")
    play_prim = next(p for p in do if "play_from_hand" in p)
    execute_effect(play_prim, st, me, opp, None)
    _drain_choices(st)

    assert len(me.characters) == chars_before + 1, \
        "手札からコスト3以下の元々効果なしキャラが登場していない"
    assert any(c.card.card_id == "OP12-035" for c in me.characters), \
        "登場したキャラが想定 (OP12-035) でない"


def test_op02_045_oniigiri_counter_no_play_effect_char():
    """効果ありキャラは「元々効果のない」対象外 → 登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP13-034")]  # ブルック cost3 だが効果あり (対象外)

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP02-045", "counter", "play_from_hand")
    play_prim = next(p for p in do if "play_from_hand" in p)
    execute_effect(play_prim, st, me, opp, None)
    _drain_choices(st)

    assert len(me.characters) == chars_before, \
        "効果ありキャラが「元々効果なし」枠で登場してはいけない"


def test_op02_045_oniigiri_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +6000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("ST01-004"), sickness=False)
    me.characters = [friend]

    do, _ = _do(overlay, "OP02-045", "counter", "power_pump")
    pump_prim = next(p for p in do if "power_pump" in p)
    execute_effect(pump_prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    _drain_choices(st)
    assert friend.power == friend_before + 6000, \
        "人間が選んだキャラに +6000 が反映されていない"


def test_op02_045_oniigiri_trigger_rest_ai():
    """【トリガー】相手のリーダーかコスト5以下のキャラ1枚までをレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-004"), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-045", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    rested = victim.rested or opp.leader.rested
    assert rested, "トリガーのレストがどこにも反映されていない"


# --------------------------------------------------------------------------- #
#  OP02-046 悪魔風脚 野獣肉シュート (EVENT): 【メイン】相手のレストのコスト4以下の
#    キャラ1枚までを、KOする。 【トリガー】手札からコスト4以下の元々効果なしキャラ1枚登場。
# --------------------------------------------------------------------------- #
def test_op02_046_shoot_main_ko_rested_cost_le4_ai():
    """メイン: 相手のレストのコスト4以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    victim.rested = True
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-046", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    assert victim not in opp.characters, "相手のレストのコスト4以下キャラが KO されていない"


def test_op02_046_shoot_main_no_ko_active():
    """相手のコスト4以下キャラが アクティブ (非レスト) なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    do, _ = _do(overlay, "OP02-046", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    assert victim in opp.characters, "アクティブなキャラが KO されてはいけない (対象外)"


def test_op02_046_shoot_main_ko_human_pick():
    """人間 + 相手のレストのコスト4以下キャラ 複数 → KO の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("ST01-004"), sickness=False)  # cost2
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    a.rested = True
    b.rested = True
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP02-046", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは場に残るべき"


def test_op02_046_shoot_trigger_play_no_effect_ai():
    """【トリガー】手札からコスト4以下の 元々効果のないキャラ1枚を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP02-043")]  # ゾロ cost4 元々効果なし

    chars_before = len(me.characters)
    do, _ = _do(overlay, "OP02-046", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain_choices(st)

    assert len(me.characters) == chars_before + 1, \
        "手札からコスト4以下の元々効果なしキャラが登場していない"
    assert any(c.card.card_id == "OP02-043" for c in me.characters), \
        "登場したキャラが想定 (OP02-043) でない"
