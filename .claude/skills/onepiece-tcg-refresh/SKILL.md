---
name: onepiece-tcg-refresh
description: ONE PIECE カードゲームの公式データ一式 (カード DB / 効果オーバーレイ + engine / 公式 FAQ・cardqa / 禁止・制限リスト / ルール PDF / レギュレーション) を最新の公式状態へ総合的に更新する運用 runbook。新弾リリース時や定期更新時の唯一の入口。ユーザーが「カード情報は最新か」「新弾を入れて/追加」「最新化して」「OPxx/新セットを取り込む」「公式の更新を確認」「禁止リスト/FAQ/cardqa/レギュレーションを更新」「データをリフレッシュ」等と言ったら、個別スクリプト名を出していなくても必ずこのスキルを使う。既存スクリプト (scraper.py / check_official_updates.py / refresh_all.py / overlay パイプライン / audit 群) を正しい順序・公式テキスト忠実主義で束ねる。
last_reviewed: 2026-06-15
---

# ONE PIECE データ最新化 runbook

新しい弾が出るたび (および定期チェックで)、 5 つの公式リソースを最新化する。 **`db/cards.json` が「正」、 SQLite は派生物**、 効果は `db/card_effects.json` overlay (公式テキスト忠実主義)。

| # | 対象 | 主担当スクリプト | 重さ |
|---|---|---|---|
| 1 | 新カード (cards.json/sqlite) | `scraper/scraper.py` | 軽 (数分) |
| 2 | 効果 overlay + engine 拡張 | 手作業 + `suggest_overlay_from_cards.py` + audit 群 | **重 (新弾の本体)** |
| 3 | FAQ / cardqa | `check_official_updates.py` (自動 rescrape) | 軽 |
| 4 | 禁止/制限/禁止ペア | `check_official_updates.py` (自動 rescrape) | 軽 |
| 5 | ルール PDF / レギュレーション | `check_official_updates.py` + `engine/deck.py` validate | 軽 |
| + | 下流 (画像 / メタ / matrix) | `cache_*_images.py` / `refresh_all.py` | 重 (matrix ~80分) |

すべて `.venv/bin/python` で実行 (リポジトリルート = `/home/ohtsuki/projects/onepiece_research`)。 各ステップの完了を確認してから次へ進む。

---

## Step 0 — 何が新しいか検知する (read-only)

まず差分を把握してからスコープを決める。 ⚠ scraper は HTML を `/tmp/onepiece_html` にキャッシュするので、 **新シリーズを発見するには top ページのキャッシュを消す**。

```bash
rm -f /tmp/onepiece_html/_top.html
.venv/bin/python scraper/scraper.py --list-series        # 公式の全 series (55+ 件)
```

これを `cards.json` の収録弾と突き合わせ、 未取得の series を特定する (例: OP16 = 550116)。 確認用:

```bash
.venv/bin/python - <<'PY'
import json, re
from collections import Counter
cards = json.load(open("db/cards.json", encoding="utf-8"))
sets = Counter(re.match(r'^(OP\d+|EB\d+|ST\d+|PRB\d+|P)', c["card_id"].split("_")[0]).group(1)
               for c in cards if re.match(r'^(OP\d+|EB\d+|ST\d+|PRB\d+|P)', c["card_id"]))
print("総数", len(cards), "/ 弾", dict(sorted(sets.items())))
PY
```

FAQ / cardqa / 禁止リスト / PDF の変更検知 (ハッシュ比較。 変更があれば自動で再 scrape する):

```bash
.venv/bin/python scripts/check_official_updates.py
```

→ 出力の `[NEW]/[CHANGED]` と末尾サマリで、 どのリソースが動いたか分かる (戻り値 1 = 変更あり)。 これで **Step 3・4・5 の検知と取得が一括で走る**。

---

## Step 1 — 新カードを取り込む (cards.json / sqlite)

### ⚠⚠ 最重要の落とし穴

- **`scraper.py --series <id>` は cards.json を「そのセットだけ」 で上書きする (追記でない)**。 既存 4,500+ 枚が消える。 **必ず `--all` を使う**。
- `--all` は各 series の HTML を `/tmp/onepiece_html/<id>.html` キャッシュから読む (既存弾は再 fetch せず高速)。 新弾はキャッシュが無いので net から取得。 **既存弾のテキスト改訂 (erratum) も拾いたい場合は当該 `<id>.html` も消す**。

```bash
rm -f /tmp/onepiece_html/_top.html          # 新 series 発見のため (Step 0 で消していれば不要)
.venv/bin/python scraper/scraper.py --all   # cards.json (正) + cards.sqlite (派生) を全弾で再生成
```

完了後、 新弾が入ったか・総数が想定どおり増えたかを確認 (Step 0 の確認スクリプト再実行)。 画像は後段でまとめて (Step 6)。 `--with-images` も付けられるが時間がかかるので分離推奨。

---

## Step 2 — 効果 overlay + engine 拡張 (新弾の本体・最重要)

新カードは overlay が無いと **engine 上で効果ゼロ** (バニラ扱い)。 ここが新弾対応の中心で、 **公式テキスト忠実主義** を厳守する。 詳細な記述ルール・DSL・頻出バグ類型は **`references/overlay_authoring.md` を必ず読む**。

要点 (詳細は reference):

1. **候補の種出し (任意)**: `suggest_overlay_from_cards.py` でテキストから候補を半自動生成 → `db/card_effects.suggestions.json`。 ⚠ これは**ヒューリスティックな足場であって正ではない**。 そのまま信用しない。
2. **公式テキストから忠実に記述**: 各新カードの効果を `db/card_effects.json` に手で書く。 条件節 (ライフ X 以下 / リーダー特徴 Y 等) を省略しない。 `「fallback」「自動抽出」「簡略」「近似」 禁止`。
3. **DSL に無ければ primitive を足す**: `engine/effects.py` に新プリミティブを追加し、 `tests/test_effects.py` にテストを足す。 新トリガーが要れば engine 側も拡張 (= 「engine の更新」)。
4. **本当に表現不能な時だけ**: `{"_unimplemented": "..."}` か `_fidelity_note` で**公式テキストを残してマーク**。 空近似で誤魔化さない。
5. ルール裁定は `onepiece-tcg-rules` スキル + `db/faq/cardqa_*.json` を grep して確認。

全カード 4,518 枚は過去に `_unimplemented = 0` / audit sev≥3 = 0 を達成済み。 **新弾追加でこの基準を割らないこと** がゴール (Step 3 で機械的に担保)。

---

## Step 3 — 検証ゲート (3 つの問いに機械で答える)

新カードの overlay / engine を書いたら下記を全部通す。 各検証が **「① engine が対応しているか / ② テキストが公式に忠実か / ③ 効果が実対戦で正しく動くか (追加 engine の正しさ込み) / ④ 人間 vs AI の UI/UX で人間が操作できるか」** のどれを担保するか明記する。 ⚠ **①②だけでは「対戦で正しく使える」 は担保できない** — それが ③、 さらにブラウザ操作が ④。

### 3A. engine が対応しているか (silently-ignored の排除)
overlay のキーを engine が読まないと **無言で無視され、 audit は通るのに対戦で何も起きない/無条件発火する**。 静的に弾く:

```bash
.venv/bin/pytest tests/test_no_dead_entry_keys.py    # entry gate は if/conditions のみ。 condition単数・_if_clause 等の dead key を禁止
.venv/bin/python scripts/audit_dsl_primitives.py     # 全 do/cost/if の key が engine/effects.py に実装済か (missing を使用枚数付きで報告)
.venv/bin/python scripts/audit_engine_strictness.py  # engine 厳密化 10 項目 (10/10)
```

→ ⚠ entry gate は **`if` (単一 dict) / `conditions` (dict の list)** のみ。 `condition` (単数) は dead key。

### 3B. テキストが公式に忠実か
```bash
.venv/bin/python scripts/audit_overlay_vs_faq.py     # overlay vs FAQ 突合 (sev>=3 = 0)
.venv/bin/python scripts/verify_overlay_vs_cardqa.py # cardqa 効果マーカー vs overlay (missing = 0)
```

### 3C. 効果が「実対戦で正しく」 動くか (= 追加 engine の正しさ込み・最重要)
⚠ **smoke_test / 単体テストは「発火する・盤面が変わる」 までしか見ない (= 『変化 ≠ 正しい挙動』)**。 過去の campaign では audit 全 green でも実対戦で壊れている bug (免疫がブロック経由のバトルKOを誤防御 / optional_cost 二重 discard / マルチ攻撃で防御 pump 抑止 等) を多数発見した。 **だから新カードを実際に対戦へ投入して検証する**:

```bash
.venv/bin/python scripts/smoke_test_card_effects.py            # 各効果を最小ステートで発火 (NO_CHANGE/ERROR = 確実なバグ)
.venv/bin/pytest                                               # 新 primitive の test_effects.py 含む全テスト
.venv/bin/python scripts/fuzz_human_play.py 200                # 人間vsAI を多数 headless 実行 (crash/stuck/NO_ACT/不変条件違反)
.venv/bin/python scripts/audit_runtime_invariants.py --n-games 100 --workers 8   # AI vs AI batch で保存則違反を検出
```

さらに **新カードを積んだデッキで実際に対戦し、 正しいトリガー/対象/タイミングで解決するかを目視**する (= 自動検証が拾えない「意味的に正しいか」):
- `examples/demo_with_effects.py` か `harness.run_matchup` で新カード入りデッキを回す。
- `scripts/report_bad_moves.py --deck-a <a> --deck-b <b>` で AI の悪手 (= 効果の誤用) を抽出。
- 疑わしい新カードは `scripts/claude_play.py` で 1 手ずつ操作して効果の解決を確認 (= campaign 方式、 最も確実)。

### 3D. 人間 vs AI の UI / UX (= ブラウザで人間が正しく操作できるか)
⚠ **3A–3C は engine/ロジック層**。 `fuzz_human_play` も session API を叩くだけで **React UI 層 (modal/DnD/描画/画像) のバグは見えない**。 新カードが**新しい pending_choice kind** (新モーダル) を導入したのに UI に分岐が無い / payload キーがズレていると、 **空モーダルや操作 UI 欠落で人間が詰む** (campaign の「シュガー複製で空表示」「ブロッカー選択が dead component に埋没」 類型)。 これを守る:

```bash
.venv/bin/python scripts/lint_human_ui_contracts.py   # C1 dead component / C2 全 pending kind に UI 分岐 / C3 payload キー契約一致
.venv/bin/python -m pytest tests/test_human_ui_contracts.py tests/test_fuzz_human_play_invariants.py tests/test_human_path_conformance.py -q
cd web && npx tsc --noEmit                            # 型 (新 kind の UI 分岐・型の追従)
```

→ **C2 が新カードの新モーダル未対応を、 C3 が payload キー不一致を静的に検出する** (= 新弾 UI の最重要ゲート)。 さらに実ブラウザ層 (JS console エラー / modal 異常 / 詰まり / 画像描画):

```bash
cd web && npm run dev &                               # :3000 で起動 (別途)
.venv/bin/python scripts/browser_play_test.py         # Playwright で /play を実操作
```

人手確認: `/play` で新カードを実際にプレイし新モーダルが描画/操作できるか、 **新カード画像が出るか** (未キャッシュは公式 CDN フォールバック → Step 6 で `cache_*_images.py`)、 `/cards`・`/decks/new`・`/combos`・`/decks/[slug]/analyze` に新カードが正しく出るか。

### 新 primitive を足した時の「正しさ」 (③ の中核)
1. `tests/test_effects.py` に **最小ステートでなく実ゲーム文脈に近い** behavior test を足す (発火前後の盤面差分 + run1==run2 の再現性)。
2. `audit_dsl_primitives.py` で missing でない (= 登録された) ことを確認。
3. その primitive を使う実カードを 3C の対戦検証 (fuzz / matchup / claude_play) に通す。

- `db/audit_acknowledged.json` = intrinsic 除外 / `db/overlay_audit.{md,json}` = 結果。 新弾起因の sev≥3 / `_unimplemented` / dead key / NO_CHANGE をゼロに戻す。

---

## Step 4 — FAQ / cardqa / 禁止リスト (大半は自動)

`check_official_updates.py` (Step 0) が変更を検知すると **自動で再 scrape** する:

- FAQ/cardqa 変更 → `scrape_official_faq.py` を内部実行 → `db/faq/*.json` 更新。
- 禁止リスト変更 → `scrape_official_banlist.py` を内部実行 → `db/banlist/master.json` 更新。

やること:
1. `git diff db/faq/ db/banlist/master.json` で差分を確認。
2. ルール/Q&A が変わったら **`onepiece-tcg-rules` スキルの `last_checked` を更新**、 engine 仕様に影響するなら同 SKILL の §17 表も更新。
3. 個別に取り直したい時: `scripts/scrape_official_faq.py` / `scripts/scrape_official_banlist.py` / `scripts/check_rules_update.py`。

---

## Step 5 — レギュレーション確認

スタンダード合法性は `engine/deck.py` の `_check_standard_block` が判定: **`block_icon >= banlist["standard_min_block"]` (既定 2)**。 新弾の `block_icon` は scrape で入る。

1. 新禁止リストで `standard_min_block` やバン/制限/禁止ペアが変わっていないか (Step 4 の diff)。
2. 既存メタデッキ等が新禁止リストでまだ合法か検証:

```bash
.venv/bin/python - <<'PY'
import glob
from engine.deck import CardRepository, DeckList
repo = CardRepository.from_json("db/cards.json")
for p in sorted(glob.glob("decks/*.json")):
    if ".analysis." in p or ".target_v" in p:   # 分析/生成スクラッチは除外
        continue
    try:
        dl = DeckList.from_json(p, repo)      # path を直接渡す
    except Exception as e:
        print(p, "LOAD ERR", e); continue
    probs = dl.validate()                     # banlist=None で db/banlist/master.json を自動ロード
    if probs:
        print(p, probs)
PY
```

新禁止リスト下で違反になったデッキ (禁止ペア等) は `decks/_archive/` へ退避し、 代替が無いアーキタイプは matrix から除外する。

---

## Step 6 — 下流 (任意・重い。 必要に応じて)

- **画像**: 新弾分をキャッシュ。 `scripts/cache_deck_images.py` (デッキで使う分) か `scripts/cache_all_images.py` (全件、 30〜60分)。 web は `web/public/cards/` を優先し未キャッシュは公式 CDN フォールバックなので必須ではない。
- **メタデッキ更新**: 新弾は環境を変える。 `scripts/scrape_cardrush_decks.py` → `scripts/select_cardrush_representatives.py` (CLAUDE.md の「メタデッキ更新」 参照)。 取得レシピは新禁止リストで validate。
- **matrix 再計算 (重)**: メタが変わったら `scripts/compute_matchup_matrix.py --ai-mode exploitbeam --workers 8 --n-games 20` (~80分)。 ⚠ 配備 AI の手が変わる engine 変更後にも要再計算。
- **一括**: `scripts/refresh_all.py` が「公式チェック → cardrush 再 scrape → 代表選出 → matrix → 学習診断」 を束ねる。 ⚠ **`refresh_all.py` はカード scrape を含まない** (Step 1 は別途必須)。

---

## Step 7 — 検証してコミット

- 変更前に `git status`。 default ブランチ上ならまず作業ブランチを切る。
- 論理単位でコミット (例: ①カード scrape、 ②overlay+engine、 ③メタ/matrix)。 CLAUDE.md のコミット規約に従う。
- コミット前ゲート: Step 3 の audit/pytest が全 green、 `cd web && npx tsc --noEmit` (UI 触ったら)。

---

## 完了チェックリスト

- [ ] `cards.json` に新弾が入り総数が想定どおり (Step 0 確認スクリプト)
- [ ] 新カードの overlay を公式テキスト忠実に記述、 `_unimplemented` 不要分はゼロ
- [ ] **① engine 対応**: `test_no_dead_entry_keys` green / `audit_dsl_primitives` で missing 0 / strictness 10/10
- [ ] **② テキスト忠実**: `audit_overlay_vs_faq` sev≥3 = 0 / `verify_overlay_vs_cardqa` missing = 0
- [ ] **③ 実対戦で正しい**: smoke NO_CHANGE/ERROR = 0 / pytest green / `fuzz_human_play` + `audit_runtime_invariants` で違反0 / 新カード入りデッキを実対戦で目視確認
- [ ] **④ 人間vsAI UI/UX**: `lint_human_ui_contracts` OK (C2 新 kind に UI 分岐 / C3 payload キー一致) / UI 契約 pytest green / `tsc --noEmit` / (任意) `browser_play_test` で /play 実操作 + 新カード画像描画
- [ ] FAQ/cardqa/banlist の diff 確認、 `onepiece-tcg-rules` の last_checked 更新
- [ ] レギュレーション: 新 banlist 反映、 既存デッキの合法性確認
- [ ] (必要なら) 画像 / メタデッキ / matrix 更新
- [ ] 論理単位でコミット
