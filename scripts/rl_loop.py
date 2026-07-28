# -*- coding: utf-8 -*-
"""RL 自己改善ループ orchestrator (2026-07-28、 proper 版、 checkpoint/resumable)。

方策(value-policy)を rollout 教師で反復強化(DAgger + AlphaZero 型):
  各 iter: [1] 現best で self-play → rollout 教師データ収集(割引・rich・現best downstream)
           [2] 累積 corpus で value(regressor)学習
           [3] arena: 新 value-policy vs 現best
           [4] 勝てば昇格(次 iter は新policyの分布で収集=OOD 縮小)、 負けなら best 据置(データ蓄積継続)
state を db/_selfplay/rl_state.json に checkpoint → kill されても同コマンドで resume。 全ログ RL_LOG。

  RL_ITERS=4 RL_N_PER_ITER=150 RL_ARENA_N=160 RL_FEAT=v19 RL_GAMMA=0.98 RL_WORKERS=12 \
      .venv/bin/python scripts/rl_loop.py
"""
import os, sys, json, subprocess, time, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / (os.environ.get("RL_STATE") or "db/_selfplay/rl_state.json")
ITERS = int(os.environ.get("RL_ITERS", "4"))
N_PER = int(os.environ.get("RL_N_PER_ITER", "150"))
ARENA_N = int(os.environ.get("RL_ARENA_N", "160"))
FEAT = os.environ.get("RL_FEAT", "v19")
GAMMA = os.environ.get("RL_GAMMA", "0.98")
W = os.environ.get("RL_WORKERS", "12")
PY = str(ROOT / ".venv" / "bin" / "python")


def _run(cmd, env_extra):
    env = dict(os.environ); env.update(env_extra); env["OMP_NUM_THREADS"] = "1"
    print(f"  $ {' '.join(k+'='+v for k,v in env_extra.items())} {cmd[-1]}", flush=True)
    r = subprocess.run([PY] + cmd, env=env, cwd=str(ROOT), capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.strip().splitlines()[-6:]:
        print("    " + line, flush=True)
    return out


def _load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"iter": 0, "best": "ebv2", "corpora": [], "history": []}


def _save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1))


def main():
    s = _load_state()
    print(f"=== RL ループ start (iter {s['iter']}/{ITERS}, best={s['best']}) {time.strftime('%H:%M')} ===", flush=True)
    while s["iter"] < ITERS:
        it = s["iter"]
        print(f"\n########## ITER {it} (best={Path(s['best']).name if s['best']!='ebv2' else 'ebv2'}) ##########", flush=True)
        data_out = f"db/_selfplay/rl_iter{it}.jsonl"
        val_out = f"db/_selfplay/rl_value{it}.pkl"

        # [1] 収集(現best で self-play + rollout 教師)。 既存ファイルがあれば skip(resume)
        if not (ROOT / data_out).exists() or (ROOT / data_out).stat().st_size == 0:
            print(f"[1] 収集 (CB={Path(s['best']).name if s['best']!='ebv2' else 'ebv2'}, N={N_PER})", flush=True)
            _run(["scripts/collect_rl_data.py"],
                 {"RL_CB": s["best"], "RL_GAMMA": GAMMA, "RL_FEAT": FEAT, "RL_N": str(N_PER),
                  "RL_CAND": "5", "RL_RO": "3", "RL_WORKERS": W, "RL_OUT": data_out,
                  "RL_SEED0": str(300000 + it * 10000)})
        else:
            print(f"[1] 収集 skip(既存 {data_out})", flush=True)
        corpora = s["corpora"] + [data_out]

        # [2] 学習(累積 corpus)
        print(f"[2] 学習 (corpus {len(corpora)} 本)", flush=True)
        cmd = ["scripts/train_rl_value.py"]
        for c in corpora:
            cmd += ["--corpus", c]
        cmd += ["--out", val_out]
        _run(cmd, {})

        # [3] arena(新 vs 現best)
        print(f"[3] arena (新 vs {s['best']}, N={ARENA_N})", flush=True)
        out = _run(["scripts/arena_policy.py"],
                   {"AR_NEW": val_out, "AR_BEST": s["best"], "AR_FEAT": FEAT,
                    "AR_N": str(ARENA_N), "AR_WORKERS": W})
        m = re.search(r"勝率 ([\d.]+)% ± ([\d.]+)", out)
        wr, se = (float(m.group(1)), float(m.group(2))) if m else (0.0, 99.0)
        promoted = (wr - se) > 50.0
        print(f"[4] arena {wr:.1f}% ± {se:.1f} → {'✅昇格' if promoted else '✗据置(データ蓄積)'}", flush=True)

        s["corpora"] = corpora  # 累積は常に保持(次 iter も使う)
        s["history"].append({"iter": it, "wr": wr, "se": se, "promoted": promoted,
                             "best_before": s["best"]})
        if promoted:
            s["best"] = val_out   # 昇格 → 次 iter は新policyの分布で収集(DAgger)
        s["iter"] = it + 1
        _save_state(s)

    print(f"\n=== RL ループ 完了。 final best = {s['best']} ===", flush=True)
    print("history:", flush=True)
    for h in s["history"]:
        print(f"  iter{h['iter']}: {h['wr']:.1f}%±{h['se']:.1f} {'昇格' if h['promoted'] else '据置'}", flush=True)


if __name__ == "__main__":
    main()
