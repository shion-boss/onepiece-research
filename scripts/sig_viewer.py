"""カード効果シグネチャ sig(card) 一覧ビューア — 2026-07-26。

人間が sig(card) の中身を検索/フィルタで眺め、 **実カードテキストと並べて「sig が効果と合ってるか」を
目視検証**するための軽量 UI。 db/card_sig.json + db/cards.json を読み、 port 8771 で HTTP 配信。

  .venv/bin/python scripts/sig_viewer.py           # http://127.0.0.1:8771
  .venv/bin/python scripts/sig_viewer.py --port 8899

overlay 改善 → build_card_sig.py 再導出 → このビューアで直ったか確認、 の verify ループに使う。
"""
from __future__ import annotations
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 次元 → 日本語ラベル (人間可読化)
JP = {
    "lbl_removal": "除去", "lbl_removal_ko": "除去KO", "lbl_removal_bounce": "除去バウンス",
    "lbl_removal_tolife": "ライフ送り", "lbl_board_wipe": "全体除去", "lbl_search": "サーチ",
    "lbl_draw": "ドロー", "lbl_negate": "無効化", "lbl_keyword_grant": "KW付与", "lbl_rush_grant": "ラッシュ付与",
    "lbl_tempo_rest": "レスト", "lbl_untap": "アクティブ化", "lbl_buff_power": "パワー+", "lbl_power_set": "パワー固定",
    "lbl_life_recovery": "ライフ回復", "lbl_life_manip": "ライフ操作", "lbl_self_discard": "手札コスト",
    "lbl_ramp_don": "ドン加速", "lbl_play_accel": "展開", "lbl_recursion": "回収", "lbl_cost_reduce": "コスト減",
    "lbl_attach_don": "ドン付与", "lbl_protect": "保護", "lbl_redirect": "対象変更", "lbl_disruption": "妨害",
    "lbl_hand_disrupt": "手札破壊", "lbl_don_disrupt": "ドン妨害", "lbl_finisher_swing": "フィニッシャー",
    "lbl_t_on_play": "登場時", "lbl_t_on_attack": "アタック時", "lbl_t_on_ko": "KO時", "lbl_t_on_block": "ブロック時",
    "lbl_t_activate_main": "起動メイン", "lbl_t_counter": "カウンター", "lbl_t_trigger": "トリガー",
    "lbl_t_end_of_turn": "ターン終了時", "lbl_t_in_hand": "手札中", "lbl_t_opp_attack": "相手アタック時",
    "lbl_t_static_don": "ドン常在", "lbl_t_protect": "置換保護",
    "mag_rm_active_cost": "除去cost上限(盤面)", "mag_rm_play_cost": "除去cost上限(登場)",
    "mag_rm_active_pw": "除去pw上限(盤面k)", "mag_rm_play_pw": "除去pw上限(登場k)", "mag_rm_targets": "除去対象数",
    "mag_draw": "ドロー枚数", "mag_search": "サーチ枚数", "mag_don": "ドン量", "mag_pump": "パワー+量k", "mag_recover": "回復量",
    "cav_ko_immune": "KO耐性", "cav_negates": "効果無効", "cav_protects": "離脱置換", "cav_recovers_at_zero": "0回復",
    "in_power": "パワーk", "in_cost": "コスト", "in_counter": "カウンターk", "in_is_blocker": "ブロッカー",
}
# フィルタ chip (label → 対応する sig dim)
FILTERS = [
    ("除去", "lbl_removal"), ("サーチ", "lbl_search"), ("ドロー", "lbl_draw"), ("無効化", "lbl_negate"),
    ("ブロッカー", "in_is_blocker"), ("起動メイン", "lbl_t_activate_main"), ("登場時", "lbl_t_on_play"),
    ("KO時", "lbl_t_on_ko"), ("回復", "lbl_life_recovery"), ("KW付与", "lbl_keyword_grant"),
    ("レスト", "lbl_tempo_rest"), ("ドン加速", "lbl_ramp_don"), ("KO耐性", "cav_ko_immune"), ("離脱置換", "cav_protects"),
]

_DATA = None


def _data() -> list:
    global _DATA
    if _DATA is not None:
        return _DATA
    sig = json.loads((ROOT / "db" / "card_sig.json").read_text(encoding="utf-8"))
    cards = {c["card_id"]: c for c in json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    out = []
    for cid, s in sig.items():
        c = cards.get(cid, {})
        nz = {k: round(v, 2) for k, v in s.items() if v != 0.0}
        out.append({
            "id": cid, "name": c.get("name", cid), "cat": c.get("category", ""),
            "cost": c.get("cost", ""), "power": c.get("power", ""), "color": c.get("color", ""),
            "text": (c.get("text") or "").replace("\n", " "),
            "sig": nz,
        })
    out.sort(key=lambda r: r["id"])
    _DATA = out
    return out


HTML = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>sig(card) ビューア</title><style>
:root{color-scheme:dark}
body{margin:0;background:#0d1117;color:#c9d1d9;font:13px/1.5 -apple-system,"Segoe UI",sans-serif}
header{padding:12px 18px;background:#161b22;border-bottom:1px solid #30363d;position:sticky;top:0;z-index:5}
h1{font-size:15px;margin:0 0 8px}
#q{width:280px;padding:6px 10px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{padding:3px 10px;background:#21262d;border:1px solid #30363d;border-radius:12px;cursor:pointer;font-size:12px;user-select:none}
.chip.on{background:#1f6feb;border-color:#1f6feb;color:#fff}
.count{color:#8b949e;font-size:12px;margin-left:10px}
.wrap{display:flex;gap:0}
.list{flex:1;overflow:auto;height:calc(100vh - 110px)}
table{width:100%;border-collapse:collapse}
th,td{padding:5px 8px;border-bottom:1px solid #21262d;text-align:left;vertical-align:top}
th{position:sticky;top:0;background:#161b22;color:#8b949e;font-weight:600;font-size:11px}
tr.row{cursor:pointer}
tr.row:hover{background:#161b22}
tr.sel{background:#1c2333}
.tag{display:inline-block;padding:1px 6px;margin:1px;background:#21262d;border-radius:4px;font-size:11px;color:#a5d6ff}
.tag.mag{color:#d2a8ff}.tag.cav{color:#ffa657}.tag.in{color:#8b949e}
.detail{width:420px;border-left:1px solid #30363d;padding:14px 16px;height:calc(100vh - 110px);overflow:auto;background:#0d1117}
.detail h2{font-size:14px;margin:0 0 2px}
.detail .id{color:#8b949e;font-size:12px}
.detail .txt{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:10px;margin:10px 0;line-height:1.6;font-size:12px;white-space:pre-wrap}
.detail .siglist{display:flex;flex-wrap:wrap;gap:4px}
.lbl{color:#8b949e;font-size:11px;margin:8px 0 3px}
.cid{color:#6e7681;font-size:11px}
</style></head><body>
<header>
  <h1>sig(card) ビューア <span class="count" id="cnt"></span></h1>
  <input id="q" placeholder="名前 / ID で検索 (例: ミホーク, OP14)">
  <div class="chips" id="chips"></div>
</header>
<div class="wrap">
  <div class="list"><table><thead><tr><th>ID</th><th>名前</th><th>種</th><th>C/P</th><th>効果シグネチャ (人間可読)</th></tr></thead><tbody id="tb"></tbody></table></div>
  <div class="detail" id="detail"><p class="lbl">カードを選ぶと sig と実テキストを並べて検証できます</p></div>
</div>
<script>
let DATA=[], JP={}, FILTERS=[], active=new Set(), q='', sel=null;
function tagClass(k){return k.startsWith('mag_')?'mag':k.startsWith('cav_')?'cav':k.startsWith('in_')?'in':'';}
function sigTags(sig){return Object.entries(sig).map(([k,v])=>{
  const lab=JP[k]||k; const show=(v===1.0&&(k.startsWith('lbl_')||k==='in_is_blocker'))?lab:`${lab}:${v}`;
  return `<span class="tag ${tagClass(k)}">${show}</span>`;}).join('');}
function match(r){
  if(q){const s=(r.name+' '+r.id).toLowerCase(); if(!s.includes(q.toLowerCase()))return false;}
  for(const dim of active){ if(!(dim in r.sig))return false; }
  return true;}
function render(){
  const rows=DATA.filter(match);
  document.getElementById('cnt').textContent=`${rows.length} / ${DATA.length} 枚`;
  const cap=rows.slice(0,600);
  document.getElementById('tb').innerHTML=cap.map(r=>`<tr class="row ${sel===r.id?'sel':''}" data-id="${r.id}">
    <td class="cid">${r.id}</td><td>${r.name}</td><td class="cid">${r.cat.slice(0,4)}</td>
    <td class="cid">${r.cost||'-'}/${(r.power||'-')}</td><td>${sigTags(r.sig)}</td></tr>`).join('')
    + (rows.length>600?`<tr><td colspan=5 class="cid">…他 ${rows.length-600} 枚 (絞り込んでください)</td></tr>`:'');
  document.querySelectorAll('tr.row').forEach(tr=>tr.onclick=()=>showDetail(tr.dataset.id));
}
function showDetail(id){
  sel=id; const r=DATA.find(x=>x.id===id); if(!r)return;
  document.getElementById('detail').innerHTML=`
    <h2>${r.name}</h2><div class="id">${r.id} ・ ${r.cat} ・ ${r.color} ・ コスト${r.cost} / パワー${r.power}</div>
    <div class="lbl">実カードテキスト (照合用)</div>
    <div class="txt">${r.text||'(効果テキストなし=バニラ)'}</div>
    <div class="lbl">効果シグネチャ sig(card) ${Object.keys(r.sig).length} 次元</div>
    <div class="siglist">${Object.keys(r.sig).length?sigTags(r.sig):'<span class="cid">(全ゼロ=効果なし)</span>'}</div>
    <div class="lbl" style="margin-top:14px">検証: 上のテキストの効果が、下の sig に正しく現れているか目視で確認</div>`;
  render();
}
async function boot(){
  const d=await (await fetch('/api/sig')).json();
  DATA=d.cards; JP=d.jp; FILTERS=d.filters;
  document.getElementById('chips').innerHTML=FILTERS.map(([lab,dim])=>`<span class="chip" data-dim="${dim}">${lab}</span>`).join('');
  document.querySelectorAll('.chip').forEach(ch=>ch.onclick=()=>{
    const dim=ch.dataset.dim; if(active.has(dim)){active.delete(dim);ch.classList.remove('on');}else{active.add(dim);ch.classList.add('on');} render();});
  document.getElementById('q').oninput=e=>{q=e.target.value;render();};
  render();
}
boot();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/sig"):
            body = json.dumps({"cards": _data(), "jp": JP, "filters": FILTERS}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
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
    ap.add_argument("--port", type=int, default=8771)
    a = ap.parse_args()
    n = len(_data())
    print(f"sig(card) ビューア: http://127.0.0.1:{a.port}  ({n} 枚)")
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
