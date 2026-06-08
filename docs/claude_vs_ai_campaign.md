# Claude vs AI 全デッキ・キャンペーン (LLM=Claude が 16デッキ各5戦)

> **目的** (ohtsuki 指示 2026-06-08): 「君は俺と同等以上にプレイ上手い可能性ある。他15デッキも ClaudevsAI で5戦ずつ戦い、 ①バグ修正 ②今後の AI 人間越えの手がかり を見つけよう。 学びながら戦え。」
> LLM = Claude 自身が `scripts/claude_play.py` の人間席に座り、 配備 ExploitBeam (SmartOpponentAI) と**ミラー対戦**。
> このファイルが**復元可能な台帳**。 context をまたいだら最初にここの `_RESUME` を読む。 詳細メモは [[project_claude_vs_exploitbeam_play]]。

## _RESUME (現在地)

- **次にやること**: cardrush_1385 (クロコダイル) game 2 を開始 (seed 12)。 game 1 = 勝ち。
- **全体記録**: 1342 = 3勝2敗 (完了)。 1385 = 1勝0敗 (game1 W、 残り4戦)。 残り14デッキ未着手。
- ⚠ **操作教訓**: 連続ブーストは `don <iid> <n>` を使う (move の DON+1 は1手ごとに番号が ずれて 別キャラを ブーストする事故あり)。 リーサル計算は「相手の残カウンター枚数 × 最大counter値」を超えるサイズに各攻撃を載せる。
- **開始コマンド**: `.venv/bin/python scripts/claude_play.py start --deck <slug> --first --seed <N>`
- **デッキ順**: 1385 → 1392 → 1399 → 1439 → 1453 → 1454 → 1455 → 1456 → tcgportal_bonney → calgara → coby → corazon → hancock → op11_luffy → op13_luffy
- **手順/コマンド早見**: start / show / mulligan keep|redraw|ok / move <idx> / `attack <iid> <leader|tgt> --don N` / `don <iid> <n>` / defense <iid|none> --counter <hand_idx...> / redirect / choice <候補位置 0始まり> / counter-event <hand_idx>
- ⚠ **choice の picks は「候補リストの位置(0始まり)」** で渡す (engine が `candidates[i]["hand_idx"]` に変換)。 hand_idx 直渡しは誤爆。
- ⚠ defense のブロッカー引数は**数値 iid**。 1手ずつ番号確認 (連続固定実行 厳禁)。

## デッキ別 記録 (W-L と要点)

| # | deck | leader / archetype | 記録 | 主な学び / バグ |
|---|---|---|---|---|
| 1 | cardrush_1342 | ドフラミンゴ / 紫コントロール | 3-2 | [[project_claude_vs_exploitbeam_play]] 参照 |
| 2 | cardrush_1385 | クロコダイル / B・W ミッドレンジ | 1-0 | g1 W(t13)。 AI が受動運用で自滅気味。 クロコダイル登場lockで相手大型を無力化→グラインド勝ち |

## 🐛 engine バグ (発見・修正)

(1342セッションで計3件修正済: iid衝突 / on_attack無限ループ / ヴェルゴ-2000多重発動。 commit 4745964 等)

## 🎯 ExploitBeam AI の弱点 (= 人間が突ける穴 / 配備AI改善のネタ)

- **過剰防御**: 序盤の素チップ(無コストのリーダー攻撃)にもカウンターを切る → 毎ターン素殴りで相手カウンターを枯らせる (1342で実証)。
- **大型を受け切れず素通し**: カウンター不能サイズ(+5000要)を作ると止め札が足りず通る。
- **value/コンボデッキを回せない (1385で顕著)**: クロコダイルB・Wで2-3ターン展開せず手札を貯め込み、DON浪費、リーダー素殴りだけ。攻め型(1342)では機能した同じAIが、グラインド/蘇生/サーチ系デッキでは弱体化。⇒ **配備AIは archetype 依存で質が大きく変わる**。人間越えAIは「デッキの勝ち筋(value engineの回し方)」を理解する必要。
- (追記していく)

## 🐛 engine バグ / 表示 (調査メモ)

- ✅ **near-bug 2件は engine 正しいと確認** (1385): ①「クロコダイル(7000)が攻撃」=リーダー(boost)であってロック中のキャラ(同名10000)でない、リーダーとキャラ同名で表示が紛らわしい ②相手クロコの登場lockが自オールサンデーの `cannot_attack_through_opp_turn` を正しく立てていた(自分が見落とし)。
- ⚠ **CLI表示改善余地**: キャラの「アタック不可(lock中)」状態が show に出ない → バグと誤認しやすい。`cannot_attack_*` フラグを表示すべき。
- ✅ **choice picks 規約 (再確認)**: search/play_from_hand 系の choice は **候補リストの位置(0始まり)** を渡す。engine が `candidates[i]["idx"/"hand_idx"/"trash_idx"]` に変換 (effects.py resolve_pending_choice)。

## 🧠 人間越え AI への手がかり (= 強い人間プレイが持ち、 現AIに無いもの)

- **near-free chip の価値判断**: 「無コストで相手ライフ-1 は、相手手札が増えても得」。 現AIは board_eval 上この機微を持たない可能性。
- **バトルKO で protection 貫通**: 「効果離脱耐性」 を持つ相手は効果KOでなく**バトル(パワー勝ち)**で除去、 という条件分岐した除去選択。
- **レスト中の一度きりの除去窓**を突く先読み。
- **カウンター資源の「使わなければ腐る」会計**: リーサル確定ターンはカウンターを出し惜しみせず守りに回す。
- (追記していく)
