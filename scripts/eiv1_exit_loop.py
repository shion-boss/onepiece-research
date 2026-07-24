"""EIV1-ExIt 複利ループ = 探索→蒸留→探索↑ を自律反復 — 2026-07-24。

1 ラウンド = collect(探索の初手ランキングを記録) → train(policy 蒸留) → 定期 arena。
policy が更新されると次の collect の hero がそれで探索を導く (on-policy ExIt) → 良い出発点から
探索 → より良い教師 → policy↑ → …。 = コツコツ回すほど強くなる複利ループ。 人間の指摘不要。

⚠ 複利の成立条件 (研究の統合):
  ① 探索が現モデルより良い判断を出す (beam+engine+value) — 満たす
  ② その判断を蒸留 (policy head) — この loop の本体
  ③ 不完全情報の cycling 回避 — 世代窓 opp-mix (eiv1_collect 側で実装済)

再現性: seed は round+base で決定的、 exit_corpus は append-only、 exit_policy.pkl は上書き +
manifest 履歴。 crash 後は同コマンド再実行で継続。

  .venv/bin/python scripts/eiv1_exit_loop.py --rounds 8 --games 150 --workers 8
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
EIV1_DIR = ROOT / "db" / "eiv1"
POLICY = EIV1_DIR / "exit_policy.pkl"
EXIT_MANIFEST = EIV1_DIR / "exit_manifest.json"


def _run(args):
    subprocess.run([PY, *args], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--games", type=int, default=150)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--exit-policy-w", type=float, default=0.6,
                    help="collect 時に現 policy で探索を導く強さ (on-policy ExIt)")
    ap.add_argument("--beam-width", type=int, default=8)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--arena-every", type=int, default=4)
    ap.add_argument("--arena-n", type=int, default=120, help="policy on/off A/B の 1 seat ゲーム数")
    ap.add_argument("--arena-deck", default="cardrush_1454")
    a = ap.parse_args()

    print(f"=== ExIt loop: rounds={a.rounds} games/round={a.games} temp={a.temperature} ===",
          flush=True)
    for r in range(1, a.rounds + 1):
        print(f"\n----- round {r}/{a.rounds} -----", flush=True)
        # policy がまだ無い初回は素の探索 (W=0)、 以降は現 policy で on-policy に
        w = a.exit_policy_w if POLICY.exists() else 0.0
        _run(["scripts/eiv1_exit_collect.py", "--games", str(a.games), "--workers", str(a.workers),
              "--temperature", str(a.temperature), "--exit-policy-w", str(w),
              "--beam-width", str(a.beam_width), "--max-depth", str(a.max_depth)])
        _run(["scripts/eiv1_exit_train.py"])
        # 定期 arena: policy on vs off (同 value、 flag だけ差) を配備忠実で A/B
        if a.arena_every and r % a.arena_every == 0 and POLICY.exists():
            print(f"  arena: exit_policy_w={a.exit_policy_w} vs 0 (同 value、 policy の純効果)",
                  flush=True)
            import os
            env = dict(os.environ, AB_SLUG=a.arena_deck, AB_FLAG="_exit_policy_w",
                       AB_VALUE=str(a.exit_policy_w), AB_N=str(a.arena_n), AB_WORKERS=str(a.workers))
            subprocess.run([PY, "scripts/ab_flag.py"], env=env, check=False)

    print("\n=== ExIt loop 完了 ===", flush=True)
    if EXIT_MANIFEST.exists():
        try:
            h = json.loads(EXIT_MANIFEST.read_text(encoding="utf-8")).get("history", [])
            print("policy 蒸留の推移 (top-1 = 探索の最善手を再現する率):", flush=True)
            for e in h[-8:]:
                print(f"  iter{e['iter']:>3} 判断={e['decisions']:>6} "
                      f"top-1={e.get('top1')} (rand {e.get('rand')})", flush=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
