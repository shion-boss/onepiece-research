# -*- coding: utf-8 -*-
"""lockstep board-equality diff を **pool-pick 偏重** 合成デッキに当てる (= 2026-06-05)。

合成ランダムデッキは pool-pick modal の誘発密度が低い (88 deck × 4g で比較 12 件のみ)。
そこで overlay に pool-pick primitive (play_from_hand / play_from_trash /
play_from_hand_or_trash / search / summon_from_deck / search_from_trash /
play_from_hand_choice) を持つ 357 カードだけで 色ごとに 50枚デッキを満たし、
人間modal解決 vs AI解決 の盤面ズレを高密度で検証する。"""
import sys, json
from collections import defaultdict
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import lockstep_human_vs_ai as L
from engine.deck import make_deck_from_dict

POOL_PICK_PRIMS = {"summon_from_deck", "search", "play_from_trash", "play_from_hand",
                   "play_from_hand_choice", "search_from_trash", "play_from_hand_or_trash"}


def _walk_keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in POOL_PICK_PRIMS:
                yield k
            yield from _walk_keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_keys(v)


ov = json.load(open("db/card_effects.json"))
ov_items = ov.items() if isinstance(ov, dict) else [(e.get("card_id"), e) for e in ov]
poolpick_ids = {cid for cid, e in ov_items if any(True for _ in _walk_keys(e))}

cards = json.load(open("db/cards.json"))
cardlist = cards if isinstance(cards, list) else cards.get("cards", [])
by_id = {c["card_id"]: c for c in cardlist}

# 色ごとに leader と pool-pick カードを分類
leaders = defaultdict(list)
pp_by_color = defaultdict(list)
for c in cardlist:
    cols = str(c.get("color", "")).split("/")
    for cc in cols:
        if not cc:
            continue
        if c.get("category") == "LEADER":
            leaders[cc].append(c["card_id"])
        elif c["card_id"] in poolpick_ids:
            pp_by_color[cc].append(c["card_id"])

# 各色: pool-pick カードだけで 50枚デッキを満たす (足りなければ count で水増し)
dmap = {}
for col, ids in pp_by_color.items():
    if col not in leaders or not leaders[col] or not ids:
        continue
    # 50枚を round-robin で満たす (= 全 pool-pick カードを最低1枚、 端数は先頭から +count)
    counts = {cid: 1 for cid in ids[:50]}
    used = ids[:50]
    i = 0
    while sum(counts.values()) < 50:
        counts[used[i % len(used)]] += 1
        i += 1
    name = f"pp_{col}"
    dd = {"leader": leaders[col][0], "name": name,
          "main": [{"card_id": cid, "count": n} for cid, n in counts.items()]}
    try:
        dmap[name] = make_deck_from_dict(dd, L.repo)
    except Exception as e:  # noqa: BLE001
        print(f"  skip {name}: {e}")

slugs = list(dmap.keys())
_orig_load = L._load


def _patched_load(slug):
    dl = dmap.get(slug)
    return (dl, None) if dl is not None else _orig_load(slug)


L._load = _patched_load
print(f"pool-pick 偏重デッキ: {len(slugs)} (色) | pool-pick カード {len(poolpick_ids)}", flush=True)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    divergences = []
    stats = {"compared": 0}
    crashes = []
    for i, a in enumerate(slugs):
        for j, b in enumerate(slugs):  # 全 色ペア (= leader/色 の交差も網羅)
            for s in range(n):
                try:
                    L.run(a, b, 80000 + s, divergences, stats)
                except Exception as e:  # noqa: BLE001
                    import traceback
                    crashes.append((a, b, 80000 + s, f"{type(e).__name__}: {e}",
                                    traceback.format_exc().splitlines()[-1][:80]))
        print(f"  ... {i}/{len(slugs)} | compared {stats['compared']} | "
              f"div {len(divergences)} crash {len(crashes)}", flush=True)
    print(f"\n=== pool-pick 偏重 lockstep {len(slugs)} decks ===")
    print(f"比較した解決: {stats['compared']}")
    print(f"盤面ズレ: {len(divergences)}")
    for d in divergences[:60]:
        print(f"  [ズレ] {d['slug']} seed{d['seed']} {d['kind']}: {d['div'][:100]}")
    if crashes:
        print(f"\ncrash: {len(crashes)}")
        for c in crashes[:20]:
            print("  ", c[:4], "|", c[4])
    sys.exit(1 if (divergences or crashes) else 0)


if __name__ == "__main__":
    main()
