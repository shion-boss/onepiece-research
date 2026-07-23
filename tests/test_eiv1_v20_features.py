"""v19 (盤面の個体解像度) / v20 (除去の射程 × 的) のテスト。

⚠ 一番大事なのは **live state と保存済み snapshot で列が一致すること**。 学習は corpus の
snapshot、 推論は live state から同じ列を作るので、 ズレると value が静かに壊れる。
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from engine import card_magnitudes as CM
from engine import gbm_value as gv
from engine.deck import CardRepository, make_deck_from_dict
from engine.eiv1_features import (
    board_detail_feats_from_snapshot, hand_reach_feats_from_snapshot,
)
from engine.game import play_until_main, setup_game
from engine.game_corpus import snapshot_state

_ROOT = Path(__file__).resolve().parent.parent


def _state(me_slug: str, opp_slug: str, seed: int = 1):
    repo = CardRepository.from_json(_ROOT / "db" / "cards.json")
    me = make_deck_from_dict(json.loads((_ROOT / "decks" / f"{me_slug}.json").read_text(encoding="utf-8")), repo)
    opp = make_deck_from_dict(json.loads((_ROOT / "decks" / f"{opp_slug}.json").read_text(encoding="utf-8")), repo)
    st = setup_game(me, opp, rng=random.Random(seed), first_player=0)
    play_until_main(st)
    return st


def test_dimensions_match_keys():
    st = _state("cardrush_1454", "cardrush_1342")
    assert len(gv.features(st, 0, v19=True)) == len(gv.FEATURE_KEYS_V19) == 84
    assert len(gv.features(st, 0, v20=True)) == len(gv.FEATURE_KEYS_V20) == 94


def test_v20_is_superset_of_v18():
    """列順が v18 ⊂ v19 ⊂ v20 であること (= 既存モデルの列を壊していない)。"""
    st = _state("cardrush_1454", "cardrush_1342")
    f18 = gv.features(st, 0, v18=True)
    f19 = gv.features(st, 0, v19=True)
    f20 = gv.features(st, 0, v20=True)
    assert f19[:len(f18)] == f18
    assert f20[:len(f19)] == f19


def test_live_matches_snapshot():
    """live state の列 == 同じ state の snapshot から復元した列 (学習と推論のズレ防止)。"""
    for seed in (1, 7, 23):
        st = _state("cardrush_1454", "cardrush_1342", seed=seed)
        for me_idx in (0, 1):
            snap = snapshot_state(st)
            snap["hero_idx"] = me_idx
            live = gv.features(st, me_idx, v20=True)
            n18 = len(gv.FEATURE_KEYS_V18)
            assert live[n18:n18 + 20] == board_detail_feats_from_snapshot(snap)
            assert live[n18 + 20:] == hand_reach_feats_from_snapshot(snap)


def test_feat_for_dim_dispatch():
    """model 次元 84/94 から正しい版が選ばれること (gbm_score の自動判別経路)。"""
    st = _state("cardrush_1454", "cardrush_1342")
    assert len(gv._feat_for_dim(st, 0, 84)) == 84
    assert len(gv._feat_for_dim(st, 0, 94)) == 94


def test_magnitude_distinguishes_removal_reach():
    """ohtsuki 指摘の核: 『コスト4以下をKO』と『コスト1以下をKO』が別の値になること。"""
    db = CM.magnitudes_db()
    reaches = {round(m["rm_play_cost"]) for m in db.values() if m["rm_play_cost"] > 0}
    assert len(reaches) >= 5, f"射程が潰れている: {reaches}"
    # 条件なし除去は条件付きより射程が大きい
    assert max(reaches) >= CM.UNCOND_COST
    # 除去を持たないカードは 0 のまま (誤検出しない)
    assert db["OP01-016"]["rm_play_cost"] == 0.0   # ナミ = デッキサーチのみ


# --- 動的 feature spec (自動 feature 探索の土台) --------------------------------


def test_spec_generator_is_deterministic_and_named():
    from engine import feature_spec as FS
    a, b = FS.generate_candidates(), FS.generate_candidates()
    assert a == b and len(a) > 100
    names = [FS.col_name(c) for c in a]
    assert len(names) == len(set(names)), "列名が重複している"


def test_spec_evaluate_matches_live_state():
    """spec 列も live state と snapshot で一致すること (学習と推論のズレ防止)。"""
    from engine import feature_spec as FS
    spec = FS.generate_candidates()[:60] + FS.generate_interactions(FS.generate_candidates()[:3])
    for seed in (2, 11):
        st = _state("cardrush_1454", "cardrush_1342", seed=seed)
        for me_idx in (0, 1):
            snap = snapshot_state(st)
            snap["hero_idx"] = me_idx
            assert FS.evaluate(snap, spec) == FS.evaluate(gv._mini_snap(st, me_idx), spec)


def test_empty_spec_is_noop():
    from engine import feature_spec as FS
    st = _state("cardrush_1454", "cardrush_1342")
    assert FS.evaluate(gv._mini_snap(st, 0), []) == []
    assert len(gv.features(st, 0, v20=True)) == 94   # spec 無しなら v20 のまま


def test_spec_columns_use_only_fair_information():
    """公平性: 自分のライフ中身 / 相手の生手札を zone に含めない (推論時に知り得ない)。"""
    from engine import feature_spec as FS
    st = _state("cardrush_1454", "cardrush_1342")
    snap = snapshot_state(st)
    snap["hero_idx"] = 0
    for zone in FS.ZONES:
        assert "life" not in zone
    cards = FS.evaluate(snap, [{"k": "agg", "z": "opp_seen_hand", "c": "removal", "s": "count"}])
    assert cards == [0.0] or cards[0] >= 0.0   # 公開履歴のみ


def test_feature_blocks_are_not_silently_dead():
    """⚠ 回帰テスト: 特徴ブロックが「例外を握り潰して常にゼロ」になっていないこと。

    実例 (2026-07-23): gbm_value に `from pathlib import Path` が無く、 belief 特徴が
    NameError → except で (0.0, 0.0) を返し続けていた。 4 列が配備直後から死んでいたのに
    誰も気づけなかった。 ゼロ埋めの degrade は安全側に見えて **静かに壊れる**ので、
    「実局面で意味のある値が入る」ことをテストで固定する。
    """
    from engine.eiv1_features import belief_resource_feats_from_snapshot
    st = _state("cardrush_1454", "cardrush_1342", seed=5)
    # 数ターン進めて盤面/トラッシュが動いた状態にする
    from engine.ai import GreedyAI, play_one_action
    ais = [GreedyAI(rng=random.Random(1)), GreedyAI(rng=random.Random(2))]
    for _ in range(60):
        if st.game_over:
            break
        try:
            play_one_action(st, ais[st.turn_player_idx], ais[1 - st.turn_player_idx])
        except Exception:
            break
    snap = snapshot_state(st)
    snap["hero_idx"] = 0
    bel = belief_resource_feats_from_snapshot(snap)
    assert any(abs(v) > 0 for v in bel), f"belief 特徴が全ゼロ (degrade したまま): {bel}"
    # live 側も同様 (v20 の belief 4 列)
    live = gv.features(st, 0, v20=True)
    n16 = len(gv.FEATURE_KEYS_V16)
    assert any(abs(v) > 0 for v in live[n16:n16 + 4]), "live の belief 4 列が全ゼロ"


def test_counter_prefers_already_revealed_card():
    """同じ効果なら『相手にバレている札』から切る (情報の非対称性を減らさない)。"""
    from engine.ai import GreedyAI

    class _C:
        def __init__(self, cid, counter):
            self.card_id, self.counter = cid, counter
    ai = GreedyAI(rng=random.Random(0))
    # 同じ counter 値 2 枚。 片方 (index 1) だけ相手に割れている
    hand = [_C("AAA-001", 1000), _C("BBB-002", 1000)]
    picked = ai._optimal_counter_combo(hand, gap=500, known=["BBB-002"])
    assert picked == [1], f"バレている札を優先すべき: {picked}"
    # known 情報が無ければ従来通り (先頭)
    assert ai._optimal_counter_combo(hand, gap=500) == [0]


def test_public_search_records_known_hand_but_private_does_not():
    """公式テキストが『公開し手札に加える』なら記録、 『見て』だけなら記録しない。"""
    import json as _json
    from pathlib import Path as _P
    ov = _json.loads((_ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    pub = priv = 0
    for cid, blocks in ov.items():
        if cid.startswith("_") or not isinstance(blocks, list):
            continue
        for b in blocks:
            if not isinstance(b, dict):
                continue
            text = b.get("_text") or ""

            def _walk(node):
                nonlocal pub, priv
                if isinstance(node, dict):
                    for k, v in node.items():
                        if k in ("search_top_n", "search") and isinstance(v, dict) \
                                and v.get("public") is not None:
                            if v["public"]:
                                pub += 1
                                assert "公開" in text, f"{cid}: 非公開テキストに public=True"
                            else:
                                priv += 1
                                assert "公開" not in text, f"{cid}: 公開テキストに public=False"
                        _walk(v)
                elif isinstance(node, list):
                    for x in node:
                        _walk(x)
            _walk(b.get("do"))
    assert pub > 100 and priv > 20, f"フラグ付与が不足 (公開 {pub} / 非公開 {priv})"
