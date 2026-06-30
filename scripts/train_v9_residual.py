# -*- coding: utf-8 -*-
"""v9 residual-guarantee 訓練 (HARD floor): p = clip(p_v2_anchor + lam * R(38 matchup/board feat))。

ohtsuki『全デッキ同じ v に統一 + 新版は旧を下回るな (v6⊇v2 なら最低 v2 同等)』([[feedback_uniform_value_version]])。
v6 / v9-feature-anchor は corazon(win-starved 6%)で deploy regress(-5/-6pt): 38 matchup 列が rare-win を
overfit、 anchor を 1 feature にしても GBM が無視して noise に倒れる。

→ **base + correction を構造分離**: 配備 v2 を**常に全強度**で base(p_anchor)に置き、 38 列は**残差 (y-p_anchor)
のみ**を heavily-regularized regressor R で学習。 lam=0 で厳密 v2(hard floor)、 matchup が robust な時だけ R
が補正 → 構造的に v2 を下回りにくい。 wrapper dict {"kind":"v9_residual","anchor":v2,"resid":R,"lam":lam}。

収集は重い(~250s)ので raw corpus を db/_selfplay/<prefix>corpus.pkl に cache → --from-corpus で R を
lam/正則化違いで即再学習(秒)。

  .venv/bin/python scripts/train_v9_residual.py --deck tcgportal_corazon --games 300 --prefix corv9_
  .venv/bin/python scripts/train_v9_residual.py --deck tcgportal_corazon --from-corpus --lam 0.5 --prefix corv9_
"""
from __future__ import annotations
import argparse, json, os, pickle, random, sys, time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ONEPIECE_GBM_V6", "1")  # collect v6 (38) features

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.gbm_value import features, v2_anchor_value

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
DECK = "tcgportal_corazon"
OPPS = ["tcgportal_calgara"]
V2_ANCHOR = ""
BEAM_W, BEAM_D = 8, 6


def _dl(s):
    return DeckList.from_json(ROOT / "decks" / f"{s}.json", _REPO)


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


class ExploreBeamAI(ExploitBeamAI):
    def __init__(self, rng=None, deck_analysis=None, *, epsilon=0.0, **kw):
        super().__init__(rng=rng, deck_analysis=deck_analysis, **kw)
        self.epsilon = epsilon
        self._value_defense = False

    def choose_action(self, state):
        rng = self.rng or random
        if self.epsilon > 0 and rng.random() < self.epsilon:
            acts = legal_actions(state)
            if acts:
                return rng.choice(acts)
        return super().choose_action(state)


def _setup(deck_first, seed, opp):
    if deck_first:
        st = setup_game(_dl(DECK), _dl(opp), rng=random.Random(seed), first_player=0,
                        effects_overlay=_OVERLAY, deck1_analysis=_ana(DECK), deck2_analysis=_ana(opp))
        return st, 0
    st = setup_game(_dl(opp), _dl(DECK), rng=random.Random(seed), first_player=0,
                    effects_overlay=_OVERLAY, deck1_analysis=_ana(opp), deck2_analysis=_ana(DECK))
    return st, 1


def gen_one(task):
    epsilon, seed = task
    opp = OPPS[seed % len(OPPS)]
    st, ei = _setup(seed % 2 == 0, seed, opp)
    play_until_main(st)
    deck_ai = ExploreBeamAI(rng=random.Random(seed), deck_analysis={**_ana(DECK), "deck_slug": DECK},
                            epsilon=epsilon, beam_width=BEAM_W, max_depth=BEAM_D)
    opp_ai = ExploitBeamAI(rng=random.Random(seed + 7), deck_analysis={**_ana(opp), "deck_slug": opp},
                           beam_width=BEAM_W, max_depth=BEAM_D)
    ais = [None, None]; ais[ei] = deck_ai; ais[1 - ei] = opp_ai
    for i, x in enumerate(ais):
        if hasattr(x, "set_ai_opp"):
            x.set_ai_opp(ais[1 - i])
    recs = []
    n = 0
    while not st.game_over and n < 400:
        me = st.turn_player_idx
        try:
            f38 = features(st, ei, v6=True, v7=False, v8=False)        # 38 matchup/board
            pa = v2_anchor_value(st, ei, V2_ANCHOR)                    # 配備 v2 の P(win) = base
            recs.append((f38, pa))
        except Exception:
            pass
        try:
            play_one_action(st, ais[me], ais[1 - me])
        except Exception:
            break
        n += 1
    w = getattr(st, "winner", -1)
    y = 1 if w == ei else 0
    return [(f38, pa, y) for (f38, pa) in recs]


def _train_residual(X38, panchor, y, lam, min_leaf, lr, n_est, max_depth, subsample):
    """残差 R: feat38 -> (y - p_anchor)。 conservative GBR で過適合を抑える。"""
    from sklearn.ensemble import GradientBoostingRegressor
    target = [yy - pa for yy, pa in zip(y, panchor)]
    R = GradientBoostingRegressor(n_estimators=n_est, max_depth=max_depth, learning_rate=lr,
                                  subsample=subsample, min_samples_leaf=min_leaf, random_state=0)
    R.fit(X38, target)
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="tcgportal_corazon")
    ap.add_argument("--opps", default="tcgportal_calgara,cardrush_1385,cardrush_1454,cardrush_1456,cardrush_1453,cardrush_1392")
    ap.add_argument("--v2-model", default=None)
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--epsilon", type=float, default=0.15)
    ap.add_argument("--beam-width", type=int, default=8)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--prefix", default=None)
    ap.add_argument("--seed", type=int, default=20260629)
    # residual regressor の正則化 (conservative 既定)
    ap.add_argument("--lam", type=float, default=1.0, help="correction 強度。 0=厳密v2 floor")
    ap.add_argument("--r-min-leaf", type=int, default=150)
    ap.add_argument("--r-lr", type=float, default=0.03)
    ap.add_argument("--r-n-est", type=int, default=120)
    ap.add_argument("--r-max-depth", type=int, default=2)
    ap.add_argument("--r-subsample", type=float, default=0.7)
    ap.add_argument("--from-corpus", action="store_true", help="cache 済 corpus で R のみ再学習")
    a = ap.parse_args()
    global DECK, OPPS, BEAM_W, BEAM_D, V2_ANCHOR
    DECK = a.deck
    OPPS = [s.strip() for s in a.opps.split(",")]
    BEAM_W, BEAM_D = a.beam_width, a.max_depth
    V2_ANCHOR = a.v2_model or str(ROOT / "db" / f"value_gbm_{DECK}.pkl")
    prefix = a.prefix if a.prefix else f"v9_{DECK}_"
    outdir = ROOT / "db" / "_selfplay"; outdir.mkdir(exist_ok=True)
    corpus_path = outdir / f"{prefix}corpus.pkl"

    adim = pickle.load(open(V2_ANCHOR, "rb")).n_features_in_
    print(f"[v9-residual] deck={DECK} anchor={Path(V2_ANCHOR).name}({adim}dim) lam={a.lam}", flush=True)
    assert adim == 21, f"anchor must be v2 (21-dim), got {adim}"

    if a.from_corpus and corpus_path.exists():
        X38, panchor, y = pickle.load(open(corpus_path, "rb"))
        print(f"[corpus] reuse {corpus_path.name}: samples={len(X38)} pos={sum(y)}", flush=True)
    else:
        t0 = time.time()
        tasks = [(a.epsilon, a.seed + g) for g in range(a.games)]
        with mp.Pool(a.workers) as p:
            res = p.map(gen_one, tasks, chunksize=2)
        data = [r for game in res for r in game]
        X38 = [d[0] for d in data]; panchor = [d[1] for d in data]; y = [d[2] for d in data]
        pickle.dump((X38, panchor, y), open(corpus_path, "wb"))
        print(f"[collect] samples={len(X38)} pos={sum(y)}({sum(y)/max(1,len(y))*100:.0f}%) "
              f"dim={len(X38[0]) if X38 else 0} ({time.time()-t0:.0f}s) -> {corpus_path.name}", flush=True)
    assert X38 and len(X38[0]) == 38, f"expected 38-dim, got {len(X38[0]) if X38 else 0}"

    # held-out: residual 補正が calibration を改善するか (deploy proxy ではない、 sanity)
    from sklearn.metrics import roc_auc_score
    n = len(X38); cut = int(n * 0.75)
    idx = list(range(n)); random.Random(1).shuffle(idx)
    tr, te = idx[:cut], idx[cut:]
    R_cv = _train_residual([X38[i] for i in tr], [panchor[i] for i in tr], [y[i] for i in tr],
                           a.lam, a.r_min_leaf, a.r_lr, a.r_n_est, a.r_max_depth, a.r_subsample)
    yte = [y[i] for i in te]
    p_anc = [panchor[i] for i in te]
    corr = [R_cv.predict([X38[i]])[0] for i in te]
    p_v9 = [min(1.0, max(0.0, p_anc[k] + a.lam * corr[k])) for k in range(len(te))]
    import statistics
    auc_anc = roc_auc_score(yte, p_anc)
    auc_v9 = roc_auc_score(yte, p_v9)
    mean_abs_corr = statistics.mean(abs(c) for c in corr) if corr else 0.0
    print(f"[held-out] AUC anchor(v2)={auc_anc:.4f}  v9(anchor+resid)={auc_v9:.4f} (Δ{auc_v9-auc_anc:+.4f})", flush=True)
    print(f"[held-out] mean|correction|={mean_abs_corr:.4f} (0 に近い=ほぼ v2 floor / 大=積極補正)", flush=True)

    # full train + wrapper save
    R = _train_residual(X38, panchor, y, a.lam, a.r_min_leaf, a.r_lr, a.r_n_est, a.r_max_depth, a.r_subsample)
    anchor_model = pickle.load(open(V2_ANCHOR, "rb"))
    wrapper = {"kind": "v9_residual", "anchor": anchor_model, "resid": R, "lam": a.lam,
               "deck": DECK, "note": "p=clip(p_v2 + lam*R(38feat)); hard floor at v2"}
    p9 = outdir / f"{prefix}v9.pkl"
    pickle.dump(wrapper, open(p9, "wb"))
    print(f"[saved] {p9.name} (residual wrapper, anchor embedded, lam={a.lam})", flush=True)
    print(f"[next] gate: matchup_value_deploy_ab.py --deck {DECK} --prefix {prefix} --arms default,v9", flush=True)


if __name__ == "__main__":
    main()
