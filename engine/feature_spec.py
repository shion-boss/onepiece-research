"""宣言的 feature spec = 「指標が自動で増える」ための土台 — 2026-07-23。

これまで特徴列は gbm_value.py にベタ書きだった (v16/v18/v19/v20)。 = 列を増やすには人間が
コードを書く必要があり、 そこが律速だった。 ここでは列を **データ (JSON)** にする:

  db/eiv1/feature_spec.json  = 現在採用中の追加列 (v20(94) の後ろに append される)
  <model>.spec.json          = その model が学習された時の spec (= 推論で使う、 model と対で保存)

⭐ 評価器は 1 本だけ (evaluate)。 学習は corpus の snapshot、 推論は live state を
gbm_value._mini_snap で同じ形にして渡す → **学習と推論のズレが構造的に起きない**。

列の種類:
  agg  : {zone × label カテゴリ × 統計}  … 例 「相手の残りデッキの除去の期待枚数」
  x    : agg × 文脈スカラー (turn / ライフ差 …) … この repo の実績上、 効くのは盤面と
         相互作用する形 (静的な記述子は value に冗長で null になる)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
EIV1_DIR = ROOT / "db" / "eiv1"
ACTIVE_SPEC_PATH = EIV1_DIR / "feature_spec.json"

# --- 語彙 ------------------------------------------------------------------
ZONES = ("my_hand", "my_board", "opp_board", "my_trash", "opp_trash",
         "opp_seen_hand", "opp_belief")
# card_labels の effect ラベル (頻度上位) + 構造ラベル
CATS = ("removal", "removal_ko", "removal_bounce", "draw", "search", "buff_power",
        "blocker", "ramp_don", "play_accel", "keyword_grant", "tempo_rest", "attach_don",
        "untap", "life_recovery", "cost_reduce", "recursion", "protect", "disruption",
        "life_manip", "hand_disrupt", "self_discard", "negate", "power_set", "don_disrupt",
        "board_wipe", "finisher_swing", "counter_card", "high_power")
# 大きさ (矢印の長さ) を持つカテゴリ → card_magnitudes のどの量を使うか
MAG_FIELD = {"removal": "_rm_reach", "removal_ko": "_rm_reach", "removal_bounce": "_rm_reach",
             "draw": "draw", "ramp_don": "don", "buff_power": "pump", "search": "search",
             "life_recovery": "recover", "counter_card": "_counter", "high_power": "_power"}
STATS = ("count", "mag_sum", "mag_max")
CONTEXTS = ("turn", "life_diff", "opp_life", "my_life", "board_pw_diff", "my_don", "opp_hand_n")

_CARD_INFO: Optional[dict] = None
_BELIEF_TABLE: dict = {}


def _card_info() -> dict:
    """card_id → {cats: frozenset, mags: {field: value}}。 overlay/labels から 1 度だけ構築。"""
    global _CARD_INFO
    if _CARD_INFO is not None:
        return _CARD_INFO
    from . import card_labels, card_magnitudes
    info = {}
    try:
        labels = card_labels.build_all()
    except Exception:
        labels = {}
    mags = card_magnitudes.magnitudes_db()
    for cid, meta in labels.items():
        cats = set(meta.get("labels") or [])
        if meta.get("is_blocker"):
            cats.add("blocker")
        counter = float(meta.get("counter") or 0)
        power = float(meta.get("power") or 0)
        if counter > 0:
            cats.add("counter_card")
        if power >= 5000:
            cats.add("high_power")
        m = dict(mags.get(cid) or {})
        m["_rm_reach"] = max(m.get("rm_play_cost", 0.0), m.get("rm_active_cost", 0.0))
        m["_counter"] = counter / 1000.0
        m["_power"] = power / 1000.0
        m["pump"] = m.get("pump", 0.0) / 1000.0
        info[cid] = {"cats": frozenset(cats), "mags": m}
    _CARD_INFO = info
    return info


def _belief_cards(leader_id: str) -> list:
    """leader prior → [(card_id, E[枚数])] (leader 単位 cache)。 seen 減算は呼び出し側。"""
    tbl = _BELIEF_TABLE.get(leader_id)
    if tbl is None:
        try:
            from .opponent_deck_model import get_default_model
            bel = get_default_model().belief_for_leader(leader_id, None) or {}
            tbl = [(cid, float(v.get("exp_count", 0.0))) for cid, v in bel.items()]
        except Exception:
            tbl = []
        _BELIEF_TABLE[leader_id] = tbl
    return tbl


# --- 生成器 ----------------------------------------------------------------


def col_name(col: dict) -> str:
    if col.get("k") == "x":
        return f"x_{col_name(col['a'])}__{col['b']}"
    return f"{col['z']}_{col['c']}_{col['s']}"


def generate_candidates() -> list:
    """zone × カテゴリ × 統計 の直積で候補列を機械生成 (人手ゼロ)。"""
    out = []
    for z in ZONES:
        for c in CATS:
            for s in STATS:
                if s != "count" and c not in MAG_FIELD:
                    continue   # 大きさを持たないカテゴリは count と重複するので出さない
                out.append({"k": "agg", "z": z, "c": c, "s": s})
    return out


def generate_interactions(base_cols: list) -> list:
    """効いた列 × 文脈スカラー。 この repo の実績上、 効くのは盤面と相互作用する形。"""
    return [{"k": "x", "a": c, "b": ctx} for c in base_cols for ctx in CONTEXTS]


# --- 評価器 ----------------------------------------------------------------


def _zone_cards(snap: dict, zone: str) -> list:
    """zone → [(card_id, weight)]。 weight は belief のみ期待枚数、 他は 1。
    ⚠ 必要な zone だけ作る (belief は 60-100 枚を触るので、 使わない時は組まない = 推論速度)。

    ⚠ 公平性: 推論時に知り得ない情報は使わない (自分のライフ中身 / 相手の生手札は zone に無い)。
    相手手札は公開履歴 (known_hand_card_ids) のみ、 相手デッキは belief。"""
    hi = snap["hero_idx"]
    me, opp = snap["players"][hi], snap["players"][1 - hi]

    def ids(p, key):
        return [(c, 1.0) for c in (p.get(key) or []) if c]

    def field_ids(p):
        return [(c.get("card_id"), 1.0) for c in (p.get("field") or []) if c.get("card_id")]

    if zone == "my_hand":
        return ids(me, "hand_card_ids")
    if zone == "my_board":
        return field_ids(me)
    if zone == "opp_board":
        return field_ids(opp)
    if zone == "my_trash":
        return ids(me, "trash_card_ids")
    if zone == "opp_trash":
        return ids(opp, "trash_card_ids")
    if zone == "opp_seen_hand":
        return ids(opp, "known_hand_card_ids")
    if zone == "opp_belief":
        return _belief_rest(snap)
    return []


def _seen_key(snap: dict) -> tuple:
    """相手の見た札 (場+トラッシュ+バレ手札) の署名。 belief 集計の cache key。"""
    opp = snap["players"][1 - snap["hero_idx"]]
    seen: dict = {}
    for cid in [c.get("card_id") for c in (opp.get("field") or [])] \
            + list(opp.get("trash_card_ids") or []) + list(opp.get("known_hand_card_ids") or []):
        if cid:
            seen[cid] = seen.get(cid, 0) + 1
    return opp["leader"]["card_id"], tuple(sorted(seen.items()))


def _belief_rest(snap: dict) -> list:
    lid, seen_t = _seen_key(snap)
    seen = dict(seen_t)
    return [(cid, e - seen.get(cid, 0)) for cid, e in _belief_cards(lid)
            if e - seen.get(cid, 0) > 0]


_BELIEF_AGG_CACHE: dict = {}


def _belief_aggregates(snap: dict) -> dict:
    """belief zone の集計は 60-100 枚を触るので (leader, 見た札) で cache する。
    beam は同じ局面から多数の枝を評価するので hit 率が高い。"""
    key = _seen_key(snap)
    agg = _BELIEF_AGG_CACHE.get(key)
    if agg is None:
        agg = _zone_aggregates(_belief_rest(snap))
        if len(_BELIEF_AGG_CACHE) < 100000:
            _BELIEF_AGG_CACHE[key] = agg
    return agg


def _zone_aggregates(cards: list) -> dict:
    """[(cid, w)] → {(cat, stat): value}。 zone ごとに 1 回だけ回す。"""
    info = _card_info()
    agg: dict = {}
    for cid, w in cards:
        meta = info.get(cid)
        if not meta:
            continue
        mags = meta["mags"]
        for cat in meta["cats"]:
            agg[(cat, "count")] = agg.get((cat, "count"), 0.0) + w
            f = MAG_FIELD.get(cat)
            if f:
                v = float(mags.get(f, 0.0) or 0.0)
                if v:
                    agg[(cat, "mag_sum")] = agg.get((cat, "mag_sum"), 0.0) + w * v
                    agg[(cat, "mag_max")] = max(agg.get((cat, "mag_max"), 0.0), v)
    return agg


def _contexts(snap: dict) -> dict:
    hi = snap["hero_idx"]
    me, opp = snap["players"][hi], snap["players"][1 - hi]

    def pw(p):
        v = p.get("field_total_power")
        if v is None:
            v = sum(float(c.get("power") or 0) for c in (p.get("field") or []))
        return float(v) / 1000.0
    ml, ol = float(me.get("life_count") or 0), float(opp.get("life_count") or 0)
    return {"turn": float(snap.get("turn_number") or 0), "life_diff": ml - ol,
            "opp_life": ol, "my_life": ml, "board_pw_diff": pw(me) - pw(opp),
            "my_don": float(me.get("don_active") or 0),
            "opp_hand_n": float(opp.get("hand_count") or 0)}


def evaluate(snap: dict, spec: list) -> list:
    """snapshot (または _mini_snap した live state) + spec → 列の値。"""
    if not spec:
        return []
    try:
        need = set()
        for col in spec:
            need.add((col["a"] if col.get("k") == "x" else col)["z"])
        aggs = {z: (_belief_aggregates(snap) if z == "opp_belief"
                    else _zone_aggregates(_zone_cards(snap, z))) for z in need}
        ctx = _contexts(snap) if any(c.get("k") == "x" for c in spec) else {}
        out = []
        for col in spec:
            base = col["a"] if col.get("k") == "x" else col
            v = aggs[base["z"]].get((base["c"], base["s"]), 0.0)
            if col.get("k") == "x":
                v *= ctx.get(col["b"], 0.0)
            out.append(float(v))
        return out
    except Exception:
        return [0.0] * len(spec)


# --- spec の入出力 ----------------------------------------------------------


def load_spec(path: Any) -> list:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return list(d.get("columns") or [])
    except Exception:
        return []


def active_spec() -> list:
    """学習が今使う spec (無ければ空 = v20(94) のまま)。"""
    return load_spec(ACTIVE_SPEC_PATH)


def spec_path_for_model(model_path: Any) -> Path:
    p = Path(model_path)
    return p.with_suffix("").with_suffix(".spec.json") if p.suffix == ".pkl" \
        else Path(str(p) + ".spec.json")


def save_spec(path: Any, columns: list, provenance: Optional[dict] = None) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(
        {"n_columns": len(columns), "columns": columns, "provenance": provenance or {}},
        ensure_ascii=False, indent=1), encoding="utf-8")
