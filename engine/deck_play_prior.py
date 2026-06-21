# -*- coding: utf-8 -*-
"""自動導出の play-timing policy PRIOR (= deck-agnostic、 2026-06-16)。

「カードの効果を最大限生かす」 を、 デッキ固有の手書きでなく **効果オーバーレイの
`if` 条件から決定論で導出** する policy prior。 任意デッキ (= ユーザー作成デッキ含む)
で動く: 知識源は `state.effects_overlay` (全 4,518 カード) + `eval_condition` のみ。
学習も per-deck 資産も不要 ⇒ deploy_results 外のユーザーデッキでも素で機能する。

原理:
    条件付き効果 (`if`) は **条件が満たされた時にだけ発火** する。 ゆえに
    「条件が今満たされている札を play / activate する手」 は そのカードの効果を
    活かす良い手。 これを beam **探索の prior** (= どの手を残し深掘りするか) として
    加点する。 例: ボルサリーノ (`if self_life_le:2`) は 自ライフ 2 以下の時に
    play する手を優先探索する。

⚠ 設計鉄則 ([[project_combo_aware_ai]] / docs/HUMAN_LEVEL_AI_PLAN §2):
    これは **prior** であって value bias ではない。 plan_search の **beam 選別スコア**
    にのみ加え、 post-opp 再ランクの **最終 value (= calibrated GBM) には足さない**。
    value を直接歪めると camp 誘因で自滅する (combo-readiness を GBM に入れて
    measured dead-end、 main 395a168) のが既知。 ここは「探索が良い手を中間枝刈りで
    捨てない」 ための誘導に徹し、 最終決定は calibrated value に委ねる。

⚠ 非対称設計 (= naive flat-defer の轍を踏まない):
    条件が満たされない (= 効果が dead) 手は **罰しない** (return 0)。 過去に「条件が
    揃うまで出さない」 flat-defer は winrate を下げた ([[project_combo_aware_ai]]):
    高ライフ body は alternative とほぼ同値で「他に手が無ければ出す」 が正解、 速い
    試合は低ライフ payoff に到達しない。 ⇒ 良いタイミングを **足す** だけ、 悪い
    タイミングを **引かない**。
"""
from __future__ import annotations

from .game import ActivateMain, PlayCharacter, PlayEvent, PlayStage
from .effects import eval_condition

# action 種別 → その手で発火し得る効果の `when` 集合。
# PlayCharacter / PlayStage = on_play、 PlayEvent = メインフェイズ効果 (= main)、
# ActivateMain = 起動メイン。
# ⚠ on_attack (= 攻撃者の on_attack 条件) は measured で **外した**: 攻撃手は頻度が高く、 prior を
#    多数の attack line に撒くと beam (幅16) を飽和させ、 on_play 由来の的を絞った gain を希釈した
#    (1454: on_play のみ +7pt → on_attack 追加で +2pt、 一方 1456 は +2→+5)。 = surface を広げると
#    deck 依存のトレードに化け no-harm でなくなる。 robust な on_play/main/activate のみ採用。
#    防御 when (counter / opp_attack) は choose_defense = 別経路 (= 次の本命 headroom)。
_ACTION_WHENS = {
    PlayCharacter: ("on_play",),
    PlayStage: ("on_play",),
    PlayEvent: ("main",),
    ActivateMain: ("activate_main",),
}


def _find_by_iid(me, iid):
    """me の場 / リーダーから iid 一致の InPlay を `(card_id, inplay)` で返す。"""
    if me.leader is not None and me.leader.instance_id == iid:
        return me.leader.card.card_id, me.leader
    for ip in me.characters:
        if ip.instance_id == iid:
            return ip.card.card_id, ip
    return None, None


def _resolve_card_and_self(state, action, me):
    """action から `(card_id, self_inplay)` を解決。

    play 系は手札の CardDef (= self_inplay は登場前なので None)、 ActivateMain は
    場 / リーダーの InPlay (= source_iid)。 解決不能なら `(None, None)`。
    """
    try:
        if isinstance(action, (PlayCharacter, PlayEvent, PlayStage)):
            idx = action.hand_idx
            if 0 <= idx < len(me.hand):
                return me.hand[idx].card_id, None
        elif isinstance(action, ActivateMain):
            return _find_by_iid(me, action.source_iid)
    except Exception:
        pass
    return None, None


def count_conditional(state, action, me_idx: int) -> tuple[int, int]:
    """この play/activate に紐づく条件付き効果の `(n_gated, n_live)` を返す。

    - n_gated: 当該 action の `when` を持ち、 かつ `if` 条件付きの効果バンドル数。
    - n_live: そのうち、 今 (= 現 state) 条件が満たされ **発火する** 数。

    解決不能 / overlay なし / 該当 when なしは `(0, 0)`。 例外は握り潰す (= best-effort)。
    効果活用率の計測 (eval) と prior 加点 (下記) の両方が単一の真実を共有する。
    """
    whens = _ACTION_WHENS.get(type(action))
    if not whens:
        return 0, 0
    overlay = getattr(state, "effects_overlay", None)
    if not overlay:
        return 0, 0
    try:
        me = state.players[me_idx]
    except Exception:
        return 0, 0

    card_id, self_inplay = _resolve_card_and_self(state, action, me)
    if not card_id:
        return 0, 0
    bundle_obj = overlay.get(card_id)
    if bundle_obj is None:
        return 0, 0
    # 実行時 overlay は CardEffectBundle (= .effects に bundle list)、 raw list の両対応。
    bundles = getattr(bundle_obj, "effects", bundle_obj)
    if not isinstance(bundles, list):
        return 0, 0

    n_gated = 0
    n_live = 0
    for b in bundles:
        if not isinstance(b, dict):
            continue
        if b.get("when") not in whens:
            continue
        cond = b.get("if")
        if not cond:
            continue  # 無条件効果は prior 中立 (= body 価値で勝負、 最終 value が判断)
        n_gated += 1
        try:
            if eval_condition(cond, state, me, self_inplay):
                n_live += 1
        except Exception:
            continue  # 評価不能な条件は「不明」 = 中立扱い (= 加点しない)
    return n_gated, n_live


def play_prior_bonus(state, action, me_idx: int) -> float:
    """この手が「今 条件が満たされている条件付き効果」 を発火させるなら正の prior を返す。

    返り値は概ね `[0.0, 1.5]` の unit で、 呼出側 (plan_search) が weight で scale する。
    満たされない条件 / 条件なし / 解決不能 はすべて `0.0` (= 罰しない)。 例外は握り潰して
    探索を止めない (= prior は best-effort、 落ちても compute_score だけで beam は回る)。
    """
    _, n_live = count_conditional(state, action, me_idx)
    if n_live <= 0:
        return 0.0
    # 1 つでも live なら基礎点、 複数 live は逓減加算で cap (= 過剰加点を防ぐ)。
    return min(1.0 + 0.25 * (n_live - 1), 1.5)
