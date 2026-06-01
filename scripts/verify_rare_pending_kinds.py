#!/usr/bin/env python3
"""人間vsAI UX: ランダムプレイ fuzzer で 稀にしか到達しない pending_choice kind を
決定論的に exercise → resolve まで完遂するか検証する 回帰スクリプト。

`scripts/fuzz_human_play.py` の coverage fuzz は 29 kind 中 24 を踏むが、 残り 5
(scry_life_reorder / view_life_top_choose_position / summon_from_deck_pick /
end_of_turn_optional / on_opp_attack 系) は 特定カード + 特定状況 依存で random では
まず出ない。 本スクリプトは それらを 実カード/直接 primitive で 確実に発火させ、
resolve_pending_choice / apply_human_use_opp_attack_effect が crash/stuck なく
完遂する事を保証する。

exit 0 = 全 OK、 非0 = いずれか失敗。
"""
import os
import random
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (load_effect_overlay, execute_effect, resolve_pending_choice,
                            resolve_triggers, trigger_end_of_turn, trigger_on_opp_attack)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
repo = CardRepository.from_json(os.path.join(ROOT, "db", "cards.json"))
ov = load_effect_overlay(os.path.join(ROOT, "db", "card_effects.json"))

results = []


def _mk(human_turn=True, leader="OP01-001", deck_fill="OP01-013"):
    p1 = Player(name="P0", leader=InPlay.of(repo.get(leader), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get(deck_fill)] * 24
    p2.deck = [repo.get("OP01-013")] * 24
    p1.life = [repo.get("OP01-013") for _ in range(4)]
    p2.life = [repo.get("OP01-013") for _ in range(4)]
    st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(1), effects_overlay=ov)
    st.human_player_idx = 0
    st.turn_player_idx = 0 if human_turn else 1
    if not human_turn:
        st.forced_human_actor_idx = 0
    return st, p1, p2


def _drain(st, max_steps=12):
    """pending_choice chain を全て resolve (0 idx / 空) して drain。"""
    chain = []
    steps = 0
    while st.pending_choice is not None and steps < max_steps:
        steps += 1
        k = st.pending_choice.get("kind")
        chain.append(k)
        cs = st.pending_choice.get("candidates") or st.pending_choice.get("cards") or []
        if k in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
            resolve_pending_choice(st, [])
        else:
            resolve_pending_choice(st, [0] if cs else [])
    return chain, st.pending_choice is None


def check(label, fn):
    try:
        ok, detail = fn()
        results.append((label, "OK" if ok else "FAIL", detail))
    except Exception as e:
        results.append((label, "CRASH", f"{e} | {traceback.format_exc().splitlines()[-1][:70]}"))


# 1. scry_life_reorder (scry_life primitive、 human + 自ライフ depth>=2)
def _scry_life_reorder():
    st, me, opp = _mk()
    src = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters.append(src)
    execute_effect({"scry_life": {"owner": "self", "depth": 2}}, st, me, opp, src)
    if st.pending_choice is None or st.pending_choice.get("kind") != "scry_life_reorder":
        return False, f"halt しない / wrong kind ({st.pending_choice})"
    resolve_pending_choice(st, [1, 0])
    return st.pending_choice is None, "reorder 完遂"


# 2. view_life_top_choose_position (life top を 上/下 に置く)
def _view_life_pos():
    st, me, opp = _mk()
    src = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters.append(src)
    execute_effect({"view_life_top_choose_position": {"owner": "self", "depth": 1}}, st, me, opp, src)
    if st.pending_choice is None or st.pending_choice.get("kind") != "view_life_top_choose_position":
        return False, f"halt しない / wrong kind ({st.pending_choice})"
    resolve_pending_choice(st, [1])  # 下へ
    return st.pending_choice is None, "底へ配置 完遂"


# 3. summon_from_deck_pick (デッキから登場、 召喚先 on_play 連鎖も drain)
def _summon_from_deck():
    st, me, opp = _mk(deck_fill="OP01-016")  # ナミ (on_play search)
    me.deck = [repo.get("OP01-016"), repo.get("OP01-016"), repo.get("OP01-013")] * 6
    src = InPlay.of(repo.get("OP01-016"), sickness=False)
    me.characters.append(src)
    n0 = len(me.characters)
    execute_effect({"summon_from_deck": {"filter": {}, "limit": 1}}, st, me, opp, src)
    if st.pending_choice is None or st.pending_choice.get("kind") != "summon_from_deck_pick":
        return False, f"halt しない / wrong kind ({st.pending_choice})"
    chain, cleared = _drain(st)
    return (cleared and len(me.characters) > n0), f"chain={chain} chars {n0}->{len(me.characters)}"


# 4. end_of_turn_optional (OP04-032 ベビー5: ターン終了時 トラッシュ→ドン2 active)
def _end_of_turn_optional():
    st, me, opp = _mk()
    st.phase = Phase.END
    baby = InPlay.of(repo.get("OP04-032"), sickness=False)
    me.characters.append(baby)
    me.don_rested = 2
    trigger_end_of_turn(st, ov)
    if st.pending_choice is None or st.pending_choice.get("kind") != "end_of_turn_optional":
        return False, f"halt しない / wrong kind ({st.pending_choice})"
    resolve_pending_choice(st, [0])  # available[0] 発動
    if st.event_queue and not st.resolving:
        resolve_triggers(st)
    trashed = baby not in me.characters
    return (st.pending_choice is None and trashed and me.don_active >= 2), \
        f"trashed={trashed} don_active={me.don_active}"


# 5. on_opp_attack 効果 (OP13-002 エース: 相手アタック時 手札捨て→対象-2000) を
#    人間 defender が _available_opp_attack_effects 経由で発動できる事を確認 (SET side)。
#    実際の click 発動 (apply_human_use_opp_attack_effect) は fuzz_human_play.py で網羅。
def _on_opp_attack_available():
    st, me, opp = _mk(human_turn=False, leader="OP13-002")
    me.hand = [repo.get("OP01-013")]  # discard_hand コスト 用
    atk = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters.append(atk)
    trigger_on_opp_attack(st, me, opp, atk, ov)
    avail = getattr(st, "_available_opp_attack_effects", []) or []
    hit = any(e.get("card_id") == "OP13-002" and e.get("discard_hand") == 1 for e in avail)
    return hit, f"available={[(e.get('card_id'), e.get('discard_hand')) for e in avail]}"


check("scry_life_reorder", _scry_life_reorder)
check("view_life_top_choose_position", _view_life_pos)
check("summon_from_deck_pick", _summon_from_deck)
check("end_of_turn_optional", _end_of_turn_optional)
check("on_opp_attack_available", _on_opp_attack_available)

print("=== 稀少 pending_choice kind 検証 ===")
n_fail = 0
for label, status, detail in results:
    mark = "✓" if status == "OK" else "✗"
    if status != "OK":
        n_fail += 1
    print(f"  {mark} {label}: {status} ({detail})")

if n_fail:
    print(f"\n!!! {n_fail} 件 失敗")
    sys.exit(1)
print("\n✓ 全 稀少 kind が halt → resolve 完遂")
