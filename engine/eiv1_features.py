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
from typing import Any

from . import gbm_value

# EIV1 の feature 版:
#   - collect が corpus に保存する base = v15 (= 21 board + 8 駒種ラベル + 14 機能×timing、 43dim)。
#   - train/推論で使う実表現 = v16 (= v15 + 相手 leader matchup tag 13 + interaction 4、 60dim)。
#     v16 の追加 17 列は「保存済み state から再計算」できるので、 base を v15 に据えたまま corpus を
#     再収集せず v16 に拡張できる (= 盲目化しない設計の payoff)。
FEATURE_VER = "v15"        # corpus 保存 base (f フィールド)
TRAIN_FEATURE_VER = "v18"  # 配備の実表現 (= v15 + 相手 leader matchup 17 + belief 残り防御資源 4)。
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


def eiv1_train_vector(row: dict) -> list:
    """corpus 行 → v18 学習ベクトル = f(v15,43) + matchup(17) + belief残り防御資源(4) = 64dim。
    保存済み state から matchup/belief を復元して append (= 再収集なしで v18 化)。"""
    base = list(row.get("f", []))
    snap = row.get("state")
    mu = matchup_feats_from_snapshot(snap) if snap else [0.0] * 17
    br = belief_resource_feats_from_snapshot(snap) if snap else [0.0] * 4
    return base + mu + br
