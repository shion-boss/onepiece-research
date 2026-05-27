# -*- coding: utf-8 -*-
"""
盤面評価関数 (9 指標)
=====================

`web/src/lib/boardEval.ts` と公式・重みを同期させた評価関数。

- 5 base 指標: ライフ / 場のキャラ数 / 場のパワー合計 / 手札 / DON 総数
- 4 拡張指標: ブロッカー数 / 付与 DON 合計 / アクティブキャラ数 / リーサル兆候

`compute_score` で me_idx 視点のスコアを返す (差分 = self - opp)。
`compute_breakdown` で内訳辞書 (UI / analyzer 両方で使用)。

LookaheadAI / MCTSAI / EvalGreedyAI は本モジュールを呼んで意思決定する。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import hand_estimator
from .core import GameState, Player


@dataclass
class BoardEvalWeights:
    """評価指標の重み。 default は LookaheadAI と boardEval.ts 由来の経験的値。"""

    W_LIFE: int = 1500
    W_FIELD_COUNT: int = 1200
    W_FIELD_POWER: int = 1
    W_HAND: int = 250
    W_DON: int = 200
    # 拡張指標
    W_BLOCKER: int = 800
    W_ATTACHED_DON: int = 400
    W_ACTIVE_CHARA: int = 600
    W_LETHAL: int = 5000
    # Phase 1 新規 (R68): 被リーサル / デッキ残 / トリガー期待
    W_OPP_NEXT_LETHAL: int = 4000   # opp の次ターン lethal 推定 (= 自分が殺されるリスク)
    W_DECK_FINISHER: int = 150      # 残デッキ内の finisher 数 (= 後続の打点リソース)
    W_LIFE_TRIGGER: int = 200       # 自分のライフ内のトリガー価値 (= 受けてもいいか)
    # Phase 2 新規 (R69): キャラ個別価値 / 手札の質
    # 場・手札のカードを role 別 (finisher/removal/blocker 等) で重み付け。
    # 「7-cost vanilla と 7-cost finisher」 を等価扱いする field_count/field_power の
    # 不足を補う。 コスト効率は role_value が低 (= vanilla の場合 0.5) で実質吸収。
    W_CHARA_QUALITY: int = 400      # 場のキャラの role 別合計価値
    W_HAND_QUALITY: int = 150       # 手札の role 別合計価値
    # Phase 3 新規 (R70): 相手手札の隠匿脅威推定
    # opp.hand は隠匿だが、 未公開プール (opp.deck + opp.hand) の役割分布から
    # 平均役割価値 × 手札枚数で期待脅威度を推定。 ハンド剥がし系の価値判断に効く。
    W_OPP_HAND_THREAT: int = 300
    # ----------------------------------------------------------------------- #
    # Step 2-pre (R72+): 24 新規指標。 全て初期値 0、 outcome regression で学習。
    # 計画 10 + 即追加 9 + state 拡張 5。
    # ----------------------------------------------------------------------- #
    # 計画書 10 (= 既存 plan 由来)
    W_IS_FIRST_PLAYER: int = 0
    W_STAGE_COUNT: int = 0
    W_STAGE_VALUE: int = 0
    W_TRASH_COUNT: int = 0
    W_TRASH_ARCHETYPE_MATCH: int = 0
    W_RUSH_COUNT: int = 0
    W_DOUBLE_ATTACK_COUNT: int = 0
    W_STATIC_COST_REDUCTION_TOTAL: int = 0
    W_PLAYABLE_COST_MATCH: int = 0
    W_SYNERGY_COUNT: int = 0
    # 即追加 9 (= 他ゲーム AI 調査 由来)
    W_IS_MY_TURN: int = 0
    W_TURN_NUMBER_NORMALIZED: int = 0
    W_DEAD_CARD_IN_HAND: int = 0
    W_OPP_ACTIVE_BLOCKER_COUNT: int = 0
    W_REMOVAL_THREAT_COUNT: int = 0
    W_SELF_COUNTER_IN_HAND_TOTAL: int = 0
    W_FINISHER_IN_HAND_COUNT: int = 0
    W_KEYWORD_TAUNT_COUNT: int = 0
    W_KO_IMMUNE_COUNT: int = 0
    # state 拡張 5 (= cards_drawn_count 等の累積カウンタ由来)
    W_CARDS_DRAWN_TOTAL: int = 0
    W_CARDS_PLAYED_TOTAL: int = 0
    W_DONS_USED_TOTAL: int = 0
    W_TEMPO_LOST_TOTAL: int = 0
    W_OPP_KNOWN_FINISHER_COUNT: int = 0
    # Step 2A (= 計画書 Phase 2A 由来 4 個)
    W_DON_RESERVE: int = 0
    W_FIELD_EXPOSURE: int = 0
    W_HAND_LOG: int = 0
    W_LETHAL_RISK_DIFF: int = 0
    # ----------------------------------------------------------------------- #
    # Iter2 (R72+ 続): interaction 項 30 個 (= 線形回帰では拾えない組合せ条件)。
    # 全部 binary、 self/opp 対称、 default 0 で学習任せ。
    # ----------------------------------------------------------------------- #
    # A. 危険サイン (= 守備系) 5
    W_INT_LOW_LIFE_LOW_HAND: int = 0
    W_INT_LOW_LIFE_NO_BLOCKER: int = 0
    W_INT_OPP_LETHAL_NO_COUNTER: int = 0
    W_INT_DEFENSIVE_COLLAPSE: int = 0
    W_INT_OPP_DA_PRESSURE: int = 0
    # B. 攻めサイン (= 攻撃系) 5
    W_INT_LETHAL_SETUP_READY: int = 0
    W_INT_AGGRESSIVE_WINDOW_OPEN: int = 0
    W_INT_BURST_THRESHOLD: int = 0
    W_INT_REMOVAL_WINDOW: int = 0
    W_INT_DON_ADVANTAGE_OPEN: int = 0
    # C. テンポ系 4
    W_INT_ON_CURVE: int = 0
    W_INT_TEMPO_LOST_CRITICAL: int = 0
    W_INT_RAMP_PAYING_OFF: int = 0
    W_INT_MANA_STARVED: int = 0
    # D. シナジー系 4
    W_INT_SYNERGY_THRESHOLD_3: int = 0
    W_INT_TRASH_ARCHETYPE_5: int = 0
    W_INT_STAGE_WITH_SYNERGY: int = 0
    W_INT_RAMP_FINISHER_COMBO: int = 0
    # E. 隠匿/情報系 3
    W_INT_OPP_HIDDEN_THREAT_HIGH: int = 0
    W_INT_SELF_HAND_QUALITY_HIGH: int = 0
    W_INT_OPP_LOW_RESOURCE: int = 0
    # F. ターン文脈系 3
    W_INT_EARLY_GAME_STRONG: int = 0
    W_INT_MID_GAME_PRESSURE: int = 0
    W_INT_LATE_GAME_SOLVER: int = 0
    # G. KO 耐性 / blocker 系 2
    W_INT_KO_IMMUNE_FINISHER: int = 0
    W_INT_BLOCKER_WITH_TAUNT: int = 0
    # H. 特殊 4
    W_INT_FIRST_PLAYER_EARLY_ADV: int = 0
    W_INT_SECOND_PLAYER_LATE_SWING: int = 0
    W_INT_EXPOSED_FINISHER: int = 0
    W_INT_DRAW_ADVANTAGE: int = 0
    # I. Plan Step 1: leader 固有効果 flag × state 条件 5 個
    # ai_hint_signals 由来の have_ramp 等 flag を state condition と組合せた binary features。
    W_INT_HAVE_RAMP_LOW_DON: int = 0
    W_INT_HAVE_BURST_FINISHER_LATE: int = 0
    W_INT_HAVE_SEARCH_LOOP_LOW_HAND: int = 0
    W_INT_HAVE_REMOVAL_ARSENAL_OPP_STRONG: int = 0
    W_INT_HAVE_DRAW_ENGINE_LOW_HAND: int = 0
    # ゲーム終了 (decisive)
    W_GAME_OVER: int = 1_000_000


_AI_PARAMS_PATH = Path(__file__).resolve().parent.parent / "db" / "ai_params.json"


def _load_weights_from_ai_params() -> BoardEvalWeights:
    """db/ai_params.json から重みをロード。

    ai_params.py には依存しない (循環 import 回避のため直接 json 読み)。
    ファイル不在 / 形式不正なら dataclass デフォルトに fallback。
    """
    if not _AI_PARAMS_PATH.exists():
        return BoardEvalWeights()
    try:
        data = json.loads(_AI_PARAMS_PATH.read_text(encoding="utf-8"))
        p = data.get("params", {})
        return BoardEvalWeights(
            W_LIFE=int(p.get("w_life", 1500)),
            W_FIELD_COUNT=int(p.get("w_field_count", 1200)),
            W_FIELD_POWER=int(p.get("w_field_power", 1)),
            W_HAND=int(p.get("w_hand", 250)),
            W_DON=int(p.get("w_don", 200)),
            W_BLOCKER=int(p.get("w_blocker", 800)),
            W_ATTACHED_DON=int(p.get("w_attached_don", 400)),
            W_ACTIVE_CHARA=int(p.get("w_active_chara", 600)),
            W_LETHAL=int(p.get("w_lethal", 5000)),
            W_OPP_NEXT_LETHAL=int(p.get("w_opp_next_lethal", 4000)),
            W_DECK_FINISHER=int(p.get("w_deck_finisher", 150)),
            W_LIFE_TRIGGER=int(p.get("w_life_trigger", 200)),
            W_CHARA_QUALITY=int(p.get("w_chara_quality", 400)),
            W_HAND_QUALITY=int(p.get("w_hand_quality", 150)),
            W_OPP_HAND_THREAT=int(p.get("w_opp_hand_threat", 300)),
            # Step 2-pre (R72+): 24 新規。 全て default 0、 学習で更新される。
            W_IS_FIRST_PLAYER=int(p.get("w_is_first_player", 0)),
            W_STAGE_COUNT=int(p.get("w_stage_count", 0)),
            W_STAGE_VALUE=int(p.get("w_stage_value", 0)),
            W_TRASH_COUNT=int(p.get("w_trash_count", 0)),
            W_TRASH_ARCHETYPE_MATCH=int(p.get("w_trash_archetype_match", 0)),
            W_RUSH_COUNT=int(p.get("w_rush_count", 0)),
            W_DOUBLE_ATTACK_COUNT=int(p.get("w_double_attack_count", 0)),
            W_STATIC_COST_REDUCTION_TOTAL=int(p.get("w_static_cost_reduction_total", 0)),
            W_PLAYABLE_COST_MATCH=int(p.get("w_playable_cost_match", 0)),
            W_SYNERGY_COUNT=int(p.get("w_synergy_count", 0)),
            W_IS_MY_TURN=int(p.get("w_is_my_turn", 0)),
            W_TURN_NUMBER_NORMALIZED=int(p.get("w_turn_number_normalized", 0)),
            W_DEAD_CARD_IN_HAND=int(p.get("w_dead_card_in_hand", 0)),
            W_OPP_ACTIVE_BLOCKER_COUNT=int(p.get("w_opp_active_blocker_count", 0)),
            W_REMOVAL_THREAT_COUNT=int(p.get("w_removal_threat_count", 0)),
            W_SELF_COUNTER_IN_HAND_TOTAL=int(p.get("w_self_counter_in_hand_total", 0)),
            W_FINISHER_IN_HAND_COUNT=int(p.get("w_finisher_in_hand_count", 0)),
            W_KEYWORD_TAUNT_COUNT=int(p.get("w_keyword_taunt_count", 0)),
            W_KO_IMMUNE_COUNT=int(p.get("w_ko_immune_count", 0)),
            W_CARDS_DRAWN_TOTAL=int(p.get("w_cards_drawn_total", 0)),
            W_CARDS_PLAYED_TOTAL=int(p.get("w_cards_played_total", 0)),
            W_DONS_USED_TOTAL=int(p.get("w_dons_used_total", 0)),
            W_TEMPO_LOST_TOTAL=int(p.get("w_tempo_lost_total", 0)),
            W_OPP_KNOWN_FINISHER_COUNT=int(p.get("w_opp_known_finisher_count", 0)),
            W_DON_RESERVE=int(p.get("w_don_reserve", 0)),
            W_FIELD_EXPOSURE=int(p.get("w_field_exposure", 0)),
            W_HAND_LOG=int(p.get("w_hand_log", 0)),
            W_LETHAL_RISK_DIFF=int(p.get("w_lethal_risk_diff", 0)),
            # Iter2 interaction 30 個
            W_INT_LOW_LIFE_LOW_HAND=int(p.get("w_int_low_life_low_hand", 0)),
            W_INT_LOW_LIFE_NO_BLOCKER=int(p.get("w_int_low_life_no_blocker", 0)),
            W_INT_OPP_LETHAL_NO_COUNTER=int(p.get("w_int_opp_lethal_no_counter", 0)),
            W_INT_DEFENSIVE_COLLAPSE=int(p.get("w_int_defensive_collapse", 0)),
            W_INT_OPP_DA_PRESSURE=int(p.get("w_int_opp_da_pressure", 0)),
            W_INT_LETHAL_SETUP_READY=int(p.get("w_int_lethal_setup_ready", 0)),
            W_INT_AGGRESSIVE_WINDOW_OPEN=int(p.get("w_int_aggressive_window_open", 0)),
            W_INT_BURST_THRESHOLD=int(p.get("w_int_burst_threshold", 0)),
            W_INT_REMOVAL_WINDOW=int(p.get("w_int_removal_window", 0)),
            W_INT_DON_ADVANTAGE_OPEN=int(p.get("w_int_don_advantage_open", 0)),
            W_INT_ON_CURVE=int(p.get("w_int_on_curve", 0)),
            W_INT_TEMPO_LOST_CRITICAL=int(p.get("w_int_tempo_lost_critical", 0)),
            W_INT_RAMP_PAYING_OFF=int(p.get("w_int_ramp_paying_off", 0)),
            W_INT_MANA_STARVED=int(p.get("w_int_mana_starved", 0)),
            W_INT_SYNERGY_THRESHOLD_3=int(p.get("w_int_synergy_threshold_3", 0)),
            W_INT_TRASH_ARCHETYPE_5=int(p.get("w_int_trash_archetype_5", 0)),
            W_INT_STAGE_WITH_SYNERGY=int(p.get("w_int_stage_with_synergy", 0)),
            W_INT_RAMP_FINISHER_COMBO=int(p.get("w_int_ramp_finisher_combo", 0)),
            W_INT_OPP_HIDDEN_THREAT_HIGH=int(p.get("w_int_opp_hidden_threat_high", 0)),
            W_INT_SELF_HAND_QUALITY_HIGH=int(p.get("w_int_self_hand_quality_high", 0)),
            W_INT_OPP_LOW_RESOURCE=int(p.get("w_int_opp_low_resource", 0)),
            W_INT_EARLY_GAME_STRONG=int(p.get("w_int_early_game_strong", 0)),
            W_INT_MID_GAME_PRESSURE=int(p.get("w_int_mid_game_pressure", 0)),
            W_INT_LATE_GAME_SOLVER=int(p.get("w_int_late_game_solver", 0)),
            W_INT_KO_IMMUNE_FINISHER=int(p.get("w_int_ko_immune_finisher", 0)),
            W_INT_BLOCKER_WITH_TAUNT=int(p.get("w_int_blocker_with_taunt", 0)),
            W_INT_FIRST_PLAYER_EARLY_ADV=int(p.get("w_int_first_player_early_adv", 0)),
            W_INT_SECOND_PLAYER_LATE_SWING=int(p.get("w_int_second_player_late_swing", 0)),
            W_INT_EXPOSED_FINISHER=int(p.get("w_int_exposed_finisher", 0)),
            W_INT_DRAW_ADVANTAGE=int(p.get("w_int_draw_advantage", 0)),
            W_INT_HAVE_RAMP_LOW_DON=int(p.get("w_int_have_ramp_low_don", 0)),
            W_INT_HAVE_BURST_FINISHER_LATE=int(p.get("w_int_have_burst_finisher_late", 0)),
            W_INT_HAVE_SEARCH_LOOP_LOW_HAND=int(p.get("w_int_have_search_loop_low_hand", 0)),
            W_INT_HAVE_REMOVAL_ARSENAL_OPP_STRONG=int(p.get("w_int_have_removal_arsenal_opp_strong", 0)),
            W_INT_HAVE_DRAW_ENGINE_LOW_HAND=int(p.get("w_int_have_draw_engine_low_hand", 0)),
        )
    except Exception:
        return BoardEvalWeights()


DEFAULT_WEIGHTS = _load_weights_from_ai_params()


def reload_default_weights() -> BoardEvalWeights:
    """学習で db/ai_params.json が更新された後、 メモリ上の DEFAULT_WEIGHTS を再ロード。"""
    global DEFAULT_WEIGHTS
    DEFAULT_WEIGHTS = _load_weights_from_ai_params()
    return DEFAULT_WEIGHTS


# archetype 名 → ASCII slug (= ファイル名安全)
_ARCHETYPE_SLUG = {
    "コントロール": "control",
    "ミッドレンジ": "midrange",
    "アグロ": "aggro",
    "ランプ": "ramp",
    "コンボ": "combo",
    "ビートダウン": "beatdown",
    "ステラ": "stella",
}

# archetype 別 重み cache (= 各試合で load 回避、 重み更新時に invalidate)
_ARCHETYPE_WEIGHTS_CACHE: dict[str, BoardEvalWeights] = {}


def archetype_to_slug(archetype: str) -> str:
    """日本語 archetype 名を ASCII slug 化。 未知は そのまま小文字 ASCII tolerant。"""
    if archetype in _ARCHETYPE_SLUG:
        return _ARCHETYPE_SLUG[archetype]
    return archetype.lower().replace(" ", "_")


def load_weights_for_archetype(archetype: str) -> Optional[BoardEvalWeights]:
    """db/ai_params_archetypes/<slug>.json から重みを load。 無ければ None (= base にフォールバック)。

    cache 利用で 同 archetype の load を 1 回に。 invalidate_archetype_cache で reset 可。
    """
    if not archetype:
        return None
    slug = archetype_to_slug(archetype)
    if slug in _ARCHETYPE_WEIGHTS_CACHE:
        return _ARCHETYPE_WEIGHTS_CACHE[slug]
    path = Path(__file__).resolve().parent.parent / "db" / "ai_params_archetypes" / f"{slug}.json"
    if not path.exists():
        _ARCHETYPE_WEIGHTS_CACHE[slug] = None  # type: ignore
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        p = data.get("params", {})
        # _load_weights_from_ai_params と同じ rote pattern (= 全 73 dim load)
        # 不在 key は base 値 (= ai_params.json default) で fallback
        base = _load_weights_from_ai_params()  # base を起点に upsert
        for key, val in p.items():
            wfield = key.upper()
            if hasattr(base, wfield):
                setattr(base, wfield, int(val) if isinstance(val, (int, float)) else val)
        _ARCHETYPE_WEIGHTS_CACHE[slug] = base
        return base
    except Exception:
        _ARCHETYPE_WEIGHTS_CACHE[slug] = None  # type: ignore
        return None


def invalidate_archetype_cache() -> None:
    """学習で archetype 重みが更新された時に cache を reset。"""
    global _ARCHETYPE_WEIGHTS_CACHE
    _ARCHETYPE_WEIGHTS_CACHE = {}


def _load_archetype_weights_by_slug(archetype_slug: str) -> Optional[BoardEvalWeights]:
    """ASCII slug 直接指定で archetype 重みを load (= archetype.json の絶対値)。
    base + archetype 平均が入った状態の重みを返す。 無ければ None。
    """
    if not archetype_slug:
        return None
    path = Path(__file__).resolve().parent.parent / "db" / "ai_params_archetypes" / f"{archetype_slug}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        p = data.get("params", {})
        base = _load_weights_from_ai_params()
        for key, val in p.items():
            wfield = key.upper()
            if hasattr(base, wfield):
                setattr(base, wfield, int(val) if isinstance(val, (int, float)) else val)
        return base
    except Exception:
        return None


def load_weights_for_deck(deck_slug: str) -> Optional[BoardEvalWeights]:
    """db/ai_params_decks/<slug>.json から重みを load (= deck 別 fine-tune 結果)。

    Phase 2 集約後の hierarchical 形式:
    - deck json の params = archetype 重みからの offset (= 微小調整値)
    - base_archetype field で「どの archetype を 起点にするか」 を指定
    - 最終重み = archetype 重み (= base + archetype 平均) + deck offset

    無ければ None (= archetype 単独 / global base にフォールバック)。
    """
    if not deck_slug:
        return None
    if deck_slug in _ARCHETYPE_WEIGHTS_CACHE:
        return _ARCHETYPE_WEIGHTS_CACHE[deck_slug]
    path = Path(__file__).resolve().parent.parent / "db" / "ai_params_decks" / f"{deck_slug}.json"
    if not path.exists():
        _ARCHETYPE_WEIGHTS_CACHE[deck_slug] = None  # type: ignore
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        p = data.get("params", {})
        params_type = data.get("params_type", "")
        base_archetype = data.get("base_archetype", "")

        if params_type == "offset_from_archetype" and base_archetype:
            # 集約後の hierarchical 形式: archetype 重み に offset を加算
            base = _load_archetype_weights_by_slug(base_archetype)
            if base is None:
                base = _load_weights_from_ai_params()
            for key, val in p.items():
                wfield = key.upper()
                if hasattr(base, wfield):
                    old = getattr(base, wfield)
                    setattr(base, wfield, int(old + (val if isinstance(val, (int, float)) else 0)))
        else:
            # 旧形式 (= deck 重みが絶対値、 base からの直接 fine-tune)
            base = _load_weights_from_ai_params()
            for key, val in p.items():
                wfield = key.upper()
                if hasattr(base, wfield):
                    setattr(base, wfield, int(val) if isinstance(val, (int, float)) else val)

        _ARCHETYPE_WEIGHTS_CACHE[deck_slug] = base
        return base
    except Exception:
        _ARCHETYPE_WEIGHTS_CACHE[deck_slug] = None  # type: ignore
        return None


def compute_dynamic_weights_v2(state: "GameState", me_idx: int) -> dict[str, float]:
    """Plan F 用: state-dependent な動的重み 9 dim を dict で返す (= 教師データ生成用)。

    eval.py の compute_score 内 ONEPIECE_DYNAMIC_WEIGHTS=1 path と同じロジック。
    weight_nn の supervised warm start で「人間 hand-tuned 関数」 を教師にする。
    """
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]
    base = select_weights_for_player(state, me_idx)

    my_life = len(me.life)
    opp_life = len(opp.life)
    my_hand = len(me.hand)
    opp_hand = len(opp.hand)
    turn = state.turn_number
    opp_field_power = sum(getattr(c, "power", 0) for c in opp.characters)

    turn_factor = 1.0 + max(0, turn - 5) * 0.15

    if my_life >= 4:
        w_life_self_mult = 0.5 * turn_factor
    elif my_life >= 2:
        w_life_self_mult = 1.0 * turn_factor
    else:
        w_life_self_mult = 2.5 * turn_factor

    if opp_life >= 4:
        w_life_opp_mult = 0.7 * turn_factor
    elif opp_life >= 2:
        w_life_opp_mult = 1.2 * turn_factor
    else:
        w_life_opp_mult = 2.5 * turn_factor

    # 自分 / 相手 で重み違うが、 単一 W_LIFE しか NN 出力ないので 平均で代表
    w_life = base.W_LIFE * (w_life_self_mult + w_life_opp_mult) / 2

    if my_hand <= 2:
        w_hand_self_mult = 2.5
    elif my_hand <= 5:
        w_hand_self_mult = 1.0
    else:
        w_hand_self_mult = 0.4
    if opp_hand <= 2:
        w_hand_opp_mult = 1.5
    elif opp_hand <= 5:
        w_hand_opp_mult = 1.0
    else:
        w_hand_opp_mult = 0.6
    w_hand = base.W_HAND * (w_hand_self_mult + w_hand_opp_mult) / 2

    # DON 一律低 (= ohtsuki さん指摘で「数」 ではなく「質」 で評価、 W_DON は score 化しない方向)
    # 2026-05-20: snapshot 解析 で REFRESH DON return が critical board_eval drop 起こす confirmed、
    # 0.4 → 0.1 に さらに 削減 (= DON 数 評価 を ほぼ 無効化)。
    w_don = base.W_DON * 0.1

    opp_field_strength = 1.0
    if opp_field_power >= 15000:
        opp_field_strength = 1.5
    elif opp_field_power >= 8000:
        opp_field_strength = 1.2
    w_blocker = base.W_BLOCKER * opp_field_strength

    return {
        "W_LIFE": float(w_life),
        "W_HAND": float(w_hand),
        "W_FIELD_COUNT": float(base.W_FIELD_COUNT),
        "W_FIELD_POWER": float(base.W_FIELD_POWER),
        "W_DON": float(w_don),
        "W_BLOCKER": float(w_blocker),
        "W_ATTACHED_DON": float(base.W_ATTACHED_DON),
        "W_ACTIVE_CHARA": float(base.W_ACTIVE_CHARA),
        "W_LETHAL": float(base.W_LETHAL),
    }


def select_weights_for_player(state: GameState, me_idx: int) -> BoardEvalWeights:
    """state.deck_slugs[me_idx] → state.archetypes[me_idx] → DEFAULT_WEIGHTS の優先順で重み選択。

    1. ai_params_decks/<deck_slug>.json (= deck 別 fine-tune)
    2. ai_params_archetypes/<archetype_slug>.json (= archetype 別 fine-tune、 fallback)
    3. DEFAULT_WEIGHTS (= base、 最終 fallback)
    """
    deck_slugs = getattr(state, "deck_slugs", ["", ""])
    archetypes = getattr(state, "archetypes", ["", ""])
    if me_idx < len(deck_slugs):
        w = load_weights_for_deck(deck_slugs[me_idx])
        if w is not None:
            return w
    if me_idx < len(archetypes):
        w = load_weights_for_archetype(archetypes[me_idx])
        if w is not None:
            return w
    return DEFAULT_WEIGHTS


def _player_metrics(p: Player) -> dict:
    """Player から 8 種の生指標を抽出 (lethal を除く)。"""
    blocker = sum(
        1 for c in p.characters if c.has_keyword_active("ブロッカー")
    )
    attached = (
        p.leader.attached_dons
        + sum(c.attached_dons for c in p.characters)
        + sum(s.attached_dons for s in p.stages)
    )
    active_chara = sum(
        1
        for c in p.characters
        if not c.rested and (not c.summoning_sickness or c.is_rush_now)
    )
    return {
        "life": len(p.life),
        "field_count": len(p.characters),
        "field_power": sum(c.power for c in p.characters),
        "hand": len(p.hand),
        "don": p.total_don,
        "blocker": blocker,
        "attached_don": attached,
        "active_chara": active_chara,
    }


def lethal_estimate(state: GameState, me_idx: int) -> float:
    """me の「次自ターン総打点」リーサル可能性を 0.0〜1.0 で返す。 boardEval.ts と同公式。

    me の「次ターン総打点」(active leader + active chars) と opp の防御力
    (life × 5000 + 期待カウンター総量) を比較し、 sigmoid でスケール。

    rest/sickness は **次の自ターン開始時 の refresh で 解除** される ので、
    現状態 の rest/sickness は 「次ターン リーサル」 評価には 含めない。
    cannot_attack_static など 永続的攻撃不能 のみ 除外 する (= project_opp_next_turn_lethal と対称)。

    この仕様 で 重要な バグ修正: 旧版 では 自リーダー attack 後 rested → lethal_estimate ≈ 0
    → plan_search で 「leader attack は lethal 期待値 を 0 に する」 と 過大ペナルティ →
    AI が leader attack を 避ける 現象 が 起きていた。

    期待カウンター総量は `hand_estimator.expected_counter_total` で算出:
    opp.deck + opp.hand プール上の平均カウンター値 × 手札枚数。
    トラッシュ済カウンター持ちは自動的に除外される。
    """
    self_p = state.players[me_idx]
    opp_p = state.players[1 - me_idx]
    attackers: list[int] = []
    # 自リーダー: cannot_attack_static でなければ 含める (= 次ターン rest 解除 想定)
    if not self_p.leader.cannot_attack_static:
        attackers.append(self_p.leader.power)
    for c in self_p.characters:
        # 永続的攻撃不能のみ 除外、 rest/sickness は 次ターン refresh で 解除
        if c.cannot_attack_static:
            continue
        attackers.append(c.power)
    if not attackers:
        return 0.0
    opp_leader_p = opp_p.leader.power
    excesses = [max(0, p - opp_leader_p) for p in attackers]
    total_excess = sum(excesses)
    opp_counter_total = hand_estimator.expected_counter_total(state, 1 - me_idx)
    opp_defense = len(opp_p.life) * 5000 + opp_counter_total
    if opp_defense == 0:
        return 1.0
    ratio = total_excess / opp_defense
    return 1.0 / (1.0 + math.exp(-2 * (ratio - 1)))


def project_opp_next_turn_lethal(state: GameState, me_idx: int) -> float:
    """opp が次ターン REFRESH 後に持つ lethal 見積。 lethal_estimate の対称版。

    me が opp ターンに殺されるリスクを 0.0〜1.0 で返す。
    opp.characters は全 active 想定 (= sickness/rest が opp の REFRESH で解除される)。
    cannot_attack_static など攻撃禁止の状態は維持。
    """
    self_p = state.players[me_idx]
    opp_p = state.players[1 - me_idx]

    attackers: list[int] = []
    # opp.leader: cannot_attack_static でなければ参加 (= 次ターン rest 解除)
    if not opp_p.leader.cannot_attack_static:
        attackers.append(opp_p.leader.power)
    for c in opp_p.characters:
        # 永続的に攻撃不能なキャラは除外。 rest/sickness は次ターン解除されるので無視。
        if c.cannot_attack_static:
            continue
        attackers.append(c.power)
    if not attackers:
        return 0.0

    self_leader_p = self_p.leader.power
    excesses = [max(0, p - self_leader_p) for p in attackers]
    total_excess = sum(excesses)

    self_counter_total = hand_estimator.expected_counter_total(state, me_idx)
    self_defense = len(self_p.life) * 5000 + self_counter_total
    if self_defense == 0:
        return 1.0
    ratio = total_excess / self_defense
    return 1.0 / (1.0 + math.exp(-2 * (ratio - 1)))


def deck_finisher_count(player: Player) -> int:
    """残デッキ内の finisher 系カード数。 card_role.json の primary_role=finisher で判定。

    role 不明のカードは「不明」 として除外。 デッキ尽きた状態 (mill 直前) で 0 を返す。
    """
    from . import card_role
    try:
        role_db = card_role.load_card_role_db()
    except Exception:
        return 0
    count = 0
    for c in player.deck:
        v = role_db.get(c.card_id)
        if isinstance(v, dict) and v.get("primary_role") == "finisher":
            count += 1
    return count


def life_trigger_value(player: Player, overlay: Optional[dict]) -> float:
    """player.life カードのトリガー効果の総価値を見積。

    トリガー primitive 別に重み付け:
    - KO 系 (ko / ko_multi / ko_all_others): 3.0 (= 雷迎、 ヘラ等の強力 trigger)
    - return_to_hand / return_to_deck_bottom: 2.5
    - search 系: 1.5
    - draw: 1.0
    - power_pump / set_base_power: 0.5
    - その他のトリガー: 0.3

    overlay が None なら 0 を返す (= ライフトリガー価値を eval に組み込まない、 safe fallback)。
    """
    if not overlay:
        return 0.0
    score = 0.0
    for card in player.life:
        bundle = overlay.get(card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            if eff.get("when") != "trigger":
                continue
            for prim in eff.get("do", []):
                if not isinstance(prim, dict):
                    continue
                if any(k in prim for k in ("ko", "ko_multi", "ko_all_others")):
                    score += 3.0
                elif any(k in prim for k in ("return_to_hand", "return_to_hand_multi",
                                              "return_to_deck_bottom", "return_to_deck_bottom_multi")):
                    score += 2.5
                elif "search" in prim:
                    score += 1.5
                elif "draw" in prim:
                    score += 1.0
                elif any(k in prim for k in ("power_pump", "set_base_power", "set_base_power_timed")):
                    score += 0.5
                else:
                    score += 0.3
    return score


# role 別の基本価値 (R69)。
# - finisher: 高打点 / KO カード (= 主力)
# - removal: opp.chara KO 系
# - negation: 効果無効化
# - blocker: 防御専門
# - draw / search: 手札補充 / フィルタ
# - ramp: DON 加速
# - synergy: 効果連鎖の起点
# - disruption: opp.手札 / DON 妨害
# - recovery: ライフ回復系
# 不明 role は default 0.5 (= vanilla 扱い)。
_ROLE_VALUES: dict[str, float] = {
    "finisher": 3.0,
    "removal": 2.5,
    "negation": 2.5,
    "blocker": 2.0,
    "disruption": 2.0,
    "recovery": 1.5,
    "ramp": 1.5,
    "draw": 1.5,
    "search": 1.5,
    "synergy": 1.0,
}


def _role_value_of(card_id: str, role_db: dict) -> float:
    """card_role db から primary_role を引いて value を返す。 不明なら 0.5。"""
    v = role_db.get(card_id)
    if isinstance(v, dict):
        return _ROLE_VALUES.get(v.get("primary_role", ""), 0.5)
    return 0.5


# {card_id: role_value} の直接 cache (= primary_role を経由しない O(1) ルックアップ)。
# plan_search は compute_score を 6 回/clone × 20k clone = 125k 回呼ぶ。 各 score 内で
# opp_hand_threat が opp.deck + opp.hand (= ~55 cards) を走査するため 5M+ 回 _role_value_of が
# 呼ばれる。 dict 2-hop を 1-hop に縮めるだけで顕著に効く (R70 最適化)。
_CARD_VALUE_CACHE: Optional[dict[str, float]] = None


def _get_card_value(card_id: str) -> float:
    """{card_id: float} 直接キャッシュ。 _role_value_of の高速版。"""
    global _CARD_VALUE_CACHE
    if _CARD_VALUE_CACHE is None:
        from . import card_role
        try:
            role_db = card_role.load_card_role_db()
        except Exception:
            _CARD_VALUE_CACHE = {}
            return 0.5
        _CARD_VALUE_CACHE = {
            cid: _ROLE_VALUES.get(v.get("primary_role", ""), 0.5) if isinstance(v, dict) else 0.5
            for cid, v in role_db.items()
        }
    return _CARD_VALUE_CACHE.get(card_id, 0.5)


def chara_quality_score(player: Player) -> float:
    """場のキャラの役割別合計価値。 field_count + field_power では捉えきれない「質」 を測る。

    例: 6-cost 7000-power finisher は 3.0、 6-cost 7000-power vanilla は 0.5。
    role_db に登録ないキャラは default 0.5。
    """
    total = 0.0
    for ip in player.characters:
        total += _get_card_value(ip.card.card_id)
    return total


def hand_quality_score(player: Player) -> float:
    """手札の役割別合計価値。 finisher 多数 vs vanilla 多数 を区別する。"""
    total = 0.0
    for c in player.hand:
        total += _get_card_value(c.card_id)
    return total


# ----------------------------------------------------------------------- #
# Step 2-pre (R72+): 24 新規指標の計算 helper。 全て feature value のみを返す
# (= 重みは BoardEvalWeights / compute_breakdown で適用)。
# ----------------------------------------------------------------------- #


# role 判定 cache (= _CARD_VALUE_CACHE と並行)
_CARD_ROLE_CACHE: Optional[dict[str, str]] = None


def _get_card_role(card_id: str) -> str:
    """{card_id: primary_role} の直接 cache。 未登録は ""(空文字)。"""
    global _CARD_ROLE_CACHE
    if _CARD_ROLE_CACHE is None:
        from . import card_role
        try:
            role_db = card_role.load_card_role_db()
        except Exception:
            _CARD_ROLE_CACHE = {}
            return ""
        _CARD_ROLE_CACHE = {
            cid: v.get("primary_role", "") if isinstance(v, dict) else ""
            for cid, v in role_db.items()
        }
    return _CARD_ROLE_CACHE.get(card_id, "")


def stage_count(player: Player) -> int:
    """場のステージ枚数。"""
    return len(player.stages)


def stage_value(player: Player) -> float:
    """場のステージの role 別合計価値。"""
    return sum(_get_card_value(s.card.card_id) for s in player.stages)


def trash_count(player: Player) -> int:
    """トラッシュ枚数。"""
    return len(player.trash)


def trash_archetype_match(player: Player) -> int:
    """トラッシュ内、 自リーダー features と共通 feature を持つカード数。

    紫エネル系 (= サトリ等) の発動条件 / 黒系 (= cost-by-trash) の参照。
    leader.features ∩ trash card.features ≠ ∅ をカウント。
    """
    leader_features = set(player.leader.card.features or ())
    if not leader_features:
        return 0
    count = 0
    for c in player.trash:
        if leader_features & set(c.features or ()):
            count += 1
    return count


def rush_count(player: Player) -> int:
    """場のキャラのうち 速攻 持ち数。"""
    return sum(1 for c in player.characters if c.is_rush_now)


def double_attack_count(player: Player) -> int:
    """場のキャラのうち ダブルアタック 持ち数。"""
    return sum(1 for c in player.characters if c.is_double_attack_now)


def static_cost_reduction_total(player: Player) -> int:
    """常駐 cost 軽減源の合計 (= play_cost_reductions_filtered の amount sum)。"""
    return sum(int(r.get("amount", 0)) for r in player.play_cost_reductions_filtered)


def synergy_count(player: Player) -> int:
    """場 (= leader + characters + stages) の特徴チェーン数。

    各 feature について 「leader が持ってて、 場に同 feature 持ちキャラが N 体」 なら N をカウント。
    複数 feature が重なれば加算 (= 麦わら × 4 + 海軍 × 2 等)。
    feature が leader にない場合は 0 (= リーダーに紐づかないシナジーは無視)。
    """
    leader_features = set(player.leader.card.features or ())
    if not leader_features:
        return 0
    feature_count: dict[str, int] = {f: 0 for f in leader_features}
    for ip in player.characters:
        for f in (ip.card.features or ()):
            if f in feature_count:
                feature_count[f] += 1
    for ip in player.stages:
        for f in (ip.card.features or ()):
            if f in feature_count:
                feature_count[f] += 1
    return sum(feature_count.values())


def dead_card_in_hand(player: Player) -> int:
    """手札中、 現在の don_active で play 不可能なカード数 (= dead in hand)。

    cost - play_cost_reduction > don_active で dead 判定。
    手札は隠匿だが、 self 視点なら自手札なので公開情報。
    """
    available_don = player.don_active
    reduction = player.play_cost_reduction
    count = 0
    for c in player.hand:
        eff_cost = max(0, (c.cost or 0) - reduction)
        if eff_cost > available_don:
            count += 1
    return count


def active_blocker_count(player: Player) -> int:
    """場のキャラのうち active (= not rested) かつ blocker。 既存 blocker は rest 無視。"""
    return sum(
        1 for c in player.characters
        if c.is_blocker_now and not c.rested
    )


def removal_threat_count(player: Player) -> int:
    """手札中の role=removal カード数 + 場の activate_main で removal 持ち数。

    簡略化: 手札のみ。 場の activate_main は overlay 走査が必要 → 省略。
    self 側のみ完全公開、 opp は known_hand_card_ids 経由で部分公開。
    """
    return sum(1 for c in player.hand if _get_card_role(c.card_id) == "removal")


def self_counter_in_hand_total(player: Player) -> int:
    """自手札の counter 値合計 (= 公開情報側の counter 厚さ)。"""
    return sum(c.counter or 0 for c in player.hand)


def finisher_in_hand_count(player: Player) -> int:
    """自手札の role=finisher カード数。"""
    return sum(1 for c in player.hand if _get_card_role(c.card_id) == "finisher")


def keyword_taunt_count(player: Player) -> int:
    """場のキャラのうち attack_taunt (= 「相手はこのキャラ以外にアタックできない」) 数。"""
    return sum(1 for c in player.characters if c.attack_taunt)


def ko_immune_count(player: Player) -> int:
    """場のキャラのうち KO 耐性 (= 静的 / バトル / ターン中) を持つ数。"""
    count = 0
    for c in player.characters:
        if (
            c.battle_ko_immune_static
            or c.static_ko_immune
            or c.ko_immune_until_turn_end
            or c.ko_immune_through_opp_turn
            or c.ko_immune_battle_attributes_in
            or c.ko_immune_battle_attributes_not_in
        ):
            count += 1
    return count


def opp_known_finisher_count(player: Player) -> int:
    """known_hand_card_ids 内の role=finisher カード数。

    Phase 7I の公開済手札追跡を利用 (= return_to_hand / search で公開した分)。
    隠匿でない部分のみカウント。
    """
    return sum(1 for cid in player.known_hand_card_ids if _get_card_role(cid) == "finisher")


def playable_cost_match(player: Player) -> int:
    """「max 手札 cost - don_active」 の単純差。 大きいほど 手札が重く play できない (= bad)。

    on-curve かどうかのテンポ整合度。 手札空なら 0 を返す (= 計算不能)。
    """
    if not player.hand:
        return 0
    max_cost = max((c.cost or 0) for c in player.hand)
    return max_cost - player.don_active


def don_reserve(player: Player) -> int:
    """未使用 DON (= don_active)。 既存 W_DON は total_don なので別物。"""
    return player.don_active


def field_exposure(self_p: Player, opp_p: Player) -> int:
    """opp の最大 attacker power で取られそうな自キャラ数。

    opp の leader + characters のうち active な最大 power を attacker_max とし、
    self.characters のうち power < attacker_max + 1000 (= 1 ドン付与で届く) の数を返す。
    """
    attackers = [opp_p.leader.power] if not opp_p.leader.rested else []
    attackers.extend(
        c.power for c in opp_p.characters
        if not c.rested and (not c.summoning_sickness or c.is_rush_now)
    )
    if not attackers:
        return 0
    threshold = max(attackers) + 1000  # 1 DON 付与で届く
    return sum(1 for c in self_p.characters if c.power < threshold)


def hand_log(player: Player) -> float:
    """log(hand + 1)。 hand 6→7 と 1→2 の価値差を非線形化。"""
    return math.log(len(player.hand) + 1)


def lethal_risk_diff(state: GameState, me_idx: int) -> int:
    """self_lethal >= 0.7 - opp_lethal >= 0.7 の binary 化。

    既存 lethal は連続値、 この指標は「クリティカル閾値到達」 binary。
    """
    self_l = lethal_estimate(state, me_idx)
    opp_l = lethal_estimate(state, 1 - me_idx)
    self_bin = 1 if self_l >= 0.7 else 0
    opp_bin = 1 if opp_l >= 0.7 else 0
    return self_bin - opp_bin


def _compute_interactions(
    state: GameState, me_idx: int,
    me: Player, opp: Player,
    sm: dict, om: dict,
    self_lethal_v: float, opp_lethal_v: float,
    weights: BoardEvalWeights,
) -> list[tuple]:
    """Iter2 (R72+): 30 個の binary interaction 項を計算。

    self/opp 対称、 me 視点で self_value / opp_value を返す。 各重み 0 で start、
    線形回帰で重み学習。 「線形モデルが拾えない組合せ条件」 を明示的に手書き。
    """
    me_blocker = sm["blocker"]; opp_blocker = om["blocker"]
    me_active = sm["active_chara"]; opp_active = om["active_chara"]
    me_life = sm["life"]; opp_life = om["life"]
    me_hand = sm["hand"]; opp_hand = om["hand"]
    me_don = sm["don"]; opp_don = om["don"]
    turn = state.turn_number
    me_is_first = me_idx == 0

    me_double_atk = double_attack_count(me)
    opp_double_atk = double_attack_count(opp)
    me_active_blocker = active_blocker_count(me)
    opp_active_blocker = active_blocker_count(opp)
    me_dead_in_hand = dead_card_in_hand(me)
    opp_dead_in_hand = dead_card_in_hand(opp)
    me_counter = self_counter_in_hand_total(me)
    opp_counter = self_counter_in_hand_total(opp)
    me_finisher_hand = finisher_in_hand_count(me)
    opp_finisher_hand = finisher_in_hand_count(opp)
    me_synergy = synergy_count(me)
    opp_synergy = synergy_count(opp)
    me_stage = stage_count(me)
    opp_stage = stage_count(opp)
    me_trash_arch = trash_archetype_match(me)
    opp_trash_arch = trash_archetype_match(opp)
    me_ko_immune = ko_immune_count(me)
    opp_ko_immune = ko_immune_count(opp)
    me_taunt = keyword_taunt_count(me)
    opp_taunt = keyword_taunt_count(opp)
    me_chara_q = chara_quality_score(me)
    opp_chara_q = chara_quality_score(opp)
    me_hand_q = hand_quality_score(me)
    opp_hand_q = hand_quality_score(opp)
    me_field_exp = field_exposure(me, opp)
    opp_field_exp = field_exposure(opp, me)
    me_known_fin = opp_known_finisher_count(me)
    opp_known_fin = opp_known_finisher_count(opp)
    self_threat = opp_hand_threat_estimate(state, 1 - me_idx)  # me 視点での 自分への threat 鏡像
    opp_threat = opp_hand_threat_estimate(state, me_idx)
    me_removal = removal_threat_count(me)
    opp_removal = removal_threat_count(opp)
    opp_field_finisher = sum(1 for c in opp.characters if _get_card_role(c.card.card_id) == "finisher")
    self_field_finisher = sum(1 for c in me.characters if _get_card_role(c.card.card_id) == "finisher")

    def b(cond): return 1 if cond else 0

    metrics = [
        # A. 危険サイン (= 守備系) 5
        ("int_low_life_low_hand",
            b(me_life <= 2 and me_hand <= 2),
            b(opp_life <= 2 and opp_hand <= 2),
            weights.W_INT_LOW_LIFE_LOW_HAND),
        ("int_low_life_no_blocker",
            b(me_life <= 2 and me_blocker == 0),
            b(opp_life <= 2 and opp_blocker == 0),
            weights.W_INT_LOW_LIFE_NO_BLOCKER),
        ("int_opp_lethal_no_counter",
            b(opp_lethal_v >= 0.7 and me_counter <= 2000),
            b(self_lethal_v >= 0.7 and opp_counter <= 2000),
            weights.W_INT_OPP_LETHAL_NO_COUNTER),
        ("int_defensive_collapse",
            b(opp_lethal_v >= 0.7 and me_active <= 1),
            b(self_lethal_v >= 0.7 and opp_active <= 1),
            weights.W_INT_DEFENSIVE_COLLAPSE),
        ("int_opp_da_pressure",
            b(opp_double_atk >= 1 and me_life <= 2),
            b(me_double_atk >= 1 and opp_life <= 2),
            weights.W_INT_OPP_DA_PRESSURE),
        # B. 攻めサイン (= 攻撃系) 5
        ("int_lethal_setup_ready",
            b(me_active >= 3 and me_don >= 5 and opp_blocker == 0),
            b(opp_active >= 3 and opp_don >= 5 and me_blocker == 0),
            weights.W_INT_LETHAL_SETUP_READY),
        ("int_aggressive_window_open",
            b(me_active >= opp_active_blocker + 2),
            b(opp_active >= me_active_blocker + 2),
            weights.W_INT_AGGRESSIVE_WINDOW_OPEN),
        ("int_burst_threshold",
            b(me_double_atk >= 1 and opp_life <= 3),
            b(opp_double_atk >= 1 and me_life <= 3),
            weights.W_INT_BURST_THRESHOLD),
        ("int_removal_window",
            b(me_removal >= 1 and opp_field_finisher >= 1),
            b(opp_removal >= 1 and self_field_finisher >= 1),
            weights.W_INT_REMOVAL_WINDOW),
        ("int_don_advantage_open",
            b(me_don > opp_don + 2),
            b(opp_don > me_don + 2),
            weights.W_INT_DON_ADVANTAGE_OPEN),
        # C. テンポ系 4
        ("int_on_curve",
            b(me_dead_in_hand == 0 and me.don_active >= turn - 1),
            b(opp_dead_in_hand == 0 and opp.don_active >= turn - 1),
            weights.W_INT_ON_CURVE),
        ("int_tempo_lost_critical",
            b(me.dons_unused_at_end_count >= 5),
            b(opp.dons_unused_at_end_count >= 5),
            weights.W_INT_TEMPO_LOST_CRITICAL),
        ("int_ramp_paying_off",
            b(me_don > turn and me_don >= 6),
            b(opp_don > turn and opp_don >= 6),
            weights.W_INT_RAMP_PAYING_OFF),
        ("int_mana_starved",
            b(me_dead_in_hand >= 3),
            b(opp_dead_in_hand >= 3),
            weights.W_INT_MANA_STARVED),
        # D. シナジー系 4
        ("int_synergy_threshold_3",
            b(me_synergy >= 3),
            b(opp_synergy >= 3),
            weights.W_INT_SYNERGY_THRESHOLD_3),
        ("int_trash_archetype_5",
            b(me_trash_arch >= 5),
            b(opp_trash_arch >= 5),
            weights.W_INT_TRASH_ARCHETYPE_5),
        ("int_stage_with_synergy",
            b(me_stage >= 1 and me_synergy >= 2),
            b(opp_stage >= 1 and opp_synergy >= 2),
            weights.W_INT_STAGE_WITH_SYNERGY),
        ("int_ramp_finisher_combo",
            b(me_don >= 7 and me_finisher_hand >= 1),
            b(opp_don >= 7 and opp_finisher_hand >= 1),
            weights.W_INT_RAMP_FINISHER_COMBO),
        # E. 隠匿/情報系 3
        ("int_opp_hidden_threat_high",
            b(self_threat >= 5 and opp_known_fin >= 1),
            b(opp_threat >= 5 and me_known_fin >= 1),
            weights.W_INT_OPP_HIDDEN_THREAT_HIGH),
        ("int_self_hand_quality_high",
            b(me_hand_q >= 6 and me_finisher_hand >= 1),
            b(opp_hand_q >= 6 and opp_finisher_hand >= 1),
            weights.W_INT_SELF_HAND_QUALITY_HIGH),
        ("int_opp_low_resource",
            b(opp_don <= 2 and opp_hand <= 3),
            b(me_don <= 2 and me_hand <= 3),
            weights.W_INT_OPP_LOW_RESOURCE),
        # F. ターン文脈系 3
        ("int_early_game_strong",
            b(turn <= 3 and len(me.characters) >= 2),
            b(turn <= 3 and len(opp.characters) >= 2),
            weights.W_INT_EARLY_GAME_STRONG),
        ("int_mid_game_pressure",
            b(4 <= turn <= 7 and self_lethal_v >= 0.3),
            b(4 <= turn <= 7 and opp_lethal_v >= 0.3),
            weights.W_INT_MID_GAME_PRESSURE),
        ("int_late_game_solver",
            b(turn >= 8 and me_don >= 7),
            b(turn >= 8 and opp_don >= 7),
            weights.W_INT_LATE_GAME_SOLVER),
        # G. KO 耐性 / blocker 系 2
        ("int_ko_immune_finisher",
            b(me_ko_immune >= 1 and me_finisher_hand >= 1),
            b(opp_ko_immune >= 1 and opp_finisher_hand >= 1),
            weights.W_INT_KO_IMMUNE_FINISHER),
        ("int_blocker_with_taunt",
            b(me_blocker >= 1 and me_taunt >= 1),
            b(opp_blocker >= 1 and opp_taunt >= 1),
            weights.W_INT_BLOCKER_WITH_TAUNT),
        # H. 特殊 4
        ("int_first_player_early_adv",
            b(me_is_first and turn <= 2 and len(me.characters) >= 1),
            b((not me_is_first) and turn <= 2 and len(opp.characters) >= 1),
            weights.W_INT_FIRST_PLAYER_EARLY_ADV),
        ("int_second_player_late_swing",
            b((not me_is_first) and turn >= 5 and me_don >= 6),
            b(me_is_first and turn >= 5 and opp_don >= 6),
            weights.W_INT_SECOND_PLAYER_LATE_SWING),
        ("int_exposed_finisher",
            b(me_chara_q >= 2 and me_field_exp >= 1),
            b(opp_chara_q >= 2 and opp_field_exp >= 1),
            weights.W_INT_EXPOSED_FINISHER),
        ("int_draw_advantage",
            b(me.cards_drawn_count >= opp.cards_drawn_count + 3),
            b(opp.cards_drawn_count >= me.cards_drawn_count + 3),
            weights.W_INT_DRAW_ADVANTAGE),
        # I. Plan Step 1: leader 固有効果 flag × state 条件 5 個
        # state.deck_flags[me_idx] / [opp_idx] から have_* flag を取得して binary cross。
        # me / opp の対称形。 default 0 で学習任せ。
    ]
    me_flags = getattr(state, "deck_flags", [{}, {}])[me_idx] if me_idx < 2 else {}
    opp_flags = getattr(state, "deck_flags", [{}, {}])[1 - me_idx] if (1 - me_idx) < 2 else {}
    metrics_flag = [
        ("int_have_ramp_low_don",
            b(me_flags.get("have_ramp", False) and me_don < 5),
            b(opp_flags.get("have_ramp", False) and opp_don < 5),
            weights.W_INT_HAVE_RAMP_LOW_DON),
        ("int_have_burst_finisher_late",
            b(me_flags.get("have_burst_finisher", False) and turn >= 6),
            b(opp_flags.get("have_burst_finisher", False) and turn >= 6),
            weights.W_INT_HAVE_BURST_FINISHER_LATE),
        ("int_have_search_loop_low_hand",
            b(me_flags.get("have_search_loop", False) and me_hand <= 3),
            b(opp_flags.get("have_search_loop", False) and opp_hand <= 3),
            weights.W_INT_HAVE_SEARCH_LOOP_LOW_HAND),
        ("int_have_removal_arsenal_opp_strong",
            b(me_flags.get("have_removal_arsenal", False) and opp_chara_q >= 3),
            b(opp_flags.get("have_removal_arsenal", False) and me_chara_q >= 3),
            weights.W_INT_HAVE_REMOVAL_ARSENAL_OPP_STRONG),
        ("int_have_draw_engine_low_hand",
            b(me_flags.get("have_draw_engine", False) and me_hand <= 3),
            b(opp_flags.get("have_draw_engine", False) and opp_hand <= 3),
            weights.W_INT_HAVE_DRAW_ENGINE_LOW_HAND),
    ]
    return metrics + metrics_flag


def opp_hand_threat_estimate(state: GameState, me_idx: int) -> float:
    """opp の手札脅威度を隠匿モデルで期待値推定 (R70 / Phase 3)。

    opp.hand は本来隠匿情報なので、 直接 hand 内容を見ない。 代わりに未公開プール
    (= opp.deck + opp.hand) の役割別平均価値を計算し、 hand 枚数倍で期待脅威を返す。

    高いほど me に不利 (= opp が finisher/removal を多く隠し持っている)。 AI が
    ハンド剥がし (trash_opp_hand_random) の価値判断に使う。

    me 視点の compute_breakdown では「opp 側のみ寄与」 = self は 0 で固定。
    """
    opp = state.players[1 - me_idx]
    hand_n = len(opp.hand)
    if hand_n == 0:
        return 0.0
    pool_n = len(opp.deck) + hand_n
    if pool_n == 0:
        return 0.0
    pool_total = 0.0
    for c in opp.deck:
        pool_total += _get_card_value(c.card_id)
    for c in opp.hand:
        pool_total += _get_card_value(c.card_id)
    return (pool_total / pool_n) * hand_n


def compute_breakdown(
    state: GameState,
    me_idx: int,
    weights: Optional[BoardEvalWeights] = None,
) -> dict:
    """各指標の内訳を返す。

    返り値構造 (14 指標):
      {
        "life": {"self": int, "opp": int, "diff": int, "contribution": int},
        "field_count": {...}, "field_power": {...}, "hand": {...},
        "don": {...}, "blocker": {...}, "attached_don": {...},
        "active_chara": {...}, "lethal": {...},
        # Phase 1 (R68):
        "next_turn_lethal": {...}, # 全 chara REFRESH 想定の lethal (= 被リーサル含む)
        "deck_finisher": {...},    # 残デッキ内 finisher 数
        "life_trigger": {...},     # ライフ内 trigger 価値
        # Phase 2 (R69):
        "chara_quality": {...},    # 場の キャラの role 別合計価値
        "hand_quality": {...},     # 手札の role 別合計価値
      }
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]
    sm = _player_metrics(me)
    om = _player_metrics(opp)

    self_lethal = lethal_estimate(state, me_idx)
    opp_lethal = lethal_estimate(state, 1 - me_idx)

    # Phase 1 新規メトリック (R68)
    # next_turn_lethal: 「次の opp ターンまでに REFRESH 状態で全 chara 攻撃すると lethal か」
    # me 視点で sv = 自分が opp を仕留めるリスク、 ov = opp が自分を仕留めるリスク
    # diff = sv - ov > 0 で me が threat 優位 (= 被リーサル < 攻めリーサル)
    me_forward_lethal = project_opp_next_turn_lethal(state, 1 - me_idx)
    opp_forward_lethal = project_opp_next_turn_lethal(state, me_idx)
    self_deck_finisher = deck_finisher_count(me)
    opp_deck_finisher = deck_finisher_count(opp)
    overlay = state.effects_overlay
    self_life_trig = life_trigger_value(me, overlay)
    opp_life_trig = life_trigger_value(opp, overlay)

    # Phase 2 新規メトリック (R69)
    self_chara_q = chara_quality_score(me)
    opp_chara_q = chara_quality_score(opp)
    self_hand_q = hand_quality_score(me)
    opp_hand_q = hand_quality_score(opp)

    # Phase 3 新規メトリック (R70): 相手手札の隠匿脅威
    # self_score - opp_score 形式の整合性を保つため、 me 視点では「opp の脅威」 を
    # opp 側に置く (= self=0)。 me 視点では「自分の手札脅威」 を計算する必要はない
    # (= 既に hand_quality で扱う = 公開情報想定)。 ただし AI は両側のスコアを比較
    # するので、 対称性のため me_idx 視点で「opp の脅威」 を計算 = opp.hand の隠匿推定。
    opp_hand_threat = opp_hand_threat_estimate(state, me_idx)
    self_hand_threat = opp_hand_threat_estimate(state, 1 - me_idx)  # 対称: opp 視点での 自分

    # Step 2-pre (R72+): 24 新規指標。 me/opp 対称で計算 (= self - opp で diff)。
    # is_first_player / is_my_turn / turn_number_normalized は 直接 state から導出。
    me_is_first = 1 if me_idx == 0 else 0
    opp_is_first = 1 if (1 - me_idx) == 0 else 0
    me_is_turn = 1 if state.turn_player_idx == me_idx else 0
    opp_is_turn = 1 if state.turn_player_idx == (1 - me_idx) else 0
    turn_norm = state.turn_number / 10.0

    metrics = [
        ("life", sm["life"], om["life"], weights.W_LIFE),
        ("field_count", sm["field_count"], om["field_count"], weights.W_FIELD_COUNT),
        ("field_power", sm["field_power"], om["field_power"], weights.W_FIELD_POWER),
        ("hand", sm["hand"], om["hand"], weights.W_HAND),
        ("don", sm["don"], om["don"], weights.W_DON),
        ("blocker", sm["blocker"], om["blocker"], weights.W_BLOCKER),
        ("attached_don", sm["attached_don"], om["attached_don"], weights.W_ATTACHED_DON),
        ("active_chara", sm["active_chara"], om["active_chara"], weights.W_ACTIVE_CHARA),
        ("lethal", self_lethal, opp_lethal, weights.W_LETHAL),
        ("next_turn_lethal", me_forward_lethal, opp_forward_lethal, weights.W_OPP_NEXT_LETHAL),
        ("deck_finisher", self_deck_finisher, opp_deck_finisher, weights.W_DECK_FINISHER),
        ("life_trigger", self_life_trig, opp_life_trig, weights.W_LIFE_TRIGGER),
        ("chara_quality", self_chara_q, opp_chara_q, weights.W_CHARA_QUALITY),
        ("hand_quality", self_hand_q, opp_hand_q, weights.W_HAND_QUALITY),
        ("opp_hand_threat", self_hand_threat, opp_hand_threat, weights.W_OPP_HAND_THREAT),
        # Step 2-pre 計画書 10
        ("is_first_player", me_is_first, opp_is_first, weights.W_IS_FIRST_PLAYER),
        ("stage_count", stage_count(me), stage_count(opp), weights.W_STAGE_COUNT),
        ("stage_value", stage_value(me), stage_value(opp), weights.W_STAGE_VALUE),
        ("trash_count", trash_count(me), trash_count(opp), weights.W_TRASH_COUNT),
        ("trash_archetype_match", trash_archetype_match(me), trash_archetype_match(opp), weights.W_TRASH_ARCHETYPE_MATCH),
        ("rush_count", rush_count(me), rush_count(opp), weights.W_RUSH_COUNT),
        ("double_attack_count", double_attack_count(me), double_attack_count(opp), weights.W_DOUBLE_ATTACK_COUNT),
        ("static_cost_reduction_total", static_cost_reduction_total(me), static_cost_reduction_total(opp), weights.W_STATIC_COST_REDUCTION_TOTAL),
        ("playable_cost_match", playable_cost_match(me), playable_cost_match(opp), weights.W_PLAYABLE_COST_MATCH),
        ("synergy_count", synergy_count(me), synergy_count(opp), weights.W_SYNERGY_COUNT),
        # Step 2-pre 即追加 9
        ("is_my_turn", me_is_turn, opp_is_turn, weights.W_IS_MY_TURN),
        ("turn_number_normalized", turn_norm, 0.0, weights.W_TURN_NUMBER_NORMALIZED),
        ("dead_card_in_hand", dead_card_in_hand(me), dead_card_in_hand(opp), weights.W_DEAD_CARD_IN_HAND),
        ("active_blocker_count", active_blocker_count(me), active_blocker_count(opp), weights.W_OPP_ACTIVE_BLOCKER_COUNT),
        ("removal_threat_count", removal_threat_count(me), removal_threat_count(opp), weights.W_REMOVAL_THREAT_COUNT),
        ("self_counter_in_hand_total", self_counter_in_hand_total(me), self_counter_in_hand_total(opp), weights.W_SELF_COUNTER_IN_HAND_TOTAL),
        ("finisher_in_hand_count", finisher_in_hand_count(me), finisher_in_hand_count(opp), weights.W_FINISHER_IN_HAND_COUNT),
        ("keyword_taunt_count", keyword_taunt_count(me), keyword_taunt_count(opp), weights.W_KEYWORD_TAUNT_COUNT),
        ("ko_immune_count", ko_immune_count(me), ko_immune_count(opp), weights.W_KO_IMMUNE_COUNT),
        # Step 2-pre state 拡張 5
        ("cards_drawn_total", me.cards_drawn_count, opp.cards_drawn_count, weights.W_CARDS_DRAWN_TOTAL),
        ("cards_played_total", me.cards_played_count, opp.cards_played_count, weights.W_CARDS_PLAYED_TOTAL),
        ("dons_used_total", me.dons_used_count, opp.dons_used_count, weights.W_DONS_USED_TOTAL),
        ("tempo_lost_total", me.dons_unused_at_end_count, opp.dons_unused_at_end_count, weights.W_TEMPO_LOST_TOTAL),
        ("known_finisher_count_in_hand", opp_known_finisher_count(me), opp_known_finisher_count(opp), weights.W_OPP_KNOWN_FINISHER_COUNT),
        # Step 2A (= 計画書 Phase 2A 由来 4 個)
        ("don_reserve", don_reserve(me), don_reserve(opp), weights.W_DON_RESERVE),
        ("field_exposure", field_exposure(me, opp), field_exposure(opp, me), weights.W_FIELD_EXPOSURE),
        ("hand_log", hand_log(me), hand_log(opp), weights.W_HAND_LOG),
        ("lethal_risk_diff", lethal_risk_diff(state, me_idx), -lethal_risk_diff(state, me_idx), weights.W_LETHAL_RISK_DIFF),
    ]
    # Iter2: interaction 30 個を末尾追加
    metrics.extend(_compute_interactions(
        state, me_idx, me, opp, sm, om, self_lethal, opp_lethal, weights,
    ))
    out = {}
    for name, sv, ov, w in metrics:
        diff = sv - ov
        out[name] = {
            "self": sv,
            "opp": ov,
            "diff": diff,
            "contribution": diff * w,
        }
    return out


def compute_score(
    state: GameState,
    me_idx: int,
    weights: Optional[BoardEvalWeights] = None,
) -> float:
    """me_idx 視点の盤面スコア (= self_score - opp_score)。

    ゲーム終了時は ±W_GAME_OVER で確定値。 それ以外は 73 指標の重み付き差分合計。

    R72+ 最適化: dim group 単位で 「全重み 0」 なら計算 skip (= plan_search の leaf eval
    で重い helper を毎回呼ぶ overhead を回避)。 学習で重みが付いた group だけ計算する
    適応的設計。 学習前 (= 全 dim 重み 0) は base 8 dim 速度で動作。
    snapshot 用 full 73 dim は compute_breakdown を引き続き使う。
    """
    # === Plan Step 3: NN backend (= model file 存在で auto 有効化) ===
    # ONEPIECE_NN_DISABLE 環境変数で 強制 fallback (= 線形)。
    # 明示的に weights が渡された場合 (= 学習 / テスト / 重み比較) は NN を bypass
    # して線形評価する (= NN は重みを受け取らないため weights 比較が無意味になる)。
    #
    # blend mode (= 2026-05-17):
    #   ONEPIECE_NN_BLEND=0.0   → 線形 100% (= 既存挙動)
    #   ONEPIECE_NN_BLEND=1.0   → NN 100% (= 既存 NN 路線、 default)
    #   ONEPIECE_NN_BLEND=0.3   → 線形 70% + NN 30% (= 線形主体、 NN 補助)
    import os
    if weights is None and not os.environ.get("ONEPIECE_NN_DISABLE"):
        try:
            from .nn_eval import compute_score_nn
            nn_score = compute_score_nn(state, me_idx)
            if nn_score is not None:
                # game_over 時は決定値で上書き (= NN 推定より正確)
                if state.game_over:
                    if state.winner == me_idx:
                        return float(DEFAULT_WEIGHTS.W_GAME_OVER)
                    elif state.winner is not None:
                        return float(-DEFAULT_WEIGHTS.W_GAME_OVER)
                    return 0.0
                blend = float(os.environ.get("ONEPIECE_NN_BLEND", "1.0"))
                # Phase Y (= 2026-05-17 案 Y): phase-aware adaptive blend
                # ライフ ≤ threshold or リーサル ライン に近いと判定された state では
                # 線形 eval 主体 (= W_LETHAL の決定力)、 それ以外は NN 主体。
                # ONEPIECE_NN_PHASE_AWARE=1 で有効化。
                if os.environ.get("ONEPIECE_NN_PHASE_AWARE") == "1":
                    me_player = state.players[me_idx]
                    opp_player = state.players[1 - me_idx]
                    life_threshold = int(os.environ.get("ONEPIECE_NN_PHASE_LIFE_THRESHOLD", "2"))
                    is_critical = (
                        len(me_player.life) <= life_threshold
                        or len(opp_player.life) <= life_threshold
                    )
                    if is_critical:
                        # critical state: 線形 eval 主体 (= blend を 0.1 に強制 = 線形 90%)
                        blend = float(os.environ.get("ONEPIECE_NN_PHASE_CRITICAL_BLEND", "0.1"))
                    else:
                        # 通常時: NN 主体 (= blend を 1.0 に強制 = NN 100%)
                        blend = float(os.environ.get("ONEPIECE_NN_PHASE_NORMAL_BLEND", "1.0"))
                if blend >= 1.0:
                    return nn_score
                # blend < 1.0: 線形評価も計算して mix
                # NN を一時 disable して compute_score 再帰呼び出し (= 線形 path に流す)
                saved = os.environ.get("ONEPIECE_NN_DISABLE")
                os.environ["ONEPIECE_NN_DISABLE"] = "1"
                try:
                    linear_score = compute_score(state, me_idx, weights=None)
                finally:
                    if saved is None:
                        del os.environ["ONEPIECE_NN_DISABLE"]
                    else:
                        os.environ["ONEPIECE_NN_DISABLE"] = saved
                return blend * nn_score + (1.0 - blend) * linear_score
        except Exception:
            pass  # NN 失敗時は線形 fallback

    if weights is None:
        # archetype 別 重みを自動選択 (= state.archetypes[me_idx] 経由)。
        # 該当 archetype の ai_params_archetypes/<slug>.json があればそれ、 無ければ base。
        weights = select_weights_for_player(state, me_idx)
    if state.game_over:
        if state.winner == me_idx:
            return float(weights.W_GAME_OVER)
        elif state.winner is not None:
            return float(-weights.W_GAME_OVER)
        return 0.0  # 引き分け

    me = state.players[me_idx]
    opp = state.players[1 - me_idx]
    sm = _player_metrics(me)
    om = _player_metrics(opp)

    # === 動的重み関数 v2 (= 2026-05-18 OPTCG メカニクス対応拡張版) ===
    # ライフ受ける → 手札 +1 という公式ルールを評価に反映。
    # 状態依存で W_LIFE / W_HAND / W_DON / W_BLOCKER 等を動的計算 (= 関数化)。
    # ONEPIECE_DYNAMIC_WEIGHTS=1 で有効化、 default は固定重み (= 後方互換)。
    # ONEPIECE_WEIGHT_NN=1 で重み NN (= Plan F) を使う、 dynamic_v2 教師として fallback。
    # Plan D (= 2026-05-18 AlphaZero 風 value NN) 統合 path
    # ONEPIECE_AZ_VALUE_NN=1 で有効化、 plan_search の leaf eval で「真の P(win) ベース score」 を返す。
    # 既存 NN value 経路 (= v1-v5) は線形 fallback、 Plan D は別 NN (= value_nn_alphazero.pt)。
    if os.environ.get("ONEPIECE_AZ_VALUE_NN") == "1":
        try:
            from .value_nn_alphazero import compute_value_az
            az_score = compute_value_az(state, me_idx)
            if az_score is not None:
                if state.game_over:
                    if state.winner == me_idx:
                        return float(DEFAULT_WEIGHTS.W_GAME_OVER)
                    elif state.winner is not None:
                        return float(-DEFAULT_WEIGHTS.W_GAME_OVER)
                    return 0.0
                return az_score
        except Exception:
            pass  # fallback

    _use_weight_nn = os.environ.get("ONEPIECE_WEIGHT_NN") == "1"
    _use_dynamic = os.environ.get("ONEPIECE_DYNAMIC_WEIGHTS") == "1" or _use_weight_nn
    if _use_weight_nn:
        try:
            from .weight_nn import compute_weights_nn
            nn_weights = compute_weights_nn(state, me_idx)
            if nn_weights is not None:
                # NN 出力 weights を そのまま使う (= 動的計算 path は skip)
                score = (
                    (sm["life"] - om["life"]) * nn_weights["W_LIFE"]
                    + (sm["field_count"] - om["field_count"]) * nn_weights["W_FIELD_COUNT"]
                    + (sm["field_power"] - om["field_power"]) * nn_weights["W_FIELD_POWER"]
                    + (sm["hand"] - om["hand"]) * nn_weights["W_HAND"]
                    + (sm["don"] - om["don"]) * nn_weights["W_DON"]
                    + (sm["blocker"] - om["blocker"]) * nn_weights["W_BLOCKER"]
                    + (sm["attached_don"] - om["attached_don"]) * nn_weights["W_ATTACHED_DON"]
                    + (sm["active_chara"] - om["active_chara"]) * nn_weights["W_ACTIVE_CHARA"]
                )
                # NN 出力 W_LETHAL は別途 lethal_estimate 後に使うため、 一旦記録
                _nn_w_lethal = nn_weights["W_LETHAL"]
                _use_dynamic = False  # NN path 採用、 dynamic v2 計算は skip
        except Exception:
            pass  # NN 失敗時は dynamic v2 fallback
    if _use_dynamic:
        my_life = sm["life"]
        opp_life = om["life"]
        my_hand = sm["hand"]
        opp_hand = om["hand"]
        turn = state.turn_number
        my_field_power = sm["field_power"]
        opp_field_power = om["field_power"]

        # ----- 1. ライフ重み (= 残ライフが少ないほど重い、 ターン後半でも重い) -----
        # cross-term: ライフ × ターン (= 終盤のライフは価値増)
        turn_factor = 1.0 + max(0, turn - 5) * 0.15  # turn 5+ で 1.15, 10 で 1.75
        if my_life >= 4:
            w_life_self = weights.W_LIFE * 0.5 * turn_factor
        elif my_life >= 2:
            w_life_self = weights.W_LIFE * 1.0 * turn_factor
        else:
            w_life_self = weights.W_LIFE * 2.5 * turn_factor

        if opp_life >= 4:
            w_life_opp = weights.W_LIFE * 0.7 * turn_factor
        elif opp_life >= 2:
            w_life_opp = weights.W_LIFE * 1.2 * turn_factor
        else:
            w_life_opp = weights.W_LIFE * 2.5 * turn_factor  # 相手ライフ 1 でリーサル目前

        # ----- 2. 手札重み (= 手札枯渇時は補充価値高、 余ってる時は低) -----
        if my_hand <= 2:
            w_hand_self = weights.W_HAND * 2.5  # 枯渇時、 補充価値最大
        elif my_hand <= 5:
            w_hand_self = weights.W_HAND * 1.0
        else:
            w_hand_self = weights.W_HAND * 0.4  # 余ってる、 増の価値低い

        if opp_hand <= 2:
            w_hand_opp = weights.W_HAND * 1.5  # 相手も枯渇、 こちらの攻撃通過確率高い
        elif opp_hand <= 5:
            w_hand_opp = weights.W_HAND * 1.0
        else:
            w_hand_opp = weights.W_HAND * 0.6

        # ----- 3. ドン重み (= 一律低く、 OPTCG では「温存」 という概念がそもそもない) -----
        # OPTCG では DON 余らせ = 純損失。 ターン跨ぎでも 1 ドンしか持ち越せない、
        # 当ターン使う > 次ターン使う が常に有利 (= 同じリソース + 追加のいまターン分)。
        # → 「動的に温存重み調整」 は不要、 一律低く して「使い切れ」 を engine に教える。
        w_don = weights.W_DON * 0.4  # 全ターン同じ、 ドン差はあまり評価しない (= 攻撃に振る)

        # ----- 4. ブロッカー重み (= 相手フィールド強なら防御価値高) -----
        # 相手キャラ強いほど blocker 重要
        opp_field_strength_factor = 1.0
        if opp_field_power >= 15000:
            opp_field_strength_factor = 1.5
        elif opp_field_power >= 8000:
            opp_field_strength_factor = 1.2
        w_blocker = weights.W_BLOCKER * opp_field_strength_factor

        # ----- 5. attached_don / active_chara / field_count / field_power は固定 -----
        # （後段 Group 2-N で extra term は固定 weights で続行）

        # ----- 動的 base 8 dim score 計算 -----
        score = (
            sm["life"] * w_life_self - opp_life * w_life_opp
            + my_hand * w_hand_self - opp_hand * w_hand_opp
            + (sm["field_count"] - om["field_count"]) * weights.W_FIELD_COUNT
            + (sm["field_power"] - om["field_power"]) * weights.W_FIELD_POWER
            + (sm["don"] - om["don"]) * w_don
            + (sm["blocker"] - om["blocker"]) * w_blocker
            + (sm["attached_don"] - om["attached_don"]) * weights.W_ATTACHED_DON
            + (sm["active_chara"] - om["active_chara"]) * weights.W_ACTIVE_CHARA
        )
    else:
        # === Group 1: base 軽い 8 dim (= guard なしで毎回計算、 cost 低) ===
        score = (
            (sm["life"] - om["life"]) * weights.W_LIFE
            + (sm["field_count"] - om["field_count"]) * weights.W_FIELD_COUNT
            + (sm["field_power"] - om["field_power"]) * weights.W_FIELD_POWER
            + (sm["hand"] - om["hand"]) * weights.W_HAND
            + (sm["don"] - om["don"]) * weights.W_DON
            + (sm["blocker"] - om["blocker"]) * weights.W_BLOCKER
            + (sm["attached_don"] - om["attached_don"]) * weights.W_ATTACHED_DON
            + (sm["active_chara"] - om["active_chara"]) * weights.W_ACTIVE_CHARA
        )

    # === Group 2: lethal 系 (= 重い hand_estimator 呼び出しあり) ===
    self_lethal = 0.0
    opp_lethal = 0.0
    needs_lethal = (
        weights.W_LETHAL != 0
        or weights.W_LETHAL_RISK_DIFF != 0
        or weights.W_INT_OPP_LETHAL_NO_COUNTER != 0
        or weights.W_INT_DEFENSIVE_COLLAPSE != 0
        or weights.W_INT_MID_GAME_PRESSURE != 0
    )
    if needs_lethal:
        self_lethal = lethal_estimate(state, me_idx)
        opp_lethal = lethal_estimate(state, 1 - me_idx)
        score += (self_lethal - opp_lethal) * weights.W_LETHAL

    if weights.W_OPP_NEXT_LETHAL != 0:
        me_forward = project_opp_next_turn_lethal(state, 1 - me_idx)
        opp_forward = project_opp_next_turn_lethal(state, me_idx)
        # v2 強化 (= 2026-05-28、 ONEPIECE_GOAL_STRONG=1): self life ≤ 1 で 被 lethal 重み ×1.3。
        # opp 攻撃 受け 拒否 判断 強化 (= counter / blocker 使い 切る 方向)。
        # 過剰 boost は AI 行動 を 歪める ので 控えめ。
        w_next_lethal = float(weights.W_OPP_NEXT_LETHAL)
        if os.environ.get("ONEPIECE_GOAL_STRONG") == "1":
            if len(me.life) <= 1:
                w_next_lethal *= 1.3
        score += (me_forward - opp_forward) * w_next_lethal

    # === Group 3: deck_finisher (= role_db 経由で deck 走査) ===
    if weights.W_DECK_FINISHER != 0:
        score += (deck_finisher_count(me) - deck_finisher_count(opp)) * weights.W_DECK_FINISHER

    # === Group 4: life_trigger (= overlay 走査) ===
    if weights.W_LIFE_TRIGGER != 0:
        overlay = state.effects_overlay
        score += (life_trigger_value(me, overlay) - life_trigger_value(opp, overlay)) * weights.W_LIFE_TRIGGER

    # === Group 5: chara/hand quality (= role_db lookup) ===
    if weights.W_CHARA_QUALITY != 0:
        score += (chara_quality_score(me) - chara_quality_score(opp)) * weights.W_CHARA_QUALITY
    if weights.W_HAND_QUALITY != 0:
        score += (hand_quality_score(me) - hand_quality_score(opp)) * weights.W_HAND_QUALITY

    # === Group 6: opp_hand_threat (= 重い: 50 枚走査) ===
    if weights.W_OPP_HAND_THREAT != 0:
        s_threat = opp_hand_threat_estimate(state, 1 - me_idx)
        o_threat = opp_hand_threat_estimate(state, me_idx)
        score += (s_threat - o_threat) * weights.W_OPP_HAND_THREAT

    # === Group 7: Step 2-pre 計画書 10 ===
    has_step2pre = (
        weights.W_IS_FIRST_PLAYER != 0 or weights.W_STAGE_COUNT != 0
        or weights.W_STAGE_VALUE != 0 or weights.W_TRASH_COUNT != 0
        or weights.W_TRASH_ARCHETYPE_MATCH != 0 or weights.W_RUSH_COUNT != 0
        or weights.W_DOUBLE_ATTACK_COUNT != 0
        or weights.W_STATIC_COST_REDUCTION_TOTAL != 0
        or weights.W_PLAYABLE_COST_MATCH != 0 or weights.W_SYNERGY_COUNT != 0
    )
    if has_step2pre:
        me_is_first = 1 if me_idx == 0 else 0
        opp_is_first = 1 if (1 - me_idx) == 0 else 0
        score += (me_is_first - opp_is_first) * weights.W_IS_FIRST_PLAYER
        score += (stage_count(me) - stage_count(opp)) * weights.W_STAGE_COUNT
        score += (stage_value(me) - stage_value(opp)) * weights.W_STAGE_VALUE
        score += (trash_count(me) - trash_count(opp)) * weights.W_TRASH_COUNT
        score += (trash_archetype_match(me) - trash_archetype_match(opp)) * weights.W_TRASH_ARCHETYPE_MATCH
        score += (rush_count(me) - rush_count(opp)) * weights.W_RUSH_COUNT
        score += (double_attack_count(me) - double_attack_count(opp)) * weights.W_DOUBLE_ATTACK_COUNT
        score += (static_cost_reduction_total(me) - static_cost_reduction_total(opp)) * weights.W_STATIC_COST_REDUCTION_TOTAL
        score += (playable_cost_match(me) - playable_cost_match(opp)) * weights.W_PLAYABLE_COST_MATCH
        score += (synergy_count(me) - synergy_count(opp)) * weights.W_SYNERGY_COUNT

    # === Group 8: Step 2-pre 即追加 9 ===
    has_step2pre_add = (
        weights.W_IS_MY_TURN != 0 or weights.W_TURN_NUMBER_NORMALIZED != 0
        or weights.W_DEAD_CARD_IN_HAND != 0
        or weights.W_OPP_ACTIVE_BLOCKER_COUNT != 0
        or weights.W_REMOVAL_THREAT_COUNT != 0
        or weights.W_SELF_COUNTER_IN_HAND_TOTAL != 0
        or weights.W_FINISHER_IN_HAND_COUNT != 0
        or weights.W_KEYWORD_TAUNT_COUNT != 0
        or weights.W_KO_IMMUNE_COUNT != 0
    )
    if has_step2pre_add:
        me_is_turn = 1 if state.turn_player_idx == me_idx else 0
        opp_is_turn = 1 if state.turn_player_idx == (1 - me_idx) else 0
        score += (me_is_turn - opp_is_turn) * weights.W_IS_MY_TURN
        score += (state.turn_number / 10.0) * weights.W_TURN_NUMBER_NORMALIZED
        score += (dead_card_in_hand(me) - dead_card_in_hand(opp)) * weights.W_DEAD_CARD_IN_HAND
        score += (active_blocker_count(me) - active_blocker_count(opp)) * weights.W_OPP_ACTIVE_BLOCKER_COUNT
        score += (removal_threat_count(me) - removal_threat_count(opp)) * weights.W_REMOVAL_THREAT_COUNT
        score += (self_counter_in_hand_total(me) - self_counter_in_hand_total(opp)) * weights.W_SELF_COUNTER_IN_HAND_TOTAL
        score += (finisher_in_hand_count(me) - finisher_in_hand_count(opp)) * weights.W_FINISHER_IN_HAND_COUNT
        score += (keyword_taunt_count(me) - keyword_taunt_count(opp)) * weights.W_KEYWORD_TAUNT_COUNT
        score += (ko_immune_count(me) - ko_immune_count(opp)) * weights.W_KO_IMMUNE_COUNT

    # === Group 9: state 拡張 5 (= 軽い、 直接 attribute 参照) ===
    has_state_ext = (
        weights.W_CARDS_DRAWN_TOTAL != 0 or weights.W_CARDS_PLAYED_TOTAL != 0
        or weights.W_DONS_USED_TOTAL != 0 or weights.W_TEMPO_LOST_TOTAL != 0
        or weights.W_OPP_KNOWN_FINISHER_COUNT != 0
    )
    if has_state_ext:
        score += (me.cards_drawn_count - opp.cards_drawn_count) * weights.W_CARDS_DRAWN_TOTAL
        score += (me.cards_played_count - opp.cards_played_count) * weights.W_CARDS_PLAYED_TOTAL
        score += (me.dons_used_count - opp.dons_used_count) * weights.W_DONS_USED_TOTAL
        score += (me.dons_unused_at_end_count - opp.dons_unused_at_end_count) * weights.W_TEMPO_LOST_TOTAL
        score += (opp_known_finisher_count(me) - opp_known_finisher_count(opp)) * weights.W_OPP_KNOWN_FINISHER_COUNT

    # === Group 10: Step 2A 4 ===
    if weights.W_DON_RESERVE != 0:
        score += (don_reserve(me) - don_reserve(opp)) * weights.W_DON_RESERVE
    if weights.W_FIELD_EXPOSURE != 0:
        score += (field_exposure(me, opp) - field_exposure(opp, me)) * weights.W_FIELD_EXPOSURE
    if weights.W_HAND_LOG != 0:
        score += (hand_log(me) - hand_log(opp)) * weights.W_HAND_LOG
    if weights.W_LETHAL_RISK_DIFF != 0:
        # lethal_risk_diff は内部で lethal_estimate を呼ぶが、 needs_lethal で計算済なら再利用
        lrd = lethal_risk_diff(state, me_idx)
        score += (lrd - (-lrd)) * weights.W_LETHAL_RISK_DIFF

    # === Group 11: Iter2 interaction 30 (= 重い: helper 多数) ===
    has_int = (
        weights.W_INT_LOW_LIFE_LOW_HAND != 0 or weights.W_INT_LOW_LIFE_NO_BLOCKER != 0
        or weights.W_INT_OPP_LETHAL_NO_COUNTER != 0 or weights.W_INT_DEFENSIVE_COLLAPSE != 0
        or weights.W_INT_OPP_DA_PRESSURE != 0 or weights.W_INT_LETHAL_SETUP_READY != 0
        or weights.W_INT_AGGRESSIVE_WINDOW_OPEN != 0 or weights.W_INT_BURST_THRESHOLD != 0
        or weights.W_INT_REMOVAL_WINDOW != 0 or weights.W_INT_DON_ADVANTAGE_OPEN != 0
        or weights.W_INT_ON_CURVE != 0 or weights.W_INT_TEMPO_LOST_CRITICAL != 0
        or weights.W_INT_RAMP_PAYING_OFF != 0 or weights.W_INT_MANA_STARVED != 0
        or weights.W_INT_SYNERGY_THRESHOLD_3 != 0 or weights.W_INT_TRASH_ARCHETYPE_5 != 0
        or weights.W_INT_STAGE_WITH_SYNERGY != 0 or weights.W_INT_RAMP_FINISHER_COMBO != 0
        or weights.W_INT_OPP_HIDDEN_THREAT_HIGH != 0
        or weights.W_INT_SELF_HAND_QUALITY_HIGH != 0
        or weights.W_INT_OPP_LOW_RESOURCE != 0 or weights.W_INT_EARLY_GAME_STRONG != 0
        or weights.W_INT_MID_GAME_PRESSURE != 0 or weights.W_INT_LATE_GAME_SOLVER != 0
        or weights.W_INT_KO_IMMUNE_FINISHER != 0 or weights.W_INT_BLOCKER_WITH_TAUNT != 0
        or weights.W_INT_FIRST_PLAYER_EARLY_ADV != 0
        or weights.W_INT_SECOND_PLAYER_LATE_SWING != 0
        or weights.W_INT_EXPOSED_FINISHER != 0 or weights.W_INT_DRAW_ADVANTAGE != 0
    )
    if has_int:
        # lethal が必要だがまだ計算してない場合
        if not needs_lethal:
            self_lethal = lethal_estimate(state, me_idx)
            opp_lethal = lethal_estimate(state, 1 - me_idx)
        for _name, sv, ov, w in _compute_interactions(
            state, me_idx, me, opp, sm, om, self_lethal, opp_lethal, weights,
        ):
            score += (sv - ov) * w

    # ===== コンボ可能性 dim (= 2026-05-18 ユーザ「event 後のコンボ判断」 対応) =====
    # ONEPIECE_COMBO_DIM=1 で有効化、 default OFF (= 後方互換)。
    # 自分の active キャラの最大攻撃力 (= power + DON 付与可能数 × 1000) で
    # 相手キャラを KO 可能数を count → bonus / penalty。
    # event 後の state で「-1000 した相手キャラを 5000 攻撃で KO 可能」 等を 自然に score 化。
    if os.environ.get("ONEPIECE_COMBO_DIM") == "1":
        try:
            # 自分の active キャラの max attack (= 簡略: power + 残 DON × 1000、 1 体に集中想定)
            me_don_remaining = sum(1 for d in me.don_active if d == 0) if hasattr(me, "don_active") else len([d for d in getattr(me, "dons", []) if not d.attached])
            # actual cost-payable DON 数を取るのは難しい、 簡略 me.don_active を見る
            try:
                me_don_available = len([d for d in me.don_active if d == 0])
            except Exception:
                me_don_available = 0
            active_charas_power = [c.power for c in me.characters if not c.rested]
            if active_charas_power:
                max_attack = max(active_charas_power) + me_don_available * 1000
            else:
                max_attack = 0

            # 相手キャラ KO 可能数
            opp_chara_powers = [c.power for c in opp.characters]
            ko_possible = sum(1 for p in opp_chara_powers if max_attack >= p)

            # bonus: KO 可能 1 体ごと +500pt
            score += ko_possible * 500

            # leader 攻撃可能性: 自分 max_attack ≥ opp.leader.power → +bonus
            try:
                if max_attack >= opp.leader.power:
                    score += 800
            except Exception:
                pass
        except Exception:
            pass  # eval は止めない

    # ===== EndPhase penalty (= 2026-05-18 bad_moves 対応) =====
    # 自分のターン終了直後 (= state.turn_player_idx が opp に切替) で 未消費リソースあれば penalty。
    # plan_search の leaf state は ターン終了後を想定、 「使い切れなかった」 を score で抑制 →
    # AI が active chara / DON / leader 未使用で EndPhase を選ばないよう自然誘導。
    # ONEPIECE_END_PHASE_PENALTY=1 で有効化、 default OFF (= 後方互換)。
    if os.environ.get("ONEPIECE_END_PHASE_PENALTY") == "1":
        if state.turn_player_idx != me_idx and not state.game_over:
            # 自分のターン終了済 (= opp ターン中)、 未消費リソースあるか確認
            don_active_remaining = len([d for d in me.don_active if d == 0]) if hasattr(me, "don_active") else 0
            active_chara_count = sum(1 for c in me.characters if not c.rested)
            leader_unrested = not me.leader.rested
            # 各 penalty
            waste_penalty = 0
            waste_penalty += don_active_remaining * 500       # 余り DON 1 = -500pt
            waste_penalty += active_chara_count * 300         # 未使用 active chara 1 = -300pt
            if leader_unrested:
                waste_penalty += 400                          # leader 未攻撃 = -400pt
            score -= waste_penalty

    return score


def compute_self_opp_scores(
    state: GameState,
    me_idx: int,
    weights: Optional[BoardEvalWeights] = None,
) -> tuple[float, float]:
    """self_score, opp_score を別個に返す (UI / analyzer の表示用)。"""
    if weights is None:
        weights = DEFAULT_WEIGHTS
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]
    sm = _player_metrics(me)
    om = _player_metrics(opp)
    self_lethal = lethal_estimate(state, me_idx)
    opp_lethal = lethal_estimate(state, 1 - me_idx)
    w = weights

    def sum_side(m: dict, lethal: float) -> float:
        return (
            m["life"] * w.W_LIFE
            + m["field_count"] * w.W_FIELD_COUNT
            + m["field_power"] * w.W_FIELD_POWER
            + m["hand"] * w.W_HAND
            + m["don"] * w.W_DON
            + m["blocker"] * w.W_BLOCKER
            + m["attached_don"] * w.W_ATTACHED_DON
            + m["active_chara"] * w.W_ACTIVE_CHARA
            + lethal * w.W_LETHAL
        )

    return sum_side(sm, self_lethal), sum_side(om, opp_lethal)


def normalized_score(score: float, scale: float = 5000.0) -> float:
    """生スコアを -1.0 〜 +1.0 に正規化。 boardEval.ts と同 (tanh)。"""
    return math.tanh(score / scale)
