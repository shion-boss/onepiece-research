# カード効果 人間レビュー待ちバックログ (自動生成)

> `scripts/effect_bugfix_escalate.py` が `optcg-effect-bugfix` ルーティンの各実行末尾で再生成。
> 自動修正ルーティンが直せなかった項目 (= 忠実な自動修正が困難で human の判断が要る) の一覧。
> 空なら「レビュー待ちなし」。 消化するには session で私 (Claude) に「pending review やって」と伝えるか、
> 各項目を手動修正 → skip 解除 / `_unimplemented` 実装 で対応する。

**合計: 1 件** (skip 1 / _unimplemented 0)

## skip されているテスト (engine バグ等)

| テスト | ファイル | 診断 |
|---|---|---|
| `test_op05_089_activate_main_recur_cost1_black_ai` | test_backfill_auto_061.py | engine/overlay 実バグ: OP05-089 overlay は search source=trash を使うが engine の search primitive は常に me.deck のみ探索し source 指定を無視するため トラッシュからの回収が発火しない (正しくは trash_to_hand primitive を使うべき、 OP05-088 は trash_to_hand で正常)。 engine 修正は人間レビューへ。 |
