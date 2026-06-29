# -*- coding: utf-8 -*-
"""デッキ毎のコンセプト(= archetype 内の固有方針)をデータ駆動で導出する profiler。

ohtsuki『アーキタイプ判定が粗い。 control デッキは何をコントロールしてどう勝つか、 各デッキ固有の
コンセプトがある』([[project_leader_aware_matchup_ai]])への対処。 粗い tag(aggro/control/…)を、
「各デッキが実際にどう勝つか」のデータ駆動 signature で精緻化する foundation。

各デッキ D を field 相手に対戦 → 勝ち試合 vs 負け試合 で 汎用 win-condition 軸を contrast。
勝ちと相関する軸 = そのデッキの concept(= 何を leverage して勝つか)。 出力 = 各デッキの
concept signature(z-score 化した軸)→ leader_profiles の concept 欄を grounding。

  .venv/bin/python scripts/derive_deck_concept.py --decks cardrush_1342,cardrush_1439,... \
      --field tcgportal_bonney,cardrush_1454,... --n 8 --out db/deck_concepts.json
"""
import argparse, sys, json, random, re
from pathlib import Path
import multiprocessing as mp
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from scripts.deploy_counter import _mk_factory, _ana

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
_CARDS = json.load(open(ROOT / "db" / "cards.json"))
_CLIST = _CARDS if isinstance(_CARDS, list) else _CARDS.get("cards", [])
_COST = {c["card_id"]: (c.get("cost") or 0) for c in _CLIST}


def _dl(s):
    return DeckList.from_json(ROOT / "decks" / f"{s}.json", _REPO)


def _p0_log(g):
    log = getattr(g, "log", []) or []
    cur, out = "P0", []
    for ln in log:
        m = re.match(r"T\d+ (P[01]):", ln)
        if m:
            cur = m.group(1)
        if cur == "P0":
            out.append(ln)
    return "\n".join(out), log


def _axes(g):
    """1ゲームの P0(=対象デッキ)の汎用 win-condition 軸。 clean な計数。"""
    t, full = _p0_log(g)
    dons = [int(x) for x in re.findall(r"active=(\d+)", t)]
    # cost別 play 計数
    plays = re.findall(r"play: .+ \(cost (\d+)", t)
    play_costs = [int(c) for c in plays]
    big = sum(1 for c in play_costs if c >= 7)
    cheap = sum(1 for c in play_costs if c <= 2)
    return dict(
        ramp_maxdon=max(dons) if dons else 0,          # DON 経済の到達点 (ramp)
        big_body=big,                                  # 特大 threat 展開
        go_wide=len(play_costs),                       # 総展開数 (横/物量)
        cheap_flood=cheap,                             # 軽量物量 (aggro/go-wide)
        removal=t.count("をKO") + t.count("KO:") + t.count("レストにする"),  # 相手盤面 denial
        face_pump=t.count("attach don to leader"),     # leader 強化 (攻め/詰め)
        leader_atk=t.count("-> ") and len(re.findall(r"atk: .+リーダー", "\n".join(full))) or 0,
        life_to_hand=t.count("ライフ") and (t.count("ライフ上") + t.count("ライフを手札")) or 0,  # 受け/recovery
        block=t.count("blocked") + t.count("ブロッカー"),  # 防御
    )


def _gen(task):
    deck, opp, n, seed = task
    rep = run_matchup(_dl(deck), _dl(opp), n_games=n, seed=seed, keep_logs=True,
                      ai_factory_1=_mk_factory(deck, None, 16, 10), ai_factory_2=_mk_factory(opp, None, 16, 10),
                      deck1_analysis=_ana(deck), deck2_analysis=_ana(opp), effects_overlay=_OV)
    W, L = [], []
    for g in rep.games:
        (W if g.winner == 0 else L).append(_axes(g))
    return (deck, W, L)


AXES = ["ramp_maxdon", "big_body", "go_wide", "cheap_flood", "removal", "face_pump", "leader_atk", "life_to_hand", "block"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", required=True)
    ap.add_argument("--field", default="tcgportal_bonney,cardrush_1454,tcgportal_calgara,cardrush_1453,cardrush_1392,cardrush_1455")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default="db/deck_concepts.json")
    a = ap.parse_args()
    decks = [s.strip() for s in a.decks.split(",")]
    field = [s.strip() for s in a.field.split(",")]
    tasks = [(d, opp, a.n, a.seed) for d in decks for opp in field if opp != d]
    print(f"derive concept: {len(decks)} decks x {len(field)} field | tasks={len(tasks)}", flush=True)
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_gen, tasks, chunksize=1)
    # aggregate per deck
    agg = {d: {"W": [], "L": []} for d in decks}
    for deck, W, L in res:
        agg[deck]["W"].extend(W); agg[deck]["L"].extend(L)
    out = {}
    for d in decks:
        W, L = agg[d]["W"], agg[d]["L"]
        nW, nL = len(W), len(L)
        wr = nW / max(1, nW + nL)
        sig = {}
        for ax in AXES:
            aw = sum(r[ax] for r in W) / max(1, nW)
            al = sum(r[ax] for r in L) / max(1, nL)
            allv = [r[ax] for r in W + L]
            mean = sum(allv) / max(1, len(allv))
            var = sum((x - mean) ** 2 for x in allv) / max(1, len(allv))
            sd = var ** 0.5 or 1.0
            sig[ax] = {"win_avg": round(aw, 2), "loss_avg": round(al, 2), "z_diff": round((aw - al) / sd, 2)}
        # concept = win と最も相関する軸 top3 (z_diff)
        top = sorted(AXES, key=lambda ax: -sig[ax]["z_diff"])[:3]
        out[d] = {"winrate": round(wr, 3), "n": nW + nL, "win_corr_axes": top, "signature": sig}
        print(f"{d:18} wr={wr*100:4.0f}% concept軸(top3 win-corr)= {top}", flush=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\nsaved → {a.out}", flush=True)


if __name__ == "__main__":
    main()
