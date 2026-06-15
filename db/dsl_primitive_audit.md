# DSL Primitive Audit

全 primitive: 368, 実装済: 341, 未実装/未検出: 27

## Missing (= 未実装 / 検出不可) primitives

| primitive | total | do | cost | if | when | sample cards |
|---|---|---|---|---|---|---|
| `set_protect_from_opp_effect_static` | 8 | 8 | 0 | 0 | 0 | EB04-057, EB03-018, EB03-018_p1 |
| `_text` | 7 | 7 | 0 | 0 | 0 | OP05-074_p4, OP05-074_r1, OP05-074_r2 |
| `on_self_chara_rested_by_self_effect` | 5 | 0 | 0 | 0 | 5 | OP07-031_p1, OP07-031_r2, OP10-036 |
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
| `on_play` | 1685 | when |
| `power_pump` | 880 | do |
| `trigger` | 793 | when |
| `activate_main` | 687 | when |
| `optional_cost_then` | 663 | do |
| `once_per_turn` | 609 | cost |
| `draw` | 544 | do |
| `on_attached_don` | 510 | when |
| `on_attack` | 473 | when |
| `main` | 405 | when |
| `search_top_n` | 395 | do |
| `leader_feature` | 369 | if |
| `ko` | 363 | do |
| `pay_don` | 328 | do/cost |
| `counter` | 301 | when |
| `give_keyword` | 277 | do |
| `self_attached_don_ge` | 276 | if |
| `rest` | 244 | do |
| `on_ko` | 235 | when |
| `trash_self_hand_random` | 227 | do |
| `play_from_hand` | 209 | do |
| `attach_rested_don` | 188 | do |
| `rest_self` | 177 | cost |
| `play_self` | 166 | do |
| `self_turn` | 134 | if |
| `opp_turn` | 128 | if |
| `add_don` | 127 | do |
| `self_life_le` | 122 | if |
| `cost_minus` | 115 | do |
| `leader_name` | 114 | if |
| `trash_self` | 111 | cost |
| `untap_don` | 110 | do |
| `end_of_turn` | 108 | when |
| `discard_hand` | 107 | cost |
| `rest_self_don` | 107 | do/cost |
| `fire_self_effect` | 107 | do |
| `return_to_hand` | 101 | do |
| `target` | 101 | if |
| `add_rested_don` | 101 | do |
| `conditional` | 100 | do |
| `return_to_deck_bottom` | 90 | do |
| `self_chara_filtered_count_ge` | 83 | if |
| `by_opp_effect` | 80 | if |
| `opp_attack` | 78 | when |
| `self_hand_count_le` | 68 | if |
| `put_top_to_life` | 66 | do |
| `play_from_trash` | 66 | do |
| `untap` | 65 | do |
| `leader_features_any` | 57 | if |
| `mill_self_top` | 57 | do |