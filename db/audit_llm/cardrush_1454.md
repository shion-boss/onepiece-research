# LLM overlay 監査素材: cardrush_1454

カード数: 17

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP15-058
- name=エネル / category=LEADER / power=5000 / counter=- / attribute=特 / color=紫 / features=空島

### 公式テキスト
> ルール上、自分のドン‼デッキは6枚になる。【起動メイン】【ターン1回】自分の第2ターン以降の場合、ドン‼デッキからドン‼1枚までをアクティブで追加し、さらに4枚までをレストで追加する。その後、自分のキャラ1枚にレストのドン‼4枚までを、付与する。

### 現行 overlay
```json
[
  {
    "_text": "紫エネル ルール: ドンデッキ 6 枚",
    "when": "setup_modifier",
    "do": [
      {
        "set_don_deck_size": 6
      }
    ]
  },
  {
    "_text": "紫エネル 起動メイン: 第2T+ アクティブドン+1 + レストドン+4",
    "when": "activate_main",
    "if": {
      "self_turn_number_ge": 2
    },
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "add_don": 1
      },
      {
        "add_rested_don": 4
      }
    ]
  }
]
```

## OP15-061
- name=オーム / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=斬 / color=紫 / features=空島/神官

### 公式テキスト
> 【登場時】ドン‼-1：カード1枚を引く。【アタック時】自分の場のドン‼が6枚以下の場合、相手のキャラ1枚までを、このターン中、パワー-1000。

### 現行 overlay
```json
[
  {
    "_text": "OP15-061 オーム 登場時: ドン-1 → 1ドロー",
    "when": "on_play",
    "cost": {
      "pay_don": 1
    },
    "do": [
      {
        "draw": 1
      }
    ]
  },
  {
    "_text": "OP15-061 オーム アタック時: 自場ドン6以下で 相手キャラ1 -1000 turn",
    "when": "on_attack",
    "if": {
      "self_don_le": 6
    },
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -1000,
          "duration": "turn"
        }
      }
    ]
  }
]
```

## OP15-067
- name=シュラ / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=斬 / color=紫 / features=空島/神官

### 公式テキスト
> 自分の場のドン‼が6枚以下の場合、このキャラは【速攻】を得る。(このカードは登場したターンにアタックできる)【登場時】ドン‼-1：カード1枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "OP15-067 シュラ 常在: 自場ドン6以下なら 速攻",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_don_le": 6
    },
    "do": [
      {
        "give_keyword": {
          "target": "self",
          "keyword": "速攻"
        }
      }
    ]
  },
  {
    "_text": "OP15-067 シュラ 登場時: ドン-1 → 1ドロー",
    "when": "on_play",
    "cost": {
      "pay_don": 1
    },
    "do": [
      {
        "draw": 1
      }
    ]
  }
]
```

## OP12-071
- name=シャーロット・プリン / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=知 / color=紫 / features=ビッグ・マム海賊団

### 公式テキスト
> 【登場時】自分のデッキの上から4枚を見て、「サンジ」かイベント1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP12-071 プリン 登場時: デッキ上4を見て サンジ or イベ 1を手札 残デッキ底",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 4,
          "filter": {
            "or": [
              {
                "name": "サンジ"
              },
              {
                "category": "EVENT"
              }
            ]
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

## OP15-066
- name=サトリ / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=打 / color=紫 / features=空島/神官

### 公式テキスト
> 【登場時】ドン‼-1：カード1枚を引く。【アタック時】自分の場のドン‼が6枚以下の場合、自分のデッキの上から2枚を見て、好きな順番に並び替え、デッキの上か下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP15-066 on_play: ドン‼-1：カード1枚を引く。",
    "when": "on_play",
    "do": [
      {
        "draw": 1
      }
    ],
    "cost": {
      "pay_don": 1
    }
  },
  {
    "_text": "OP15-066 on_attack: 自分の場のドン‼が6枚以下の場合、自分のデッキの上から2枚を見て、好きな順番に並び替え、デッキの上か下に置く。",
    "when": "on_attack",
    "do": [
      {
        "look_top_reorder": {
          "depth": 2,
          "to": "choice"
        }
      }
    ],
    "if": {
      "self_don_le": 6
    }
  }
]
```

## ST10-010
- name=トラファルガー・ロー / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=斬 / color=紫 / features=ハートの海賊団

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【登場時】ドン!!-1(自分の場のドン!!を指定の数ドン!!デッキに戻すことができる)：相手の手札が7枚以上ある場合、相手の手札2枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "ST10-010 on_play: ドン!!-1(自分の場のドン!!を指定の数ドン!!デッキに戻すことができる)：相手の手札が7枚以上ある場合、相手の手札2枚を捨てる。",
    "when": "on_play",
    "do": [
      {
        "trash_opp_hand_random": 2
      }
    ],
    "cost": {
      "pay_don": 1
    },
    "if": {
      "opp_hand_count_ge": 7
    }
  }
]
```

## OP10-067
- name=セニョール・ピンク / category=CHARACTER / cost=5 / power=6000 / counter=- / attribute=特 / color=紫 / features=ドンキホーテ海賊団

### 公式テキスト
> 【登場時】ドン‼-1(自分の場のドン!!を指定の数ドン!!デッキに戻すことができる)：自分のトラッシュからコスト5以下の紫のイベント1枚までを、手札に加える。その後、自分のドン‼1枚までを、アクティブにする。

### 現行 overlay
```json
[
  {
    "_text": "OP10-067 on_play: ドン‼-1(自分の場のドン!!を指定の数ドン!!デッキに戻すことができる)：自分のトラッシュからコスト5以下の紫のイベント1枚までを、手札に加える。その後、自分",
    "when": "on_play",
    "do": [
      {
        "untap_don": 1
      }
    ],
    "cost": {
      "pay_don": 1
    }
  }
]
```

## OP12-063
- name=ヴィンスモーク・レイジュ / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=特 / color=紫 / features=ヴィンスモーク家/ジェルマ66

### 公式テキスト
> 自分のトラッシュにイベントが4枚以上ある場合、このキャラのパワー+2000し、コスト+5。【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)

### 現行 overlay
```json
[
  {
    "_text": "レイジュ static: トラッシュ4枚以上で +2000",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_trash_count_ge": 4
    },
    "do": [
      {
        "power_pump": {
          "target": "self",
          "amount": 2000,
          "duration": "static"
        }
      }
    ]
  }
]
```

## OP09-072
- name=フランキー / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=打 / color=紫 / features=麦わらの一味

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【登場時】ドン!!-2,自分の手札1枚を捨てることができる：カード2枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "OP09-072 on_play: ドン!!-2,自分の手札1枚を捨てることができる：カード2枚を引く。",
    "when": "on_play",
    "do": [
      {
        "draw": 2
      },
      {
        "trash_self_hand_random": 1
      }
    ],
    "cost": {
      "pay_don": 2,
      "discard_hand": 1
    }
  }
]
```

## OP15-118
- name=エネル / category=CHARACTER / cost=6 / power=8000 / counter=- / attribute=特 / color=紫 / features=空島

### 公式テキスト
> 自分の場のドン‼が6枚以下の場合、このキャラは相手の効果で場を離れず、パワー+2000。【登場時】ドン‼-1：自分のデッキの上から5枚を見て、カード1枚までを手札に加える。その後、残りを好きな順番でデッキの下に置き、自分の手札1枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "OP15-118 エネル 常在: 自場ドン6以下なら このキャラ 相手効果不滅 + パワー +2000",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_don_le": 6
    },
    "do": [
      {
        "set_ko_immune": "self"
      },
      {
        "power_pump": {
          "target": "self",
          "amount": 2000,
          "duration": "static"
        }
      }
    ]
  },
  {
    "_text": "OP15-118 エネル 登場時: ドン-1, デッキ上5を見て1枚手札 + 残りデッキ底 + 1捨て",
    "when": "on_play",
    "cost": {
      "pay_don": 1
    },
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {},
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      },
      {
        "trash_self_hand_random": 1
      }
    ]
  }
]
```

## OP15-077
- name=雷龍 / category=EVENT / cost=- / power=- / counter=- / color=紫 / features=空島

### 公式テキスト
> 【メイン】ドン‼-1：カード1枚を引く。その後、相手のレストのパワー6000以下のキャラ1枚までは、次の相手のリフレッシュフェイズでアクティブにならない。

### 現行 overlay
```json
[
  {
    "_text": "OP15-077 雷龍 メイン: ドン-1 → 1ドロー + 相手レスト power6000以下1 stay_rested_next_refresh",
    "when": "main",
    "cost": {
      "pay_don": 1
    },
    "do": [
      {
        "draw": 1
      },
      {
        "stay_rested_next_refresh": "one_opponent_rested_character_power_le_6000"
      }
    ]
  }
]
```

## OP15-075
- name=神の裁き / category=EVENT / cost=- / power=- / counter=- / color=紫 / features=空島

### 公式テキスト
> 【メイン】ドン‼-1：自分のリーダーが「エネル」の場合、自分のリーダーかキャラ1枚までを、このターン中、パワー+1000。その後、相手のパワー3000以下のキャラ1枚までを、KOする。【カウンター】自分の「エネル」1枚までを、このバトル中、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "OP15-075 main: ドン‼-1：自分のリーダーが「エネル」の場合、自分のリーダーかキャラ1枚までを、このターン中、パワー+1000。その後、相手のパワー3000以下のキャラ1枚まで",
    "when": "main",
    "do": [
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 1000,
          "duration": "turn"
        }
      },
      {
        "ko": "one_opponent_character_power_le_3000"
      }
    ],
    "cost": {
      "pay_don": 1
    },
    "if": {
      "leader_name": "エネル"
    }
  },
  {
    "_text": "OP15-075 counter: 自分の「エネル」1枚までを、このバトル中、パワー+2000。",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": {
            "type": "self_chara_named",
            "name": "エネル"
          },
          "amount": 2000,
          "duration": "battle"
        }
      }
    ]
  }
]
```

## OP15-076
- name=雷獣 / category=EVENT / cost=- / power=- / counter=- / color=紫 / features=空島

### 公式テキスト
> 【メイン】ドン‼-1：自分のリーダーが「エネル」の場合、カード1枚を引く。その後、相手のキャラ1枚までを、このターン中、パワー-1000。【カウンター】自分の「エネル」1枚までを、このバトル中、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "OP15-076 main: ドン‼-1：自分のリーダーが「エネル」の場合、カード1枚を引く。その後、相手のキャラ1枚までを、このターン中、パワー-1000。",
    "when": "main",
    "do": [
      {
        "draw": 1
      },
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -1000,
          "duration": "turn"
        }
      }
    ],
    "cost": {
      "pay_don": 1
    },
    "if": {
      "leader_name": "エネル"
    }
  },
  {
    "_text": "OP15-076 counter: 自分の「エネル」1枚までを、このバトル中、パワー+2000。",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": {
            "type": "self_chara_named",
            "name": "エネル"
          },
          "amount": 2000,
          "duration": "battle"
        }
      }
    ]
  }
]
```

## OP15-078
- name=万雷 / category=EVENT / cost=- / power=- / counter=- / color=紫 / features=空島

### 公式テキスト
> 【メイン】ドン‼-2：カード1枚を引く。その後、相手のパワー5000以下のキャラ1枚までを、レストにする。【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+1000。その後、自分の場のドン‼が6枚以下の場合、カード1枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "OP15-078 main: ドン‼-2：カード1枚を引く。その後、相手のパワー5000以下のキャラ1枚までを、レストにする。",
    "when": "main",
    "do": [
      {
        "draw": 1
      },
      {
        "rest": "one_opponent_character_le_5000"
      }
    ],
    "cost": {
      "pay_don": 2
    }
  },
  {
    "_text": "OP15-078 counter: 自分のリーダーかキャラ1枚までを、このバトル中、パワー+1000。その後、自分の場のドン‼が6枚以下の場合、カード1枚を引く。",
    "when": "counter",
    "do": [
      {
        "draw": 1
      },
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 1000,
          "duration": "battle"
        }
      }
    ],
    "if": {
      "self_don_le": 6
    }
  }
]
```

## OP13-076
- name=神避 / category=EVENT / cost=- / power=- / counter=- / color=紫 / features=海賊王/ロジャー海賊団

### 公式テキスト
> 【メイン】自分のドン‼5枚をレストにできる：自分の付与されているドン‼がある場合、相手のキャラ1枚までを、このターン中、パワー-8000。【カウンター】自分の手札1枚を捨てることができる：自分のリーダーかキャラ1枚までを、このバトル中、パワー+3000。

### 現行 overlay
```json
[
  {
    "_text": "OP13-076 神避 メイン: ドン-5 + 自付与ドンあり → 相手キャラ1体 -8000 turn",
    "when": "main",
    "cost": {
      "rest_self_don": 5
    },
    "if": {
      "self_attached_don_ge": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -8000,
          "duration": "turn"
        }
      }
    ]
  },
  {
    "_text": "OP13-076 神避 カウンター: 手札1捨て → 自リーダー/キャラ +3000 battle",
    "when": "counter",
    "cost": {
      "discard_hand": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 3000,
          "duration": "battle"
        }
      }
    ]
  }
]
```

## OP05-077
- name=ガンマナイフ / category=EVENT / cost=2 / power=- / counter=- / color=紫 / features=ハートの海賊団
- **trigger**: 【トリガー】ドン!!デッキからドン!!1枚までを、アクティブで追加する。

### 公式テキスト
> 【メイン】ドン!!-1(自分の場のドン!!を指定の数ドン!!デッキに戻すことができる)：相手のキャラ1枚までを、このターン中、パワー-5000。

### 現行 overlay
```json
[
  {
    "_text": "OP05-077 ガンマナイフ メイン: ドン-1 → 相手キャラ1 -5000 turn",
    "when": "main",
    "cost": {
      "pay_don": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -5000,
          "duration": "turn"
        }
      }
    ]
  },
  {
    "_text": "trigger: ドン1 アクティブ 追加",
    "when": "trigger",
    "do": [
      {
        "add_don": 1
      }
    ]
  }
]
```

## OP15-074
- name=放電 / category=EVENT / cost=- / power=- / counter=- / color=紫 / features=空島

### 公式テキスト
> 【メイン】ドン‼-1：自分のリーダーが「エネル」の場合、カード1枚を引く。その後、自分のキャラ1枚までを、次の相手のエンドフェイズ終了時まで、コスト+2。【カウンター】自分の「エネル」1枚までを、このバトル中、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "OP15-074 main: ドン‼-1：自分のリーダーが「エネル」の場合、カード1枚を引く。その後、自分のキャラ1枚までを、次の相手のエンドフェイズ終了時まで、コスト+2。",
    "when": "main",
    "do": [
      {
        "draw": 1
      },
      {
        "cost_minus": {
          "target": "one_self_character_any",
          "amount": -2,
          "duration": "next_opp_turn_end"
        }
      }
    ],
    "cost": {
      "pay_don": 1
    },
    "if": {
      "leader_name": "エネル"
    }
  },
  {
    "_text": "OP15-074 counter: 自分の「エネル」1枚までを、このバトル中、パワー+2000。",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": {
            "type": "self_chara_named",
            "name": "エネル"
          },
          "amount": 2000,
          "duration": "battle"
        }
      }
    ]
  }
]
```
