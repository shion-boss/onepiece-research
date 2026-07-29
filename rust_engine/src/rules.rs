//! ルールエンジン (Rust)。 engine/game.py apply_action + phase 機械のミラー (Phase R2)。
//!
//! action は canonical エンコード (instance_id でなく zone 位置で対象参照 = 状態と同じ iid 非依存規約)。
//! ⚠ 効果トリガー (trigger_*) と evaluate_static_effects は R3 (effects) で移植。 現状は効果が絡まない
//! action / vanilla 盤面でのみ Python と一致する (差分テストがその境界を明示)。 update_ownership_flags は
//! 効果非依存なので移植済 (DON+1000 ゲート)。

use crate::state::{CardDef, GameState, InPlay, Phase, Player};
use serde_json::Value;

fn geti(a: &Value, k: &str, default: i64) -> i64 {
    a.get(k).and_then(|v| v.as_i64()).unwrap_or(default)
}

/// player の leader + characters + stages を可変イテレート。
fn each_inplay_mut(p: &mut Player) -> impl Iterator<Item = &mut InPlay> {
    std::iter::once(&mut p.leader)
        .chain(p.characters.iter_mut())
        .chain(p.stages.iter_mut())
}

/// game.py:_recompute_static = ownership 更新 + 静的効果 (evaluate_static_effects) 再評価。
/// apply_action 末尾 + advance_phase 末尾 で呼ぶ (Python と同じ位置)。
pub fn recompute_static(state: &mut GameState) {
    update_ownership_flags(state);
    crate::effects::evaluate_static_effects(state);
}

/// game.py:_update_ownership_flags = 各 InPlay の owner_idx/is_owners_turn を再計算 (DON+1000 ゲート)。
pub fn update_ownership_flags(state: &mut GameState) {
    let tp = state.turn_player_idx;
    for me_idx in 0..state.players.len() {
        let is_my = me_idx == tp;
        for ip in each_inplay_mut(&mut state.players[me_idx]) {
            ip.owner_idx = me_idx as i32;
            ip.is_owners_turn = is_my;
        }
    }
}

fn declare_winner(state: &mut GameState, idx: usize) {
    if state.winner.is_none() {
        state.winner = Some(idx);
        state.game_over = true;
    }
}

/// game.py:_reset_battle_buffs = バトル終了時に全 InPlay の battle_buff (このバトル中効果) をクリア。
fn reset_battle_buffs(state: &mut GameState) {
    for p in state.players.iter_mut() {
        for ip in each_inplay_mut(p) {
            ip.battle_buff = 0;
        }
    }
}

// ============================ 戦闘 (Attack) 用ヘルパー ============================

/// player の全 InPlay (leader+chara+stage) のいずれかが指定 when 効果を持つか。 trigger cascade 判定用。
fn board_has_when(p: &Player, when: &str) -> bool {
    std::iter::once(&p.leader)
        .chain(p.characters.iter())
        .chain(p.stages.iter())
        .any(|ip| crate::effects::card_has_when(&ip.card.card_id, when))
}

/// game.py:_battle_attr_bonus = combatant が「属性X とバトル時+N」を持ち opponent が属性X の時 +N。
fn battle_attr_bonus(combatant: &InPlay, opponent: &InPlay) -> i32 {
    let attr = &opponent.card.attribute;
    if attr.is_empty() {
        return 0;
    }
    combatant.battle_pump_vs_attribute.get(attr).copied().unwrap_or(0)
}

/// game.py:_battle_ko_immune_by_attribute = defender が attacker の属性でバトル KO 不可か。
fn battle_ko_immune_by_attribute(defender: &InPlay, attacker: &InPlay) -> bool {
    if defender.battle_ko_immune_static
        || defender.battle_ko_immune_until_turn_end
        || defender.battle_ko_immune_through_opp_turn
    {
        return true;
    }
    let atk_attr = attacker.card.attribute.clone();
    let mut atk_attrs = attacker.granted_attributes.clone();
    if !atk_attr.is_empty() {
        atk_attrs.insert(atk_attr.clone());
    }
    if defender
        .ko_immune_battle_attributes_in
        .iter()
        .any(|a| atk_attrs.contains(a))
    {
        return true;
    }
    // 「属性 X を持たないカードとのバトルで KO されない」: attacker が not_in に含まれない → KO 不可
    if !defender.ko_immune_battle_attributes_not_in.is_empty()
        && !defender.ko_immune_battle_attributes_not_in.contains(&atk_attr)
    {
        return true;
    }
    false
}

/// game.py:_spend_counters = 手札 counter 札を trash し合計 counter 値を返す (hand_counter_boost 考慮)。
fn spend_counters(p: &mut Player, idxs: &[i64]) -> i32 {
    if idxs.is_empty() {
        return 0;
    }
    let mut order: Vec<usize> = idxs.iter().filter(|&&i| i >= 0).map(|&i| i as usize).collect();
    order.sort_unstable();
    order.dedup();
    order.reverse(); // 降順で pop = idx 不変
    let boost = p.hand_counter_boost.clone();
    let mut total = 0;
    for i in order {
        if i < p.hand.len() {
            let card = p.hand.remove(i);
            let mut base = card.counter;
            if let Some(b) = &boost {
                let cat = match card.category {
                    crate::state::Category::Leader => "LEADER",
                    crate::state::Category::Character => "CHARACTER",
                    crate::state::Category::Event => "EVENT",
                    crate::state::Category::Stage => "STAGE",
                };
                let bcat = b.get("category").and_then(|v| v.as_str()).unwrap_or(cat);
                let bpow = b.get("power_eq").and_then(|v| v.as_i64()).unwrap_or(card.power as i64) as i32;
                if cat == bcat && card.power == bpow {
                    base += b.get("amount").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
                }
            }
            total += base;
            p.trash.push(card);
        }
    }
    total
}

/// バトル KO 実行: victim キャラを trash へ、 付与ドン→レスト、 chara_ko_taken_this_turn++。
/// (trigger cascade は呼出側で bail 済 = last_chara_ko_victim_card は cascade 完了後 None に戻るので触らない)
fn battle_ko_character(state: &mut GameState, owner: usize, idx: usize) {
    if idx >= state.players[owner].characters.len() {
        return;
    }
    let removed = state.players[owner].characters.remove(idx);
    let don = removed.attached_dons;
    state.players[owner].trash.push(removed.card);
    state.players[owner].don_rested += don;
    state.players[owner].chara_ko_taken_this_turn += 1;
}

/// バトル KO + trigger cascade (game.py:1713/1974)。 KO 実行後に board trigger を発火:
///  - on_opp_chara_ko (攻撃側 board) / on_self_chara_ko (victim 側 board) = fire_field_when で再現。
///  - victim 自身の on_ko は source が trash (self_inplay=None) で発火が delicate → 該当時 bail。
///  - victim 側 replace_ko/replace_leave (置換効果) → bail。
///  - fire_self_battle_ko=true (AttackLeader blocker 経路のみ) で attacker on_self_battle_ko → bail。
/// last_chara_ko_victim_card は cascade 完了後 None (Python) = Rust は触らず None のまま = 一致。
/// victim 参照条件 (victim_*) は eval_condition 未対応で None → fire_field_when が bail = 安全。
fn do_battle_ko(
    state: &mut GameState,
    victim_owner: usize,
    victim_idx: usize,
    attacker_owner: usize,
    attacker_cid: &str,
    fire_self_battle_ko: bool,
) -> Result<(), String> {
    let vcid = state.players[victim_owner].characters[victim_idx].card.card_id.clone();
    if crate::effects::card_has_when(&vcid, "on_ko")
        || board_has_when(&state.players[victim_owner], "replace_ko")
        || board_has_when(&state.players[victim_owner], "replace_leave")
    {
        return Err("KO cascade (on_ko/replace) 未対応".into());
    }
    if fire_self_battle_ko && crate::effects::card_has_when(attacker_cid, "on_self_battle_ko") {
        return Err("on_self_battle_ko 未対応".into());
    }
    battle_ko_character(state, victim_owner, victim_idx);
    // trigger_on_opp_chara_ko (攻撃側) → trigger_on_self_chara_ko (victim 側) の順 (game.py 準拠)
    crate::effects::fire_field_when(state, attacker_owner, "on_opp_chara_ko")?;
    crate::effects::fire_field_when(state, victim_owner, "on_self_chara_ko")?;
    Ok(())
}

/// game.py:_reset_turn_buff = ターン終了時のバフ/フラグクリア (applier-tracking 含む)。
pub fn reset_turn_buff(state: &mut GameState) {
    let tp = state.turn_player_idx;
    let turn_number = state.turn_number;
    for p in state.players.iter_mut() {
        for ip in std::iter::once(&mut p.leader)
            .chain(p.characters.iter_mut())
            .chain(p.stages.iter_mut())
        {
            ip.turn_buff = 0;
            ip.granted_keywords.clear();
            ip.granted_attributes.clear();
            ip.ko_immune_until_turn_end = false;
            ip.battle_ko_immune_until_turn_end = false;
            ip.blocker_disabled_until_turn_end = false;
            ip.cannot_attack_until_turn_end = false;
            ip.cost_minus_until_turn_end = 0;
            ip.attacker_prevents_blocker_until_turn_end = false;
            ip.attacker_prevents_blocker_power_le = -1;
            ip.cannot_attack_target_cost_le_until_turn_end = -1;
            ip.turn_base_power_override = None;
        }
        p.play_cost_reduction = 0;
        p.block_chara_play_until_turn_end = false;
        p.opp_on_play_disabled_through_opp_turn = false;
        p.block_self_draw_until_turn_end = false;
        p.cannot_attack_leader_until_turn_end = false;
        p.turn_battle_ko_save_discard = false;
        p.life_lost_this_turn = false;
        p.chara_ko_taken_this_turn = 0;
        p.block_chara_play_cost_ge_threshold = -1;
        p.play_cost_reductions_filtered_turn = vec![];
        p.prevent_self_life_to_hand_until_turn_end = false;
        p.hand_discarded_by_effect_this_turn = false;
        p.max_event_cost_this_turn = 0;
    }
    // me_turn のみ: through_opp_turn 系をクリア
    for ip in each_inplay_mut(&mut state.players[tp]) {
        ip.effect_disabled_through_opp_turn = false;
        ip.cannot_attack_through_opp_turn = false;
        ip.ko_immune_through_opp_turn = false;
        ip.battle_ko_immune_through_opp_turn = false;
        ip.cost_minus_through_opp_turn = 0;
    }
    // applier-tracking timed buffs: applied_turn < turn_number かつ ended_idx 条件で消える
    let ended = tp as i32;
    for p in state.players.iter_mut() {
        for ip in std::iter::once(&mut p.leader)
            .chain(p.characters.iter_mut())
            .chain(p.stages.iter_mut())
        {
            if (ip.next_opp_turn_end_buff != 0 || ip.next_opp_turn_end_applier_idx >= 0)
                && ip.next_opp_turn_end_applier_idx >= 0
                && ip.next_opp_turn_end_applied_turn < turn_number
                && ended != ip.next_opp_turn_end_applier_idx
            {
                ip.next_opp_turn_end_buff = 0;
                ip.next_opp_turn_end_applier_idx = -1;
                ip.next_opp_turn_end_applied_turn = 0;
            }
            if (ip.next_self_turn_end_buff != 0 || ip.next_self_turn_end_applier_idx >= 0)
                && ip.next_self_turn_end_applier_idx >= 0
                && ip.next_self_turn_end_applied_turn < turn_number
                && ended == ip.next_self_turn_end_applier_idx
            {
                ip.next_self_turn_end_buff = 0;
                ip.next_self_turn_end_applier_idx = -1;
                ip.next_self_turn_end_applied_turn = 0;
            }
            if ip.cannot_be_rested_buff
                && ip.cannot_be_rested_applier_idx >= 0
                && ip.cannot_be_rested_applied_turn < turn_number
                && ended != ip.cannot_be_rested_applier_idx
            {
                ip.cannot_be_rested_buff = false;
                ip.cannot_be_rested_applier_idx = -1;
                ip.cannot_be_rested_applied_turn = 0;
            }
            if ip.next_opp_turn_end_base_power_override.is_some()
                && ip.next_opp_turn_end_base_power_override_applier_idx >= 0
                && ip.next_opp_turn_end_base_power_override_applied_turn < turn_number
                && ended != ip.next_opp_turn_end_base_power_override_applier_idx
            {
                ip.next_opp_turn_end_base_power_override = None;
                ip.next_opp_turn_end_base_power_override_applier_idx = -1;
                ip.next_opp_turn_end_base_power_override_applied_turn = 0;
            }
            if ip.next_opp_turn_end_base_cost_override.is_some()
                && ip.next_opp_turn_end_base_cost_override_applier_idx >= 0
                && ip.next_opp_turn_end_base_cost_override_applied_turn < turn_number
                && ended != ip.next_opp_turn_end_base_cost_override_applier_idx
            {
                ip.next_opp_turn_end_base_cost_override = None;
                ip.next_opp_turn_end_base_cost_override_applier_idx = -1;
                ip.next_opp_turn_end_base_cost_override_applied_turn = 0;
            }
            if ip.attack_cost_discard_hand_n > 0
                && ip.attack_cost_discard_hand_applier_idx >= 0
                && ip.attack_cost_discard_hand_applied_turn < turn_number
                && ended != ip.attack_cost_discard_hand_applier_idx
            {
                ip.attack_cost_discard_hand_n = 0;
                ip.attack_cost_discard_hand_applier_idx = -1;
                ip.attack_cost_discard_hand_applied_turn = 0;
            }
            if !ip.granted_keywords_through_opp_turn.is_empty()
                && ip.granted_keywords_through_opp_turn_applier_idx >= 0
                && ip.granted_keywords_through_opp_turn_applied_turn < turn_number
                && ended != ip.granted_keywords_through_opp_turn_applier_idx
            {
                ip.granted_keywords_through_opp_turn.clear();
                ip.granted_keywords_through_opp_turn_applier_idx = -1;
                ip.granted_keywords_through_opp_turn_applied_turn = 0;
            }
        }
    }
}

/// game.py:advance_phase の vanilla 移植 (効果トリガー/静的 eval は R3 で追加)。
pub fn advance_phase(state: &mut GameState) -> Result<(), String> {
    if state.game_over {
        return Ok(());
    }
    let cur = state.phase.clone();
    let me = state.turn_player_idx;
    match cur {
        Phase::Refresh => {
            if state.turn_number > 1 {
                let p = &mut state.players[me];
                if p.leader.stay_rested_next_refresh {
                    p.leader.stay_rested_next_refresh = false;
                } else {
                    p.leader.rested = false;
                }
                p.leader.act_used = false; // 起動メイン once_per_turn を毎ターン回復
                if p.leader.ko_per_turn_immune_max > 0 {
                    p.leader.ko_per_turn_immune_remaining = p.leader.ko_per_turn_immune_max;
                }
                let mut don_from_chars = 0;
                for c in p.characters.iter_mut() {
                    if c.stay_rested_next_refresh {
                        c.stay_rested_next_refresh = false;
                    } else {
                        c.rested = false;
                    }
                    c.act_used = false;
                    don_from_chars += c.attached_dons;
                    c.attached_dons = 0;
                    if c.ko_per_turn_immune_max > 0 {
                        c.ko_per_turn_immune_remaining = c.ko_per_turn_immune_max;
                    }
                }
                p.don_active += don_from_chars;
                let mut kept = p.next_refresh_kept_rested_don;
                let mut avail = p.don_rested - kept;
                if avail < 0 {
                    avail = 0;
                    kept = p.don_rested;
                }
                p.don_active += avail + p.leader.attached_dons;
                p.leader.attached_dons = 0;
                p.don_rested = kept;
                p.next_refresh_kept_rested_don = 0;
                for s in p.stages.iter_mut() {
                    s.rested = false;
                    s.act_used = false;
                }
                for c in p.characters.iter_mut() {
                    c.summoning_sickness = false;
                }
                p.leader.next_turn_buff = 0;
                p.leader.next_turn_base_power_override = None;
                for c in p.characters.iter_mut() {
                    c.next_turn_buff = 0;
                    c.next_turn_base_power_override = None;
                }
                for s in p.stages.iter_mut() {
                    s.next_turn_buff = 0;
                    s.next_turn_base_power_override = None;
                }
                p.once_per_turn_used.clear();
            }
            // ターン開始時トリガー (game.py:707、 turn_number==1 含む全ターン)。
            // turn player の on_turn_start → 非turn player の opp_turn_start の順 (turn-first)。
            let opp = 1 - me;
            crate::effects::fire_field_when(state, me, "on_turn_start")?;
            crate::effects::fire_field_when(state, opp, "opp_turn_start")?;
            state.phase = Phase::Draw;
        }
        Phase::Draw => {
            if !(state.turn_number == 1 && state.turn_player_idx == 0) {
                let p = &mut state.players[me];
                if p.deck.is_empty() {
                    let win_self = p.deck_out_wins;
                    declare_winner(state, if win_self { me } else { 1 - me });
                    return Ok(());
                }
                let card = p.deck.remove(0);
                let cid = card.card_id.clone();
                // known_top 消費 (Player.draw)
                if !p.known_top_card_ids.is_empty() && p.known_top_card_ids[0] == cid {
                    p.known_top_card_ids.remove(0);
                } else if let Some(pos) = p.known_top_card_ids.iter().position(|x| *x == cid) {
                    p.known_top_card_ids.remove(pos);
                }
                p.hand.push(card);
                p.cards_drawn_count += 1;
            }
            state.phase = Phase::Don;
        }
        Phase::Don => {
            let n_base = if state.turn_number == 1 && state.turn_player_idx == 0 { 1 } else { 2 };
            let p = &mut state.players[me];
            let n = n_base.min(p.don_remaining_in_deck);
            p.don_active += n;
            p.don_remaining_in_deck -= n;
            // don_phase_modifier / delayed_at_opp_main_phase_start 効果: R3 で追加
            state.phase = Phase::Main;
        }
        Phase::Main => {
            state.phase = Phase::End;
        }
        Phase::End => {
            // ターン終了時トリガー (end_of_turn / opp_end_of_turn) は cost/optional 込みで複雑 → 該当時 bail。
            if board_has_when(&state.players[me], "end_of_turn")
                || board_has_when(&state.players[1 - me], "opp_end_of_turn")
            {
                return Err("end_of_turn trigger 未対応".into());
            }
            reset_turn_buff(state);
            if state.extra_turn_pending {
                state.extra_turn_pending = false;
                state.turn_number += 1;
            } else {
                state.turn_player_idx = 1 - state.turn_player_idx;
                state.turn_number += 1;
            }
            state.phase = Phase::Refresh;
            update_ownership_flags(state);
        }
    }
    // resolve_triggers: R3。 _recompute_static = ownership + 静的効果
    recompute_static(state);
    Ok(())
}

/// action を state に適用 (副作用)。 Python apply_action ラッパ相当: impl 後に _recompute_static の
/// ownership 部分を反映 (静的効果 eval は R3)。
pub fn apply_action(state: &mut GameState, action: &Value) -> Result<(), String> {
    let r = apply_action_impl(state, action);
    if r.is_ok() {
        recompute_static(state); // ownership + 静的効果 (Python _recompute_static)
        for p in state.players.iter_mut() {
            normalize_known_hand(p);
        }
    }
    r
}

/// core.py Player.normalize_known_hand = known_hand_card_ids を hand との整合で正規化
/// (退場カード分を先頭マッチで削除)。
fn normalize_known_hand(p: &mut Player) {
    use std::collections::BTreeMap;
    let mut hand_counts: BTreeMap<&str, i32> = BTreeMap::new();
    for c in &p.hand {
        *hand_counts.entry(c.card_id.as_str()).or_insert(0) += 1;
    }
    let mut used: BTreeMap<String, i32> = BTreeMap::new();
    let mut new_known = Vec::new();
    for cid in &p.known_hand_card_ids {
        let hc = hand_counts.get(cid.as_str()).copied().unwrap_or(0);
        let u = used.get(cid).copied().unwrap_or(0);
        if u < hc {
            new_known.push(cid.clone());
            *used.entry(cid.clone()).or_insert(0) += 1;
        }
    }
    p.known_hand_card_ids = new_known;
}

fn apply_action_impl(state: &mut GameState, action: &Value) -> Result<(), String> {
    let t = action.get("t").and_then(|v| v.as_str()).ok_or("action に t が無い")?;
    let me = state.turn_player_idx;
    match t {
        // キャラ登場 (game.py:1325)。 ⚠ on_play 効果 + cost 軽減 (in_hand/filtered) は R3 で追加。
        // 現状は play 機構 + last_self_chara_played context のみ (効果無し/軽減無しカードで一致)。
        "PlayCharacter" => {
            let hand_idx = geti(action, "hand_idx", -1);
            let sac_idx = action.get("sacrifice_idx").and_then(|v| v.as_i64());
            if hand_idx < 0 || hand_idx as usize >= state.players[me].hand.len() {
                return Err(format!("hand_idx 範囲外: {hand_idx}"));
            }
            let card: CardDef = state.players[me].hand[hand_idx as usize].clone();
            // eff_cost = cost - play_cost_reduction - in_hand - filtered (game.py と一致)
            let eff_cost = crate::effects::eff_cost(state, me, &card);
            if state.players[me].don_active < eff_cost {
                return Err("not enough don".into());
            }
            let p = &mut state.players[me];
            if let Some(si) = sac_idx {
                if si < 0 || si as usize >= p.characters.len() {
                    return Err(format!("sacrifice_idx 範囲外: {si}"));
                }
                let s = p.characters.remove(si as usize);
                let sd = s.attached_dons;
                p.trash.push(s.card);
                if sd > 0 {
                    p.don_rested += sd;
                }
            }
            p.hand.remove(hand_idx as usize);
            p.don_rested += eff_cost;
            p.don_active -= eff_cost;
            let consumed = card.cost - eff_cost;
            p.play_cost_reduction = (p.play_cost_reduction - consumed).max(0);
            let sickness = !card.is_rush();
            p.characters.push(InPlay::of(card.clone(), sickness));
            p.cards_played_count += 1;
            let played_idx = p.characters.len() - 1;
            // trigger_on_play context (Python は on_play 有無に関わらず設定、 effects.py:10640)
            state.last_self_chara_played_card = Some(card);
            state.last_self_chara_played_from_trash = false; // 手札からの登場
            // on_play 効果を実行 (未対応 primitive のカードは diverge = 差分テストが境界)。
            // ⚠ on_opp_chara_played (相手側) は未対応。
            crate::effects::execute_on_play(state, me, played_idx);
            Ok(())
        }
        "AttachDonToLeader" => {
            let p = &mut state.players[me];
            let n = (geti(action, "n", 0) as i32).min(p.don_active);
            p.don_active -= n;
            p.leader.attached_dons += n;
            p.dons_used_count += n;
            Ok(())
        }
        "AttachDonToCharacter" => {
            let idx = geti(action, "target_idx", -1);
            let p = &mut state.players[me];
            if idx < 0 || idx as usize >= p.characters.len() {
                return Err(format!("target_idx 範囲外: {idx}"));
            }
            let n = (geti(action, "n", 0) as i32).min(p.don_active);
            p.don_active -= n;
            p.characters[idx as usize].attached_dons += n;
            p.dons_used_count += n;
            Ok(())
        }
        // リーダーへのアタック (game.py:1441)。 counter card + blocker + 基本 KO/life まで対応。
        // bail(Err=差分テスト境界): attack cost / on_attack / opp_attack / counter event /
        //   on_block / on_opp_blocker_use / KO cascade / life 移動 trigger / on_life_zero。
        "AttackLeader" => {
            let opp = 1 - me;
            let atk_kind = action.get("attacker_kind").and_then(|v| v.as_str()).unwrap_or("");
            let atk_idx = geti(action, "attacker_idx", 0) as usize;
            let counter_cards: Vec<i64> = action
                .get("counter_card_idxs")
                .and_then(|v| v.as_array())
                .map(|a| a.iter().filter_map(|x| x.as_i64()).collect())
                .unwrap_or_default();
            if action
                .get("counter_event_idxs")
                .and_then(|v| v.as_array())
                .map_or(false, |a| !a.is_empty())
            {
                return Err("counter event 未対応".into());
            }
            // attacker 存在チェック (absent = 攻撃不発 = Ok no-op、 game.py:1443)
            let attacker_exists = match atk_kind {
                "leader" => true,
                "char" => atk_idx < state.players[me].characters.len(),
                _ => return Err("bad attacker".into()),
            };
            if !attacker_exists {
                return Ok(());
            }
            let is_leader = atk_kind == "leader";
            // 初期 read (on_attack 発火前): card_id / attack cost だけ確認
            let (atk_cid, cost_discard) = {
                let a = if is_leader { &state.players[me].leader } else { &state.players[me].characters[atk_idx] };
                (a.card.card_id.clone(), a.attack_cost_discard_hand_n)
            };
            if cost_discard > 0 {
                return Err("attack cost 未対応".into());
            }
            // attacker.rested = true (game.py:1466、 on_attack 発火前)
            if is_leader {
                state.players[me].leader.rested = true;
            } else {
                state.players[me].characters[atk_idx].rested = true;
            }
            // 【アタック時】(on_attack) 発火 (game.py:1467、 costless slice のみ、 未対応は Err で bail)
            crate::effects::fire_on_attack(state, me, is_leader, atk_idx)?;
            // 【相手のアタック時】(opp_attack + on_leader) 発火 (game.py:1476、 defended_target=leader)。
            // AI が発動しない (skip) なら一致、 cost effect fire は Err (防御 EV heuristic 移植済)。
            let atk_cost = {
                let a = if is_leader { &state.players[me].leader } else { &state.players[me].characters[atk_idx] };
                a.card.cost
            };
            let ap = if is_leader { state.players[me].leader.power() } else { state.players[me].characters[atk_idx].power() };
            let dp = state.players[opp].leader.power();
            crate::effects::fire_opp_attack(state, opp, "opp_attack", ap, atk_cost, dp)?;
            let dp2 = state.players[opp].leader.power();
            crate::effects::fire_opp_attack(state, opp, "opp_attack_on_leader", ap, atk_cost, dp2)?;
            // on_attack/opp_attack で power/keyword が変化しうるので attacker を再スナップショット
            let attacker: InPlay = if is_leader {
                state.players[me].leader.clone()
            } else {
                state.players[me].characters[atk_idx].clone()
            };
            let atk_power_base = attacker.power();
            let is_double = attacker.is_double_attack_now();
            let is_banish = attacker.is_banish_now();
            let no_block = attacker.has_no_block_now();
            // === ブロックステップ (7-1-2) ===
            let blocker_idx: Option<usize> = if no_block {
                None
            } else {
                action
                    .get("blocker")
                    .and_then(|b| if b.is_null() { None } else { b.get("idx").and_then(|v| v.as_i64()) })
                    .map(|i| i as usize)
            };
            let mut is_blocked = false;
            let mut blk_idx = 0usize;
            if let Some(bi) = blocker_idx {
                let valid = bi < state.players[opp].characters.len() && {
                    let b = &state.players[opp].characters[bi];
                    !b.rested && b.is_blocker_now() && !b.blocker_disabled_until_turn_end
                };
                if valid {
                    let bcid = state.players[opp].characters[bi].card.card_id.clone();
                    if crate::effects::card_has_when(&bcid, "on_block")
                        || board_has_when(&state.players[me], "on_opp_blocker_use")
                    {
                        return Err("on_block/on_opp_blocker_use 未対応".into());
                    }
                    state.players[opp].characters[bi].rested = true;
                    is_blocked = true;
                    blk_idx = bi;
                }
                // 不正ブロッカーは無視 = リーダーへ続行 (game.py:1591-1605)
            }
            // === カウンターフェイズ (7-1-3) ===
            let counter_added = spend_counters(&mut state.players[opp], &counter_cards);

            if is_blocked {
                // ブロッカー vs アタッカー (勝てば blocker KO、 負ければ生存、 リーダーへの damage 無)
                let (atk_power, def_power, immune) = {
                    let blocker = &state.players[opp].characters[blk_idx];
                    let ap = atk_power_base + battle_attr_bonus(&attacker, blocker);
                    let dp = blocker.power() + counter_added + battle_attr_bonus(blocker, &attacker);
                    let vs_leader_immune = blocker.battle_ko_immune_vs_leader && atk_kind == "leader";
                    let imm = blocker.ko_immune_until_turn_end
                        || battle_ko_immune_by_attribute(blocker, &attacker)
                        || vs_leader_immune;
                    (ap, dp, imm)
                };
                if atk_power >= def_power && !immune {
                    // EB02-030: バトルKO 代替で手札1捨てて生存 (= 該当時 bail)
                    if state.players[opp].turn_battle_ko_save_discard
                        && !state.players[opp].hand.is_empty()
                    {
                        return Err("battle_ko_save_discard 未対応".into());
                    }
                    do_battle_ko(state, opp, blk_idx, me, &atk_cid, true)?;
                }
                reset_battle_buffs(state);
                return Ok(());
            }

            // === 非ブロック: リーダーへのダメージ (leader へは attr bonus 無) ===
            let def_power = state.players[opp].leader.power() + counter_added;
            if atk_power_base >= def_power {
                let damage = if is_double { 2 } else { 1 };
                if state.players[opp].life.is_empty() {
                    if crate::effects::card_has_when(
                        &state.players[opp].leader.card.card_id,
                        "on_life_zero",
                    ) {
                        return Err("on_life_zero 未対応".into());
                    }
                    // 敗北宣言 (game.py:1748 は reset_battle_buffs せず return)
                    declare_winner(state, me);
                    return Ok(());
                }
                // 取られる life 上位 damage 枚: 防御 AI が【トリガー】を発動しない (=手札へ) なら一致、
                // 発動 or 条件 unknown は未対応 (trigger_lifecard_trigger の発火は複雑) → bail。
                for i in 0..(damage as usize).min(state.players[opp].life.len()) {
                    let cid = state.players[opp].life[i].card_id.clone();
                    match crate::effects::should_fire_trigger(state, opp, &cid) {
                        Some(false) => {}
                        _ => return Err("life trigger (fire/unknown) 未対応".into()),
                    }
                }
                for _ in 0..damage {
                    if state.players[opp].life.is_empty() {
                        break;
                    }
                    let taken = state.players[opp].life.remove(0);
                    state.players[opp].life_lost_this_turn = true;
                    if is_banish {
                        // バニッシュ = trash 直行、 _resolve_life_taken を通らない = life 移動 trigger 無
                        state.players[opp].trash.push(taken);
                    } else {
                        // 手札へ (should_fire=false 済) → 公式 10-1-5 直後の life 移動 trigger を per-hit 発火。
                        // attacker: on_opp_life_taken / defender: on_self_life_to_hand + on_self_life_taken。
                        state.players[opp].hand.push(taken);
                        crate::effects::fire_field_when(state, me, "on_opp_life_taken")?;
                        crate::effects::fire_field_when(state, opp, "on_self_life_to_hand")?;
                        crate::effects::fire_field_when(state, opp, "on_self_life_taken")?;
                    }
                }
            }
            reset_battle_buffs(state);
            Ok(())
        }
        // キャラへのアタック (game.py:1813)。 counter card + blocker + KO 判定 (attr bonus 両方向)。
        // bail: attack cost / on_attack / on_self_battled / opp_attack / counter event / on_block /
        //   return_at_battle_end / KO cascade。
        "AttackCharacter" => {
            let opp = 1 - me;
            let atk_kind = action.get("attacker_kind").and_then(|v| v.as_str()).unwrap_or("");
            let atk_idx = geti(action, "attacker_idx", 0) as usize;
            let tgt_idx = geti(action, "target_idx", -1);
            let counter_cards: Vec<i64> = action
                .get("counter_card_idxs")
                .and_then(|v| v.as_array())
                .map(|a| a.iter().filter_map(|x| x.as_i64()).collect())
                .unwrap_or_default();
            if action
                .get("counter_event_idxs")
                .and_then(|v| v.as_array())
                .map_or(false, |a| !a.is_empty())
            {
                return Err("counter event 未対応".into());
            }
            let attacker_exists = match atk_kind {
                "leader" => true,
                "char" => atk_idx < state.players[me].characters.len(),
                _ => return Err("bad attacker".into()),
            };
            if !attacker_exists {
                return Ok(());
            }
            let is_leader = atk_kind == "leader";
            let (atk_cid, cost_discard, ret_at_battle_end) = {
                let a = if is_leader { &state.players[me].leader } else { &state.players[me].characters[atk_idx] };
                (a.card.card_id.clone(), a.attack_cost_discard_hand_n, a.return_to_deck_bottom_at_battle_end)
            };
            if cost_discard > 0 {
                return Err("attack cost 未対応".into());
            }
            // on_self_battled は char vs char バトル終了時に発火 (game.py:1994) → bail
            if crate::effects::card_has_when(&atk_cid, "on_self_battled") {
                return Err("on_self_battled 未対応".into());
            }
            if ret_at_battle_end {
                return Err("return_at_battle_end 未対応".into());
            }
            // attacker.rested = true (game.py:1833、 on_attack 発火前、 target-check より先)
            if is_leader {
                state.players[me].leader.rested = true;
            } else {
                state.players[me].characters[atk_idx].rested = true;
            }
            // 【アタック時】(on_attack) 発火 (costless slice のみ、 未対応は Err)
            crate::effects::fire_on_attack(state, me, is_leader, atk_idx)?;
            // 【相手のアタック時】(opp_attack + on_chara) 発火 (game.py:1843、 defended_target=対象キャラ)。
            // target 消失時 (= 通常起きない、 fire は bail) は defended_power=0 で扱う。
            let atk_cost = {
                let a = if is_leader { &state.players[me].leader } else { &state.players[me].characters[atk_idx] };
                a.card.cost
            };
            let ap = if is_leader { state.players[me].leader.power() } else { state.players[me].characters[atk_idx].power() };
            let dp = if (tgt_idx as usize) < state.players[opp].characters.len() {
                state.players[opp].characters[tgt_idx as usize].power()
            } else {
                0
            };
            crate::effects::fire_opp_attack(state, opp, "opp_attack", ap, atk_cost, dp)?;
            let dp2 = if (tgt_idx as usize) < state.players[opp].characters.len() {
                state.players[opp].characters[tgt_idx as usize].power()
            } else {
                0
            };
            crate::effects::fire_opp_attack(state, opp, "opp_attack_on_chara", ap, atk_cost, dp2)?;
            // target 存在チェック (on_attack/opp_attack 後、 消失 = 空打ち = reset+Ok、 game.py:1849)
            if tgt_idx < 0 || tgt_idx as usize >= state.players[opp].characters.len() {
                reset_battle_buffs(state);
                return Ok(());
            }
            // on_attack で power/keyword が変化しうるので再スナップショット
            let attacker: InPlay = if is_leader {
                state.players[me].leader.clone()
            } else {
                state.players[me].characters[atk_idx].clone()
            };
            // === ブロック (AttackCharacter は has_no_block を見ない、 on_opp_blocker_use も発火しない) ===
            let mut actual_idx = tgt_idx as usize;
            let blocker_idx: Option<usize> = action
                .get("blocker")
                .and_then(|b| if b.is_null() { None } else { b.get("idx").and_then(|v| v.as_i64()) })
                .map(|i| i as usize);
            if let Some(bi) = blocker_idx {
                let valid = bi < state.players[opp].characters.len() && {
                    let b = &state.players[opp].characters[bi];
                    !b.rested && b.is_blocker_now() && !b.blocker_disabled_until_turn_end
                };
                if valid {
                    let bcid = state.players[opp].characters[bi].card.card_id.clone();
                    if crate::effects::card_has_when(&bcid, "on_block") {
                        return Err("on_block 未対応".into());
                    }
                    state.players[opp].characters[bi].rested = true;
                    actual_idx = bi;
                }
            }
            // === カウンター ===
            let counter_added = spend_counters(&mut state.players[opp], &counter_cards);
            // === バトル解決 (attr bonus 両方向) ===
            let (atk_power, def_power, immune) = {
                let target = &state.players[opp].characters[actual_idx];
                let ap = attacker.power() + battle_attr_bonus(&attacker, target);
                let dp = target.power() + counter_added + battle_attr_bonus(target, &attacker);
                let imm = target.ko_immune_until_turn_end || battle_ko_immune_by_attribute(target, &attacker);
                (ap, dp, imm)
            };
            if atk_power >= def_power && !immune {
                do_battle_ko(state, opp, actual_idx, me, &atk_cid, false)?;
            }
            reset_battle_buffs(state);
            Ok(())
        }
        // 起動メイン (game.py:2009)。 source(位置)の effect_index を発火。
        "ActivateMain" => {
            let source_kind = action.get("source_kind").and_then(|v| v.as_str()).unwrap_or("");
            let source_idx = geti(action, "source_idx", 0) as usize;
            let effect_index = geti(action, "effect_index", 0) as usize;
            let p = &state.players[me];
            let card_id = match source_kind {
                "leader" => Some(p.leader.card.card_id.clone()),
                "char" => p.characters.get(source_idx).map(|c| c.card.card_id.clone()),
                "stage" => p.stages.get(source_idx).map(|c| c.card.card_id.clone()),
                _ => None,
            };
            let Some(cid) = card_id else {
                return Err("ActivateMain source 不明".into());
            };
            crate::effects::fire_activate_main(state, me, &cid, effect_index, source_kind, source_idx);
            Ok(())
        }
        // イベント使用 (game.py:1364)。 hand→trash、 cost 支払い、 max_event_cost、 main 効果実行。
        "PlayEvent" => {
            let hand_idx = geti(action, "hand_idx", -1);
            if hand_idx < 0 || hand_idx as usize >= state.players[me].hand.len() {
                return Err(format!("hand_idx 範囲外: {hand_idx}"));
            }
            let card: CardDef = state.players[me].hand[hand_idx as usize].clone();
            let eff_cost = crate::effects::eff_cost(state, me, &card);
            if state.players[me].don_active < eff_cost {
                return Err("not enough don".into());
            }
            let p = &mut state.players[me];
            p.hand.remove(hand_idx as usize);
            p.don_rested += eff_cost;
            p.don_active -= eff_cost;
            let consumed = card.cost - eff_cost;
            p.play_cost_reduction = (p.play_cost_reduction - consumed).max(0);
            let card_id = card.card_id.clone();
            let ccost = card.cost;
            p.trash.push(card);
            p.cards_played_count += 1;
            p.max_event_cost_this_turn = p.max_event_cost_this_turn.max(ccost);
            crate::effects::execute_main_event(state, me, &card_id);
            Ok(())
        }
        // ステージ登場 (game.py:1382)。 hand→stage、 既存 stage (MAX=1) は trash、 on_play 発火。
        "PlayStage" => {
            let hand_idx = geti(action, "hand_idx", -1);
            if hand_idx < 0 || hand_idx as usize >= state.players[me].hand.len() {
                return Err(format!("hand_idx 範囲外: {hand_idx}"));
            }
            let card: CardDef = state.players[me].hand[hand_idx as usize].clone();
            let eff_cost = crate::effects::eff_cost(state, me, &card);
            if state.players[me].don_active < eff_cost {
                return Err("not enough don".into());
            }
            let p = &mut state.players[me];
            // 3-8-5-1: 既存ステージ (MAX_STAGES=1) があれば trash、 付与ドンはレストへ
            if p.stages.len() >= 1 {
                let old = p.stages.remove(0);
                let od = old.attached_dons;
                p.trash.push(old.card);
                if od > 0 {
                    p.don_rested += od;
                }
            }
            p.hand.remove(hand_idx as usize);
            p.don_rested += eff_cost;
            p.don_active -= eff_cost;
            let consumed = card.cost - eff_cost;
            p.play_cost_reduction = (p.play_cost_reduction - consumed).max(0);
            p.stages.push(InPlay::of(card.clone(), false)); // stage は召喚酔い無
            p.cards_played_count += 1;
            let played_idx = p.stages.len() - 1;
            // trigger_on_play context (effects.py:10640、 stage も trigger_on_play を通る)
            state.last_self_chara_played_card = Some(card.clone());
            state.last_self_chara_played_from_trash = false;
            // stage の on_play 効果 (未対応 primitive は diverge)
            crate::effects::execute_stage_on_play(state, me, played_idx);
            Ok(())
        }
        // ターン終了 (game.py:1313)。 MAIN→END→REFRESH→…→MAIN。 効果トリガーは R3。
        "EndPhase" => {
            state.players[me].dons_unused_at_end_count += state.players[me].don_active;
            advance_phase(state)?; // MAIN → END
            if state.game_over {
                return Ok(());
            }
            advance_phase(state)?; // END → REFRESH
            if state.game_over {
                return Ok(());
            }
            while state.phase != Phase::Main && !state.game_over {
                advance_phase(state)?;
            }
            Ok(())
        }
        other => Err(format!("R2 未実装 action: {other}")),
    }
}
