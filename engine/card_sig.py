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

# --- 作り込み: card_labels 未マップ primitive の追加マップ + ラッパー再帰 (2026-07-26) ------ #
# card_labels は 58 primitive しかマップしない → overlay の 141 未マップ効果/静的を sig 用に補完。
# 効果カテゴリは _LABEL_DIMS の既存名を再利用 (新規は最小)。 コスト系(pay_don/rest_self 等)は
# 「何をするか」でないので効果としては拾わない (intrinsic/cost は別途)。
_ADDITIONAL_PRIM_LABEL: dict[str, tuple[str, ...]] = {
    # コスト減
    "cost_minus": ("cost_reduce",), "in_hand_cost_minus": ("cost_reduce",),
    "set_base_cost_filtered_static": ("cost_reduce",), "set_base_cost": ("cost_reduce",),
    "set_base_cost_timed": ("cost_reduce",), "reduce_play_cost": ("cost_reduce",),
    "reduce_play_cost_filtered_static": ("cost_reduce",),
    # デッキ/ライフ操作 (mill/scry)
    "mill_self_top": ("life_manip",), "mill_self_life_to_trash": ("life_manip",),
    "mill_self_life_until_n": ("life_manip",), "scry_life": ("search",),
    "scry_all_life_one_to_deck": ("search",), "scry_deck_reorder": ("search",),
    "scry_all_life_reorder": ("search",), "look_top_reorder": ("search",),
    "peek_self_life_top": ("search",), "peek_opp_deck_top": ("search",),
    "reveal_life_top_play": ("play_accel", "search"), "reveal_top_then": ("search",),
    "shuffle_self_deck": (), "put_top_to_life": ("life_manip",), "hand_to_self_life": ("life_manip",),
    "life_to_hand": ("life_manip",), "life_top_or_bottom_to_hand": ("life_manip",),
    # 相手 mill/ライフ削り (aggressive)
    "mill_opp_life_to_trash": ("disruption", "finisher_swing"),
    "mill_opp_life_to_hand": ("disruption",), "to_opp_life": ("finisher_swing",),
    # レスト拘束
    "stay_rested_next_refresh": ("tempo_rest",), "keep_opp_rested_chara_next_refresh": ("tempo_rest",),
    "keep_opp_rested_don_next_refresh": ("tempo_rest", "don_disrupt"),
    "rest_multi": ("tempo_rest",), "set_cannot_rest": ("tempo_rest",),
    # 回収 (トラッシュ/デッキ→手札)
    "trash_to_hand": ("recursion",), "search_from_trash": ("recursion", "search"),
    "play_from_trash": ("recursion", "play_accel"), "to_hand_self_trigger": ("recursion",),
    "return_self_to_hand": ("recursion",), "return_self_to_trash": (),
    # 手札/デッキ妨害
    "opp_hand_to_deck_bottom": ("hand_disrupt", "disruption"),
    "opp_hand_to_deck_then_draw": ("hand_disrupt",), "self_hand_to_deck_bottom": (),
    "hand_to_deck_bottom": ("hand_disrupt",), "trash_opp_hand_random": ("hand_disrupt", "disruption"),
    # 展開/プレイ
    "play_self": ("play_accel",), "play_stage_from_hand": ("play_accel",),
    "play_from_hand_named_with_dynamic_cost": ("play_accel",), "play_from_hand": ("play_accel",),
    "play_from_hand_named": ("play_accel",), "summon_from_deck": ("play_accel",),
    "play_event_from_hand": ("play_accel",),
    # 除去追加
    "ko_opp_stage": ("removal", "removal_ko"), "ko_total_power_le": ("removal", "removal_ko"),
    "ko_self_with_filter": (), "chara_to_trash": ("removal",),
    "chara_to_self_life": ("removal", "removal_tolife"), "trash_all_face_up_life": ("life_manip",),
    "other_self_charas_to_deck_bottom": (), "opp_trash_to_deck_bottom": ("disruption",),
    "trash_to_deck": (), "return_self_to_deck_bottom_if_condition": (),
    # ドン妨害/操作
    "return_opp_don": ("don_disrupt",), "return_self_don_to_deck": ("ramp_don",),
    "rest_opp_don": ("don_disrupt",), "add_rested_don": ("ramp_don",),
    "opp_may_return_active_don_else_debuff": ("don_disrupt",), "move_attached_don": (),
    # 攻撃制限/静的debuff
    "set_cannot_attack": ("disruption",), "set_cannot_attack_static": ("disruption",),
    "set_cannot_attack_target_cost_le": ("disruption",), "cannot_attack_target_except": ("disruption",),
    "cannot_attack_target_cost_le": ("disruption",), "set_attack_taunt": ("disruption",),
    "block_chara_play_turn": ("disruption",), "force_opp_play_from_hand": ("disruption",),
    "disable_opp_on_play_through_opp_turn": ("disruption", "negate"),
    "prevent_blocker_for_attacker": ("disruption",),
    "prevent_blocker_for_attacker_power_le": ("disruption",),
    "disable_blocker": ("disruption",), "block_self_draw_turn": (),
    # 保護/耐性
    "give_ko_immune_through_opp_turn": ("protect",), "set_battle_ko_immune": ("protect",),
    "set_ko_immune": ("protect",), "set_ko_immune_timed": ("protect",),
    "set_ko_immune_battle_only": ("protect",), "prevent_ko": ("protect",),
    "set_protect_from_opp_effect_static": ("protect",), "set_immune_attribute_in_battle": ("protect",),
    "prevent_self_life_to_hand_turn": ("protect",),
    # パワー/バフ追加
    "power_pump_multi": ("buff_power",), "power_pump_per_target_attached_don": ("buff_power",),
    "set_base_power": ("power_set",), "set_base_power_timed": ("power_set",),
    "set_base_power_copy": ("power_set",), "swap_opp_power": ("power_set",),
    "swap_self_power": ("power_set",),
    # キーワード付与
    "give_keyword": ("keyword_grant",), "give_rush": ("rush_grant", "keyword_grant"),
    "give_attack_active_chara": ("keyword_grant",),
    # 無効/その他
    "disable_effect": ("negate",), "negate_effect": ("negate",),
    "extra_turn": ("finisher_swing",), "redirect_attack": ("redirect",),
    "flip_life_face_up_effect": ("life_manip",), "reveal_self_life_top_pump_per_cost": ("buff_power",),
    "static_swords_attack_chara": ("buff_power",),
    "static_self_attack_chara_if": ("rush_grant", "keyword_grant"),
    # 特殊勝利・残り
    "win_game": ("finisher_swing",), "set_deck_out_wins": ("finisher_swing",),
    "keep_opp_rested_chara_with_don_ge_next_refresh": ("tempo_rest",),
}
# ラッパー: 内側の効果リストをどう取り出すか (再帰対象)
_WRAPPERS: dict[str, str] = {
    "optional_cost_then": "effect",        # {cost, effect:[...]}
    "conditional": "do",                    # {do:[...], if}
    "optional_effect": "do",
    "optional_discard_hand_for_battle_buff": "do",
}


def _collect_effect_labels(effs, out: set, depth: int = 0) -> None:
    """overlay の効果ツリーを再帰的に歩き、 効果カテゴリ label を out に集める。
    ラッパー(optional_cost_then/conditional/choice_effect…)は内側を再帰。"""
    if depth > 8:
        return
    from . import card_labels as CL
    for e in (effs if isinstance(effs, list) else [effs]):
        if not isinstance(e, dict):
            continue
        # do + cost の両方を見る (cost にも効果的な primitive があるが、 主に do)
        for bucket in ("do", "cost"):
            for prim in (e.get(bucket) or []):
                if not isinstance(prim, dict):
                    continue
                for k, v in prim.items():
                    if k in _WRAPPERS:                       # ラッパー → 内側を再帰
                        inner = v.get(_WRAPPERS[k]) if isinstance(v, dict) else None
                        if inner:
                            _collect_effect_labels([{"do": inner}], out, depth + 1)
                    elif k == "choice_effect":               # {options:[{do:[...]}]}
                        opts = v.get("options") if isinstance(v, dict) else None
                        for opt in (opts or []):
                            if isinstance(opt, dict) and opt.get("do"):
                                _collect_effect_labels([{"do": opt["do"]}], out, depth + 1)
                    elif k in CL._PRIM_LABEL:
                        out.update(CL._PRIM_LABEL[k])
                    elif k in _ADDITIONAL_PRIM_LABEL:
                        out.update(_ADDITIONAL_PRIM_LABEL[k])


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
    ov_path = overlay_path or str(_ROOT / "db" / "card_effects.json")
    overlay = json.loads(Path(ov_path).read_text(encoding="utf-8"))

    out: dict = {}
    for cid, card in cards.items():
        sig = _blank()
        # 1) labels (one-hot)。 timing は card_labels の "timings"(登場時/起動メイン等)、
        # 効果カテゴリは overlay を **再帰 walk**(ラッパー展開 + 追加マップ)で網羅収集 → ギャップ解消。
        try:
            rec = label_db.get(cid) or {}
            labs = set(rec.get("timings") or [])
            _collect_effect_labels(overlay.get(cid) or [], labs)
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
