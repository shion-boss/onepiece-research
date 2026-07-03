"""16-pool 全デッキに block_residual value(塊帰結+v11threat+残差アンカー+centering)を
自律展開する fleet grind。 各デッキ: build → A/B gate → 非負なら配備。 per-deck checkpoint で resumable。

docs/block_value_architecture.md の勝ち構成を fleet 化。 cardrush_1454(+7)/tcgportal_calgara(+2.5)で
deck-generality 確認済 → 残り 14 デッキへ。 block_residual は floor 付き(≈配備 value)なので
非負 gate + backup で低リスク。

  .venv/bin/python scripts/fleet_block_residual.py --n 20 --workers 12   # 全残りデッキ grind

checkpoint = db/_analyst/fleet_block_status.json(deck→{default_wr,v11cent_wr,deployed})。
再実行で done deck を skip。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
STATUS = ROOT / "db" / "_analyst" / "fleet_block_status.json"

POOL = ["cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399", "cardrush_1439",
        "cardrush_1453", "cardrush_1454", "cardrush_1455", "cardrush_1456", "tcgportal_bonney",
        "tcgportal_calgara", "tcgportal_coby", "tcgportal_corazon", "tcgportal_hancock",
        "tcgportal_op11_luffy", "tcgportal_op13_luffy"]
# A/B の相手 field(archetype spread)
AB_OPPS = ["cardrush_1454", "tcgportal_calgara", "tcgportal_bonney", "cardrush_1342"]
# build の self-play 相手(多相手で matchup variance を出す)
BUILD_OPPS = ["cardrush_1454", "tcgportal_calgara", "tcgportal_bonney", "cardrush_1342", "cardrush_1439"]


def _load_status():
    if STATUS.exists():
        return json.loads(STATUS.read_text(encoding="utf-8"))
    return {}


def _save_status(s):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def _build(deck, n_games, deploy_lam):
    pkl = ROOT / "db" / "_selfplay" / f"mcab_{deck}_v11cent.pkl"
    if pkl.exists():
        return True
    r = subprocess.run([PY, str(ROOT / "scripts" / "build_block_residual_value.py"),
                        "--deck", deck, "--opponents", *BUILD_OPPS,
                        "--n-games", str(n_games), "--deploy-lam", str(deploy_lam)])
    return r.returncode == 0 and pkl.exists()


def _ab(deck, n, workers):
    """default vs v11cent を A/B し (default_wr, v11cent_wr) を返す。"""
    opps = [o for o in AB_OPPS if o != deck] or ["cardrush_1454"]
    # mirror を必ず含める
    if deck not in opps:
        opps = [deck] + opps[:3]
    p = subprocess.run([PY, str(ROOT / "scripts" / "matchup_value_deploy_ab.py"),
                        "--deck", deck, "--arms", "default,v11cent", "--opps", ",".join(opps),
                        "--n", str(n), "--beam-width", "16", "--max-depth", "10",
                        "--workers", str(workers)],
                       capture_output=True, text=True)
    m = re.search(r"OVERALL\s+([\d.]+)\s+([\d.]+)", p.stdout)
    if not m:
        print(p.stdout[-800:]); return None
    return float(m.group(1)), float(m.group(2))


def _deploy(deck):
    live = ROOT / "db" / f"value_gbm_{deck}.pkl"
    bak = ROOT / "db" / f"value_gbm_{deck}_pre_block.pkl"
    src = ROOT / "db" / "_selfplay" / f"mcab_{deck}_v11cent.pkl"
    if not bak.exists() and live.exists():
        shutil.copy(live, bak)
    shutil.copy(src, live)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="A/B seat あたり N")
    ap.add_argument("--build-games", type=int, default=10)
    ap.add_argument("--deploy-lam", type=float, default=0.5)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--margin", type=float, default=-0.5,
                    help="v11cent_wr >= default_wr + margin で配備(floor付きなので僅かな負も許容)")
    ap.add_argument("--decks", nargs="*", default=None, help="対象 deck(既定 POOL 全部)")
    a = ap.parse_args()

    status = _load_status()
    decks = a.decks or POOL
    for deck in decks:
        st = status.get(deck, {})
        if st.get("deployed") is not None:
            print(f"[skip] {deck} 済 (default {st.get('default_wr')} / v11cent {st.get('v11cent_wr')} "
                  f"/ deployed {st.get('deployed')})", flush=True)
            continue
        t0 = time.time()
        anchor = ROOT / "db" / f"value_gbm_{deck}.pkl"
        if not anchor.exists():
            print(f"[skip] {deck} anchor 無し(agnostic path が要る)", flush=True)
            status[deck] = {"deployed": False, "reason": "no_anchor"}; _save_status(status); continue
        print(f"\n=== {deck} build ===", flush=True)
        if not _build(deck, a.build_games, a.deploy_lam):
            print(f"[fail] {deck} build", flush=True)
            status[deck] = {"deployed": False, "reason": "build_fail"}; _save_status(status); continue
        print(f"=== {deck} A/B (N={a.n}/seat) ===", flush=True)
        res = _ab(deck, a.n, a.workers)
        if res is None:
            print(f"[fail] {deck} A/B parse", flush=True)
            status[deck] = {"deployed": False, "reason": "ab_fail"}; _save_status(status); continue
        dwr, vwr = res
        deploy = vwr >= dwr + a.margin
        if deploy:
            _deploy(deck)
        status[deck] = {"default_wr": dwr, "v11cent_wr": vwr, "delta": round(vwr - dwr, 1),
                        "deployed": bool(deploy)}
        _save_status(status)
        print(f"[done] {deck}: default {dwr} -> v11cent {vwr} (Δ{vwr-dwr:+.1f}) "
              f"{'配備' if deploy else '見送り'} ({time.time()-t0:.0f}s)", flush=True)

    # サマリ
    print("\n=== fleet block_residual サマリ ===")
    dep = [d for d, s in status.items() if s.get("deployed")]
    print(f"配備 {len(dep)}/{len(status)}: " + ", ".join(
        f"{d}(Δ{status[d].get('delta','?'):+})" for d in dep))


if __name__ == "__main__":
    main()
