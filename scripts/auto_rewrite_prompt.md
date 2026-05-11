# Auto DSL Rewrite Round

`db/card_effects.json` の残 `_unimplemented` を 1 ラウンド分書き換える。
ローカル cron から呼ばれるバッチタスク。 人間のレビュー無しで実行されることを意識して、
保守的に動くこと。

## 鉄則

1. **既存 primitive / condition / filter / target spec で書ける軽量パターンのみ**。
   新規 primitive 追加 / 新 condition 追加 / `InPlay` or `Player` フィールド追加 /
   game.py 改修が必要な場合は **STOP marker を作って exit**。
2. **公式テキスト忠実主義** (CLAUDE.md より): 「fallback / 自動抽出 / 簡略 / 省略 / 近似」 禁止。
   解釈不可なら触らずにスキップ。 安易な簡略化で _unimplemented を消すのは厳禁。
3. **1 ラウンド = 5〜15 件処理**。 それ以上は次回。
4. **メタデッキ採用カード** (`decks/cardrush_*.json` で参照) は触らない。 安全側に倒す。
5. `pytest tests/` と `.venv/bin/python scripts/smoke_test_card_effects.py` の両方が pass することを確認。
6. 失敗時は `git reset --hard HEAD` で巻き戻し + `.auto_rewrite.STOP` を作って exit 1。
7. 完了したら `git commit` のみ (push しない)。

## 直前ラウンドの失敗教訓

過去の自動ラウンドで sonnet が書いた DSL で `smoke_test_card_effects.py` が
`on_play: ERROR=2` を出して revert されたケースがある。 原因は **target spec が
存在しない名前** だったり、 **必須引数が無い** primitive 呼び出しが書かれたこと。

対策:
- 書き換える前に、 該当 primitive の引数仕様を `engine/effects.py` で **必ず grep して確認**:
  ```bash
  grep -n -A 5 'elif k == "PRIMITIVE_NAME"' engine/effects.py
  ```
- target spec は既存の以下から選ぶ (grep で確認):
  - 単独: `self`, `self_leader`, `opponent_leader`, `self_inplay`, `one_self_character_any`,
    `one_opponent_character_any`, `one_opponent_inplay_any`, `other_self_chara`,
    `all_self_characters`, `all_opponent_characters`, `all_self_team`
  - 派生 (regex): `one_opponent_character_cost_le_N`, `one_opponent_character_cost_le_Ncost`,
    `any_opponent_character_cost_le_N`, `one_opponent_character_power_le_N`,
    `one_opponent_character_power_eq_N`, `one_opponent_rested_character_cost_le_N`,
    `one_opponent_character_attached_don_ge_N`, `one_self_character_cost_le_N`
  - 辞書 spec: `{"type": "one_self_chara_or_leader_filtered", "filter": {...}}` /
    `{"type": "self_chara_named", "name": "..."}` / `{"type": "all_self_chara_named", "name": "..."}`
- 公開されていない名前 (例: `one_self_chara_filter`, `any_self_chara_with_feature` 等)
  を creative に作らない。 該当 spec が無いなら **その unique はスキップ**。
- 書き換え後の `git diff db/card_effects.json` を見て、 各 effect block の構造
  (`when` / `if` / `do` / `cost`) が公式テキストと合致するか必ず再チェック。

## 進め方

```bash
# 1. 現状確認 (commit 履歴と _unimplemented 件数)
git log --oneline -5
.venv/bin/python -c "
import json
from collections import Counter
with open('db/card_effects.json') as f: data = json.load(f)
c = Counter()
def w(o):
    if isinstance(o, dict):
        if '_unimplemented' in o: c[o['_unimplemented']] += 1
        for v in o.values(): w(v)
    elif isinstance(o, list):
        for v in o: w(v)
for cid, e in data.items():
    if not cid.startswith('_'): w(e)
print(f'total={sum(c.values())} unique={len(c)}')
for t, n in c.most_common(30):
    print(f'  [{n}x] {t[:140]}')
"

# 2. 既存 primitive で書けそうな 5-15 件 を選定 (パラレル違いでまとめてカウント)
# 主要既存 primitive: power_pump / ko / ko_multi / rest / return_to_hand / play_from_hand /
# play_from_hand_or_trash / play_from_trash / trash_to_hand / mill / search_top_n /
# reveal_top_play / scry_life / life_top_or_bottom_to_hand / hand_to_self_life /
# optional_cost_then / choice / disable_effect / prevent_blocker_for_attacker /
# untap / untap_chara / give_keyword / give_rush / give_attack_active_chara / attach_don /
# rest_self_don / rest_self_cards / return_self_to_hand / return_self_to_trash /
# add_don / untap_don / pay_don / mill_self_top / look_top_reorder / play_event_from_hand /
# in_hand_cost_minus / set_cannot_attack / set_cannot_attack_target_cost_le /
# give_ko_immune_through_opp_turn / rest_opp_don / win_game / deal_opp_leader_damage /
# opp_hand_to_deck_bottom / return_to_deck_bottom / to_opp_life / draw / trash_self_hand_random
# 主要 condition: leader_feature / leader_feature_contains / leader_color / leader_multicolor /
# leader_name / leader_name_in / leader_features_any / self_life_le/ge / opp_life_le/ge /
# self_field_count_le/ge / self_don_le/ge / self_attached_don_ge / self_chara_feature_count_ge /
# self_chara_cost_ge_count / self_hand_count_le / opp_hand_count_ge / self_turn / opp_turn /
# self_rested / self_summoning_sickness / opp_leader_attribute / self_leader_attribute /
# self_trash_count_ge / self_trash_event_count_ge / self_rested_cards_count_ge /
# self_chara_only_feature / don_diff_le / life_zero_either

# 3. 書き換えスクリプトを実行 (= 既存パターンの Python スクリプト)
# 4. テスト
.venv/bin/pytest tests/ -q
.venv/bin/python scripts/smoke_test_card_effects.py
# 5. 件数確認 (= 減ったか)
# 6. git diff で確認 → 問題なければ commit
git add db/card_effects.json
git commit -m "Auto DSL rewrite ($(date +%Y-%m-%dT%H:%M)): -N件 (累計 _unimplemented X→Y)"
```

## STOP 条件 (必ず守る)

以下のどれかに該当したら、 ファイル変更を行わず `.auto_rewrite.STOP` (空ファイル) を作って `exit 0`:

- 残 _unimplemented が「既存 primitive で書ける」 と判定できるものが 5 件未満
- 新 primitive / condition / フィールド / engine 改修が必要なケースが top 30 を占める
- pytest が pre-check で失敗 (= 既に状態が壊れている = 直前のラウンドが失敗してる)

失敗時は次のステップで対応:

- `git status` で変更ファイルを確認
- `git reset --hard HEAD` で前回 commit に戻す
- `.auto_rewrite.STOP` を作って exit 1

## 厳禁

- `git push` (= リモートに反映しない、 人間レビュー前)
- メタデッキ採用カード (`decks/cardrush_*.json` で参照) の overlay を変更
- `engine/` ファイル変更 (= primitive 追加は人間判断)
- ブランチ操作 (`git checkout` 等)
- 不可逆操作 (`rm -rf`, `git push --force`, etc.)

## 完了時メッセージ

最後に 1 行で結果を報告する。 例:
- `OK: -12 件 / -6 unique (commit abc123)`
- `STOP: 既存 primitive で書ける軽量パターンが尽きた (5 件未満)`
- `ABORT: post-test failed, reverted`
