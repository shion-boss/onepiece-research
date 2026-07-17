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

# v6don = 40 (2026-06-30): v6 + active DON 経済 2 列 (me/opp の don_active)。
# ohtsuki 観察『紫エネルが pay_don イベントを使いすぎて DON を戻しすぎ』([[feedback_don_quality_over_quantity]])。
# 根因: value の DON feature は total_don のみ (= _player_metrics) で **active DON (= 今動かせる DON)**
# を見ていない → pay_don イベントで active DON が枯れても value が気づけず乱発。 active_don を足すと
# 「イベントを打つべきか (= DON を払う価値があるか)」 を value が学習できる。 v6 の末尾に append (=
# v6don[:38] == v6、 column-slice 互換)。 per-deck 学習なので 6-DON エネル等は文脈込みで価格付けを学ぶ。
FEATURE_KEYS_V6DON = FEATURE_KEYS_V6 + ("don_active_me", "don_active_opp")

# v10 = 54 (2026-07-02): **agnostic value の own-deck 条件付け**。 v8(= v6 + 相手 role vector)に
# 自 leader の role vector(myrole 8)を足し、 matchup を **自archetype × 相手archetype × 盤面** で
# 対称に条件付ける。 per-deck value では自 deck が固定=定数で無意味(deploy-null)だが、 多デッキを
# pool して学習する 1 個の *agnostic* value では「今どの archetype を操縦中か」を GBM tree が deck 毎に
# 分岐して board 重みを可変化する essential な信号 = **user/未知デッキに汎化する非依存 value の鍵**。
# 全て inference 計算可(自/相手 leader は公開情報、 role vector は db/leader_role_vectors.json)。
FEATURE_KEYS_V10 = FEATURE_KEYS_V8 + tuple("myrole_" + r for r in _ROLE_DIMS)

# v11 = 41 (2026-07-03): **防御保持の意思決定を条件付ける threat×exposure interaction**
# (ohtsuki: 「ブロッカー付きキャラを攻撃に使わない方が良いターンと使っても平気なターン」)。
# 現 v6 の blocker 特徴は has_keyword_active で **rested を見ない** → ブロッカーで殴って exposure が
# 上がっても value に映らない穴があった。 v11 で:
#  - me_avail_blocker : **unrested** ブロッカー数 (= 攻撃で減る、 手ごとに変わる board 信号)。 穴の直接修正
#  - ix_incoming_unblocked : max(0, 相手 active 攻撃役 − 自 avail_blocker) = 次ターン通る攻撃見込み。
#      me_avail_blocker で手ごとに変わる → selection-relevant (v6 教訓: ゲーム内定数は順位を変えず null)
#  - ix_deck_threat_exposure : 相手デッキの速攻/aggro belief (db/opp_aggro_threat.json、 未見の rush
#      finisher) を 自 avail_blocker で gate = deck-level threat × exposure。 belief は定数だが interaction
#      で手ごとに変わる。 相手手札枚数/盤面は既に v6 base にある (opp_hand/opp_field_power)
FEATURE_KEYS_V11 = FEATURE_KEYS_V6 + (
    "me_avail_blocker", "ix_incoming_unblocked", "ix_deck_threat_exposure",
)

# v12 = 45 (2026-07-04): **サーチ等で中身バレした相手手札カード**(ohtsuki: 「相手の手札の中の
# サーチ等で取得した中身バレしている特定のカード」)。 engine は `Player.known_hand_card_ids` で
# 公開済カードを追跡し board_eval は使うのに、 学習 value(v11)に無かった gap(docs/evaluation_metrics_reference.md)。
#  - opp_known_finisher : 相手手札で見えたフィニッシャー数(= 確定した脅威)
#  - opp_known_removal  : 相手手札で見えた除去札数(= 自盤面が飛ぶリスク)
#  - opp_known_counter  : 相手手札で見えた counter 総量(= 自攻撃が通りにくい確定防御資源)
#  - ix_known_fin_expo  : 見えたフィニッシャー / (1+自 avail_blocker) = 脅威 × 自防御の交互作用(手ごとに変わる)
# = belief(v11 deck_threat)でなく **確定情報**。 隠匿の穴を確定情報で埋める。 block_residual 枠で安全検証。
# ⚠ 45 dim(v7=44 と衝突回避のため 4 列)。 dim 自動判別の一意性が必須。
FEATURE_KEYS_V12 = FEATURE_KEYS_V11 + (
    "opp_known_finisher", "opp_known_removal", "opp_known_counter", "ix_known_fin_expo",
)


def v2_anchor_value(state: Any, me_idx: int, anchor_path: str) -> float:
    """companion v2 model(21-dim)の P(win) を anchor feature として返す。 失敗時 0.5(neutral)。"""
    try:
        m = _load(anchor_path)
        # 明示 False で env (ONEPIECE_GBM_V5/V6/...) の上書きを遮断 → 純 v2 (21-dim) を保証。
        x21 = features(state, me_idx, rich=True, v3=False, v4=False, v5=False, v6=False, v7=False, v8=False, v10=False)
        if hasattr(m, "predict_proba"):
            return float(m.predict_proba([x21])[0][1])
        return min(1.0, max(0.0, float(m.predict([x21])[0])))
    except Exception:
        return 0.5


_AGGRO_THREAT_CACHE: dict = {}  # leader_id -> deck aggro index (lazy load)


def _avail_blockers(player: Any) -> int:
    """unrested(= 実際に防御できる)ブロッカー数。 has_keyword_active は rested を見ないので自前で。"""
    try:
        return sum(
            1 for c in player.characters
            if c.has_keyword_active("ブロッカー") and not getattr(c, "rested", False)
        )
    except Exception:
        return 0


def _opp_deck_aggro(state: Any, me_idx: int) -> float:
    """相手 leader の deck-level 速攻/aggro belief 指数 (db/opp_aggro_threat.json)。 未知 leader は 0。"""
    global _AGGRO_THREAT_CACHE
    if not _AGGRO_THREAT_CACHE:
        try:
            import json as _json
            p = _REPO_ROOT_RV() / "db" / "opp_aggro_threat.json"
            raw = _json.loads(p.read_text(encoding="utf-8"))
            _AGGRO_THREAT_CACHE = {
                lid: float(v.get("rush_exp", 0.0)) + 0.2 * float(v.get("aggro_exp", 0.0))
                for lid, v in raw.items()
            }
        except Exception:
            _AGGRO_THREAT_CACHE = {"_": 0.0}
    try:
        lid = state.players[1 - me_idx].leader.card.card_id
    except Exception:
        return 0.0
    return _AGGRO_THREAT_CACHE.get(lid, 0.0)


def _defense_threat_features(state: Any, me_idx: int) -> list:
    """v11: 防御保持の意思決定を条件付ける 3 特徴 (avail_blocker + threat×exposure interaction)。"""
    me_p = state.players[me_idx]
    opp_p = state.players[1 - me_idx]
    me_avail = _avail_blockers(me_p)
    # 相手の active 攻撃役 (= 次ターン殴ってくる駒。 rush でない召喚酔いは除く)
    try:
        opp_attackers = sum(
            1 for c in opp_p.characters
            if not getattr(c, "rested", False)
            and (not getattr(c, "summoning_sickness", False) or getattr(c, "is_rush_now", False))
        )
    except Exception:
        opp_attackers = 0
    incoming_unblocked = max(0.0, float(opp_attackers) - float(me_avail))
    deck_threat = _opp_deck_aggro(state, me_idx) / (1.0 + float(me_avail))
    return [float(me_avail), incoming_unblocked, deck_threat]


def _revealed_opp_features(state: Any, me_idx: int) -> list:
    """v12: サーチ等で中身バレした相手手札カードの脅威(known_hand_card_ids = 確定情報)。"""
    try:
        from .eval import opp_known_finisher_count, _get_card_role
        opp = state.players[1 - me_idx]
        known_fin = float(opp_known_finisher_count(opp))
        known_ids = list(getattr(opp, "known_hand_card_ids", []) or [])
        known_rem = float(sum(1 for cid in known_ids if _get_card_role(cid) == "removal"))
        # 見えた相手カードの counter 総量(hand の該当カードから)
        known_counter = 0
        hand_by_id = {}
        for c in opp.hand:
            hand_by_id.setdefault(c.card_id, []).append(int(getattr(c, "counter", 0) or 0))
        for cid in known_ids:
            if hand_by_id.get(cid):
                known_counter += hand_by_id[cid].pop()
    except Exception:
        return [0.0, 0.0, 0.0, 0.0]
    me_avail = _avail_blockers(state.players[me_idx])
    ix = known_fin / (1.0 + float(me_avail))
    return [known_fin, known_rem, float(known_counter), ix]


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


def _my_role_vector(state: Any, me_idx: int) -> list:
    """自分 leader → role-composition signature(自デッキ archetype、 8次元)。 `_opp_role_vector` の
    own-side 対称。 未知 leader は全0。 per-deck value では定数で無意味だが、 多デッキ pool の *agnostic*
    value では「自分が何 archetype を操縦中か」を 1 model が deck 毎に可変化する essential な条件付け。"""
    global _OPP_ROLE_CACHE
    if _OPP_ROLE_CACHE is None:
        try:
            import json as _json
            p = _REPO_ROOT_RV() / "db" / "leader_role_vectors.json"
            _OPP_ROLE_CACHE = _json.loads(p.read_text(encoding="utf-8")).get("leaders", {})
        except Exception:
            _OPP_ROLE_CACHE = {}
    try:
        lid = state.players[me_idx].leader.card.card_id
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
             v7: Optional[bool] = None, v8: Optional[bool] = None,
             v6don: Optional[bool] = None, v10: Optional[bool] = None,
             v11: Optional[bool] = None, v12: Optional[bool] = None) -> list:
    """GameState + me_idx → feature vector。 rich=True で v2 (21)、 既定は env
    ONEPIECE_GBM_RICH (= 学習時に set)。 推論は gbm_score が model 次元で自動判別。
    v5=True (env ONEPIECE_GBM_V5) で 相手 leader の matchup tag 13 列を追加 (= 34、 matchup-条件付き)。
    v6=True (env ONEPIECE_GBM_V6) で v5 + matchup interaction 4 列 (= 38、 board×matchup の交互作用)。
    v7=True (env ONEPIECE_GBM_V7) で v6 + balance 6 列 (= 44、 own-plan×opp-denial のマッチ毎バランス)。"""
    from .eval import _player_metrics
    me = _player_metrics(state.players[me_idx])
    opp = _player_metrics(state.players[1 - me_idx])
    # 手札の質 nudge (= ONEPIECE_HAND_QUALITY_W、 既定 0 で完全 no-op)。 GBM の hand feature は
    # 枚数しか見ず、 勝ち札(finisher)を握っているかの「質」を区別できない。 my_hand/opp_hand を
    # finisher 数で弱く底上げして「良い手札を保持する価値」を value に薄く乗せる。 discount と
    # 同じく balanced sweep 用 (ohtsuki 2026-07-17「係数で微調整・比較して balance」)。
    mh, oh = me["hand"], opp["hand"]
    import os as _os_hq
    _hqw = 0.0
    try:
        _hqw = float(_os_hq.environ.get("ONEPIECE_HAND_QUALITY_W", "0"))
    except Exception:
        _hqw = 0.0
    if _hqw > 0.0:
        # 質 = 手札の「実戦力」= 高パワー(≥5000)脅威 + 高counter(≥2000)守備札 の枚数。
        # finisher role は分類が疎で no-op になりやすいので、 直接計算できる robust な proxy を使う。
        def _hq(p):
            return sum(
                1 for c in p.hand
                if int(getattr(c, "power", 0) or 0) >= 5000
                or int(getattr(c, "counter", 0) or 0) >= 2000
            )
        mh = me["hand"] + _hqw * _hq(state.players[me_idx])
        oh = opp["hand"] + _hqw * _hq(state.players[1 - me_idx])
    base = [
        me["life"] - opp["life"],
        me["field_count"] - opp["field_count"],
        me["field_power"] - opp["field_power"],
        mh - oh,
        me["don"] - opp["don"],
        me["blocker"] - opp["blocker"],
        me["attached_don"] - opp["attached_don"],
        me["active_chara"] - opp["active_chara"],
        me["life"], opp["life"], mh, oh,
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
    if v6don is None:
        v6don = os.environ.get("ONEPIECE_GBM_V6DON") == "1"
    if v10 is None:
        v10 = os.environ.get("ONEPIECE_GBM_V10") == "1"
    if v11 is None:
        v11 = os.environ.get("ONEPIECE_GBM_V11") == "1"
    if v12 is None:
        v12 = os.environ.get("ONEPIECE_GBM_V12") == "1"
    if v12:
        v11 = True  # v12 ⊃ v11 (+ 中身バレ相手カード)。 v11 の 3 列の後に 3 列 append。
    if v11:
        v6 = True  # v11 ⊃ v6 (+ defense-threat interaction)。 末尾に 3 列 append。
    if v10:
        v8 = True  # v10 ⊃ v8 (= v6 + opp role) + 自 role vector。 末尾に myrole を append。
    if v6don:
        v6 = True  # v6don ⊃ v6 (+ active DON 経済)。 末尾に don_active を append。
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
    # my_counter/opp_counter = 手札の守備資源。 既定は shield counter (= .counter 値) の合計だが、
    # ⚠ 旧実装は【カウンター】EVENT (神避/放電 等、 .counter=0 で効果 pump) を 0 と数え、
    #   守備 counter-event を手札に温存する価値が value に全く乗らなかった (= ohtsuki 2026-07-17
    #   「カウンターがついてるカードは手札で持っても価値がある、 盤面展開だけ良しとする構造はだめ」)。
    #   ONEPIECE_COUNTER_EVENT_DEF=1 で counter-event の pump も実効カウンター値に算入する。
    #   ⚠ GBM は旧定義 (shield のみ) で学習済 = 有効化時は my_counter 分布が OOD にずれるので、
    #   本来は再学習が要る (= まず gated で構造の正しさを確認 → A/B → 再学習)。
    import os as _os_ce
    if _os_ce.environ.get("ONEPIECE_COUNTER_EVENT_DEF") == "1":
        from .hand_estimator import _effective_counter_value as _ecv
        ov = getattr(state, "effects_overlay", None)
        my_ln = getattr(getattr(me_p.leader, "card", None), "name", "")
        opp_ln = getattr(getattr(opp_p.leader, "card", None), "name", "")
        my_counter = sum(_ecv(c, ov, my_ln) for c in me_p.hand)
        opp_counter = sum(_ecv(c, ov, opp_ln) for c in opp_p.hand)
    else:
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
    if v10:
        # 自 leader の role vector (= own-deck archetype 条件付け)。 v8 の opp role の直後に append し
        # FEATURE_KEYS_V10 = FEATURE_KEYS_V8 + myrole の列順と一致させる。
        out += _my_role_vector(state, me_idx)
    if v6don:
        # active DON 経済 (= 今動かせる DON)。 DON 配分 (召喚/イベント/付与) の最適化を value が
        # 学習するための根本 feature ([[feedback_don_quality_over_quantity]])。 v6 末尾に append。
        out += [
            int(getattr(me_p, "don_active", 0) or 0),
            int(getattr(opp_p, "don_active", 0) or 0),
        ]
    if v11:
        out += _defense_threat_features(state, me_idx)
    if v12:
        out += _revealed_opp_features(state, me_idx)
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


def _feat_for_dim(state, me_idx, n):
    """次元 n に一致する feature version を自動判別して返す。"""
    return features(state, me_idx,
                    rich=(n == len(FEATURE_KEYS_V2)), v3=(n == len(FEATURE_KEYS_V3)),
                    v4=(n == len(FEATURE_KEYS_V4)), v5=(n == len(FEATURE_KEYS_V5)),
                    v6=(n == len(FEATURE_KEYS_V6)), v7=(n == len(FEATURE_KEYS_V7)),
                    v8=(n == len(FEATURE_KEYS_V8)), v6don=(n == len(FEATURE_KEYS_V6DON)),
                    v10=(n == len(FEATURE_KEYS_V10)), v11=(n == len(FEATURE_KEYS_V11)),
                    v12=(n == len(FEATURE_KEYS_V12)))


# prefix 一致で slice 再利用できる次元(V1⊂V2⊂V5⊂V6⊂V11⊂V12 の chain のみ。 v3/v4/v9/v6don/v8/v10 は
# v2 から分岐するので不可)。 _feats[:n] は n がこの集合のときだけ安全。
_PREFIX_SAFE_DIMS = frozenset({17, 21, 34, 38, 41, 45})


def _reuse_ok(feats, n):
    return feats is not None and len(feats) >= n and n in _PREFIX_SAFE_DIMS


def _fast_val(model: Any, x: list) -> float:
    """GB classifier/regressor を float32 _raw_predict で高速評価(sklearn の validate_data/check_array
    の per-call 検証を回避、 profile: value の predict の ~1.4x)。 classifier=P(win)(sigmoid)、
    regressor=raw。 想定外は標準 predict に fallback(= 完全に安全)。"""
    try:
        import numpy as _np
        X = _np.asarray([x], dtype=_np.float32)
        raw = float(model._raw_predict(X).ravel()[0])
        if hasattr(model, "predict_proba"):
            return 1.0 / (1.0 + _np.exp(-raw))  # classifier: sigmoid(decision)
        return raw  # regressor: _raw_predict == predict
    except Exception:
        if hasattr(model, "predict_proba"):
            return float(model.predict_proba([x])[0][1])
        return float(model.predict([x])[0])


def _model_pwin(model: Any, state: Any, me_idx: int, _feats: Optional[list] = None) -> float:
    """任意 model (plain GBM / v9_residual / block_residual dict) の P(win) を [0,1] で返す。
    dict wrapper の anchor が更に dict でも **再帰で解ける** → 反復で value を合成できる
    (V_{k+1} = block_residual(anchor=V_k))。 [[project_block_value_architecture]]

    ⚡ 速度: FEATURE_KEYS_V1⊂V2⊂V5⊂V6⊂V11⊂V12 は prefix 一致(features() が prefix 順に build)
    なので、 最大次元の feature を 1 回計算し小次元は slice で再利用(_feats)。 block_residual の
    anchor(v6=38)+resid(v11=41)で 2 回計算していた feature を 1 回に(profile: value の ~半分が feature 計算)。"""
    if isinstance(model, dict) and model.get("kind") == "v9_residual":
        feat38 = _feats[:38] if _reuse_ok(_feats, 38) \
            else features(state, me_idx, v6=True, v7=False, v8=False, v10=False)
        p_anchor = _model_pwin(model["anchor"], state, me_idx, _feats=feat38)
        resid = _fast_val(model["resid"], feat38)
        return min(1.0, max(0.0, p_anchor + float(model.get("lam", 1.0)) * resid))
    if isinstance(model, dict) and model.get("kind") == "block_residual":
        rn = int(getattr(model["resid"], "n_features_in_", len(FEATURE_KEYS_V11)))
        rfeat = _feats[:rn] if _reuse_ok(_feats, rn) \
            else features(state, me_idx, v12=(rn == len(FEATURE_KEYS_V12)),
                          v11=(rn == len(FEATURE_KEYS_V11)))
        # anchor は rfeat の prefix を再利用(v6⊂v11⊂v12 の prefix 一致)
        p_anchor = _model_pwin(model["anchor"], state, me_idx, _feats=rfeat)
        resid = _fast_val(model["resid"], rfeat)
        return min(1.0, max(0.0, p_anchor + float(model.get("lam", 1.0)) * resid))
    # plain sklearn model (次元自動判別、 classifier/regressor 両対応)
    n = int(getattr(model, "n_features_in_", len(FEATURE_KEYS)))
    x = _feats[:n] if _reuse_ok(_feats, n) else _feat_for_dim(state, me_idx, n)
    v = _fast_val(model, x)
    return v if hasattr(model, "predict_proba") else min(1.0, max(0.0, v))


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
        # v9_residual / block_residual(anchor が更に dict でも再帰)/ plain GBM を _model_pwin で
        # 統一処理。 anchor 合成可 → V_{k+1}=block_residual(anchor=V_k) で反復できる。
        p = _model_pwin(_load(path), state, me_idx)
        return (p - 0.5) * SCALE
    except Exception:
        return None
