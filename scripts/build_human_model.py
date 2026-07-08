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


def analyze_game(d: dict, opp_leader_name: str | None = None) -> dict | None:
    meta = d.get("metadata", {})
    human_idx = meta.get("human_idx")
    ai_idx = meta.get("ai_idx")
    if human_idx is None or ai_idx is None:
        return None
    log = d.get("log", [])
    result = d.get("result", {})

    # ⚠ 実ログの攻撃フォーマット (2026-06-05 修正): 攻撃宣言は
    #   `atk: <攻撃者>(P=N) -> <対象>(P=M)`、 リーダーヒットは `hit: P{ai} life->hand (…)`。
    # 旧コードは「リーダーへアタック」 等の存在しない文字列を照合 → attacks_face/chara が常に 0
    # (= aggression が degenerate)。 対象がリーダーか否かは **対象名 == 相手リーダー名** で判定。
    # ミラー戦の同名キャラ衝突に備え、 life ダメージを出した atk の対象 (= 確実にリーダー) を
    # ログからも収集して leader 名集合に union する (= 解析自己完結 + analysis からの opp_leader_name)。
    leader_names = set()
    if opp_leader_name:
        leader_names.add(opp_leader_name)
    _last_atk_target = None
    for ln in log:
        _t, _p, _b = _strip_prefix(ln)
        mt = re.match(r"\s*atk:\s*.+?->\s*(.+?)\(P=", _b)
        if mt and _p == human_idx:
            _last_atk_target = mt.group(1).strip()
        elif re.match(rf"\s*hit:\s*P{ai_idx}\s+life", _b) and _last_atk_target:
            leader_names.add(_last_atk_target)  # life ダメージ確定 = 対象はリーダー

    human_def_counters = 0       # 人間が counter を切った回数 (= AIターン中)
    human_def_counter_value = 0  # その counter 値 合計
    human_def_blocks = 0         # 人間が blocker を出した回数 (= AIターン中)
    human_attacks_face = 0       # 人間がリーダーを攻撃 (= 対象がリーダー名)
    human_attacks_chara = 0      # 人間がキャラを攻撃
    human_face_hits = 0          # 人間のリーダー攻撃が通った回数 (= life ダメージ)
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
        # --- 攻撃 (自=人間ターン中の `atk: A(P=) -> TARGET(P=)`) ---
        if pidx == human_idx:
            ma = re.match(r"\s*atk:\s*.+?->\s*(.+?)\(P=", body)
            if ma:
                target = ma.group(1).strip()
                if target in leader_names:
                    human_attacks_face += 1
                else:
                    human_attacks_chara += 1
            # リーダーに life ダメージが通った (= 人間の顔詰め成功)
            if re.match(rf"\s*hit:\s*P{ai_idx}\s+life", body):
                human_face_hits += 1
        # --- マリガン (人間の keep/引き直し) ---
        # ⚠ 修正 (2026-06-05): mulligan 行は開始 turn_player の prefix (例 `T1 P0:`) を持つので
        # pidx==human_idx では漏れる → body の `(人間)` で判定。 かつ 「引き直さない」 は 「引き直し」
        # を部分文字列に含むので keep を先に判定 (旧コードは順序逆で keep を redraw と誤計上)。
        if "マリガン" in body and "(人間)" in body:
            if "引き直さない" in body or "keep" in body:
                mull_keep += 1
            elif "引き直し" in body:
                mull_redraw += 1

    turns = int(result.get("turns", 0)) or 1
    return {
        "human_def_counters": human_def_counters,
        "human_def_counter_value": human_def_counter_value,
        "human_def_blocks": human_def_blocks,
        "human_attacks_face": human_attacks_face,
        "human_attacks_chara": human_attacks_chara,
        "human_face_hits": human_face_hits,
        "mull_keep": mull_keep,
        "mull_redraw": mull_redraw,
        "turns": turns,
        "human_won": int(result.get("winner_for_human", 0) == 1),
    }


def build(log_dir: Path) -> dict:
    _leader_cache: dict = {}

    def _opp_leader(slug):
        if not slug:
            return None
        if slug not in _leader_cache:
            ap = ROOT / "decks" / f"{slug}.analysis.json"
            try:
                _leader_cache[slug] = json.loads(ap.read_text(encoding="utf-8")).get("leader_name")
            except Exception:
                _leader_cache[slug] = None
        return _leader_cache[slug]

    games = []
    for f in sorted(glob.glob(str(log_dir / "*.json"))):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        # 相手 (AI) の deck = 攻撃対象リーダー。 metadata の deck_ai_slug から leader 名を解決。
        opp_leader = _opp_leader(d.get("metadata", {}).get("deck_ai_slug"))
        g = analyze_game(d, opp_leader)
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
    tot_face_hits = sum(g.get("human_face_hits", 0) for g in games)
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
        "face_hits_per_turn": round(tot_face_hits / max(1, tot_turns), 4),
        "_raw_totals": {
            "def_counters": tot_counters, "def_blocks": sum(g["human_def_blocks"] for g in games),
            "attacks_face": tot_face, "attacks_chara": tot_chara,
            "face_hits": tot_face_hits, "turns": tot_turns,
        },
        "_note": ("sample_size が小さい間は HumanModelAI は greedy に近い (= データ量でスケール)。"
                  " 公開サーバの試合が増えるほど精度向上。"),
    }


def _parse_matchup_from_name(name: str):
    """log ファイル名 → (human_deck, ai_deck) or None。 api/main.py の _parse_play_log_name と同形式。"""
    base = name.rsplit("/", 1)[-1]
    if base.endswith(".json"):
        base = base[:-5]
    if "_" not in base or "_vs_" not in base:
        return None
    _ts, rest = base.split("_", 1)
    if "_vs_" not in rest:
        return None
    human, right = rest.split("_vs_", 1)
    parts = right.rsplit("_", 2)  # [ai, tag, sid(-suffix)]
    if len(parts) < 3:
        return None
    return human, parts[0]


def _mark_trained(log_dir: Path) -> dict:
    """「学習に使った」時点の matchup 別 累計件数を db/human_play_trained.json に記録する。
    = ohtsuki 「学習に使ったら分母に 10 足す」 の実体。 api の progress は
    new_games = games - trained_upto で計る (= 次バッチへの進捗)。 abandoned は除外。"""
    from collections import Counter
    counts: Counter = Counter()
    for f in glob.glob(str(log_dir / "*.json")):
        parsed = _parse_matchup_from_name(Path(f).name)
        if not parsed:
            continue
        base = Path(f).name
        if "_abandoned_" in base or base.endswith("_abandoned.json"):
            continue
        human, ai = parsed
        counts[f"{human}__vs__{ai}"] += 1
    out = ROOT / "db" / "human_play_trained.json"
    prev = {}
    try:
        prev = json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        prev = {}
    # trained_upto は「消費済み累計」= 現時点の全件数へ更新 (単調増加でのみ上書き)。
    merged = dict(prev)
    for k, c in counts.items():
        merged[k] = max(int(prev.get(k, 0)), int(c))
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", default=str(ROOT / "db" / "human_play_log"))
    ap.add_argument("--out", default=str(ROOT / "db" / "human_model.json"))
    ap.add_argument("--no-mark-trained", action="store_true",
                    help="学習消費として human_play_trained.json を更新しない (= 進捗バーを進めない)")
    args = ap.parse_args()
    model = build(Path(args.log_dir))
    Path(args.out).write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(model, ensure_ascii=False, indent=2))
    print(f"\n→ {args.out}")
    if not args.no_mark_trained:
        merged = _mark_trained(Path(args.log_dir))
        print(f"→ 学習消費を記録 (matchup {len(merged)} 件) db/human_play_trained.json"
              f"  (進捗バーは次バッチへリセット)")


if __name__ == "__main__":
    main()
