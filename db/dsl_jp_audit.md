# DSL → 日本語 vs 公式テキスト 比較 audit

全 1 件の mismatch を検出。

## 重要度サマリ

- **sev 5**: 1 件

## 種類別件数

- `marker__unimplemented`: 1

## sev 5 (= 致命) 上位 50 件

### OP11-092 — marker__unimplemented
- **公式**: 【登場時】自分の手札1枚を捨てることができる：カード1枚を引き、自分のトラッシュから「ヘルメッポ」以外のコスト8以下の特徴《SWORD》を持つキャラカード1枚までを、登場させる。その後、このターン終了時、この効果で登場させたキャラ1枚を持ち主のデッキの下に置く。
- **renderer**: 【登場時】[手札を1枚捨てる]カード1枚を引く、 自分のトラッシュから特徴《SWORD》(ヘルメッポを除く)CHARACTERコスト8以下カードを場に出す、 [未実装: ターン終了時、 この効果で登場させたキャラ1枚を持ち主のデッキ下 (= tracked_played_chara primitive 未実装)]
- note: simplification marker remains

## sev 4 上位 50 件
