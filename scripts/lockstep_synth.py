# -*- coding: utf-8 -*-
"""lockstep board-equality diff を 合成デッキ (~4,200 カード網羅) に当てて、 16プール外の
大量の pool-pick カード (search/summon/play_from_trash/reveal 系) の 人間modal解決 vs
AI解決 のズレを探す (= 2026-06-05、 最強オラクル × 最大カバレッジ)。

第1引数 = pair毎の試合数、 第2引数 = arrange seed (hunt_synth のカードシャッフル)。
hunt_synth.synth_decks をそのまま流用 (= 色ごと×全カード網羅の 50枚デッキ群)。"""
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import lockstep_human_vs_ai as L
import hunt_synth as H  # import 時に sys.argv[2] (arrange) を読んで H.synth_decks を構築

# slug -> DeckList map (= 合成デッキ)。 lockstep の _load を差し替えて使う。
dmap = {na: dl for na, dl in H.synth_decks}
slugs = list(dmap.keys())

_orig_load = L._load


def _patched_load(slug):
    dl = dmap.get(slug)
    if dl is None:
        return _orig_load(slug)
    return dl, None  # analysis は無し (= 合成デッキ)


L._load = _patched_load
print(f"合成デッキ lockstep: {len(slugs)} decks", flush=True)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    divergences = []
    stats = {"compared": 0}
    crashes = []
    for i, a in enumerate(slugs):
        b = slugs[(i + 1) % len(slugs)]
        for s in range(n):
            try:
                L.run(a, b, 70000 + s, divergences, stats)
            except Exception as e:  # noqa: BLE001
                import traceback
                crashes.append((a, b, 70000 + s, f"{type(e).__name__}: {e}",
                                traceback.format_exc().splitlines()[-1][:80]))
        if i % 10 == 0:
            print(f"  ... {i}/{len(slugs)} | compared {stats['compared']} | "
                  f"div {len(divergences)} crash {len(crashes)}", flush=True)
    print(f"\n=== 合成デッキ lockstep {len(slugs)} decks ===")
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
