# -*- coding: utf-8 -*-
"""self-play ログ精読ツール (= ohtsuki の #1打倒ループ「self-play から悪手を見つけて改善」 の読解エンジン)。

フィールドデッキ vs #1(target) を N 戦し、 試合ログ (run_matchup keep_logs) を構造化して:
  (1) win/loss 別の悪手メトリクス: 試合長 / 総攻撃 / KO / リーダー接続 / 弾かれた攻撃 / 被弾(bleed) / 攻撃効率
  (2) --dump-defense: loss ゲームの防御決定 (相手→自リーダー攻撃を 受け/守り + 攻撃力 + gap + 推定ライフ)

diagnose_loss_vs_target.py (= 敗因の大分類) を補完し、 **手レベルの悪手** (序盤の bleed=守れる
チップを高ライフで受ける / カウンター壁への素殴り 等) を定量化する。 win/loss の差が大きい指標 =
直すべき1手の候補。 field player は field deck の leader 名一致で同定 (= 先攻/後攻入替に頑健)。

  .venv/bin/python scripts/analyze_self_play_misplays.py cardrush_1342 tcgportal_calgara --n 30
  .venv/bin/python scripts/analyze_self_play_misplays.py cardrush_1342 tcgportal_calgara --n 30 --dump-defense
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import DeckList, CardRepository  # noqa: E402
from engine.harness import run_matchup  # noqa: E402
from engine.exploit_beam_ai import ExploitBeamAI  # noqa: E402

REPO = CardRepository.from_json(ROOT / "db" / "cards.json")


def _ana(slug):
    p = ROOT / "decks" / f"{slug}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _leader_name(slug):
    d = json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8"))
    return REPO.get(d.get("leader") or d.get("leader_id")).name


def _field_idx(g, field_leader):
    """snapshot から field player の index を leader 名一致で同定。"""
    sn = g.snapshots or []
    if not sn:
        return 0
    p0_leader = str(sn[0]["players"][0]["leader"].get("name", ""))
    return 0 if field_leader in p0_leader or p0_leader in field_leader else 1


def _attack_metrics(log, fi):
    """field の攻撃結果 (connect/KO/repelled) と被弾(bleed) を 1 ゲーム分集計。"""
    fp, op = f"P{fi}", f"P{1 - fi}"
    m = dict(atk=0, connect=0, ko=0, repelled=0, bleed=0)
    cur = None
    for i, l in enumerate(log):
        tm = re.match(r"T\d+ (P\d):", l)
        if tm:
            cur = tm.group(1)
        if cur == fp and "atk:" in l:
            m["atk"] += 1
            connected = ko = repelled = False
            # 結果行 (hit/KO/blocked/survived) は同じ "TN P?:" prefix を持つので
            # prefix では切らず、 次の atk/play/refresh/don/GAME OVER で打ち切る。
            for j in range(i + 1, min(i + 9, len(log))):
                nx = log[j]
                if any(s in nx for s in ("atk:", "play:", "refresh:", "don phase", "GAME OVER")):
                    break
                if "hit:" in nx:
                    connected = True
                if "KO:" in nx:
                    ko = True
                if "blocked" in nx or "survived" in nx:
                    repelled = True
            if ko:
                m["ko"] += 1
            elif connected:
                m["connect"] += 1
            elif repelled:
                m["repelled"] += 1
        if cur == op and f"hit: {fp} life->hand" in l:
            m["bleed"] += 1
    return m


def _dump_defense(log, fi, field_leader, gi, target_life, turns, max_games_state):
    """loss ゲームの「相手→自リーダー攻撃」 を 受け/守り + gap + 推定ライフ で列挙。"""
    fp, op = f"P{fi}", f"P{1 - fi}"
    print(f"\n===== game{gi} ({field_leader} 敗北, target {target_life}残, {turns}T) =====")
    cur = curT = None
    field_life = 5
    for i, l in enumerate(log):
        tm = re.match(r"T(\d+) (P\d):", l)
        if tm:
            curT, cur = tm.group(1), tm.group(2)
        if cur == op and "atk:" in l and "->" in l:
            mm = re.search(r"atk: ([^()]+)\(P=(\d+)\) -> ([^()]+)\(P=(\d+)\)", l)
            if not mm:
                continue
            atkr, ap, tgt = mm.group(1), int(mm.group(2)), mm.group(3)
            if field_leader.split("・")[0] not in tgt and "ンキ" not in tgt and field_leader[:3] not in tgt:
                continue  # field leader への攻撃のみ
            res = "?"
            for j in range(i + 1, min(i + 6, len(log))):
                nx = log[j]
                if "atk:" in nx or "refresh:" in nx:
                    break
                if f"hit: {fp}" in nx:
                    res = "受け(bleed)"
                    field_life -= 1
                elif "blocked" in nx:
                    res = "守った"
                elif "対象変更" in nx or "redirect" in nx:
                    res = "redirect"
            before = field_life + (1 if res.startswith("受") else 0)
            print(f"  T{curT}: {atkr[:8]}({ap}) → leader  [life {before}→{field_life}]  gap={ap - 5000:+}  ⇒ {res}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("field")
    ap.add_argument("target", nargs="?", default="tcgportal_calgara")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dump-defense", action="store_true", help="loss ゲームの防御決定を列挙")
    a = ap.parse_args()

    dF = DeckList.from_json(ROOT / "decks" / f"{a.field}.json", REPO)
    dT = DeckList.from_json(ROOT / "decks" / f"{a.target}.json", REPO)
    fl_name = _leader_name(a.field)

    def aF(rng, da=None):
        return ExploitBeamAI(rng=rng, deck_analysis={"deck_slug": a.field})

    def aT(rng, da=None):
        return ExploitBeamAI(rng=rng, deck_analysis={"deck_slug": a.target})

    rep = run_matchup(dF, dT, n_games=a.n, seed=a.seed, ai_factory_1=aF, ai_factory_2=aT,
                      deck1_analysis=_ana(a.field), deck2_analysis=_ana(a.target),
                      keep_logs=True, record_snapshots=True)

    wins, losses = [], []
    dumped = 0
    for gi, g in enumerate(rep.games):
        sn = g.snapshots or []
        if not sn:
            continue
        fi = _field_idx(g, fl_name)
        fl = sn[-1]["players"][fi]["life_count"]
        ol = sn[-1]["players"][1 - fi]["life_count"]
        won = fl > 0 and ol == 0
        m = _attack_metrics(g.log or [], fi)
        m["turns"] = g.turns
        (wins if won else losses).append(m)
        if a.dump_defense and not won and dumped < 5:
            dumped += 1
            _dump_defense(g.log or [], fi, fl_name, gi, ol, g.turns, 5)

    def avg(arr, k):
        return sum(x[k] for x in arr) / max(1, len(arr))

    print(f"\n=== {a.field} vs {a.target}: {len(wins)}勝 {len(losses)}敗 (N={a.n}) ===")
    print(f"{'metric':<24}{'WIN':>8}{'LOSS':>8}")
    for k, lbl in [("turns", "試合長"), ("atk", "総攻撃数"), ("ko", "KO成功"),
                   ("connect", "リーダー接続"), ("repelled", "弾かれた攻撃"), ("bleed", "被弾(bleed)")]:
        print(f"  {lbl:<22}{avg(wins, k):>8.1f}{avg(losses, k):>8.1f}")

    def eff(arr):
        t = sum(x["atk"] for x in arr)
        return sum(x["connect"] + x["ko"] for x in arr) / max(1, t) * 100
    print(f"  {'攻撃効率(接続+KO)/総':<22}{eff(wins):>7.0f}%{eff(losses):>7.0f}%")


if __name__ == "__main__":
    main()
