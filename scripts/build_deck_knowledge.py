"""デッキプレイ知識を card_effects.json の DSL から生成する (= 仕様 docs/DECK_PLAY_KNOWLEDGE.md)。

出力 db/deck_play_knowledge_<slug>.json:
  - combos: デッキ内コンボ (= A.produces ∩ B.consumes のエッジ、 Stage A)
  - cards: 各カードの有効な使い方 (= roles / usage[] / timing_hint、 Stage B)

固定プランは作らない (= 探索プライア/value特徴/可視化の素材)。 全カード・全デッキ汎用。
usage: .venv/bin/python scripts/build_deck_knowledge.py [deck_slug]
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList  # noqa: E402

SLUG = sys.argv[1] if len(sys.argv) > 1 else "tcgportal_calgara"
repo = CardRepository.from_json(ROOT / "db" / "cards.json")
dl = DeckList.from_json(ROOT / "decks" / f"{SLUG}.json", repo)
ov = json.load(open(ROOT / "db" / "card_effects.json", encoding="utf-8"))

_fc: dict[str, int] = defaultdict(int)
for c in dl.main:
    for f in c.features:
        _fc[f] += 1
MAIN_FEATURE = max(_fc, key=_fc.get) if _fc else None
DECK_FEATURES = set(_fc)


def _effs(card):
    return [e for e in (ov.get(card.card_id) or []) if isinstance(e, dict)]


def _do_keys(eff: dict) -> list[str]:
    out: list[str] = []
    for d in eff.get("do") or []:
        if isinstance(d, dict):
            out += list(d.keys())
    return out


def _all_do_keys(card) -> set[str]:
    out: set[str] = set()
    for e in _effs(card):
        out |= set(_do_keys(e))
    return out


def _flatten_if(iff) -> list:
    out: list = []
    if isinstance(iff, dict):
        for k, v in iff.items():
            if k in ("or", "and", "not", "any", "all"):
                for s in (v if isinstance(v, list) else [v]):
                    out += _flatten_if(s)
            else:
                out.append((k, v))
    elif isinstance(iff, list):
        for s in iff:
            out += _flatten_if(s)
    return out


def _cost_keys(cost) -> set:
    out: set = set()
    for ci in ([cost] if isinstance(cost, dict) else (cost if isinstance(cost, list) else [])):
        if isinstance(ci, dict):
            out |= set(ci.keys())
    return out


# summon 対象 feature (= 《F》 を登場/プレイ系効果で参照)
_SUMMON_DO = {"play_from_hand", "summon_from_deck", "play_from_hand_named", "play_from_hand_or_trash"}
SUMMON_FEATURES: set[str] = set()
for c in [dl.leader] + dl.main:
    if _all_do_keys(c) & _SUMMON_DO:
        for f in re.findall(r"《([^》]+)》", c.text or ""):
            if f in DECK_FEATURES:
                SUMMON_FEATURES.add(f)

PROD_HAND = {"search_top_n", "search", "reveal_top_play", "reveal_top_then", "draw",
             "draw_per_self_hand_discarded"}
PROD_ATTACH = {"attach_rested_don", "attach_don", "attach_active_don"}
PROD_RAMP = {"add_don", "add_rested_don"}
PROD_LIFE = {"put_top_to_life", "hand_to_self_life"}
PROD_KEYWORD = {"give_keyword", "give_rush", "give_attack_active_chara"}
PROD_TRASH = {"trash_self_hand_random"}
PROD_BOARD = {"play_from_hand", "play_from_trash", "summon_from_deck", "play_self",
              "play_from_hand_named", "play_from_hand_or_trash"}
PROD_COSTRED = {"set_base_cost", "set_base_cost_timed"}
REMOVAL = {"ko", "ko_multi", "ko_all_others", "return_to_hand", "return_to_hand_multi",
           "return_to_deck_bottom", "return_to_deck_bottom_multi", "chara_to_self_life",
           "chara_to_opp_life"}


def extract(card):
    prod, cons = set(), set()
    summon_feats = re.findall(r"《([^》]+)》", card.text or "")
    for eff in _effs(card):
        if_pairs = _flatten_if(eff.get("if") or eff.get("cond"))
        if_keys = {k for k, _ in if_pairs}
        cost_keys = _cost_keys(eff.get("cost"))
        keys = _do_keys(eff)
        for k in keys:
            if k in PROD_HAND:
                prod.add("hand_fuel")
                for sf in SUMMON_FEATURES:
                    prod.add(f"hand:{sf}")
            if k in PROD_ATTACH:
                prod.add("attach_don")
            if k in PROD_RAMP:
                prod.add("don")
            if k in PROD_LIFE:
                prod.add("life+")
            if k in PROD_KEYWORD:
                prod.add("keyword")
            if k in PROD_TRASH:
                prod.add("trash+")
            if k in PROD_COSTRED or k.startswith("reduce_play_cost"):
                prod.add("cost_reduction")
            if k in PROD_BOARD and MAIN_FEATURE:
                prod.add(f"board:{MAIN_FEATURE}")
        if cost_keys & {"discard_hand", "optional_discard_hand"}:
            cons.add("hand_fuel")
            prod.add("trash+")
        if cost_keys & {"rest_self_don", "pay_don"}:
            cons.add("don")
        if "self_attached_don_ge" in if_keys:
            cons.add("attach_don")
        if "self_don_ge" in if_keys:
            cons.add("don")
        if "self_life_le" in if_keys:
            cons.add("low_life(外的)")
        if {"opp_life_ge", "opp_life_le"} & if_keys:
            cons.add("opp_life(外的)")
        if {"trash_count_ge", "self_trash_count_ge"} & if_keys or "play_from_trash" in keys:
            cons.add("trash+")
        for _k, _v in if_pairs:
            if _k == "self_chara_filtered_count_ge" and isinstance(_v, dict):
                filt = _v.get("filter", {})
                tgt = filt.get("name") or filt.get("feature") or filt.get("feature_in")
                if isinstance(tgt, list):
                    tgt = tgt[0] if tgt else None
                if tgt:
                    cons.add(f"board:{tgt}")
        if "play_from_hand" in keys and summon_feats:
            for sf in summon_feats:
                cons.add(f"hand:{sf}")
    if "character" in str(card.category).lower():
        for f in card.features:
            prod.add(f"board:{f}")
        prod.add(f"board:{card.name}")
    return prod, cons


_OPS = [("_le", "<="), ("_ge", ">="), ("_lt", "<"), ("_gt", ">"), ("_eq", "==")]


def _cond_str(if_pairs) -> str:
    if not if_pairs:
        return "常時"
    parts = []
    for k, v in if_pairs:
        if k == "self_chara_filtered_count_ge" and isinstance(v, dict):
            filt = v.get("filter", {})
            tgt = filt.get("name") or filt.get("feature") or filt.get("feature_in") or "?"
            if isinstance(tgt, list):
                tgt = tgt[0] if tgt else "?"
            parts.append(f"場に{tgt}>={v.get('count', 1)}")
            continue
        sym = None
        base = k
        for suf, s in _OPS:
            if k.endswith(suf):
                sym, base = s, k[: -len(suf)]
                break
        if sym is not None and not isinstance(v, (dict, list)):
            parts.append(f"{base}{sym}{v}")
        elif not isinstance(v, (dict, list)):
            parts.append(f"{k}={v}")
        else:
            parts.append(k)
    return " かつ ".join(parts)


def _reachable(if_keys) -> str:
    if "self_life_le" in if_keys:
        return "ライフは減るので時間経過で満たされやすい(温存価値高)"
    if {"trash_count_ge", "self_trash_count_ge"} & if_keys:
        return "トラッシュは増えるので満たされやすい"
    if {"self_don_ge", "self_attached_don_ge"} & if_keys:
        return "DONは増えるので満たされやすい"
    if "opp_life_ge" in if_keys:
        return "序盤に満たされやすい(相手ライフ依存)"
    if "self_chara_filtered_count_ge" in if_keys:
        return "場に対象を用意すれば自力で満たせる"
    if "leader_feature" in if_keys:
        return "リーダー固定(常時成立)"
    return "状況依存"


def _value_class(keys: set) -> str:
    if keys & PROD_LIFE:
        return "recovery"
    if keys & REMOVAL:
        return "removal"
    if any(k.startswith("draw") for k in keys):
        return "draw"
    if any(k.startswith("power_pump") or k.startswith("set_base_power") for k in keys):
        return "pump"
    if keys & {"search_top_n", "search", "reveal_top_play", "reveal_top_then"}:
        return "search"
    if keys & PROD_RAMP:
        return "ramp"
    if keys & PROD_ATTACH:
        return "attach_don"
    if keys & {"play_from_hand", "summon_from_deck", "play_from_trash", "play_self"}:
        return "summon"
    if keys & {"give_keyword", "give_rush"}:
        return "keyword"
    if any(k.startswith("reduce_play_cost") for k in keys) or keys & PROD_COSTRED:
        return "cost_reduction"
    return next(iter(keys), "—") if keys else "—"


def roles_of(card) -> list[str]:
    r = []
    keys = _all_do_keys(card)
    whens = {e.get("when") for e in _effs(card)}
    if "leader" in str(card.category).lower():
        r.append("leader")
    if card.is_blocker:
        r.append("blocker")
    if (card.counter or 0) > 0 or "counter" in whens:
        r.append("counter")
    if (card.power or 0) >= 7000 or card.is_double_attack:
        r.append("finisher")
    if keys & {"search_top_n", "search", "reveal_top_play", "reveal_top_then"}:
        r.append("searcher")
    if keys & PROD_RAMP:
        r.append("ramp")
    if keys & PROD_LIFE:
        r.append("recovery")
    if keys & REMOVAL:
        r.append("removal")
    if any(k.startswith("power_pump") for k in keys):
        r.append("pump")
    return r


def usage_profile(card):
    usage = []
    for eff in _effs(card):
        if_pairs = _flatten_if(eff.get("if") or eff.get("cond"))
        if_keys = {k for k, _ in if_pairs}
        keys = set(_do_keys(eff))
        if not keys:
            continue
        usage.append({
            "when": eff.get("when"),
            "cond": _cond_str(if_pairs),
            "do": sorted(keys),
            "value_class": _value_class(keys),
            "reachable": _reachable(if_keys) if if_pairs else "常時成立",
            "conditional": bool(if_pairs),
        })
    return usage


def timing_hint(card, usage, roles) -> str:
    strong = [u for u in usage if u["conditional"]
              and u["value_class"] in {"recovery", "removal", "draw", "summon", "pump", "search"}]
    if strong:
        u = strong[0]
        return (f"{u['when']}効果は「{u['cond']}」でのみ発火({u['value_class']})。"
                f"条件外なら body のみ → {u['reachable']}")
    if "counter" in roles and any(u["when"] == "counter" for u in usage):
        return "カウンターは相手の攻撃時まで温存(防御で使う)"
    uncond = [u for u in usage if not u["conditional"] and u["value_class"] not in ("—", "other")]
    if uncond:
        return f"いつでも{uncond[0]['value_class']}を発動できる(即時運用)"
    if "blocker" in roles:
        return "ブロッカー: 守りが要る時 (低ライフ/相手の打点が高い時) の価値が高い"
    if "finisher" in roles:
        return "フィニッシャー: 打点を通せる盤面/リーサル圏で価値が高い"
    return "効果なし/バニラ: コストカーブ通りに運用"


# === 構築 ===
uniq = {}
for c in [dl.leader] + dl.main:
    uniq.setdefault(c.card_id, c)

info = {}
for cid, c in uniq.items():
    p, cn = extract(c)
    info[cid] = {"card": c, "prod": p, "cons": cn}

EXTERNAL = {"low_life(外的)", "opp_life(外的)"}
edges = []
for bid, b in info.items():
    for tag in b["cons"]:
        if tag in EXTERNAL:
            continue
        producers = [aid for aid, a in info.items() if aid != bid and tag in a["prod"]]
        if producers:
            edges.append({"tag": tag, "to": bid, "from": producers})

enables = defaultdict(set)
enabled_by = defaultdict(set)
for e in edges:
    enabled_by[e["to"]].update(e["from"])
    for a in e["from"]:
        enables[a].add(e["to"])

cards_out = {}
for cid, d in info.items():
    c = d["card"]
    roles = roles_of(c)
    if enables.get(cid):
        roles.append("enabler")
    if enabled_by.get(cid):
        roles.append("payoff")
    usage = usage_profile(c)
    cards_out[cid] = {
        "name": c.name, "cost": c.cost, "power": c.power, "counter": c.counter,
        "roles": roles,
        "produces": sorted(d["prod"]),
        "consumes": sorted(d["cons"]),
        "usage": usage,
        "combo": {"enables": sorted(enables.get(cid, [])),
                  "enabled_by": sorted(enabled_by.get(cid, []))},
        "timing_hint": timing_hint(c, usage, roles),
    }

out = {
    "slug": SLUG, "deck_name": dl.name, "main_feature": MAIN_FEATURE,
    "summon_features": sorted(SUMMON_FEATURES),
    "combos": edges, "cards": cards_out,
}
outp = ROOT / "db" / f"deck_play_knowledge_{SLUG}.json"
outp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

# === レポート ===
def nm(cid):
    return f"{uniq[cid].name}({cid})"


print(f"=== デッキプレイ知識: {dl.name} ({SLUG}) | 主要feature={MAIN_FEATURE} | summon={sorted(SUMMON_FEATURES)} ===")
print(f"unique={len(uniq)} combos={len(edges)}\n")
print("--- デッキ内コンボ ---")
for e in sorted(edges, key=lambda x: -len(x["from"])):
    more = f" 他{len(e['from']) - 5}" if len(e["from"]) > 5 else ""
    print(f"  [{e['tag']}] → {nm(e['to'])}  ← {'、'.join(nm(a) for a in e['from'][:5])}{more}")
print("\n--- 各カードの有効な使い方 (timing_hint) ---")
for cid, co in cards_out.items():
    print(f"  {nm(cid)} [{'/'.join(co['roles']) or 'vanilla'}]")
    print(f"      {co['timing_hint']}")
print(f"\nsaved: {outp.relative_to(ROOT)}")
