# -*- coding: utf-8 -*-
"""学習盤面value (= GBM) を beam の leaf eval に使う (= 2026-06-04 自律、 70% 探索)。

board_eval (= hand-tuned linear) は winrate-tune 済でも beam が 62.5% で飽和 (= 線形の天井)。
GBM (= 非線形、 特徴の交互作用) を beam-vs-greedy の (盤面, 勝敗) で学習し、 leaf で P(win) を
返せば、 線形 eval が捉えられない交互作用 (例: low-life × no-blocker) を value 化できる。

統合: compute_score の冒頭で ONEPIECE_GBM_VALUE_PATH が set されていれば、 game_over は
±W_GAME_OVER、 非終端は (P(win)-0.5)*SCALE を返す (= 既存 leaf eval を置換)。
"""
from __future__ import annotations

import os
from typing import Any, Optional

# feature 名 (= 学習/推論で厳密一致させる)。 v1 = 17 (基本盤面量、 2026-06-04)。
FEATURE_KEYS = (
    "d_life", "d_field_count", "d_field_power", "d_hand", "d_don",
    "d_blocker", "d_attached_don", "d_active_chara",
    "my_life", "opp_life", "my_hand", "opp_hand",
    "my_field_count", "opp_field_count", "my_field_power", "opp_field_power",
    "turn",
)
# v2 = 21 (2026-06-05): v1 が ROC0.755 で飽和 (= 37k sample でも不変 → データでなく特徴が天井)。
# race圏 (lethal) と 手札 counter 総量 (= 防御資源、 線形 eval が捉えぬ交互作用) を追加。
FEATURE_KEYS_V2 = FEATURE_KEYS + ("my_lethal", "opp_lethal", "my_counter", "opp_counter")
# v3 = 23 (2026-06-12): v2 は d_don (= total_don diff) しか持たず active/tapped を区別できない。
# raw active DON (= 各自の untapped DON) を追加 = 「DON0窓 (tap out)」「守備リザーブ (counter-event 用)」
# を value 化する狙い (= #7 counter-event 守備修正で初めて活きた防御資源)。
# ⚠ A/B 実測 (2026-06-12、 改善後AIで 1000戦学習、 各 vs deployed N=300):
#   op13 = v3 53% / v2recal 50% (= +3pt) だが 1342 = v3 47% / v2recal 47% (= ±0) → 再現性なし=ノイズ。
#   ROC も op13 0.725→0.729、 1342 0.812→0.814 でほぼ不変。 ⇒ raw DON は value を有意に改善せず、
#   v3 GBM は deploy しない (= deployed は v2 のまま)。 この機構は 将来の別特徴 実験用の scaffold として残置。
FEATURE_KEYS_V3 = FEATURE_KEYS_V2 + ("my_don_active", "opp_don_active")
# v4 = 25 (2026-06-19): v2 + card-advantage エンジン潜在力 (= deck archetype 信号)。
# 現特徴は即時盤面量のみ → control/aggro を区別できず単一 agnostic value が aggro を誤評価
# (= Phase B 回帰、 [[project_deck_agnostic_value_selfplay]])。 overlay の draw/search/recursion
# (engine) と life→hand/heal (recovery) 密度を 自/相手デッキ全体で計数し、 1-ply value に
# 「このデッキは grind(control) 型か race(aggro) 型か」 を持たせる (= 多ターン性の proxy)。
FEATURE_KEYS_V4 = FEATURE_KEYS_V2 + ("my_engine", "opp_engine", "my_recovery", "opp_recovery")
# v5 = 34 (2026-06-26): 相手 leader の matchup tag (= leader_profiles.json の機械可読 tag) を
# 直接 feature 化。 v2/v4 は board / deck-card-density のみで「相手が誰か(攻略すべき脅威)」を
# 見ない (= opp-agnostic、 単一 value が matchup を区別できない)。 hand-rule 注入は学習 value に
# 負ける (= [[project_leader_aware_matchup_ai]] -4.6pt) ので、 leader 理解を効かせる唯一の道 =
# 学習 feature 化: 相手 leader tag を渡し、 GBM tree が matchup で分岐して board 重みを
# 「相手攻略情報で可変」にする (= ohtsuki 案『評価関数の数値を相手デッキの攻略情報で可変的に』)。
# tag は 1 ゲーム内で定数 → 多相手 self-play data (--opp comma list) で variance が出て初めて
# tree が条件分けを学習できる (= 単一相手訓練では無意味、 必ず多相手で訓練)。
# 語彙は固定順 (= 列の安定性が必須)。 leader_profiles の現行 13 tag を sorted で固定。
_MATCHUP_TAG_VOCAB = (
    "aggro", "big_finisher", "char_protect_to_life", "control", "cost_tax",
    "counter_pump", "defensive_buff_low_life", "draw_engine", "draw_on_life_loss",
    "midrange", "proactive_snowball", "ramp", "redirect_protect",
)
FEATURE_KEYS_V5 = FEATURE_KEYS_V2 + tuple("opp_" + t for t in _MATCHUP_TAG_VOCAB)


def _opp_matchup_tag_vector(state: Any, me_idx: int) -> list:
    """相手 leader → leader_profiles tag を 固定語彙の binary vector に。 未知 leader / 取得失敗は全0
    (= neutral/unknown matchup、 fallback)。 推論・学習の両方で呼ばれる (= leader は公開情報)。"""
    try:
        opp = state.players[1 - me_idx]
        lid = opp.leader.card.card_id
    except Exception:
        return [0.0] * len(_MATCHUP_TAG_VOCAB)
    try:
        from .matchup_model import read_leader_profile
        prof = read_leader_profile(lid)
    except Exception:
        prof = None
    tags = set(prof.get("tags", []) or []) if prof else set()
    return [1.0 if t in tags else 0.0 for t in _MATCHUP_TAG_VOCAB]


def _opp_tag_set(state: Any, me_idx: int) -> set:
    try:
        lid = state.players[1 - me_idx].leader.card.card_id
        from .matchup_model import read_leader_profile
        prof = read_leader_profile(lid)
        return set((prof.get("tags", []) or [])) if prof else set()
    except Exception:
        return set()


# v6 = 38 (2026-06-26): matchup *interaction* features (= 相手 tag × board)。 v5 の tag は
# 1 ゲーム内で定数 → value の *水準* は動かすが、 同一ターン内で全候補に定数で乗るため *手の相対
# 順位* をほぼ変えず deploy null だった (= [[project_leader_aware_matchup_ai]] high-N null)。
# これは「相手理解不足」(ohtsuki 2026-06-26): 必要なのは「この相手を *この盤面* にするのが良いか」
# = board×matchup の交互作用 (= 候補ごとに変わる selection-relevant 信号)。 例「相手を低ライフへ
# chip すると defensive buff が起動」「相手の draw engine にライフを与えた」 を board-varying に encode。
# 全て公開情報 (相手 leader tag + 公開 board) で計算 → 訓練/推論で一致 (= hidden-info 不要)。
_REF_LIFE = 5.0  # OPTCG leader 初期ライフの代表値 (= life-fed proxy の基準、 厳密でなくてよい)
FEATURE_KEYS_V6 = FEATURE_KEYS_V5 + (
    "ix_opp_buff_active",      # defensive_buff_low_life × 相手ライフが buff 圏 (≤1)
    "ix_opp_life_fed_draw",    # draw_on_life_loss × 相手が失ったライフ (= draw engine に塩を送った量)
    "ix_opp_counter_threat",   # counter_pump × 相手手札 (= カウンター trick の potential)
    "ix_opp_finisher_armed",   # big_finisher × 相手 active DON (= alpha-strike の構え)
)


def _opp_matchup_interaction_vector(state: Any, me_idx: int) -> list:
    """相手 tag × board の交互作用 (= 候補ごとに変わる selection-relevant な matchup 信号)。
    公開情報のみ。 未知 leader (tag 空) は全0。"""
    tags = _opp_tag_set(state, me_idx)
    if not tags:
        return [0.0, 0.0, 0.0, 0.0]
    try:
        opp = state.players[1 - me_idx]
        opp_life = float(len(getattr(opp, "life", []) or []))
        opp_hand = float(len(getattr(opp, "hand", []) or []))
        opp_don_active = float(int(getattr(opp, "don_active", 0) or 0))
    except Exception:
        return [0.0, 0.0, 0.0, 0.0]
    buff_active = 1.0 if ("defensive_buff_low_life" in tags and opp_life <= 1) else 0.0
    life_fed = max(0.0, _REF_LIFE - opp_life) if "draw_on_life_loss" in tags else 0.0
    counter_threat = opp_hand if "counter_pump" in tags else 0.0
    finisher_armed = opp_don_active if "big_finisher" in tags else 0.0
    return [buff_active, life_fed, counter_threat, finisher_armed]


# v7 = 44 (2026-06-28): ohtsuki 原則『自分のやりたいこと(own-plan) と 相手にやらせたくないこと
# (opp-denial) のバランスを 組み合わせ毎に考慮する』を value 設計に落とす。 v5/v6 は opp 情報
# (脅威)のみ → value は「相手を知る」が「自分のやりたいこと vs denial のバランス」を持たない。
# ドフラ vs ボニーの mispilot(リーダーにドンを注いで顔を race→counterで弾かれ全ターン浪費、
# 本来は除去/denial に使うべき)が典型。 own-race へのコミット(my_leader_don)を opp の
# aggressiveness と交互作用させ、 GBM tree が「速攻相手にリーダー race = バランス違反 = 悪」を
# matchup 毎に学習できるようにする(手書きrule でなく学習で原則を実現、 [[feedback_evolutionary_over_tuning]])。
_AGGRO_TAGS = frozenset({"aggro", "proactive_snowball"})
FEATURE_KEYS_V7 = FEATURE_KEYS_V6 + (
    "my_leader_don",            # own-plan: 自リーダーへのドン投資 (= race へのコミット度)
    "opp_leader_don",           # 相手の leader-offense コミット
    "my_active_chara",          # own-plan: 自分の active 攻撃体 (= 圧/盤面)
    "opp_active_chara",         # denial: 相手の active 攻撃体 (= 捌くべき盤面圧)
    "ix_my_leaderrace_vs_aggro",  # my_leader_don × opp_aggressive = 速攻相手にリーダー race (= バランス違反 flag)
    "ix_opp_pressure_vs_aggro",   # opp_active_chara × opp_aggressive = 速攻相手の盤面圧 (= denial 優先度)
)


def _balance_features(state: Any, me_idx: int) -> list:
    """own-plan(自分のやりたいこと) × opp-denial(相手にやらせたくないこと) のバランス信号。
    own-race(リーダーへのドン)を opp の aggressiveness と掛け、 マッチ毎のバランスを学習可能に。"""
    from .eval import _player_metrics
    try:
        me_p, opp_p = state.players[me_idx], state.players[1 - me_idx]
        my_ld = float(getattr(me_p.leader, "attached_dons", 0) or 0)
        opp_ld = float(getattr(opp_p.leader, "attached_dons", 0) or 0)
        my_act = float(_player_metrics(me_p)["active_chara"])
        opp_act = float(_player_metrics(opp_p)["active_chara"])
    except Exception:
        return [0.0] * 6
    opp_aggr = 1.0 if (_opp_tag_set(state, me_idx) & _AGGRO_TAGS) else 0.0
    return [my_ld, opp_ld, my_act, opp_act, my_ld * opp_aggr, opp_act * opp_aggr]


# v8 = 46 (2026-06-29): ohtsuki『archetype 判定が粗い。 相手 concept を matchup value の opp 条件付けに』
# (= 効いた v5/v6 の延長、 [[project_leader_aware_matchup_ai]] B)。 v5 の粗い tag(13、 control が
# dofla/im/nami を束ねる)を、 相手 deck の **role-composition signature**(= card-pool 分析の
# 正規化 role 密度、 db/leader_role_vectors.json)で精緻化。 dofla= ramp0.28/nami= removal+cardadv/
# im= protection+cardadv と「control」を細分 → value が相手 concept 毎に条件付けを学べる。 opp leader
# (公開)で引く = 相手 deck を leader から予想する prior。 未知 leader は全0(neutral)。
_ROLE_DIMS = ("ramp", "big_threat", "removal", "protection", "card_adv", "go_wide", "defense", "recovery")
FEATURE_KEYS_V8 = FEATURE_KEYS_V6 + tuple("opprole_" + r for r in _ROLE_DIMS)
_OPP_ROLE_CACHE: Optional[dict] = None

# v9 = 39 (2026-06-29): residual-guarantee。 ohtsuki『全デッキ同じ v に統一 + 新版は旧を下回るな
# (v6⊇v2 なら最低 v2 同等のはず)』([[feedback_uniform_value_version]])。 v6 が deploy で v2 に
# 負ける deck(corazon: win-starved 6% で AUC>v2 でも deploy<v2)を、 **v2 の予測を anchor 列として
# 渡す**ことで構造保証: GBM は v2_anchor をそのまま出力する選択肢を持つ → v6 を v2 に anchor し、
# matchup 列で上回れる時だけ補正 → **構造的に v2 を下回りにくい**。 win-starved deck は補正≒0 で
# v9≈v2(回帰なし)、 強い deck は補正で v9>v2。 v2_anchor は companion v2 model(= value_gbm_<slug>
# _v2anchor.pkl)の predict。 訓練/推論で同一に計算。
FEATURE_KEYS_V9 = FEATURE_KEYS_V6 + ("v2_anchor",)


def v2_anchor_value(state: Any, me_idx: int, anchor_path: str) -> float:
    """companion v2 model(21-dim)の P(win) を anchor feature として返す。 失敗時 0.5(neutral)。"""
    try:
        m = _load(anchor_path)
        # 明示 False で env (ONEPIECE_GBM_V5/V6/...) の上書きを遮断 → 純 v2 (21-dim) を保証。
        x21 = features(state, me_idx, rich=True, v3=False, v4=False, v5=False, v6=False, v7=False, v8=False)
        if hasattr(m, "predict_proba"):
            return float(m.predict_proba([x21])[0][1])
        return min(1.0, max(0.0, float(m.predict([x21])[0])))
    except Exception:
        return 0.5


def _opp_role_vector(state: Any, me_idx: int) -> list:
    """相手 leader → role-composition signature(= concept、 正規化 role 密度 8 次元)。 未知は全0。"""
    global _OPP_ROLE_CACHE
    if _OPP_ROLE_CACHE is None:
        try:
            import json as _json
            p = _REPO_ROOT_RV() / "db" / "leader_role_vectors.json"
            _OPP_ROLE_CACHE = _json.loads(p.read_text(encoding="utf-8")).get("leaders", {})
        except Exception:
            _OPP_ROLE_CACHE = {}
    try:
        lid = state.players[1 - me_idx].leader.card.card_id
    except Exception:
        return [0.0] * len(_ROLE_DIMS)
    e = _OPP_ROLE_CACHE.get(lid)
    if not e:
        return [0.0] * len(_ROLE_DIMS)
    vec = e.get("vec", {})
    return [float(vec.get(r, 0.0)) for r in _ROLE_DIMS]


def _REPO_ROOT_RV():
    from pathlib import Path as _P
    return _P(__file__).resolve().parent.parent

# card-advantage を生む primitive (= grind/draw power)。 overlay 実測の key 名に厳密一致。
_ENGINE_PRIMS = frozenset({
    "draw", "draw_to_hand_size", "draw_per_hand_to_deck_bottom",
    "draw_per_self_hand_discarded", "draw_per_self_chara_then_discard",
    "search_top_n", "search", "search_from_trash",
    "play_from_trash", "play_from_hand_or_trash",
    "reveal_top_play", "reveal_top_then", "reveal_life_top_play",
    "summon_from_deck",
})
# 防御的延命 (= ライフ→手札/回復、 「受ける」 control の署名)。
_RECOVERY_PRIMS = frozenset({
    "life_to_hand", "life_top_or_bottom_to_hand", "then_life_to_hand",
    "put_top_to_life", "hand_to_self_life", "chara_to_self_life",
    "hand_or_trash_to_self_life", "or_to_life",
})
_CARD_POTENCY: Optional[dict] = None


def _card_potency() -> dict:
    """card_id -> (engine_count, recovery_count)。 overlay から 1 度だけ計数 (= lazy, module cache)。"""
    global _CARD_POTENCY
    if _CARD_POTENCY is not None:
        return _CARD_POTENCY
    import json
    from pathlib import Path
    out: dict = {}
    try:
        ov = json.loads((Path(__file__).resolve().parent.parent / "db" /
                         "card_effects.json").read_text(encoding="utf-8"))
    except Exception:
        ov = {}

    def _walk(do, acc):
        if isinstance(do, list):
            for x in do:
                _walk(x, acc)
        elif isinstance(do, dict):
            for k, v in do.items():
                if k in _ENGINE_PRIMS:
                    acc[0] += 1
                if k in _RECOVERY_PRIMS:
                    acc[1] += 1
                if isinstance(v, (list, dict)):
                    _walk(v, acc)

    for cid, entry in ov.items():
        acc = [0, 0]
        if isinstance(entry, list):
            for e in entry:
                if isinstance(e, dict) and "do" in e:
                    _walk(e["do"], acc)
        if acc[0] or acc[1]:
            out[cid] = (acc[0], acc[1])
    _CARD_POTENCY = out
    return out


def _zone_potency(p) -> tuple:
    """player の全ゾーン (deck/hand/trash/life/場/leader) のカードの engine/recovery 密度合計。
    ≈ デッキ全体の card-advantage 密度 = ほぼ静的な archetype 記述子 (= ナミ control 高 / エネル aggro 低)。"""
    pot = _card_potency()
    eng = rec = 0

    def _cid(c):
        cid = getattr(c, "card_id", None)
        if cid is None:
            cid = getattr(getattr(c, "card", None), "card_id", None)
        return cid

    cards = []
    for z in (p.deck, p.hand, p.trash, p.life, p.characters, p.stages):
        cards.extend(z)
    lead = getattr(p, "leader", None)
    if lead is not None:
        cards.append(lead)
    for c in cards:
        cid = _cid(c)
        if cid is not None:
            v = pot.get(cid)
            if v:
                eng += v[0]
                rec += v[1]
    return eng, rec


_MODEL = None
_MODEL_PATH: Optional[str] = None
_MODEL_CACHE: dict = {}  # path -> model (multi-slot: v9 は main + companion v2anchor を交互 load するため)
SCALE = 1_000_000.0


def features(state: Any, me_idx: int, rich: Optional[bool] = None,
             v3: Optional[bool] = None, v4: Optional[bool] = None,
             v5: Optional[bool] = None, v6: Optional[bool] = None,
             v7: Optional[bool] = None, v8: Optional[bool] = None) -> list:
    """GameState + me_idx → feature vector。 rich=True で v2 (21)、 既定は env
    ONEPIECE_GBM_RICH (= 学習時に set)。 推論は gbm_score が model 次元で自動判別。
    v5=True (env ONEPIECE_GBM_V5) で 相手 leader の matchup tag 13 列を追加 (= 34、 matchup-条件付き)。
    v6=True (env ONEPIECE_GBM_V6) で v5 + matchup interaction 4 列 (= 38、 board×matchup の交互作用)。
    v7=True (env ONEPIECE_GBM_V7) で v6 + balance 6 列 (= 44、 own-plan×opp-denial のマッチ毎バランス)。"""
    from .eval import _player_metrics
    me = _player_metrics(state.players[me_idx])
    opp = _player_metrics(state.players[1 - me_idx])
    base = [
        me["life"] - opp["life"],
        me["field_count"] - opp["field_count"],
        me["field_power"] - opp["field_power"],
        me["hand"] - opp["hand"],
        me["don"] - opp["don"],
        me["blocker"] - opp["blocker"],
        me["attached_don"] - opp["attached_don"],
        me["active_chara"] - opp["active_chara"],
        me["life"], opp["life"], me["hand"], opp["hand"],
        me["field_count"], opp["field_count"], me["field_power"], opp["field_power"],
        int(getattr(state, "turn_number", 0)),
    ]
    if rich is None:
        rich = os.environ.get("ONEPIECE_GBM_RICH") == "1"
    if v3 is None:
        v3 = os.environ.get("ONEPIECE_GBM_V3") == "1"
    if v4 is None:
        v4 = os.environ.get("ONEPIECE_GBM_V4") == "1"
    if v5 is None:
        v5 = os.environ.get("ONEPIECE_GBM_V5") == "1"
    if v6 is None:
        v6 = os.environ.get("ONEPIECE_GBM_V6") == "1"
    if v7 is None:
        v7 = os.environ.get("ONEPIECE_GBM_V7") == "1"
    if v8 is None:
        v8 = os.environ.get("ONEPIECE_GBM_V8") == "1"
    if v7:
        v6 = True  # v7 ⊃ v6 (balance)
    if v8:
        v6 = True  # v8 ⊃ v6 (opp role-composition)
    if v6:
        v5 = True  # v6 ⊃ v5 (tag + interaction)
    if v3 or v4 or v5:
        rich = True  # v3/v4/v5 ⊃ v2
    if not rich:
        return base
    from .eval import lethal_estimate
    me_p, opp_p = state.players[me_idx], state.players[1 - me_idx]
    my_counter = sum(int(getattr(c, "counter", 0) or 0) for c in me_p.hand)
    opp_counter = sum(int(getattr(c, "counter", 0) or 0) for c in opp_p.hand)
    out = base + [
        float(lethal_estimate(state, me_idx)),
        float(lethal_estimate(state, 1 - me_idx)),
        my_counter, opp_counter,
    ]
    if v3:
        out += [
            int(getattr(me_p, "don_active", 0) or 0),
            int(getattr(opp_p, "don_active", 0) or 0),
        ]
    if v4:
        my_e, my_r = _zone_potency(me_p)
        op_e, op_r = _zone_potency(opp_p)
        out += [my_e, op_e, my_r, op_r]
    if v5:
        out += _opp_matchup_tag_vector(state, me_idx)
    if v6:
        out += _opp_matchup_interaction_vector(state, me_idx)
    if v7:
        out += _balance_features(state, me_idx)
    if v8:
        out += _opp_role_vector(state, me_idx)
    return out


def _load(path: str):
    global _MODEL, _MODEL_PATH
    m = _MODEL_CACHE.get(path)
    if m is not None:
        return m
    import pickle
    with open(path, "rb") as f:
        m = pickle.load(f)
    _MODEL_CACHE[path] = m
    _MODEL, _MODEL_PATH = m, path  # 後方互換 (旧 single-slot を参照する箇所向け)
    return m


def gbm_score(state: Any, me_idx: int) -> Optional[float]:
    """ONEPIECE_GBM_VALUE_PATH の GBM で leaf value を返す (= 未設定なら None)。

    game_over は ±W_GAME_OVER、 非終端は (P(win)-0.5)*SCALE。
    """
    path = os.environ.get("ONEPIECE_GBM_VALUE_PATH")
    if not path:
        return None
    if getattr(state, "game_over", False):
        from .eval import DEFAULT_WEIGHTS
        w = getattr(state, "winner", -1)
        if w == me_idx:
            return float(DEFAULT_WEIGHTS.W_GAME_OVER)
        if w == 1 - me_idx:
            return -float(DEFAULT_WEIGHTS.W_GAME_OVER)
        return 0.0
    try:
        model = _load(path)
        # ── v9 residual wrapper (hard residual-guarantee) ─────────────────────
        # dict {"kind":"v9_residual", "anchor": v2 model(21), "resid": 38-dim regressor, "lam": float}。
        # p = clip(p_anchor + lam * resid(38feat))。 p_anchor は配備 v2 を**常に全強度**で base に置く →
        # 構造的に v2 を下回らない(lam=0 で厳密 v2)。 resid は matchup/board 38 列の**残差**のみ学習
        # (heavily regularized)→ 過適合した noise が base を上書きできない。 feature-anchor(v9 39-dim
        # classifier)が deploy で regress した教訓: anchor を 1 feature にすると GBM が無視して 38 列の
        # rare-win overfit に倒れる。 base+correction の分離で hard floor を担保。 [[feedback_uniform_value_version]]
        if isinstance(model, dict) and model.get("kind") == "v9_residual":
            feat21 = features(state, me_idx, rich=True, v3=False, v4=False,
                              v5=False, v6=False, v7=False, v8=False)
            feat38 = features(state, me_idx, v6=True, v7=False, v8=False)
            anchor = model["anchor"]
            if hasattr(anchor, "predict_proba"):
                p_anchor = float(anchor.predict_proba([feat21])[0][1])
            else:
                p_anchor = min(1.0, max(0.0, float(anchor.predict([feat21])[0])))
            resid = float(model["resid"].predict([feat38])[0])
            p = min(1.0, max(0.0, p_anchor + float(model.get("lam", 1.0)) * resid))
            return (p - 0.5) * SCALE
        # ── 通常 GBM (次元で v1(17)/v2(21)/.../v8(46) 自動判別、 後方互換) ───────
        n_feat = int(getattr(model, "n_features_in_", len(FEATURE_KEYS)))
        x = [features(state, me_idx,
                      rich=(n_feat == len(FEATURE_KEYS_V2)),
                      v3=(n_feat == len(FEATURE_KEYS_V3)),
                      v4=(n_feat == len(FEATURE_KEYS_V4)),
                      v5=(n_feat == len(FEATURE_KEYS_V5)),
                      v6=(n_feat == len(FEATURE_KEYS_V6)),
                      v7=(n_feat == len(FEATURE_KEYS_V7)),
                      v8=(n_feat == len(FEATURE_KEYS_V8)))]
        # classifier (= predict_proba) と regressor (= predict、 rollout 勝率を直接回帰、
        # 2026-06-18 検証ハーネス組み込み) の両対応。 regressor は [0,1] にクリップ。
        if hasattr(model, "predict_proba"):
            p = float(model.predict_proba(x)[0][1])
        else:
            p = min(1.0, max(0.0, float(model.predict(x)[0])))
        return (p - 0.5) * SCALE
    except Exception:
        return None
