# -*- coding: utf-8 -*-
"""EBV2 決定の統計オブザーバ (2026-07-27、 Claude-analyst loop = 定量軸)。

多くのランダムデッキ対戦で hero の決定を集計し、 系統的な戦略的弱点を検出:
  - 消極性: ターン終了時に「遊んでいる connect 可能な攻撃者」(active + power>=相手leader だが未攻撃)
  - 無駄打ち: connect しない攻撃(公式 >= ルール)
  - 除去志向: キャラ攻撃 vs 顔攻撃 の比率
  - DON 遊び: ターン終了時の余り active DON

  STAT_N=120 STAT_WORKERS=4 .venv/bin/python scripts/stat_ebv2_decisions.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, AttackLeader, AttackCharacter, EndPhase)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
POOL = ["cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399", "cardrush_1439",
        "cardrush_1453", "cardrush_1454", "cardrush_1455", "cardrush_1456",
        "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby", "tcgportal_corazon",
        "tcgportal_hancock", "tcgportal_op11_luffy", "tcgportal_op13_luffy"]
_DL = {}


def _dl(slug):
    if slug not in _DL:
        _DL[slug] = make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)
    return _DL[slug]


FIXED_HERO = os.environ.get("STAT_HERO", "")  # 指定すると hero を固定(control/aggro 比較用)


def _one(seed):
    rng = random.Random(seed)
    if FIXED_HERO:
        h = FIXED_HERO
        o = rng.choice([d for d in POOL if d != h])
    else:
        h, o = rng.sample(POOL, 2)
    fp = seed % 2
    state = setup_game(_dl(h), _dl(o), rng=random.Random(seed), first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    # ⚠ setup_game は先攻を players[0] に置く (players=[p2,p1] if fp==1)。 hero(deck h)=deck1 は
    # fp==0 のとき index0、 fp==1 のとき index1。 ais は player 位置で index せねばならない。
    hero_idx = 0 if fp == 0 else 1
    opp_idx = 1 - hero_idx
    ais = [None, None]
    ais[hero_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 1), deck_analysis={"deck_slug": h})
    ais[opp_idx] = ExploitBeamAI(rng=random.Random(seed * 7 + 3), deck_analysis={"deck_slug": o})
    st = {"hero_turns": 0, "attacks": 0, "face": 0, "char": 0, "waste": 0,
          "idle_connect_sum": 0, "leftover_don_sum": 0, "turns_no_attack": 0,
          "opp_big_present": 0, "opp_big_attacked": 0}
    n, last_turn, atk_this_turn = 0, -1, 0
    while not state.game_over and state.turn_number < 60 and n < 1500:
        cur = state.turn_player_idx
        if cur == hero_idx and state.turn_number != last_turn:
            last_turn = state.turn_number
            st["hero_turns"] += 1
            atk_this_turn = 0
        if cur == hero_idx:
            try:
                chosen = ais[hero_idx].choose_action(state)
                me = state.players[hero_idx]; opp = state.players[opp_idx]
                if isinstance(chosen, EndPhase):
                    # 真のターン終了: 遊び攻撃者 + 余り active DON を測定
                    opp_lead = opp.leader.power
                    idle = sum(1 for c in me.characters if not c.rested and c.power >= opp_lead)
                    st["idle_connect_sum"] += idle
                    st["leftover_don_sum"] += me.don_active
                    if atk_this_turn == 0:
                        st["turns_no_attack"] += 1
                    # 相手に大型(7000+)がいて、 自分が攻撃可能だったのに一度も除去しなかったか
                    big = [c for c in opp.characters if c.power >= 7000 and not c.rested]
                    if big:
                        st["opp_big_present"] += 1
                elif isinstance(chosen, (AttackLeader, AttackCharacter)):
                    st["attacks"] += 1; atk_this_turn += 1
                    if isinstance(chosen, AttackLeader):
                        st["face"] += 1
                        atk = next((c for c in me.characters
                                    if c.instance_id == chosen.attacker_iid),
                                   me.leader if me.leader.instance_id == chosen.attacker_iid else None)
                        if atk and atk.power < opp.leader.power:
                            st["waste"] += 1
                    else:
                        st["char"] += 1
                        tgt = next((c for c in opp.characters if c.instance_id == chosen.target_iid), None)
                        atk = next((c for c in me.characters
                                    if c.instance_id == chosen.attacker_iid), None)
                        if tgt and tgt.power >= 5000:
                            st["opp_big_attacked"] += 1  # 実脅威(5000+)への除去
                        if atk and tgt and atk.power < tgt.power:
                            st["waste"] += 1
            except Exception:
                pass
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    st["done"] = 1 if state.game_over else 0
    return st


def main():
    N = int(os.environ.get("STAT_N", "120"))
    W = int(os.environ.get("STAT_WORKERS", "4"))
    seeds = list(range(20000, 20000 + N))
    t0 = time.time()
    print(f"[stat_ebv2] ランダム 16 deck pool、 N={N} games、 workers={W}", flush=True)
    with mp.Pool(W) as p:
        res = [r for r in p.map(_one, seeds) if r]
    agg = defaultdict(int)
    for r in res:
        for k, v in r.items():
            agg[k] += v
    ht = max(1, agg["hero_turns"]); at = max(1, agg["attacks"])
    label = FIXED_HERO if FIXED_HERO else "ランダム 16 deck"
    print(f"\n=== EBV2 決定 統計 [hero={label}] ({len(res)} games, {agg['done']} 完走, {time.time()-t0:.0f}s) ===", flush=True)
    print(f"  hero ターン総数 = {agg['hero_turns']:,}", flush=True)
    print(f"  ① 攻撃頻度 = {agg['attacks']/ht:.2f} 回/ターン", flush=True)
    print(f"  ② 攻撃対象: 顔 {agg['face']/at*100:.0f}% / キャラ(除去) {agg['char']/at*100:.0f}%", flush=True)
    print(f"  ③ 無駄打ち率(connectしない攻撃)= {agg['waste']/at*100:.1f}%  ({agg['waste']}/{agg['attacks']})", flush=True)
    print(f"  ④ 消極性: ターン終了時の遊び攻撃者(active+顔connect可 だが未攻撃)= {agg['idle_connect_sum']/ht:.2f} 体/ターン", flush=True)
    print(f"  ⑤ 消極性: 攻撃者いても無攻撃で終えたターン = {agg['turns_no_attack']/ht*100:.0f}%", flush=True)
    print(f"  ⑥ DON 遊び: ターン終了時の余り active DON = {agg['leftover_don_sum']/ht:.2f} 個/ターン", flush=True)
    print(f"  ⑦ 除去の質: キャラ攻撃 {agg['char']} 回中 実脅威(5000+)狙い = {agg['opp_big_attacked']} 回 "
          f"({agg['opp_big_attacked']/max(1,agg['char'])*100:.0f}%)", flush=True)
    print(f"  ⑧ 未処理の大型: 相手 7000+ active がいる状態でターンを終えた回 = {agg['opp_big_present']} "
          f"({agg['opp_big_present']/ht*100:.0f}% のターン)", flush=True)


if __name__ == "__main__":
    main()
