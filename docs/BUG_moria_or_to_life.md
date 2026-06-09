# ✅ RESOLVED — BUG (overlay fidelity): モリア OP14-104 の「ライフに加えるか登場させる」選択が欠落

> **修正済 (2026-06-09、 commit)**: 下記「修正方針」を実装。 `play_from_trash` に `or_to_life` flag +
> `play_from_trash_or_life_pick` modal (human のみ、 AI は従来通り登場=matrix/AI不変)、 web UI
> `PlayFromTrashOrLifePickModal`、 regression test `tests/test_op14_104_moria_or_to_life.py` 5件。
> pytest 821 pass / tsc clean / UI契約リンタ green。

**発見**: 2026-06-09、 claude_vs_ai campaign deck5 (cardrush_1439 青黄ナミ) g1 turn11。

## 症状
ゲッコー・モリア OP14-104 の【登場時】公式テキスト:
> 自分のトラッシュからコスト4以下の特徴《スリラーバーク海賊団》を持つキャラカード1枚までを、**ライフの上に表向きで加えるか登場させる**。

= プレイヤーが「ライフに加える」 か 「登場させる」 を**選択**する効果。

しかし overlay (`db/card_effects.json` OP14-104 / OP14-104_p1) は:
```json
{"when":"on_play","do":[{"play_from_trash":{"filter":{"category":"CHARACTER","cost_le":4,"feature":"スリラーバーク海賊団"},"limit":1}}]}
```
= `play_from_trash`(登場)のみ。**「ライフに加える」分岐が欠落**。

human プレイ中、候補1枚(クマシー)が**選択肢なしで auto 登場**された。私はライフ2で「ライフに加える(+1 life)」を選びたかったが提示されなかった。

## 重要度
- **低〜中 (fidelity gap、 correctness violation ではない)**: 登場は合法な部分解決で、 human は害されない(ボディを得る)。 1399 の auto-discard バグ(人間のカードを勝手に捨てる=害)とは異なり、 これは益を与える。
- ただし公式テキストの選択肢が human に提示されない = **「人間の判断を復元」原則([[project_human_judgment_restore]])違反**。

## 修正方針 (専用タスク)
1. `play_from_trash` に `or_to_life: true` flag を追加。 set 時 + human acting + 候補ありで destination 選択 modal を立てる(候補×{ライフ/登場} + skip)。 **AI は従来通り登場(matrix/AI 不変)**。
2. 新 pending_choice kind `play_from_trash_or_life_pick` の resolution: `dest=="life"` → `me.life.insert(0, card)` + `me.face_up_life_count = min(+1, len(life))`; `dest=="play"` → 既存 play_from_trash 経路を `_picks_idx` で再呼出。
3. overlay OP14-104 + OP14-104_p1 に `"or_to_life": true` を追加。
4. regression test (human で モリア on_play → 選択 modal、 life 分岐で +1 life)。
5. pytest 全 green 確認。

## 関連
- 同型「ライフに加えるか登場」の choice は OP14-104 (+_p1) のみ (全 4518 カード grep 確認)。 他の「ライフに表向きで加える」 21 件は必須 (`hand_to_self_life` 等で実装済)。
- ライフ挿入機構は `engine/effects.py:6335 hand_to_self_life` (`me.life` 操作) を参照。
