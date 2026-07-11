# -*- coding: utf-8 -*-
"""アーキタイプ(leader)別の「手札特徴 採用率 prior」を実大会レシピから構築 (2026-07-11、 ohtsuki 案)。

手札予測を self-play でなく **デッキのデータ(採用率)を根拠に** する土台。 各 leader について
その deck が平均何枚 速攻キャラ / 2000+カウンター / ブロッカー / 除去 を積むかを実レシピから集計。
→ 相手 leader が分かれば「そのデッキが速攻/大型カウンターをどれだけ持つか」の基準率が出る。
これに turn/引いた枚数/見えた札 を掛けて P(今 手札に特徴Fを持つ) を推定 (= 条件付き最適手の土台)。

出力: db/deck_feature_priors.json = {leader_id: {feature: E[deck採用枚数], "_n": レシピ数, "_deck_size": 平均}}

  .venv/bin/python scripts/build_feature_priors.py
"""
import json, glob, os, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")

# 大型除去 (KO/バウンス) をテキストで粗く検出
_REMOVAL_KW = ("KO", "手札に戻", "デッキの下", "レストに", "コストを-")


def _feat(cid):
    c = _REPO.get(cid)
    if not c:
        return None
    txt = c.text or ""
    cat = str(getattr(getattr(c, "category", None), "value", "")).upper()
    counter = int(getattr(c, "counter", 0) or 0)
    return dict(
        rush=("速攻" in txt) and cat == "CHARACTER",
        blocker=("ブロッカー" in txt),
        counter2000=counter >= 2000,
        counter_event=(cat == "EVENT" and counter >= 1000),
        removal=(cat in ("EVENT", "CHARACTER") and any(k in txt for k in _REMOVAL_KW)),
        cat=cat, cost=int(c.cost or 0),
    )


def _cards_of(recipe):
    cards = recipe.get("main") or recipe.get("cards") or recipe.get("main_deck") or []
    out = []
    for e in cards:
        if isinstance(e, dict):
            cid = e.get("card_id") or e.get("card_number") or e.get("number")
            n = e.get("count", 1)
        else:
            cid, n = e, 1
        if cid:
            out.append((cid, n))
    return out


def _leader_id(recipe):
    l = recipe.get("leader") or recipe.get("leader_id")
    if isinstance(l, dict):
        return l.get("card_id") or l.get("card_number")
    return l


def main():
    recipes = glob.glob(str(ROOT / "decks" / "cardrush_*.json")) + \
        glob.glob(str(ROOT / "decks" / "_archive" / "cardrush_raw" / "*.json"))
    FEATS = ["rush", "blocker", "counter2000", "counter_event", "removal"]
    by_leader = defaultdict(list)
    for f in recipes:
        try:
            d = json.loads(open(f, encoding="utf-8").read())
        except Exception:
            continue
        leader = _leader_id(d)
        if not leader:
            continue
        acc = {k: 0 for k in FEATS}
        size = 0
        for cid, n in _cards_of(d):
            info = _feat(cid)
            if not info:
                continue
            size += n
            for k in FEATS:
                if info.get(k):
                    acc[k] += n
        by_leader[leader].append((acc, size))

    out = {}
    for leader, rows in by_leader.items():
        n = len(rows)
        prof = {k: round(sum(a[k] for a, _ in rows) / n, 2) for k in FEATS}
        prof["_n"] = n
        prof["_deck_size"] = round(sum(s for _, s in rows) / n, 1)
        out[leader] = prof
    path = ROOT / "db" / "deck_feature_priors.json"
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"レシピ {len(recipes)}件 → leader {len(out)}種 の特徴採用 prior → {path}")
    # 上位表示
    for leader, prof in sorted(out.items(), key=lambda x: -x[1]["rush"])[:8]:
        nm = _REPO.get(leader).name if _REPO.get(leader) else leader
        print(f"  {str(nm)[:12]:12s}: 速攻{prof['rush']:.1f} 2000c{prof['counter2000']:.1f} "
              f"cEvent{prof['counter_event']:.1f} ブロッカ{prof['blocker']:.1f} 除去{prof['removal']:.1f} (n={prof['_n']})")


if __name__ == "__main__":
    main()
