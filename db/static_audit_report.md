# Static Audit Report (Layer 1)

generated: 2026-05-28T15:17:05.700838Z  
cards scanned: 4518  
issues total: 197  

## by rule

- `L3`: 48
- `L4`: 68
- `L7`: 41
- `L8`: 40

## by category

- `count_limit_missing`: 68
- `self_opp_reversal_suspect`: 48
- `cost_le_missing`: 41
- `duration_next_turn_missing`: 40

## by severity

- sev 4: 81
- sev 3: 68
- sev 2: 48

## top 100 issues

### 1. EB02-007 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「リーダーとキャラ合計3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【メイン】自分のリーダーとキャラ合計3枚までを、このターン中、パワー+1000。その後、相手のパワー3000以下のキャラ1枚…`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 2. EB03-021 (L7, sev 4)

**cost_le_missing**: text に 「コスト 3 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…手札1枚を捨てることができる：相手の元々の、パワー4000以下のキャラ1枚までとコスト3以下のキャラ1枚までを、持ち主のデッキの下に置く。`
- fix: `target に target_cost_le: 3 を 追加 (or target_spec 文字列 を cost_le_3 系 へ)`

### 3. EB04-028 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…とができる：自分のリーダーが特徴《海軍》を持つ場合、相手のパワー10000以下のキャラ2枚までは、次の相手のエンドフェイズ終了時まで、アタックできない。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 4. EB04-028_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…とができる：自分のリーダーが特徴《海軍》を持つ場合、相手のパワー10000以下のキャラ2枚までは、次の相手のエンドフェイズ終了時まで、アタックできない。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 5. EB04-040 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 6. EB04-044 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 7. EB04-044_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 8. EB04-044_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 9. EB04-052 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 10. EB04-052_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 11. OP01-013 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラにレストのドン‼2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…に加えることができる：このキャラは、このターン中、パワー+2000。その後、このキャラにレストのドン‼2枚までを付与する。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 12. OP01-013_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラにレストのドン‼2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…に加えることができる：このキャラは、このターン中、パワー+2000。その後、このキャラにレストのドン‼2枚までを付与する。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 13. OP01-013_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラにレストのドン‼2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…に加えることができる：このキャラは、このターン中、パワー+2000。その後、このキャラにレストのドン‼2枚までを付与する。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 14. OP01-013_p3 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラにレストのドン‼2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…に加えることができる：このキャラは、このターン中、パワー+2000。その後、このキャラにレストのドン‼2枚までを付与する。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 15. OP01-115 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【メイン】相手のコスト2以下のキャラ1枚までを、KOし、ドン‼デッキからドン‼1枚までをアクティブで追加する。`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 16. OP02-013 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 17. OP02-013_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 18. OP02-013_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 19. OP02-013_p3 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 20. OP02-013_p5 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 21. OP02-013_r1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 22. OP02-064 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【ドン‼×1】【アタック時】自分の手札1枚を捨てることができる：コスト2以下のキャラ1枚までを、持ち主のデッキの下に置く。その後、このバトル終了時、このキャラを持ち…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 23. OP02-089 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「リーダーかキャラ合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…】ドン‼-1(自分の場のドン‼を指定の数ドン‼デッキに戻すことができる)：相手のリーダーかキャラ合計2枚までを、このターン中、パワー-3000。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 24. OP02-089_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「リーダーかキャラ合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…】ドン‼-1(自分の場のドン‼を指定の数ドン‼デッキに戻すことができる)：相手のリーダーかキャラ合計2枚までを、このターン中、パワー-3000。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 25. OP02-089_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「リーダーかキャラ合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…】ドン‼-1(自分の場のドン‼を指定の数ドン‼デッキに戻すことができる)：相手のリーダーかキャラ合計2枚までを、このターン中、パワー-3000。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 26. OP02-089_p3 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「リーダーかキャラ合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…】ドン‼-1(自分の場のドン‼を指定の数ドン‼デッキに戻すことができる)：相手のリーダーかキャラ合計2枚までを、このターン中、パワー-3000。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 27. OP02-089_r1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「リーダーかキャラ合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…】ドン‼-1(自分の場のドン‼を指定の数ドン‼デッキに戻すことができる)：相手のリーダーかキャラ合計2枚までを、このターン中、パワー-3000。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 28. OP02-094 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 29. OP02-112 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 30. OP03-024 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】自分のリーダーが特徴《東の海》を持つ場合、相手のコスト4以下のキャラ2枚までを、レストにする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 31. OP03-024_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】自分のリーダーが特徴《東の海》を持つ場合、相手のコスト4以下のキャラ2枚までを、レストにする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 32. OP03-025 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのコスト4以下のキャラ2枚までを、KOする。【ドン!!×1】このキャラは【ダブルアタック】を得る。(このカード…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 33. OP03-025_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのコスト4以下のキャラ2枚までを、KOする。【ドン!!×1】このキャラは【ダブルアタック】を得る。(このカード…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 34. OP03-038 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】相手のコスト2以下のキャラ2枚までを、レストにする`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 35. OP03-057 (L7, sev 4)

**cost_le_missing**: text に 「コスト 5 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【メイン】コスト5以下のキャラ1枚までを、持ち主のデッキの下に置く。`
- fix: `target に target_cost_le: 5 を 追加 (or target_spec 文字列 を cost_le_5 系 へ)`

### 36. OP03-057_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 5 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【メイン】コスト5以下のキャラ1枚までを、持ち主のデッキの下に置く。`
- fix: `target に target_cost_le: 5 を 追加 (or target_spec 文字列 を cost_le_5 系 へ)`

### 37. OP03-057_p2 (L7, sev 4)

**cost_le_missing**: text に 「コスト 5 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【メイン】コスト5以下のキャラ1枚までを、持ち主のデッキの下に置く。`
- fix: `target に target_cost_le: 5 を 追加 (or target_spec 文字列 を cost_le_5 系 へ)`

### 38. OP03-057_p3 (L7, sev 4)

**cost_le_missing**: text に 「コスト 5 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【メイン】コスト5以下のキャラ1枚までを、持ち主のデッキの下に置く。`
- fix: `target に target_cost_le: 5 を 追加 (or target_spec 文字列 を cost_le_5 系 へ)`

### 39. OP03-057_r1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 5 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【メイン】コスト5以下のキャラ1枚までを、持ち主のデッキの下に置く。`
- fix: `target に target_cost_le: 5 を 追加 (or target_spec 文字列 を cost_le_5 系 へ)`

### 40. OP03-095 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】相手のキャラ2枚までを、このターン中、コスト-2。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 41. OP04-031 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「リーダーとキャラ合計3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【登場時】相手のレストの、リーダーとキャラ合計3枚までは、次の相手のリフレッシュフェイズでアクティブにならない。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 42. OP04-031_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「リーダーとキャラ合計3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【登場時】相手のレストの、リーダーとキャラ合計3枚までは、次の相手のリフレッシュフェイズでアクティブにならない。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 43. OP04-031_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「リーダーとキャラ合計3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【登場時】相手のレストの、リーダーとキャラ合計3枚までは、次の相手のリフレッシュフェイズでアクティブにならない。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 44. OP04-031_r1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「リーダーとキャラ合計3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【登場時】相手のレストの、リーダーとキャラ合計3枚までは、次の相手のリフレッシュフェイズでアクティブにならない。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 45. OP04-055 (L7, sev 4)

**cost_le_missing**: text に 「コスト 4 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【メイン】自分の手札から「氷鬼」1枚を捨て、コスト4以下のキャラ1枚を、持ち主のデッキの下に置くことができる：自分のトラッシュから「氷鬼」1枚を…`
- fix: `target に target_cost_le: 4 を 追加 (or target_spec 文字列 を cost_le_4 系 へ)`

### 46. OP05-002 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `…》を持つカード1枚を捨てることができる：自分の特徴《革命軍》か【トリガー】を持つキャラ3枚までを、このターン中、パワー+3000。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 47. OP05-002_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `…》を持つカード1枚を捨てることができる：自分の特徴《革命軍》か【トリガー】を持つキャラ3枚までを、このターン中、パワー+3000。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 48. OP05-002_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `…》を持つカード1枚を捨てることができる：自分の特徴《革命軍》か【トリガー】を持つキャラ3枚までを、このターン中、パワー+3000。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 49. OP05-007 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】相手のキャラ2枚までを、パワーの合計が4000以下になるようにKOする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 50. OP05-007_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】相手のキャラ2枚までを、パワーの合計が4000以下になるようにKOする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 51. OP05-007_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】相手のキャラ2枚までを、パワーの合計が4000以下になるようにKOする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 52. OP05-007_r1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】相手のキャラ2枚までを、パワーの合計が4000以下になるようにKOする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 53. OP05-041 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 54. OP05-041_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 55. OP05-045 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【起動メイン】自分の手札1枚を捨て、このキャラをレストにできる：コスト2以下のキャラ1枚までを、持ち主のデッキの下に置く。`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 56. OP06-001 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 57. OP06-001_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 58. OP06-001_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 59. OP06-020 (L7, sev 4)

**cost_le_missing**: text に 「コスト 3 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【起動メイン】このリーダーをレストにできる：相手の、コスト3以下のキャラかドン !!1枚までを、レストにする。その後、自分は、このターン中、自分の効果で…`
- fix: `target に target_cost_le: 3 を 追加 (or target_spec 文字列 を cost_le_3 系 へ)`

### 60. OP06-020_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 3 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【起動メイン】このリーダーをレストにできる：相手の、コスト3以下のキャラかドン !!1枚までを、レストにする。その後、自分は、このターン中、自分の効果で…`
- fix: `target に target_cost_le: 3 を 追加 (or target_spec 文字列 を cost_le_3 系 へ)`

### 61. OP06-020_p2 (L7, sev 4)

**cost_le_missing**: text に 「コスト 3 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【起動メイン】このリーダーをレストにできる：相手の、コスト3以下のキャラかドン‼1枚までを、レストにする。その後、自分は、このターン中、自分の効果でライ…`
- fix: `target に target_cost_le: 3 を 追加 (or target_spec 文字列 を cost_le_3 系 へ)`

### 62. OP06-023 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのリーダー1枚までは、次の相手のターン終了時まで、アタックできない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 63. OP06-023_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのリーダー1枚までは、次の相手のターン終了時まで、アタックできない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 64. OP06-023_p2 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのリーダー1枚までは、次の相手のターン終了時まで、アタックできない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 65. OP06-023_p3 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのリーダー1枚までは、次の相手のターン終了時まで、アタックできない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 66. OP06-023_r1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのリーダー1枚までは、次の相手のターン終了時まで、アタックできない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 67. OP06-035 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 68. OP06-035_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 69. OP06-035_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 70. OP06-035_r1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 71. OP06-043 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…クの対象をこのカードにできる)【起動メイン】【ターン1回】自分の手札1枚を捨て、コスト2以下のキャラ1枚を持ち主のデッキの下に置くことができる：このキャラは、このターン中、パワー＋…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 72. OP06-043_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…クの対象をこのカードにできる)【起動メイン】【ターン1回】自分の手札1枚を捨て、コスト2以下のキャラ1枚を持ち主のデッキの下に置くことができる：このキャラは、このターン中、パワー＋…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 73. OP06-058 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】コスト6以下のキャラ2枚までを、好きな順番で持ち主のデッキの下に置く。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 74. OP06-058_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】コスト6以下のキャラ2枚までを、好きな順番で持ち主のデッキの下に置く。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 75. OP06-058_r1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】コスト6以下のキャラ2枚までを、好きな順番で持ち主のデッキの下に置く。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 76. OP06-071 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラカード2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…徴《FILM》を持つ場合、自分のトラッシュの特徴《FILM》を持つコスト4以下のキャラカード2枚までを、手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 77. OP06-071 (L7, sev 4)

**cost_le_missing**: text に 「コスト 4 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…のリーダーが特徴《FILM》を持つ場合、自分のトラッシュの特徴《FILM》を持つコスト4以下のキャラカード2枚までを、手札に加える。`
- fix: `target に target_cost_le: 4 を 追加 (or target_spec 文字列 を cost_le_4 系 へ)`

### 78. OP06-075 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…のドン !!を指定の数ドン !!デッキに戻すことができる)：相手のコスト2以下のキャラ2枚までを、レストにする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 79. OP06-096 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【カウンター】自分のライフの上から1枚を手札に加えることができる：自分のコスト7以下のキャラすべては、このターン中、バトルでKOされない。`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 80. OP07-029 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 81. OP07-029_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 82. OP07-029_r1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 83. OP07-051 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手の「モンキー・D・ルフィ」以外のキャラ1枚までは、次の相手のターン終了時まで、アタックできない。その後、コスト1以下のキャラ1枚までを、持ち主のデッキの下に…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 84. OP07-051_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手の「モンキー・D・ルフィ」以外のキャラ1枚までは、次の相手のターン終了時まで、アタックできない。その後、コスト1以下のキャラ1枚までを、持ち主のデッキの下に…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 85. OP07-051_p2 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手の「モンキー・D・ルフィ」以外のキャラ1枚までは、次の相手のターン終了時まで、アタックできない。その後、コスト1以下のキャラ1枚までを、持ち主のデッキの下に…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 86. OP07-051_p3 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手の「モンキー・D・ルフィ」以外のキャラ1枚までは、次の相手のターン終了時まで、アタックできない。その後、コスト1以下のキャラ1枚までを、持ち主のデッキの下に…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 87. OP07-051_p4 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手の「モンキー・D・ルフィ」以外のキャラ1枚までは、次の相手のターン終了時まで、アタックできない。その後、コスト1以下のキャラ1枚までを、持ち主のデッキの下に…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 88. OP07-051_p5 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手の「モンキー・D・ルフィ」以外のキャラ1枚までは、次の相手のターン終了時まで、アタックできない。その後、コスト1以下のキャラ1枚までを、持ち主のデッキの下に…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 89. OP07-063 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…ダーが特徴《フォクシー海賊団》を持つ場合、相手のコスト6以下のキャラ1枚までは、次の相手のターン終了時までアタックできない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 90. OP07-076 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 91. OP07-076_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 92. OP07-076_r1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 93. OP07-079 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 94. OP07-079_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 95. OP07-079_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 96. OP07-091 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【アタック時】相手のコスト2以下のキャラ1枚までをトラッシュに置く。その後、自分のトラッシュからコスト4以上のキャラカー…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 97. OP07-091_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【アタック時】相手のコスト2以下のキャラ1枚までをトラッシュに置く。その後、自分のトラッシュからコスト4以上のキャラカー…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 98. OP08-001 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【起動メイン】【ターン1回】自分の特徴《動物》か《ドラム王国》を持つキャラ3枚までにレストのドン‼1枚ずつまでを、付与する。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 99. OP08-001_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【起動メイン】【ターン1回】自分の特徴《動物》か《ドラム王国》を持つキャラ3枚までにレストのドン‼1枚ずつまでを、付与する。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 100. OP08-001_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【起動メイン】【ターン1回】自分の特徴《動物》か《ドラム王国》を持つキャラ3枚までにレストのドン‼1枚ずつまでを、付与する。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`
