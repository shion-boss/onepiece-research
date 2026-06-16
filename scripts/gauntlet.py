# -*- coding: utf-8 -*-
"""#1 デッキ gauntlet: 他デッキが #1 (= 既定 matrix 1位) と N 戦ずつ戦い、 勝率スコアボードを出す。

ohtsuki ループ: 「#1 を対象に他デッキ ×N戦 → 勝率更新 → 改善 → 繰り返す」 の測定バックボーン。
改善 (= AI/heuristic/value 変更) の前後でこれを回し、 各デッキの vs #1 勝率の変化を追う。
#1 が陥落 (= 他に抜かれる) したら別の #1 へ再ターゲット。

両者 ExploitBeam (= 配備)。 #1 は固定 (= 自身の per-deck GBM)。 first/second 交互。

  GAUNTLET_TARGET=tcgportal_calgara GAUNTLET_N=5 GAUNTLET_WORKERS=8 \
      .venv/bin/python scripts/gauntlet.py
"""
import os, sys, json, random, time
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
_DECK_CACHE = {}
# 我々側 (= 挑戦者) に deck非依存 GBM fallback を使うか (= 改善レバーの一例)。 #1 側は常に固定。
_CHALLENGER_AGNOSTIC = os.environ.get("GAUNTLET_AGNOSTIC") == "1"


def _matrix_top():
    m = json.loads((REPO_ROOT / "db" / "matchup_matrix.json").read_text(encoding="utf-8"))
    import statistics
    best, bw = None, -1
    names = {}
    for e in m["matrix"]:
        wr = [c["winrate"] for c in e["row"] if c.get("winrate") is not None]
        names[e["deck_a"]] = e["deck_a_name"]
        if wr and statistics.mean(wr) > bw:
            bw, best = statistics.mean(wr), e["deck_a"]
    return best, names


def _deck(slug):
    if slug not in _DECK_CACHE:
        _DECK_CACHE[slug] = json.loads(
            (REPO_ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8"))
    return _DECK_CACHE[slug]


def _analysis(slug):
    """full deck_analysis (mulligan_keep / archetype profile 含む) を読む。 = matrix/run_matchup と同条件。"""
    p = REPO_ROOT / "decks" / f"{slug}.analysis.json"
    a = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    a["deck_slug"] = slug
    return a


def _beam(seed, slug, *, agnostic=False):
    ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                       deck_analysis=_analysis(slug))
    ai._use_agnostic_gbm = agnostic
    return ai


def _one(task):
    seed, challenger, target = task
    a_idx = seed % 2           # challenger がどちら側か
    fp = (seed // 2) % 2
    decks = [None, None]
    decks[a_idx] = make_deck_from_dict(_deck(challenger), _REPO)
    decks[1 - a_idx] = make_deck_from_dict(_deck(target), _REPO)
    state = setup_game(decks[0], decks[1], rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = _beam(seed * 5 + 1, challenger, agnostic=_CHALLENGER_AGNOSTIC)
    ais[1 - a_idx] = _beam(seed * 7 + 3, target)   # #1 は固定 (per-deck GBM)
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return (challenger, None)
    w = getattr(state, "winner", -1)
    return (challenger, "W" if w == a_idx else ("L" if w == (1 - a_idx) else None))


def main():
    n = int(os.environ.get("GAUNTLET_N", "5"))
    workers = int(os.environ.get("GAUNTLET_WORKERS", "8"))
    top, names = _matrix_top()
    target = os.environ.get("GAUNTLET_TARGET", top)
    challengers = [dk["slug"] for dk in json.loads(
        (REPO_ROOT / "db" / "matchup_matrix.json").read_text(encoding="utf-8"))["decks"]
        if dk["slug"] != target]
    print(f"#1(target) = {target} ({names.get(target,'?')})  | challengers={len(challengers)} "
          f"| N={n}/deck | challenger_agnostic={_CHALLENGER_AGNOSTIC}")
    tasks = [(1000 + i, c, target) for c in challengers for i in range(n)]
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, tasks, chunksize=4)
    from collections import defaultdict
    run = defaultdict(lambda: [0, 0])  # this run: deck -> [W, L]
    for c, r in res:
        if r == "W": run[c][0] += 1
        elif r == "L": run[c][1] += 1

    # === 永続累積 (ohtsuki: 過去戦績に足し込み、 合計勝率で見る。 何週もループ) ===
    note = os.environ.get("GAUNTLET_NOTE", "")  # AI版/改善のタグ (= ラグ解釈用)
    log_path = REPO_ROOT / "db" / f"gauntlet_{target}.json"
    if log_path.exists():
        log = json.loads(log_path.read_text(encoding="utf-8"))
    else:
        log = {"target": target, "cum": {}, "runs": []}
    cum = log["cum"]
    run_rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": note, "n_per": n, "wl": {}}
    for c in challengers:
        w, l = run[c]
        cum.setdefault(c, [0, 0])
        cum[c][0] += w; cum[c][1] += l
        run_rec["wl"][c] = [w, l]
    log["runs"].append(run_rec)
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")

    # 直近ウィンドウ (= 最後の RECENT_K run = 現在のAI実力)
    recent_k = int(os.environ.get("GAUNTLET_RECENT_K", "5"))
    rec = defaultdict(lambda: [0, 0])
    for r in log["runs"][-recent_k:]:
        for c, (w, l) in r["wl"].items():
            rec[c][0] += w; rec[c][1] += l

    def _wr(wl):
        w, l = wl; return w / max(1, w + l) * 100
    rows = sorted(((names.get(c, c), c, run[c], cum[c], rec[c]) for c in challengers),
                  key=lambda x: _wr(x[3]))
    print(f"=== vs {names.get(target,target)} スコアボード "
          f"(run {len(log['runs'])}, note='{note}') ===")
    print(f"  {'deck':<20}{'今回':>8}{'生涯累積':>12}{'直近'+str(recent_k):>11}")
    for name, c, rn, cm, rc in rows:
        print(f"  {name:<20}{rn[0]:>3}-{rn[1]:<3}{cm[0]:>5}-{cm[1]:<4}{_wr(cm):>4.0f}%"
              f"{rc[0]:>4}-{rc[1]:<3}{_wr(rc):>4.0f}%")
    aW = sum(cum[c][0] for c in challengers); aL = sum(cum[c][1] for c in challengers)
    rW = sum(rec[c][0] for c in challengers); rL = sum(rec[c][1] for c in challengers)
    print(f"  {'AGGREGATE':<20}{'':<8}{aW:>5}-{aL:<4}{aW/max(1,aW+aL)*100:>4.0f}%"
          f"{rW:>4}-{rL:<3}{rW/max(1,rW+rL)*100:>4.0f}%   ({time.time()-t0:.0f}s)")
    print(f"  → challenger 生涯勝率 {aW/max(1,aW+aL)*100:.0f}% / 直近 {rW/max(1,rW+rL)*100:.0f}% "
          f"(= calgara を倒せてる割合。 改善でこれが上がるのを何週も追う)")


if __name__ == "__main__":
    main()
