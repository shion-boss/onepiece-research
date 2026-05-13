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
        )
    except Exception:
        return BoardEvalWeights()


DEFAULT_WEIGHTS = _load_weights_from_ai_params()


def reload_default_weights() -> BoardEvalWeights:
    """学習で db/ai_params.json が更新された後、 メモリ上の DEFAULT_WEIGHTS を再ロード。"""
    global DEFAULT_WEIGHTS
    DEFAULT_WEIGHTS = _load_weights_from_ai_params()
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
        if not c.rested and not c.summoning_sickness
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
    """リーサル可能性を 0.0〜1.0 で返す。 boardEval.ts と同公式。

    me の「次ターン総打点」(active leader + active chars) と opp の防御力
    (life × 5000 + 期待カウンター総量) を比較し、 sigmoid でスケール。

    期待カウンター総量は `hand_estimator.expected_counter_total` で算出:
    opp.deck + opp.hand プール上の平均カウンター値 × 手札枚数。
    トラッシュ済カウンター持ちは自動的に除外される。
    """
    self_p = state.players[me_idx]
    opp_p = state.players[1 - me_idx]
    attackers: list[int] = []
    if not self_p.leader.rested:
        attackers.append(self_p.leader.power)
    for c in self_p.characters:
        if not c.rested and not c.summoning_sickness:
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


def chara_quality_score(player: Player) -> float:
    """場のキャラの役割別合計価値。 field_count + field_power では捉えきれない「質」 を測る。

    例: 6-cost 7000-power finisher は 3.0、 6-cost 7000-power vanilla は 0.5。
    role_db に登録ないキャラは default 0.5。
    """
    from . import card_role
    try:
        role_db = card_role.load_card_role_db()
    except Exception:
        return 0.0
    total = 0.0
    for ip in player.characters:
        total += _role_value_of(ip.card.card_id, role_db)
    return total


def hand_quality_score(player: Player) -> float:
    """手札の役割別合計価値。 finisher 多数 vs vanilla 多数 を区別する。"""
    from . import card_role
    try:
        role_db = card_role.load_card_role_db()
    except Exception:
        return 0.0
    total = 0.0
    for c in player.hand:
        total += _role_value_of(c.card_id, role_db)
    return total


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
    ]
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

    ゲーム終了時は ±W_GAME_OVER で確定値。 それ以外は 9 指標の重み付き差分合計。
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    if state.game_over:
        if state.winner == me_idx:
            return float(weights.W_GAME_OVER)
        elif state.winner is not None:
            return float(-weights.W_GAME_OVER)
        return 0.0  # 引き分け

    breakdown = compute_breakdown(state, me_idx, weights)
    return sum(m["contribution"] for m in breakdown.values())


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
