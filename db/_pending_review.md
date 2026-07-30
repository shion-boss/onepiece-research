# カード効果 人間レビュー待ちバックログ (自動生成)

> `scripts/effect_bugfix_escalate.py` が `optcg-effect-bugfix` ルーティンの各実行末尾で再生成。
> 自動修正ルーティンが直せなかった項目 (= 忠実な自動修正が困難で human の判断が要る) の一覧。
> 空なら「レビュー待ちなし」。 消化するには session で私 (Claude) に「pending review やって」と伝えるか、
> 各項目を手動修正 → skip 解除 / `_unimplemented` 実装 で対応する。

**合計: 2 件** (skip 2 / _unimplemented 0 / 近似・未実装 0)

## skip されているテスト (engine バグ等)

| テスト | ファイル | 診断 |
|---|---|---|
| `test_op13_053_on_attack_ko_cost_draw_and_banish` | test_backfill_auto_128.py | overlay bug: OP13-053 の on_attack effect が公式テキストの 『カード1枚を引き』(draw:1) を欠き give_keyword バニッシュ のみ。 公式テキスト忠実な assert が通らないため skip。 overlay 修正は人間レビュー。 |
| `test_op13_075_main_add_rested_don_when_roger_and_attached_ai` | test_backfill_auto_129.py | overlay/engine bug: OP13-075 の main 条件 leader_name が全角 『ゴール・Ｄ・ロジャー』だが CardDef.name は半角 D に正規化される (『ゴール・D・ロジャー』)。 leader_name プリミティブは leader_name_contains と違い 半角/全角 D の normalize を行わないため 実 leader (OP13-003) で条件が常に不一致になり main 効果が発火しない。 公式テ... |
