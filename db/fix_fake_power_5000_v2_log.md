# fake_power_5000 v2 修正ログ

## OP02-013
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP11-028
  stay_rested_next_refresh: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## EB04-018
  ko: one_opponent_rested_character_le_5000 → one_opponent_character_power_le_8000
## OP08-040
  rest: one_opponent_character_le_5000 → one_opponent_character_cost_le_4
## OP07-019
  rest: one_opponent_character_le_5000 → one_opponent_inplay_any
## OP14-079
  ko: one_opponent_character_le_5000 → all_opponent_characters
## ST24-004
  rest: one_opponent_character_le_5000 → one_opponent_character_any
## OP08-036
  rest: one_opponent_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'cost_le': 7, 'rested': True}}
## OP13-076
  target (power_pump amount=8000): one_opponent_character_le_5000 → one_opponent_character_any
## OP05-077
  target (power_pump amount=5000): one_opponent_character_le_5000 → one_opponent_character_any
## OP15-061
  target (power_pump amount=1000): one_opponent_character_le_5000 → one_opponent_character_any
## OP07-076
  rest: one_opponent_character_le_5000 → one_opponent_character_any
## EB04-008
  target (power_pump amount=3000): one_opponent_character_le_5000 → one_opponent_character_any
## OP13-080
  target (power_pump amount=2000): one_opponent_character_le_5000 → one_opponent_character_any
## OP14-061
  target (power_pump amount=2000): one_opponent_character_le_5000 → one_opponent_character_any
## OP15-021
  target (power_pump amount=3000): one_opponent_character_le_5000 → one_opponent_character_any
## OP15-021
  target (power_pump amount=3000): one_opponent_character_le_5000 → one_opponent_character_any
## OP14-079_p1
  ko: one_opponent_character_le_5000 → all_opponent_characters
## OP07-019_p3
  rest: one_opponent_character_le_5000 → one_opponent_inplay_any
## ST15-002
  ko: one_opponent_character_power_le_5000 → one_opponent_character_le_5000
## EB01-010
  ko: one_opponent_character_power_le_5000 → one_opponent_character_power_le_6000
## OP15-063
  ko: one_opponent_character_le_5000 → one_opponent_character_power_le_2000
## OP11-020
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP08-019
  ko: one_opponent_character_power_le_5000 → one_opponent_character_any
## OP06-019
  ko: one_opponent_character_power_le_5000 → one_opponent_character_le_5000
## OP03-018
  ko: one_opponent_character_power_le_5000 → one_opponent_character_le_5000
## OP05-077_p1
  target (power_pump amount=5000): one_opponent_character_le_5000 → one_opponent_character_any
## OP07-076_p1
  rest: one_opponent_character_le_5000 → one_opponent_character_any
## ST15-002_p2
  ko: one_opponent_character_power_le_5000 → one_opponent_character_le_5000
## OP15-061_p1
  target (power_pump amount=1000): one_opponent_character_le_5000 → one_opponent_character_any
## OP14-061_p1
  target (power_pump amount=2000): one_opponent_character_le_5000 → one_opponent_character_any
## OP13-076_p1
  target (power_pump amount=8000): one_opponent_character_le_5000 → one_opponent_character_any
## OP13-080_p1
  target (power_pump amount=2000): one_opponent_character_le_5000 → one_opponent_character_any
## OP13-080_p2
  target (power_pump amount=2000): one_opponent_character_le_5000 → one_opponent_character_any
## ST15-002_p1
  ko: one_opponent_character_power_le_5000 → one_opponent_character_le_5000
## OP02-013_p3
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP03-018_p1
  ko: one_opponent_character_power_le_5000 → one_opponent_character_le_5000
## OP02-013_p1
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP02-013_p2
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP02-013_p5
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP08-036_p1
  rest: one_opponent_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'cost_le': 7, 'rested': True}}
## OP05-077_r1
  target (power_pump amount=5000): one_opponent_character_le_5000 → one_opponent_character_any
## OP07-026_r1
  stay_rested_next_refresh: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## OP07-076_r1
  rest: one_opponent_character_le_5000 → one_opponent_character_any
## ST15-002_r1
  ko: one_opponent_character_power_le_5000 → one_opponent_character_le_5000
## ST16-004_p2
  ko: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## ST16-004_r1
  ko: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## OP02-013_r1
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP05-007_p2
  ko: any_opponent_character_le_5000 → one_opponent_character_any
## OP05-007_r1
  ko: any_opponent_character_le_5000 → one_opponent_character_any
## EB04-060
  target (power_pump amount=1000): one_opponent_character_le_5000 → one_opponent_character_any
## EB01-039
  ko: one_opponent_character_le_5000 → one_opponent_character_cost_le_8
## EB01-042
  target (cost_minus amount=2): one_opponent_character_le_5000 → one_opponent_character_any
## OP12-043
  stay_rested_next_refresh: one_opponent_rested_character_le_5000 → one_opponent_character_any
## ST16-004_p1
  ko: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## OP09-018
  ko: any_opponent_character_le_5000 → one_opponent_character_any
## OP09-073
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP07-003
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP07-026
  stay_rested_next_refresh: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## OP07-026_p1
  stay_rested_next_refresh: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## OP06-033
  ko: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## OP05-007
  ko: any_opponent_character_le_5000 → one_opponent_character_any
## OP05-007_p1
  ko: any_opponent_character_le_5000 → one_opponent_character_any
## OP05-072
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP04-018
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP01-022
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP01-026
  ko: one_opponent_character_le_5000 → one_opponent_character_le_4000
## ST30-010
  stay_rested_next_refresh: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## ST30-010_p1
  stay_rested_next_refresh: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## ST26-004
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## OP05-072_r1
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2
## ST16-004
  ko: one_opponent_rested_character_le_5000 → {'type': 'one_opponent_character_filtered', 'filter': {'rested': True}}
## OP01-022_p1
  target (power_pump): any_opponent_character_le_5000 → all_opponent_chara_filtered limit=2