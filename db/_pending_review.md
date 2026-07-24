# カード効果 人間レビュー待ちバックログ (自動生成)

> `scripts/effect_bugfix_escalate.py` が `optcg-effect-bugfix` ルーティンの各実行末尾で再生成。
> 自動修正ルーティンが直せなかった項目 (= 忠実な自動修正が困難で human の判断が要る) の一覧。
> 空なら「レビュー待ちなし」。 消化するには session で私 (Claude) に「pending review やって」と伝えるか、
> 各項目を手動修正 → skip 解除 / `_unimplemented` 実装 で対応する。

**合計: 6 件** (skip 0 / _unimplemented 0 / 近似・未実装 6)

## overlay 近似・未実装マーカー (engine 機構が要る = engine/human レビュー)

> `_missing_effect` / `_approx_note` / gap 系 `_doc`。 効果を忠実表現できず近似
> している箇所 (多くは safely-incomplete = 誤動作せず no-op)。 新規 primitive/機構が要る。

| card_id | marker | 診断 |
|---|---|---|
| OP10-099 | `_approx_note` | cost: 自ライフ表向き は 簡略 (engine 未対応) |
| OP13-119 | `_doc` | 「そうした場合、相手は自身の手札からコスト4以下のキャラ1枚までを、登場させる」 の opp 報酬は engine 未配線 (= 相手の forced 行動)。 optional 部分のみ実装。 |
| OP15-059 | `_doc` | 相手の don 戻し選択は engine 未実装 → 簡略: AI は常に -2000 適用 (= 相手は払わない 前提)。 optional: true は『-2000 適用 する/しない』 の選択。 |
| P-117 | `_missing_effect` | 自デッキ上1枚をトラッシュ (= self-deck-mill、 deck-out 特殊勝利を進める。 primitive 要) |
| ST13-001 | `_missing_effect` | 自コスト3+パワー7000+キャラをライフに表向き加える cost → 自キャラ+2000 (= face-up-life cost 未対応) |
| ST13-002 | `_missing_effect` | 自ライフ表向きカードすべてをトラッシュ (= 表向きライフ未モデル、 face-up-life 機構要) |
