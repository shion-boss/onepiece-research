# -*- coding: utf-8 -*-
"""deck非依存 value GBM の汎化 de-risk (offline)。

多様デッキ pool で greedy self-play → (board特徴 ++ deck特徴, 勝敗) を収集 →
TRAIN デッキで GBM 学習 → **HELD-OUT デッキ (= 訓練に一度も出ないデッキ)** で AUC を測り
「予測器として deck をまたいで汎化するか」 を確認する。

判定:
  - held-out-deck AUC ≈ train-val AUC かつ ≫ 0.5 → deck非依存 value は汎化する
    (= ユーザーデッキにも learned value が効く見込み = board_eval degrade を脱せる)。
  - held-out AUC が崩れる → deck に overfit = 汎化しない (= 正直な negative)。
比較: deck特徴あり vs board-only (= deck特徴なし) で held-out AUC を比べ、 deck条件付けの寄与を見る。

  VA_TRAIN_GAMES=3000 VA_HELD_GAMES=1000 VA_WORKERS=8 .venv/bin/python scripts/value_agnostic.py
"""
import os, sys, json, random, time, statistics
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action, GreedyAI
from engine.gbm_value import features as board_features, _card_potency

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
_COLORS = ["赤", "青", "緑", "紫", "黒", "黄"]
_DF_CACHE = {}
_DECK_CACHE = {}


def _deck(slug):
    if slug not in _DECK_CACHE:
        _DECK_CACHE[slug] = json.loads(
            (REPO_ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8"))
    return _DECK_CACHE[slug]


def deck_features(slug):
    """デッキの静的特徴ベクトル (= 色/カーブ/カウンター密度/構成比/パワー)。"""
    if slug in _DF_CACHE:
        return _DF_CACHE[slug]
    d = _deck(slug)
    lead = _REPO.get(d.get("leader")) if d.get("leader") else None
    lead_colors = set(getattr(lead, "color", []) or []) if lead else set()
    costs, powers = [], []
    counters = counter1 = counter2 = n_char = n_event = n_stage = n_block = total = 0
    for c in d.get("main", []):
        cid = c.get("card_id") if isinstance(c, dict) else c
        cnt = c.get("count", 1) if isinstance(c, dict) else 1
        cd = _REPO.get(cid)
        if cd is None:
            continue
        total += cnt
        costs += [getattr(cd, "cost", 0) or 0] * cnt
        powers += [getattr(cd, "power", 0) or 0] * cnt
        cat = str(getattr(cd, "category", "") or "").lower()
        if "char" in cat:
            n_char += cnt
        elif "event" in cat:
            n_event += cnt
        elif "stage" in cat:
            n_stage += cnt
        ctr = getattr(cd, "counter", 0) or 0
        counters += ctr * cnt
        counter1 += cnt if ctr == 1000 else 0
        counter2 += cnt if ctr == 2000 else 0
        n_block += cnt if getattr(cd, "is_blocker", False) else 0
    t = max(1, total)
    fr = lambda lo, hi: sum(1 for x in costs if lo <= x <= hi) / max(1, len(costs))
    feats = [
        statistics.mean(costs) if costs else 0, max(costs) if costs else 0,
        fr(0, 1), fr(2, 3), fr(4, 5), fr(6, 7), fr(8, 99),
        n_char / t, n_event / t, n_stage / t, n_block / t,
        counters / t, counter1 / t, counter2 / t,
        (statistics.mean(powers) if powers else 0) / 1000.0,
    ] + [1.0 if c in lead_colors else 0.0 for c in _COLORS]
    _DF_CACHE[slug] = feats
    return feats


def deck_recovery(slug):
    """デッキの recovery 密度 (= life→hand/heal 効果数、 control/aggro の archetype gate 信号)。
    gbm_value._zone_potency と同義 (= main deck + leader 全カードの recovery 計数、 ほぼ静的)。"""
    d = _deck(slug)
    pot = _card_potency()
    rec = 0
    for c in d.get("main", []):
        cid = c.get("card_id") if isinstance(c, dict) else c
        cnt = c.get("count", 1) if isinstance(c, dict) else 1
        v = pot.get(cid)
        if v:
            rec += v[1] * cnt
    lead = d.get("leader")
    if lead and pot.get(lead):
        rec += pot[lead][1]
    return rec


def _collect_game(task):
    """1 ゲーム greedy self-play。 各ターン頭で両者の (board++deck) 特徴をサンプル、
    終局の勝敗をラベルにして返す。 戻り値 = [(feat_vector, label), ...]。"""
    seed, slug_a, slug_b = task
    da, db = make_deck_from_dict(_deck(slug_a), _REPO), make_deck_from_dict(_deck(slug_b), _REPO)
    fp = seed % 2
    state = setup_game(da, db, rng=random.Random(seed), first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    # 収集 pilot: greedy (既定、 速い) or exploitbeam (= 強い、 aggro も上手く回す → 状態品質↑、 遅い)。
    if os.environ.get("VA_PILOT") == "exploitbeam":
        from engine.exploit_beam_ai import ExploitBeamAI
        ais = [ExploitBeamAI(rng=random.Random(seed * 5 + 1), deck_analysis={"deck_slug": slug_a}),
               ExploitBeamAI(rng=random.Random(seed * 7 + 3), deck_analysis={"deck_slug": slug_b})]
    else:
        ais = [GreedyAI(rng=random.Random(seed * 5 + 1)), GreedyAI(rng=random.Random(seed * 7 + 3))]
    dfa, dfb = deck_features(slug_a), deck_features(slug_b)
    samples = []  # (board_p0, board_p1, turn_idx)
    last_tp = None
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        if cur != last_tp:  # 手番が変わった = ターン頭付近 → サンプル
            try:
                samples.append((board_features(state, 0, rich=True),
                                board_features(state, 1, rich=True)))
            except Exception:
                pass
            last_tp = cur
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    w = getattr(state, "winner", -1)
    if w not in (0, 1):
        return []
    out = []
    for b0, b1 in samples:
        out.append((b0 + dfa, 1 if w == 0 else 0))
        out.append((b1 + dfb, 1 if w == 1 else 0))
    return out


def _gen_tasks(slugs, n, seed0):
    rng = random.Random(seed0)
    return [(seed0 + i, *rng.sample(slugs, 2)) for i in range(n)]


def _collect(slugs, n, workers, seed0):
    tasks = _gen_tasks(slugs, n, seed0)
    with mp.Pool(workers) as p:
        chunks = p.map(_collect_game, tasks, chunksize=32)
    return [s for c in chunks for s in c]


def main():
    workers = int(os.environ.get("VA_WORKERS", "8"))
    n_train = int(os.environ.get("VA_TRAIN_GAMES", "3000"))
    n_held = int(os.environ.get("VA_HELD_GAMES", "1000"))
    pool = sorted(p.stem for p in (REPO_ROOT / "decks").glob("cardrush_*.json")
                  if ".analysis" not in p.name and ".target" not in p.name)
    rng = random.Random(42)
    rng.shuffle(pool)
    n_held_decks = max(6, len(pool) // 5)
    held_decks, train_decks = pool[:n_held_decks], pool[n_held_decks:]
    # archetype cluster filter (= per-archetype value): recovery 密度で control/aggro を分けて学習。
    # VA_RECOVERY_MAX=11 で aggro(非control)、 VA_RECOVERY_MIN=12 で control。 split は full pool
    # seed-42 で固定 (= eval_agnostic_value と held 一致)、 その後に cluster で絞る。
    rmax = os.environ.get("VA_RECOVERY_MAX")
    rmin = os.environ.get("VA_RECOVERY_MIN")
    if rmax is not None or rmin is not None:
        lo = float(rmin) if rmin is not None else -1.0
        hi = float(rmax) if rmax is not None else 1e9
        keep = lambda s: lo <= deck_recovery(s) <= hi
        train_decks = [s for s in train_decks if keep(s)]
        held_decks = [s for s in held_decks if keep(s)]
        print(f"recovery cluster [{lo},{hi}]")
    print(f"pool={len(pool)} decks | train={len(train_decks)} held-out={len(held_decks)}")
    print(f"held-out decks: {held_decks}")

    t0 = time.time()
    train_data = _collect(train_decks, n_train, workers, 1000)
    held_data = _collect(held_decks, n_held, workers, 900000)
    print(f"collected: train {len(train_data)} samples / held {len(held_data)} samples "
          f"({time.time()-t0:.0f}s)")

    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    Xtr = np.array([f for f, _ in train_data]); ytr = np.array([y for _, y in train_data])
    Xhd = np.array([f for f, _ in held_data]); yhd = np.array([y for _, y in held_data])
    # train-val split (= in-distribution 汎化の基準)
    idx = np.arange(len(Xtr)); np.random.RandomState(0).shuffle(idx)
    cut = int(len(idx) * 0.9)
    tr, va = idx[:cut], idx[cut:]
    n_board = Xtr.shape[1] - len(deck_features(train_decks[0]))  # board特徴の次元数

    def _fit_eval(use_deck):
        sl = slice(None) if use_deck else slice(0, n_board)  # board=先頭 n_board 次元
        clf = GradientBoostingClassifier(n_estimators=200, max_depth=3,
                                         learning_rate=0.05, subsample=0.8)
        clf.fit(Xtr[tr][:, sl], ytr[tr])
        auc_val = roc_auc_score(ytr[va], clf.predict_proba(Xtr[va][:, sl])[:, 1])
        auc_held = roc_auc_score(yhd, clf.predict_proba(Xhd[:, sl])[:, 1])
        return auc_val, auc_held

    print("=== 汎化 de-risk 結果 (AUC: 1.0=完璧 0.5=でたらめ) ===")
    for label, use_deck in [("deck特徴あり", True), ("board-only", False)]:
        av, ah = _fit_eval(use_deck)
        print(f"  {label:<12} train-val(同分布) {av:.3f} | held-out-deck(訓練外) {ah:.3f}  "
              f"差 {av-ah:+.3f}")
    print("判定: held-out AUC が train-val に近く ≫0.5 なら deck非依存 value は汎化 (= user deck に効く見込み)")

    # Phase B: board-only deck非依存 GBM を train データ全体で学習し pkl 保存 (= held-out 未学習)。
    # n_features_in_=n_board(=rich21) なので gbm_value.gbm_score が rich 特徴で自動推論する。
    save_path = os.environ.get("VA_SAVE")
    if save_path:
        import pickle
        clf = GradientBoostingClassifier(n_estimators=200, max_depth=3,
                                         learning_rate=0.05, subsample=0.8)
        clf.fit(Xtr[:, :n_board], ytr)
        with open(save_path, "wb") as f:
            pickle.dump(clf, f)
        print(f"saved board-only agnostic GBM ({n_board} feat, {len(Xtr)} samples, "
              f"train {len(train_decks)} decks) -> {save_path}")
        print(f"held-out decks (= A/B 対象): {held_decks}")


if __name__ == "__main__":
    main()
