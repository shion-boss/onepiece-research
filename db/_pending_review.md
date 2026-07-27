# カード効果 人間レビュー待ちバックログ (自動生成)

> `scripts/effect_bugfix_escalate.py` が `optcg-effect-bugfix` ルーティンの各実行末尾で再生成。
> 自動修正ルーティンが直せなかった項目 (= 忠実な自動修正が困難で human の判断が要る) の一覧。
> 空なら「レビュー待ちなし」。 消化するには session で私 (Claude) に「pending review やって」と伝えるか、
> 各項目を手動修正 → skip 解除 / `_unimplemented` 実装 で対応する。

**合計: 1 件** (skip 1 / _unimplemented 0 / 近似・未実装 0)

## skip されているテスト (engine バグ等)

| テスト | ファイル | 診断 |
|---|---|---|
| `test_op10_047_on_attack_return_revo_pump_self` | test_backfill_auto_104.py | overlay bug: OP10-047 は effect に余分な return_to_hand (one_self_chara_filtered/filter空) があり コアラ自身まで手札に戻る。公式は コスト革命軍1枚のみ返し コアラは場に残り +3000。engine 非編集方針で人間レビューへ |
