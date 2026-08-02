"""overlay (db/card_effects.json) のキーと engine 実装を突き合わせ、 未実装 = silent 不発 を洗い出す。

bail に現れない穴 (静的効果・trigger 未発火・未知 target spec) を機械的に検出する。
Python 側は `engine/effects.py` の実装キー、 Rust 側は `rust_engine/src/*.rs` の grep で判定。

    .venv/bin/python scripts/scan_overlay_engine_gaps.py
"""

import json, re, pathlib, sys
sys.path.insert(0, '.')

SRC = pathlib.Path('engine/effects.py').read_text().split('\n')

def func_body(name):
    i = next(i for i, l in enumerate(SRC) if l.startswith(f'def {name}('))
    j = next(j for j in range(i + 1, len(SRC)) if SRC[j].startswith('def '))
    return '\n'.join(SRC[i:j])

# --- 1) primitive ---
ex = func_body('_execute_effect_body') + func_body('evaluate_static_effects')

prim_handled = set(re.findall(r'(?:el)?if k == "([a-zA-Z0-9_]+)"', ex))
prim_handled |= set(re.findall(r'"([a-zA-Z0-9_]+)" in primitive', ex))
prim_handled |= set(re.findall(r'k in \(([^)]*)\)', ex) and re.findall(r'"([a-zA-Z0-9_]+)"', ' '.join(re.findall(r'k in \(([^)]*)\)', ex))) or [])

# --- 2) condition ---
ec = func_body('eval_condition') + func_body('_replace_ko_match') + func_body('evaluate_static_effects')
cond_handled = set(re.findall(r'(?:el)?if k == "([a-zA-Z0-9_]+)"', ec))
cond_handled |= set(re.findall(r'k == "([a-zA-Z0-9_]+)"', ec))
cond_handled |= set(re.findall(r'cond\.get\("([a-zA-Z0-9_]+)"', ec))
cond_handled |= set(re.findall(r'^\s+([a-z_]+): bool,', func_body('_replace_ko_match'), re.M))
cond_handled |= {'target','target_feature','target_power_le','target_power_ge','target_cost_le',
                 'target_cost_ge','target_name','target_name_exclude','target_color','target_rested',
                 'by_opp_effect','by_battle','by_opp_chara_effect','leave_kind','optional','n'}
cond_handled |= set(re.findall(r'k in \(([^)]*)\)', ec) and re.findall(r'"([a-zA-Z0-9_]+)"', ' '.join(re.findall(r'k in \(([^)]*)\)', ec))) or [])

# --- 3) target spec (literal + regex) ---
rt = func_body('_resolve_target')
tgt_literals = set(re.findall(r'target_spec == "([a-zA-Z0-9_]+)"', rt))
tgt_literals |= set(re.findall(r't == "([a-zA-Z0-9_]+)"', rt))
for grp in re.findall(r'target_spec in \(([^)]*)\)', rt):
    tgt_literals |= set(re.findall(r'"([a-zA-Z0-9_]+)"', grp))
tgt_regexes = [re.compile(p) for p in re.findall(r're\.match\(r"([^"]+)"', rt)]
# _TYPE_ALIASES
alias = set(re.findall(r'"([a-zA-Z0-9_]+)": "[a-zA-Z0-9_]+"', func_body('_resolve_target')))

def tgt_known(spec: str) -> bool:
    if spec in tgt_literals or spec in alias:
        return True
    return any(r.match(spec) for r in tgt_regexes)

ov = json.load(open('db/card_effects.json'))
prim_used, cond_used, tgt_used = {}, {}, {}

TGT_KEYS = {"target", "from_target", "to_target", "pump_target"}

def walk(node, cid):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in TGT_KEYS and isinstance(v, str):
                tgt_used.setdefault(v, set()).add(cid)
            walk(v, cid)
    elif isinstance(node, list):
        for x in node:
            walk(x, cid)

for cid, effs in ov.items():
    if not isinstance(effs, list):
        continue
    for eff in effs:
        if not isinstance(eff, dict):
            continue
        for prim in eff.get('do', []) or []:
            if isinstance(prim, dict):
                for k, v in prim.items():
                    if k.startswith('_'):
                        continue
                    prim_used.setdefault(k, set()).add(cid)
                    if isinstance(v, str):
                        tgt_used.setdefault(v, set()).add(cid)
                walk(prim, cid)
        for ck in ('if', 'conditions', 'unless'):
            c = eff.get(ck)
            if isinstance(c, dict):
                for k in c:
                    if not k.startswith('_'):
                        cond_used.setdefault(k, set()).add(cid)

def report(title, used, known_fn):
    miss = {k: v for k, v in used.items() if not known_fn(k)}
    print(f"\n=== {title}: 未処理 {len(miss)} 種 ===")
    for k, cids in sorted(miss.items(), key=lambda kv: -len(kv[1]))[:40]:
        print(f"  {len(cids):4d} card  {k}   e.g. {sorted(cids)[:3]}")

# 既知の false positive (= 別経路で処理済) は除外して報告する。
_PY_OK_ELSEWHERE_PRIM = {
    "auto_attach_to_leader",   # game.py DON フェイズ
    "play_multi_from_trash",   # play_from_trash と or 条件で同じ arm
    "in_hand_cost_plus",       # game.py コスト計算 + effects.py in_hand_cost_minus と同 arm
    "set_don_deck_size",       # setup_modifier (game.py setup)
}
_PY_OK_ELSEWHERE_COND = {   # replace_ko/replace_leave の match 条件 (_replace_ko_match)
    "target_attribute", "target_feature_contains", "target_truly_original_power_eq",
}
_TGT_OK = {"one_opp_chara_or_don"}  # rest / rest_multi の専用分岐

report("primitive", prim_used, lambda k: k in prim_handled or k in _PY_OK_ELSEWHERE_PRIM)
report("condition", cond_used, lambda k: k in cond_handled or k in _PY_OK_ELSEWHERE_COND)
# target は do の値が文字列でも target spec でないもの (色名等) が混ざるので、
# 「target キー由来」だけに絞った版も出す
report("target spec (全 string 値、 カード名等の値は false positive)", tgt_used,
       lambda k: tgt_known(k) or k in _TGT_OK)


# --- Rust 側 (未実装 = bail か silent 不発) ---
RS = ""
for f in ("effects.rs", "rules.rs", "setup.rs", "selfplay.rs"):
    fp = pathlib.Path("rust_engine/src") / f
    if fp.exists():
        RS += fp.read_text()
if RS:
    when_used = {}
    for cid, effs in ov.items():
        if not isinstance(effs, list):
            continue
        for e in effs:
            if isinstance(e, dict) and e.get("when"):
                when_used.setdefault(e["when"], set()).add(cid)
    for title, used in (("primitive", prim_used), ("condition", cond_used), ("when", when_used)):
        _RS_OK = {"setup_modifier"}  # deck の don_deck_size 経由で反映 (rust_parity_check.deck_value)
        miss = {k: v for k, v in used.items() if f'"{k}"' not in RS and k not in _RS_OK}
        print(f"\n=== Rust 未実装 {title}: {len(miss)} 種 ===")
        for k, cids in sorted(miss.items(), key=lambda kv: -len(kv[1]))[:30]:
            print(f"  {len(cids):4d} card  {k}   e.g. {sorted(cids)[:3]}")
