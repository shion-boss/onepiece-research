# Static Audit Report (Layer 1)

generated: 2026-05-28T14:31:03.425819Z  
cards scanned: 4518  
issues total: 22  

## by rule

- `L2`: 2
- `L5`: 3
- `L6`: 17

## by category

- `trigger_missing`: 17
- `leader_feature_missing`: 3
- `once_per_turn_missing`: 2

## by severity

- sev 4: 19
- sev 3: 3

## top 100 issues

### 1. OP03-105 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`

### 2. OP03-115 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`

### 3. OP03-115_r1 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`

### 4. OP04-024 (L5, sev 3)

**leader_feature_missing**: text の 「自分のリーダーが特徴《ドンキホーテ海賊団》を持つ なら/場合」 に 対応 する if.leader_feature が overlay に なし

- text: `【相手のターン中】【ターン1回】相手がキャラを登場させた時、自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、相手のキャラ1枚までを、レストにする。その後、このキャラをレストにす…`
- fix: `該当 entry の if に leader_feature: 'ドンキホーテ海賊団' を 追加`

### 5. OP04-024_p1 (L5, sev 3)

**leader_feature_missing**: text の 「自分のリーダーが特徴《ドンキホーテ海賊団》を持つ なら/場合」 に 対応 する if.leader_feature が overlay に なし

- text: `【相手のターン中】【ターン1回】相手がキャラを登場させた時、自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、相手のキャラ1枚までを、レストにする。その後、このキャラをレストにす…`
- fix: `該当 entry の if に leader_feature: 'ドンキホーテ海賊団' を 追加`

### 6. OP04-024_p2 (L5, sev 3)

**leader_feature_missing**: text の 「自分のリーダーが特徴《ドンキホーテ海賊団》を持つ なら/場合」 に 対応 する if.leader_feature が overlay に なし

- text: `【相手のターン中】【ターン1回】相手がキャラを登場させた時、自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、相手のキャラ1枚までを、レストにする。その後、このキャラをレストにす…`
- fix: `該当 entry の if に leader_feature: 'ドンキホーテ海賊団' を 追加`

### 7. OP04-105 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`

### 8. OP04-105_p2 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`

### 9. OP09-081 (L6, sev 4)

**trigger_missing**: text に 「【登場時】」 が 含まれる が overlay に when ∈ ['on_play'] entry なし

- text: ``
- fix: `when: on_play の entry を 追加`

### 10. OP09-081_p1 (L6, sev 4)

**trigger_missing**: text に 「【登場時】」 が 含まれる が overlay に when ∈ ['on_play'] entry なし

- text: ``
- fix: `when: on_play の entry を 追加`

### 11. OP09-081_p2 (L6, sev 4)

**trigger_missing**: text に 「【登場時】」 が 含まれる が overlay に when ∈ ['on_play'] entry なし

- text: ``
- fix: `when: on_play の entry を 追加`

### 12. OP09-081_p3 (L6, sev 4)

**trigger_missing**: text に 「【登場時】」 が 含まれる が overlay に when ∈ ['on_play'] entry なし

- text: ``
- fix: `when: on_play の entry を 追加`

### 13. OP10-118 (L2, sev 4)

**once_per_turn_missing**: text に 「ターン1回」 が 含まれる が overlay entries の どれも once_per_turn を 持たない

- text: `このキャラはターンに1回、相手の効果でKOされない。【アタック時】自分のトラッシュからカード3枚を好きな…`
- fix: `該当 entry に once_per_turn: true (もしくは cost.once_per_turn: true) を 追加`

### 14. OP10-118_p1 (L2, sev 4)

**once_per_turn_missing**: text に 「ターン1回」 が 含まれる が overlay entries の どれも once_per_turn を 持たない

- text: `このキャラはターンに1回、相手の効果でKOされない。【アタック時】自分のトラッシュからカード3枚を好きな…`
- fix: `該当 entry に once_per_turn: true (もしくは cost.once_per_turn: true) を 追加`

### 15. OP11-102 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`

### 16. OP13-110 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`

### 17. OP13-110_p1 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`

### 18. P-118 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`

### 19. PRB01-001 (L6, sev 4)

**trigger_missing**: text に 「【登場時】」 が 含まれる が overlay に when ∈ ['on_play'] entry なし

- text: ``
- fix: `when: on_play の entry を 追加`

### 20. PRB01-001_p1 (L6, sev 4)

**trigger_missing**: text に 「【登場時】」 が 含まれる が overlay に when ∈ ['on_play'] entry なし

- text: ``
- fix: `when: on_play の entry を 追加`

### 21. ST29-014 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`

### 22. ST29-014_p1 (L6, sev 4)

**trigger_missing**: text に 「【トリガー】」 が 含まれる が overlay に when ∈ ['trigger'] entry なし

- text: ``
- fix: `when: trigger の entry を 追加`
