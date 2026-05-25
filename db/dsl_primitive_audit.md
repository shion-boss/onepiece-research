# DSL Primitive Audit

全 primitive: 284, 実装済: 248, 未実装/未検出: 36

## Missing (= 未実装 / 検出不可) primitives

| primitive | total | do | cost | if | when | sample cards |
|---|---|---|---|---|---|---|
| `in_hand_cost_plus` | 8 | 8 | 0 | 0 | 0 | OP12-093, OP12-093_p1, EB03-042 |
| `leader_passive` | 8 | 0 | 0 | 0 | 8 | OP05-074_p4, OP05-074_r1, OP05-074_r2 |
| `_chain` | 7 | 7 | 0 | 0 | 0 | PRB02-001, OP04-112, OP08-076 |
| `_condition` | 7 | 7 | 0 | 0 | 0 | PRB02-001, OP04-112, OP08-076 |
| `_text` | 7 | 7 | 0 | 0 | 0 | OP05-074_p4, OP05-074_r1, OP05-074_r2 |
| `self_hand_le` | 6 | 0 | 0 | 6 | 0 | OP11-041, OP11-041_p1, OP01-062 |
| `total_life_le` | 6 | 0 | 0 | 6 | 0 | P-088_p1, P-088_r1, OP09-100 |
| `on_self_chara_rested_by_self_effect` | 5 | 0 | 0 | 0 | 5 | OP07-031_p1, OP07-031_r2, OP10-036 |
| `returned_don_count_ge` | 4 | 0 | 0 | 4 | 0 | EB02-035, EB02-035_p1, EB02-035_p2 |
| `opp_hand_ge` | 4 | 0 | 0 | 4 | 0 | OP06-093, OP06-093_p3, OP06-093_p1 |
| `target_rested` | 4 | 0 | 0 | 4 | 0 | OP05-030_p2, OP05-030_r1, OP05-030 |
| `set_protect_from_opp_effect_static` | 4 | 4 | 0 | 0 | 0 | OP11-046, OP02-027, P-104 |
| `leader_attribute` | 3 | 0 | 0 | 3 | 0 | OP12-021, OP12-036, OP12-036_p1 |
| `on_self_life_taken` | 2 | 0 | 0 | 0 | 2 | OP11-041, OP11-041_p1 |
| `self_all_chara_feature` | 2 | 0 | 0 | 2 | 0 | OP15-001, OP15-001_p1 |
| `self_life_plus_hand_le` | 2 | 0 | 0 | 2 | 0 | OP04-040, OP04-040_p1 |
| `self_hand_eq` | 2 | 0 | 0 | 2 | 0 | OP02-049, OP02-049_p1 |
| `life_top_or_bottom_to_hand` | 2 | 0 | 2 | 0 | 0 | OP04-115, ST07-004 |
| `target_feature_contains` | 2 | 0 | 0 | 2 | 0 | OP13-047, OP13-060 |
| `target_name` | 2 | 0 | 0 | 2 | 0 | OP09-012, OP09-012_r1 |
| `target_truly_original_power_eq` | 2 | 0 | 0 | 2 | 0 | ST30-009, ST30-009_p1 |
| `either_player_don_total_eq_10` | 2 | 0 | 0 | 2 | 0 | P-104, P-104_p1 |
| `on_self_trigger_fired` | 1 | 0 | 0 | 0 | 1 | OP13-106 |
| `self_leader_power_le` | 1 | 0 | 0 | 1 | 0 | OP15-013 |
| `set_ko_immune_from_source_power_le` | 1 | 1 | 0 | 0 | 0 | OP14-003 |
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
| `on_play` | 1646 | when |
| `power_pump` | 930 | do |
| `trigger` | 797 | when |
| `activate_main` | 701 | when |
| `once_per_turn` | 630 | cost |
| `on_attack` | 530 | when |
| `draw` | 529 | do |
| `ko` | 487 | do |
| `on_attached_don` | 434 | when |
| `trash_self_hand_random` | 418 | do |
| `main` | 392 | when |
| `search_top_n` | 387 | do |
| `leader_feature` | 361 | if |
| `discard_hand` | 359 | cost |
| `pay_don` | 351 | do/cost |
| `give_keyword` | 325 | do |
| `optional_cost_then` | 283 | do |
| `counter` | 279 | when |
| `rest` | 269 | do |
| `on_ko` | 218 | when |
| `self_life_le` | 189 | if |
| `rest_self` | 174 | cost |
| `play_self` | 172 | do |
| `play_from_hand` | 160 | do |
| `add_don` | 153 | do |
| `attach_don` | 134 | do |
| `return_to_hand` | 130 | do |
| `opp_turn` | 130 | if |
| `untap_don` | 127 | do |
| `trash_self` | 117 | cost |
| `end_of_turn` | 106 | when |
| `self_attached_don_ge` | 103 | if |
| `self_turn` | 103 | if |
| `add_rested_don` | 103 | do |
| `fire_self_effect` | 102 | do |
| `cost_minus` | 101 | do |
| `leader_name` | 101 | if |
| `put_top_to_life` | 97 | do |
| `return_to_deck_bottom` | 92 | do |
| `rest_self_don` | 84 | do/cost |
| `untap` | 76 | do |
| `opp_attack` | 75 | when |
| `target` | 70 | if |
| `play_from_trash` | 69 | do |
| `leader_features_any` | 67 | if |
| `self_hand_count_le` | 67 | if |
| `life_to_hand` | 65 | do/cost |
| `by_opp_effect` | 62 | if |
| `self_trash_count_ge` | 60 | if |
| `look_top_reorder` | 53 | do |