"""カード効果シグネチャ (card effect signature) — 2026-07-26。

各カードを「何をするか」の**固定長ベクトル**で表す。 既存の効果導出を consolidate:
  - card_labels     : 効果カテゴリ (removal/search/negate/keyword_grant/timing…、 ~42 種) を one-hot
  - card_magnitudes : 効果の量/射程 (除去 cost 上限・draw 枚数・pump 量…、 10 numeric)
  - card_knowledge  : caveat (ko_immune/negates/protects/recovers_at_zero、 4 binary)
  - intrinsic       : power/cost/counter/blocker

**全て overlay (db/card_effects.json) + cards.json から静的導出** = 学習不要・全4518枚 day1 カバー。
overlay が改善 (test/fix routine) されたら再導出で sig も自動同期。 埋め込みと違い「疎な per-card 統計」
を必要とせず、 同じ効果カテゴリで統計が共有される (= データ疎さ対策) [[project_card_identity_in_decisions]]。

用途: card-aware value/決定の「効果シグネチャ × 状況 × 候補差分」特徴の土台。 候補手で消える/出るカードの
sig を delta 集計 → 状況と交互作用させて value に入れる (方式B)。

  runtime: sig_for(card_id) / sig_vector(card_id)
  build  : scripts/build_card_sig.py → db/card_sig.json (dump + 検証)
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent

# --- 次元定義 (順序固定 = ベクトルの安定性) ------------------------------------ #
# card_labels の全カテゴリ (primitive + timing)。 sorted で決定的。
_LABEL_DIMS = [
    "attach_don", "board_wipe", "buff_power", "cost_reduce", "disruption", "don_disrupt",
    "draw", "finisher_swing", "hand_disrupt", "keyword_grant", "life_manip", "life_recovery",
    "negate", "play_accel", "power_set", "protect", "ramp_don", "recursion", "redirect",
    "removal", "removal_bounce", "removal_ko", "removal_tolife", "rush_grant", "search",
    "self_discard", "t_activate_main", "t_counter", "t_end_of_turn", "t_in_hand", "t_on_attack",
    "t_on_block", "t_on_ko", "t_on_play", "t_opp_attack", "t_protect", "t_static_don",
    "t_trigger", "tempo_rest", "untap",
]
_MAG_DIMS = ["rm_active_cost", "rm_active_pw", "rm_play_cost", "rm_play_pw", "rm_targets",
             "draw", "don", "pump", "search", "recover"]
_CAVEAT_DIMS = ["ko_immune", "negates", "protects", "recovers_at_zero"]
_INTRINSIC_DIMS = ["power", "cost", "counter", "is_blocker"]

SIG_KEYS: list[str] = (
    [f"lbl_{k}" for k in _LABEL_DIMS]
    + [f"mag_{k}" for k in _MAG_DIMS]
    + [f"cav_{k}" for k in _CAVEAT_DIMS]
    + [f"in_{k}" for k in _INTRINSIC_DIMS]
)
SIG_DIM = len(SIG_KEYS)

_DB: Optional[dict] = None


def _blank() -> dict:
    return {k: 0.0 for k in SIG_KEYS}


def _cards_index() -> dict:
    cards = json.loads((_ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    return {c["card_id"]: c for c in cards}


def build_all(overlay_path: Optional[str] = None) -> dict:
    """overlay + cards.json から 全カードの sig を導出。 {card_id: {SIG_KEYS: value}}。"""
    from . import card_labels as CL
    from . import card_magnitudes as CM
    from . import card_knowledge as CK

    cards = _cards_index()
    mags = CM.build_all(overlay_path)
    cav = CK.build_all(overlay_path)
    # ⚠ labels_for_card を per-card で呼ぶと build_all が毎回再実行され激遅 → 1回だけ dict を取り直接引く
    label_db = CL.build_all()

    out: dict = {}
    for cid, card in cards.items():
        sig = _blank()
        # 1) labels (one-hot)。 ⚠ card_labels は効果を "labels"、 timing(登場時/起動メイン等)を
        # "timings" の別キーで返す → 両方 union しないと timing (t_on_play/t_activate_main…) が欠落。
        try:
            rec = label_db.get(cid) or {}
            labs = set(rec.get("labels") or []) | set(rec.get("timings") or [])
        except Exception:
            labs = set()
        for k in _LABEL_DIMS:
            if k in labs:
                sig[f"lbl_{k}"] = 1.0
        # 2) magnitudes (正規化: cost はそのまま、 power/pump は /1000)
        m = mags.get(cid) or {}
        for k in _MAG_DIMS:
            v = float(m.get(k, 0.0) or 0.0)
            if k in ("rm_active_pw", "rm_play_pw", "pump"):
                v /= 1000.0
            sig[f"mag_{k}"] = v
        # 3) caveats (binary)
        cr = cav.get(cid) or {}
        for k in _CAVEAT_DIMS:
            sig[f"cav_{k}"] = 1.0 if cr.get(k) else 0.0
        # 4) intrinsic (power/1000, cost, counter/1000, blocker)。 cards.json は全て文字列。
        def _num(v):
            try:
                return float(str(v).replace(",", ""))
            except (ValueError, TypeError):
                return 0.0
        sig["in_power"] = _num(card.get("power")) / 1000.0
        sig["in_cost"] = _num(card.get("cost"))
        sig["in_counter"] = _num(card.get("counter")) / 1000.0   # "-" → 0
        text = str(card.get("text") or "")
        sig["in_is_blocker"] = 1.0 if ("ブロッカー" in text or "Blocker" in text) else 0.0
        out[cid] = sig
    return out


def sig_db() -> dict:
    """キャッシュ付き sig DB。 db/card_sig.json があれば読む、 無ければ build。"""
    global _DB
    if _DB is None:
        p = _ROOT / "db" / "card_sig.json"
        if p.exists():
            try:
                _DB = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                _DB = build_all()
        else:
            _DB = build_all()
    return _DB


def for_card(card_id: str) -> dict:
    return sig_db().get(card_id) or _blank()


def sig_vector(card_id: str) -> list:
    """SIG_KEYS 順の固定長ベクトル。"""
    s = for_card(card_id)
    return [float(s.get(k, 0.0)) for k in SIG_KEYS]
