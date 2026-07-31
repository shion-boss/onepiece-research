"""Rust ネイティブ self-play 強化学習ダッシュボード (localhost) — 2026-07-31。

Rust の Expert Iteration ループ (scripts/rust_selfplay_ei.py) を「回す前」から「回している最中」まで
多角的に観察するための localhost ダッシュボード。 db/rust_selfplay/manifest.json を読むだけ (学習を邪魔しない)。
外部依存なし (stdlib http.server + 自前 SVG)。

  .venv/bin/python scripts/rust_selfplay_dashboard.py            # http://localhost:8770
  .venv/bin/python scripts/rust_selfplay_dashboard.py --port 9000

観察軸 (3 系統):
  A. 成長段階   — ① A/B 新vs旧 勝率 (本物の物差し) / ⑨ 採否タイムライン / ② 生成スループット
  B. 学習状況   — ③ AUC (train/holdout) / ④ loss+Brier / ⑤ value 較正 / ⑥ 予測値ヒスト / ⑦ 学習した重み
  C. self-play 分散 — ⑧ デッキ分散 / ⑩ 先攻有利+draw / ⑪ ゲーム長 / ⑫ ターン別勝率 /
                      ⑬ matchup ヒート / ⑭ デッキ別勝率 / ⑮ 特徴分布

データが無い状態 (RL 開始前) では preflight (heuristic self-play の分散 + engine 速度) を表示し、
round が溜まるにつれ成長/学習の系列が現れる。
"""
from __future__ import annotations
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "db" / "rust_selfplay" / "manifest.json"


def _load() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"config": {}, "rounds": [], "preflight": None}


def _stats() -> dict:
    man = _load()
    rounds = man.get("rounds") or []
    cfg = man.get("config") or {}
    pf = man.get("preflight")
    feat_names = cfg.get("features") or [f"f{i}" for i in range(16)]

    growth, auc, loss, tp, seat = [], [], [], [], []
    for r in rounds:
        i = r.get("round")
        growth.append({"round": i, "win": r.get("ab_win"), "se": r.get("ab_se"),
                       "gate": r.get("gate"), "adopt": r.get("adopt")})
        auc.append({"round": i, "train_auc": r.get("train_auc"),
                    "holdout_auc": r.get("holdout_auc")})
        loss.append({"round": i, "logloss": r.get("train_logloss"), "brier": r.get("brier")})
        tp.append({"round": i, "sps": r.get("samples_per_sec")})
        sp = r.get("selfplay") or {}
        seat.append({"round": i, "fp": sp.get("first_player_winrate"),
                     "draw": sp.get("draw_rate")})

    # active self-play block: 最新 round の分散、 無ければ preflight
    active = None
    active_src = None
    if rounds:
        active = rounds[-1].get("selfplay")
        active_src = f"round {rounds[-1].get('round')} (value 学習後)"
    elif pf:
        active = pf.get("selfplay")
        active_src = "preflight (heuristic、 RL 開始前)"

    latest = rounds[-1] if rounds else None
    weights_latest = None
    if latest and latest.get("weights"):
        w = latest["weights"]
        weights_latest = [{"name": feat_names[i] if i < len(feat_names) else f"f{i}",
                           "w": round(float(w[i]), 3)} for i in range(len(w))]

    # 重み推移 (feature 別、 round 系列) — 学習が何を掴んだかの変化
    weight_series = []
    if len([r for r in rounds if r.get("weights")]) >= 2:
        idxs = list(range(len(feat_names)))
        for fi in idxs:
            pts = [{"round": r.get("round"), "w": round(float(r["weights"][fi]), 3)}
                   for r in rounds if r.get("weights") and fi < len(r["weights"])]
            weight_series.append({"name": feat_names[fi], "points": pts})

    n_adopt = sum(1 for r in rounds if r.get("adopt"))
    total_games = sum(int(r.get("n_games") or 0) for r in rounds)
    best_ho = max([r.get("holdout_auc") for r in rounds if r.get("holdout_auc")], default=None)
    latest_win = growth[-1]["win"] if growth else None
    gps = None
    if pf:
        gps = pf.get("games_per_sec")

    return {
        "config": cfg, "preflight": pf, "has_rounds": bool(rounds),
        "kpi": {"n_rounds": len(rounds), "n_adopt": n_adopt, "latest_win": latest_win,
                "best_holdout_auc": best_ho, "total_games": total_games, "games_per_sec": gps},
        "growth": growth, "auc": auc, "loss": loss, "throughput": tp, "seat": seat,
        "weights_latest": weights_latest, "weight_series": weight_series,
        "calibration": latest.get("calibration") if latest else None,
        "hist_win": latest.get("hist_win") if latest else None,
        "hist_loss": latest.get("hist_loss") if latest else None,
        "active_selfplay": active, "active_src": active_src,
        "feat_names": feat_names,
        "updated": man.get("updated", "—"),
    }


HTML = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>Rust self-play RL ダッシュボード</title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#0d1117;color:#c9d1d9;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:14px 20px;background:#161b22;border-bottom:1px solid #30363d;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
h1{font-size:16px;margin:0;font-weight:600}
.ts{color:#8b949e;font-size:12px}
.sec{max-width:1500px;margin:0 auto;padding:4px 16px}
.sech{font-size:13px;font-weight:700;color:#e6edf3;margin:18px 4px 2px;letter-spacing:.03em;border-left:3px solid #58a6ff;padding-left:8px}
.sech .d{color:#8b949e;font-weight:400;font-size:11px;margin-left:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:14px;padding:6px 0}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
.card h2{font-size:13px;margin:0 0 4px;font-weight:600}
.card .sub{color:#8b949e;font-size:11px;margin:0 0 10px}
.kpi{display:flex;gap:18px;flex-wrap:wrap;padding:4px 0}
.kpi div{min-width:96px}
.kpi b{display:block;font-size:22px;font-weight:600;color:#58a6ff}
.kpi span{font-size:11px;color:#8b949e}
svg{width:100%;height:200px;display:block}
.gl{stroke:#21262d;stroke-width:1}
.lbl{fill:#8b949e;font-size:10px}
.bar{fill:#388bfd}
table{width:100%;border-collapse:collapse;font-size:12px}
td{padding:2px 6px;border-bottom:1px solid #21262d}
.note{color:#8b949e;font-size:11px;margin-top:8px;line-height:1.5}
.badge{display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;background:#1f6feb33;color:#79c0ff;border:1px solid #1f6feb55}
.pill{display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;margin:1px}
</style></head><body>
<header><h1>Rust self-play 強化学習ダッシュボード <span class="badge" id="mode">—</span></h1>
<div style="display:flex;align-items:center;gap:12px">
  <span class="ts" id="ts"></span>
  <label style="font-size:12px;color:#8b949e;display:flex;align-items:center;gap:4px;cursor:pointer">
    <input type="checkbox" id="auto" checked>自動更新(15s)</label>
  <button id="refresh" style="background:#238636;color:#fff;border:0;border-radius:6px;
    padding:6px 14px;font-size:13px;cursor:pointer">今すぐ更新</button>
</div></header>
<div id="root"></div>
<script>
const $=(h)=>{const t=document.createElement('template');t.innerHTML=h.trim();return t.content.firstChild;};
function fmt2(v){return Number.isInteger(v)?v:v.toFixed(0);}
function line(data, xk, yk, {ymin=null,ymax=null,fmt=(v)=>v.toFixed(3),ref=null,color='#58a6ff',se=null,gate=null}={}){
  const W=420,H=200,pl=44,pr=12,pt=12,pb=26;
  const dd=data.filter(d=>d[yk]!=null);
  if(!dd.length) return `<svg viewBox="0 0 ${W} ${H}"><text x="${W/2}" y="${H/2}" class="lbl" text-anchor="middle">データ待ち (round 実行後に表示)</text></svg>`;
  const xs=dd.map(d=>d[xk]), ys=dd.map(d=>d[yk]);
  let y0=ymin!==null?ymin:Math.min(...ys), y1=ymax!==null?ymax:Math.max(...ys);
  if(y0===y1){y0-=0.5;y1+=0.5;}
  const x0=Math.min(...xs), x1=Math.max(...xs);
  const X=v=>pl+(x1===x0?0.5:(v-x0)/(x1-x0))*(W-pl-pr);
  const Y=v=>pt+(1-(v-y0)/(y1-y0))*(H-pt-pb);
  let g='';
  for(let i=0;i<=4;i++){const yv=y0+(y1-y0)*i/4;const yy=Y(yv);
    g+=`<line class="gl" x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}"/><text class="lbl" x="${pl-4}" y="${yy+3}" text-anchor="end">${fmt(yv)}</text>`;}
  if(ref!==null&&ref>=y0&&ref<=y1){const yy=Y(ref);g+=`<line x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}" stroke="#f85149" stroke-dasharray="4 3" stroke-width="1"/>`;}
  if(gate!==null&&gate>=y0&&gate<=y1){const yy=Y(gate);g+=`<line x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}" stroke="#d29922" stroke-dasharray="2 3" stroke-width="1"/><text class="lbl" x="${W-pr}" y="${yy-2}" text-anchor="end" fill="#d29922">gate ${gate}</text>`;}
  if(se){for(const d of dd){if(d[se]==null)continue;const cx=X(d[xk]),s=d[se]||0;g+=`<line x1="${cx}" y1="${Y(d[yk]-s)}" x2="${cx}" y2="${Y(d[yk]+s)}" stroke="${color}" stroke-opacity="0.4" stroke-width="1"/>`;}}
  const path=dd.map((d,i)=>`${i?'L':'M'}${X(d[xk]).toFixed(1)} ${Y(d[yk]).toFixed(1)}`).join(' ');
  g+=`<path d="${path}" fill="none" stroke="${color}" stroke-width="2"/>`;
  for(const d of dd){const col=(d.adopt===true)?'#3fb950':(d.adopt===false?'#f85149':color);g+=`<circle cx="${X(d[xk])}" cy="${Y(d[yk])}" r="3" fill="${col}"/>`;}
  g+=`<text class="lbl" x="${pl}" y="${H-6}">r${fmt2(x0)}</text><text class="lbl" x="${W-pr}" y="${H-6}" text-anchor="end">r${fmt2(x1)}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}
function line2(data, xk, series, {ymin=null,ymax=null,fmt=(v)=>v.toFixed(3),ref=null}={}){
  const W=420,H=200,pl=44,pr=12,pt=16,pb=26;
  const all=[];series.forEach(s=>data.forEach(d=>{if(d[s.k]!=null)all.push(d[s.k]);}));
  if(!all.length) return `<svg viewBox="0 0 ${W} ${H}"><text x="${W/2}" y="${H/2}" class="lbl" text-anchor="middle">データ待ち</text></svg>`;
  let y0=ymin!==null?ymin:Math.min(...all), y1=ymax!==null?ymax:Math.max(...all);
  if(y0===y1){y0-=0.1;y1+=0.1;}
  const xs=data.map(d=>d[xk]);const x0=Math.min(...xs),x1=Math.max(...xs);
  const X=v=>pl+(x1===x0?0.5:(v-x0)/(x1-x0))*(W-pl-pr);
  const Y=v=>pt+(1-(v-y0)/(y1-y0))*(H-pt-pb);
  let g='';
  for(let i=0;i<=4;i++){const yv=y0+(y1-y0)*i/4;const yy=Y(yv);
    g+=`<line class="gl" x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}"/><text class="lbl" x="${pl-4}" y="${yy+3}" text-anchor="end">${fmt(yv)}</text>`;}
  if(ref!==null&&ref>=y0&&ref<=y1){const yy=Y(ref);g+=`<line x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}" stroke="#f85149" stroke-dasharray="4 3" stroke-width="1"/>`;}
  series.forEach((s,si)=>{const dd=data.filter(d=>d[s.k]!=null);
    if(!dd.length)return;
    const path=dd.map((d,i)=>`${i?'L':'M'}${X(d[xk]).toFixed(1)} ${Y(d[s.k]).toFixed(1)}`).join(' ');
    g+=`<path d="${path}" fill="none" stroke="${s.c}" stroke-width="2"/>`;
    for(const d of dd){g+=`<circle cx="${X(d[xk])}" cy="${Y(d[s.k])}" r="2.5" fill="${s.c}"/>`;}
    g+=`<rect x="${pl+6+si*130}" y="${pt-13}" width="10" height="10" fill="${s.c}"/><text class="lbl" x="${pl+20+si*130}" y="${pt-4}">${s.name}</text>`;});
  g+=`<text class="lbl" x="${pl}" y="${H-6}">r${fmt2(x0)}</text><text class="lbl" x="${W-pr}" y="${H-6}" text-anchor="end">r${fmt2(x1)}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}
function bars(data,lk,vk,{fmt=(v)=>v.toFixed(2),color='#388bfd'}={}){
  const W=420,H=200,pl=44,pr=12,pt=12,pb=44;const vs=data.map(d=>d[vk]);
  if(!data.length)return '<svg viewBox="0 0 420 200"><text x="210" y="100" class="lbl" text-anchor="middle">データ待ち</text></svg>';
  const vmax=Math.max(...vs,0.001);const bw=(W-pl-pr)/data.length*0.7;let g='';
  data.forEach((d,i)=>{const x=pl+(i+0.15)*(W-pl-pr)/data.length;const h=(d[vk]/vmax)*(H-pt-pb);
    g+=`<rect x="${x}" y="${H-pb-h}" width="${bw}" height="${h}" fill="${color}"/>`;
    g+=`<text class="lbl" x="${x+bw/2}" y="${H-pb+11}" text-anchor="middle" transform="rotate(-30 ${x+bw/2} ${H-pb+11})">${d[lk]}</text>`;
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
  const pts=(bins||[]).filter(b=>b.actual!=null);
  if(pts.length){
    const path=pts.map((b,i)=>`${i?'L':'M'}${X(b.pred).toFixed(1)} ${Y(b.actual).toFixed(1)}`).join(' ');
    g+=`<path d="${path}" fill="none" stroke="#58a6ff" stroke-width="2"/>`;
    const nmax=Math.max(...pts.map(b=>b.n),1);
    for(const b of pts){const r=(2.5+4*Math.sqrt(b.n/nmax)).toFixed(1);
      g+=`<circle cx="${X(b.pred)}" cy="${Y(b.actual)}" r="${r}" fill="#58a6ff" fill-opacity="0.75"/>`;}
  } else { g+=`<text x="${W/2}" y="${H/2}" class="lbl" text-anchor="middle">データ待ち</text>`; }
  g+=`<text class="lbl" x="${pl+2}" y="${pt+2}">実勝率↑ / 予測勝率→ (対角=完全較正)</text>`;
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}
function histDual(win,loss){
  const W=420,H=200,pl=40,pr=12,pt=12,pb=26;const n=(win&&win.length)||10;
  if((!win||!win.length)&&(!loss||!loss.length)) return `<svg viewBox="0 0 ${W} ${H}"><text x="${W/2}" y="${H/2}" class="lbl" text-anchor="middle">データ待ち</text></svg>`;
  const mx=Math.max(...(win||[]),...(loss||[]),1);const bw=(W-pl-pr)/n;let g='';
  for(let i=0;i<=4;i++){const yy=pt+(1-i/4)*(H-pt-pb);
    g+=`<line class="gl" x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}"/><text class="lbl" x="${pl-4}" y="${yy+3}" text-anchor="end">${Math.round(mx*i/4)}</text>`;}
  for(let i=0;i<n;i++){const x=pl+i*bw;
    const hw=(win[i]||0)/mx*(H-pt-pb), hl=(loss[i]||0)/mx*(H-pt-pb);
    g+=`<rect x="${x+bw*0.12}" y="${H-pb-hl}" width="${bw*0.76}" height="${hl}" fill="#f85149" fill-opacity="0.55"/>`;
    g+=`<rect x="${x+bw*0.12}" y="${H-pb-hw}" width="${bw*0.76}" height="${hw}" fill="#3fb950" fill-opacity="0.6"/>`;}
  [0,0.5,1].forEach(t=>{g+=`<text class="lbl" x="${pl+t*(W-pl-pr)}" y="${H-8}" text-anchor="middle">${t}</text>`;});
  g+=`<rect x="${W-96}" y="10" width="10" height="10" fill="#3fb950" fill-opacity="0.6"/><text class="lbl" x="${W-82}" y="19">勝局面</text>`;
  g+=`<rect x="${W-96}" y="24" width="10" height="10" fill="#f85149" fill-opacity="0.55"/><text class="lbl" x="${W-82}" y="33">負局面</text>`;
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}
function weightBars(rows){
  // 符号付き水平バー (正=青/負=赤)、 中央=0。 学習 value が何を重視するか
  if(!rows||!rows.length) return `<p class="note">round 実行後に表示 (学習した重み)</p>`;
  const mx=Math.max(...rows.map(r=>Math.abs(r.w)),0.01);
  return `<div style="display:flex;flex-direction:column;gap:2px">`+rows.map(r=>{
    const w=r.w, pct=Math.abs(w)/mx*50, col=w>=0?'#388bfd':'#f85149';
    const left = w>=0 ? 50 : 50-pct;
    return `<div style="display:flex;align-items:center;gap:6px;font-size:11px">`
      +`<span style="width:96px;text-align:right;color:#c9d1d9;white-space:nowrap;overflow:hidden">${r.name}</span>`
      +`<span style="flex:1;position:relative;height:13px;background:#0d1117;border-radius:2px">`
      +`<span style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:#30363d"></span>`
      +`<span style="position:absolute;left:${left}%;top:0;height:100%;width:${pct}%;background:${col};border-radius:2px"></span></span>`
      +`<span style="width:48px;text-align:right;color:${col}">${w>=0?'+':''}${w.toFixed(2)}</span></div>`;
  }).join('')+`</div>`;
}
function _lerp(a,b,t){return Math.round(a+(b-a)*t);}
function wcolor(w){ if(w==null) return '#161b22';
  const t=(w-0.5)*2;
  if(t>=0) return `rgb(${_lerp(45,31,t)},${_lerp(51,111,t)},${_lerp(59,235,t)})`;
  const a=-t; return `rgb(${_lerp(45,218,a)},${_lerp(51,54,a)},${_lerp(59,51,a)})`;
}
function heatmap(labels,cells){
  if(!labels||!labels.length) return '<p class="note">matchup 集計中 (各セル n≥5)</p>';
  const n=labels.length, lw=96, cw=46, rh=24, top=58;
  const W=lw+n*cw+8, H=top+n*rh+6;
  let g='';
  for(let j=0;j<n;j++){const cx=lw+j*cw+cw/2;
    g+=`<text class="lbl" x="${cx}" y="${top-6}" text-anchor="end" transform="rotate(-40 ${cx} ${top-6})">${labels[j]}</text>`;}
  for(let i=0;i<n;i++){const y=top+i*rh;
    g+=`<text class="lbl" x="0" y="${y+15}">${labels[i]}</text>`;
    for(let j=0;j<n;j++){const c=cells[i][j], x=lw+j*cw;
      g+=`<rect x="${x}" y="${y}" width="${cw-2}" height="${rh-3}" fill="${wcolor(c.win)}" stroke="#0d1117"/>`;
      if(c.win!=null) g+=`<text x="${x+(cw-2)/2}" y="${y+15}" text-anchor="middle" style="font-size:10px;fill:#fff">${Math.round(c.win*100)}</text>`;}
  }
  return `<svg viewBox="0 0 ${W} ${H}" style="height:${H}px">${g}</svg>`;
}
function featDist(names,mean,std){
  // 特徴 mean ± std を水平に。 self-play 局面が各特徴でどう散っているか
  if(!mean||!mean.length) return `<p class="note">データ待ち</p>`;
  const rows=names.map((nm,i)=>({nm,m:mean[i],s:std[i]||0}));
  const lo=Math.min(...rows.map(r=>r.m-r.s),0), hi=Math.max(...rows.map(r=>r.m+r.s),0);
  const span=(hi-lo)||1;
  const X=v=>((v-lo)/span*100);
  return `<div style="display:flex;flex-direction:column;gap:2px">`+rows.map(r=>{
    return `<div style="display:flex;align-items:center;gap:6px;font-size:11px">`
      +`<span style="width:96px;text-align:right;color:#c9d1d9;white-space:nowrap;overflow:hidden">${r.nm}</span>`
      +`<span style="flex:1;position:relative;height:12px;background:#0d1117;border-radius:2px">`
      +(lo<0&&hi>0?`<span style="position:absolute;left:${X(0)}%;top:0;bottom:0;width:1px;background:#30363d"></span>`:'')
      +`<span style="position:absolute;left:${X(r.m-r.s)}%;width:${(r.s*2/span*100).toFixed(1)}%;top:4px;height:4px;background:#8b949e55;border-radius:2px"></span>`
      +`<span style="position:absolute;left:${(X(r.m)-1).toFixed(1)}%;top:1px;width:6px;height:10px;background:#58a6ff;border-radius:2px"></span></span>`
      +`<span style="width:78px;text-align:right;color:#8b949e">${r.m.toFixed(2)}±${r.s.toFixed(2)}</span></div>`;
  }).join('')+`</div>`;
}
function wrbar(w){const p=(w*100).toFixed(0);const col=w>=0.5?'#3fb950':'#f85149';
  return `<div style="background:#21262d;border-radius:3px;height:14px;position:relative">
    <div style="background:${col};width:${Math.min(100,w*100)}%;height:100%;border-radius:3px"></div>
    <span style="position:absolute;right:4px;top:0;font-size:10px;line-height:14px">${p}%</span></div>`;}
function section(title,desc){return `<div class="sech">${title}<span class="d">${desc}</span></div>`;}
function grid(cards){return `<div class="grid">${cards.join('')}</div>`;}

async function load(force){
  const btn=document.getElementById('refresh');
  if(force){btn.textContent='更新中...';btn.disabled=true;}
  let s;
  try{ s=await (await fetch('/api/stats')).json(); }
  catch(e){ if(force){btn.textContent='今すぐ更新';btn.disabled=false;} return; }
  if(force){btn.textContent='今すぐ更新';btn.disabled=false;}
  document.getElementById('ts').textContent='更新 '+s.updated;
  const cfg=s.config||{}, k=s.kpi||{}, root=document.getElementById('root');
  document.getElementById('mode').textContent = s.has_rounds ? `RL 進行中 (round ${k.n_rounds})` : 'RL 開始前 (preflight)';
  const out=[];

  // ===== KPI + 設定 (pre-flight observability) =====
  out.push(`<div class="sec">${grid([
    `<div class="card"><h2>現況</h2><div class="kpi">
      <div><b>${k.n_rounds}</b><span>実行 round (採用 ${k.n_adopt})</span></div>
      <div><b>${k.latest_win!=null?(k.latest_win*100).toFixed(1)+'%':'—'}</b><span>最新 A/B (新vs旧)</span></div>
      <div><b>${k.best_holdout_auc!=null?k.best_holdout_auc.toFixed(3):'—'}</b><span>最良 holdout AUC</span></div>
      <div><b>${k.games_per_sec!=null?Math.round(k.games_per_sec):'—'}</b><span>engine 速度 (games/s)</span></div>
      <div><b>${(k.total_games||0).toLocaleString()}</b><span>累計生成ゲーム</span></div>
    </div></div>`,
    (()=>{
      const dl=cfg.deck_leaders||{};
      const decks=(cfg.decks||[]).map(d=>{const L=dl[d]||{};return `<span class="pill" style="background:#21262d">${(L.name||d)} <span style="color:#6e7681">${d.replace(/^(cardrush_|tcgportal_|pros02_)/,'')}</span></span>`;}).join('');
      const feats=(cfg.features||[]).map((f,i)=>`<span class="pill" style="background:#0d1117;color:#8b949e">${i}:${f}</span>`).join('');
      return `<div class="card" style="grid-column:1/-1"><h2>ループ設定 (フライホイール) <span style="color:#6e7681;font-weight:400">${cfg.note||''}</span></h2>
      <div style="display:flex;gap:24px;flex-wrap:wrap">
        <div><div class="sub" style="margin:0 0 3px">生成モード</div><b style="color:#58a6ff">${cfg.gen_mode||'—'}</b></div>
        <div><div class="sub" style="margin:0 0 3px">A/B 評価</div><b style="color:#58a6ff">${cfg.eval_mode||'—'} (${(cfg.beam||[]).join('/')})</b></div>
        <div><div class="sub" style="margin:0 0 3px">gate (採用下限)</div><b style="color:#d29922">${cfg.gate!=null?(cfg.gate*100).toFixed(0)+'%':'—'}</b></div>
        <div><div class="sub" style="margin:0 0 3px">生成/round</div><b>${cfg.games_per_round||'—'} games</b></div>
        <div><div class="sub" style="margin:0 0 3px">A/B games</div><b>${cfg.eval_games||'—'}</b></div>
      </div>
      <div class="sub" style="margin:10px 0 3px">デッキ pool (${(cfg.decks||[]).length} 種、 自己対戦)</div><div>${decks}</div>
      <div class="sub" style="margin:8px 0 3px">value 特徴 (${(cfg.features||[]).length} 次元、 線形 logistic)</div><div>${feats}</div>
      ${s.has_rounds?'':`<p class="note" style="border-top:1px solid #30363d;margin-top:10px;padding-top:8px"><b style="color:#d29922">RL 未開始:</b> 下の分散は preflight (heuristic self-play) の測定値。 <code style="color:#79c0ff">.venv/bin/python scripts/rust_selfplay_ei.py --rounds 8</code> を回すと round 系列 (成長/学習) がここに現れる (15s 自動更新)。</p>`}
      </div>`;
    })(),
  ])}</div>`);

  // ===== A. 成長段階 =====
  out.push(`<div class="sec">${section('A. 成長段階','value は世代を経て本当に強くなっているか')}${grid([
    `<div class="card"><h2>① A/B 新value vs 旧value (本物の物差し)</h2>
      <p class="sub">beam 葉評価での head-to-head。 赤破線=50%(互角) / 橙点線=gate。 点の緑=採用/赤=棄却</p>
      ${line(s.growth,'round','win',{ymin:0.3,ymax:0.7,fmt:v=>(v*100).toFixed(0)+'%',ref:0.5,se:'se',gate:cfg.gate})}
      <p class="note">50% 付近で振動なら「回っているが強くなっていない」。 gate を継続的に超えれば複利成長</p></div>`,
    `<div class="card"><h2>② 生成スループット (samples/秒)</h2>
      <p class="sub">Rust ネイティブ self-play の生成速度。 Rust を作った本来目的 = 単一 PC で高速ループ</p>
      ${line(s.throughput,'round','sps',{ymin:0,fmt:v=>v.toFixed(0),color:'#db6d28'})}
      <p class="note">急落は value 肥大 / CPU 競合の兆候。 Python 比 ~14x が想定値</p></div>`,
  ])}</div>`);

  // ===== B. 学習状況 =====
  out.push(`<div class="sec">${section('B. 学習状況','value (logistic) の予測精度・較正・掴んだ重み')}${grid([
    `<div class="card"><h2>③ AUC 推移 (予測精度)</h2>
      <p class="sub">value が勝敗を予測できる度合い。 holdout(緑) = リーク無しの本物</p>
      ${line2(s.auc,'round',[{k:'holdout_auc',name:'holdout',c:'#3fb950'},{k:'train_auc',name:'train',c:'#8b949e'}],{ymin:0.5,ymax:0.9,fmt:v=>v.toFixed(2),ref:0.5})}
      <p class="note">memo: このタスクの value AUC は ~0.75 で頭打ち = 天井は model でなく input 特徴。 プラトーなら表現の限界</p></div>`,
    `<div class="card"><h2>④ loss / Brier (学習の進み)</h2>
      <p class="sub">logloss(青) = 学習誤差、 Brier(橙) = holdout の二乗誤差。 下がるほど良い</p>
      ${line2(s.loss,'round',[{k:'logloss',name:'train logloss',c:'#58a6ff'},{k:'brier',name:'holdout Brier',c:'#db6d28'}],{ymin:0,fmt:v=>v.toFixed(2)})}
      </div>`,
    `<div class="card"><h2>⑤ value 較正 (予測勝率 vs 実勝率)
      <span style="float:right;font-size:11px;color:#8b949e" id="ece"></span></h2>
      <p class="sub">最新 round の holdout。 対角=完全較正。 上=悲観 / 下=楽観 (lethal 過大評価の兆候)</p>
      ${reliab(s.calibration&&s.calibration.bins)}
      </div>`,
    `<div class="card"><h2>⑥ 予測値の分布 (弁別力)</h2>
      <p class="sub">勝局面(緑)は右、 負局面(赤)は左に寄るほど value が勝敗を弁別できている</p>
      ${histDual(s.hist_win,s.hist_loss)}
      <p class="note">2 山が重なる=弁別できていない。 AUC(③) を視覚化したもの</p></div>`,
    `<div class="card"><h2>⑦ 学習した重み (value が重視する特徴)</h2>
      <p class="sub">最新 round の logistic 係数。 正(青)=勝ちに効く / 負(赤)=負けに効く特徴 (bias 含む)</p>
      ${weightBars(s.weights_latest)}
      <p class="note">ライフ差・手札差が大きく正なら健全。 spurious な特徴 (empty-hand 等) に偏ると greedy で exploit される</p></div>`,
    (s.weight_series&&s.weight_series.length? `<div class="card"><h2>⑦b 重み推移 (何を掴んでいくか)</h2>
      <p class="sub">主要特徴の係数が round でどう動くか</p>
      ${line2(s.weight_series.filter(w=>['ライフ差','手札差','盤面パワー差','使用可能ドン'].includes(w.name)).flatMap(w=>w.points.map(p=>({round:p.round,[w.name]:p.w}))).reduce((acc,cur)=>{const e=acc.find(a=>a.round===cur.round);if(e)Object.assign(e,cur);else acc.push(cur);return acc;},[]),'round',[{k:'ライフ差',name:'ライフ差',c:'#3fb950'},{k:'手札差',name:'手札差',c:'#58a6ff'},{k:'盤面パワー差',name:'盤面パワー差',c:'#db6d28'},{k:'使用可能ドン',name:'ドン',c:'#a371f7'}],{fmt:v=>v.toFixed(1)})}
      </div>`:''),
  ])}</div>`);

  // ===== C. self-play 分散 =====
  const sp=s.active_selfplay||{};
  out.push(`<div class="sec">${section('C. self-play 分散 / 偏り', (s.active_src||'—')+' の局面分布')}${grid([
    `<div class="card"><h2>⑧ デッキ分散 (登場ゲーム数)</h2>
      <p class="sub">各デッキが均等に自己対戦しているか。 min ${sp.deck_min??'—'} / max ${sp.deck_max??'—'} (${sp.deck_types??'—'} 種)</p>
      ${bars((sp.deck_dist||[]).map(d=>({l:(d.deck||'').replace(/^(cardrush_|tcgportal_|pros02_)/,''),n:d.n})),'l','n',{fmt:v=>v})}
      </div>`,
    `<div class="card"><h2>⑩ 先攻有利 / 引分率 (席バイアス)</h2>
      <p class="sub">先攻の勝率と draw 率の round 推移。 先攻勝率が 50% から大きく乖離 = 席の偏り</p>
      ${line2(s.seat,'round',[{k:'fp',name:'先攻勝率',c:'#58a6ff'},{k:'draw',name:'引分率',c:'#8b949e'}],{ymin:0,ymax:1,fmt:v=>(v*100).toFixed(0)+'%',ref:0.5})}
      <p class="note">現在: 先攻勝率 <b>${sp.first_player_winrate!=null?(sp.first_player_winrate*100).toFixed(0)+'%':'—'}</b> / 引分 <b>${sp.draw_rate!=null?(sp.draw_rate*100).toFixed(1)+'%':'—'}</b></p></div>`,
    `<div class="card"><h2>⑪ ゲーム長 分布</h2>
      <p class="sub">中央値 ${sp.median_turns??'—'} ターン (平均 ${sp.mean_turns??'—'})。 短すぎ=速攻偏り / v1 は防御未実装で短めになりがち</p>
      ${bars((sp.game_len_hist||[]).map(d=>({l:d.turn,n:d.n})),'l','n',{fmt:v=>v,color:'#a371f7'})}
      </div>`,
    `<div class="card"><h2>⑫ ターン別 hero 勝率 (局面分布)</h2>
      <p class="sub">終盤ほど勝敗が確定。 序盤の勝率が学習の難所</p>
      ${bars((sp.turn_winrate||[]).map(d=>({l:d.bucket,w:d.win})),'l','w',{fmt:v=>(v*100).toFixed(0)+'%',color:'#388bfd'})}
      </div>`,
    `<div class="card"><h2>⑭ デッキ別 勝率</h2>
      <p class="sub">この value がうまく操縦できるデッキ / できないデッキ</p>
      <table>${(sp.deck_dist||[]).slice().sort((a,b)=>b.win-a.win).map(d=>`<tr><td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${(d.deck||'').replace(/^(cardrush_|tcgportal_|pros02_)/,'')}</td><td style="width:100px">${wrbar(d.win)}</td><td style="color:#8b949e;width:36px;text-align:right">${d.n}</td></tr>`).join('')||'<tr><td>集計中</td></tr>'}</table>
      </div>`,
    `<div class="card"><h2>⑮ 特徴分布 (mean ± std)</h2>
      <p class="sub">self-play 局面が各特徴でどう散っているか。 分散が潰れている特徴は学習に効かない</p>
      ${featDist(s.feat_names,sp.feature_mean,sp.feature_std)}
      </div>`,
  ])}</div>`);

  // ⑬ matchup (full width)
  const mu=sp.matchup||{labels:[],cells:[]};
  out.push(`<div class="sec">${grid([
    `<div class="card" style="grid-column:1/-1"><h2>⑬ matchup ヒートマップ (自リーダー × 相手リーダー、 hero 視点勝率)</h2>
      <p class="sub">行=自分 / 列=相手。 セル=勝率、 50% を中点に青(有利)↔赤(不利)。 各セル n≥5、 低Nは灰。 ${s.active_src||''}</p>
      <div style="overflow-x:auto">${heatmap(mu.labels,mu.cells)}</div>
      <p class="note">アーキタイプ相性の構造を読む図。 行内に赤が多いリーダー = value が操縦しづらい苦手対面を抱える</p></div>`,
  ])}</div>`);

  root.replaceChildren(...out.map(h=>$(h)));
  const ece=document.getElementById('ece');
  if(ece&&s.calibration) ece.textContent=`ECE=${s.calibration.ece!=null?s.calibration.ece.toFixed(3):'—'}`;
}
setInterval(()=>{if(document.getElementById('auto').checked)load();},15000);
document.getElementById('refresh').addEventListener('click',()=>load(true));
load();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/stats"):
            body = json.dumps(_stats()).encode("utf-8")
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
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print(f"Rust self-play RL ダッシュボード → http://localhost:{a.port}  (Ctrl-C で停止)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
