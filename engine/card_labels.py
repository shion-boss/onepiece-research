"""カード → 駒種ラベル の機械導出 (2026-07-22)。

背景: EBV2(v2 21次元 value)は盤面のスカラー量しか見ず、 「KO 効果を持つ 6000」 と
「バニラ 6000」 を score 上 区別できない (Δ=0 実証済)。 = 将棋で飛車と歩を同じ 1 枚と
数える状態。 これを解消する第一歩が 「カードに駒種ラベルを付ける」 こと。

このモジュールは overlay(db/card_effects.json)の DSL から機械的にラベルを導出する
(= 人手で 4500 枚 貼らない)。 導出物:
  - effect labels : do プリミティブ を効果カテゴリに束ねたもの (removal_ko, draw, ramp_don, ...)
  - timing labels : when トリガー (on_play, activate_main, on_attack, counter, ...)
  - structural    : is_blocker / power / cost / counter (card 本体から)

用途 (2 系統、 どちらにも同じラベルを使う):
  (A) 効果活用 指標 の分類軸 = 「AI は removal は上手いが draw の起動タイミングを外す」 を出す
  (B) piece-aware value の feature 語彙 = selection-relevant(手ごとに変わる)形で value に入れる

⚠ ラベルはあくまで粗い駒種。 精密な「今この効果を使うと強いか」 は timing/文脈依存で、
   多ターン探索 + rollout 指標が埋める。
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent

# do プリミティブ → effect label。 CLAUDE.md の DSL カテゴリ + overlay 実出現語彙に基づく。
# 1 プリミティブが複数ラベルに属してよい (= たくさんラベル)。
_PRIM_LABEL: dict[str, tuple[str, ...]] = {
    # --- 除去 (相手の駒を盤面から) ---
    "ko": ("removal", "removal_ko"),
    "ko_multi": ("removal", "removal_ko"),
    "ko_all_others": ("removal", "removal_ko", "board_wipe"),
    "return_to_hand": ("removal", "removal_bounce"),
    "return_to_hand_multi": ("removal", "removal_bounce"),
    "return_to_deck_bottom": ("removal", "removal_bounce"),
    "return_to_deck_bottom_multi": ("removal", "removal_bounce"),
    "chara_to_opp_life": ("removal", "removal_tolife"),
    # --- パワー操作 ---
    "power_pump": ("buff_power",),
    "power_pump_per_self_don": ("buff_power",),
    "power_pump_per_target_attached_don": ("buff_power",),
    "set_base_power": ("power_set",),
    "set_base_power_timed": ("power_set",),
    "set_base_power_copy": ("power_set",),
    "swap_opp_power": ("power_set", "disruption"),
    # --- ドロー / 手札 ---
    "draw": ("draw",),
    "draw_per_self_hand_discarded": ("draw",),
    "draw_per_hand_to_deck_bottom": ("draw",),
    "trash_opp_hand_random": ("disruption", "hand_disrupt"),
    "trash_self_hand_random": ("self_discard",),
    # --- サーチ / 展開加速 ---
    "search": ("search",),
    "search_top_n": ("search",),
    "reveal_top_then": ("search",),
    "reveal_top_play": ("search", "play_accel"),
    "summon_from_deck": ("play_accel",),
    "play_from_hand": ("play_accel",),
    "play_from_hand_named": ("play_accel",),
    "play_from_hand_named_set": ("play_accel",),
    "play_from_hand_or_trash": ("play_accel",),
    "play_from_trash": ("play_accel", "recursion"),
    "play_event_from_hand": ("play_accel",),
    # --- DON 加速 / 操作 ---
    "add_don": ("ramp_don",),
    "add_rested_don": ("ramp_don",),
    "attach_don": ("attach_don",),
    "attach_rested_don": ("attach_don",),
    "attach_active_don": ("attach_don",),
    "untap_don": ("untap",),
    "rest_opp_don": ("disruption", "don_disrupt"),
    "keep_opp_rested_don_next_refresh": ("disruption", "don_disrupt"),
    # --- レスト操作 ---
    "rest": ("tempo_rest",),
    "untap_chara": ("untap",),
    "set_cannot_rest": ("tempo_rest",),
    # --- キーワード付与 ---
    "give_keyword": ("keyword_grant",),
    "give_rush": ("keyword_grant", "rush_grant"),
    "give_attack_active_chara": ("keyword_grant",),
    # --- ライフ回復 / 操作 ---
    "life_to_hand": ("life_manip",),
    "put_top_to_life": ("life_recovery",),
    "hand_to_self_life": ("life_recovery",),
    "chara_to_self_life": ("life_recovery",),
    # --- 無効化 / 妨害 ---
    "negate_effect": ("negate",),
    "disable_effect": ("negate",),
    # --- KO 耐性 / 保護 ---
    "prevent_ko": ("protect",),
    "set_ko_immune": ("protect",),
    "set_ko_immune_timed": ("protect",),
    "set_ko_immune_battle_only": ("protect",),
    "set_immune_attribute_in_battle": ("protect",),
    # --- コスト操作 ---
    "reduce_play_cost": ("cost_reduce",),
    "reduce_play_cost_filtered_static": ("cost_reduce",),
    "set_base_cost": ("cost_reduce",),
    "set_base_cost_timed": ("cost_reduce",),
    # --- その他 決め手 ---
    "extra_turn": ("finisher_swing",),
    "redirect_attack": ("redirect",),
}

# when トリガー → timing label (いつ効果が出るか = 起動の「時」を選べるか)。
_WHEN_LABEL: dict[str, str] = {
    "on_play": "t_on_play",
    "activate_main": "t_activate_main",   # ★ 時を選べる = value が最も過小評価しがち
    "main": "t_activate_main",
    "on_attack": "t_on_attack",
    "counter": "t_counter",               # 手札で守備に温存する価値
    "trigger": "t_trigger",
    "on_ko": "t_on_ko",
    "on_block": "t_on_block",
    "opp_attack": "t_opp_attack",
    "end_of_turn": "t_end_of_turn",
    "on_attached_don": "t_static_don",    # DON 付与で常在強化 = 静的
    "replace_ko": "t_protect",
    "replace_leave": "t_protect",
    "in_hand": "t_in_hand",
}

_STRUCT_KEYS = frozenset(_PRIM_LABEL) | frozenset(_WHEN_LABEL)  # 参照用

_CACHE: Optional[dict] = None


def _walk_prims(do, out: set) -> None:
    if isinstance(do, list):
        for x in do:
            _walk_prims(x, out)
    elif isinstance(do, dict):
        for k, v in do.items():
            if k in _PRIM_LABEL:
                out.add(k)
            if isinstance(v, (list, dict)):
                _walk_prims(v, out)


def _card_meta(repo, cid: str) -> dict:
    try:
        c = repo.get(cid)
    except Exception:
        return {}
    return {
        "is_blocker": bool(getattr(c, "is_blocker", False)),
        "power": int(getattr(c, "power", 0) or 0),
        "cost": int(getattr(c, "cost", 0) or 0),
        "counter": int(getattr(c, "counter", 0) or 0),
        "category": str(getattr(getattr(c, "category", None), "value", "")),
    }


def build_all(repo=None, overlay_path: Optional[str] = None) -> dict:
    """全カードの label レコードを返す。 cid -> {labels, timings, prims, ...struct}。"""
    global _CACHE
    if _CACHE is not None and repo is None and overlay_path is None:
        return _CACHE
    if repo is None:
        from engine.deck import CardRepository
        repo = CardRepository.from_json(str(_ROOT / "db" / "cards.json"))
    ov_path = overlay_path or str(_ROOT / "db" / "card_effects.json")
    raw = json.loads(Path(ov_path).read_text(encoding="utf-8"))

    out: dict = {}
    for cid, entry in raw.items():
        if not isinstance(cid, str) or cid.startswith("_"):
            continue
        prims: set = set()
        timings: set = set()
        if isinstance(entry, list):
            for e in entry:
                if not isinstance(e, dict):
                    continue
                w = e.get("when")
                if w in _WHEN_LABEL:
                    timings.add(_WHEN_LABEL[w])
                _walk_prims(e.get("do"), prims)
        labels: set = set()
        for p in prims:
            labels.update(_PRIM_LABEL[p])
        meta = _card_meta(repo, cid)
        if meta.get("is_blocker"):
            labels.add("blocker")
        rec = {
            "labels": sorted(labels),
            "timings": sorted(timings),
            "prims": sorted(prims),
            **meta,
        }
        out[cid] = rec
    if repo is None and overlay_path is None:
        _CACHE = out
    return out


def labels_for_card(cid: str) -> set:
    """cid の effect label 集合 (キャッシュ経由)。"""
    rec = build_all().get(cid)
    return set(rec["labels"]) if rec else set()


# 全ラベル語彙 (feature 列や指標の分類軸に使う固定順)
EFFECT_LABELS = tuple(sorted({l for ls in _PRIM_LABEL.values() for l in ls} | {"blocker"}))
TIMING_LABELS = tuple(sorted(set(_WHEN_LABEL.values())))
