# -*- coding: utf-8 -*-
"""「盤面→相手手札」予測器の学習 (2026-07-11、 ohtsuki 案)。

collect_hand_data.py の (観測特徴, 実手札) から、 各 deck カードについて
**E[そのカードが手札にある枚数 | 観測特徴]** を回帰学習。 特徴 = ohtsuki の信号:
  turn(タイミング) / このカードの board枚数・trash枚数(場・墓地) / deck採用枚数 /
  hand_size / 場・墓地総数 / DON / life / カードの cost・category(役割 proxy)。
出力: db/hand_predictor_<deck>.pkl = {model, cards, card_meta}。 determinize で手札サンプルの重みに使う。

  .venv/bin/python scripts/train_hand_predictor.py --deck cardrush_1454
"""
import argparse, json, os, pickle, sys
from collections import Counter
from pathlib import Path
import numpy as np

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_CAT = {"CHARACTER": 0, "EVENT": 1, "STAGE": 2, "LEADER": 3}


_META = {}  # card_id -> (cost, category, counter) — deck から埋める


def _card_meta(card_id):
    return _META.get(card_id, (0, "", 0))


def _deck_cards(slug):
    d = json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8"))
    dk = make_deck_from_dict(d, _REPO)
    cnt = Counter()
    for c in dk.main:
        cid = c.card_id
        cnt[cid] += 1
        cat = getattr(getattr(c, "category", None), "value", None) or str(getattr(c, "category", ""))
        _META[cid] = (int(getattr(c, "cost", 0) or 0), str(cat).upper(),
                      int(getattr(c, "counter", 0) or 0))
    return dict(cnt)  # card_id -> deck採用枚数


def _n_counters_in_trash(feat):
    """トラッシュにある「カウンター札」の枚数 (= 使ったカウンター proxy)。"""
    tc = feat.get("trash_counts", {})
    return sum(n for cid, n in tc.items() if _META.get(cid, (0, "", 0))[2] >= 1000)


def _row(feat, cid, deck_count):
    cost, cat, counter = _card_meta(cid)
    bc = feat.get("board_counts", {}).get(cid, 0)
    tc = feat.get("trash_counts", {}).get(cid, 0)
    af = feat.get("attacks_faced", 0)
    n_ctr = _n_counters_in_trash(feat)
    return [
        feat["turn"], bc, tc, deck_count, feat["hand_size"],
        feat.get("n_board", 0), feat.get("n_trash", 0),
        feat.get("don_active", 0), feat.get("don_rested", 0), feat.get("life", 0),
        cost, 1 if cat == "EVENT" else 0, 1 if cat == "CHARACTER" else 0, 1 if cat == "STAGE" else 0,
        # === behavioral (ohtsuki): 受けた攻撃数 / このカードのcounter値 / 使ったカウンター数 /
        #     断った推定(受けた攻撃 - 使ったカウンター)。 counter札で「機会多いのに未使用→手札に無い」を学ぶ ===
        af, counter, n_ctr, max(0, af - n_ctr),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1454")
    ap.add_argument("--data", default=None)
    a = ap.parse_args()
    data = a.data or f"db/_analyst/hand_data_{a.deck}.jsonl"
    rows = [json.loads(l) for l in open(data, encoding="utf-8")]
    deck_counts = _deck_cards(a.deck)
    cards = sorted(deck_counts.keys())
    X, y = [], []
    for feat in rows:
        hand_cnt = Counter(feat["hand"])
        for cid in cards:
            X.append(_row(feat, cid, deck_counts[cid]))
            y.append(hand_cnt.get(cid, 0))  # このカードが手札に何枚あるか
    X = np.array(X, dtype=float); y = np.array(y, dtype=float)
    print(f"{a.deck}: {len(rows)} 局面 × {len(cards)} カード = {len(X)} 行, 平均手札枚数/カード {y.mean():.3f}")
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import cross_val_score
    m = GradientBoostingRegressor(n_estimators=250, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0)
    cv = cross_val_score(m, X, y, cv=4, scoring="r2")
    print(f"CV R2 (E[手札枚数]回帰): {cv.mean():.3f} +/- {cv.std():.3f}  (>0 で盤面から手札を予測できている)")
    m.fit(X, y)
    out = f"db/hand_predictor_{a.deck}.pkl"
    pickle.dump({"model": m, "cards": cards, "deck_counts": deck_counts,
                 "card_meta": {c: _META.get(c, (0, "", 0)) for c in cards},
                 "feat_version": "v2_behavioral"}, open(out, "wb"))
    print(f"保存: {out}")


if __name__ == "__main__":
    main()
