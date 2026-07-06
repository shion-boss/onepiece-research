"""多軸評価関数フレームワーク(ohtsuki 設計 2026-07-06)。

単一の盤面 value(表現の天井で plateau)でなく、 **人間が使う戦略軸を1つずつ評価関数として手で書き**、
候補手(turn plan)ごとに評価関数ベクトルを算出 → combiner が最終判断して最善手を選ぶ。

狙い: 生盤面特徴では表せない「戦略的推論」(DON コスパ / 資源 denial / 攻撃判断 / 効果活用 / 相手
カウンター推定 …)を**知識で評価関数化** → GPU-NN の feature 学習を人間知識で代替 → CPU で天井突破。

各評価関数: fn(ctx) -> float(高いほど me に有利)。 ctx = EvalContext(orig, cur, plan, me_idx)。
  - orig  : 自ターン開始時の state(このターンの起点)
  - cur   : plan 適用後の state(相手応手の前)
  - plan  : このターンの action 列
  - me_idx: 自分の player index

登録は @eval_function(name, group)。 eval_vector(ctx) が {name: 値} を返す。 combiner は別途
(重み付き or 学習)。 各軸は必ず A/B で検証してから重みを上げる(効かない軸は 0 のまま = 無害)。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable

# 登録簿: (name, group, fn)
EVAL_FUNCTIONS: list[tuple[str, str, Callable]] = []


def eval_function(name: str, group: str):
    def deco(f: Callable) -> Callable:
        EVAL_FUNCTIONS.append((name, group, f))
        return f
    return deco


@dataclass
class EvalContext:
    orig: Any          # 自ターン開始時 state
    cur: Any           # plan 適用後 state
    plan: list         # このターンの action 列
    me_idx: int
    # 遅延計算のキャッシュ(重い belief 等を 1 度だけ)
    _cache: dict = None

    def __post_init__(self):
        if self._cache is None:
            self._cache = {}

    @property
    def opp_idx(self):
        return 1 - self.me_idx

    def me(self, state):
        return state.players[self.me_idx]

    def opp(self, state):
        return state.players[self.opp_idx]


def _life(p):
    return len(getattr(p, "life", []))


def _hand(p):
    return len(getattr(p, "hand", []))


def _field(p):
    return len(getattr(p, "characters", []))


# ─────────────────────────────────────────────────────────────────────────
# 資源効率群(D): DON コスパ / 資源 denial
# ─────────────────────────────────────────────────────────────────────────
@eval_function("resource_denial", "denial")
def ef_resource_denial(ctx: EvalContext) -> float:
    """このプランで減らした相手リソース(life + 手札 + 盤面キャラ)。 = 相手を削る量。
    盤面 value が過小評価する一時的/条件付き除去・手札破壊を直接 credit する軸。"""
    o, c = ctx.opp(ctx.orig), ctx.opp(ctx.cur)
    life_rm = _life(o) - _life(c)
    hand_rm = _hand(o) - _hand(c)
    field_rm = _field(o) - _field(c)
    # 重みは暫定(life > 盤面 > 手札 の粗い序列)。 combiner が最終調整。
    return 3.0 * life_rm + 2.0 * field_rm + 1.5 * hand_rm


@eval_function("don_cospa", "efficiency")
def ef_don_cospa(ctx: EvalContext) -> float:
    """DON コスパ = 相手リソース削減 ÷ 実効 DON コスト(デッキに戻す ≤2 は無料、 ohtsuki)。
    「少ない DON で最大の削減」を報酬。 ≤2 DON return の無料除去(ドン!!-1)を高評価にする狙い。"""
    denial = ef_resource_denial(ctx)
    if denial <= 0:
        return 0.0
    mo, mc = ctx.me(ctx.orig), ctx.me(ctx.cur)
    # このターン使った DON(total_don の減少)。 デッキに戻す ≤2 は無料 → 実効から引く。
    don_used = max(0, getattr(mo, "total_don", 0) - getattr(mc, "total_don", 0))
    eff_don = max(1.0, float(don_used) - 2.0)  # ≤2 は無傷
    return denial / eff_don


# ─────────────────────────────────────────────────────────────────────────
# 攻撃判断群(F/E): 相手手札カウンター推定 / 攻撃先
# ─────────────────────────────────────────────────────────────────────────
@eval_function("opp_counter_threat", "attack")
def ef_opp_counter_threat(ctx: EvalContext) -> float:
    """相手手札の推定カウンター総量(belief)。 高いほど自分の攻撃が通りにくい → 負の信号。
    hand_estimator.expected_counter_total を使用(既存の隠匿情報推定)。"""
    try:
        from . import hand_estimator
        ct = hand_estimator.expected_counter_total(ctx.cur, ctx.opp_idx)
        return -float(ct) / 1000.0  # counter 値を 1000 単位に正規化、 多いほど負
    except Exception:
        return 0.0


@eval_function("lethal_progress", "race")
def ef_lethal_progress(ctx: EvalContext) -> float:
    """レース優位 = 自分のリーサル見積 − 相手のリーサル見積(この plan 後)。"""
    try:
        from .eval import lethal_estimate
        return float(lethal_estimate(ctx.cur, ctx.me_idx)) - float(lethal_estimate(ctx.cur, ctx.opp_idx))
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────
# ベクトル算出
# ─────────────────────────────────────────────────────────────────────────
def eval_vector(orig, cur, plan, me_idx) -> dict[str, float]:
    """全評価関数を評価して {name: 値} を返す。 失敗した軸は 0.0。"""
    ctx = EvalContext(orig=orig, cur=cur, plan=plan, me_idx=me_idx)
    out = {}
    for name, group, fn in EVAL_FUNCTIONS:
        try:
            out[name] = float(fn(ctx))
        except Exception:
            out[name] = 0.0
    return out


def combine(vec: dict[str, float], weights: dict[str, float] | None = None) -> float:
    """評価ベクトルを最終スコアに(Phase1 = 重み付き和)。 weights 無しは全軸 0(= 無害)。
    Phase2 で学習 combiner に差し替え予定(評価ベクトル → 勝率)。"""
    if not weights:
        return 0.0
    return sum(vec.get(k, 0.0) * w for k, w in weights.items())
