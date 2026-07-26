"""EIV1 の特徴表現 (card-aware・grounded・growable) — 2026-07-23。

EIV1 = 天井なしコツコツ強化の self-play Expert Iteration AI ([[project_eiv1_expert_iteration]])。
その "表現" レバー。 EBV2 の 21 匿名スカラー(盲目)を、 overlay 由来の駒種ラベルで grounding した
card-aware な起点にする。

現状の起点 = gbm_value v15 (= 43dim)。 3 層の card-aware grounded 表現:
  1. v2 board 21 = 匿名スカラー盤面(EBV2 相当)
  2. v14 駒種ラベル 8 = on-board を removal/blocker/effect/activatable で分解 (機能ラベル)
  3. v15 機能×timing 14 = search_engine(起動メインサーチ) vs search_body(登場時サーチ) 等を別列
     (= ohtsuki 要求「ラベル + timing 区別」)。 draw_engine/ramp/recovery/negate/aggression も per player。

⚠ growable の設計: ここに列を APPEND して次元を伸ばす (= 容量をデータと共に伸ばす③の"表現"側)。
gbm_score は model 次元で feature 版を自動判別するので、 新次元は gbm_value.features + _feat_for_dim に
版を足せば inference も追随 (v16, v17... と増やせる)。

成長ロードマップ (ohtsuki 要求「カードそのものも認識」):
  - grounded ラベル+timing = ここまで実装済 (色跨ぎ共有・data 効率良・学習不要)
  - card identity (= 同カテゴリ内の強弱の微差、 例: 強いサーチ vs 弱いサーチ) = **学習埋め込み**が要る。
    GBM は埋め込みを学習できない → 次段は value を小 NN 化 (embedding テーブル + MLP)。 これが
    「カードそのもの」を捉える成長ピースで、 data-hungry (= EIV1 の corpus を貯めてから)。 grounded を
    起点にすれば cold-start しない (未知カードもラベル+timing で汎化、 学習でその上に微差を乗せる)。
"""
from __future__ import annotations
import types
from typing import Any, Optional

from . import gbm_value

# EIV1 の feature 版:
#   - collect が corpus に保存する base = v15 (= 21 board + 8 駒種ラベル + 14 機能×timing、 43dim)。
#   - train/推論で使う実表現 = v16 (= v15 + 相手 leader matchup tag 13 + interaction 4、 60dim)。
#     v16 の追加 17 列は「保存済み state から再計算」できるので、 base を v15 に据えたまま corpus を
#     再収集せず v16 に拡張できる (= 盲目化しない設計の payoff)。
FEATURE_VER = "v15"        # corpus 保存 base (f フィールド)
TRAIN_FEATURE_VER = "v20"  # 配備の実表現 (= v18 + 盤面の個体解像度 20 + 除去の射程×的 10 = 94)。
# v19/v20 = 2026-07-23。 ohtsuki 指摘「『コスト4以下をKO』と『コスト1以下をKO』は角度が同じでも
# 矢印の長さが違う」。 card_labels は効果の向きしか持たず射程を捨てていた → card_magnitudes で
# overlay から機械導出。 射程は盤面ではほぼ発火しない (盤面から繰り返し撃てる除去は 129/4731 枚 =
# 除去は手札から飛ぶ) ので、 自分=手札の実カード / 相手=leader prior − 見た札 の belief で測る。
# 実測 (12 万行 / game 単位 split): v18 0.8286 → v19 0.8302 (+0.0017) → v20 0.8323 (+0.0037)。
# 序中盤ほど効く (turn1-4 +0.0066 / 5-7 +0.0053 / 8-10 +0.0031 / 11+ -0.0004)。
# v18 = 見た札(場+トラッシュ+バレ手札)で相手デッキ予測 → 残りカウンター/ブロッカーを推定 (opponent_deck_model
# seen 事後 belief − トラッシュ消費)。 生トラッシュ(旧 v17)は AUC null だったが belief と組むと +0.0039
# (中盤 turn5-7 で +0.008〜0.010)。 保存済み state から再収集なし再計算。


def eiv1_features(state: Any, me_idx: int) -> list:
    """corpus 保存用の base 特徴 (= v15、 43dim)。 collect が f として記録。"""
    return gbm_value.features(state, me_idx, v15=True)


def eiv1_dim() -> int:
    return len(gbm_value.FEATURE_KEYS_V15)


def matchup_feats_from_snapshot(snap: dict) -> list:
    """保存済み state snapshot から 相手リーダー matchup 特徴 (tag 13 + interaction 4 = 17) を復元。
    tag は相手 leader card_id、 interaction は相手 life/hand/don に依存 (全て snapshot に在る) →
    再収集せず既存 corpus を v16 に拡張できる。 snapshot 欠損時は neutral(全0)。"""
    try:
        def _mk(p):
            leader = types.SimpleNamespace(card=types.SimpleNamespace(card_id=p["leader"]["card_id"]))
            return types.SimpleNamespace(leader=leader, life=[0] * p["life_count"],
                                         hand=[0] * p["hand_count"], don_active=p.get("don_active", 0))
        fs = types.SimpleNamespace(players=[_mk(p) for p in snap["players"]])
        hi = snap["hero_idx"]
        return gbm_value._opp_matchup_tag_vector(fs, hi) + gbm_value._opp_matchup_interaction_vector(fs, hi)
    except Exception:
        return [0.0] * 17


_REPO = None


def _repo():
    global _REPO
    if _REPO is None:
        from pathlib import Path
        from engine.deck import CardRepository
        root = Path(__file__).resolve().parent.parent
        _REPO = CardRepository.from_json(str(root / "db" / "cards.json"))
    return _REPO


def trash_feats_from_snapshot(snap: dict) -> list:
    """保存済み snapshot の trash_card_ids から トラッシュ防御資源 (my/opp × counter総量, blocker数 = 4)
    を復元。 trash は公開情報 → 再収集せず既存 corpus を v17 に拡張できる。 欠損時は全0。"""
    try:
        repo = _repo()
        hi = snap["hero_idx"]

        def _z(p):
            ctr = blk = 0
            for cid in p.get("trash_card_ids", []):
                try:
                    c = repo.get(cid)
                except Exception:
                    continue
                ctr += int(getattr(c, "counter", 0) or 0)
                if getattr(c, "is_blocker", False):
                    blk += 1
            return float(ctr), float(blk)
        me = snap["players"][hi]
        opp = snap["players"][1 - hi]
        mc, mb = _z(me)
        oc, ob = _z(opp)
        return [mc, oc, mb, ob]  # my_ctr, opp_ctr, my_blk, opp_blk (= gbm_value._trash_resource_features 順)
    except Exception:
        return [0.0] * 4


def belief_resource_feats_from_snapshot(snap: dict) -> list:
    """保存済み snapshot から belief-based 残り防御資源 4 (opp: E[deck counter/blocker], 残りカウンター/
    ブロッカー) を復元。 seen = 場+トラッシュ+バレ手札。 gbm_value._belief_deck_totals (cache) を再利用 →
    live inference と同値。 = 再収集なしで v18 化。"""
    try:
        from collections import Counter
        from . import gbm_value as G
        hi = snap["hero_idx"]
        opp = snap["players"][1 - hi]
        lid = opp["leader"]["card_id"]
        ids = [f["card_id"] for f in opp.get("field", [])] + opp.get("trash_card_ids", []) \
            + list(opp.get("known_hand_card_ids", []) or [])
        seen = {k: v for k, v in Counter([i for i in ids if i]).items()}
        exp_c, exp_b = G._belief_deck_totals(lid, seen)
        if exp_c == 0.0 and exp_b == 0.0:
            return [0.0, 0.0, 0.0, 0.0]   # 未知 leader (belief 空) → neutral
        repo = _repo()
        tc = tb = 0
        for cid in opp.get("trash_card_ids", []):
            try:
                c = repo.get(cid)
            except Exception:
                continue
            tc += int(getattr(c, "counter", 0) or 0)
            tb += 1 if getattr(c, "is_blocker", False) else 0
        return [float(exp_c), float(exp_c - tc), float(exp_b), float(exp_b - tb)]
    except Exception:
        return [0.0, 0.0, 0.0, 0.0]


BOARD_DETAIL_KEYS = [
    # per player (my, opp) の順で 10 列ずつ = 20。 「盤面をもっと詳細に把握する」列 (v19)。
    "rm_reach_cost", "rm_reach_pw", "rm_cover_n", "rm_cover_pw", "top1_power",
    "top1_don", "top2_power", "power_spread", "max_cost", "eff_magnitude",
]


def board_detail_feats_from_snapshot(snap: dict) -> list:
    """保存済み snapshot の field (card_id/cost/power/attached_dons) から 盤面の詳細特徴 20 を復元。

    v15 までの盤面は「体数・合計パワー・ラベル別合計パワー」= 個体が潰れていた。 ここでは
      (a) 効果の**大きさ** (card_magnitudes = 除去の射程 等、 = 矢印の長さ)
      (b) **interaction** (自分の除去が今の相手盤面の何体に実際に届くか)
      (c) **個体の解像度** (top1/top2 のパワー・付与ドン・パワーの散らばり・最大コスト)
    を足す。 全て snapshot から再計算できる → 再収集なしで既存 corpus を v19 化できる。"""
    try:
        from . import card_magnitudes as CM
        hi = snap["hero_idx"]
        sides = [snap["players"][hi], snap["players"][1 - hi]]

        def _chars(p):
            return [c for c in (p.get("field") or []) if isinstance(c, dict)]

        def _side(p, other):
            fs, os_ = _chars(p), _chars(other)
            if not fs:
                return [0.0] * 10
            mags = [CM.for_card(c.get("card_id") or "") for c in fs]
            # (a) 盤面から繰り返し撃てる除去の射程 (登場時 = 使用済なので active のみ)
            reach = [(m["rm_active_cost"], m["rm_active_pw"]) for m in mags if m["rm_active_cost"] > 0]
            rc = max((r[0] for r in reach), default=0.0)
            rp = max((r[1] for r in reach), default=0.0)
            # (b) interaction: その射程が今の相手盤面の何体に届くか (union)
            cover = [c for c in os_
                     if any(float(c.get("cost") or 0) <= r[0] and float(c.get("power") or 0) <= r[1]
                            for r in reach)]
            cov_n = float(len(cover))
            cov_pw = sum(float(c.get("power") or 0) for c in cover) / 1000.0
            # (c) 個体の解像度
            powers = sorted((float(c.get("power") or 0) for c in fs), reverse=True)
            top1 = powers[0] / 1000.0
            top2 = (powers[1] / 1000.0) if len(powers) > 1 else 0.0
            spread = (powers[0] - powers[-1]) / 1000.0
            best = max(fs, key=lambda c: float(c.get("power") or 0))
            top1_don = float(best.get("attached_dons") or 0)
            max_cost = max((float(c.get("cost") or 0) for c in fs), default=0.0)
            mag = sum(m["draw"] + m["don"] + m["pump"] / 1000.0 + m["search"] / 2.0 + m["recover"]
                      for m in mags)
            return [rc, rp / 1000.0, cov_n, cov_pw, top1, top1_don, top2, spread, max_cost, mag]

        return _side(sides[0], sides[1]) + _side(sides[1], sides[0])
    except Exception:
        return [0.0] * 20


HAND_REACH_KEYS = [
    # v20 = 除去の「射程」を効く場所 (= 手札 / 相手の残りデッキ) に置いた 10 列。
    "my_hand_rm_n", "my_hand_rm_playable_n", "my_hand_rm_cover_n", "my_hand_rm_cover_pw",
    "my_hand_rm_cover_top",
    "opp_bel_rm_total", "opp_bel_threat_sum", "opp_bel_threat_max", "opp_bel_threat_top1",
    "opp_bel_threat_frac",
]

_BELIEF_RM_CACHE: dict = {}


def _belief_removal_table(leader_id: str) -> list:
    """leader prior から [(card_id, E[枚数], 除去 cost 射程, 除去 power 射程)] を作る (leader 単位 cache)。

    seen 条件付けは呼び出し側で「prior − 見た枚数」で行う (= 全 row で belief を引き直すと重い、
    かつ 『残り』の意味としてはこれで足りる)。"""
    tbl = _BELIEF_RM_CACHE.get(leader_id)
    if tbl is not None:
        return tbl
    tbl = []
    try:
        from . import card_magnitudes as CM
        from .opponent_deck_model import get_default_model
        bel = get_default_model().belief_for_leader(leader_id, None)
        for cid, info in (bel or {}).items():
            m = CM.for_card(cid)
            if m["rm_play_cost"] > 0 or m["rm_active_cost"] > 0:
                reach_c = max(m["rm_play_cost"], m["rm_active_cost"])
                reach_p = max(m["rm_play_pw"], m["rm_active_pw"])
                tbl.append((cid, float(info.get("exp_count", 0.0)), reach_c, reach_p))
    except Exception:
        tbl = []
    _BELIEF_RM_CACHE[leader_id] = tbl
    return tbl


def hand_reach_feats_from_snapshot(snap: dict) -> list:
    """v20: 除去の射程 × 的 の interaction を **手札 (自分) と belief (相手)** で測る 10 列。

    v19 で盤面に置いた射程列はほぼ発火しなかった (盤面から繰り返し撃てる除去は 129/4731 枚)。
    この game の除去は実質 **手札から飛ぶ** ので、 射程はそこで測る:
      - 自分側 = 手札の実カード (推論時も自分の手札は公開情報 → そのまま配備できる)
      - 相手側 = leader prior − 見た札 (= 公開情報のみ、 v18 の belief と同じ土俵)
    """
    try:
        from collections import Counter
        from . import card_magnitudes as CM
        repo = _repo()
        hi = snap["hero_idx"]
        me, opp = snap["players"][hi], snap["players"][1 - hi]
        my_f = [c for c in (me.get("field") or []) if isinstance(c, dict)]
        op_f = [c for c in (opp.get("field") or []) if isinstance(c, dict)]

        # --- 自分の手札の除去 × 今の相手盤面 ---
        don = float(me.get("don_active") or 0)
        hand_rm = []
        for cid in me.get("hand_card_ids", []) or []:
            m = CM.for_card(cid)
            if m["rm_play_cost"] <= 0:
                continue
            try:
                cost = float(getattr(repo.get(cid), "cost", 0) or 0)
            except Exception:
                cost = 99.0
            hand_rm.append((cost, m["rm_play_cost"], m["rm_play_pw"]))
        playable = [r for r in hand_rm if r[0] <= don]
        cover = [c for c in op_f
                 if any(float(c.get("cost") or 0) <= rc and float(c.get("power") or 0) <= rp
                        for _, rc, rp in playable)]
        cov_pw = [float(c.get("power") or 0) / 1000.0 for c in cover]
        mine = [float(len(hand_rm)), float(len(playable)), float(len(cover)),
                sum(cov_pw), max(cov_pw, default=0.0)]

        # --- 相手の残り除去 (belief) × 自分の盤面 ---
        tbl = _belief_removal_table(opp["leader"]["card_id"])
        if not tbl:
            return mine + [0.0] * 5
        seen = Counter([c["card_id"] for c in op_f] + list(opp.get("trash_card_ids", []) or [])
                       + list(opp.get("known_hand_card_ids", []) or []))
        rest = [(e - float(seen.get(cid, 0)), rc, rp) for cid, e, rc, rp in tbl]
        rest = [(max(e, 0.0), rc, rp) for e, rc, rp in rest]
        total = sum(e for e, _, _ in rest)
        masses = []
        for c in my_f:
            cc, cp = float(c.get("cost") or 0), float(c.get("power") or 0)
            masses.append(sum(e for e, rc, rp in rest if cc <= rc and cp <= rp))
        if my_f:
            top_i = max(range(len(my_f)), key=lambda i: float(my_f[i].get("power") or 0))
            theirs = [total, sum(masses), max(masses), masses[top_i],
                      float(sum(1 for m in masses if m > 0)) / float(len(my_f))]
        else:
            theirs = [total, 0.0, 0.0, 0.0, 0.0]
        return mine + theirs
    except Exception:
        return [0.0] * 10


# v21 = 94 + 24 (2026-07-27): カード効果シグネチャ (sig(card)) の盤面合成。 各盤面(自/相手)の
# キャラ sig を curated 12 次元で合計 = 「盤面にどんな効果があるか」を card-aware に表現。 候補プランで
# 盤面が変わる → sig 合成が変わる = selection-relevant (v6 と同じ shape)。 sig は overlay 由来で全カバー
# (= per-card 統計の疎さを効果類似で汎化)。 snapshot(field card_id)から計算 → 再収集なし。
_SIG_BOARD_DIMS = ["lbl_removal", "lbl_t_activate_main", "in_is_blocker", "lbl_negate",
                   "lbl_keyword_grant", "lbl_life_recovery", "lbl_hand_disrupt", "lbl_cost_reduce",
                   "lbl_search", "lbl_buff_power", "lbl_ramp_don", "lbl_protect"]


def sig_board_feats_from_snapshot(snap: dict) -> list:
    """自/相手盤面のキャラの効果シグネチャ合成 (curated 12 dim × 2 = 24)。 hero 盤面→opp 盤面の順。"""
    try:
        from . import card_sig as CS
        hi = snap["hero_idx"]
        out: list = []
        for p in (snap["players"][hi], snap["players"][1 - hi]):
            acc = [0.0] * len(_SIG_BOARD_DIMS)
            for c in (p.get("field") or []):
                if not isinstance(c, dict):
                    continue
                s = CS.for_card(c.get("card_id", "") or "")
                for i, k in enumerate(_SIG_BOARD_DIMS):
                    acc[i] += float(s.get(k, 0.0))
            out.extend(acc)
        return out
    except Exception:
        return [0.0] * (len(_SIG_BOARD_DIMS) * 2)


def eiv1_train_vector(row: dict) -> list:
    """corpus 行 → v20 学習ベクトル = f(v15,43) + matchup(17) + belief残り防御資源(4)
    + 盤面の個体解像度(20) + 除去の射程×的(10) = 94dim。
    全て保存済み state から復元できる → 再収集なしで v20 化 (= 盲目化しない設計の payoff)。"""
    base = list(row.get("f", []))
    snap = row.get("state")
    mu = matchup_feats_from_snapshot(snap) if snap else [0.0] * 17
    br = belief_resource_feats_from_snapshot(snap) if snap else [0.0] * 4
    bd = board_detail_feats_from_snapshot(snap) if snap else [0.0] * 20
    hr = hand_reach_feats_from_snapshot(snap) if snap else [0.0] * 10
    return base + mu + br + bd + hr + _spec_tail(snap)


def _spec_tail(snap: Optional[dict]) -> list:
    """自動 feature 探索で採用された動的列 (db/eiv1/feature_spec.json)。 無ければ空 = v20 のまま。"""
    from .feature_spec import active_spec, evaluate
    spec = active_spec()
    if not spec:
        return []
    return evaluate(snap, spec) if snap else [0.0] * len(spec)
