//! OPTCG 状態モデル (Rust)。 engine/core.py の完全ミラー (Phase R1)。
//!
//! 全 field を core.py 順に写す (InPlay 71 / Player 39 / GameState 37)。 差分ハーネス
//! (engine/state_snapshot.py) と同じ正準化規約:
//!  - instance_id は struct に持たない (グローバル採番タグ = 除外)
//!  - set → BTreeSet (sorted = canonical 一致) / dict → BTreeMap (key sorted)
//!  - CardDef → card_id に畳む / rng/log/overlay/hook は持たない
//!  - opaque な DSL payload (filter/delayed/event_queue) は serde_json::Value (R2/R3 で型付け)

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub enum Category {
    #[serde(rename = "LEADER")]
    Leader,
    #[default]
    #[serde(rename = "CHARACTER")]
    Character,
    #[serde(rename = "EVENT")]
    Event,
    #[serde(rename = "STAGE")]
    Stage,
}

/// 静的カード定義 (core.py CardDef、 frozen)。 db/cards.json 由来。 digest では card_id に畳む。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
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
    pub text: String,
    pub trigger: String,
}

fn find_subslice(hay: &[char], needle: &[char]) -> Option<usize> {
    if needle.is_empty() || needle.len() > hay.len() {
        return None;
    }
    (0..=hay.len() - needle.len()).find(|&i| hay[i..i + needle.len()] == *needle)
}

impl CardDef {
    /// core.py CardDef.has_innate_keyword を忠実移植 (条件付き/動的付与は innate でない)。
    /// ⚠ 日本語なので char 単位でスライス (Python の文字数スライスに一致させる)。
    pub fn has_innate_keyword(&self, keyword: &str) -> bool {
        if self.text.is_empty() {
            return false;
        }
        let brackets = [format!("【{keyword}】"), format!("[{keyword}]")];
        if !brackets.iter().any(|b| self.text.contains(b.as_str())) {
            return false;
        }
        let normalized = self.text.replace('\n', "。");
        for s in normalized.split('。') {
            let sc: Vec<char> = s.chars().collect();
            for bracket in &brackets {
                let bc: Vec<char> = bracket.chars().collect();
                let Some(bstart) = find_subslice(&sc, &bc) else { continue };
                let bend = bstart + bc.len();
                let after: String = sc[bend..(bend + 20).min(sc.len())].iter().collect();
                let before: String = sc[..bstart].iter().collect();
                if after.starts_with("を得")
                    || after.starts_with("を発動")
                    || after.starts_with("になる")
                    || after.starts_with("を持つ")
                    || after.starts_with("を持た")
                {
                    continue;
                }
                let after10: String = sc[bend..(bend + 10).min(sc.len())].iter().collect();
                if after10.contains("発動できない") {
                    continue;
                }
                if before.contains("場合") || before.contains('：') || before.contains(':') {
                    continue;
                }
                if before.ends_with('】') {
                    if let Some(lb) = before.rfind('【') {
                        let marker = &before[lb..];
                        if marker.contains("ドン") || marker.contains('×') || marker.contains("ターン1回") {
                            continue;
                        }
                    }
                }
                return true;
            }
        }
        false
    }

    /// core.py CardDef.is_rush = 【速攻】か【スピード】を innate 所持。
    pub fn is_rush(&self) -> bool {
        self.has_innate_keyword("スピード") || self.has_innate_keyword("速攻")
    }

    /// core.py CardDef.is_blocker = 【ブロッカー】を innate 所持。
    pub fn is_blocker(&self) -> bool {
        self.has_innate_keyword("ブロッカー")
    }
}

fn ser_card_id<S: serde::Serializer>(c: &CardDef, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&c.card_id)
}

fn ser_card_ids<S: serde::Serializer>(v: &[CardDef], s: S) -> Result<S::Ok, S::Error> {
    use serde::ser::SerializeSeq;
    let mut seq = s.serialize_seq(Some(v.len()))?;
    for c in v {
        seq.serialize_element(&c.card_id)?;
    }
    seq.end()
}

/// Option<CardDef> を card_id (or null) に畳む (Python canonical と一致)。
fn ser_opt_card_id<S: serde::Serializer>(c: &Option<CardDef>, s: S) -> Result<S::Ok, S::Error> {
    match c {
        Some(cd) => s.serialize_str(&cd.card_id),
        None => s.serialize_none(),
    }
}

/// 場のカード (core.py InPlay、 71 field。 instance_id は除外)。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct InPlay {
    #[serde(serialize_with = "ser_card_id")]
    pub card: CardDef,
    pub rested: bool,
    pub attached_dons: i32,
    pub summoning_sickness: bool,
    pub counters_used_this_battle: i32,
    // buff 群 (静的/ターン/バトル/次ターン)
    pub static_buff: i32,
    pub turn_buff: i32,
    pub battle_buff: i32,
    pub next_turn_buff: i32,
    // 動的付与キーワード/属性
    pub granted_keywords: BTreeSet<String>,
    pub granted_attributes: BTreeSet<String>,
    pub static_granted_keywords: BTreeSet<String>,
    pub granted_keywords_through_opp_turn: BTreeSet<String>,
    pub granted_keywords_through_opp_turn_applier_idx: i32,
    pub granted_keywords_through_opp_turn_applied_turn: i32,
    // アタック時 手札 N 捨て制約 (applier-tracking)
    pub attack_cost_discard_hand_n: i32,
    pub attack_cost_discard_hand_applier_idx: i32,
    pub attack_cost_discard_hand_applied_turn: i32,
    // バトル KO 耐性 群
    pub battle_ko_immune_static: bool,
    pub battle_ko_immune_until_turn_end: bool,
    pub battle_ko_immune_through_opp_turn: bool,
    pub battle_ko_immune_vs_leader: bool,
    pub battle_pump_vs_attribute: BTreeMap<String, i32>,
    // turn 限定フラグ 群
    pub blocker_disabled_until_turn_end: bool,
    pub ko_immune_until_turn_end: bool,
    pub cannot_attack_until_turn_end: bool,
    pub return_to_deck_bottom_at_turn_end: bool,
    pub played_from_trash: bool,
    pub trash_at_self_turn_end: bool,
    pub return_to_deck_bottom_at_battle_end: bool,
    // コスト修正
    pub cost_minus_until_turn_end: i32,
    pub cost_minus_through_opp_turn: i32,
    pub stay_rested_next_refresh: bool,
    // 静的 KO 耐性 群
    pub static_ko_immune: bool,
    pub static_ko_immune_from_source_power_le: i32,
    pub static_ko_immune_from_non_attribute: String,
    // base power/cost override 群 (Option = None なら CardDef 値)
    pub base_power_override: Option<i32>,
    pub turn_base_power_override: Option<i32>,
    pub next_turn_base_power_override: Option<i32>,
    pub next_opp_turn_end_base_power_override: Option<i32>,
    pub next_opp_turn_end_base_power_override_applier_idx: i32,
    pub next_opp_turn_end_base_power_override_applied_turn: i32,
    pub base_cost_override: Option<i32>,
    pub next_opp_turn_end_base_cost_override: Option<i32>,
    pub next_opp_turn_end_base_cost_override_applier_idx: i32,
    pub next_opp_turn_end_base_cost_override_applied_turn: i32,
    // 常在フラグ 群
    pub attack_taunt: bool,
    pub cannot_attack_static: bool,
    pub protect_from_opp_effect: bool,
    pub ko_immune_battle_attributes_in: BTreeSet<String>,
    pub ko_immune_battle_attributes_not_in: BTreeSet<String>,
    pub effect_disabled_through_opp_turn: bool,
    pub cannot_attack_through_opp_turn: bool,
    pub attacker_prevents_blocker_until_turn_end: bool,
    pub attacker_prevents_blocker_power_le: i32,
    pub cannot_attack_target_cost_le_until_turn_end: i32,
    pub ko_immune_through_opp_turn: bool,
    pub ko_per_turn_immune_remaining: i32,
    pub ko_per_turn_immune_max: i32,
    // 時限 buff 群 (applier-tracking)
    pub next_opp_turn_end_buff: i32,
    pub next_opp_turn_end_applier_idx: i32,
    pub next_opp_turn_end_applied_turn: i32,
    pub next_self_turn_end_buff: i32,
    pub next_self_turn_end_applier_idx: i32,
    pub next_self_turn_end_applied_turn: i32,
    pub cannot_be_rested_buff: bool,
    pub cannot_be_rested_applier_idx: i32,
    pub cannot_be_rested_applied_turn: i32,
    // ownership
    pub owner_idx: i32,
    pub is_owners_turn: bool,
}

impl InPlay {
    /// core.py InPlay.of: card から場のカードを新規生成。
    /// ⚠ Python dataclass の default が -1 の field (各 applier_idx / *_power_le / cost_le / owner_idx) を
    /// 明示設定 (Rust の Default 派生は i32→0 なので不一致になる)。 owner_idx/is_owners_turn は直後の
    /// update_ownership_flags が上書きするが Python 既定に合わせる。
    pub fn of(card: CardDef, sickness: bool) -> Self {
        InPlay {
            card,
            summoning_sickness: sickness,
            granted_keywords_through_opp_turn_applier_idx: -1,
            attack_cost_discard_hand_applier_idx: -1,
            static_ko_immune_from_source_power_le: -1,
            next_opp_turn_end_base_power_override_applier_idx: -1,
            next_opp_turn_end_base_cost_override_applier_idx: -1,
            attacker_prevents_blocker_power_le: -1,
            cannot_attack_target_cost_le_until_turn_end: -1,
            next_opp_turn_end_applier_idx: -1,
            next_self_turn_end_applier_idx: -1,
            cannot_be_rested_applier_idx: -1,
            owner_idx: -1,
            is_owners_turn: true,
            ..Default::default()
        }
    }

    /// core.py InPlay.base_power = override 優先順位 (turn > next_turn > next_opp_turn_end > static > card)。
    pub fn base_power(&self) -> i32 {
        if let Some(p) = self.turn_base_power_override {
            return p;
        }
        if let Some(p) = self.next_turn_base_power_override {
            return p;
        }
        if let Some(p) = self.next_opp_turn_end_base_power_override {
            return p;
        }
        self.base_power_override.unwrap_or(self.card.power)
    }

    /// core.py InPlay.power = base + DON+1000(所有者ターンのみ)+ 各 buff。
    pub fn power(&self) -> i32 {
        let don_buff = if self.is_owners_turn { 1000 * self.attached_dons } else { 0 };
        self.base_power()
            + don_buff
            + self.static_buff
            + self.turn_buff
            + self.battle_buff
            + self.next_turn_buff
            + self.next_opp_turn_end_buff
            + self.next_self_turn_end_buff
    }

    /// core.py InPlay.is_blocker_now = innate or 付与【ブロッカー】。
    pub fn is_blocker_now(&self) -> bool {
        self.card.is_blocker()
            || self.granted_keywords.contains("ブロッカー")
            || self.static_granted_keywords.contains("ブロッカー")
            || self.granted_keywords_through_opp_turn.contains("ブロッカー")
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum Phase {
    #[serde(rename = "REFRESH")]
    Refresh,
    #[serde(rename = "DRAW")]
    Draw,
    #[serde(rename = "DON")]
    Don,
    #[serde(rename = "MAIN")]
    Main,
    #[serde(rename = "END")]
    End,
}

/// プレイヤー状態 (core.py Player、 39 field)。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
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
    pub face_up_life_count: i32,
    pub known_hand_card_ids: Vec<String>,
    pub known_bottom_card_ids: Vec<String>,
    pub known_top_card_ids: Vec<String>,
    pub don_active: i32,
    pub don_rested: i32,
    pub don_remaining_in_deck: i32,
    pub play_cost_reduction: i32,
    // filter 付きコスト軽減 (opaque DSL payload = Value)
    pub play_cost_reductions_filtered: Vec<serde_json::Value>,
    pub play_cost_reductions_filtered_turn: Vec<serde_json::Value>,
    pub block_chara_play_until_turn_end: bool,
    pub cannot_attack_leader_until_turn_end: bool,
    pub block_chara_play_cost_ge_threshold: i32,
    pub opp_on_play_disabled_through_opp_turn: bool,
    pub block_self_draw_until_turn_end: bool,
    pub turn_battle_ko_save_discard: bool,
    pub life_lost_this_turn: bool,
    pub chara_ko_taken_this_turn: i32,
    pub deck_out_wins: bool,
    pub prevent_self_life_to_hand_until_turn_end: bool,
    pub hand_discarded_by_effect_this_turn: bool,
    pub delayed_at_opp_main_phase_start: Vec<serde_json::Value>,
    pub next_refresh_kept_rested_don: i32,
    // once_per_turn_used は key が instance_id 依存 = canonical 除外 (Python _EXCLUDE と一致)。
    // Rust は追跡しない (single-action の gating は legal_actions 側で担保)。
    #[serde(default, skip_serializing)]
    pub once_per_turn_used: BTreeSet<String>,
    pub cards_drawn_count: i32,
    pub cards_played_count: i32,
    pub max_event_cost_this_turn: i32,
    pub dons_used_count: i32,
    pub dons_unused_at_end_count: i32,
    pub did_mulligan: bool,
    pub hand_counter_boost: Option<serde_json::Value>,
}

/// ゲーム状態 (core.py GameState の**ルール状態**のみ)。 AI 評価/UI/デッキメタ/human 対話は
/// 差分対象外 (Python 側 _EXCLUDE と一致)。 last_* トリガー context は action 間では通常 None。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GameState {
    pub players: Vec<Player>,
    pub turn_player_idx: usize,
    pub turn_number: i32,
    pub phase: Phase,
    pub winner: Option<usize>,
    pub game_over: bool,
    pub pending_attack_redirect: Option<i32>,
    pub event_queue: Vec<serde_json::Value>,
    pub resolving: bool,
    pub extra_turn_pending: bool,
    // 直近トリガー context (action 間では通常 None)。 card ref は card_id に畳む (Python canonical と一致)
    pub last_discard_source_inplay: Option<InPlay>,
    pub last_discard_count: i32,
    pub last_returned_don_count: i32,
    pub last_peeked_opp_deck_top: Option<serde_json::Value>,
    #[serde(serialize_with = "ser_opt_card_id")]
    pub last_chara_ko_victim_card: Option<CardDef>,
    #[serde(serialize_with = "ser_opt_card_id")]
    pub last_opp_chara_played_card: Option<CardDef>,
    #[serde(serialize_with = "ser_opt_card_id")]
    pub last_self_chara_played_card: Option<CardDef>,
    // last_self_chara_played_iid は instance_id タグ = Rust 再現不可 → canonical から除外 (Python _EXCLUDE と一致)
    pub last_self_chara_played_from_trash: bool,
    pub last_trigger_kept_in_hand: bool,
}
