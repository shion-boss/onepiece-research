# -*- coding: utf-8 -*-
"""lockstep board-equality diff を 広デッキプール (archive 含む 441 cards) に当てて
16プール外カードの 人間modal解決 vs AI解決 のズレを探す (= 2026-06-05、 lockstep×広カバレッジ)。"""
import sys, glob, json
from pathlib import Path
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import lockstep_human_vs_ai as L

# slug -> path map (= decks/ 以下 全 json を再帰収集)。 ⚠ key は **parentdir/filename** で
# unique 化 (= 各リーダー dir の variant_0.json を dedup せず全部テスト、 325 decks/667 cards)。
import os
pathmap = {}
for root, _, fns in os.walk("decks"):
    for fn in fns:
        if fn.endswith(".json") and "analysis" not in fn:
            key = os.path.join(os.path.basename(root), fn.replace(".json", ""))
            pathmap[key] = os.path.join(root, fn)

_orig_load = L._load


def _patched_load(slug):
    fn = pathmap.get(slug)
    if fn is None:
        return _orig_load(slug)
    dl = L.DeckList.from_json(fn, L.repo)
    ap = fn.replace(".json", ".analysis.json")
    ana = json.load(open(ap)) if Path(ap).exists() else None
    return dl, ana


L._load = _patched_load

# loadable な slug のみ
slugs = []
for slug, fn in pathmap.items():
    try:
        L.DeckList.from_json(fn, L.repo)
        slugs.append(slug)
    except Exception:
        pass
print(f"loadable decks: {len(slugs)}", flush=True)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    divergences = []
    stats = {"compared": 0}
    crashes = []
    for i, a in enumerate(slugs):
        b = slugs[(i + 1) % len(slugs)]
        for s in range(n):
            try:
                L.run(a, b, 4000 + s, divergences, stats)
            except Exception as e:  # noqa: BLE001
                import traceback
                crashes.append((a, b, 4000 + s, f"{type(e).__name__}: {e}",
                                traceback.format_exc().splitlines()[-1][:80]))
        if i % 20 == 0:
            print(f"  ... {i}/{len(slugs)} | compared {stats['compared']} | div {len(divergences)} crash {len(crashes)}", flush=True)
    print(f"\n=== 広プール lockstep {len(slugs)} decks ===")
    print(f"比較した解決: {stats['compared']}")
    print(f"盤面ズレ: {len(divergences)}")
    for d in divergences[:40]:
        print(f"  [ズレ] {d['slug']} seed{d['seed']} {d['kind']}: {d['div'][:90]}")
    if crashes:
        print(f"\ncrash: {len(crashes)}")
        for c in crashes[:15]:
            print("  ", c[:4], "|", c[4])
    sys.exit(1 if (divergences or crashes) else 0)


if __name__ == "__main__":
    main()
