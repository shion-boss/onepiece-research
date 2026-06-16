# -*- coding: utf-8 -*-
"""#1 デッキ gauntlet: 他デッキが #1 (= 既定 matrix 1位) と N 戦ずつ戦い、 勝率スコアボードを出す。

ohtsuki ループ: 「#1 を対象に他デッキ ×N戦 → 勝率更新 → 改善 → 繰り返す」 の測定バックボーン。
改善 (= AI/heuristic/value 変更) の前後でこれを回し、 各デッキの vs #1 勝率の変化を追う。
#1 が陥落 (= 他に抜かれる) したら別の #1 へ再ターゲット。

⭐ 測定は **compute_matchup_matrix.py と同一の run_matchup** を使う (= /meta と一致)。
旧版は play_one_action の手書きループ (turn<50 / except-break) で run_matchup と乖離し、
calgara を ~52% と誤測定していた (full matrix は 76.8%)。 手書きループを廃止し、
seed=42/N=20 で回せば matrix の (challenger, target) セルを完全再現する。

  GAUNTLET_TARGET=tcgportal_calgara GAUNTLET_N=20 GAUNTLET_SEED=42 GAUNTLET_WORKERS=8 \
      .venv/bin/python scripts/gauntlet.py

env:
  GAUNTLET_TARGET   #1 の slug (既定 = matrix の row-avg 1位)
  GAUNTLET_N        challenger 毎の試合数 (既定 20)
  GAUNTLET_SEED     run_matchup seed。 未指定なら 42 + これまでの run 数 (= 毎週違う試合)
  GAUNTLET_WORKERS  並列数 (challenger 単位、 既定 8)
  GAUNTLET_AGNOSTIC =1 で challenger 側を agnostic GBM fallback に (= 改善レバー)。 #1 側は固定
  GAUNTLET_NOTE     run のタグ (AI版/改善内容、 スコアボードに残す)
  GAUNTLET_RECENT_K 直近ウィンドウの run 数 (既定 5)
"""
import os, sys, json, random, time
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.exploit_beam_ai import ExploitBeamAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
_METHOD = "run_matchup_v2"  # 測定方式タグ。 変わったら旧スコアボードは破棄 (累積が比較不能になる)
_DECK_CACHE: dict = {}
_ANALYSIS_CACHE: dict = {}
# challenger 側に deck非依存 GBM fallback を使うか (= 改善レバーの一例)。 #1 側は常に固定 (per-deck GBM)。
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


def _decklist(slug):
    if slug not in _DECK_CACHE:
        _DECK_CACHE[slug] = DeckList.from_json(REPO_ROOT / "decks" / f"{slug}.json", _REPO)
    return _DECK_CACHE[slug]


def _analysis(slug):
    """full deck_analysis (mulligan_keep / archetype profile 含む)。 matrix/run_matchup と同条件。"""
    if slug not in _ANALYSIS_CACHE:
        p = REPO_ROOT / "decks" / f"{slug}.analysis.json"
        _ANALYSIS_CACHE[slug] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _ANALYSIS_CACHE[slug]


def _run_challenger(task):
    """challenger vs target を n_games 戦 (run_matchup、 matrix と同一構成)。 challenger 視点 (W,L,D) を返す。"""
    challenger, target, n_games, seed, agnostic = task

    # ⭐ matrix (compute_matchup_matrix.py) と同一の ExploitBeam 構成: deck_analysis に deck_slug を
    #    merge して per-deck GBM を解決。 beam_width/max_depth は ExploitBeam 既定 (= 配備値) に委ねる。
    def _aif_c(rng, deck_analysis=None):
        ai = ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": challenger})
        ai._use_agnostic_gbm = agnostic
        return ai

    def _aif_t(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": target})

    rep = run_matchup(
        _decklist(challenger), _decklist(target),
        n_games=n_games, seed=seed,
        ai_factory_1=_aif_c, ai_factory_2=_aif_t,
        deck1_analysis=_analysis(challenger), deck2_analysis=_analysis(target),
        effects_overlay=_OVERLAY,
    )
    return (challenger, rep.deck1_wins, rep.deck2_wins, rep.draws)


def main():
    n = int(os.environ.get("GAUNTLET_N", "20"))
    workers = int(os.environ.get("GAUNTLET_WORKERS", "8"))
    top, names = _matrix_top()
    target = os.environ.get("GAUNTLET_TARGET", top)
    challengers = [dk["slug"] for dk in json.loads(
        (REPO_ROOT / "db" / "matchup_matrix.json").read_text(encoding="utf-8"))["decks"]
        if dk["slug"] != target]

    # === 永続累積 (ohtsuki: 過去戦績に足し込み、 合計勝率で見る。 何週もループ) ===
    log_path = REPO_ROOT / "db" / f"gauntlet_{target}.json"
    log = None
    if log_path.exists():
        log = json.loads(log_path.read_text(encoding="utf-8"))
        if log.get("method") != _METHOD:
            # 旧 (手書きループ) の累積は方式が違うので比較不能 → 退避してリセット
            broken = log_path.with_suffix(".broken.json")
            broken.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"⚠ 旧 method='{log.get('method')}' のスコアボードを {broken.name} へ退避しリセット "
                  f"(run_matchup 方式に移行)")
            log = None
    if log is None:
        log = {"target": target, "method": _METHOD, "cum": {}, "runs": []}

    # seed: 明示なければ 42 + これまでの run 数 (= 毎週違う試合を足し込む。 ohtsuki: seed変えながら)
    seed = int(os.environ.get("GAUNTLET_SEED", str(42 + len(log["runs"]))))

    print(f"#1(target) = {target} ({names.get(target,'?')})  | challengers={len(challengers)} "
          f"| N={n}/deck | seed={seed} | challenger_agnostic={_CHALLENGER_AGNOSTIC} | method={_METHOD}")
    tasks = [(c, target, n, seed, _CHALLENGER_AGNOSTIC) for c in challengers]
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_run_challenger, tasks, chunksize=1)
    from collections import defaultdict
    run = {c: [0, 0, 0] for c in challengers}  # this run: deck -> [W, L, D]
    for c, w, l, d in res:
        run[c] = [w, l, d]

    note = os.environ.get("GAUNTLET_NOTE", "")
    cum = log["cum"]
    run_rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": note, "n_per": n,
               "seed": seed, "wl": {}}
    for c in challengers:
        w, l, d = run[c]
        cum.setdefault(c, [0, 0, 0])
        cum[c][0] += w; cum[c][1] += l; cum[c][2] += d
        run_rec["wl"][c] = [w, l, d]
    log["runs"].append(run_rec)
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")

    # 直近ウィンドウ (= 最後の RECENT_K run = 現在のAI実力)
    recent_k = int(os.environ.get("GAUNTLET_RECENT_K", "5"))
    rec = defaultdict(lambda: [0, 0, 0])
    for r in log["runs"][-recent_k:]:
        for c, wld in r["wl"].items():
            for i in range(3):
                rec[c][i] += wld[i] if i < len(wld) else 0

    def _wr(wld):
        w, l, d = (list(wld) + [0, 0, 0])[:3]
        return w / max(1, w + l + d) * 100
    rows = sorted(((names.get(c, c), c, run[c], cum[c], rec[c]) for c in challengers),
                  key=lambda x: _wr(x[3]))
    print(f"=== vs {names.get(target,target)} スコアボード (run {len(log['runs'])}, note='{note}') ===")
    print(f"  {'deck':<20}{'今回(W-L-D)':>13}{'生涯累積':>14}{'直近'+str(recent_k):>12}")
    for name, c, rn, cm, rc in rows:
        print(f"  {name:<20}{rn[0]:>3}-{rn[1]:<2}-{rn[2]:<3}{cm[0]:>5}-{cm[1]:<3}{_wr(cm):>4.0f}%"
              f"{rc[0]:>5}-{rc[1]:<2}{_wr(rc):>4.0f}%")
    aW = sum(cum[c][0] for c in challengers); aL = sum(cum[c][1] for c in challengers)
    aD = sum(cum[c][2] for c in challengers)
    rW = sum(rec[c][0] for c in challengers); rL = sum(rec[c][1] for c in challengers)
    rD = sum(rec[c][2] for c in challengers)
    print(f"  {'AGGREGATE':<20}{'':<13}{aW:>5}-{aL:<3}{aW/max(1,aW+aL+aD)*100:>4.0f}%"
          f"{rW:>5}-{rL:<2}{rW/max(1,rW+rL+rD)*100:>4.0f}%   ({time.time()-t0:.0f}s)")
    print(f"  → challenger 生涯勝率 {aW/max(1,aW+aL+aD)*100:.0f}% / 直近 {rW/max(1,rW+rL+rD)*100:.0f}% "
          f"(= {names.get(target,target)} を倒せてる割合。 改善でこれが上がるのを何週も追う)")


if __name__ == "__main__":
    main()
