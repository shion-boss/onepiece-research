//! OPTCG 状態モデル (Rust)。 engine/core.py のミラー。
//!
//! ⚠ これは scaffold = 主要 field のみ。 完全 port は core.py の InPlay(71) / Player(39) /
//! GameState(37) 全 field を写す (差分ハーネスが field 単位で一致を検証する)。
//! serde derive で canonical JSON serialize → sha1 digest を Python engine と突合する。
//!
//! 正準化の規約 (engine/state_snapshot.py と一致させること):
//!  - instance_id は除外 (グローバル採番タグ = 言語間で不一致、 状態の意味は card_id+flag+位置)
//!  - set は sorted、 dict は key sorted、 rng/log/overlay は除外

use serde::Serialize;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub enum Category {
    Leader,
    Character,
    Event,
    Stage,
}

/// 静的カード定義 (engine/core.py CardDef、 frozen)。 db/cards.json 由来。
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct CardDef {
    pub card_id: String,
    pub name: String,
    pub category: Category,
    pub color: Vec<String>,
    pub cost: i32,
    pub life: i32,
    pub power: i32,
    pub counter: i32,
    pub attribute: String,
    pub block_icon: i32,
    pub features: Vec<String>,
    // text/trigger/rarity は gameplay に効くもの (trigger) 以外 digest から除外予定
    pub trigger: String,
}

/// 場のカード (engine/core.py InPlay、 71 field)。 ここでは中核のみ。
/// ⚠ #[serde(skip)] instance_id 相当は持たせない (canonical から除外する規約)。
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct InPlay {
    // card は card_id に畳んで serialize (CardDef 全体でなく)
    #[serde(serialize_with = "ser_card_id")]
    pub card: CardDef,
    pub rested: bool,
    pub attached_dons: i32,
    pub summoning_sickness: bool,
    pub static_buff: i32,
    pub turn_buff: i32,
    pub battle_buff: i32,
    pub next_turn_buff: i32,
    // TODO(port): 残り ~60 field (granted_keywords/各種 ko_immune/base_power_override/
    //   時限 override 群 …) を core.py 順に追加。 各追加時に差分ハーネスで Python と突合。
}

fn ser_card_id<S: serde::Serializer>(c: &CardDef, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&c.card_id)
}

/// プレイヤー状態 (engine/core.py Player、 39 field)。 中核のみ。
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Player {
    pub name: String,
    pub leader: InPlay,
    #[serde(serialize_with = "ser_card_ids")]
    pub deck: Vec<CardDef>,
    #[serde(serialize_with = "ser_card_ids")]
    pub hand: Vec<CardDef>,
    pub characters: Vec<InPlay>,
    pub stages: Vec<InPlay>,
    #[serde(serialize_with = "ser_card_ids")]
    pub trash: Vec<CardDef>,
    #[serde(serialize_with = "ser_card_ids")]
    pub life: Vec<CardDef>,
    pub don_active: i32,
    pub don_rested: i32,
    pub don_remaining_in_deck: i32,
    // TODO(port): 残り Player field (play_cost_reduction/各種 turn フラグ/once_per_turn_used/
    //   known_*_card_ids/累積カウンタ …)。
}

fn ser_card_ids<S: serde::Serializer>(v: &[CardDef], s: S) -> Result<S::Ok, S::Error> {
    use serde::ser::SerializeSeq;
    let mut seq = s.serialize_seq(Some(v.len()))?;
    for c in v {
        seq.serialize_element(&c.card_id)?;
    }
    seq.end()
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub enum Phase {
    Refresh,
    Draw,
    Don,
    Main,
    End,
}

/// ゲーム状態 (engine/core.py GameState、 37 field)。 中核のみ。
/// rng/log/effects_overlay/snapshots/hook は canonical から除外 (Serialize で持たせない)。
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct GameState {
    pub players: Vec<Player>,
    pub turn_player_idx: usize,
    pub turn_number: i32,
    pub phase: Phase,
    pub winner: Option<usize>,
    pub game_over: bool,
    // TODO(port): pending_event/event_queue/resolving/extra_turn_pending/pending_attack_redirect …
}
