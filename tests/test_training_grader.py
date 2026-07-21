"""training_grader の純関数 (value/AI 非依存) の回帰テスト。

grade_turn 全体は value model + 配備 AI を要し重いので、 ここでは判定閾値と
事実差テキスト生成が honest に働くかを固定する (= 「悪い手を良いと言わない」担保)。
"""
from engine.training_grader import verdict_for_gap, _fact_diffs, turn_facts


def test_verdict_tiers():
    # gap = p_best - p_user。 大きいほど「あなたの手が最善より劣る」。
    assert verdict_for_gap(0.0)["tier"] == "good"
    assert verdict_for_gap(0.02)["tier"] == "good"
    assert verdict_for_gap(0.05)["tier"] == "slight"
    assert verdict_for_gap(0.12)["tier"] == "bad"
    # 負 gap (= あなたが最善より上) も good 扱い (= 咎めない)。
    assert verdict_for_gap(-0.05)["tier"] == "good"


def test_fact_diffs_surfaces_don_waste():
    # あなた: DON 3枚使い残し・展開0。 最善: 使い残し1・展開2。
    user = {"opp_life_dealt": 0, "opp_chars_kod": 0, "my_chars_added": 0,
            "my_board_power": 3000, "don_unused": 3, "my_hand": 2}
    best = {"opp_life_dealt": 1, "opp_chars_kod": 0, "my_chars_added": 2,
            "my_board_power": 9000, "don_unused": 1, "my_hand": 1}
    reasons = _fact_diffs(user, best)
    joined = " / ".join(reasons)
    assert "DON" in joined  # 使い残しを指摘する
    assert "展開" in joined  # 盤面作りの遅れを指摘する
    assert any("ライフ" in r for r in reasons)  # 攻めの差を指摘する


def test_fact_diffs_empty_when_equal():
    # 互角 (= 同じ事実) なら理由は空 (= 良い手を咎めない)。
    facts = {"opp_life_dealt": 1, "opp_chars_kod": 0, "my_chars_added": 2,
             "my_board_power": 9000, "don_unused": 0, "my_hand": 2}
    assert _fact_diffs(facts, facts) == []
