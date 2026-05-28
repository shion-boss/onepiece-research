# Static Audit Report (Layer 1)

generated: 2026-05-28T15:50:08.587388Z  
cards scanned: 4518  
issues total: 143  

## by rule

- `L3`: 47
- `L4`: 43
- `L7`: 26
- `L8`: 27

## by category

- `self_opp_reversal_suspect`: 47
- `count_limit_missing`: 43
- `duration_next_turn_missing`: 27
- `cost_le_missing`: 26

## by severity

- sev 4: 53
- sev 3: 43
- sev 2: 47

## top 100 issues

### 1. EB04-040 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 2. EB04-044 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 3. EB04-044_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 4. EB04-044_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 5. EB04-052 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 6. EB04-052_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 7. OP01-013 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラにレストのドン‼2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…に加えることができる：このキャラは、このターン中、パワー+2000。その後、このキャラにレストのドン‼2枚までを付与する。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 8. OP01-013_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラにレストのドン‼2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…に加えることができる：このキャラは、このターン中、パワー+2000。その後、このキャラにレストのドン‼2枚までを付与する。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 9. OP01-013_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラにレストのドン‼2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…に加えることができる：このキャラは、このターン中、パワー+2000。その後、このキャラにレストのドン‼2枚までを付与する。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 10. OP01-013_p3 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラにレストのドン‼2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…に加えることができる：このキャラは、このターン中、パワー+2000。その後、このキャラにレストのドン‼2枚までを付与する。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 11. OP02-013 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 12. OP02-013_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 13. OP02-013_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 14. OP02-013_p3 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 15. OP02-013_p5 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 16. OP02-013_r1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 17. OP02-094 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 18. OP02-112 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 19. OP03-025 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのコスト4以下のキャラ2枚までを、KOする。【ドン!!×1】このキャラは【ダブルアタック】を得る。(このカード…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 20. OP03-025_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】自分の手札1枚を捨てることができる：相手のレストのコスト4以下のキャラ2枚までを、KOする。【ドン!!×1】このキャラは【ダブルアタック】を得る。(このカード…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 21. OP03-038 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】相手のコスト2以下のキャラ2枚までを、レストにする`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 22. OP03-095 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】相手のキャラ2枚までを、このターン中、コスト-2。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 23. OP04-055 (L7, sev 4)

**cost_le_missing**: text に 「コスト 4 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【メイン】自分の手札から「氷鬼」1枚を捨て、コスト4以下のキャラ1枚を、持ち主のデッキの下に置くことができる：自分のトラッシュから「氷鬼」1枚を…`
- fix: `target に target_cost_le: 4 を 追加 (or target_spec 文字列 を cost_le_4 系 へ)`

### 24. OP05-002 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `…》を持つカード1枚を捨てることができる：自分の特徴《革命軍》か【トリガー】を持つキャラ3枚までを、このターン中、パワー+3000。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 25. OP05-002_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `…》を持つカード1枚を捨てることができる：自分の特徴《革命軍》か【トリガー】を持つキャラ3枚までを、このターン中、パワー+3000。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 26. OP05-002_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `…》を持つカード1枚を捨てることができる：自分の特徴《革命軍》か【トリガー】を持つキャラ3枚までを、このターン中、パワー+3000。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 27. OP05-041 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 28. OP05-041_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 29. OP05-045 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【起動メイン】自分の手札1枚を捨て、このキャラをレストにできる：コスト2以下のキャラ1枚までを、持ち主のデッキの下に置く。`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 30. OP06-001 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 31. OP06-001_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 32. OP06-001_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 33. OP06-035 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 34. OP06-035_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 35. OP06-035_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 36. OP06-035_r1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン !!合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【速攻】(このカードは登場したターンにアタックできる)【登場時】相手の、キャラかドン !!合計2枚までを、レストにする。その後、自分のライフの上から1枚を手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 37. OP06-043 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…クの対象をこのカードにできる)【起動メイン】【ターン1回】自分の手札1枚を捨て、コスト2以下のキャラ1枚を持ち主のデッキの下に置くことができる：このキャラは、このターン中、パワー＋…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 38. OP06-043_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…クの対象をこのカードにできる)【起動メイン】【ターン1回】自分の手札1枚を捨て、コスト2以下のキャラ1枚を持ち主のデッキの下に置くことができる：このキャラは、このターン中、パワー＋…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 39. OP06-058 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】コスト6以下のキャラ2枚までを、好きな順番で持ち主のデッキの下に置く。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 40. OP06-058_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】コスト6以下のキャラ2枚までを、好きな順番で持ち主のデッキの下に置く。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 41. OP06-058_r1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】コスト6以下のキャラ2枚までを、好きな順番で持ち主のデッキの下に置く。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 42. OP06-071 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラカード2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…徴《FILM》を持つ場合、自分のトラッシュの特徴《FILM》を持つコスト4以下のキャラカード2枚までを、手札に加える。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 43. OP06-071 (L7, sev 4)

**cost_le_missing**: text に 「コスト 4 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…のリーダーが特徴《FILM》を持つ場合、自分のトラッシュの特徴《FILM》を持つコスト4以下のキャラカード2枚までを、手札に加える。`
- fix: `target に target_cost_le: 4 を 追加 (or target_spec 文字列 を cost_le_4 系 へ)`

### 44. OP06-075 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…のドン !!を指定の数ドン !!デッキに戻すことができる)：相手のコスト2以下のキャラ2枚までを、レストにする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 45. OP06-096 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【カウンター】自分のライフの上から1枚を手札に加えることができる：自分のコスト7以下のキャラすべては、このターン中、バトルでKOされない。`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 46. OP07-029 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 47. OP07-029_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 48. OP07-029_r1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 49. OP07-076 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 50. OP07-076_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 51. OP07-076_r1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 52. OP07-079 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 53. OP07-079_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 54. OP07-079_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 55. OP07-091 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【アタック時】相手のコスト2以下のキャラ1枚までをトラッシュに置く。その後、自分のトラッシュからコスト4以上のキャラカー…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 56. OP07-091_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 2 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【アタック時】相手のコスト2以下のキャラ1枚までをトラッシュに置く。その後、自分のトラッシュからコスト4以上のキャラカー…`
- fix: `target に target_cost_le: 2 を 追加 (or target_spec 文字列 を cost_le_2 系 へ)`

### 57. OP08-001 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【起動メイン】【ターン1回】自分の特徴《動物》か《ドラム王国》を持つキャラ3枚までにレストのドン‼1枚ずつまでを、付与する。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 58. OP08-001_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【起動メイン】【ターン1回】自分の特徴《動物》か《ドラム王国》を持つキャラ3枚までにレストのドン‼1枚ずつまでを、付与する。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 59. OP08-001_p2 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【起動メイン】【ターン1回】自分の特徴《動物》か《ドラム王国》を持つキャラ3枚までにレストのドン‼1枚ずつまでを、付与する。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 60. OP08-001_p3 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ3枚まで」 が 含まれる が overlay に count: 3 制限 なし

- text: `【起動メイン】【ターン1回】自分の特徴《動物》か《ドラム王国》を持つキャラ3枚までにレストのドン‼1枚ずつまでを、付与する。`
- fix: `該当 effect に count: 3 (or limit: 3) を 追加`

### 61. OP08-022 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…登場時】自分のリーダーが特徴《ミンク族》を持つ場合、相手のレストのコスト5以下のキャラ2枚までは、次の相手のリフレッシュフェイズでアクティブにならない。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 62. OP08-069 (L7, sev 4)

**cost_le_missing**: text に 「コスト 6 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…ことができる：自分のデッキの上から1枚までを、ライフの上に加える。その後、相手のコスト6以下のキャラ1枚までを、相手のライフの上か下に表向きで加える。`
- fix: `target に target_cost_le: 6 を 追加 (or target_spec 文字列 を cost_le_6 系 へ)`

### 63. OP08-069_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 6 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…ことができる：自分のデッキの上から1枚までを、ライフの上に加える。その後、相手のコスト6以下のキャラ1枚までを、相手のライフの上か下に表向きで加える。`
- fix: `target に target_cost_le: 6 を 追加 (or target_spec 文字列 を cost_le_6 系 へ)`

### 64. OP08-069_p2 (L7, sev 4)

**cost_le_missing**: text に 「コスト 6 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…ことができる：自分のデッキの上から1枚までを、ライフの上に加える。その後、相手のコスト6以下のキャラ1枚までを、相手のライフの上か下に表向きで加える。`
- fix: `target に target_cost_le: 6 を 追加 (or target_spec 文字列 を cost_le_6 系 へ)`

### 65. OP08-079 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…回】自分の手札1枚を捨てることができる：このキャラが登場したターンの場合、相手のコスト7以下のキャラ1枚までを、トラッシュに置く。その後、相手は自身の手札1枚を捨てる。`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 66. OP08-079_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…回】自分の手札1枚を捨てることができる：このキャラが登場したターンの場合、相手のコスト7以下のキャラ1枚までを、トラッシュに置く。その後、相手は自身の手札1枚を捨てる。`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 67. OP08-118 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手のキャラ2枚までを選び、次の相手のターン終了時まで、1枚をパワー-3000し、残りをパワー-2000。その後、相手のパワー3000…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 68. OP08-118_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手のキャラ2枚までを選び、次の相手のターン終了時まで、1枚をパワー-3000し、残りをパワー-2000。その後、相手のパワー3000…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 69. OP08-118_p2 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手のキャラ2枚までを選び、次の相手のターン終了時まで、1枚をパワー-3000し、残りをパワー-2000。その後、相手のパワー3000…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 70. OP08-118_r1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `【登場時】相手のキャラ2枚までを選び、次の相手のターン終了時まで、1枚をパワー-3000し、残りをパワー-2000。その後、相手のパワー3000…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 71. OP09-033 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…上いる場合、自分の特徴《ODYSSEY》か《麦わらの一味》を持つキャラすべては、次の相手のターン終了時まで、効果でKOされない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 72. OP09-033_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…上いる場合、自分の特徴《ODYSSEY》か《麦わらの一味》を持つキャラすべては、次の相手のターン終了時まで、効果でKOされない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 73. OP09-033_r1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…上いる場合、自分の特徴《ODYSSEY》か《麦わらの一味》を持つキャラすべては、次の相手のターン終了時まで、効果でKOされない。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 74. OP09-036 (L7, sev 4)

**cost_le_missing**: text に 「コスト 6 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【登場時】自分のレストのキャラが2枚以上いる場合、相手のコスト6以下のキャラ1枚かドン‼1枚までを、レストにする。`
- fix: `target に target_cost_le: 6 を 追加 (or target_spec 文字列 を cost_le_6 系 へ)`

### 75. OP09-081 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…の【登場時】効果は無効になる。【起動メイン】自分の手札1枚を捨てることができる：次の相手のターン終了時まで、相手の【登場時】効果は無効になる。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 76. OP09-081_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…の【登場時】効果は無効になる。【起動メイン】自分の手札1枚を捨てることができる：次の相手のターン終了時まで、相手の【登場時】効果は無効になる。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 77. OP09-081_p2 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…の【登場時】効果は無効になる。【起動メイン】自分の手札1枚を捨てることができる：次の相手のターン終了時まで、相手の【登場時】効果は無効になる。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 78. OP09-081_p3 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のターン終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…の【登場時】効果は無効になる。【起動メイン】自分の手札1枚を捨てることができる：次の相手のターン終了時まで、相手の【登場時】効果は無効になる。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 79. OP09-101 (L7, sev 4)

**cost_le_missing**: text に 「コスト 3 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `【登場時】相手のコスト3以下のキャラ1枚を、相手のライフの上か下に表向きで置く：相手は自身の手札1枚を捨てる。`
- fix: `target に target_cost_le: 3 を 追加 (or target_spec 文字列 を cost_le_3 系 へ)`

### 80. OP10-023 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【登場時】自分のリーダーが特徴《海軍》を持つ場合、相手のコスト5以下のキャラ2枚までを、レストにする。`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 81. OP10-058 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラカード2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…の後、自分の手札から、「レベッカ」以外の特徴《ドレスローザ》を持つコスト7以下のキャラカード2枚までを、公開する。公開したカードのうち1枚を登場させ、残りがコスト4以下ならレストで…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 82. OP10-058 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…1枚を引く。その後、自分の手札から、「レベッカ」以外の特徴《ドレスローザ》を持つコスト7以下のキャラカード2枚までを、公開する。公開したカードのうち1枚を登場させ、残りがコスト4以…`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 83. OP10-058_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラカード2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `…の後、自分の手札から、「レベッカ」以外の特徴《ドレスローザ》を持つコスト7以下のキャラカード2枚までを、公開する。公開したカードのうち1枚を登場させ、残りがコスト4以下ならレストで…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 84. OP10-058_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 7 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…1枚を引く。その後、自分の手札から、「レベッカ」以外の特徴《ドレスローザ》を持つコスト7以下のキャラカード2枚までを、公開する。公開したカードのうち1枚を登場させ、残りがコスト4以…`
- fix: `target に target_cost_le: 7 を 追加 (or target_spec 文字列 を cost_le_7 系 へ)`

### 85. OP11-088 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 86. OP12-009 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…2枚を公開することができる：このキャラは、このターン中、【速攻】を得る。その後、次の相手のエンドフェイズ終了時まで、このキャラのパワー+1000。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 87. OP12-020 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 88. OP12-020_p1 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 89. OP12-020_p2 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 90. OP12-020_p3 (L3, sev 2)

**self_opp_reversal_suspect**: text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec に opp_* 系 が 1 つ も 無い (= 自他反転 疑い、 多く は false-positive)

- text: ``
- fix: `該当 target を opp_* spec へ 変更 (要 手動 確認)`

### 91. OP12-037 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン‼合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】自分のドン‼3枚をレストにできる：相手の、キャラかドン‼合計2枚までを、レストにする。【カウンター】自分のリーダーを、このバトル中、パワー+3000…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 92. OP12-037_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラかドン‼合計2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】自分のドン‼3枚をレストにできる：相手の、キャラかドン‼合計2枚までを、レストにする。【カウンター】自分のリーダーを、このバトル中、パワー+3000…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 93. OP12-051 (L7, sev 4)

**cost_le_missing**: text に 「コスト 4 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…メイン】このキャラをレストにし、自分の手札1枚を捨てることができる：相手の元々のコスト4以下のキャラ1枚までは、このターン中、【ブロッカー】を発動できない。`
- fix: `target に target_cost_le: 4 を 追加 (or target_spec 文字列 を cost_le_4 系 へ)`

### 94. OP12-051_p1 (L7, sev 4)

**cost_le_missing**: text に 「コスト 4 以下」 が 含まれる が overlay に target_cost_le / cost_le_N spec なし

- text: `…メイン】このキャラをレストにし、自分の手札1枚を捨てることができる：相手の元々のコスト4以下のキャラ1枚までは、このターン中、【ブロッカー】を発動できない。`
- fix: `target に target_cost_le: 4 を 追加 (or target_spec 文字列 を cost_le_4 系 へ)`

### 95. OP12-073 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…分の、「ドンキホーテ・ロシナンテ」と特徴《ハートの海賊団》を持つキャラすべてを、次の相手のエンドフェイズ終了時まで、パワー+1000。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 96. OP12-073_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…分の、「ドンキホーテ・ロシナンテ」と特徴《ハートの海賊団》を持つキャラすべてを、次の相手のエンドフェイズ終了時まで、パワー+1000。`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 97. OP12-119 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…きる：自分のデッキの上から1枚までを、ライフの上に加える。その後、このキャラは、次の相手のエンドフェイズ終了時まで、コスト+2。【相手のターン中】【KO時】自分のデッキの上から1枚までを、ライフ…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 98. OP12-119_p1 (L8, sev 4)

**duration_next_turn_missing**: text に 「次の相手のエンドフェイズ終了時まで」 (= 次ターン 跨ぎ) が 含まれる が overlay に 関連 next-turn duration 宣言 なし

- text: `…きる：自分のデッキの上から1枚までを、ライフの上に加える。その後、このキャラは、次の相手のエンドフェイズ終了時まで、コスト+2。【相手のターン中】【KO時】自分のデッキの上から1枚までを、ライフ…`
- fix: `該当 primitive に duration: 'next_opp_turn_end' を 追加`

### 99. OP13-040 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】自分のドン‼2枚をレストにできる：相手のレストのコスト7以下のキャラ2枚までは、次の相手のリフレッシュフェイズでアクティブにならない。【カウンター】自分のリ…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`

### 100. OP13-040_p1 (L4, sev 3)

**count_limit_missing**: text に chara/leader 文脈 で 「キャラ2枚まで」 が 含まれる が overlay に count: 2 制限 なし

- text: `【メイン】自分のドン‼2枚をレストにできる：相手のレストのコスト7以下のキャラ2枚までは、次の相手のリフレッシュフェイズでアクティブにならない。【カウンター】自分のリ…`
- fix: `該当 effect に count: 2 (or limit: 2) を 追加`
