"""カードID → 『盤面ヒューリスティックを覆す効果 + pros02 の知見』を引く知識層 (2026-07-22)。

背景: value は盤面スカラーを絶対値で見る (opp_life=0 → near-win)。 だが相手リーダー効果に
よって意味が反転する — 黄エネル(OP05-098)は 0→1 に回復するので opp_life=0 は near-win で
ない (pros: 「ライフ1から3発以上通さないと締めきれない/実効8-10ライフ」)。 = 効果を把握しない
と評価が構造的に間違う。

この層は「そのカードが何であるか(caveat)」を **カードID で** 引けるようにする。 2 源:
  1. 機械導出 (overlay): recovers_at_zero / can_recover_life / ko_immune / negates / protects 等、
     「naive 評価を無効化する」効果パターンを DSL から検出。
  2. pros02 知見 (PROS_FACTS): 記事から抽出した明示的な戦い方 (実効ライフ/リーサル要求 等)。

用途 (value feature に足すのではない — それは冗長で null):
  - lethal/burst 判定: 回復相手は opp_life=0 を lethal 扱いしない (回復を貫通する burst を要求)
  - value の補正: 該当効果 × 盤面圧 の interaction (v6 と同じ効く形)
  - Claude 教師: 「この相手にはこう指せ」の採点/実演 context
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent

# --- 機械導出: naive 評価を覆す効果パターン (overlay の when/do から検出) --- #
_RECOVER_PRIMS = {"put_top_to_life", "hand_to_self_life", "chara_to_self_life",
                  "life_top_or_bottom_to_hand"}  # 自ライフを増やす系 (回復)
_KOIMMUNE_PRIMS = {"prevent_ko", "set_ko_immune", "set_ko_immune_timed",
                   "set_ko_immune_battle_only", "set_immune_attribute_in_battle"}
_NEGATE_PRIMS = {"negate_effect", "disable_effect"}
_PROTECT_WHENS = {"replace_ko", "replace_leave"}

# --- pros02 由来の明示知見 (記事から抽出、 source を明記) --- #
# ⚠ まずは黄エネルの 1 例を seed。 スケール時は scripts で進行記事から機械抽出予定。
PROS_FACTS: dict[str, dict] = {
    "OP05-098": {  # 黄エネル
        "name": "黄エネル",
        "archetype": "回復コントロール",
        "effective_life": "8-10",   # 既存ライフ+回復で実質これだけ受ける
        "lethal_rule": "ライフ1からでも3発以上通さないと締めきれない (回復を貫通する burst 必須)",
        "vs_advice": "チマチマ削ると 1→0→1 で太らせるだけ。 盤面を作って一気に詰める時のみライフを詰める",
        "source": "pros02:n942b451cd191 (月うさぎ型黄エネル解説)",
    },
}

_CACHE: Optional[dict] = None


def _walk_keys(x, acc: set) -> None:
    if isinstance(x, list):
        for y in x:
            _walk_keys(y, acc)
    elif isinstance(x, dict):
        for k, v in x.items():
            acc.add(k)
            _walk_keys(v, acc)


def build_all(overlay_path: Optional[str] = None) -> dict:
    """全カードの caveat レコードを返す。 cid -> {caveats:[...], recovers_at_zero, ..., pros}。"""
    global _CACHE
    if _CACHE is not None and overlay_path is None:
        return _CACHE
    raw = json.loads(Path(overlay_path or (_ROOT / "db" / "card_effects.json")).read_text(encoding="utf-8"))
    out: dict = {}
    for cid, entry in raw.items():
        if not isinstance(cid, str) or cid.startswith("_") or not isinstance(entry, list):
            continue
        recovers_at_zero = False
        can_recover = ko_immune = negates = protects = False
        for e in entry:
            if not isinstance(e, dict):
                continue
            when = e.get("when")
            if when in _PROTECT_WHENS:
                protects = True
            keys: set = set()
            _walk_keys(e.get("do"), keys)
            if keys & _RECOVER_PRIMS:
                can_recover = True
                if when == "on_life_zero":
                    recovers_at_zero = True
            if keys & _KOIMMUNE_PRIMS:
                ko_immune = True
            if keys & _NEGATE_PRIMS:
                negates = True
        caveats = []
        if recovers_at_zero:
            caveats.append("recovers_at_zero")   # opp_life=0 は near-win でない
        elif can_recover:
            caveats.append("can_recover_life")
        if ko_immune:
            caveats.append("ko_immune")            # 除去が効かない
        if negates:
            caveats.append("negates")              # 自効果を消される
        if protects:
            caveats.append("protects")             # 離脱/KO を置換
        pros = PROS_FACTS.get(cid)
        if caveats or pros:
            out[cid] = {
                "caveats": caveats,
                "recovers_at_zero": recovers_at_zero,
                "can_recover_life": can_recover,
                "ko_immune": ko_immune,
                "negates": negates,
                "protects": protects,
                "pros": pros,
            }
    if overlay_path is None:
        _CACHE = out
    return out


def caveats_for(card_id: str) -> dict:
    """card_id の caveat レコード (無ければ空 dict)。 opponent leader id を渡して評価補正に使う。"""
    return build_all().get(card_id, {})


def opp_invalidates_life_pressure(leader_id: str) -> bool:
    """相手リーダーが『ライフ圧の naive 評価(opp_life=0=near-win)』を無効化するか。
    = 回復リーダー(エネル等)。 lethal 判定と value 割引のフックが参照する。"""
    return bool(build_all().get(leader_id, {}).get("recovers_at_zero"))


# --- pros02 matchup 知見 (db/pros02_matchup_facts.json、 leader_id キー) --- #
# 3 並列エージェントが note.com/pros_02 383記事から抽出・カードID検証した対戦知見。
# ~95% は fuzzy(位置取り/実効ライフ/優先除去) = Claude 教師の採点 context 用、
# 少数の機構的 fact のみ hard rule フックが参照。 builder=scripts/build_pros02_matchup_facts.py
_PROS_MATCHUP: Optional[dict] = None


def _pros_matchup() -> dict:
    global _PROS_MATCHUP
    if _PROS_MATCHUP is None:
        try:
            _PROS_MATCHUP = json.loads(
                (_ROOT / "db" / "pros02_matchup_facts.json").read_text(encoding="utf-8"))
        except Exception:
            _PROS_MATCHUP = {}
    return _PROS_MATCHUP


def matchup_facts_for(leader_id: str, fact_type: Optional[str] = None) -> list:
    """leader_id に対する pros02 知見のリスト。 fact_type で絞り込み可
    (recovery/effective_life/ko_immune/protect/key_threat/board_wipe/over_extend/negate/counter_timing)。"""
    rec = _pros_matchup().get(leader_id)
    if not rec:
        return []
    facts = rec.get("facts", [])
    if fact_type:
        facts = [f for f in facts if f.get("fact_type") == fact_type]
    return facts


def format_matchup_facts_for_teacher(leader_id: str) -> str:
    """相手 leader の pros02 知見を Claude 教師の採点 prompt 用テキストに整形。
    ~95% の fuzzy 知見の主 consumer = 教師が『プロならこう指す』の基準に使う。"""
    rec = _pros_matchup().get(leader_id)
    if not rec:
        return ""
    lines = [f"【相手 {rec.get('name', leader_id)} への pros02 定石】"]
    for f in rec.get("facts", []):
        cid = f.get("card_id")
        tag = f.get("fact_type", "")
        card = f" ({cid})" if cid else ""
        lines.append(f"  - [{tag}]{card} {f.get('rule', '')}")
    return "\n".join(lines)
