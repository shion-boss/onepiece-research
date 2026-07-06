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
# ⚠ 剪定(2026-07-06): resource_denial(life+/hand-/field を合成)と don_cospa(それ÷DON)を削除。
# 顔攻撃は life→hand で life削り(+)と手札"増"(-)が逆向き → 合成すると相殺 = lossy(combiner が
# 分離不能)。 原則「評価関数は測るだけ、 処理(合成/重み)は combiner だけ」に反する。 アトミックな
# opp_life_removed / opp_hand_removed / opp_field_removed / don_used_this_turn を残し、 combiner が
# life-pressure と hand-denial と DON コスパを **別々に学習** する(life→hand trade-off も学べる)。
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


def _power(p):
    return sum(int(getattr(c, "power", 0) or 0) for c in getattr(p, "characters", []))


def _active_attackers(p):
    n = 0
    for c in getattr(p, "characters", []):
        if getattr(c, "rested", False):
            continue
        if not getattr(c, "summoning_sickness", False) or getattr(c, "is_rush_now", False):
            n += 1
    return n


def _avail_blockers(p):
    return sum(1 for c in getattr(p, "characters", [])
               if c.has_keyword_active("ブロッカー") and not getattr(c, "rested", False))


def _counter_in_hand(p):
    return sum(int(getattr(c, "counter", 0) or 0) for c in getattr(p, "hand", []))


# ─────────────────────────────────────────────────────────────────────────
# 位置・盤面群(A)
# ─────────────────────────────────────────────────────────────────────────
@eval_function("board_power_diff", "position")
def ef_board_power_diff(ctx):
    return (_power(ctx.me(ctx.cur)) - _power(ctx.opp(ctx.cur))) / 1000.0


@eval_function("board_count_diff", "position")
def ef_board_count_diff(ctx):
    return float(_field(ctx.me(ctx.cur)) - _field(ctx.opp(ctx.cur)))


@eval_function("active_attacker_diff", "position")
def ef_active_attacker_diff(ctx):
    return float(_active_attackers(ctx.me(ctx.cur)) - _active_attackers(ctx.opp(ctx.cur)))


@eval_function("my_avail_blocker", "position")
def ef_my_avail_blocker(ctx):
    """次の相手ターンに防御できる自分のブロッカー数(exposure の逆)。"""
    return float(_avail_blockers(ctx.me(ctx.cur)))


@eval_function("opp_active_blocker", "position")
def ef_opp_active_blocker(ctx):
    """相手の active ブロッカー数 = 自分の攻撃を止める壁(負の信号)。"""
    return -float(_avail_blockers(ctx.opp(ctx.cur)))


# ─────────────────────────────────────────────────────────────────────────
# ライフ群(B)
# ─────────────────────────────────────────────────────────────────────────
@eval_function("life_diff", "life")
def ef_life_diff(ctx):
    return float(_life(ctx.me(ctx.cur)) - _life(ctx.opp(ctx.cur)))


@eval_function("opp_life_pressure", "life")
def ef_opp_life_pressure(ctx):
    """相手ライフが低いほど高(=リーサル圏に近い)。 5 - opp_life。"""
    return float(5 - _life(ctx.opp(ctx.cur)))


@eval_function("my_life_buffer", "life")
def ef_my_life_buffer(ctx):
    """自分のライフ buffer(低いと危険 = 負)。"""
    return float(_life(ctx.me(ctx.cur)) - 2)


# ─────────────────────────────────────────────────────────────────────────
# 手札群(C)
# ─────────────────────────────────────────────────────────────────────────
@eval_function("card_advantage", "hand")
def ef_card_advantage(ctx):
    return float(_hand(ctx.me(ctx.cur)) - _hand(ctx.opp(ctx.cur)))


@eval_function("my_counter_value", "hand")
def ef_my_counter_value(ctx):
    """自分の手札のカウンター総量(= 次の相手ターンの防御資源)。"""
    return _counter_in_hand(ctx.me(ctx.cur)) / 1000.0


@eval_function("opp_hand_size", "hand")
def ef_opp_hand_size(ctx):
    """相手の手札枚数(多い=相手のリソース = 負)。"""
    return -float(_hand(ctx.opp(ctx.cur)))


# ─────────────────────────────────────────────────────────────────────────
# DON 群(D)
# ─────────────────────────────────────────────────────────────────────────
@eval_function("don_used_this_turn", "efficiency")
def ef_don_used_this_turn(ctx):
    """このターンに使った DON(= 展開量。 遊ばせてない)。 total_don の減少。"""
    return float(max(0, getattr(ctx.me(ctx.orig), "total_don", 0)
                     - getattr(ctx.me(ctx.cur), "total_don", 0)))


@eval_function("don_reserve_active", "defense")
def ef_don_reserve_active(ctx):
    """ターン終了時の active DON(= カウンター用 reserve)。 少量は防御に有用(過度は無駄)。
    符号は combiner が学習(脅威高い時は正、 低い時は負を学べる)。"""
    return float(getattr(ctx.me(ctx.cur), "don_active", 0))


@eval_function("attached_don_on_active", "efficiency")
def ef_attached_don_on_active(ctx):
    """未 rest(攻撃予定/した)キャラに付いた DON(= 有効付与)vs rested でない遊び。"""
    p = ctx.me(ctx.cur)
    useful = sum(c.attached_dons for c in getattr(p, "characters", [])
                 if getattr(c, "attached_dons", 0) > 0 and getattr(c, "rested", False))
    wasted = sum(c.attached_dons for c in ([p.leader] + list(getattr(p, "characters", [])))
                 if getattr(c, "attached_dons", 0) > 0 and not getattr(c, "rested", False))
    return float(useful - wasted)  # 攻撃済みキャラの付与=有効、 未攻撃の付与=無駄


# ─────────────────────────────────────────────────────────────────────────
# 相手推定群(E、 belief)
# ─────────────────────────────────────────────────────────────────────────
@eval_function("opp_blocker_prob", "belief")
def ef_opp_blocker_prob(ctx):
    """相手が手札にブロッカーを持つ確率(belief)= 攻撃が止まるリスク(負)。"""
    try:
        from . import hand_estimator
        return -float(hand_estimator.probability_of_blocker_in_hand(ctx.cur, ctx.opp_idx))
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────
# 資源 denial 詳細群(H、 個別信号 = combiner が life/hand/field を別々に weigh)
# ─────────────────────────────────────────────────────────────────────────
@eval_function("opp_life_removed", "denial")
def ef_opp_life_removed(ctx):
    return float(_life(ctx.opp(ctx.orig)) - _life(ctx.opp(ctx.cur)))


@eval_function("opp_hand_removed", "denial")
def ef_opp_hand_removed(ctx):
    """相手手札を減らした量(手札破壊)。 ohtsuki weakness ③。"""
    return float(_hand(ctx.opp(ctx.orig)) - _hand(ctx.opp(ctx.cur)))


@eval_function("opp_field_removed", "denial")
def ef_opp_field_removed(ctx):
    """相手盤面キャラを減らした量(除去)。"""
    return float(_field(ctx.opp(ctx.orig)) - _field(ctx.opp(ctx.cur)))


# ─────────────────────────────────────────────────────────────────────────
# 攻撃判断群(F、 ohtsuki の attack 知識を信号化)
# ─────────────────────────────────────────────────────────────────────────
def _count_attacks(plan):
    try:
        from .game import AttackLeader, AttackCharacter
        leader = sum(1 for a in plan if isinstance(a, AttackLeader))
        chara = sum(1 for a in plan if isinstance(a, AttackCharacter))
        return leader, chara
    except Exception:
        return 0, 0


@eval_function("attacks_on_leader", "attack")
def ef_attacks_on_leader(ctx):
    """リーダーへの攻撃回数(= 基本の顔詰め、 打点/防御強制)。"""
    return float(_count_attacks(ctx.plan)[0])


@eval_function("attacks_on_chara", "attack")
def ef_attacks_on_chara(ctx):
    """キャラへの攻撃回数(除去狙い)。 threat 除去なら価値、 無駄ならコスパ悪。"""
    return float(_count_attacks(ctx.plan)[1])


@eval_function("attack_power_committed", "attack")
def ef_attack_power_committed(ctx):
    """攻撃に乗せた総パワー(= 相手に防御を強制する量。 +1000/+2000 で counter/ライフ強制)。
    rested になった自キャラ(=攻撃した)の power 合計 で近似。"""
    p = ctx.me(ctx.cur)
    return sum(int(getattr(c, "power", 0) or 0) for c in getattr(p, "characters", [])
               if getattr(c, "rested", False)) / 1000.0


# ─────────────────────────────────────────────────────────────────────────
# レース群(I)
# ─────────────────────────────────────────────────────────────────────────
@eval_function("opp_next_lethal", "race")
def ef_opp_next_lethal(ctx):
    """相手の次ターンのリーサル脅威(= 自分の clock、 負)。"""
    try:
        from .eval import lethal_estimate
        return -float(lethal_estimate(ctx.cur, ctx.opp_idx))
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────
# テンポ・効果群(G)
# ─────────────────────────────────────────────────────────────────────────
@eval_function("cards_played", "tempo")
def ef_cards_played(ctx):
    """このターンにプレイしたカード数(展開)= 場のキャラ増 で近似。"""
    return float(_field(ctx.me(ctx.cur)) - _field(ctx.me(ctx.orig)))


@eval_function("plan_length", "tempo")
def ef_plan_length(ctx):
    """プランの action 数(= このターンの活動量。 過小なら手抜き)。"""
    return float(len(ctx.plan))


# ─────────────────────────────────────────────────────────────────────────
# 推論軸(生盤面特徴が持てない "計算/評価"。 = 天井を超える本命)
# ─────────────────────────────────────────────────────────────────────────
# ⚠ 剪定: attack_vs_counter(attack_power − opp_counter の合成)を削除。 attack_power_committed(r=0.95
# で冗長)と opp_counter_threat が既にアトミックにあり、 combiner が「攻撃圧 vs 相手カウンター」を学習。
@eval_function("threat_removed_power", "denial")
def ef_threat_removed_power(ctx):
    """このターンで盤面から除いた相手キャラの power 合計(= 除去した"脅威の大きさ"。 数でなく質、
    ohtsuki「効果が嫌なキャラ/大きいキャラの除去」)。 instance_id で orig→cur の消えたキャラを特定。"""
    o = {getattr(c, "instance_id", id(c)): int(getattr(c, "power", 0) or 0)
         for c in getattr(ctx.opp(ctx.orig), "characters", [])}
    cur_ids = {getattr(c, "instance_id", id(c)) for c in getattr(ctx.opp(ctx.cur), "characters", [])}
    return sum(pw for iid, pw in o.items() if iid not in cur_ids) / 1000.0


@eval_function("opp_board_threat", "belief")
def ef_opp_board_threat(ctx):
    """相手盤面の総 power(= 自分が次ターン受ける危険)。 負の信号。"""
    return -_power(ctx.opp(ctx.cur)) / 1000.0


@eval_function("net_tempo_swing", "tempo")
def ef_net_tempo_swing(ctx):
    """このターンの盤面 power の純増減(自増 − 相手増)= このターンで盤面差をどれだけ動かしたか。"""
    my_d = _power(ctx.me(ctx.cur)) - _power(ctx.me(ctx.orig))
    opp_d = _power(ctx.opp(ctx.cur)) - _power(ctx.opp(ctx.orig))
    return (my_d - opp_d) / 1000.0


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
    """評価ベクトルを最終スコアに(Phase1 = 重み付き和)。 weights 無しは全軸 0(= 無害)。"""
    if not weights:
        return 0.0
    return sum(vec.get(k, 0.0) * w for k, w in weights.items())


# ── 学習 combiner(Phase2): 評価ベクトル → P(win)。 beam の value 代替 ────────────
_COMBINER_CACHE: dict = {}


def _load_combiner(path: str):
    m = _COMBINER_CACHE.get(path)
    if m is None:
        import pickle
        with open(path, "rb") as f:
            m = pickle.load(f)
        _COMBINER_CACHE[path] = m
    return m


def _sigmoid(z: float) -> float:
    import math
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def combiner_pwin(orig, cur, plan, me_idx, path: str) -> float:
    """combiner で候補plan の評価ベクトル → P(win)。 beam が最善手を選ぶ value。
    combiner pkl は 2 種類を受ける:
      - {"model": sklearn, "axes": [...]}          学習 combiner(self-play 勝敗で fit)
      - {"kind":"linear","weights":{axis:w},"bias":b}  hand-prior 線形(知識で符号固定 = 逆因果矯正)
    """
    c = _load_combiner(path)
    vec = eval_vector(orig, cur, plan, me_idx)
    if c.get("kind") == "linear":
        z = float(c.get("bias", 0.0)) + sum(vec.get(k, 0.0) * w for k, w in c["weights"].items())
        return _sigmoid(z)
    x = [[float(vec.get(k, 0.0)) for k in c["axes"]]]
    try:
        return float(c["model"].predict_proba(x)[0][1])
    except Exception:
        return 0.5
