# DSL Primitive Audit

全 primitive: 386, 実装済: 351, 未実装/未検出: 35

## Missing (= 未実装 / 検出不可) primitives

| primitive | total | do | cost | if | when | sample cards |
|---|---|---|---|---|---|---|
| `pay_don` | 338 | 0 | 338 | 0 | 0 | EB01-031, EB01-031_p1, EB01-033 |
| `rest_self_don` | 124 | 0 | 124 | 0 | 0 | EB02-025, EB03-029, EB03-038 |
| `target_truly_original_power_le` | 10 | 0 | 0 | 10 | 0 | OP11-001, OP11-001_p1, OP15-009 |
| `set_protect_from_opp_effect_static` | 8 | 8 | 0 | 0 | 0 | EB03-018, EB03-018_p1, EB03-018_p2 |
| `target_truly_original_cost_le` | 7 | 0 | 0 | 7 | 0 | EB04-043, EB04-043_p1, OP10-049 |
| `_text` | 7 | 7 | 0 | 0 | 0 | OP05-074, OP05-074_p1, OP05-074_p2 |
| `on_self_chara_rested_by_self_effect` | 6 | 0 | 0 | 0 | 6 | OP07-031, OP07-031_p1, OP07-031_r1 |
| `on_self_battled` | 5 | 0 | 0 | 0 | 5 | OP04-047, ST02-010, ST02-010_p2 |
| `target_rested` | 4 | 0 | 0 | 4 | 0 | OP05-030, OP05-030_p1, OP05-030_p2 |
| `target_name` | 4 | 0 | 0 | 4 | 0 | OP09-012, OP09-012_r1, OP12-061 |
| `on_self_chara_leave_by_opp_effect` | 4 | 0 | 0 | 0 | 4 | OP09-080, OP13-078, OP16-041 |
| `target_truly_original_power_ge` | 4 | 0 | 0 | 4 | 0 | OP15-098, OP15-098_p1, ST30-011 |
| `set_deck_out_wins` | 3 | 3 | 0 | 0 | 0 | OP03-040, OP03-040_p1, P-117 |
| `set_battle_ko_immune_vs_leader` | 3 | 3 | 0 | 0 | 0 | OP09-025, ST08-002, ST08-002_p2 |
| `target_truly_original_cost_ge` | 2 | 0 | 0 | 2 | 0 | EB03-001, EB03-001_p1 |
| `on_self_don_attached` | 2 | 0 | 0 | 0 | 2 | OP02-002, OP02-002_p1 |
| `on_self_battle_ko` | 2 | 0 | 0 | 0 | 2 | OP02-094, OP04-086 |
| `on_self_trigger_fired` | 2 | 0 | 0 | 0 | 2 | OP05-109, OP13-106 |
| `play_multi_from_trash` | 2 | 2 | 0 | 0 | 0 | OP06-062, OP06-062_p1 |
| `return_self_don_to_deck` | 2 | 0 | 2 | 0 | 0 | OP06-074, OP14-070 |
| `on_turn_start` | 2 | 0 | 0 | 0 | 2 | OP11-040, OP11-040_p1 |
| `on_self_life_taken` | 2 | 0 | 0 | 0 | 2 | OP13-002, OP13-002_p1 |
| `target_feature_contains` | 2 | 0 | 0 | 2 | 0 | OP13-047, OP13-060 |
| `set_effect_negate_filtered_static` | 2 | 2 | 0 | 0 | 0 | OP13-064, OP13-064_p1 |
| `set_deck_out_defer` | 2 | 2 | 0 | 0 | 0 | OP15-022, OP15-022_p1 |
| `in_hand_cost_plus` | 2 | 2 | 0 | 0 | 0 | OP16-082, OP16-082_p1 |
| `set_hand_counter_boost` | 2 | 2 | 0 | 0 | 0 | OP16-118, OP16-118_p1 |
| `set_cannot_attack_filtered_static` | 2 | 2 | 0 | 0 | 0 | P-084, P-084_r1 |
| `set_battle_pump_vs_attribute` | 2 | 2 | 0 | 0 | 0 | ST05-010, ST05-010_r1 |
| `target_truly_original_power_eq` | 2 | 0 | 0 | 2 | 0 | ST30-009, ST30-009_p1 |
| `on_self_draw_non_draw_phase` | 1 | 0 | 0 | 0 | 1 | OP05-053 |
| `set_ko_immune_from_non_attribute` | 1 | 1 | 0 | 0 | 0 | OP11-005 |
| `set_cannot_be_rested_static` | 1 | 1 | 0 | 0 | 0 | OP12-021 |
| `set_ko_immune_from_source_power_le` | 1 | 1 | 0 | 0 | 0 | OP14-003 |
| `cannot_attack_target_except` | 1 | 1 | 0 | 0 | 0 | P-067 |

## 実装済 primitives (top 50 by usage)

| primitive | total | category |
|---|---|---|
| `on_play` | 1751 | when |
| `power_pump` | 867 | do |
| `trigger` | 824 | when |
| `optional_cost_then` | 756 | do |
| `activate_main` | 710 | when |
| `once_per_turn` | 586 | cost |
| `on_attached_don` | 550 | when |
| `draw` | 548 | do |
| `on_attack` | 484 | when |
| `main` | 413 | when |
| `search_top_n` | 394 | do |
| `ko` | 356 | do |
| `conditional` | 318 | do |
| `counter` | 305 | when |
| `leader_feature` | 283 | if |
| `give_keyword` | 283 | do |
| `self_attached_don_ge` | 271 | if |
| `on_ko` | 247 | when |
| `rest` | 240 | do |
| `trash_self_hand_random` | 220 | do |
| `play_from_hand` | 210 | do |
| `rest_self` | 176 | cost |
| `attach_rested_don` | 175 | do |
| `play_self` | 161 | do |
| `self_turn` | 151 | if |
| `opp_turn` | 131 | if |
| `add_don` | 130 | do |
| `trash_self` | 116 | cost |
| `end_of_turn` | 112 | when |
| `target` | 108 | if |
| `cost_minus` | 108 | do |
| `fire_self_effect` | 108 | do |
| `discard_hand` | 107 | cost |
| `untap_don` | 105 | do |
| `add_rested_don` | 100 | do |
| `self_life_le` | 98 | if |
| `return_to_hand` | 97 | do |
| `leader_name` | 92 | if |
| `by_opp_effect` | 88 | if |
| `return_to_deck_bottom` | 88 | do |
| `self_chara_filtered_count_ge` | 84 | if |
| `opp_attack` | 83 | when |
| `play_from_trash` | 71 | do |
| `untap` | 65 | do |
| `self_hand_count_le` | 64 | if |
| `put_top_to_life` | 59 | do |
| `replace_leave` | 59 | when |
| `leader_feature_contains` | 53 | if |
| `self_don_ge` | 53 | if |
| `set_base_cost` | 50 | do |