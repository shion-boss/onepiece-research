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

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Default)]
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

    /// core.py CardDef.is_rush_chara_only = 【速攻：キャラ】を innate 所持。
    pub fn is_rush_chara_only(&self) -> bool {
        self.has_innate_keyword("速攻：キャラ") || self.has_innate_keyword("速攻:キャラ")
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
    /// 「バトルでKOされる場合、 代わりに手札1枚を捨てる」 救済対象 (EB02-030、 core.py と同名)。
    /// ⚠ 効果発動時に場にいたキャラだけに付与 (cardqa_eb_02: 発動後登場は対象外)。
    pub battle_ko_save_discard_until_turn_end: bool,
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
    /// ⭐ その上書きが 「**元々の** パワーを◯◯にする」 効果由来か (公式 4-9-2-1)。
    /// 素の 「パワーが◯◯になる」 (OP06-009) は現在パワーだけを変え 「元々のパワーN以下」 に
    /// 影響しない。 core.py InPlay.*_is_original のミラー。
    #[serde(default)]
    pub base_power_override_is_original: bool,
    pub turn_base_power_override: Option<i32>,
    #[serde(default)]
    pub turn_base_power_override_is_original: bool,
    pub next_turn_base_power_override: Option<i32>,
    #[serde(default)]
    pub next_turn_base_power_override_is_original: bool,
    pub next_opp_turn_end_base_power_override: Option<i32>,
    #[serde(default)]
    pub next_opp_turn_end_base_power_override_is_original: bool,
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
    // 常在「相手の効果でレストにされない」 (OP12-021、 set_cannot_be_rested_static)。 recompute で再計算。
    #[serde(default)]
    pub static_cannot_be_rested: bool,
    // ownership
    pub owner_idx: i32,
    pub is_owners_turn: bool,
    // 起動メイン発動済フラグ (once_per_turn ゲート、 Python core.py InPlay._act_used のミラー)
    #[serde(rename = "_act_used", default)]
    pub act_used: bool,
    // 【アタック時】/【相手のアタック時】once_per_turn を消費した effect idx 群 (ソート保持)。
    // Python core.py InPlay.attack_once_used のミラー。 refresh で clear。
    #[serde(default)]
    pub attack_once_used: Vec<i64>,
    // field-when (on_self_life_to_hand 等) once_per_turn の canonical mirror ("{when}:{idx}" ソート保持)。
    // Python core.py InPlay.event_once_used のミラー。 refresh で clear。
    #[serde(default)]
    pub event_once_used: Vec<String>,
    /// 効果解決中に「この InPlay が発動元」であることを一時的に印付ける一意トークン (0 = 無印)。
    /// cost / 各 primitive が盤面を動かした後に発動元の位置 index を取り直すために使う =
    /// Python の self_inplay (object 参照) の代替。 canonical 化からは除外 (serde skip) するので
    /// 差分照合には現れない。 入れ子は別トークンになるので互いを消さない。
    /// ⚠ 入れ子 (do 内の optional_cost_then 等) で同じ InPlay に複数タグが乗るのでスタックにする。
    /// 単一値だと内側の tag_src が外側のトークンを上書きし、 外側が発動元を見失う。
    #[serde(skip)]
    pub rust_src_tag: Vec<u64>,
}

impl InPlay {
    /// 【アタック時】/【相手のアタック時】once_per_turn 効果 idx を消費済にする (ソート保持)。
    /// Python core.py InPlay.mark_attack_once_used のミラー。
    pub fn mark_attack_once(&mut self, idx: i64) {
        if !self.attack_once_used.contains(&idx) {
            self.attack_once_used.push(idx);
            self.attack_once_used.sort_unstable();
        }
    }

    /// field-when once を消費済に ("{when}:{idx}"、 ソート保持)。 Python InPlay.mark_event_once のミラー。
    pub fn mark_event_once(&mut self, when: &str, idx: i64) {
        let mk = format!("{when}:{idx}");
        if !self.event_once_used.contains(&mk) {
            self.event_once_used.push(mk);
            self.event_once_used.sort_unstable();
        }
    }

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

    /// core.py InPlay.truly_original_power = 「元々のパワー」。 原則は印刷値だが、
    /// **「元々のパワーを◯◯にする」 効果** (公式 4-9-2-1) で書き換えられていればその値。
    /// ⚠ 素の 「パワーが◯◯になる」 (= `original` フラグ false) は現在パワーだけを変える。
    /// 「元々のパワー」。 ⚠ **複数の 「元々のパワーを◯◯にする」 が適用されている場合は最も高い値**
    /// (公式 4-9-2-1、 cardqa_st_34 / ST34-004 リンリン)。 slot 優先順位で 1 つ選ぶと、 後から掛けた
    /// 低い値が高い値を潰す (2026-08-11 に Python と同時に是正)。
    pub fn truly_original_power(&self) -> i32 {
        let mut best: Option<i32> = None;
        for (v, is_orig) in [
            (self.turn_base_power_override, self.turn_base_power_override_is_original),
            (self.next_turn_base_power_override, self.next_turn_base_power_override_is_original),
            (
                self.next_opp_turn_end_base_power_override,
                self.next_opp_turn_end_base_power_override_is_original,
            ),
            (self.base_power_override, self.base_power_override_is_original),
        ] {
            if is_orig {
                if let Some(p) = v {
                    best = Some(best.map_or(p, |b: i32| b.max(p)));
                }
            }
        }
        best.unwrap_or(self.card.power)
    }

    /// core.py InPlay.power = base + DON+1000(所有者ターンのみ)+ 各 buff。
    /// core.py InPlay.base_cost: override (next_opp_turn_end > base_cost_override > card.cost) - cost_minus。
    pub fn base_cost(&self) -> i32 {
        let raw = self
            .next_opp_turn_end_base_cost_override
            .or(self.base_cost_override)
            .unwrap_or(self.card.cost);
        (raw - self.cost_minus_until_turn_end - self.cost_minus_through_opp_turn).max(0)
    }

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
        self.has_kw_now("ブロッカー", self.card.is_blocker())
    }

    fn has_kw_now(&self, kw: &str, innate: bool) -> bool {
        innate
            || self.granted_keywords.contains(kw)
            || self.static_granted_keywords.contains(kw)
            || self.granted_keywords_through_opp_turn.contains(kw)
    }

    pub fn is_double_attack_now(&self) -> bool {
        self.has_kw_now("ダブルアタック", self.card.has_innate_keyword("ダブルアタック"))
    }

    pub fn is_banish_now(&self) -> bool {
        self.has_kw_now("バニッシュ", self.card.has_innate_keyword("バニッシュ"))
    }

    /// core.py InPlay.has_no_block_now = innate【ブロック不可】or 付与「ブロック不可」。
    /// True の attacker はブロックされない (AttackLeader のブロック判定で skip)。
    pub fn has_no_block_now(&self) -> bool {
        self.has_kw_now("ブロック不可", self.card.has_innate_keyword("ブロック不可"))
    }

    /// core.py InPlay.is_rush_now = 【速攻】/【スピード】を innate or 付与所持。
    pub fn is_rush_now(&self) -> bool {
        self.has_kw_now("速攻", self.card.is_rush())
    }

    /// core.py InPlay.is_rush_chara_only_now = 【速攻：キャラ】を innate or 付与所持 (「：」「:」両表記)。
    pub fn is_rush_chara_only_now(&self) -> bool {
        if self.card.is_rush_chara_only() {
            return true;
        }
        ["速攻：キャラ", "速攻:キャラ"].iter().any(|kw| {
            self.granted_keywords.contains(*kw)
                || self.static_granted_keywords.contains(*kw)
                || self.granted_keywords_through_opp_turn.contains(*kw)
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub enum Phase {
    #[default]
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
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
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
    /// ⭐ ライフ **1 枚ごと** の表向き/裏向き (= life と同じ長さ・同じ並び)。
    /// Python `Player.life_face_up` の対 (2026-08-11 に 「枚数だけ」 モデルから移行)。
    /// ⚠ 「表向きは上から N 枚」 の近似は使えない: ST13-012 マキノ 「ライフすべてを見て好きな
    ///   順番で置く」 が全体を並べ替えるため。
    #[serde(default)]
    pub life_face_up: Vec<bool>,
    /// 「ルール上、 自分の表向きのライフは手札に加わる代わりにデッキの下に置かれる」
    /// (ST13-003 モンキー・D・ルフィ(L))。 静的効果なので recompute_static で毎回再計算する。
    #[serde(default)]
    pub face_up_life_to_deck_bottom: bool,
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
    /// 「手札からカードをプレイできない」(OP13-028 シャンクス)。 通常プレイ (キャラ/イベント/ステージ)
    /// のみ禁止し、 別の効果による effect summon は禁止しない (cardqa_op_13, db0c0c0d2ab9)。
    #[serde(default)]
    pub block_hand_play_until_turn_end: bool,
    pub cannot_attack_leader_until_turn_end: bool,
    pub block_chara_play_cost_ge_threshold: i32,
    pub opp_on_play_disabled_through_opp_turn: bool,
    pub block_self_draw_until_turn_end: bool,
    /// 「自分は、 このターン中、 キャラの効果でドン‼をアクティブにできない」
    /// (EB04-016 トリ / OP10-030 スモーカー)。 公式はこの自己ロックで 【ターン1回】 の
    /// 無い起動メインの無限ループを防いでいる (core.py と同名 field)。
    pub block_chara_effect_untap_don_until_turn_end: bool,
    pub life_lost_this_turn: bool,
    /// 「このターン中、 このリーダーが **相手のキャラと** バトルしている」 (cardqa_op_12 / OP12-020)。
    /// core.py Player.leader_battled_opp_chara_this_turn のミラー (canonical = digest 対象)。
    #[serde(default)]
    pub leader_battled_opp_chara_this_turn: bool,
    pub chara_ko_taken_this_turn: i32,
    pub deck_out_wins: bool,
    /// 公式 (OP15-022 ブルック リーダー): 「ルール上、 自分はデッキが0枚でも敗北せず、
    /// デッキが0枚になったターン終了時に敗北する」 (core.py Player.deck_out_defer のミラー)。
    #[serde(default)]
    pub deck_out_defer: bool,
    /// 「デッキが0枚に **なった**」 事実を そのターン中 記憶する (core.py Player.deck_hit_zero_this_turn)。
    /// 公式 (cardqa_op_15): デッキ0のターンに補充しても / リーダー効果を無効にされても
    /// そのターン終了時に敗北する = 遅延敗白の義務は 0 枚到達で確定する。
    #[serde(default)]
    pub deck_hit_zero_this_turn: bool,
    pub prevent_self_life_to_hand_until_turn_end: bool,
    pub hand_discarded_by_effect_this_turn: bool,
    pub delayed_at_opp_main_phase_start: Vec<serde_json::Value>,
    // このターン終了時に発動する予約効果 (core.py Player.scheduled_at_self_turn_end のミラー)。
    #[serde(default)]
    pub scheduled_at_self_turn_end: Vec<serde_json::Value>,
    // replace_ko/replace_leave の once_per_turn (card-id-keyed) の canonical mirror (core.py 同名)。
    #[serde(default)]
    pub replace_opt_used_cards: Vec<String>,
    // 明示キー (文字列) once_per_turn の canonical mirror (core.py 同名、 key 形式 "key:<opt>")。
    // instance_id 非依存なので digest 可。 複数 when が 1 キーを共有する効果 (OP13-002 等) の追跡用。
    #[serde(default)]
    pub once_shared_used: Vec<String>,
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

impl Player {
    /// 表向きのライフ枚数 (= `life_face_up` の true の数)。 Python の property と同則。
    /// ⚠ **書き込みは `life_face_up` を直接操作する** (枚数だけを持つ旧モデルは 2026-08-11 に廃止)。
    pub fn face_up_life_count(&self) -> i32 {
        self.life_face_up.iter().filter(|x| **x).count() as i32
    }

    /// `life_face_up` の長さを `life` に揃える (setup / まるごと差し替えの後に呼ぶ)。
    pub fn life_sync_flags(&mut self) {
        let n = self.life.len();
        self.life_face_up.resize(n, false);
    }
}


/// ゲーム状態 (core.py GameState の**ルール状態**のみ)。 AI 評価/UI/デッキメタ/human 対話は
/// 差分対象外 (Python 側 _EXCLUDE と一致)。 last_* トリガー context は action 間では通常 None。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct GameState {
    pub players: Vec<Player>,
    pub turn_player_idx: usize,
    pub turn_number: i32,
    pub phase: Phase,
    pub winner: Option<usize>,
    pub game_over: bool,
    /// ⚠ Python は instance_id、 Rust は位置 index を入れる = 表現が原理的に一致しない。
    /// action 内 transient (消費即クリア) なので digest 対象外 (state_snapshot._EXCLUDE)。
    #[serde(skip)]
    pub pending_attack_redirect: Option<i32>,
    pub event_queue: Vec<serde_json::Value>,
    pub resolving: bool,
    pub extra_turn_pending: bool,
    // 直近トリガー context (action 間では通常 None)。 card ref は card_id に畳む (Python canonical と一致)
    pub last_discard_source_inplay: Option<InPlay>,
    pub last_discard_count: i32,
    /// 直近の trash_self_hand_random が **実際に捨てた枚数** (Python `last_self_hand_discard_amount`)。
    /// 公式 「捨てた枚数と同じ枚数を…」 (OP09-059) が読む。 last_discard_count (= イベント context、
    /// 発火後 0 に戻す) と違い、 同じ do 配列の後続 primitive が読めるようクリアしない = digest 対象。
    pub last_self_hand_discard_amount: i32,
    pub last_returned_don_count: i32,
    pub last_peeked_opp_deck_top: Option<serde_json::Value>,
    #[serde(serialize_with = "ser_opt_card_id")]
    pub last_chara_ko_victim_card: Option<CardDef>,
    /// KO された **時点** の 「元々のパワー」 (効果で書き換わっている場合がある、 公式 4-9-2-1)。
    /// Python `state._on_ko_victim_truly_original_power` の対。 CardDef の印刷値では判定できない
    /// (OP14-053 ビスタ が リーダーの元々のパワーを写して 6000 の状態で KO されるケース)。
    /// transient (= victim 文脈と同じ寿命) なので digest 対象外。
    #[serde(skip)]
    pub rust_ko_victim_truly_original_power: Option<i32>,
    #[serde(serialize_with = "ser_opt_card_id")]
    pub last_opp_chara_played_card: Option<CardDef>,
    #[serde(serialize_with = "ser_opt_card_id")]
    pub last_self_chara_played_card: Option<CardDef>,
    // last_self_chara_played_iid は instance_id タグ = Rust 再現不可 → canonical から除外 (Python _EXCLUDE と一致)
    pub last_self_chara_played_from_trash: bool,
    /// 公式 (cardqa_op_12、 OP12-081 コアラ): 「**キャラの効果で**キャラを登場させた時」 =
    /// **場にあるキャラ** の効果による登場のみ (トリガー/イベント/リーダーは該当しない)。
    #[serde(skip)]
    pub last_chara_played_by_field_chara: bool,
    pub last_trigger_kept_in_hand: bool,
    // current_source_card_id: 効果処理中だけ立つ transient (effects.py:297 で set / 504 で restore)。
    // action 境界では常に None (= Python setattr で digest 不参照) → skip。 play_self 等 self_inplay=None の
    // source-gone 効果が「発動元カード」を特定するのに使う。
    #[serde(skip)]
    pub current_source_card_id: Option<String>,
    /// いま実行中の効果の発動元が **場のキャラ** か (Python の state._effect_source_ip 相当)。
    /// 「キャラの効果でキャラを登場させた時」 (cardqa_op_12 / OP12-081) の判定に使う。
    #[serde(skip)]
    pub rust_play_source_is_field_chara: bool,
    /// 予約効果 (schedule_at_self_turn_end) の flush 中だけ立つ 「発動元 category」。
    /// effects.py の state._scheduled_src_category ミラー (cardqa_eb_02 / OP10-030)。
    /// action 境界を跨がない transient なので digest 対象外 (= serde skip)。
    #[serde(skip)]
    pub rust_scheduled_src_category: Option<String>,
    // アタック解決中だけ立つ transient。 opp_attack 系の条件 (opp_attacker_attribute) が参照する。
    // Python は current_attacker_iid から InPlay を引くが、 Rust は iid が無いので属性を直接持つ。
    #[serde(skip)]
    pub current_attacker_attribute: Option<String>,
    /// 現在アタック中のカードを指す一時トークン (effects.py の `current_attacker_iid` 相当)。
    /// target spec "opponent_attacker" の解決に使う。 action 境界で None に戻る。
    #[serde(skip)]
    pub current_attacker_tok: Option<u64>,
    // 手札破棄を起こした効果の発動元カードの特徴 (transient)。 Python の
    // state.last_discard_source_inplay 相当で、 条件 actor_source_feature_contains が参照する。
    #[serde(skip)]
    pub current_discard_source_features: Option<Vec<String>>,
    /// 【トリガー】/イベント (= InPlay を持たない発動元) の特徴。 effects.py の
    /// state.current_source_card ミラー (cardqa_op_12 / OP12-057 → OP12-040 クザン)。
    /// fire_life_trigger / イベント解決中だけ立つ transient → digest 対象外。
    #[serde(skip)]
    pub current_source_card_features: Option<Vec<String>>,
    // 直近に効果で捨てた手札の枚数 (transient、 Python の state.last_discard_count 相当)。
    // draw_per_self_hand_discarded (OP12-040 クザン「捨てた枚数分ドロー」) が読む。
    #[serde(skip)]
    pub current_discard_count: i32,
    // ===== trigger キュー (Python effects.py:event_queue / resolving の移植、 2026-08-01) =====
    // Python は【登場時】等を enqueue し、 resolving=false の時だけ drain する。 つまり
    // **トリガー解決の途中で登場したキャラの on_play は後回し** になる (zone 操作が終わってから発火)。
    // Rust が inline 発火していたため、 zone を並べ替える on_play で順序がズレて bail していた。
    // ⚠ action 境界では必ず空になるので digest には現れない (= serde skip で Python と一致)。
    // ⚠ canonical の event_queue/resolving (Python full_dump 由来、 上記) とは別に、 Rust 内部の
    //   解決キューを持つ (型が違う & action 境界では両方空なので digest 不変)。
    #[serde(skip)]
    pub rust_event_queue: Vec<crate::effects::PendingTrigger>,
    #[serde(skip)]
    pub rust_resolving: bool,
    /// 直前にバトルした相手キャラ (player_idx, char_idx)。 effects.py の動的属性
    /// `last_battled_opp_iid` 相当。 条件 opp_just_battled_* / target spec opp_just_battled 用。
    #[serde(skip)]
    pub last_battled_opp: Option<(usize, usize)>,
    /// 直前に power_pump した対象 (player_idx, Slot 相当の char/leader 位置)。 effects.py:3616
    /// `last_pumped_iid` の代替。 target spec self_just_buffed の解決に使う。
    /// -1 = leader、 0.. = characters index。
    #[serde(skip)]
    pub last_pumped: Option<(usize, i32)>,
    /// 効果解決中に発動元が場を離れた時の直前スナップショット。 Python は self_inplay を
    /// object 参照で保持し場外でも読めるので、 その代替 (アタッカーの power/cost 参照等)。
    #[serde(skip)]
    pub rust_detached_src: Option<InPlay>,
    /// 直前の return_to_hand が実際に 1 枚以上バウンスしたか (effects.py:3970
    /// `last_return_to_hand_success`)。 OP13-119 の「そうした場合」 gate に使う。
    #[serde(skip)]
    pub last_return_to_hand_success: bool,
    /// **同時離脱バッチ** (effects.py:`_LeaveBatch`) のスナップショット。
    /// 公式は 「1 つの効果で複数のキャラが同時に場を離れる」 を 1 事象として扱うので、
    /// ① 置換 holder は **バッチ開始時の盤面** から決める (順序非依存、 cardqa_op_10 / OP10-032 たしぎ)
    /// ② 同じ holder の置換コストは **1 回だけ** (cardqa_op_15 / OP15-090 ペローナ)
    /// (owner_idx, holder を追う一意トークン, card_id)。 transient なので digest 対象外。
    #[serde(skip)]
    pub rust_leave_batch_holders: Option<Vec<(usize, Option<u64>, String)>>,
    /// このバッチで既に置換コストを払った (holder トークン, when)。
    #[serde(skip)]
    pub rust_leave_batch_paid: Vec<(u64, String)>,
    /// このバッチで 「代替しない」 と確定した (holder トークン, when)。
    /// victim に依らない条件 (トラッシュ枚数等) は **バッチ開始時の状態** で 1 度だけ判定する
    /// (cardqa_op_11 / OP11-001 コビー: 先に離れた victim がトラッシュを増やした状態を
    ///  後の victim の判定に使えない)。
    #[serde(skip)]
    pub rust_leave_batch_declined: Vec<(u64, String)>,
    /// 「自分の(特徴X を持つ)キャラが場を離れた時」 の victim 判定用スナップショット。
    /// 効果の **最外側** で自陣キャラの顔ぶれを控え、 トリガー発火時に差分を取る
    /// (= 離脱経路が 16 以上あるので個別に victim を引き回すと必ず取りこぼす)。
    #[serde(skip)]
    pub rust_leave_victim_snapshot: Option<Vec<CardDef>>,
    /// 直近の leave-by-self イベントで場を離れた victim (条件 leave_victim_feature_in が読む)。
    #[serde(skip)]
    pub rust_leave_by_self_victims: Vec<CardDef>,
    /// 「自分の効果で場を離れ、 行き先が **公開領域** (トラッシュ / 表向きライフ)」 だった
    /// キャラの台帳 (effects.py の `state._departed_to_public_zone` ミラー、 (owner_idx, card_id))。
    /// 公式 cardqa_op_08 (OP08-046 シャクヤク): 離脱した **本人** も
    /// on_self_chara_leave_by_self_effect を発動できる (行き先が公開領域の時だけ)。
    /// 直後の発火で consume + clear する transient なので digest 対象外。
    #[serde(skip)]
    pub rust_departed_to_public: Vec<(usize, String)>,
    /// 直前の KO が「相手の効果由来」か (effects.py の動的属性 `last_ko_by_opp_effect` 相当)。
    /// 条件 by_opp_effect / by_battle の判定に使う。 fire_on_ko の引数から設定する。
    #[serde(skip)]
    pub last_ko_by_opp_effect: bool,
    /// KO 直前の victim が 「効果無効」 状態だったか。 公式 Q&A (cardqa_op_09/op_10):
    /// 「効果を無効にされたキャラがKOされた場合、 そのキャラの持つ【KO時】効果は発動できますか？」
    /// → 「いいえ」。 on_ko は victim が既に場外なので、 除去時に記録して fire_on_ko が読む。
    #[serde(skip)]
    pub ko_victim_effect_negated: bool,
    /// 直前に negate_effect した相手のリーダー or キャラ (player_idx, Slot)。 effects.py:7666
    /// `state.last_negated_iid` の代替。 opp_just_negated_cost_le_N (OP09-098) と
    /// opp_just_negated_any (OP09-097 闇水、 リーダーも対象) の解決に使う。
    #[serde(skip)]
    pub last_negated: Option<(usize, crate::effects::Slot)>,
    /// 直前の `rest` が **選んだ** カード (player_idx, Slot)。 effects.py の
    /// `state.last_rest_selected_iid` の代替。 just_rest_selected (ST24-004 ロー&ベポ
    /// 「相手キャラ1枚までをレストにし、 **そのキャラは** 次のリフレッシュでアクティブに
    /// ならない」) の解決に使う。 ⚠ Python は instance_id、 Rust は位置 index (last_negated
    /// と同じ制約) — 選択と参照の間に場が動くと表現が食い違いうる。
    #[serde(skip)]
    pub last_rest_selected: Option<(usize, crate::effects::Slot)>,
    /// 直前に cost の discard_hand_with_filter で捨てたカード名 (effects.py:8877
    /// `state.last_discarded_names`)。 filter の name_in_last_discarded 解決に使う (EB02-039)。
    #[serde(skip)]
    pub last_discarded_names: Vec<String>,
    // rng: full_dump の _rng_state (MT getstate keys 625) を入力として受け、 rng 依存 effect で消費。
    // digest には含めない (Python state_digest は rng 非依存) = skip_serializing。 live は lazy init。
    #[serde(rename = "_rng_state", default, skip_serializing)]
    pub rng_state: Vec<u64>,
    #[serde(skip)]
    pub rng: Option<crate::rng::PyRandom>,
}

impl GameState {
    /// rng_state (625 keys) から復元した live MT が使えるか。
    pub fn has_rng(&self) -> bool {
        self.rng.is_some() || self.rng_state.len() == 625
    }
    /// rng 依存 effect 用の live MT (初回に rng_state から復元)。 has_rng() が true の時のみ呼ぶ。
    pub fn rng_mut(&mut self) -> &mut crate::rng::PyRandom {
        if self.rng.is_none() {
            self.rng = crate::rng::PyRandom::from_state(&self.rng_state);
        }
        self.rng.as_mut().expect("rng_mut: rng_state 未設定 (has_rng で確認せよ)")
    }
}
