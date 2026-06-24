# -*- coding: utf-8 -*-
"""打倒1位 campaign: vs-1位セルだけ差し替えて ranking を高速再計算 (ohtsuki 提案)。

全 matrix 再計算 (240 cell, 数時間) は不要。 self-play で counter が #1 戦を改善したら、
その (challenger, #1) / (#1, challenger) セルだけ更新 → row-avg 再計算 → #1 陥落したか即判定。

⭐ **--save で永続化** (= 手順4.5、 2026-06-24 ohtsuki 指摘の本質バグ修正): override を
`matchup_matrix.json` に**書き戻す**。 これが無いと deploy しても matrix が古いまま →
手順1 (= 現#1を matrix row-avg で測る) が常に旧#1 を返し、 ローテーションが session を跨いで
永続しない。 --save すると deploy 済 counter の改善が matrix に残り、 次ラウンドの #1 確認が
正しくなる (= 本当に「回る」)。 履歴は `db/dethrone_campaign.json` に追記。

  # 現状の ranking を再現 (= 機械の検証、 override 無し):
  .venv/bin/python scripts/recompute_rank_vs_top.py
  # 改善を反映して**永続化** (= deploy 後にこれを打つ):
  .venv/bin/python scripts/recompute_rank_vs_top.py --override cardrush_1454=0.32 --save --n 100 \
      --note "round1: enel 1454 self-play deploy"
  # gauntlet 結果ファイルから一括反映 (+ --save で永続化):
  .venv/bin/python scripts/recompute_rank_vs_top.py --gauntlet db/gauntlet_tcgportal_calgara.json --save
"""
import argparse
import datetime as _dt
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MATRIX = ROOT / "db" / "matchup_matrix.json"
CAMPAIGN_LOG = ROOT / "db" / "dethrone_campaign.json"


def _load_matrix(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _row_avgs(m):
    """各 deck の強さ = **両 seat 平均** (= vs 全相手で、 自分が deck_a の時と deck_b の時を平均)。
    mirror(None)は除外。 ⚠ deck_a-only (= 自分の row だけ) は noise 敏感で**符号を誤る**:
    cell は独立実測 (N小) で非対称、 deck_a-only は 2 cell の片方しか見ない。 counter を強化すると
    その counter の deck_a seat だけ上がり、 #1 の deck_a cell は逆に上がりうる → #1 が強く見える誤り
    (2026-06-24 round1 enel で確認: deck_a-only は calgara +0.3pt と誤判定、 両 seat は -0.67pt と正)。
    両 seat 平均 = avg(cell(X,Y), 1-cell(Y,X)) で X 視点に統一 → 符号が正しい + noise 半減。"""
    names = {}
    W = {}
    for e in m["matrix"]:
        names[e["deck_a"]] = e["deck_a_name"]
        W[e["deck_a"]] = {c["deck_b"]: c.get("winrate") for c in e["row"]}
    slugs = list(W.keys())
    out = {}
    for x in slugs:
        vals = []
        for y in slugs:
            if y == x:
                continue
            a = W[x].get(y)              # x が deck_a の時の x 勝率
            b = W.get(y, {}).get(x)      # y が deck_a の時の y 勝率 → x 勝率 = 1-b
            parts = []
            if a is not None:
                parts.append(a)
            if b is not None:
                parts.append(1.0 - b)
            if parts:
                vals.append(sum(parts) / len(parts))
        out[x] = statistics.mean(vals) if vals else 0.0
    return out, names


def _cell(m, a, b):
    for e in m["matrix"]:
        if e["deck_a"] == a:
            for c in e["row"]:
                if c["deck_b"] == b:
                    return c
    return None


def _apply_override(m, top, overrides):
    """challenger の vs-top 勝率を override → (challenger,top) と (top,challenger) を整合更新。"""
    for ch, wr_vs_top in overrides.items():
        c1 = _cell(m, ch, top)      # challenger が top に勝つ率
        c2 = _cell(m, top, ch)      # top が challenger に勝つ率 = 1 - 上記
        if c1 is not None:
            c1["winrate"] = wr_vs_top
        if c2 is not None:
            c2["winrate"] = 1.0 - wr_vs_top


def _stamp_cell(cell, wr, n):
    """書き戻しセルの bookkeeping を整える (= w/l/d を n から復元 + 出自タグ)。"""
    if cell is None:
        return
    now = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    cell["winrate"] = wr
    cell["wins"] = int(round(wr * n))
    cell["losses"] = int(n - round(wr * n))
    cell["draws"] = 0
    cell["computed_at"] = now
    cell["stale"] = False
    cell["selfplay_deployed"] = True  # 出自: self-play deploy 由来の書き戻し


def _persist(m, path, top, overrides, n, note, avg_before, avg_after, new_top):
    """override を matrix に書き戻し + campaign 履歴に追記。"""
    for ch, wr in overrides.items():
        _stamp_cell(_cell(m, ch, top), wr, n)
        _stamp_cell(_cell(m, top, ch), 1.0 - wr, n)
    Path(path).write_text(
        json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # campaign 履歴 (audit log)
    log = {"rounds": []}
    if CAMPAIGN_LOG.exists():
        try:
            log = json.loads(CAMPAIGN_LOG.read_text(encoding="utf-8"))
        except Exception:
            log = {"rounds": []}
    log.setdefault("rounds", []).append({
        "ts": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "top_before": top,
        "top_rowavg_before": round(avg_before.get(top, 0.0), 4),
        "overrides": {k: round(v, 4) for k, v in overrides.items()},
        "n_per_matchup": n,
        "top_rowavg_after": round(avg_after.get(top, 0.0), 4),
        "new_top": new_top,
        "rotated": new_top != top,
        "note": note,
        "matrix_ai_version": m.get("ai_version"),
    })
    CAMPAIGN_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", default=None, help="#1 slug (既定 = 現 row-avg 1位)")
    ap.add_argument("--override", default="", help="slug=wr,slug=wr (challenger の vs-#1 勝率)")
    ap.add_argument("--gauntlet", default="", help="gauntlet_<top>.json から vs-#1 を一括反映")
    ap.add_argument("--save", action="store_true", help="override を matrix に書き戻す (= 永続化、 手順4.5)")
    ap.add_argument("--n", type=int, default=80, help="--save 時の 1 matchup あたり試合数 (w/l/d 復元用)")
    ap.add_argument("--note", default="", help="--save 時に campaign 履歴へ残すメモ")
    ap.add_argument("--matrix-path", default=str(DEFAULT_MATRIX), help="既定 db/matchup_matrix.json")
    a = ap.parse_args()

    m = _load_matrix(a.matrix_path)
    avg0, names = _row_avgs(m)
    rank0 = sorted(avg0.items(), key=lambda x: -x[1])
    top = a.top or rank0[0][0]
    print(f"=== 現 ranking (#1 = {top} {names.get(top,'')} {avg0[top]*100:.1f}%) ===")
    for i, (s, v) in enumerate(rank0[:5]):
        print(f"  {i+1}. {names.get(s,s):18} {v*100:.1f}%")

    overrides = {}
    if a.override:
        for kv in a.override.split(","):
            if "=" in kv:
                k, v = kv.split("=")
                overrides[k.strip()] = float(v)
    if a.gauntlet:
        g = json.loads(Path(a.gauntlet).read_text(encoding="utf-8"))
        for ch, wld in g.get("cum", {}).items():
            w, l, d = (list(wld) + [0, 0, 0])[:3]
            n = w + l + d
            if n:
                overrides[ch] = w / n
    if not overrides:
        print("\n(override 無し → 機械検証: 現 ranking を再現するだけ)")
        return

    _apply_override(m, top, overrides)
    avg1, _ = _row_avgs(m)
    rank1 = sorted(avg1.items(), key=lambda x: -x[1])
    print(f"\n=== 差し替え後 (override {len(overrides)} 件: "
          f"{', '.join(f'{k}→{v:.0%}' for k, v in overrides.items())}) ===")
    for i, (s, v) in enumerate(rank1[:5]):
        d = (v - avg0.get(s, v)) * 100
        flag = " ⭐#1陥落!" if s == top and i > 0 else (" ⭐新#1" if i == 0 and s != top else "")
        print(f"  {i+1}. {names.get(s,s):18} {v*100:.1f}%  ({d:+.1f}pt){flag}")
    new_top = rank1[0][0]
    if new_top != top:
        print(f"\n⭐⭐ #1 が {names.get(top,top)} → {names.get(new_top,new_top)} に交代! 打倒成功、 次の標的へ。")
    else:
        print(f"\n#1 は {names.get(top,top)} のまま (row-avg {avg0[top]*100:.1f}→{avg1[top]*100:.1f}%)。")

    if a.save:
        _persist(m, a.matrix_path, top, overrides, a.n, a.note, avg0, avg1, new_top)
        print(f"\n💾 matrix 永続化: {a.matrix_path} に {len(overrides)} 件書き戻し "
              f"(n={a.n}/matchup, 出自=selfplay_deployed) + 履歴を {CAMPAIGN_LOG.name} に追記。")
        print(f"   → 次ラウンドの 手順1 (現#1 確認) はこの更新を反映する (= 本当に回る)。")


if __name__ == "__main__":
    main()
