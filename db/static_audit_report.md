# Static Audit Report (Layer 1)

generated: 2026-05-28T15:53:50.414379Z  
cards scanned: 4518  
issues total: 125  

## by rule

- `L3`: 41
- `L4`: 30
- `L7`: 27
- `L8`: 27

## by category

- `self_opp_reversal_suspect`: 41
- `count_limit_missing`: 30
- `cost_le_missing`: 27
- `duration_next_turn_missing`: 27

## by severity

- sev 4: 54
- sev 3: 30
- sev 2: 41

## top 100 issues

### 1. EB04-040 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 2. EB04-052 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 3. EB04-052_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 4. OP02-013 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 5. OP02-013_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 6. OP02-013_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 7. OP02-013_p3 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 8. OP02-013_p5 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 9. OP02-013_r1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 10. OP02-094 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 11. OP02-112 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 12. OP03-025 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのコスト4以下のキャラ2枚までを、KOする。【ドン!!×1】このキャラは【ダブルアタック】を得る。(このカード…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 13. OP03-025_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのコスト4以下のキャラ2枚までを、KOする。【ドン!!×1】このキャラは【ダブルアタック】を得る。(このカード…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 14. OP03-038 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】相手のコスト2以下のキャラ2枚までを、レストにする`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 15. OP03-095 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】相手のキャラ2枚までを、このターン中、コスト-2。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 16. OP05-002 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `…》を持つカード1枚を捨てることができる：自分の特徴《革命軍》か【トリガー】を持つキャラ3枚までを、このターン中、パワー+3000。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 17. OP05-002_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `…》を持つカード1枚を捨てることができる：自分の特徴《革命軍》か【トリガー】を持つキャラ3枚までを、このターン中、パワー+3000。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 18. OP05-002_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `…》を持つカード1枚を捨てることができる：自分の特徴《革命軍》か【トリガー】を持つキャラ3枚までを、このターン中、パワー+3000。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 19. OP05-041 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 20. OP05-041_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 21. OP06-001 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 22. OP06-001_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 23. OP06-001_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 24. OP06-035 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 25. OP06-035_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 26. OP06-035_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 27. OP06-035_r1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 28. OP06-058 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】コスト6以下のキャラ2枚までを、好きな順番で持ち主のデッキの下に置く。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 29. OP06-058_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】コスト6以下のキャラ2枚までを、好きな順番で持ち主のデッキの下に置く。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 30. OP06-058_r1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】コスト6以下のキャラ2枚までを、好きな順番で持ち主のデッキの下に置く。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 31. OP06-071 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラカード2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…徴《FILM》を持つ場合、自分のトラッシュの特徴《FILM》を持つコスト4以下のキャラカード2枚までを、手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 32. OP06-071 (L7, sev 4)

**cost_le_missing**: text に 「コスト 4 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…のリーダーが特徴《FILM》を持つ場合、自分のトラッシュの特徴《FILM》を持つコスト4以下のキャラカード2枚までを、手札に加える。`
- fix: `target に target_cost_le: 4 を 追加 (or target_spec 文字列 を cost_le_4 系 へ)`

### 33. OP06-075 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…のドン !!を指定の数ドン !!デッキに戻すことができる)：相手のコスト2以下のキャラ2枚までを、レストにする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 34. OP06-096 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【カウンター】自分のライフの上から1枚を手札に加えることができる：自分のコスト7以下のキャラすべては、このターン中、バトルでKOされない。`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 35. OP07-029 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 36. OP07-029_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 37. OP07-029_r1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 38. OP07-076 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 39. OP07-076_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 40. OP07-076_r1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 41. OP07-079 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 42. OP07-079_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 43. OP07-079_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 44. OP07-091 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【アタック時】相手のコスト2以下のキャラ1枚までをトラッシュに置く。その後、自分のトラッシュからコスト4以上のキャラカー…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 45. OP07-091_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【アタック時】相手のコスト2以下のキャラ1枚までをトラッシュに置く。その後、自分のトラッシュからコスト4以上のキャラカー…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 46. OP08-022 (L7, sev 4)

**cost_le_missing**: text に 「コスト 5 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【登場時】自分のリーダーが特徴《ミンク族》を持つ場合、相手のレストのコスト5以下のキャラ2枚までは、次の相手のリフレッシュフェイズでアクティブにならない。`
- fix: `target に target_cost_le: 5 を 追加 (or target_spec 文字列 を cost_le_5 系 へ)`

### 47. OP08-069 (L7, sev 4)

**cost_le_missing**: text に 「コスト 6 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…ことができる：自分のデッキの上から1枚までを、ライフの上に加える。その後、相手のコスト6以下のキャラ1枚までを、相手のライフの上か下に表向きで加える。`
- fix: `target に target_cost_le: 6 を 追加 (or target_spec 文字列 を cost_le_6 系 へ)`

### 48. OP08-069_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 6 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…ことができる：自分のデッキの上から1枚までを、ライフの上に加える。その後、相手のコスト6以下のキャラ1枚までを、相手のライフの上か下に表向きで加える。`
- fix: `target に target_cost_le: 6 を 追加 (or target_spec 文字列 を cost_le_6 系 へ)`

### 49. OP08-069_p2 (L7, sev 4)

**cost_le_missing**: text に 「コスト 6 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…ことができる：自分のデッキの上から1枚までを、ライフの上に加える。その後、相手のコスト6以下のキャラ1枚までを、相手のライフの上か下に表向きで加える。`
- fix: `target に target_cost_le: 6 を 追加 (or target_spec 文字列 を cost_le_6 系 へ)`

### 50. OP08-079 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…回】自分の手札1枚を捨てることができる：このキャラが登場したターンの場合、相手のコスト7以下のキャラ1枚までを、トラッシュに置く。その後、相手は自身の手札1枚を捨てる。`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 51. OP08-079_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…回】自分の手札1枚を捨てることができる：このキャラが登場したターンの場合、相手のコスト7以下のキャラ1枚までを、トラッシュに置く。その後、相手は自身の手札1枚を捨てる。`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 52. OP08-118 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手のキャラ2枚までを選び、次の相手のターン終了時まで、1枚をパワー-3000し、残りをパワー-2000。その後、相手のパワー3000…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 53. OP08-118_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手のキャラ2枚までを選び、次の相手のターン終了時まで、1枚をパワー-3000し、残りをパワー-2000。その後、相手のパワー3000…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 54. OP08-118_p2 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手のキャラ2枚までを選び、次の相手のターン終了時まで、1枚をパワー-3000し、残りをパワー-2000。その後、相手のパワー3000…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 55. OP08-118_r1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手のキャラ2枚までを選び、次の相手のターン終了時まで、1枚をパワー-3000し、残りをパワー-2000。その後、相手のパワー3000…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 56. OP09-033 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…上いる場合、自分の特徴《ODYSSEY》か《麦わらの一味》を持つキャラすべては、次の相手のターン終了時まで、効果でKOされない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 57. OP09-033_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…上いる場合、自分の特徴《ODYSSEY》か《麦わらの一味》を持つキャラすべては、次の相手のターン終了時まで、効果でKOされない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 58. OP09-033_r1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…上いる場合、自分の特徴《ODYSSEY》か《麦わらの一味》を持つキャラすべては、次の相手のターン終了時まで、効果でKOされない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 59. OP09-036 (L7, sev 4)

**cost_le_missing**: text に 「コスト 6 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【登場時】自分のレストのキャラが2枚以上いる場合、相手のコスト6以下のキャラ1枚かドン‼1枚までを、レストにする。`
- fix: `target に target_cost_le: 6 を 追加 (or target_spec 文字列 を cost_le_6 系 へ)`

### 60. OP09-081 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…の【登場時】効果は無効になる。【起動メイン】自分の手札1枚を捨てることができる：次の相手のターン終了時まで、相手の【登場時】効果は無効になる。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 61. OP09-081_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…の【登場時】効果は無効になる。【起動メイン】自分の手札1枚を捨てることができる：次の相手のターン終了時まで、相手の【登場時】効果は無効になる。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 62. OP09-081_p2 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…の【登場時】効果は無効になる。【起動メイン】自分の手札1枚を捨てることができる：次の相手のターン終了時まで、相手の【登場時】効果は無効になる。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 63. OP09-081_p3 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…の【登場時】効果は無効になる。【起動メイン】自分の手札1枚を捨てることができる：次の相手のターン終了時まで、相手の【登場時】効果は無効になる。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 64. OP09-101 (L7, sev 4)

**cost_le_missing**: text に 「コスト 3 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【登場時】相手のコスト3以下のキャラ1枚を、相手のライフの上か下に表向きで置く：相手は自身の手札1枚を捨てる。`
- fix: `target に target_cost_le: 3 を 追加 (or target_spec 文字列 を cost_le_3 系 へ)`

### 65. OP10-023 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】自分のリーダーが特徴《海軍》を持つ場合、相手のコスト5以下のキャラ2枚までを、レストにする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 66. OP10-058 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラカード2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…の後、自分の手札から、「レベッカ」以外の特徴《ドレスローザ》を持つコスト7以下のキャラカード2枚までを、公開する。公開したカードのうち1枚を登場させ、残りがコスト4以下ならレストで…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 67. OP10-058 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…1枚を引く。その後、自分の手札から、「レベッカ」以外の特徴《ドレスローザ》を持つコスト7以下のキャラカード2枚までを、公開する。公開したカードのうち1枚を登場させ、残りがコスト4以…`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 68. OP10-058_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラカード2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…の後、自分の手札から、「レベッカ」以外の特徴《ドレスローザ》を持つコスト7以下のキャラカード2枚までを、公開する。公開したカードのうち1枚を登場させ、残りがコスト4以下ならレストで…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 69. OP10-058_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…1枚を引く。その後、自分の手札から、「レベッカ」以外の特徴《ドレスローザ》を持つコスト7以下のキャラカード2枚までを、公開する。公開したカードのうち1枚を登場させ、残りがコスト4以…`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 70. OP12-009 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…2枚を公開することができる：このキャラは、このターン中、【速攻】を得る。その後、次の相手のエンドフェイズ終了時まで、このキャラのパワー+1000。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 71. OP12-020 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 72. OP12-020_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 73. OP12-020_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 74. OP12-020_p3 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 75. OP12-037 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン‼合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】自分のドン‼3枚をレストにできる：相手の、キャラかドン‼合計2枚までを、レストにする。【カウンター】自分のリーダーを、このバトル中、パワー+3000…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 76. OP12-037_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン‼合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】自分のドン‼3枚をレストにできる：相手の、キャラかドン‼合計2枚までを、レストにする。【カウンター】自分のリーダーを、このバトル中、パワー+3000…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 77. OP12-051 (L7, sev 4)

**cost_le_missing**: text に 「コスト 4 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…メイン】このキャラをレストにし、自分の手札1枚を捨てることができる：相手の元々のコスト4以下のキャラ1枚までは、このターン中、【ブロッカー】を発動できない。`
- fix: `target に target_cost_le: 4 を 追加 (or target_spec 文字列 を cost_le_4 系 へ)`

### 78. OP12-051_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 4 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…メイン】このキャラをレストにし、自分の手札1枚を捨てることができる：相手の元々のコスト4以下のキャラ1枚までは、このターン中、【ブロッカー】を発動できない。`
- fix: `target に target_cost_le: 4 を 追加 (or target_spec 文字列 を cost_le_4 系 へ)`

### 79. OP12-073 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…分の、「ドンキホーテ・ロシナンテ」と特徴《ハートの海賊団》を持つキャラすべてを、次の相手のエンドフェイズ終了時まで、パワー+1000。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 80. OP12-073_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…分の、「ドンキホーテ・ロシナンテ」と特徴《ハートの海賊団》を持つキャラすべてを、次の相手のエンドフェイズ終了時まで、パワー+1000。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 81. OP12-119 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…きる：自分のデッキの上から1枚までを、ライフの上に加える。その後、このキャラは、次の相手のエンドフェイズ終了時まで、コスト+2。【相手のターン中】【KO時】自分のデッキの上から1枚までを、ライフ…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 82. OP12-119_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…きる：自分のデッキの上から1枚までを、ライフの上に加える。その後、このキャラは、次の相手のエンドフェイズ終了時まで、コスト+2。【相手のターン中】【KO時】自分のデッキの上から1枚までを、ライフ…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 83. OP13-040 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【メイン】自分のドン‼2枚をレストにできる：相手のレストのコスト7以下のキャラ2枚までは、次の相手のリフレッシュフェイズでアクティブにならない。【カウンター】…`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 84. OP13-040_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【メイン】自分のドン‼2枚をレストにできる：相手のレストのコスト7以下のキャラ2枚までは、次の相手のリフレッシュフェイズでアクティブにならない。【カウンター】…`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 85. OP13-064 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 86. OP13-064_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 87. OP13-082 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラカード5枚まで」 が 含まれる が overlay に count: 5 制限 なし

- text: `…に置き、自分のトラッシュからパワー5000のカード名の異なる特徴《五老星》を持つキャラカード5枚までを、登場させる。`
- fix: `該当 effect に count: 5 (or limit: 5) を 追加`

### 88. OP13-082_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラカード5枚まで」 が 含まれる が overlay に count: 5 制限 なし

- text: `…に置き、自分のトラッシュからパワー5000のカード名の異なる特徴《五老星》を持つキャラカード5枚までを、登場させる。`
- fix: `該当 effect に count: 5 (or limit: 5) を 追加`

### 89. OP13-095 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…自分のキャラが、特徴《天竜人》を持つキャラのみの場合、相手の元々のコスト3以下のキャラ2枚までを、KOする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 90. OP14-020 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 91. OP14-020_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 92. OP14-033 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】相手のコスト5以下のキャラ2枚までは、次の相手のエンドフェイズ終了時まで、レストにできない。【KO時】自分のカード…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 93. OP14-033_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】相手のコスト5以下のキャラ2枚までは、次の相手のエンドフェイズ終了時まで、レストにできない。【KO時】自分のカード…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 94. OP14-033_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】相手のコスト5以下のキャラ2枚までは、次の相手のエンドフェイズ終了時まで、レストにできない。【KO時】自分のカード…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 95. OP14-070 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 96. OP14-079 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 97. OP14-111 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】/【KO時】相手のコスト6以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、アタックできない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 98. OP14-111_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】/【KO時】相手のコスト6以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、アタックできない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 99. OP14-119 (L7, sev 4)

**cost_le_missing**: text に 「コスト 9 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【自分のターン中】このキャラがレストになった時、相手のコスト9以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、レストにできない。【相手のアタッ…`
- fix: `target に target_cost_le: 9 を 追加 (or target_spec 文字列 を cost_le_9 系 へ)`

### 100. OP14-119 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…のターン中】このキャラがレストになった時、相手のコスト9以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、レストにできない。【相手のアタック時】【ターン1回】自分の手札1枚を捨てること…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`
