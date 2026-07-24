"""EIV1 学習データ可視化ダッシュボード (localhost) — 2026-07-24。

学習中の db/eiv1/ を読んで、 人間が傾向を一目で分かるグラフを localhost に出す。
外部依存なし (stdlib http.server + 自前 SVG チャート)、 学習を邪魔しない (読むだけ)。

  .venv/bin/python scripts/eiv1_dashboard.py            # http://localhost:8770
  .venv/bin/python scripts/eiv1_dashboard.py --port 9000

見られる指標:
  ① 強さ推移 (ε=0 arena vs EBV2)  = 絶対的に強くなっているか (本物の物差し)
  ② AUC 推移                      = 予測精度 (学習の進み)
  ③ corpus 成長                   = データ量
  ④ 対 1 世代前 勝率 (直近ラウンド) = 世代交代が進んでいるか (cycling の速報)
  ⑤ デッキ分散                    = hero デッキが偏っていないか
  ⑥ turn 別 win率                 = 局面分布
  ⑦ rollout 実験の現況
"""
from __future__ import annotations
import argparse
import json
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EIV1 = ROOT / "db" / "eiv1"

_CACHE: dict = {"corpus": None, "corpus_ts": 0.0}
_CORPUS_TTL = 60.0   # corpus スキャンは重いので 60s キャッシュ


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


def _corpus_stats() -> dict:
    """corpus 末尾をサンプルして分散/turn別勝率。 TTL キャッシュ (重い)。"""
    now = time.time()
    if _CACHE["corpus"] and now - _CACHE["corpus_ts"] < _CORPUS_TTL:
        return _CACHE["corpus"]
    p = EIV1 / "corpus.jsonl"
    res = {"total": 0, "games_est": 0, "hero_top": [], "hero_min": 0, "hero_max": 0,
           "hero_n_decks": 0, "turn_winrate": [], "rollout_greedy": 0, "rollout_beam": 0}
    try:
        # 末尾 ~30k 行をサンプル
        lines = []
        with open(p, encoding="utf-8") as f:
            for line in f:
                lines.append(line)
                if len(lines) > 30000:
                    lines.pop(0)
        res["total"] = sum(1 for _ in open(p))
        res["games_est"] = res["total"] // 12
        hero = Counter()
        turn_bucket: dict = {}
        for line in lines:
            try:
                d = json.loads(line)
                hero[d.get("hero", "?")] += 1
                t = int((d.get("state") or {}).get("turn_number") or 0)
                b = "1-4" if t <= 4 else ("5-7" if t <= 7 else ("8-10" if t <= 10 else "11+"))
                tb = turn_bucket.setdefault(b, [0, 0])
                tb[0] += 1
                tb[1] += int(d.get("y", 0))
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
    except Exception:
        pass
    for tag, key in (("rollout_corpus.jsonl", "rollout_greedy"),
                     ("rollout_corpus_beam.jsonl", "rollout_beam")):
        f = EIV1 / tag
        if f.exists():
            try:
                res[key] = sum(1 for _ in open(f))
            except Exception:
                pass
    _CACHE["corpus"], _CACHE["corpus_ts"] = res, now
    return res


def _stats() -> dict:
    return {"manifest": _read_manifest(), "arena": _read_arena(),
            "loop": _read_loop_progress(), "corpus": _corpus_stats(),
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
<header><h1>EIV1 学習ダッシュボード</h1><span class="ts" id="ts"></span></header>
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
async function load(){
  const s=await (await fetch('/api/stats')).json();
  document.getElementById('ts').textContent='更新 '+s.ts;
  const c=s.corpus, arena=s.arena, man=s.manifest, loop=s.loop;
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
  // ⑦ rollout
  cards.push(`<div class="card"><h2>⑦ rollout target 実験</h2>
    <p class="sub">最終勝敗ラベルより強い教師を作れるか (本命)</p>
    <table><tr><td>rollout(greedy) 局面</td><td>${c.rollout_greedy.toLocaleString()}</td></tr>
    <tr><td>rollout(beam) 局面</td><td>${c.rollout_beam.toLocaleString()}</td></tr></table>
    <p class="note">beam rollout > outcome なら「policy 整合が鍵」が確定</p></div>`);
  document.getElementById('grid').replaceChildren(...cards.map(h=>$(h)));
}
load();setInterval(load,15000);
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
