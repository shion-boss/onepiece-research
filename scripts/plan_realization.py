# -*- coding: utf-8 -*-
"""デッキ設計意図の実行率 計測 (2026-07-27、 ohtsuki の問い)。

「デッキ制作時に想定したコンボ / ターン毎の狙いを、 AI が実際に実行できているか」を自己対戦で測る。
各 key card を「引いた(手札に来た)のに、 意図した役割(展開/発動)で使えたか」で計測:
  - realization = 役割で使った試合 / 引いた試合   (低い = 引いても腐る/カウンターに溶かす=意図未実行)
  - finisher の平均展開ターン vs ideal_moves の想定ターン
  - ramp が実際に効いたか (DON 総数 > ターン数 = ramp 発火)

  PR_HERO=cardrush_1342 PR_N=100 PR_WORKERS=8 .venv/bin/python scripts/plan_realization.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, PlayCharacter, PlayEvent, PlayStage,
                         ActivateMain, AttackLeader, AttackCharacter)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
POOL = ["cardrush_1385", "cardrush_1454", "cardrush_1456", "tcgportal_bonney",
        "tcgportal_hancock", "tcgportal_calgara", "tcgportal_coby", "cardrush_1453"]
HERO = os.environ.get("PR_HERO", "cardrush_1342")
_DL = {}


def _dl(slug):
    if slug not in _DL:
        _DL[slug] = make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)
    return _DL[slug]


def _key_cards():
    a = json.loads((ROOT / "decks" / f"{HERO}.analysis.json").read_text())
    kc = {}
    for k in a.get("key_cards", []):
        kc[k["card_id"]] = {"name": k["name"], "role": k["role"], "cost": k.get("cost", 0)}
    return kc


KEY = _key_cards()


def _cid_hand(c):
    return getattr(c, "card_id", None)


def _cid_board(c):
    return getattr(getattr(c, "card", None), "card_id", None) or getattr(c, "card_id", None)


FIXED_OPP = os.environ.get("PR_OPP", "")


def _one(seed):
    rng = random.Random(seed)
    opp = FIXED_OPP if FIXED_OPP else rng.choice([d for d in POOL if d != HERO])
    fp = seed % 2
    state = setup_game(_dl(HERO), _dl(opp), rng=random.Random(seed), first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    hero_idx = 0 if fp == 0 else 1
    opp_idx = 1 - hero_idx
    ais = [None, None]
    ais[hero_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 1), deck_analysis={"deck_slug": HERO})
    ais[opp_idx] = ExploitBeamAI(rng=random.Random(seed * 7 + 3), deck_analysis={"deck_slug": opp})
    seen = set()          # 手札に来た key card_id
    played = set()        # 意図した役割(登場/発動)で使った key card_id
    affordable = set()    # 手札にあり total_don >= cost だった(=打てた)key card_id
    play_turn = {}        # card_id -> 最初に展開したターン
    ramp_fired = 0        # DON総数 > ターン数 だったターン数
    hero_turns = 0
    n, last_turn = 0, -1
    while not state.game_over and state.turn_number < 60 and n < 1500:
        cur = state.turn_player_idx
        me = state.players[hero_idx]
        if cur == hero_idx:
            # 手札スナップ(引いた key card + 打てた key card を記録)
            for c in me.hand:
                cid = _cid_hand(c)
                if cid in KEY:
                    seen.add(cid)
                    if me.total_don >= KEY[cid]["cost"]:
                        affordable.add(cid)
            if state.turn_number != last_turn:
                last_turn = state.turn_number
                hero_turns += 1
                # ramp 判定: DON 総数がターン進行(標準=turn_number/2 で自分は約 turn_number 相当)より多いか
                # 自分の総 DON が「自分のターン数」を超えていれば ramp 発火とみなす
                my_turn_count = (state.turn_number + (1 if fp == 0 else 0)) // 2
                if me.total_don > max(1, my_turn_count) + 0:
                    ramp_fired += 1
            try:
                chosen = ais[hero_idx].choose_action(state)
                cid = None
                if isinstance(chosen, (PlayCharacter, PlayEvent, PlayStage)):
                    if 0 <= getattr(chosen, "hand_idx", -1) < len(me.hand):
                        cid = _cid_hand(me.hand[chosen.hand_idx])
                elif isinstance(chosen, ActivateMain):
                    for c in me.characters:
                        if c.instance_id == getattr(chosen, "source_iid", None):
                            cid = _cid_board(c); break
                if cid in KEY:
                    played.add(cid)
                    play_turn.setdefault(cid, state.turn_number)
            except Exception:
                pass
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    won = 1 if getattr(state, "winner", -1) == hero_idx else 0
    # 終了時ゾーン: key card が最終的にどこにあったか(なぜ未実行かの切り分け)
    me = state.players[hero_idx]
    zones = defaultdict(lambda: defaultdict(int))  # cid -> {hand,trash,deck,board,life}
    for c in me.hand:
        cid = _cid_hand(c)
        if cid in KEY: zones[cid]["hand"] += 1
    for c in getattr(me, "trash", []):
        cid = _cid_hand(c)
        if cid in KEY: zones[cid]["trash"] += 1
    for c in getattr(me, "deck", []):
        cid = _cid_hand(c)
        if cid in KEY: zones[cid]["deck"] += 1
    for c in me.characters:
        cid = _cid_board(c)
        if cid in KEY: zones[cid]["board"] += 1
    for c in getattr(me, "life", []):
        cid = _cid_hand(c)
        if cid in KEY: zones[cid]["life"] += 1
    zones = {k: dict(v) for k, v in zones.items()}
    return {"seen": seen, "played": played, "affordable": affordable, "play_turn": play_turn,
            "zones": zones, "ramp_fired": ramp_fired, "hero_turns": hero_turns,
            "won": won, "done": state.game_over}


def main():
    N = int(os.environ.get("PR_N", "100"))
    W = int(os.environ.get("PR_WORKERS", "8"))
    seeds = list(range(40000, 40000 + N))
    t0 = time.time()
    print(f"[plan_realization] hero={HERO}  N={N}  key_cards={len(KEY)}", flush=True)
    with mp.Pool(W) as p:
        res = [r for r in p.map(_one, seeds) if r]
    seen_cnt = defaultdict(int); played_cnt = defaultdict(int); aff_cnt = defaultdict(int)
    aff_played_cnt = defaultdict(int)
    turn_sum = defaultdict(list)
    zsum = defaultdict(lambda: defaultdict(int))
    ramp_fired = 0; hero_turns = 0; wins = 0
    for r in res:
        for cid in r["seen"]:
            seen_cnt[cid] += 1
        for cid in r["played"]:
            played_cnt[cid] += 1
        for cid in r.get("affordable", set()):
            aff_cnt[cid] += 1
            if cid in r["played"]:
                aff_played_cnt[cid] += 1
        for cid, t in r["play_turn"].items():
            turn_sum[cid].append(t)
        for cid, z in r.get("zones", {}).items():
            for k, v in z.items():
                zsum[cid][k] += v
        ramp_fired += r["ramp_fired"]; hero_turns += r["hero_turns"]; wins += r["won"]
    print(f"\n=== 設計意図の実行率 [hero={HERO}] ({len(res)} games, 勝率 {wins/len(res)*100:.0f}%, {time.time()-t0:.0f}s) ===", flush=True)
    print(f"  ramp 発火率(DON総数>自ターン数)= {ramp_fired/max(1,hero_turns)*100:.0f}% のターン", flush=True)
    print(f"  {'role':9}{'card':18} cost 引いた 実行率 | 打てた試合 打った率★ | 終了時 手ト盤", flush=True)
    order = {"ramp": 0, "search": 1, "draw": 2, "removal": 3}
    for cid in sorted(KEY, key=lambda c: (order.get(KEY[c]["role"], 9), KEY[c]["cost"])):
        info = KEY[cid]; s = seen_cnt[cid]; pl = played_cnt[cid]
        rate = pl / max(1, s) * 100
        a = aff_cnt[cid]; ap = aff_played_cnt[cid]
        arate = ap / max(1, a) * 100
        z = zsum[cid]; tot = max(1, sum(z.values()))
        flag = " ⚠" if arate < 55 and a >= 20 else ""
        print(f"  {info['role']:9}{info['name'][:16]:18} {info['cost']:3}  {s:4}  {rate:4.0f}% | "
              f"{a:5}      {arate:4.0f}% | 手{z.get('hand',0)*100//tot:2} ト{z.get('trash',0)*100//tot:2} 盤{z.get('board',0)*100//tot:2}{flag}", flush=True)


if __name__ == "__main__":
    main()
