# LLM overlay 監査素材: tcgportal_coby

カード数: 15

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP11-001
- name=コビー / category=LEADER / power=5000 / counter=- / attribute=打 / color=赤/黒 / features=海軍/SWORD

### 公式テキスト
> 自分の特徴《SWORD》を持つキャラは、登場したターンにキャラへアタックできる。【ターン1回】自分の元々のパワー7000以下の特徴《海軍》を持つキャラが相手の効果で場を離れる場合、代わりに自分のトラッシュからカード3枚を好きな順番でデッキの下に置くことができる。

### 現行 overlay
```json
[
  {
    "_text": "OP11-001 on_attached_don (パターン未一致): 自分の特徴《SWORD》を持つキャラは、登場したターンにキャラへアタックできる。【ターン1回】自分の元々のパワー7000以下の特徴《海軍》を持つキャラが相手の効",
    "when": "on_attached_don",
    "n": 0,
    "do": [
      {
        "static_swords_attack_chara": true
      }
    ],
    "cost": {
      "once_per_turn": true
    }
  }
]
```

## EB04-047
- name=ヘルメッポ / category=CHARACTER / cost=3 / power=3000 / counter=2000 / attribute=斬 / color=黒 / features=海軍/SWORD

### 公式テキスト
> 【起動メイン】このキャラをトラッシュに置くことができる：自分の手札かトラッシュから「ヘルメッポ」以外のコスト3以下の特徴《SWORD》を持つキャラカード1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "EB04-047 activate_main: このキャラをトラッシュに置くことができる：自分の手札かトラッシュから「ヘルメッポ」以外のコスト3以下の特徴《SWORD》を持つキャラカード1枚までを、登場させる",
    "when": "activate_main",
    "do": [
      {
        "optional_cost_then": {
          "cost": [
            {
              "trash_self": true
            }
          ],
          "effect": [
            {
              "play_from_hand_or_trash": {
                "filter": {
                  "category": "CHARACTER",
                  "feature": "SWORD",
                  "cost_le": 3,
                  "exclude_name": "ヘルメッポ"
                },
                "limit": 1
              }
            }
          ]
        }
      }
    ]
  }
]
```

## OP13-007
- name=エース＆サボ＆ルフィ / category=CHARACTER / cost=1 / power=1000 / counter=2000 / attribute=打 / color=赤 / features=ゴア王国

### 公式テキスト
> 【起動メイン】自分のリーダーかキャラ1枚に自分のアクティブのドン‼1枚を付与し、このキャラをトラッシュに置くことができる：相手のキャラ1枚までを、このターン中、パワー-3000。

### 現行 overlay
```json
[
  {
    "_text": "OP13-007 activate_main: 自分のリーダーかキャラ1枚に自分のアクティブのドン‼1枚を付与し、このキャラをトラッシュに置くことができる：相手のキャラ1枚までを、このターン中、パワー-300",
    "when": "activate_main",
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -3000,
          "duration": "turn"
        }
      }
    ],
    "cost": {
      "trash_self": true
    }
  }
]
```

## OP11-092
- name=ヘルメッポ / category=CHARACTER / cost=6 / power=7000 / counter=- / attribute=斬 / color=黒 / features=海軍/SWORD

### 公式テキスト
> 【登場時】自分の手札1枚を捨てることができる：カード1枚を引き、自分のトラッシュから「ヘルメッポ」以外のコスト8以下の特徴《SWORD》を持つキャラカード1枚までを、登場させる。その後、このターン終了時、この効果で登場させたキャラ1枚を持ち主のデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP11-092 ヘルメッポ 登場時: 1捨て → draw1 + SWORDキャラtrash一時登場 (ターン終了時デッキ底へ)",
    "when": "on_play",
    "do": [
      {
        "draw": 1
      },
      {
        "play_from_trash": {
          "filter": {
            "category": "CHARACTER",
            "feature": "SWORD",
            "cost_le": 8,
            "exclude_name": "ヘルメッポ"
          },
          "limit": 1,
          "return_to_deck_bottom_at_turn_end": true
        }
      }
    ],
    "cost": {
      "discard_hand": 1
    }
  }
]
```

## EB04-044
- name=コビー / category=CHARACTER / cost=6 / power=7000 / counter=1000 / attribute=打 / color=黒 / features=海軍/SWORD

### 公式テキスト
> 【ターン1回】自分のリーダーが『海軍』を含む特徴を持ち、このキャラが場を離れる場合、代わりに自分の手札1枚を捨てることができる。【自分のターン中】【ターン1回】相手のキャラがKOされた時、カード1枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "EB04-044 replace_ko (海軍リーダー + ターン1回): 場を離れる代わりに手札1枚捨て",
    "when": "replace_leave",
    "if": {
      "target": "self",
      "leader_feature": "海軍"
    },
    "cost": [
      {
        "once_per_turn": true
      }
    ],
    "do": [
      {
        "trash_self_hand_random": 1
      }
    ],
    "optional": true
  },
  {
    "_text": "EB04-044 on_opp_chara_ko (自ターン中): 相手キャラ KO 時 1 ドロー",
    "when": "on_opp_chara_ko",
    "if": {
      "self_turn": true
    },
    "do": [
      {
        "draw": 1
      }
    ]
  }
]
```

## OP11-099
- name=ぼくは!!!海軍将校になる男です!!!! / category=EVENT / cost=1 / power=- / counter=- / color=黒 / features=東の海/海軍
- **trigger**: 【トリガー】このカードの【メイン】効果を発動する。

### 公式テキスト
> 【メイン】自分のデッキの上から3枚を見て、「ぼくは!!!海軍将校になる男です!!!!」以外の特徴《海軍》を持つカード1枚までを公開し、手札に加える。その後、残りをトラッシュに置く。

### 現行 overlay
```json
[
  {
    "_text": "OP11-099 main: 自分のデッキの上から3枚を見て、「ぼくは!!!海軍将校になる男です!!!!」以外の特徴《海軍》を持つカード1枚までを公開し、手札に加える。その後、残りをトラッシ",
    "when": "main",
    "do": [
      {
        "search_top_n": {
          "depth": 3,
          "filter": {
            "feature": "海軍",
            "exclude_name": "ぼくは!!!海軍将校になる男です!!!!"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "trash"
        }
      }
    ]
  },
  {
    "_text": "OP11-099 trigger: このカードの【メイン】効果を発動する。",
    "when": "trigger",
    "do": [
      {
        "fire_self_effect": {
          "when_kind": "main"
        }
      }
    ]
  }
]
```

## EB03-008
- name=ひばり / category=CHARACTER / cost=3 / power=5000 / counter=- / attribute=射 / color=赤 / features=海軍/SWORD

### 公式テキスト
> 【登場時】/【アタック時】自分の特徴《SWORD》を持つ、リーダーかキャラ1枚までは、このターン中、アクティブのキャラにもアタックできる。【起動メイン】【ターン1回】相手のキャラ1枚までを、このターン中、パワー-1000。

### 現行 overlay
```json
[
  {
    "_text": "EB03-008 on_attack: 自分の特徴《SWORD》を持つ、リーダーかキャラ1枚までは、このターン中、アクティブのキャラにもアタックできる。",
    "when": "on_attack",
    "do": [
      {
        "give_attack_active_chara": {
          "target": {
            "type": "one_self_chara_or_leader_filtered",
            "filter": {
              "feature": "SWORD"
            }
          }
        }
      }
    ]
  },
  {
    "_text": "EB03-008 activate_main: 【ターン1回】相手のキャラ1枚までを、このターン中、パワー-1000。",
    "when": "activate_main",
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -1000,
          "duration": "turn"
        }
      }
    ],
    "cost": {
      "once_per_turn": true
    }
  },
  {
    "_text": "EB03-008 on_play: 自分の特徴《SWORD》を持つ、リーダーかキャラ1枚までは、このターン中、アクティブのキャラにもアタックできる。",
    "when": "on_play",
    "do": [
      {
        "give_attack_active_chara": {
          "target": {
            "type": "one_self_chara_or_leader_filtered",
            "filter": {
              "feature": "SWORD"
            }
          }
        }
      }
    ]
  }
]
```

## OP11-096
- name=リッパー / category=CHARACTER / cost=1 / power=1000 / counter=1000 / attribute=知 / color=黒 / features=東の海/海軍

### 公式テキスト
> 「リッパー」以外の自分の黒の特徴《海軍》を持つキャラがいる場合、このキャラは【ブロッカー】を得る。(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)

### 現行 overlay
```json
[
  {
    "_text": "「リッパー」以外の自分の黒の特徴《海軍》を持つキャラがいる場合、このキャラは【ブロッカー】を得る。",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_chara_filtered_count_ge": {
        "filter": {
          "color": "黒",
          "feature": "海軍",
          "exclude_name": "リッパー"
        },
        "count": 1
      }
    },
    "do": [
      {
        "give_keyword": {
          "target": "self",
          "keyword": "ブロッカー"
        }
      }
    ]
  }
]
```

## OP11-008
- name=ドール / category=CHARACTER / cost=4 / power=1000 / counter=1000 / attribute=打 / color=赤 / features=海軍

### 公式テキスト
> 【ブロッカー】【登場時】自分の手札1枚を捨てることができる：自分のリーダーが特徴《海軍》を持つ場合、相手のキャラ1枚までを、このターン中、パワー-6000。

### 現行 overlay
```json
[
  {
    "_text": "OP11-008 on_play: 自分の手札1枚を捨てることができる：自分のリーダーが特徴《海軍》を持つ場合、相手のキャラ1枚までを、このターン中、パワー-6000。",
    "when": "on_play",
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -6000,
          "duration": "turn"
        }
      }
    ],
    "cost": {
      "discard_hand": 1
    },
    "if": {
      "leader_feature": "海軍"
    }
  }
]
```

## OP11-004
- name=孔雀 / category=CHARACTER / cost=1 / power=- / counter=1000 / attribute=特 / color=赤 / features=海軍/SWORD

### 公式テキスト
> 【登場時】自分のデッキの上から5枚を見て、「孔雀」以外の特徴《海軍》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。【起動メイン】このキャラをトラッシュに置くことができる：自分のキャラ1枚までを、このターン中、パワー+1000。

### 現行 overlay
```json
[
  {
    "_text": "OP11-004 on_play: 自分のデッキの上から5枚を見て、「孔雀」以外の特徴《海軍》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "feature": "海軍",
            "exclude_name": "孔雀"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      }
    ]
  },
  {
    "_text": "OP11-004 activate_main: このキャラをトラッシュに置くことができる：自分のキャラ1枚までを、このターン中、パワー+1000。",
    "when": "activate_main",
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
              "power_pump": {
                "target": "one_self_character_any",
                "amount": 1000,
                "duration": "turn"
              }
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

## PRB02-001
- name=コビー / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=打 / color=赤 / features=海軍/SWORD

### 公式テキスト
> 【相手のターン中】自分のリーダーが特徴《海軍》を持つ場合、このキャラのパワー+1000。【アタック時】相手の元々のパワー3000以下のキャラ1枚までを、KOする。その後、自分の手札が6枚以下の場合、カード1枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "【アタック時】相手の元々のパワー3000以下のキャラ1枚をKO。 その後、 手札6以下で draw 1",
    "when": "on_attack",
    "do": [
      {
        "ko": {
          "type": "one_opponent_character_filtered",
          "filter": {
            "truly_original_power_le": 3000
          }
        }
      },
      {
        "draw": 1,
        "_chain": "always",
        "_condition": {
          "self_hand_count_le": 6
        }
      }
    ]
  },
  {
    "_text": "【相手のターン中】自分のリーダーが特徴《海軍》を持つ場合、このキャラのパワー+1000。",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "opp_turn": true,
      "leader_feature": "海軍"
    },
    "do": [
      {
        "power_pump": {
          "target": "self",
          "amount": 1000,
          "duration": "static"
        }
      }
    ]
  }
]
```

## OP11-018
- name=実直拳骨 / category=EVENT / cost=6 / power=- / counter=- / color=赤 / features=海軍/SWORD
- **trigger**: 【トリガー】相手のパワー6000以下のキャラ1枚までを、KOする。

### 公式テキスト
> 【メイン】相手のキャラ1枚までを、このターン中、パワー-4000。その後、相手のパワー6000以下のキャラ1枚までを、KOする。

### 現行 overlay
```json
[
  {
    "_text": "OP11-018 main: 相手のキャラ1枚までを、このターン中、パワー-4000。その後、相手のパワー6000以下のキャラ1枚までを、KOする。",
    "when": "main",
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -4000,
          "duration": "turn"
        }
      },
      {
        "ko": "one_opponent_character_power_le_6000"
      }
    ]
  },
  {
    "_text": "OP11-018 trigger: 相手のパワー6000以下のキャラ1枚までを、KOする。",
    "when": "trigger",
    "do": [
      {
        "ko": "one_opponent_character_power_le_6000"
      }
    ]
  }
]
```

## OP11-082
- name=アラマキ / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=特 / color=黒 / features=海軍

### 公式テキスト
> 【起動メイン】このキャラをトラッシュに置くことができる：自分のリーダーが特徴《海軍》を持つ場合、自分の特徴《海軍》を持つキャラ1枚までは、このターン中、アクティブのキャラにもアタックできる。その後、自分のデッキの上から2枚をトラッシュに置く。

### 現行 overlay
```json
[
  {
    "_text": "OP11-082 アラマキ 起動メイン: 自KO cost → 自海軍 1 に アクティブキャラアタック可 + デッキ上2 trash",
    "when": "activate_main",
    "do": [
      {
        "give_attack_active_chara": {
          "target": {
            "type": "one_self_chara_or_leader_filtered",
            "filter": {
              "feature": "海軍"
            }
          }
        }
      },
      {
        "mill_self_top": 2
      }
    ],
    "cost": {
      "trash_self": true
    },
    "if": {
      "leader_feature": "海軍"
    }
  }
]
```

## EB03-041
- name=孔雀 / category=CHARACTER / cost=4 / power=6000 / counter=- / attribute=特 / color=黒 / features=海軍/SWORD

### 公式テキスト
> 【相手のターン中】自分のコスト6以下の特徴《SWORD》を持つキャラすべてを、パワー+2000。【登場時】自分の手札から特徴《海軍》を持つカード1枚を捨てることができる：カード2枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "EB03-041 on_play: 自分の手札から特徴《海軍》を持つカード1枚を捨てることができる：カード2枚を引く。",
    "when": "on_play",
    "do": [
      {
        "draw": 2
      }
    ],
    "cost": {
      "discard_hand_with_filter": {
        "filter": {
          "feature": "海軍"
        },
        "count": 1
      }
    }
  },
  {
    "_text": "EB03-041 孔雀 相手ターン中: 自コスト6以下 SWORD キャラ全員 +2000",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "opp_turn": true
    },
    "do": [
      {
        "power_pump": {
          "target": {
            "type": "all_self_chara_filtered",
            "filter": {
              "cost_le": 6,
              "feature": "SWORD"
            }
          },
          "amount": 2000,
          "duration": "static"
        }
      }
    ]
  }
]
```

## OP11-013
- name=プリンス・グルス / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=特 / color=赤 / features=海軍/SWORD

### 公式テキスト
> 【アタック時】相手のパワー2000以下のキャラすべては、このターン中、【ブロッカー】を発動できない。

### 現行 overlay
```json
[
  {
    "_text": "OP11-013 プリンス・グルス アタック時: 相手 power 2000 以下 キャラすべて は このターン中【ブロッカー】 使用不能",
    "when": "on_attack",
    "do": [
      {
        "disable_blocker": {
          "target": {
            "type": "all_opponent_chara_filtered",
            "filter": {
              "power_le": 2000
            }
          },
          "duration": "turn"
        }
      }
    ]
  }
]
```
