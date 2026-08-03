# カード効果 人間レビュー待ちバックログ (自動生成)

> `scripts/effect_bugfix_escalate.py` が `optcg-effect-bugfix` ルーティンの各実行末尾で再生成。
> 自動修正ルーティンが直せなかった項目 (= 忠実な自動修正が困難で human の判断が要る) の一覧。
> 空なら「レビュー待ちなし」。 消化するには session で私 (Claude) に「pending review やって」と伝えるか、
> 各項目を手動修正 → skip 解除 / `_unimplemented` 実装 で対応する。

**合計: 0 件** (skip 0 / _unimplemented 0 / 近似・未実装 0)

現在レビュー待ちなし ✅

## 公式解釈の裁定待ち (2026-08-03 追加)

- **`don_minus_opp` で相手のドンをドンデッキに戻した時、相手の
  `on_self_don_returned_to_deck` (「自分の場のドン‼が…ドン‼デッキに戻された時」) は
  発動するか？**
  - 現状: Python は発動させない (`don_minus_opp` は `trigger_on_self_don_returned_to_deck`
    を呼ばない)。 Rust も Python に合わせた (2026-08-03)。
  - 疑問: 公式テキストは 「自分の場のドン‼が戻された時」 であって 「自分が戻した時」 では
    ないので、 相手の効果で戻された場合も満たすように読める。 該当カード = EB02-035
    サンジ&プリン / OP06-042 / OP06-076 / OP04-058 / OP12-040 等。
  - 判定できたら Python を直し、 Rust を追従させる (どちらか一方だけ直すと差分が出る)。
