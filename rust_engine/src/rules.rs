//! ルールエンジン (Rust)。 engine/game.py apply_action + phase 機械のミラー (Phase R2)。
//!
//! action は canonical エンコード (instance_id でなく zone 位置で対象参照 = 状態と同じ iid 非依存規約)。
//! ⚠ 効果トリガー (trigger_*) と evaluate_static_effects は R3 (effects) で移植。 現状は効果が絡まない
//! action / vanilla 盤面でのみ Python と一致する (差分テストがその境界を明示)。 update_ownership_flags は
//! 効果非依存なので移植済 (DON+1000 ゲート)。

use crate::state::{GameState, InPlay, Phase, Player};
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
pub fn advance_phase(state: &mut GameState) {
    if state.game_over {
        return;
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
            // trigger_turn_start: R3 で追加
            state.phase = Phase::Draw;
        }
        Phase::Draw => {
            if !(state.turn_number == 1 && state.turn_player_idx == 0) {
                let p = &mut state.players[me];
                if p.deck.is_empty() {
                    let win_self = p.deck_out_wins;
                    declare_winner(state, if win_self { me } else { 1 - me });
                    return;
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
            // trigger_end_of_turn: R3 で追加
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
    // resolve_triggers: R3。 _recompute_static = ownership のみ移植 (静的効果 eval は R3)
    update_ownership_flags(state);
}

/// action を state に適用 (副作用)。 未実装 action type は Err (差分テストで境界が判る)。
pub fn apply_action(state: &mut GameState, action: &Value) -> Result<(), String> {
    let t = action.get("t").and_then(|v| v.as_str()).ok_or("action に t が無い")?;
    let me = state.turn_player_idx;
    match t {
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
        // ターン終了 (game.py:1313)。 MAIN→END→REFRESH→…→MAIN。 効果トリガーは R3。
        "EndPhase" => {
            state.players[me].dons_unused_at_end_count += state.players[me].don_active;
            advance_phase(state); // MAIN → END
            if state.game_over {
                return Ok(());
            }
            advance_phase(state); // END → REFRESH
            if state.game_over {
                return Ok(());
            }
            while state.phase != Phase::Main && !state.game_over {
                advance_phase(state);
            }
            Ok(())
        }
        other => Err(format!("R2 未実装 action: {other}")),
    }
}
