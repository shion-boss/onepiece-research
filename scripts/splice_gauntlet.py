# -*- coding: utf-8 -*-
"""gauntlet で clean 再計測した「#1 列」を matchup_matrix に差し込み、 再ランクで #1 を出し直す。

ohtsuki ループ: フル matrix 再計算 (~2h) でなく、 毎イテレーション #1 の列だけ
uniform-ExploitBeam の新データで更新 → 再ランク。 列ごとに matrix が refresh され、
#1 が収束。 /meta は db/matchup_matrix.json を読むので自動反映。

⚠ spliced matrix は hybrid (= 更新列=clean uniformEB / 残り=旧 SmartOpponentAI)。
列を重ねるほど fresh 比率が上がる。 backup を取ってから上書き。

  SPLICE_TARGET=tcgportal_calgara .venv/bin/python scripts/splice_gauntlet.py
"""
import json, os, statistics, time
from pathlib import Path

REPO = Path(os.getcwd())
target = os.environ["SPLICE_TARGET"]

mat_path = REPO / "db" / "matchup_matrix.json"
m = json.loads(mat_path.read_text(encoding="utf-8"))
g = json.loads((REPO / "db" / f"gauntlet_{target}.json").read_text(encoding="utf-8"))
cum = g["cum"]  # {challenger_slug: [W, L]} (= challenger の vs target)
names = {e["deck_a"]: e["deck_a_name"] for e in m["matrix"]}

# backup (= /meta 公開データなので保全)
bak = mat_path.with_suffix(".json.bak")
bak.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

# entry を slug で引けるよう index
by_a = {e["deck_a"]: e for e in m["matrix"]}


def _cell(entry, deck_b):
    for c in entry["row"]:
        if c["deck_b"] == deck_b:
            return c
    return None


updated = 0
ts = time.strftime("%Y-%m-%dT%H:%M:%S")
for c, (w, l) in cum.items():
    if w + l == 0 or c == target:
        continue
    # challenger c の行: c vs target = W/(W+L)
    cell = _cell(by_a.get(c, {"row": []}), target)
    if cell:
        cell.update(winrate=w / (w + l), wins=w, losses=l, draws=0,
                    ai_version="uniformEB_gauntlet", computed_at=ts)
        updated += 1
    # target の行: target vs c = 補数 (= 引分なしなので W↔L 反転)
    cell2 = _cell(by_a.get(target, {"row": []}), c)
    if cell2:
        cell2.update(winrate=l / (w + l), wins=l, losses=w, draws=0,
                     ai_version="uniformEB_gauntlet", computed_at=ts)

mat_path.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"spliced {updated} cells (target={names.get(target,target)} 列) -> {mat_path.name} "
      f"(backup: {bak.name})")

# 再ランク
rows = []
for e in m["matrix"]:
    wr = [c["winrate"] for c in e["row"] if c.get("winrate") is not None]
    if wr:
        rows.append((e["deck_a_name"], e["deck_a"], statistics.mean(wr)))
rows.sort(key=lambda x: -x[2])
print(f"=== 再ランク (calgara 列を clean 更新後) ===")
for i, (n, s, w) in enumerate(rows, 1):
    flag = " ← 新 #1" if i == 1 else (" (旧#1)" if s == target else "")
    print(f"  {i:>2}. {n:<20}{w*100:>5.1f}%{flag}")
