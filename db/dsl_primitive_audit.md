# DSL Primitive Audit

全 primitive: 274, 実装済: 240, 未実装/未検出: 34

## Missing (= 未実装 / 検出不可) primitives

| primitive | total | do | cost | if | when | sample cards |
|---|---|---|---|---|---|---|
| `leader_passive` | 9 | 0 | 0 | 0 | 9 | OP05-074_p4, OP05-074_r1, OP05-074_r2 |
| `in_hand_cost_plus` | 8 | 8 | 0 | 0 | 0 | OP12-093, OP12-093_p1, EB03-042 |
| `_chain` | 7 | 7 | 0 | 0 | 0 | PRB02-001, OP04-112, OP08-076 |
| `_condition` | 7 | 7 | 0 | 0 | 0 | PRB02-001, OP04-112, OP08-076 |
| `_text` | 7 | 7 | 0 | 0 | 0 | OP05-074_p4, OP05-074_r1, OP05-074_r2 |
| `self_hand_le` | 6 | 0 | 0 | 6 | 0 | OP11-041, OP11-041_p1, OP01-062 |
| `on_self_chara_rested_by_self_effect` | 5 | 0 | 0 | 0 | 5 | OP07-031_p1, OP07-031_r2, OP10-036 |
| `returned_don_count_ge` | 4 | 0 | 0 | 4 | 0 | EB02-035, EB02-035_p1, EB02-035_p2 |
| `opp_hand_ge` | 4 | 0 | 0 | 4 | 0 | OP06-093, OP06-093_p3, OP06-093_p1 |
| `target_rested` | 4 | 0 | 0 | 4 | 0 | OP05-030_p2, OP05-030_r1, OP05-030 |
| `opp_discard_hand_to_deck_bottom` | 4 | 4 | 0 | 0 | 0 | OP06-044_p1, OP06-044_r1, OP08-046 |
| `set_protect_from_opp_effect_static` | 4 | 4 | 0 | 0 | 0 | OP11-046, OP02-027, P-104 |
| `return_self_chara_to_hand` | 3 | 0 | 3 | 0 | 0 | EB01-021_p2, EB01-021, EB01-021_p1 |
| `leader_attribute` | 3 | 0 | 0 | 3 | 0 | OP12-021, OP12-036, OP12-036_p1 |
| `on_self_life_taken` | 2 | 0 | 0 | 0 | 2 | OP11-041, OP11-041_p1 |
| `self_life_plus_hand_le` | 2 | 0 | 0 | 2 | 0 | OP04-040, OP04-040_p1 |
| `self_hand_eq` | 2 | 0 | 0 | 2 | 0 | OP02-049, OP02-049_p1 |
| `life_top_or_bottom_to_hand` | 2 | 0 | 2 | 0 | 0 | OP04-115, ST07-004 |
| `target_feature_contains` | 2 | 0 | 0 | 2 | 0 | OP13-047, OP13-060 |
| `target_name` | 2 | 0 | 0 | 2 | 0 | OP09-012, OP09-012_r1 |
| `target_truly_original_power_eq` | 2 | 0 | 0 | 2 | 0 | ST30-009, ST30-009_p1 |
| `either_player_don_total_eq_10` | 2 | 0 | 0 | 2 | 0 | P-104, P-104_p1 |
| `self_leader_power_le` | 1 | 0 | 0 | 1 | 0 | OP15-013 |
| `self_don_rested_ge` | 1 | 0 | 0 | 1 | 0 | OP12-021 |
| `set_cannot_be_rested_static` | 1 | 1 | 0 | 0 | 0 | OP12-021 |
| `opp_attacker_attribute` | 1 | 0 | 0 | 1 | 0 | OP11-088 |
| `self_not_rested` | 1 | 0 | 0 | 1 | 0 | OP08-029 |
| `opp_inplay_truly_original_power_ge_6000_count_ge` | 1 | 0 | 0 | 1 | 0 | OP06-012 |
| `self_leader_active` | 1 | 0 | 0 | 1 | 0 | OP06-088 |
| `on_self_draw_non_draw_phase` | 1 | 0 | 0 | 0 | 1 | OP05-053 |
| `self_ko` | 1 | 0 | 1 | 0 | 0 | OP03-043 |
| `self_deck_count_le` | 1 | 0 | 0 | 1 | 0 | OP03-045 |
| `self_don_active_eq` | 1 | 0 | 0 | 1 | 0 | OP02-027 |
| `cannot_attack_target_except` | 1 | 1 | 0 | 0 | 0 | P-067 |

## 実装済 primitives (top 50 by usage)

| primitive | total | category |
|---|---|---|
| `on_play` | 1650 | when |
| `power_pump` | 908 | do |
| `activate_main` | 701 | when |
| `trigger` | 664 | when |
| `once_per_turn` | 628 | cost |
| `on_attack` | 530 | when |
| `draw` | 520 | do |
| `ko` | 478 | do |
| `on_attached_don` | 415 | when |
| `trash_self_hand_random` | 411 | do |
| `search_top_n` | 387 | do |
| `main` | 384 | when |
| `discard_hand` | 358 | cost |
| `leader_feature` | 346 | if |
| `give_keyword` | 321 | do |
| `pay_don` | 306 | do/cost |
| `counter` | 279 | when |
| `optional_cost_then` | 273 | do |
| `rest` | 261 | do |
| `on_ko` | 218 | when |
| `self_life_le` | 176 | if |
| `rest_self` | 173 | cost |
| `play_from_hand` | 158 | do |
| `add_don` | 142 | do |
| `attach_don` | 134 | do |
| `return_to_hand` | 129 | do |
| `untap_don` | 127 | do |
| `trash_self` | 116 | cost |
| `opp_turn` | 113 | if |
| `end_of_turn` | 106 | when |
| `fire_self_effect` | 102 | do |
| `cost_minus` | 101 | do |
| `play_self` | 101 | do |
| `self_attached_don_ge` | 99 | if |
| `add_rested_don` | 99 | do |
| `self_turn` | 94 | if |
| `leader_name` | 93 | if |
| `return_to_deck_bottom` | 92 | do |
| `put_top_to_life` | 92 | do |
| `rest_self_don` | 84 | do/cost |
| `untap` | 76 | do |
| `opp_attack` | 71 | when |
| `target` | 69 | if |
| `play_from_trash` | 68 | do |
| `self_hand_count_le` | 67 | if |
| `leader_features_any` | 66 | if |
| `life_to_hand` | 65 | do/cost |
| `by_opp_effect` | 60 | if |
| `self_trash_count_ge` | 60 | if |
| `look_top_reorder` | 54 | do |