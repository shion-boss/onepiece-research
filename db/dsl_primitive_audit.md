# DSL Primitive Audit

全 primitive: 222, 実装済: 185, 未実装/未検出: 37

## Missing (= 未実装 / 検出不可) primitives

| primitive | total | do | cost | if | when | sample cards |
|---|---|---|---|---|---|---|
| `discard_hand` | 313 | 0 | 313 | 0 | 0 | EB03-025, OP06-051, OP09-044 |
| `end_of_turn` | 106 | 0 | 0 | 0 | 106 | OP02-001, OP04-029, OP04-034 |
| `opp_attack` | 71 | 0 | 0 | 0 | 71 | OP07-019, OP13-001, OP13-002 |
| `leader_features_any` | 46 | 0 | 0 | 46 | 0 | OP02-013, EB02-028, OP13-072 |
| `set_ko_immune` | 27 | 27 | 0 | 0 | 0 | OP15-118, OP13-083, OP13-089 |
| `target` | 25 | 0 | 0 | 25 | 0 | OP15-098, OP10-032, OP14-061 |
| `by_opp_effect` | 18 | 0 | 0 | 18 | 0 | OP15-098, OP10-032, OP14-061 |
| `in_hand` | 14 | 0 | 0 | 0 | 14 | ST23-001, EB04-061, OP15-021 |
| `discard_feature` | 11 | 0 | 11 | 0 | 0 | OP02-018_p3, OP02-018_p4, OP02-018_p5 |
| `set_base_cost` | 7 | 7 | 0 | 0 | 0 | OP15-092, OP15-092_p1, OP08-083 |
| `set_immune_attribute_in_battle` | 6 | 6 | 0 | 0 | 0 | OP11-005, P-007, P-025 |
| `reduce_play_cost_filtered_static` | 6 | 6 | 0 | 0 | 0 | OP01-067, OP01-067_p1, OP05-097_p1 |
| `target_feature` | 5 | 0 | 0 | 5 | 0 | OP15-098, OP14-061, OP15-098_p1 |
| `set_attack_taunt` | 5 | 5 | 0 | 0 | 0 | OP01-051, OP01-051_p3, OP01-051_p2 |
| `target_color` | 4 | 0 | 0 | 4 | 0 | OP10-032, OP10-032_p1, OP10-032_p2 |
| `target_name_exclude` | 4 | 0 | 0 | 4 | 0 | OP10-032, OP10-032_p1, OP10-032_p2 |
| `set_base_power` | 4 | 4 | 0 | 0 | 0 | OP15-092, OP15-092_p1 |
| `set_base_cost_filtered_static` | 4 | 4 | 0 | 0 | 0 | OP10-042, OP10-042_p1, OP10-042_p2 |
| `_if_clause` | 3 | 3 | 0 | 0 | 0 | EB03-053, EB03-053_p1, EB03-053_p2 |
| `target_power_le` | 3 | 0 | 0 | 3 | 0 | OP15-052, OP15-090, OP15-035 |
| `set_cannot_attack_static` | 3 | 3 | 0 | 0 | 0 | OP14-056, OP11-022, OP11-022_p1 |
| `replace_rest` | 3 | 0 | 0 | 0 | 3 | PRB02-006, PRB02-006_p1, PRB02-006_p2 |
| `by_opp_chara_effect` | 3 | 0 | 0 | 3 | 0 | PRB02-006, PRB02-006_p1, PRB02-006_p2 |
| `target_cost_le` | 3 | 0 | 0 | 3 | 0 | OP12-027, OP12-102, OP12-102_p1 |
| `don_phase_modifier` | 2 | 0 | 0 | 0 | 2 | OP13-003, OP13-003_p1 |
| `auto_attach_to_leader` | 2 | 2 | 0 | 0 | 0 | OP13-003, OP13-003_p1 |
| `game_start` | 2 | 0 | 0 | 0 | 2 | OP13-079, OP13-079_p1 |
| `summon_stage_from_deck_with_feature` | 2 | 2 | 0 | 0 | 0 | OP13-079, OP13-079_p1 |
| `target_power_ge` | 2 | 0 | 0 | 2 | 0 | OP15-098, OP15-098_p1 |
| `set_opp_protect_static` | 1 | 1 | 0 | 0 | 0 | OP14-079 |
| `setup_modifier` | 1 | 0 | 0 | 0 | 1 | OP15-058 |
| `on_self_life_lost` | 1 | 0 | 0 | 0 | 1 | OP12-099 |
| `target_attribute` | 1 | 0 | 0 | 1 | 0 | OP12-027 |
| `look_top_n_filter_to_hand` | 1 | 1 | 0 | 0 | 0 | EB04-029 |
| `discard_self_hand` | 1 | 0 | 1 | 0 | 0 | EB04-029 |
| `set_ko_immune_battle_only` | 1 | 1 | 0 | 0 | 0 | OP10-104 |
| `target_base_power_le` | 1 | 0 | 0 | 1 | 0 | OP15-069 |

## 実装済 primitives (top 50 by usage)

| primitive | total | category |
|---|---|---|
| `on_play` | 1609 | when |
| `power_pump` | 870 | do |
| `activate_main` | 684 | when |
| `trigger` | 667 | when |
| `once_per_turn` | 573 | cost |
| `on_attack` | 520 | when |
| `draw` | 519 | do |
| `ko` | 446 | do |
| `trash_self_hand_random` | 403 | do |
| `main` | 381 | when |
| `search` | 306 | do |
| `pay_don` | 299 | do/cost |
| `counter` | 279 | when |
| `leader_feature` | 278 | if |
| `optional_cost_then` | 269 | do |
| `on_attached_don` | 263 | when |
| `rest` | 238 | do |
| `on_ko` | 209 | when |
| `give_keyword` | 183 | do |
| `play_from_hand` | 159 | do |
| `attach_don` | 134 | do |
| `add_don` | 127 | do |
| `self_life_le` | 105 | if |
| `untap_don` | 104 | do |
| `fire_self_effect` | 104 | do |
| `return_to_hand` | 101 | do |
| `trash_self` | 101 | cost |
| `play_self` | 101 | do |
| `cost_minus` | 100 | do |
| `leader_name` | 89 | if |
| `self_attached_don_ge` | 87 | if |
| `put_top_to_life` | 87 | do |
| `return_to_deck_bottom` | 80 | do |
| `add_rested_don` | 79 | do |
| `untap` | 68 | do |
| `play_from_trash` | 65 | do |
| `search_top_n` | 63 | do |
| `life_to_hand` | 60 | do |
| `self_hand_count_le` | 58 | if |
| `self_trash_count_ge` | 54 | if |
| `look_top_reorder` | 52 | do |
| `rest_self` | 51 | cost |
| `self_turn` | 49 | if |
| `trash_opp_hand_random` | 48 | do |
| `opp_turn` | 45 | if |
| `self_don_ge` | 40 | if |
| `mill_self_top` | 37 | do |
| `trash_to_hand` | 37 | do |
| `untap_chara` | 36 | do |
| `opp_hand_count_ge` | 35 | if |