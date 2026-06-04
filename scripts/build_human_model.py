# -*- coding: utf-8 -*-
"""人間プレイ log → 人間「相手モデル」 のパラメータを推定 (= 探索の仮想敵に差す用)。

⭐ 狙い: 今の対戦 AI が弱い核心は「探索が相手を GreedyAI と仮定して読む」こと
(深読みするほど悪化、と measured 確認済)。 本物の人間の打ち方を log から学び、
探索の仮想敵を「人間モデル」 に差し替えれば、 AI は人間相手に過剰展開や咎められる手を
避けるようになる (= self-play では作れなかった部分)。

これは その第一歩 = **頑健に数えられる粗い人間挙動パラメータ** を出す:
  - defense_activity: 相手(AI)ターン中に人間が counter/block を使った頻度 (= 防御の手厚さ)
  - counter_value_avg: 1 防御あたり平均 counter 値 (= 何 power 盛るか)
  - aggression: 自ターンの攻撃のうち リーダー面 を狙う比率 (= 顔詰め志向)
  - mulligan_keep_rate / avg_turns
  - sample_size (= 試合数。 少なければ HumanModelAI は greedy に degrade)

⚠ データ量が要る。 8 試合では ≈greedy。 公開サーバに人が集まるほど精度が上がる設計
(= ロードマップ Phase 9 集合知)。 出力: db/human_model.json。

実行:
  .venv/bin/python scripts/build_human_model.py
  .venv/bin/python scripts/build_human_model.py --log-dir db/human_play_log --out db/human_model.json
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _strip_prefix(line: str):
    """'T{turn} P{idx}: body' → (turn, pidx, body)。 マッチしなければ (None,None,line)。"""
    m = re.match(r"^T(\d+) P(\d+):\s?(.*)$", line)
    if not m:
        return None, None, line
    return int(m.group(1)), int(m.group(2)), m.group(3)


def analyze_game(d: dict) -> dict | None:
    meta = d.get("metadata", {})
    human_idx = meta.get("human_idx")
    ai_idx = meta.get("ai_idx")
    if human_idx is None or ai_idx is None:
        return None
    log = d.get("log", [])
    result = d.get("result", {})

    # snapshots から turn_player を引けるが、 log prefix の P{idx} = その手番の turn_player。
    # 相手(AI)ターン中の counter/block = 人間の防御。 自ターンの "blocked"/"counter" は AI の防御。
    human_def_counters = 0       # 人間が counter を切った回数 (= AIターン中)
    human_def_counter_value = 0  # その counter 値 合計
    human_def_blocks = 0         # 人間が blocker を出した回数 (= AIターン中)
    human_attacks_face = 0       # 人間がリーダーを攻撃
    human_attacks_chara = 0      # 人間がキャラを攻撃
    mull_keep = mull_redraw = 0

    for ln in log:
        turn, pidx, body = _strip_prefix(ln)
        if pidx is None:
            continue
        ai_turn = (pidx == ai_idx)   # この行は AI の手番中 (= 防御者は人間)
        # --- 防御 (相手=AIターン中の人間の counter/block) ---
        if ai_turn:
            mc = re.search(r"counter\s*\+(\d+)", body)
            if mc:
                human_def_counters += 1
                human_def_counter_value += int(mc.group(1))
            if "アタック対象変更" in body or body.strip().startswith("blocker:"):
                human_def_blocks += 1
        # --- 攻撃 (自=人間ターン中の攻撃宣言) ---
        if pidx == human_idx:
            if "リーダーへアタック" in body or "→ リーダー" in body or "アタック: リーダー" in body:
                human_attacks_face += 1
            elif body.startswith("アタック") and "対象変更" not in body:
                human_attacks_chara += 1
        # --- マリガン ---
        if pidx == human_idx and "マリガン" in body:
            if "引き直し" in body:
                mull_redraw += 1
            elif "keep" in body or "引き直さない" in body:
                mull_keep += 1

    turns = int(result.get("turns", 0)) or 1
    return {
        "human_def_counters": human_def_counters,
        "human_def_counter_value": human_def_counter_value,
        "human_def_blocks": human_def_blocks,
        "human_attacks_face": human_attacks_face,
        "human_attacks_chara": human_attacks_chara,
        "mull_keep": mull_keep,
        "mull_redraw": mull_redraw,
        "turns": turns,
        "human_won": int(result.get("winner_for_human", 0) == 1),
    }


def build(log_dir: Path) -> dict:
    games = []
    for f in sorted(glob.glob(str(log_dir / "*.json"))):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        g = analyze_game(d)
        if g:
            games.append(g)

    n = len(games)
    if n == 0:
        return {"sample_size": 0, "note": "ログ無し → HumanModelAI は greedy に degrade"}

    tot_def = sum(g["human_def_counters"] + g["human_def_blocks"] for g in games)
    tot_turns = sum(g["turns"] for g in games)
    tot_counters = sum(g["human_def_counters"] for g in games)
    tot_counter_val = sum(g["human_def_counter_value"] for g in games)
    tot_face = sum(g["human_attacks_face"] for g in games)
    tot_chara = sum(g["human_attacks_chara"] for g in games)
    tot_keep = sum(g["mull_keep"] for g in games)
    tot_redraw = sum(g["mull_redraw"] for g in games)

    # defense_activity = 1 ターンあたりの 人間 防御アクション数 (= 防御の手厚さ proxy)。
    # greedy は機械的に「得なら必ず受ける」。 人間がそれより手厚い/手薄いかを表す。
    defense_activity = tot_def / max(1, tot_turns)
    counter_value_avg = tot_counter_val / max(1, tot_counters)
    aggression = tot_face / max(1, tot_face + tot_chara)  # 顔詰め志向 [0,1]

    return {
        "sample_size": n,
        "defense_activity": round(defense_activity, 4),
        "counter_value_avg": round(counter_value_avg, 1),
        "aggression": round(aggression, 4),
        "mulligan_keep_rate": round(tot_keep / max(1, tot_keep + tot_redraw), 4),
        "avg_turns": round(tot_turns / n, 2),
        "human_winrate_vs_ai": round(sum(g["human_won"] for g in games) / n, 4),
        "_raw_totals": {
            "def_counters": tot_counters, "def_blocks": sum(g["human_def_blocks"] for g in games),
            "attacks_face": tot_face, "attacks_chara": tot_chara, "turns": tot_turns,
        },
        "_note": ("sample_size が小さい間は HumanModelAI は greedy に近い (= データ量でスケール)。"
                  " 公開サーバの試合が増えるほど精度向上。"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", default=str(ROOT / "db" / "human_play_log"))
    ap.add_argument("--out", default=str(ROOT / "db" / "human_model.json"))
    args = ap.parse_args()
    model = build(Path(args.log_dir))
    Path(args.out).write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(model, ensure_ascii=False, indent=2))
    print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
