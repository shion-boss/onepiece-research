# -*- coding: utf-8 -*-
"""一人回し (goldfish) ハーネス = デッキ健全性の診断。

目的は kill 速度ではなく、 **13 ターン回し切って「デッキがちゃんと回るか」 を観察する**こと:
  - DON をどれだけ使えているか (= 余り DON = 機会損失。 高コスト過多 / カーブ崩れの直接指標)
  - 各ターン何枚 play できているか (= 死にターン / カーブの穴 / 終盤フラッド)
  - 手札が詰まっていないか (= 撃てない高コストの滞留)
  - 何が何ターンで場に出るか (= 展開プロファイル)

相手は passive (= 何もしない) で、 さらに **life を厚く pad して 13 ターン落ちない** ようにする
(= 途中で倒して終わらせず、 全 13 ターンの回り具合を観察するため)。 ⚠ 相手が殴ってこない
ので「被弾で誘発する効果 (ナミのドローエンジン等)」 は発火しない = solo 半分の診断。

使い方:
    GF_SLUG=cardrush_1439 GF_N=30000 GF_WORKERS=8 .venv/bin/python scripts/goldfish.py
    GF_BENCH=1 .venv/bin/python scripts/goldfish.py     # timing ベンチ
"""
import os, sys, time, json, random, statistics
import multiprocessing as mp
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (
    setup_game, play_until_main, EndPhase, PlayCharacter, PlayEvent, PlayStage,
    AttackLeader, AttackCharacter,
)
from engine.ai import play_one_action, GreedyAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
_raw = json.loads((REPO_ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
_cards_list = _raw["cards"] if isinstance(_raw, dict) and "cards" in _raw else _raw
_NAMES = {c["card_id"]: c.get("name", c["card_id"])
          for c in _cards_list if isinstance(c, dict) and "card_id" in c}

SLUG = os.environ.get("GF_SLUG", "cardrush_1439")
TURN_CAP = int(os.environ.get("GF_TURN_CAP", "13"))


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")),
        _REPO,
    )


class PassiveAI(GreedyAI):
    def choose_action(self, state):
        return EndPhase()

    def choose_defense(self, state, attacker, target, is_leader_attack, defender):
        return (None, ())


class RecordingGreedy(GreedyAI):
    """play した (card_id, nami_turn) を記録 + 各ターン終了時の余り DON を蓄積。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.plays = []
        self._cur_turn = 0

    def choose_action(self, state):
        a = super().choose_action(state)
        if isinstance(a, (PlayCharacter, PlayEvent, PlayStage)):
            me = state.players[state.turn_player_idx]
            idx = getattr(a, "hand_idx", -1)
            if 0 <= idx < len(me.hand):
                self.plays.append((me.hand[idx].card_id, self._cur_turn))
        return a


def _make_pilot(kind, seed):
    if kind == "exploitbeam":
        from engine.exploit_beam_ai import ExploitBeamAI
        return ExploitBeamAI(rng=random.Random(seed), deck_analysis={"deck_slug": SLUG})
    return RecordingGreedy(rng=random.Random(seed), deck_analysis={"deck_slug": SLUG})


def goldfish_once(task):
    seed, pilot_kind = task
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=0, effects_overlay=_OVERLAY)
    play_until_main(state)
    # 相手 life を厚く pad → 13 ターン落ちない (= 全ターン観察)。 dummy = leader card (no trigger)。
    opp = state.players[1]
    opp.life.extend([opp.leader.card] * 80)
    pilot = _make_pilot(pilot_kind, seed * 3 + 1)
    passive = PassiveAI(rng=random.Random(seed * 5 + 2))
    ais = [pilot, passive]
    turns = 0
    last_tp = None
    n = 0
    # ターン別スナップ: 各 pilot ターン開始時の (don_total, hand, board)
    snaps = []
    while not state.game_over and n < 2000:
        cur = state.turn_player_idx
        if cur == 0 and last_tp != 0:
            turns += 1
            if turns > TURN_CAP:
                break
            p0 = state.players[0]
            snaps.append((p0.total_don, len(p0.hand), len(p0.characters)))
        if cur == 0:
            pilot._cur_turn = turns
        last_tp = cur
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    p0 = state.players[0]
    return {
        "turns": turns,
        "don_wasted": int(getattr(p0, "dons_unused_at_end_count", 0)),  # 累積余りDON
        "plays": getattr(pilot, "plays", []),
        "final_hand": len(p0.hand),
        "final_board": len(p0.characters),
        "snaps": snaps,
    }


def _run(n, pilot_kind, workers, seed0=0):
    tasks = [(seed0 + s, pilot_kind) for s in range(n)]
    t0 = time.time()
    if workers > 1:
        with mp.Pool(workers) as p:
            res = p.map(goldfish_once, tasks, chunksize=64)
    else:
        res = [goldfish_once(t) for t in tasks]
    return res, time.time() - t0


def _bench(workers):
    res_g, t_g = _run(200, "greedy", workers)
    per_g = t_g / 200
    print(f"[greedy] 200 runs {t_g:.1f}s = {per_g*1000:.0f} ms/run "
          f"=> 30k: {per_g*30000/60/workers:.1f}分 ({workers}並列)")


def _report(res, elapsed, n):
    N = len(res)
    waste = [r["don_wasted"] for r in res]
    tot_plays = [len(r["plays"]) for r in res]
    print(f"=== goldfish デッキ健全性診断: {SLUG}  ({n} runs, {elapsed:.0f}s, {TURN_CAP}ターン回し切り) ===")
    print(f"[DON健全性] 13ターンで余らせたDON (機会損失) 平均 {statistics.mean(waste):.1f} "
          f"(/turn {statistics.mean(waste)/TURN_CAP:.2f}) / median {statistics.median(waste):.0f}")
    print(f"[展開量] 総play 平均 {statistics.mean(tot_plays):.1f}枚 / "
          f"終了時 board {statistics.mean(r['final_board'] for r in res):.1f}体 / "
          f"手札滞留 {statistics.mean(r['final_hand'] for r in res):.1f}枚")

    # ターン別: 平均 play 数 + 死にターン率 (= その turn に 0 play だった割合)
    plays_pos = defaultdict(int)
    dead_pos = defaultdict(int)
    for r in res:
        per_turn = Counter(t for _, t in r["plays"] if 1 <= t <= TURN_CAP)
        for t in range(1, TURN_CAP + 1):
            plays_pos[t] += per_turn.get(t, 0)
            if per_turn.get(t, 0) == 0:
                dead_pos[t] += 1
    print(f"[カーブ実現] ターン別 平均play数 / 死にターン率:")
    line1 = "  turn:  " + "".join(f"{t:>5}" for t in range(1, TURN_CAP + 1))
    line2 = "  play:  " + "".join(f"{plays_pos[t]/N:>5.1f}" for t in range(1, TURN_CAP + 1))
    line3 = "  dead%: " + "".join(f"{dead_pos[t]/N*100:>5.0f}" for t in range(1, TURN_CAP + 1))
    print(line1); print(line2); print(line3)

    # 展開プロファイル (登場率 / 中央ターン)
    pc = Counter()
    ft = defaultdict(list)
    for r in res:
        seen = {}
        for cid, t in r["plays"]:
            seen.setdefault(cid, t)
        for cid, t in seen.items():
            pc[cid] += 1
            ft[cid].append(t)
    print(f"[展開プロファイル] カード別 登場率 / 中央ターン (上位15):")
    for cid, cnt in pc.most_common(15):
        print(f"  {cid:<11}{_NAMES.get(cid,'')[:18]:<19}{cnt/N*100:>5.0f}%  t{statistics.median(ft[cid]):>2.0f}")


def main():
    workers = int(os.environ.get("GF_WORKERS", "8"))
    if os.environ.get("GF_BENCH") == "1":
        _bench(workers)
        return
    n = int(os.environ.get("GF_N", "30000"))
    res, t = _run(n, os.environ.get("GF_PILOT", "greedy"), workers)
    _report(res, t, n)


if __name__ == "__main__":
    main()
