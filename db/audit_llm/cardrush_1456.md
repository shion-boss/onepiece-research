# LLM overlay 監査素材: cardrush_1456

カード数: 17

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP13-002
- name=ポートガス・Ｄ・エース / category=LEADER / power=6000 / counter=- / attribute=特 / color=赤/青 / features=白ひげ海賊団

### 公式テキスト
> 【相手のアタック時】【ターン1回】自分の手札1枚を捨てることができる：相手のリーダーかキャラ1枚までを、このバトル中、パワー-2000。【ドン‼×1】【ターン1回】自分がダメージを受けた時か自分の元々のパワー6000以上のキャラがKOされた時、カード1枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "赤青エース 相手アタック時: 相手リーダー -2000",
    "when": "opp_attack",
    "do": [
      {
        "power_pump": {
          "target": "opponent_leader",
          "amount": -2000,
          "duration": "turn"
        }
      }
    ],
    "cost": {
      "once_per_turn": true,
      "discard_hand": 1
    }
  },
  {
    "_text": "赤青エース ドン1+ 自分アタック時 1ドロー",
    "when": "on_attack",
    "if": {
      "self_don_active_ge": 1
    },
    "do": [
      {
        "draw": 1
      }
    ],
    "cost": {
      "once_per_turn": true
    }
  }
]
```

## ST22-002
- name=イゾウ / category=CHARACTER / cost=1 / power=- / counter=1000 / attribute=射 / color=青 / features=ワノ国/白ひげ海賊団

### 公式テキスト
> 【登場時】自分のデッキの上から5枚を見て、「イゾウ」以外の『白ひげ海賊団』を含む特徴を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。【相手のアタック時】このキャラをトラッシュに置くことができる：カード1枚を引き、自分の手札1枚をデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "イゾウ (青 cost1) 【登場時】白ひげサーチ",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "category": "CHARACTER",
            "feature": "白ひげ海賊団"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "trash"
        }
      }
    ]
  },
  {
    "_text": "ST22-002 opp_attack: このキャラをトラッシュに置くことができる：カード1枚を引き、自分の手札1枚をデッキの下に置く。",
    "when": "opp_attack",
    "do": [
      {
        "optional_cost_then": {
          "cost": [
            {
              "return_self_to_trash": true
            }
          ],
          "effect": [
            {
              "draw": 1
            },
            {
              "self_hand_to_deck_bottom": 1
            }
          ]
        }
      }
    ],
    "cost": {
      "trash_self": true
    }
  }
]
```

## OP13-016
- name=モンキー・Ｄ・ガープ / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=打 / color=赤 / features=海軍

### 公式テキスト
> 【登場時】自分のリーダーが「サボ」か「ポートガス・D・エース」か「モンキー・Ｄ・ルフィ」の場合、自分のデッキの上から4枚を見て、コスト3以上のカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP13-016 ガープ 登場時: サボ/エース/ルフィ リーダーで デッキ上4を見て cost3+ を1枚手札",
    "when": "on_play",
    "if": {
      "leader_name_in": [
        "サボ",
        "ポートガス・D・エース",
        "モンキー・D・ルフィ"
      ]
    },
    "do": [
      {
        "search_top_n": {
          "depth": 4,
          "filter": {
            "cost_ge": 3
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      }
    ]
  }
]
```

## OP13-043
- name=お玉 / category=CHARACTER / cost=1 / power=- / counter=2000 / attribute=特 / color=青 / features=ワノ国

### 公式テキスト
> 【登場時】自分のライフが3枚以下の場合、カード2枚を引き、自分の手札1枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "OP13-043 お玉 登場時: 自ライフ3以下なら 2ドロー + 1捨て",
    "when": "on_play",
    "if": {
      "self_life_le": 3
    },
    "do": [
      {
        "draw": 2
      },
      {
        "trash_self_hand_random": 1
      }
    ]
  }
]
```

## OP10-045
- name=キャベンディッシュ / category=CHARACTER / cost=4 / power=6000 / counter=- / attribute=斬 / color=青 / features=ドレスローザ/美しき海賊団

### 公式テキスト
> 【アタック時】【ターン1回】カード2枚を引き、自分の手札1枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "OP10-045 キャベ アタック時 (ターン1回): 2ドロー + 1捨て",
    "when": "on_attack",
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "draw": 2
      },
      {
        "trash_self_hand_random": 1
      }
    ]
  }
]
```

## OP08-040
- name=アトモス / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=斬 / color=青 / features=白ひげ海賊団

### 公式テキスト
> 【登場時】自分の手札から『白ひげ海賊団』を含む特徴を持つカード2枚を公開することができる：自分のリーダーが『白ひげ海賊団』を含む特徴を持つ場合、相手のコスト4以下のキャラ1枚までを、持ち主の手札に戻す。

### 現行 overlay
```json
[
  {
    "_text": "アトモス 登場時: 白ひげ海賊団リーダー時 相手キャラ1枚レスト",
    "when": "on_play",
    "if": {
      "leader_feature": "白ひげ海賊団"
    },
    "do": [
      {
        "rest": "one_opponent_character_cost_le_4"
      },
      {
        "return_to_hand": {
          "type": "one_opponent_character_filtered",
          "filter": {
            "cost_le": 4
          }
        }
      }
    ]
  }
]
```

## PRB02-008
- name=マルコ / category=CHARACTER / cost=4 / power=6000 / counter=- / attribute=特 / color=青 / features=ワノ国/元白ひげ海賊団

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【KO時】カード2枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "マルコ (青ブロッカー) KO時 2ドロー",
    "when": "on_ko",
    "do": [
      {
        "draw": 2
      }
    ]
  }
]
```

## OP13-054
- name=ヤマト / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=打 / color=青 / features=ワノ国

### 公式テキスト
> 【登場時】自分のライフが3枚以下の場合、カード2枚を引く。その後、自分のリーダーにレストのドン‼1枚までを、付与する。

### 現行 overlay
```json
[
  {
    "_text": "ヤマト 登場時: ライフ3以下なら2ドロー",
    "when": "on_play",
    "if": {
      "self_life_le": 3
    },
    "do": [
      {
        "draw": 2
      }
    ]
  }
]
```

## ST22-010
- name=ポートガス・Ｄ・エース / category=CHARACTER / cost=5 / power=6000 / counter=2000 / attribute=特 / color=青 / features=白ひげ海賊団

### 公式テキスト
> -

### 現行 overlay
`[]` (効果なし = バニラ / ブロッカーのみ / パラレル空 でマーク済)

## OP08-047
- name=ジョズ / category=CHARACTER / cost=6 / power=7000 / counter=1000 / attribute=打 / color=青 / features=白ひげ海賊団

### 公式テキスト
> 【登場時】このキャラ以外の自分のキャラ1枚を持ち主の手札に戻すことができる：コスト6以下のキャラ1枚までを、持ち主の手札に戻す。

### 現行 overlay
```json
[
  {
    "_text": "OP08-047 on_play: このキャラ以外の自分のキャラ1枚を持ち主の手札に戻すことができる：コスト6以下のキャラ1枚までを、持ち主の手札に戻す。",
    "when": "on_play",
    "do": [
      {
        "optional_cost_then": {
          "cost": [
            {
              "return_to_hand": "other_self_chara"
            }
          ],
          "effect": [
            {
              "return_to_hand": "one_opponent_character_cost_le_6cost"
            }
          ]
        }
      }
    ]
  }
]
```

## OP07-051
- name=ボア・ハンコック / category=CHARACTER / cost=6 / power=8000 / counter=- / attribute=特 / color=青 / features=王下七武海/九蛇海賊団

### 公式テキスト
> 【登場時】相手の「モンキー・D・ルフィ」以外のキャラ1枚までは、次の相手のターン終了時まで、アタックできない。その後、コスト1以下のキャラ1枚までを、持ち主のデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP07-051 on_play: 相手の「モンキー・D・ルフィ」以外のキャラ1枚までは、次の相手のターン終了時まで、アタックできない。その後、コスト1以下のキャラ1枚までを、持ち主のデッキの下に",
    "when": "on_play",
    "do": [
      {
        "return_to_deck_bottom": "one_opponent_character_any_cost_le_1"
      },
      {
        "set_cannot_attack": {
          "target": "one_opponent_character_any",
          "duration": "next_opp_turn_end"
        }
      }
    ]
  }
]
```

## ST23-001
- name=ウタ / category=CHARACTER / cost=6 / power=4000 / counter=2000 / attribute=特 / color=赤 / features=FILM

### 公式テキスト
> 手札のこのカードは、自分のパワー10000以上のキャラがいる場合、コスト-4。【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)

### 現行 overlay
```json
[
  {
    "_text": "ST23-001 ウタ 手札時 コスト-4: 自パワー10000+キャラあり",
    "when": "in_hand",
    "if": {
      "self_chara_power_ge": 10000
    },
    "do": [
      {
        "in_hand_cost_minus": 4
      }
    ]
  }
]
```

## EB04-007
- name=ロロノア・ゾロ / category=CHARACTER / cost=7 / power=9000 / counter=- / attribute=斬 / color=赤 / features=エッグヘッド/麦わらの一味

### 公式テキスト
> 【登場時】自分のリーダーを、次の相手のエンドフェイズ終了時まで、パワー+2000。【起動メイン】【ターン1回】相手のパワー8000以上のキャラがいる場合、このキャラは、このターン中、【速攻：キャラ】を得る。

### 現行 overlay
```json
[
  {
    "_text": "EB04-007 on_play: 自分のリーダーを、次の相手のエンドフェイズ終了時まで、パワー+2000。",
    "when": "on_play",
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 2000,
          "duration": "next_opp_turn_end"
        }
      }
    ]
  },
  {
    "_text": "EB04-007 起動メイン: 相手power8000+ キャラ存在で 速攻 + アクティブキャラアタック可",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "give_keyword": {
          "target": "self",
          "keyword": "速攻"
        }
      },
      {
        "give_attack_active_chara": "self"
      }
    ],
    "if": {
      "opp_chara_filtered_count_ge": {
        "filter": {
          "power_ge": 8000
        },
        "count": 1
      }
    }
  }
]
```

## OP13-042
- name=エドワード・ニューゲート / category=CHARACTER / cost=10 / power=12000 / counter=- / attribute=特 / color=青 / features=四皇/白ひげ海賊団

### 公式テキスト
> 【ブロッカー】【登場時】カード2枚を引き、自分の手札1枚を捨てる。その後、自分のリーダーとキャラ1枚にレストのドン‼2枚ずつまでを、付与する。

### 現行 overlay
```json
[
  {
    "_text": "OP13-042 白ひげ 登場時: 2ドロー + 1捨て + 自リーダーとキャラ1にレストドン2ずつ",
    "when": "on_play",
    "do": [
      {
        "draw": 2
      },
      {
        "trash_self_hand_random": 1
      },
      {
        "attach_don": {
          "target": "self_leader",
          "count": 2,
          "rested": true
        }
      },
      {
        "attach_don": {
          "target": "one_self_character_any",
          "count": 2,
          "rested": true
        }
      }
    ]
  }
]
```

## OP09-118
- name=ゴール・D・ロジャー / category=CHARACTER / cost=10 / power=13000 / counter=- / attribute=斬 / color=赤 / features=海賊王/ロジャー海賊団

### 公式テキスト
> 【速攻】(このカードは登場したターンにアタックできる)相手が【ブロッカー】を発動した時、自分か相手のライフが0枚の場合、自分はゲームに勝利する。

### 現行 overlay
```json
[
  {
    "_text": "OP09-118 on_opp_blocker_use: ライフ0 (either) で勝利",
    "when": "on_opp_blocker_use",
    "if": {
      "life_zero_either": true
    },
    "do": [
      {
        "win_game": true
      }
    ]
  }
]
```

## ST22-015
- name=おれァ‘‘白ひげ‘‘だァア!!!! / category=EVENT / cost=8 / power=- / counter=- / color=青 / features=四皇/白ひげ海賊団

### 公式テキスト
> 【メイン】自分のリーダーが『白ひげ海賊団』を含む特徴を持つ場合、自分の手札から「エドワード・ニューゲート」1枚までを、登場させる。その後、自分のライフの上か下から1枚を手札に加えてもよい。そうした場合、自分のリーダー1枚までを、次の相手のターン終了時まで、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "ST22-015 main: 自分のリーダーが『白ひげ海賊団』を含む特徴を持つ場合、自分の手札から「エドワード・ニューゲート」1枚までを、登場させる。その後、自分のライフの上か下から1枚を手",
    "when": "main",
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 2000,
          "duration": "next_opp_turn_end"
        }
      }
    ],
    "if": {
      "leader_features_any": [
        "白ひげ海賊団"
      ]
    }
  }
]
```

## OP14-018
- name=反撃に出るぞ / category=EVENT / cost=1 / power=- / counter=- / color=赤 / features=王下七武海/超新星/ハートの海賊団
- **trigger**: 【トリガー】自分の手札からパワー2000以下の赤のキャラカード1枚までを、登場させる。

### 公式テキスト
> 【カウンター】パワー8000以上のキャラがいる場合、自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。

### 現行 overlay
```json
[
  {
    "_text": "反撃に出るぞ カウンター: P8000+ あれば +4000",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 4000,
          "duration": "battle"
        }
      }
    ]
  },
  {
    "_text": "trigger: 手札から パワー2000以下 赤キャラ 1 登場",
    "when": "trigger",
    "do": [
      {
        "play_from_hand": {
          "filter": {
            "category": "CHARACTER",
            "color": "赤",
            "power_le": 2000
          },
          "limit": 1
        }
      }
    ]
  }
]
```
