# 公式裁定の記録 (engine 実装の根拠)

> engine の実装が **公式 Q&A / ルールのどれを根拠にしているか** を残す場所。
> 「なぜこう実装したか」 を後から追えるようにするのが目的で、 一次情報 (`db/faq/cardqa_*.json` /
> `db/rules/*.pdf`) の該当箇所を必ず引用する。
>
> ⚠ **`db/_pending_review.md` に書かないこと**。 あれは
> `scripts/effect_bugfix_escalate.py` が毎回 **全文を再生成** する自動レポートなので、
> 手書きした内容は cron (`optcg-effect-bugfix`、 4h ごと) の次回実行で消える
> (2026-08-04 に実際に消された)。 裁定のような恒久情報はこのファイルに置く。

---

## ドン‼が「戻された時」は誰の効果かを問わない (2026-08-04 決着)

**問**: `don_minus_opp` などで **相手の効果によって** 自分の場のドン‼がドン‼デッキに
戻された時、 「自分の場のドン‼が…ドン‼デッキに戻された時」 (`on_self_don_returned_to_deck`)
は発動するか？

**答**: **発動する**。

一次情報:
- `db/faq/cardqa_op_06.json` — 「自分のターン中に、**相手のカードの効果で**自分のドン!!が
  ドン!!デッキに戻された時、この【自分のターン中】効果を発動できますか？」 → **「はい、できます。」**
- `db/faq/cardqa_st_10.json` — 同趣旨 2 問 (【自分のターン中】/【ターン1回】 いずれも
  「はい、発動します。」)
- `db/faq/cardqa_op_02.json` — 「「場のドン!!がドン!!デッキに戻された時」とは、相手のドン!!が
  相手のドン!!デッキに戻された場合も含まれますか？」 → 「はい、含まれます。」

**結論**: トリガーは 「誰の効果で戻されたか」 を問わない。 owner = **戻された側**。
該当カード = EB02-035 サンジ&プリン / OP06-042 / OP06-076 / OP04-058 / OP12-040 等。

**実装**: Python `don_minus_opp` が `trigger_on_self_don_returned_to_deck(state, opp, me, ...)`
を呼ぶ。 Rust も同じ (`don_minus_opp` の `owner = opp_idx`)。 両エンジン実装済。

---

## 「トラッシュに置く」 は KO ではない (2026-08-04 是正)

**根拠**: 公式テキストは 「KOする」 と 「トラッシュに置く」 を **書き分けている**。
後者は場を離れるだけで 【KO時】は発動せず、 このターンの被 KO 数にも数えない。

**是正**: OP03-043 ガイモン 「そうした場合、このキャラをトラッシュに置く。」 の overlay が
`self_ko` (= KO) になっていたので `trash_self` へ直した。 overlay 全体で `self_ko` を使うのは
この 1 枚だけで、 公式テキストに 「KO」 の語が無かった。

**恒久ガード**: `tests/test_effect_interactions.py`
- `test_trash_self_cost_is_not_a_ko` — 被 KO 数が増えないことを固定
- `test_no_card_uses_self_ko_cost_against_official_text` — overlay 全走査で
  「公式テキストに『KO』が無いのに `self_ko`」 を検出

---

## 効果を無効にされたキャラの【KO時】は発動しない

**一次情報**: `db/faq/cardqa_op_09.json` / `cardqa_op_10.json` —
「効果を無効にされたキャラがKOされた場合、そのキャラの【KO時】効果は発動できますか？」
→ **「いいえ、できません」**

**実装上の注意**: 【KO時】は発動元が既に場外 (`self_inplay=None`) なので、 通常の
「効果無効」 gate を通らない。 **KO 直前の無効化状態を呼び出し側から渡す** 必要がある
(Python `trigger_on_ko(victim_effect_negated=...)` / Rust `note_ko_victim_negated`)。
⚠ 効果 KO 経路だけ入れて **バトル KO 経路に入れ忘れる** 事故が実際に起きた (2026-08-04)。

**恒久ガード**: `tests/test_effect_interactions.py` の
`test_negated_character_ko_does_not_fire_on_ko` (+ 対照テスト)。

---

## 【起動メイン】に【ターン1回】が無ければコストを払える限り何度でも

**根拠**: 公式テキストに 【ターン1回】 の表記が無い 【起動メイン】 に回数制限は無い。

**経緯**: engine が `cost.get("once_per_turn", True)` = **既定 True** で一律 1 回に制限して
いた (「無限ループ回避」 の意図的近似)。 2026-08-04 に撤去。

無限ループは **公式ルール側が防いでいた**: 該当 197 枚のうち 180 枚が自己制限的コスト
(このキャラをレスト等)、 11 枚が資源消費、 残る 2 枚 (EB04-016 トリ / OP10-030 スモーカー) は
公式の自己ロック 「その後、 このターン中、 キャラの効果でドン‼をアクティブにできない」 が
**overlay に未実装** だった (= 近似がこのバグを隠していた)。

詳細は memory `project_approximation_hides_bugs`。
