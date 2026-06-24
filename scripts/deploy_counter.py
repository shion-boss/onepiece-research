# -*- coding: utf-8 -*-
"""打倒1位 campaign の 1 ラウンドを実行する orchestrator (= gate → deploy → 永続化 → recompute)。

self-play で訓練した counter の学習 value を **配備忠実 (16/10 + value_defense は deck config 通り)**
で、 **両 seat 別々に** 実測し、 配備 baseline (= 現 deployed value) を超えたら:
  1. deploy : 学習 pkl を db/value_gbm_<counter>.pkl に配備
  2. 永続化 : 実測した両 seat 勝率を matchup_matrix.json の (counter,top)/(top,counter) セルに
              **seat 別に** 書き戻す (= symmetric override と違い calgara row-avg が正しい向きに動く)
  3. recompute: row-avg 再計算 → #1 交代を報告 + db/dethrone_campaign.json に履歴追記
超えなければ deploy しない (= 回帰を配備しない、 [[feedback_evaluation_axis]])。
これで「対戦で強化 → 順位に反映 → 標的回転」 が session を跨いで永続する (= 本当に回る)。

  .venv/bin/python scripts/deploy_counter.py --counter cardrush_1454 --iter iter4 --n 40
  # 標的は既定で matrix の現 #1。 --top で明示も可。 --dry-run で測るだけ (deploy しない)。
"""
import argparse
import datetime as _dt
import json
import shutil
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.exploit_beam_ai import ExploitBeamAI
import scripts.recompute_rank_vs_top as R  # matrix helpers を再利用

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _mk_factory(slug, gbm, bw, bd):
    """配備忠実 ExploitBeamAI factory。 gbm=None → deck_slug から配備 GBM auto-load +
    value_defense は config 通り。 gbm=path → 学習 value 差替。"""
    def aif(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": slug},
                             gbm_path=gbm, beam_width=bw, max_depth=bd)
    return aif


def _measure_seat(task):
    """1 seat を実測。 cond=base/cand, seat=cA(counter先)/tA(top先)。 返り = counter視点 w/l/d。"""
    cond, seat, counter, top, gbm, n, seed, bw, bd = task
    cg = None if cond == "base" else gbm  # base=配備GBM(auto), cand=学習pkl
    if seat == "cA":  # counter = deck1
        rep = run_matchup(
            DeckList.from_json(ROOT / "decks" / f"{counter}.json", _REPO),
            DeckList.from_json(ROOT / "decks" / f"{top}.json", _REPO),
            n_games=n, seed=seed, ai_factory_1=_mk_factory(counter, cg, bw, bd),
            ai_factory_2=_mk_factory(top, None, bw, bd),
            deck1_analysis=_ana(counter), deck2_analysis=_ana(top), effects_overlay=_OVERLAY)
        cw, tw = rep.deck1_wins, rep.deck2_wins
    else:  # top = deck1, counter = deck2
        rep = run_matchup(
            DeckList.from_json(ROOT / "decks" / f"{top}.json", _REPO),
            DeckList.from_json(ROOT / "decks" / f"{counter}.json", _REPO),
            n_games=n, seed=seed, ai_factory_1=_mk_factory(top, None, bw, bd),
            ai_factory_2=_mk_factory(counter, cg, bw, bd),
            deck1_analysis=_ana(top), deck2_analysis=_ana(counter), effects_overlay=_OVERLAY)
        cw, tw = rep.deck2_wins, rep.deck1_wins
    return (cond, seat, cw, tw, rep.draws)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--counter", required=True, help="訓練した counter slug")
    ap.add_argument("--top", default=None, help="標的 #1 (既定 = matrix 現 #1)")
    ap.add_argument("--iter", required=True, help="配備候補 iter (= db/_selfplay/<prefix><iter>.pkl)")
    ap.add_argument("--pkl-prefix", default=None, help="既定 beamloop_<counter>_")
    ap.add_argument("--n", type=int, default=40, help="seat あたり試合数")
    ap.add_argument("--beam-width", type=int, default=16)
    ap.add_argument("--max-depth", type=int, default=10)
    ap.add_argument("--margin", type=float, default=2.0, help="baseline+margin(pt) 超えで deploy")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true", help="測るだけ (deploy/書き戻しなし)")
    a = ap.parse_args()

    prefix = a.pkl_prefix if a.pkl_prefix is not None else f"beamloop_{a.counter}_"
    pkl = ROOT / "db" / "_selfplay" / f"{prefix}{a.iter}.pkl"
    if not pkl.exists():
        print(f"✗ 学習 pkl が無い: {pkl}")
        return

    m = R._load_matrix(str(R.DEFAULT_MATRIX))
    avg0, names = R._row_avgs(m)
    top = a.top or sorted(avg0.items(), key=lambda x: -x[1])[0][0]
    counter = a.counter
    print(f"=== 手順1: 現 #1 = {top} {names.get(top,'')} ({avg0[top]*100:.1f}%) | "
          f"counter = {counter} {names.get(counter,'')} ({avg0[counter]*100:.1f}%) ===")
    print(f"    候補 value = {pkl.name} | 配備忠実 beam {a.beam_width}/{a.max_depth} | n={a.n}/seat")

    # base (配備GBM) と cand (学習pkl) を 両 seat 実測 (4 tasks 並列)
    tasks = [(cond, seat, counter, top, str(pkl), a.n, a.seed + i, a.beam_width, a.max_depth)
             for i, (cond, seat) in enumerate([("base", "cA"), ("base", "tA"),
                                               ("cand", "cA"), ("cand", "tA")])]
    t0 = time.time()
    with mp.Pool(4) as p:
        res = p.map(_measure_seat, tasks, chunksize=1)
    by = {(c, s): (cw, tw, d) for c, s, cw, tw, d in res}

    def combined(cond):
        cw = by[(cond, "cA")][0] + by[(cond, "tA")][0]
        tot = sum(by[(cond, "cA")]) + sum(by[(cond, "tA")])
        return cw / max(1, tot)
    base_wr, cand_wr = combined("base"), combined("cand")
    # seat 別 cell 値 (cand): cell(counter,top)=counter as A 勝率 / cell(top,counter)=top as A 勝率
    cA = by[("cand", "cA")]; tA = by[("cand", "tA")]
    cell_ct = cA[0] / max(1, sum(cA))            # counter(A) vs top
    cell_tc = tA[1] / max(1, sum(tA))            # top(A) vs counter
    print(f"\n=== 手順4 gate (両 seat, {time.time()-t0:.0f}s) ===")
    print(f"  baseline(配備GBM) counter勝率 = {base_wr*100:.0f}%  "
          f"[cA {by[('base','cA')][0]}/{a.n}, tA {by[('base','tA')][0]}/{a.n}]")
    print(f"  candidate(学習)   counter勝率 = {cand_wr*100:.0f}%  "
          f"[cA {cA[0]}/{a.n}, tA {tA[0]}/{a.n}]  (Δ={ (cand_wr-base_wr)*100:+.0f}pt)")

    deploy = cand_wr > base_wr + a.margin / 100.0
    if not deploy:
        print(f"\n→ 配備しない (baseline+{a.margin:.0f}pt 未達 = 回帰/横ばい)。 counter 選定か規模を見直す。")
        return
    if a.dry_run:
        print(f"\n→ [dry-run] baseline 超え。 本番なら deploy + 永続化する。")
        return

    # 手順4 deploy: pkl を配備
    dst = ROOT / "db" / f"value_gbm_{counter}.pkl"
    backup = ROOT / "db" / "_selfplay" / f"_pre_deploy_{counter}.pkl.bak"
    if dst.exists():
        shutil.copy2(dst, backup)  # 旧配備 value を退避 (revert 用)
    shutil.copy2(pkl, dst)
    print(f"\n💾 手順4 deploy: {pkl.name} → {dst.name} (旧 value は {backup.name} に退避)")

    # 手順4.5 永続化: seat 別に matrix セル書き戻し
    now = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    for (a_slug, b_slug, wr) in [(counter, top, cell_ct), (top, counter, cell_tc)]:
        c = R._cell(m, a_slug, b_slug)
        if c is not None:
            c["winrate"] = wr
            c["wins"] = int(round(wr * a.n)); c["losses"] = int(a.n - round(wr * a.n)); c["draws"] = 0
            c["computed_at"] = now; c["stale"] = False; c["selfplay_deployed"] = True
    Path(R.DEFAULT_MATRIX).write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 手順5 recompute
    avg1, _ = R._row_avgs(m)
    rank1 = sorted(avg1.items(), key=lambda x: -x[1])
    new_top = rank1[0][0]
    print(f"\n=== 手順5 recompute (永続化済) ===")
    print(f"  cell(counter→top)={cell_ct*100:.0f}%  cell(top→counter)={cell_tc*100:.0f}%  書き戻し")
    for i, (s, v) in enumerate(rank1[:5]):
        d = (v - avg0.get(s, v)) * 100
        flag = " ⭐#1陥落!" if s == top and i > 0 else (" ⭐新#1" if i == 0 and s != top else "")
        print(f"  {i+1}. {names.get(s,s):18} {v*100:.1f}%  ({d:+.1f}pt){flag}")

    # campaign 履歴
    log = {"rounds": []}
    if R.CAMPAIGN_LOG.exists():
        try:
            log = json.loads(R.CAMPAIGN_LOG.read_text(encoding="utf-8"))
        except Exception:
            log = {"rounds": []}
    log.setdefault("rounds", []).append({
        "ts": now, "top_before": top, "counter": counter, "iter": a.iter,
        "baseline_wr": round(base_wr, 4), "candidate_wr": round(cand_wr, 4),
        "cell_counter_vs_top": round(cell_ct, 4), "cell_top_vs_counter": round(cell_tc, 4),
        "n_per_seat": a.n, "top_rowavg_before": round(avg0[top], 4),
        "top_rowavg_after": round(avg1[top], 4), "new_top": new_top, "rotated": new_top != top,
    })
    R.CAMPAIGN_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if new_top != top:
        print(f"\n⭐⭐ 手順6: #1 が {names.get(top,top)} → {names.get(new_top,new_top)} に交代! 次標的へ。")
    else:
        print(f"\n#1 は {names.get(top,top)} のまま ({avg0[top]*100:.1f}→{avg1[top]*100:.1f}%)。"
              f" 複数 counter × round で削る (skill 鉄則)。")
    print(f"   履歴 → {R.CAMPAIGN_LOG.name} | 次ラウンドの 手順1 はこの永続化を反映。")


if __name__ == "__main__":
    main()
