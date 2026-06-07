"""デッキ内の静的コンボグラフを card_effects.json の DSL から構築する。

各カードが「生む資源/条件 (produces)」 と「要る資源/条件 (consumes)」 を DSL primitive +
features/text から抽出し、 A.produces ∩ B.consumes でエッジを張る。 固定プランは作らない
(= 探索のプライア / value 特徴 / 可視化の素材)。

「コンボを把握する AI」 の足場: このグラフで「デッキにどんな連携があるか」 を可視化し、
後段で「AI がそれを実行できているか」 を実ログ照合する。

usage: .venv/bin/python scripts/build_combo_graph.py [deck_slug]
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

# デッキ主要 feature (= board producer 用)
_fc: dict[str, int] = defaultdict(int)
for c in dl.main:
    for f in c.features:
        _fc[f] += 1
MAIN_FEATURE = max(_fc, key=_fc.get) if _fc else None
DECK_FEATURES = set(_fc)


def _do_keys_of(card) -> list[str]:
    out: list[str] = []
    for eff in ov.get(card.card_id) or []:
        if isinstance(eff, dict):
            for d in eff.get("do") or []:
                if isinstance(d, dict):
                    out += list(d.keys())
    return out


# summon 対象 feature (= 《F》 を登場/プレイ系効果で参照するカードから抽出)。
# searcher は これらを 手札に供給する = 「コンボのパーツ供給」。
_SUMMON_DO = {"play_from_hand", "summon_from_deck", "play_from_hand_named",
              "play_from_hand_or_trash"}
SUMMON_FEATURES: set[str] = set()
for c in [dl.leader] + dl.main:
    keys = set(_do_keys_of(c))
    if keys & _SUMMON_DO:
        for f in re.findall(r"《([^》]+)》", c.text or ""):
            if f in DECK_FEATURES:
                SUMMON_FEATURES.add(f)


def _do_keys(eff: dict) -> list[str]:
    out: list[str] = []
    for d in eff.get("do") or []:
        if isinstance(d, dict):
            out += list(d.keys())
    return out


def _is_character(card) -> bool:
    return "character" in str(card.category).lower()


# primitive → 生む資源タグ
PROD_HAND = {"search_top_n", "search", "reveal_top_play", "reveal_top_then",
             "draw", "draw_per_self_hand_discarded", "reveal_top_then_hand"}
PROD_ATTACH = {"attach_rested_don", "attach_don", "attach_active_don"}
PROD_RAMP = {"add_don", "add_rested_don"}
PROD_LIFE = {"put_top_to_life", "hand_to_self_life"}
PROD_KEYWORD = {"give_keyword", "give_rush", "give_attack_active_chara"}
PROD_TRASH = {"trash_self_hand_random"}
PROD_BOARD = {"play_from_hand", "play_from_trash", "summon_from_deck", "play_self",
              "play_from_hand_named", "play_from_hand_or_trash"}
PROD_COSTRED = {"set_base_cost", "set_base_cost_timed"}


def extract(card):
    prod: set[str] = set()
    cons: set[str] = set()
    effs = ov.get(card.card_id) or []
    summon_feats = re.findall(r"《([^》]+)》", card.text or "")
    for eff in effs:
        if not isinstance(eff, dict):
            continue
        iff = eff.get("if") or eff.get("cond") or {}
        cost = eff.get("cost") or {}
        keys = _do_keys(eff)
        for k in keys:
            if k in PROD_HAND:
                prod.add("hand_fuel")
                # searcher/ドローは summon 対象 feature を手札に供給 (= summon エンジンのパーツ)
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
        # cost
        if cost.get("discard_hand") or cost.get("optional_discard_hand"):
            cons.add("hand_fuel")
            prod.add("trash+")
        if cost.get("rest_self_don") or cost.get("pay_don"):
            cons.add("don")
        # if 条件 = consumes
        if "self_attached_don_ge" in iff:
            cons.add("attach_don")
        if "self_don_ge" in iff:
            cons.add("don")
        if "self_life_le" in iff:
            cons.add("low_life(外的)")
        if "opp_life_ge" in iff or "opp_life_le" in iff:
            cons.add("opp_life(外的)")
        if "trash_count_ge" in iff or "self_trash_count_ge" in iff or "play_from_trash" in keys:
            cons.add("trash+")
        scc = iff.get("self_chara_filtered_count_ge")
        if isinstance(scc, dict):
            filt = scc.get("filter", {})
            tgt = filt.get("name") or filt.get("feature") or filt.get("feature_in")
            if isinstance(tgt, list):
                tgt = tgt[0] if tgt else None
            if tgt:
                cons.add(f"board:{tgt}")
        # leader/summon: play_from_hand consuming a 《feature》 in hand
        if "play_from_hand" in keys and summon_feats:
            for sf in summon_feats:
                cons.add(f"hand:{sf}")
    # board presence: 場に出ると features/name を供給
    if _is_character(card):
        for f in card.features:
            prod.add(f"board:{f}")
        prod.add(f"board:{card.name}")
    return prod, cons


# unique card 一覧 (leader + main)
uniq: dict[str, object] = {}
for c in [dl.leader] + dl.main:
    uniq.setdefault(c.card_id, c)

info = {}
for cid, c in uniq.items():
    p, cn = extract(c)
    info[cid] = {"card": c, "prod": p, "cons": cn}

# エッジ: A.prod ∩ B.cons (A != B)。 「外的」 タグはデッキ内 producer が無いので別枠。
EXTERNAL = {"low_life(外的)", "opp_life(外的)"}
edges = []
for bid, b in info.items():
    for tag in b["cons"]:
        if tag in EXTERNAL:
            continue
        producers = [aid for aid, a in info.items()
                     if aid != bid and tag in a["prod"]]
        if producers:
            edges.append((tag, producers, bid))

# レポート
nm = lambda cid: f"{uniq[cid].name}({cid})"
print(f"=== コンボグラフ: {dl.name} ({SLUG}) | 主要feature={MAIN_FEATURE} ===")
print(f"unique cards={len(uniq)} | edges(tag単位)={len(edges)}\n")

# tag 別にまとめて表示 (consumer 視点 = 「この札を活かすには」)
by_consumer = defaultdict(list)
for tag, producers, bid in edges:
    by_consumer[bid].append((tag, producers))

# 重要 consumer を cons 数 + edge 数 で並べる
order = sorted(by_consumer, key=lambda b: -sum(len(p) for _, p in by_consumer[b]))
for bid in order:
    c = uniq[bid]
    print(f"▼ {nm(bid)} c{c.cost} P{c.power} を活かす連携:")
    for tag, producers in by_consumer[bid]:
        plist = "、".join(nm(p) for p in producers[:6])
        more = f" 他{len(producers)-6}枚" if len(producers) > 6 else ""
        print(f"    [{tag}] ← {plist}{more}")
    print()

# 外的条件 (= 相手/盤面状況依存、 デッキ内では作れない)
ext = [(cid, t) for cid, d in info.items() for t in d["cons"] if t in EXTERNAL]
if ext:
    print("=== 外的条件依存 (= デッキ内コンボでなく状況待ち) ===")
    for cid, t in ext:
        print(f"    {nm(cid)}: {t}")
    print()

# JSON 保存
out = {
    "slug": SLUG, "deck_name": dl.name, "main_feature": MAIN_FEATURE,
    "edges": [{"tag": t, "from": producers, "to": bid} for t, producers, bid in edges],
    "cards": {cid: {"name": uniq[cid].name, "cost": uniq[cid].cost,
                    "produces": sorted(d["prod"]), "consumes": sorted(d["cons"])}
              for cid, d in info.items()},
}
outp = ROOT / "db" / f"combo_graph_{SLUG}.json"
outp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"saved: {outp.relative_to(ROOT)}")
