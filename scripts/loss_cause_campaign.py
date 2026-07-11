# -*- coding: utf-8 -*-
"""全デッキ 敗因調査キャンペーン: 16デッキ×50game×10セット を回し、 各セットで
clean bug を集約走査 → findings.log に記録。 チェックポイント/resume 付き、 並列、
ディスク節約(セット走査後に raw ログ削除)。

⚠ 前提: capture_learning_log の AI-deck 席ミスマッチ修正 (commit 0c7398a) 済であること。
各セット: deck i は 相手 = DECKS[(i+1+set)%16](set毎にローテ=多マッチ被覆)と 50game。

  .venv/bin/python scripts/loss_cause_campaign.py --sets 10 --games 50 --workers 8
"""
import argparse, json, os, subprocess, glob, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.getcwd()
DECKS = [
    "cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399",
    "cardrush_1439", "cardrush_1453", "cardrush_1454", "cardrush_1455",
    "cardrush_1456", "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby",
    "tcgportal_corazon", "tcgportal_hancock", "tcgportal_op11_luffy", "tcgportal_op13_luffy",
]
CAMP = "db/_analyst/campaign"
os.makedirs(CAMP, exist_ok=True)
CKPT = f"{CAMP}/progress.json"
FINDINGS = f"{CAMP}/findings.log"


def load_ckpt():
    if os.path.exists(CKPT):
        return json.load(open(CKPT))
    return {"done_sets": []}


def save_ckpt(c):
    json.dump(c, open(CKPT, "w"), indent=1)


def run_one(deck, opp, seed, out, games):
    r = subprocess.run(
        [".venv/bin/python", "scripts/capture_learning_log.py", "--a", deck, "--b", opp,
         "--n", str(games), "--seed", str(seed), "--skip-ceiling", "--out", out],
        capture_output=True, text=True)
    # 勝率行を拾う (deck-a=hero の正 rate、 harness修正済)
    wr = ""
    for line in r.stdout.splitlines():
        if "勝率" in line:
            wr = line.strip()
    return deck, opp, wr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", type=int, default=10)
    ap.add_argument("--games", type=int, default=50)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    ckpt = load_ckpt()

    def log(msg):
        with open(FINDINGS, "a") as f:
            f.write(msg + "\n")
        print(msg, flush=True)

    for S in range(a.sets):
        if S in ckpt["done_sets"]:
            continue
        t0 = time.time()
        log(f"\n===== SET {S} 開始 (games={a.games}/deck) =====")
        tasks = []
        for i, deck in enumerate(DECKS):
            opp = DECKS[(i + 1 + S) % len(DECKS)]
            out = f"{CAMP}/s{S}_{deck}_vs_{opp}.jsonl"
            seed = 60000 + S * 1000 + i * 10
            tasks.append((deck, opp, seed, out, a.games))
        wrs = []
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            for deck, opp, wr in ex.map(lambda t: run_one(*t), tasks):
                wrs.append(f"  {deck} vs {opp}: {wr}")
        log("勝率(hero=deck a):")
        for w in wrs:
            log(w)
        # 集約 clean bug 走査
        logs = sorted(glob.glob(f"{CAMP}/s{S}_*.jsonl"))
        scan = subprocess.run(
            [".venv/bin/python", "scripts/scan_clean_bugs.py"] + logs,
            capture_output=True, text=True)
        log("clean bug 走査:")
        for line in scan.stdout.splitlines():
            if line.strip() and "===" not in line:
                log("  " + line.strip())
        # ディスク節約: raw ログ削除
        for lf in logs:
            os.remove(lf)
        ckpt["done_sets"].append(S)
        save_ckpt(ckpt)
        log(f"===== SET {S} 完了 ({time.time()-t0:.0f}s) =====")
    log("\n##### 全セット完了 #####")


if __name__ == "__main__":
    main()
