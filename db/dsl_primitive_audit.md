# DSL Primitive Audit

全 primitive: 370, 実装済: 343, 未実装/未検出: 27

## Missing (= 未実装 / 検出不可) primitives

| primitive | total | do | cost | if | when | sample cards |
|---|---|---|---|---|---|---|
| `set_protect_from_opp_effect_static` | 8 | 8 | 0 | 0 | 0 | EB04-057, EB03-018, EB03-018_p1 |
| `_text` | 7 | 7 | 0 | 0 | 0 | OP05-074_p4, OP05-074_r1, OP05-074_r2 |
| `on_self_chara_rested_by_self_effect` | 6 | 0 | 0 | 0 | 6 | OP07-031_p1, OP07-031_r2, OP10-036 |
| `target_name` | 4 | 0 | 0 | 4 | 0 | OP12-061, OP12-061_p1, OP09-012 |
| `on_self_battled` | 4 | 0 | 0 | 0 | 4 | ST08-013, ST02-010, ST02-010_r1 |
| `target_rested` | 4 | 0 | 0 | 4 | 0 | OP05-030_p2, OP05-030_r1, OP05-030 |
| `set_battle_ko_immune_vs_leader` | 3 | 3 | 0 | 0 | 0 | ST08-002, ST08-002_p2, OP09-025 |
| `target_cost_ge` | 2 | 0 | 0 | 2 | 0 | EB03-001, EB03-001_p1 |
| `on_turn_start` | 2 | 0 | 0 | 0 | 2 | OP11-040, OP11-040_p1 |
| `on_self_life_taken` | 2 | 0 | 0 | 0 | 2 | OP13-002, OP13-002_p1 |
| `set_deck_out_wins` | 2 | 2 | 0 | 0 | 0 | OP03-040, OP03-040_p1 |
| `on_self_don_attached` | 2 | 0 | 0 | 0 | 2 | OP02-002, OP02-002_p1 |
| `set_effect_negate_filtered_static` | 2 | 2 | 0 | 0 | 0 | OP13-064, OP13-064_p1 |
| `play_multi_from_trash` | 2 | 2 | 0 | 0 | 0 | OP06-062, OP06-062_p1 |
| `on_self_battle_ko` | 2 | 0 | 0 | 0 | 2 | OP04-086, OP02-094 |
| `set_cannot_attack_filtered_static` | 2 | 2 | 0 | 0 | 0 | P-084_r1, P-084 |
| `set_battle_pump_vs_attribute` | 2 | 2 | 0 | 0 | 0 | ST05-010, ST05-010_r1 |
| `target_feature_contains` | 2 | 0 | 0 | 2 | 0 | OP13-047, OP13-060 |
| `target_truly_original_power_eq` | 2 | 0 | 0 | 2 | 0 | ST30-009, ST30-009_p1 |
| `on_self_trigger_fired` | 1 | 0 | 0 | 0 | 1 | OP13-106 |
| `set_ko_immune_from_non_attribute` | 1 | 1 | 0 | 0 | 0 | OP11-005 |
| `set_ko_immune_from_source_power_le` | 1 | 1 | 0 | 0 | 0 | OP14-003 |
| `set_cannot_be_rested_static` | 1 | 1 | 0 | 0 | 0 | OP12-021 |
| `on_self_draw_non_draw_phase` | 1 | 0 | 0 | 0 | 1 | OP05-053 |
| `cannot_attack_target_except` | 1 | 1 | 0 | 0 | 0 | P-067 |
| `static` | 1 | 0 | 0 | 0 | 1 | OP16-080 |
| `in_hand_cost_plus` | 1 | 1 | 0 | 0 | 0 | OP16-082 |

## 実装済 primitives (top 50 by usage)

| primitive | total | category |
|---|---|---|
| `on_play` | 1724 | when |
| `power_pump` | 900 | do |
| `trigger` | 821 | when |
| `activate_main` | 699 | when |
| `optional_cost_then` | 686 | do |
| `once_per_turn` | 619 | cost |
| `draw` | 558 | do |
| `on_attached_don` | 524 | when |
| `on_attack` | 482 | when |
| `main` | 411 | when |
| `search_top_n` | 402 | do |
| `leader_feature` | 378 | if |
| `ko` | 369 | do |
| `pay_don` | 332 | do/cost |
| `counter` | 306 | when |
| `give_keyword` | 286 | do |
| `self_attached_don_ge` | 279 | if |
| `rest` | 252 | do |
| `on_ko` | 241 | when |
| `trash_self_hand_random` | 231 | do |
| `play_from_hand` | 216 | do |
| `attach_rested_don` | 194 | do |
| `rest_self` | 181 | cost |
| `play_self` | 168 | do |
| `self_turn` | 139 | if |
| `opp_turn` | 129 | if |
| `add_don` | 129 | do |
| `self_life_le` | 122 | if |
| `leader_name` | 116 | if |
| `cost_minus` | 115 | do |
| `trash_self` | 112 | cost |
| `untap_don` | 111 | do |
| `rest_self_don` | 110 | do/cost |
| `end_of_turn` | 109 | when |
| `discard_hand` | 108 | cost |
| `fire_self_effect` | 108 | do |
| `return_to_hand` | 104 | do |
| `target` | 104 | if |
| `add_rested_don` | 104 | do |
| `conditional` | 103 | do |
| `return_to_deck_bottom` | 91 | do |
| `self_chara_filtered_count_ge` | 84 | if |
| `by_opp_effect` | 83 | if |
| `opp_attack` | 80 | when |
| `self_hand_count_le` | 68 | if |
| `put_top_to_life` | 67 | do |
| `untap` | 67 | do |
| `play_from_trash` | 67 | do |
| `mill_self_top` | 58 | do |
| `leader_features_any` | 57 | if |