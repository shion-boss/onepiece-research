"""EIV1 学習データ可視化ダッシュボード (localhost) — 2026-07-24。

学習中の db/eiv1/ を読んで、 人間が傾向を一目で分かるグラフを localhost に出す。
外部依存なし (stdlib http.server + 自前 SVG チャート)、 学習を邪魔しない (読むだけ)。

  .venv/bin/python scripts/eiv1_dashboard.py            # http://localhost:8770
  .venv/bin/python scripts/eiv1_dashboard.py --port 9000

見られる指標:
  ① 強さ推移 (ε=0 arena vs EBV2)  = 絶対的に強くなっているか (本物の物差し)
  ② AUC 推移                      = 予測精度 (学習の進み)
  ⑮ value 較正 (reliability)      = 予測勝率が実勝率と合っているか (楽観/悲観の監視)
  ⑯ 予測値ヒスト (弁別力)          = 勝/負 局面で予測値が分離しているか
  ③④ 対世代前 勝率 / corpus 成長   = 世代交代・データ量
  ⑤ デッキ分散 / ⑥ turn 別 win率   = 偏り・局面分布
  ⑰ matchup ヒートマップ           = デッキ×相手デッキ 相性の構造 (self-play)
  ⑩⑪⑫ 相手 leader別/得意苦手/ゲーム長
  ⑬ rollout ラベル / ⑭ ExIt 複利ループ / ⑦ rollout 現況

グラフ設計の根拠 = 3 系統のネット調査 (ML 学習可視化 / self-play RL 診断 / TCG メタ分析)。
較正・信頼区間・self-play 適合 (使用率系は誇張しない) を反映。
"""
from __future__ import annotations
import argparse
import json
import sys
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # script 直起動でも engine.* を import 可能に (calibration の featurizer)
EIV1 = ROOT / "db" / "eiv1"

_CACHE: dict = {"corpus": None, "corpus_ts": 0.0}
_CORPUS_TTL = 60.0   # corpus スキャンは重いので 60s キャッシュ
_NAMES: dict = {}
_MODEL_CACHE: dict = {"path": None, "mtime": 0.0, "model": None, "featfn": None}
_CAL_MAX = 6000      # calibration 用に featurize する最大サンプル (featurize は ~0.5ms/行)


def _names() -> dict:
    """card_id → 名前 (1 回ロード)。 leader 表示用。"""
    global _NAMES
    if not _NAMES:
        try:
            cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
            if isinstance(cards, dict):
                cards = cards.get("cards", cards)
            _NAMES = {c["card_id"]: c.get("name", c["card_id"])
                      for c in cards if isinstance(c, dict)}
        except Exception:
            _NAMES = {"_": "_"}
    return _NAMES


def _corr(xs, ys) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = sum((a - mx) ** 2 for a in xs) ** 0.5
    dy = sum((b - my) ** 2 for b in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def _read_manifest() -> list:
    try:
        h = json.loads((EIV1 / "manifest.json").read_text(encoding="utf-8")).get("history", [])
        return [{"iter": e.get("iter"), "n": e.get("n"), "auc": e.get("auc"),
                 "split": e.get("auc_split", "sample")} for e in h if e.get("auc") is not None]
    except Exception:
        return []


def _read_arena() -> list:
    out = []
    p = EIV1 / "arena.jsonl"
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            if d.get("n_games", 0) >= 100 and "agnostic" in str(d.get("ref", "")):
                out.append({"iter": d["iter"], "win": d["win"], "se": d.get("se", 0),
                            "n": d["n_games"]})
        except Exception:
            continue
    return out


def _read_loop_progress(n: int = 40) -> list:
    """loop.log の『対 1 世代前 勝率』行を時系列で。"""
    out = []
    p = EIV1 / "loop.log"
    if not p.exists():
        return out
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return out
    for line in lines:
        if "対 1 世代前 勝率 = " in line:
            try:
                wr = float(line.split("対 1 世代前 勝率 = ")[1].split(" ")[0])
                tot = int(line.split("corpus 総計 ")[1].split(" ")[0])
                out.append({"corpus": tot, "win": wr})
            except Exception:
                continue
    return out[-n:]


def _read_throughput(n: int = 40) -> list:
    """loop.log の collect 行から 1 ラウンドの samples/秒 を時系列で (遅延検知)。"""
    out = []
    p = EIV1 / "loop.log"
    if not p.exists():
        return out
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return out
    idx = 0
    for line in lines:
        if line.startswith("appended ") and "games (" in line:
            try:
                samples = int(line.split("appended ")[1].split(" ")[0])
                games = int(line.split("from ")[1].split("/")[0])
                secs = int(line.split("games (")[1].split("s)")[0])
                idx += 1
                out.append({"i": idx, "games": games, "secs": secs,
                            "spm": round(samples / max(secs, 1) * 60, 1)})  # samples/分
            except Exception:
                continue
    return out[-n:]


def _rollout_stats() -> dict:
    """rollout corpus から ラベル相関 と 分布 (yr を y=0/1 別にビン)。"""
    res = {"greedy": None, "beam": None}
    for tag, key in (("rollout_corpus.jsonl", "greedy"),
                     ("rollout_corpus_beam.jsonl", "beam")):
        f = EIV1 / tag
        if not f.exists():
            continue
        y, yr = [], []
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                d = json.loads(line)
                y.append(float(d["y"]))
                yr.append(float(d["yr"]))
        except Exception:
            continue
        if not y:
            continue
        # y=0 と y=1 の局面で yr の平均 (rollout が勝敗を予見できているか)
        yr0 = [b for a, b in zip(y, yr) if a < 0.5]
        yr1 = [b for a, b in zip(y, yr) if a >= 0.5]
        res[key] = {"n": len(y), "y_mean": sum(y) / len(y), "yr_mean": sum(yr) / len(yr),
                    "corr": round(_corr(y, yr), 3),
                    "yr_on_loss": round(sum(yr0) / len(yr0), 3) if yr0 else None,
                    "yr_on_win": round(sum(yr1) / len(yr1), 3) if yr1 else None}
    return res


def _corpus_stats(force: bool = False) -> dict:
    """corpus 末尾をサンプルして分散/turn別勝率。 TTL キャッシュ (重い)。 force で cache 無視。"""
    now = time.time()
    if not force and _CACHE["corpus"] and now - _CACHE["corpus_ts"] < _CORPUS_TTL:
        return _CACHE["corpus"]
    p = EIV1 / "corpus.jsonl"
    res = {"total": 0, "games_est": 0, "hero_top": [], "hero_min": 0, "hero_max": 0,
           "hero_n_decks": 0, "turn_winrate": [], "rollout_greedy": 0, "rollout_beam": 0,
           "matchup": {"rows": [], "cols": [], "cells": []},
           "calibration": {"bins": [], "ece": None, "brier": None, "n": 0,
                           "hist_win": [], "hist_loss": []}}
    try:
        # ⚡ 末尾だけ seek で読む (921MB 全読みは重すぎ = API hang の原因)。
        # 末尾 ~45MB を読み、 行に分割して最後の 30k 行を採る。 1 行 ~1.5KB なので十分。
        fsize = p.stat().st_size
        tail_bytes = min(fsize, 45 * 1024 * 1024)
        with open(p, "rb") as f:
            f.seek(fsize - tail_bytes)
            chunk = f.read()
        raw = chunk.split(b"\n")
        if tail_bytes < fsize and raw:
            raw = raw[1:]                       # 先頭の欠けた行を捨てる
        lines = [ln.decode("utf-8", "ignore") for ln in raw if ln.strip()][-30000:]
        # total は filesize / 平均行長 で概算 (全読みしない)
        avg = (sum(len(ln) for ln in raw[:2000]) / max(1, min(2000, len(raw)))) or 1500
        res["total"] = int(fsize / max(avg, 1))
        res["games_est"] = res["total"] // 12
        hero = Counter()
        turn_bucket: dict = {}
        hero_wr: dict = {}        # hero deck → [n, wins]
        oppL_wr: dict = {}        # opp leader card_id → [n, wins]
        game_turn: dict = {}      # game_id → max turn (ゲーム長)
        mm: dict = {}             # (hero_leader_id, opp_leader_id) → [n, wins] (matchup 行列)
        heroL_freq: Counter = Counter()
        cal_rows: list = []       # calibration 用 dict サンプル
        cal_stride = max(1, len(lines) // _CAL_MAX)
        nm = _names()
        for _li, line in enumerate(lines):
            try:
                d = json.loads(line)
                h = d.get("hero", "?")
                y = int(d.get("y", 0))
                hero[h] += 1
                if _li % cal_stride == 0 and len(cal_rows) < _CAL_MAX:
                    cal_rows.append(d)
                hw = hero_wr.setdefault(h, [0, 0])
                hw[0] += 1
                hw[1] += y
                st = d.get("state") or {}
                t = int(st.get("turn_number") or 0)
                b = "1-4" if t <= 4 else ("5-7" if t <= 7 else ("8-10" if t <= 10 else "11+"))
                tb = turn_bucket.setdefault(b, [0, 0])
                tb[0] += 1
                tb[1] += y
                # 相手 leader
                hi = st.get("hero_idx", 0)
                pl = st.get("players") or []
                if len(pl) == 2:
                    lid = (pl[1 - hi].get("leader") or {}).get("card_id")
                    if lid:
                        ow = oppL_wr.setdefault(lid, [0, 0])
                        ow[0] += 1
                        ow[1] += y
                        # matchup: 自分リーダー(行) × 相手リーダー(列) の勝率
                        hlid = (pl[hi].get("leader") or {}).get("card_id")
                        if hlid:
                            mc = mm.setdefault((hlid, lid), [0, 0]); mc[0] += 1; mc[1] += y
                            heroL_freq[hlid] += 1
                g = d.get("g")
                if g:
                    game_turn[g] = max(game_turn.get(g, 0), t)
            except Exception:
                continue
        if hero:
            vals = list(hero.values())
            res["hero_n_decks"] = len(hero)
            res["hero_min"], res["hero_max"] = min(vals), max(vals)
            res["hero_top"] = [{"deck": k, "n": v} for k, v in hero.most_common(12)]
        order = {"1-4": 0, "5-7": 1, "8-10": 2, "11+": 3}
        res["turn_winrate"] = [
            {"bucket": b, "n": v[0], "win": v[1] / v[0] if v[0] else 0}
            for b, v in sorted(turn_bucket.items(), key=lambda kv: order.get(kv[0], 9))]
        # hero デッキ別 勝率 (n>=40 のみ、 得意/苦手 top6)
        hd = [{"deck": k, "n": v[0], "win": v[1] / v[0]} for k, v in hero_wr.items() if v[0] >= 40]
        hd.sort(key=lambda r: -r["win"])
        res["hero_best"] = hd[:6]
        res["hero_worst"] = hd[-6:][::-1]
        # 相手 leader 別 勝率 (n>=60 のみ、 出現多い順 top10)
        ol = [{"leader": nm.get(k, k), "n": v[0], "win": v[1] / v[0]}
              for k, v in oppL_wr.items() if v[0] >= 60]
        ol.sort(key=lambda r: -r["n"])
        res["opp_leader"] = ol[:10]
        # ゲーム長 分布 (完全な game_id を持つ分のみ)
        if game_turn:
            gl = Counter()
            for t in game_turn.values():
                bucket = min(20, (t + 1) // 2 * 2)  # 2 ターン刻み
                gl[bucket] += 1
            res["game_len"] = [{"turn": k, "n": v} for k, v in sorted(gl.items())]
            res["game_len_median"] = sorted(game_turn.values())[len(game_turn) // 2]
            res["game_len_n"] = len(game_turn)
        res["matchup"] = _build_matchup(mm, heroL_freq, oppL_wr, nm)
        res["calibration"] = _calibration(cal_rows)
    except Exception:
        pass
    for tag, key in (("rollout_corpus.jsonl", "rollout_greedy"),
                     ("rollout_corpus_beam.jsonl", "rollout_beam")):
        f = EIV1 / tag
        if f.exists():
            try:  # rollout corpus は小さい (< 数MB) ので全読みで正確に
                with open(f, "rb") as fh:
                    res[key] = fh.read().count(b"\n")
            except Exception:
                pass
    _CACHE["corpus"], _CACHE["corpus_ts"] = res, now
    return res


def _value_model():
    """配備 value.pkl を mtime キャッシュでロード。 featurizer (eiv1_train_vector) も 1 回だけ import。
    sklearn / engine が無ければ (None, None) を返す (calibration は静かに skip)。"""
    p = EIV1 / "value.pkl"
    if not p.exists():
        return None, None
    try:
        mt = p.stat().st_mtime
    except Exception:
        return None, None
    if _MODEL_CACHE["model"] is not None and _MODEL_CACHE["mtime"] == mt:
        return _MODEL_CACHE["model"], _MODEL_CACHE["featfn"]
    try:
        import pickle
        with open(p, "rb") as f:
            model = pickle.load(f)
        if _MODEL_CACHE["featfn"] is None:
            from engine.eiv1_features import eiv1_train_vector  # 学習と同一 featurizer
            _MODEL_CACHE["featfn"] = eiv1_train_vector
        _MODEL_CACHE.update({"path": str(p), "mtime": mt, "model": model})
        return model, _MODEL_CACHE["featfn"]
    except Exception:
        return None, None


def _calibration(rows: list) -> dict:
    """配備 value を rows(=corpus dict のサンプル)に適用し、 予測勝率 vs 実勝率の較正を測る。
    reliability diagram (10 bin) + ECE + Brier + 予測値ヒスト (勝/負 別) を返す。
    「lethal / 局面 value が楽観 or 悲観にズレていないか」 の常時監視 (研究 #3/#4)。"""
    out: dict = {"bins": [], "ece": None, "brier": None, "n": 0,
                 "hist_win": [], "hist_loss": []}
    model, featfn = _value_model()
    if model is None or featfn is None or not rows:
        return out
    try:
        import numpy as np
        exp = int(getattr(model, "n_features_in_", 0) or 0)
        X, Y = [], []
        for d in rows[-_CAL_MAX:]:
            try:
                v = featfn(d)
                if exp and len(v) != exp:
                    continue
                X.append(v)
                Y.append(int(d.get("y", 0)))
            except Exception:
                continue
        if len(X) < 200:
            return out
        X = np.asarray(X, dtype=np.float32)
        Y = np.asarray(Y, dtype=np.float64)
        pv = model.predict_proba(X)[:, 1].astype(np.float64)
        out["n"] = int(len(Y))
        out["brier"] = round(float(np.mean((pv - Y) ** 2)), 4)
        ece = 0.0
        bins = []
        for i in range(10):
            lo, hi = i / 10.0, (i + 1) / 10.0
            m = (pv >= lo) & (pv < hi) if i < 9 else (pv >= lo) & (pv <= hi)
            k = int(m.sum())
            if k:
                conf, acc = float(pv[m].mean()), float(Y[m].mean())
                ece += (k / len(pv)) * abs(conf - acc)
                bins.append({"pred": round(conf, 3), "actual": round(acc, 3), "n": k})
            else:
                bins.append({"pred": round((lo + hi) / 2, 3), "actual": None, "n": 0})
        out["bins"] = bins
        out["ece"] = round(float(ece), 4)
        # 予測値ヒスト (勝/負 別) = 弁別力。 勝局面が右、 負局面が左に寄れば健全
        hw = np.histogram(pv[Y >= 0.5], bins=10, range=(0, 1))[0].tolist()
        hl = np.histogram(pv[Y < 0.5], bins=10, range=(0, 1))[0].tolist()
        out["hist_win"] = [int(x) for x in hw]
        out["hist_loss"] = [int(x) for x in hl]
    except Exception:
        return out
    return out


def _build_matchup(mm: dict, heroL_freq: Counter, oppL_wr: dict, nm: dict,
                   n_rows: int = 12, n_cols: int = 12, min_n: int = 20) -> dict:
    """(hero_leader_id, opp_leader_id) → [n, wins] から 自分リーダー(行) × 相手リーダー(列) の勝率行列。
    リーダー = OPTCG のアーキタイプ identity なので、 デッキで割るより密で標準的な matchup 図 (③ P0)。
    低 N セルは win=None (グレー)。 self-play なので行列は非対称 (hero 視点勝率)。"""
    if not mm:
        return {"rows": [], "cols": [], "cells": []}
    row_ids = [lid for lid, _ in heroL_freq.most_common(n_rows)]
    col_ids = [lid for lid, _ in sorted(oppL_wr.items(), key=lambda kv: -kv[1][0])[:n_cols]]
    cells = []
    for h in row_ids:
        row = []
        for o in col_ids:
            nw = mm.get((h, o))
            if not nw or nw[0] < min_n:
                row.append({"win": None, "n": nw[0] if nw else 0})
            else:
                row.append({"win": round(nw[1] / nw[0], 3), "n": nw[0]})
        cells.append(row)
    def _lbl(i, w):
        # 名前 + セット記号 (OP14 等) で同名リーダー (複数弾のルフィ等) を区別
        return f"{(nm.get(i, i) or i)[:w]} {str(i).split('-')[0]}"
    return {"rows": [_lbl(i, 5) for i in row_ids],
            "cols": [_lbl(i, 4) for i in col_ids], "cells": cells}


def _read_exit() -> dict:
    """ExIt policy 蒸留の履歴 (top-1 = 探索の最善手を再現する率) + policy 有無。"""
    res = {"history": [], "has_policy": (EIV1 / "exit_policy.pkl").exists()}
    m = EIV1 / "exit_manifest.json"
    if m.exists():
        try:
            h = json.loads(m.read_text(encoding="utf-8")).get("history", [])
            res["history"] = [{"iter": e.get("iter"), "top1": e.get("top1"),
                               "rand": e.get("rand"), "decisions": e.get("decisions")}
                              for e in h]
        except Exception:
            pass
    return res


def _stats(force: bool = False) -> dict:
    return {"manifest": _read_manifest(), "arena": _read_arena(),
            "loop": _read_loop_progress(), "corpus": _corpus_stats(force),
            "throughput": _read_throughput(), "rollout": _rollout_stats(),
            "exit": _read_exit(),
            "ts": time.strftime("%Y-%m-%d %H:%M:%S")}


HTML = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>EIV1 学習ダッシュボード</title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#0d1117;color:#c9d1d9;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:14px 20px;background:#161b22;border-bottom:1px solid #30363d;display:flex;justify-content:space-between;align-items:center}
h1{font-size:16px;margin:0;font-weight:600}
.ts{color:#8b949e;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:16px;padding:16px;max-width:1500px;margin:0 auto}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
.card h2{font-size:13px;margin:0 0 4px;font-weight:600}
.card .sub{color:#8b949e;font-size:11px;margin:0 0 10px}
.kpi{display:flex;gap:20px;flex-wrap:wrap;padding:4px 0}
.kpi div{min-width:110px}
.kpi b{display:block;font-size:22px;font-weight:600;color:#58a6ff}
.kpi span{font-size:11px;color:#8b949e}
svg{width:100%;height:200px;display:block}
.axis{stroke:#30363d;stroke-width:1}
.gl{stroke:#21262d;stroke-width:1}
.lbl{fill:#8b949e;font-size:10px}
.bar{fill:#388bfd}
table{width:100%;border-collapse:collapse;font-size:12px}
td{padding:2px 6px;border-bottom:1px solid #21262d}
.note{color:#8b949e;font-size:11px;margin-top:8px;line-height:1.5}
</style></head><body>
<header><h1>EIV1 学習ダッシュボード</h1>
<div style="display:flex;align-items:center;gap:12px">
  <span class="ts" id="ts"></span>
  <label style="font-size:12px;color:#8b949e;display:flex;align-items:center;gap:4px;cursor:pointer">
    <input type="checkbox" id="auto" checked>自動更新(15s)</label>
  <button id="refresh" style="background:#238636;color:#fff;border:0;border-radius:6px;
    padding:6px 14px;font-size:13px;cursor:pointer">今すぐ更新</button>
</div></header>
<div class="grid" id="grid"></div>
<script>
const $=(h)=>{const t=document.createElement('template');t.innerHTML=h.trim();return t.content.firstChild;};
function line(data, xk, yk, {ymin=null,ymax=null,fmt=(v)=>v.toFixed(3),ref=null,color='#58a6ff',se=null}={}){
  const W=420,H=200,pl=44,pr=12,pt=12,pb=26;
  if(!data.length) return `<svg viewBox="0 0 ${W} ${H}"><text x="${W/2}" y="${H/2}" class="lbl" text-anchor="middle">データなし</text></svg>`;
  const xs=data.map(d=>d[xk]), ys=data.map(d=>d[yk]);
  let y0=ymin!==null?ymin:Math.min(...ys), y1=ymax!==null?ymax:Math.max(...ys);
  if(y0===y1){y0-=0.5;y1+=0.5;}
  const x0=Math.min(...xs), x1=Math.max(...xs);
  const X=v=>pl+(x1===x0?0.5:(v-x0)/(x1-x0))*(W-pl-pr);
  const Y=v=>pt+(1-(v-y0)/(y1-y0))*(H-pt-pb);
  let g='';
  for(let i=0;i<=4;i++){const yv=y0+(y1-y0)*i/4;const yy=Y(yv);
    g+=`<line class="gl" x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}"/><text class="lbl" x="${pl-4}" y="${yy+3}" text-anchor="end">${fmt(yv)}</text>`;}
  if(ref!==null&&ref>=y0&&ref<=y1){const yy=Y(ref);g+=`<line x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}" stroke="#f85149" stroke-dasharray="4 3" stroke-width="1"/>`;}
  if(se){for(const d of data){const cx=X(d[xk]),s=d[se]||0;g+=`<line x1="${cx}" y1="${Y(d[yk]-s)}" x2="${cx}" y2="${Y(d[yk]+s)}" stroke="${color}" stroke-opacity="0.4" stroke-width="1"/>`;}}
  const path=data.map((d,i)=>`${i?'L':'M'}${X(d[xk]).toFixed(1)} ${Y(d[yk]).toFixed(1)}`).join(' ');
  g+=`<path d="${path}" fill="none" stroke="${color}" stroke-width="2"/>`;
  for(const d of data){g+=`<circle cx="${X(d[xk])}" cy="${Y(d[yk])}" r="2.5" fill="${color}"/>`;}
  g+=`<text class="lbl" x="${pl}" y="${H-6}">${fmt2(x0)}</text><text class="lbl" x="${W-pr}" y="${H-6}" text-anchor="end">${fmt2(x1)}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}
function fmt2(v){return Number.isInteger(v)?v:v.toFixed(0);}
function bars(data,lk,vk,{fmt=(v)=>v.toFixed(2)}={}){
  const W=420,H=200,pl=44,pr=12,pt=12,pb=40;const vs=data.map(d=>d[vk]);
  if(!data.length)return '<svg viewBox="0 0 420 200"></svg>';
  const vmax=Math.max(...vs,0.001);const bw=(W-pl-pr)/data.length*0.7;let g='';
  data.forEach((d,i)=>{const x=pl+(i+0.15)*(W-pl-pr)/data.length;const h=(d[vk]/vmax)*(H-pt-pb);
    g+=`<rect class="bar" x="${x}" y="${H-pb-h}" width="${bw}" height="${h}"/>`;
    g+=`<text class="lbl" x="${x+bw/2}" y="${H-pb+12}" text-anchor="middle">${d[lk]}</text>`;
    g+=`<text class="lbl" x="${x+bw/2}" y="${H-pb-h-3}" text-anchor="middle">${fmt(d[vk])}</text>`;});
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}
function reliab(bins){
  const W=420,H=200,pl=40,pr=12,pt=14,pb=26;
  const X=v=>pl+v*(W-pl-pr), Y=v=>pt+(1-v)*(H-pt-pb);
  let g='';
  for(let i=0;i<=5;i++){const t=i/5;
    g+=`<line class="gl" x1="${pl}" y1="${Y(t)}" x2="${W-pr}" y2="${Y(t)}"/>`
      +`<text class="lbl" x="${pl-4}" y="${Y(t)+3}" text-anchor="end">${t.toFixed(1)}</text>`
      +`<text class="lbl" x="${X(t)}" y="${H-8}" text-anchor="middle">${t.toFixed(1)}</text>`;}
  g+=`<line x1="${X(0)}" y1="${Y(0)}" x2="${X(1)}" y2="${Y(1)}" stroke="#8b949e" stroke-dasharray="4 3" stroke-width="1"/>`;
  const pts=bins.filter(b=>b.actual!=null);
  if(pts.length){
    const path=pts.map((b,i)=>`${i?'L':'M'}${X(b.pred).toFixed(1)} ${Y(b.actual).toFixed(1)}`).join(' ');
    g+=`<path d="${path}" fill="none" stroke="#58a6ff" stroke-width="2"/>`;
    const nmax=Math.max(...pts.map(b=>b.n),1);
    for(const b of pts){const r=(2.5+4*Math.sqrt(b.n/nmax)).toFixed(1);
      g+=`<circle cx="${X(b.pred)}" cy="${Y(b.actual)}" r="${r}" fill="#58a6ff" fill-opacity="0.75"/>`;}
  }
  g+=`<text class="lbl" x="${pl+2}" y="${pt+2}">実勝率↑ / 予測勝率→ (対角=完全較正)</text>`;
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}
function histDual(win,loss){
  const W=420,H=200,pl=40,pr=12,pt=12,pb=26;const n=win.length||10;
  if(!win.length&&!loss.length) return `<svg viewBox="0 0 ${W} ${H}"><text x="${W/2}" y="${H/2}" class="lbl" text-anchor="middle">データなし</text></svg>`;
  const mx=Math.max(...win,...loss,1);const bw=(W-pl-pr)/n;let g='';
  for(let i=0;i<=4;i++){const yy=pt+(1-i/4)*(H-pt-pb);
    g+=`<line class="gl" x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}"/><text class="lbl" x="${pl-4}" y="${yy+3}" text-anchor="end">${Math.round(mx*i/4)}</text>`;}
  for(let i=0;i<n;i++){const x=pl+i*bw;
    const hw=win[i]/mx*(H-pt-pb), hl=loss[i]/mx*(H-pt-pb);
    g+=`<rect x="${x+bw*0.12}" y="${H-pb-hl}" width="${bw*0.76}" height="${hl}" fill="#f85149" fill-opacity="0.55"/>`;
    g+=`<rect x="${x+bw*0.12}" y="${H-pb-hw}" width="${bw*0.76}" height="${hw}" fill="#3fb950" fill-opacity="0.6"/>`;}
  [0,0.5,1].forEach(t=>{g+=`<text class="lbl" x="${pl+t*(W-pl-pr)}" y="${H-8}" text-anchor="middle">${t}</text>`;});
  g+=`<rect x="${W-96}" y="10" width="10" height="10" fill="#3fb950" fill-opacity="0.6"/><text class="lbl" x="${W-82}" y="19">勝局面</text>`;
  g+=`<rect x="${W-96}" y="24" width="10" height="10" fill="#f85149" fill-opacity="0.55"/><text class="lbl" x="${W-82}" y="33">負局面</text>`;
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}
function _lerp(a,b,t){return Math.round(a+(b-a)*t);}
function wcolor(w){ if(w==null) return '#161b22';
  const t=(w-0.5)*2;
  if(t>=0) return `rgb(${_lerp(45,31,t)},${_lerp(51,111,t)},${_lerp(59,235,t)})`;   // 中立→青(有利)
  const a=-t; return `rgb(${_lerp(45,218,a)},${_lerp(51,54,a)},${_lerp(59,51,a)})`;   // 中立→赤(不利)
}
function heatmap(rows,cols,cells){
  if(!rows||!rows.length||!cols||!cols.length) return '<p class="note">matchup 集計中 (デッキ×相手リーダーの対戦データが必要、 各セル n≥20)</p>';
  const nr=rows.length, nc=cols.length, lw=96, cw=46, rh=24, top=54;
  const W=lw+nc*cw+8, H=top+nr*rh+6;
  let g='';
  for(let j=0;j<nc;j++){const cx=lw+j*cw+cw/2;
    g+=`<text class="lbl" x="${cx}" y="${top-6}" text-anchor="end" transform="rotate(-40 ${cx} ${top-6})">${cols[j]}</text>`;}
  for(let i=0;i<nr;i++){const y=top+i*rh;
    g+=`<text class="lbl" x="0" y="${y+15}">${rows[i]}</text>`;
    for(let j=0;j<nc;j++){const c=cells[i][j], x=lw+j*cw;
      g+=`<rect x="${x}" y="${y}" width="${cw-2}" height="${rh-3}" fill="${wcolor(c.win)}" stroke="#0d1117"/>`;
      if(c.win!=null) g+=`<text x="${x+(cw-2)/2}" y="${y+15}" text-anchor="middle" style="font-size:10px;fill:#fff">${Math.round(c.win*100)}</text>`;}
  }
  return `<svg viewBox="0 0 ${W} ${H}" style="height:${H}px">${g}</svg>`;
}
function wrbar(w){const p=(w*100).toFixed(0);const col=w>=0.5?'#3fb950':'#f85149';
  return `<div style="background:#21262d;border-radius:3px;height:14px;position:relative">
    <div style="background:${col};width:${Math.min(100,w*100)}%;height:100%;border-radius:3px"></div>
    <span style="position:absolute;right:4px;top:0;font-size:10px;line-height:14px">${p}%</span></div>`;}
function wtable(rows,lk,color){return `<table>${rows.map(r=>
  `<tr><td style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r[lk]}</td>
   <td style="width:90px">${wrbar(r.win)}</td><td style="color:#8b949e;width:36px;text-align:right">${r.n}</td></tr>`).join('')}</table>`;}
async function load(force){
  const btn=document.getElementById('refresh');
  if(force){btn.textContent='更新中...';btn.disabled=true;}
  const url='/api/stats'+(force?'?force=1':'');
  let s;
  try{ s=await (await fetch(url)).json(); }
  catch(e){ if(force){btn.textContent='今すぐ更新';btn.disabled=false;} return; }
  if(force){btn.textContent='今すぐ更新';btn.disabled=false;}
  document.getElementById('ts').textContent='更新 '+s.ts;
  const c=s.corpus, arena=s.arena, man=s.manifest, loop=s.loop, tp=s.throughput, ro=s.rollout;
  const last=arena.length?arena[arena.length-1]:null;
  const lastAuc=man.length?man[man.length-1]:null;
  const cards=[];
  // KPI
  cards.push(`<div class="card"><h2>現況</h2><div class="kpi">
    <div><b>${c.games_est.toLocaleString()}</b><span>ゲーム相当 (${c.total.toLocaleString()} 局面)</span></div>
    <div><b>${last?(last.win*100).toFixed(1)+'%':'—'}</b><span>強さ vs EBV2 (最新)</span></div>
    <div><b>${lastAuc?lastAuc.auc.toFixed(4):'—'}</b><span>AUC (最新)</span></div>
    <div><b>${c.hero_n_decks}</b><span>hero デッキ種</span></div></div></div>`);
  // ① arena
  cards.push(`<div class="card"><h2>① 強さ推移 (ε=0 arena vs EBV2)</h2>
    <p class="sub">絶対的に強くなっているか。 赤破線=50% (互角)。 上に離れれば強い</p>
    ${line(arena,'iter','win',{ymin:0.4,ymax:0.6,fmt:v=>(v*100).toFixed(0)+'%',ref:0.5,se:'se'})}
    <p class="note">これが本物の物差し。 横ばいなら「回っているが強くなっていない」</p></div>`);
  // ② AUC
  cards.push(`<div class="card"><h2>② AUC 推移 (予測精度)</h2>
    <p class="sub">学習の進み。 リーク無し game split (iter119〜)</p>
    ${line(man,'iter','auc',{fmt:v=>v.toFixed(3),color:'#3fb950'})}
    <p class="note">プラトーなら表現/target の限界。 データ量では動かない</p></div>`);
  // ⑮ value キャリブレーション (較正)
  const cal=c.calibration||{bins:[],ece:null,brier:null,n:0,hist_win:[],hist_loss:[]};
  const eceTxt=cal.ece!=null?cal.ece.toFixed(3):'—';
  const eceCol=cal.ece==null?'#8b949e':(cal.ece<0.03?'#3fb950':(cal.ece<0.07?'#d29922':'#f85149'));
  cards.push(`<div class="card"><h2>⑮ value 較正 (予測勝率 vs 実勝率)
    <span style="float:right;font-size:11px;color:${eceCol}">ECE=${eceTxt} Brier=${cal.brier!=null?cal.brier.toFixed(3):'—'}</span></h2>
    <p class="sub">配備 value.pkl を ${cal.n.toLocaleString()} 局面に適用。 点=各予測帯の実勝率、 対角=完全較正</p>
    ${cal.bins&&cal.bins.length?reliab(cal.bins):'<p class="note">value.pkl 未生成 / featurize 待ち</p>'}
    <p class="note">対角より<b>上</b>=value が<b>悲観</b>(勝ちを低く見積る)、 <b>下</b>=<b>楽観</b>(lethal 過大評価の兆候)。 ECE&lt;0.03 が理想</p></div>`);
  // ⑯ 予測値ヒスト (弁別力)
  cards.push(`<div class="card"><h2>⑯ 予測値の分布 (弁別力)</h2>
    <p class="sub">勝局面(緑)は右、 負局面(赤)は左に寄るほど value が勝敗を弁別できている</p>
    ${cal.hist_win&&(cal.hist_win.length||cal.hist_loss.length)?histDual(cal.hist_win,cal.hist_loss):'<p class="note">value.pkl 未生成 / featurize 待ち</p>'}
    <p class="note">2 山が重なる(中央に集中)=弁別できていない。 較正(⑮)とは別軸で、 AUC を視覚化したもの</p></div>`);
  // ③ corpus 成長 + ④ 対1世代前
  cards.push(`<div class="card"><h2>③ 対 1 世代前 勝率 (直近ラウンド)</h2>
    <p class="sub">世代交代が進んでいるか。 50% 付近で振動 = cycling</p>
    ${line(loop,'corpus','win',{ymin:0.3,ymax:0.7,fmt:v=>(v*100).toFixed(0)+'%',ref:0.5,color:'#d29922'})}
    <p class="note">上向きなら新世代が前世代を確実に越えている</p></div>`);
  // ⑤ デッキ分散
  cards.push(`<div class="card"><h2>⑤ hero デッキ分散 (上位12)</h2>
    <p class="sub">最小 ${c.hero_min} / 最大 ${c.hero_max} 局面 (${c.hero_n_decks} 種)。 均等なほど良い</p>
    ${bars(c.hero_top.map(d=>({l:d.deck.replace(/^(cardrush_|tcgportal_|train_)/,''),n:d.n})),'l','n',{fmt:v=>v})}
    </div>`);
  // ⑥ turn別
  cards.push(`<div class="card"><h2>⑥ turn 別 hero 勝率 (局面分布)</h2>
    <p class="sub">終盤ほど勝敗が確定。 序盤の勝率が学習の難所</p>
    ${bars(c.turn_winrate.map(d=>({l:d.bucket,w:d.win})),'l','w',{fmt:v=>(v*100).toFixed(0)+'%'})}
    </div>`);
  // ⑧ corpus 成長
  cards.push(`<div class="card"><h2>⑧ corpus 成長 (iter vs 局面数)</h2>
    <p class="sub">データ量の推移。 増えても①②が横ばいなら「量は律速でない」</p>
    ${line(man,'iter','n',{fmt:v=>(v/1000).toFixed(0)+'k',color:'#a371f7'})}</div>`);
  // ⑨ スループット
  cards.push(`<div class="card"><h2>⑨ 収集スループット (samples/分)</h2>
    <p class="sub">ラウンド毎の生成速度。 急落は value 肥大や CPU 競合の兆候</p>
    ${line(tp,'i','spm',{ymin:0,fmt:v=>v.toFixed(0),color:'#db6d28'})}
    <p class="note">${tp.length?('直近 '+tp[tp.length-1].games+'/500 games / '+tp[tp.length-1].secs+'s'):''}</p></div>`);
  // ⑩ 相手 leader 別勝率
  cards.push(`<div class="card"><h2>⑩ 相手リーダー別 hero 勝率</h2>
    <p class="sub">どのアーキタイプに勝てて/負けているか (出現多い順)</p>
    ${c.opp_leader&&c.opp_leader.length?wtable(c.opp_leader,'leader'):'<p class="note">集計中</p>'}</div>`);
  // ⑪ hero デッキ別 得意/苦手
  cards.push(`<div class="card"><h2>⑪ hero デッキ別 勝率 (得意/苦手)</h2>
    <p class="sub">value がうまく操縦できるデッキ / できないデッキ (n≥40)</p>
    <div style="color:#3fb950;font-size:11px;margin:2px 0">得意 top6</div>
    ${c.hero_best?wtable(c.hero_best.map(r=>({...r,deck:r.deck.replace(/^(cardrush_|tcgportal_|train_)/,'')})),'deck'):''}
    <div style="color:#f85149;font-size:11px;margin:8px 0 2px">苦手 worst6</div>
    ${c.hero_worst?wtable(c.hero_worst.map(r=>({...r,deck:r.deck.replace(/^(cardrush_|tcgportal_|train_)/,'')})),'deck'):''}</div>`);
  // ⑰ matchup ヒートマップ (全幅)
  const mu=c.matchup||{rows:[],cols:[],cells:[]};
  cards.push(`<div class="card" style="grid-column:1/-1"><h2>⑰ matchup ヒートマップ (自分リーダー × 相手リーダー、 hero 視点勝率)</h2>
    <p class="sub">行=自分リーダー / 列=相手リーダー(アーキタイプ)。 セル=勝率、 50% を中点に青(有利)↔赤(不利)。 各セル n≥20、 低Nは灰</p>
    <div style="overflow-x:auto">${heatmap(mu.rows,mu.cols,mu.cells)}</div>
    <p class="note">self-play データなので「相性の構造」を読む図 (使用率は設計値なので無意味)。 ⑩(相手リーダー別)の 2D 版 — 行内に赤が多いリーダー = value が操縦しづらい苦手対面を抱える</p></div>`);
  // ⑫ ゲーム長分布
  cards.push(`<div class="card"><h2>⑫ ゲーム長 分布</h2>
    <p class="sub">中央値 ${c.game_len_median||'—'} ターン (${(c.game_len_n||0).toLocaleString()} game)。 短すぎ=速攻偏り</p>
    ${c.game_len?bars(c.game_len.map(d=>({l:d.turn,n:d.n})),'l','n',{fmt:v=>v}):'<p class="note">g付き行が必要</p>'}</div>`);
  // ⑬ rollout ラベル相関
  const rows=[];
  for(const [k,r] of [['greedy',ro.greedy],['beam',ro.beam]]){ if(!r) continue;
    rows.push(`<tr><td>${k}</td><td>${r.n}</td><td>corr=${r.corr}</td>
      <td>敗時 yr=${r.yr_on_loss}</td><td>勝時 yr=${r.yr_on_win}</td></tr>`);}
  cards.push(`<div class="card"><h2>⑬ rollout ラベル分析 (本命)</h2>
    <p class="sub">最終勝敗より強い教師か。 corr(y,yr)=相関、 勝時 yr > 敗時 yr なら勝敗を予見</p>
    <table><tr style="color:#8b949e"><td>policy</td><td>n</td><td>相関</td><td>敗局面</td><td>勝局面</td></tr>${rows.join('')||'<tr><td colspan=5>収集中</td></tr>'}</table>
    <p class="note">rollout(greedy)=1回目は互角 (0.496)。 beam の勝時/敗時 yr の差が大きいほど良い教師</p></div>`);
  // ⑭ ExIt 複利ループ (本命)
  const ex=s.exit||{history:[],has_policy:false};
  cards.push(`<div class="card"><h2>⑭ ExIt 複利ループ (探索→policy蒸留→探索↑)</h2>
    <p class="sub">top-1 = policy が探索の最善手を再現する率。 上がり続ければ蒸留が効いている</p>
    ${ex.history&&ex.history.length?line(ex.history.filter(e=>e.top1!=null),'iter','top1',{ymin:0,ymax:1,fmt:v=>(v*100).toFixed(0)+'%',color:'#2ea043'}):'<p class="note">policy 学習待ち (collect→train 進行中)</p>'}
    <p class="note">policy model: ${ex.has_policy?'有り (beam prior に還元中)':'未生成'} ${ex.history&&ex.history.length?('/ 最新 top-1='+((ex.history[ex.history.length-1].top1||0)*100).toFixed(0)+'% vs random '+((ex.history[ex.history.length-1].rand||0)*100).toFixed(0)+'%'):''}</p></div>`);
  // ⑦ rollout 局面数
  cards.push(`<div class="card"><h2>⑦ rollout 収集 現況</h2>
    <p class="sub">実験データの蓄積</p>
    <table><tr><td>rollout(greedy) 局面</td><td>${c.rollout_greedy.toLocaleString()}</td></tr>
    <tr><td>rollout(beam) 局面</td><td>${c.rollout_beam.toLocaleString()}</td></tr></table></div>`);
  document.getElementById('grid').replaceChildren(...cards.map(h=>$(h)));
}
let _timer=setInterval(()=>{if(document.getElementById('auto').checked)load();},15000);
document.getElementById('refresh').addEventListener('click',()=>load(true));  // 強制更新 (cache無視)
load();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/stats"):
            force = "force=1" in self.path
            body = json.dumps(_stats(force)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    a = ap.parse_args()
    # 起動時に corpus を 1 回温めておく (別スレッド、 初回アクセスを速く)
    threading.Thread(target=_corpus_stats, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print(f"EIV1 ダッシュボード → http://localhost:{a.port}  (Ctrl-C で停止)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
