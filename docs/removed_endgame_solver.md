# `engine/endgame_solver.py` を削除した記録 (2026-08-24)

## 何だったか

「終盤厳密 search」 と称する 129 行のモジュール。 `solve_endgame()` が `EndgameResult`
(フィールド名 **`p_win_exact` = 厳密勝率**) を返す形になっていた。

## なぜ消したか

1. **誰も使っていなかった**。 `engine/` `scripts/` `api/` `tests/` `web/` を全走査して
   参照 0 件 (自分自身の docstring を除く)。
2. **中身が 「厳密」 ではなかった**。 実装は `lethal_planner` の攻撃合計と相手カウンターの
   P90 見積を比べて **0.95 / 0.6 / 0.2 のハードコード定数** を返すだけ。 docstring 自身が
   「ライフトリガー乱数の全展開は未実装 (= Step 1 では骨組みのみ)」
   「簡易: 0.95 とする (= 厳密値ではない)」 と書いていた。
3. → **名前 (`p_win_exact`) が中身を偽っている dead code**。 残すと将来誰かが
   「厳密勝率」 として信用する。 未実装の骨組みを 「実装済の何か」 に見せるのは
   [[project_approximation_hides_bugs]] と同じ型。

## 必要になったら

終盤厳密解は 「ライフトリガーの乱数を全展開する」 のが本体で、 それは
`lethal_planner` + determinization の上に作るべきもの。 骨組みを復活させるのではなく
**要求が出た時に設計から書く**。 参考: `engine/lethal_planner.py` /
[[project_lethal_calc_improvement]]。
