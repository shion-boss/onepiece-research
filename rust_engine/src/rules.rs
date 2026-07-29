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
    // resolve_triggers: R3。 _recompute_static = ownership + 静的効果
    recompute_static(state);
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
            let p = &mut state.players[me];
            if hand_idx < 0 || hand_idx as usize >= p.hand.len() {
                return Err(format!("hand_idx 範囲外: {hand_idx}"));
            }
            let card: CardDef = p.hand[hand_idx as usize].clone();
            let eff_cost = (card.cost - p.play_cost_reduction).max(0);
            if p.don_active < eff_cost {
                return Err("not enough don".into());
            }
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
        // リーダーへのアタック (game.py:1441)。 ⚠ 空防御 (counter/blocker 無) + trigger 無の基本ケースのみ。
        // trigger(on_attack/opp_attack/life)・counter・blocker・attack cost 有なら Err(=差分テストが skip)。
        "AttackLeader" => {
            let opp = 1 - me;
            let atk_kind = action.get("attacker_kind").and_then(|v| v.as_str()).unwrap_or("");
            let atk_idx = geti(action, "attacker_idx", 0) as usize;
            // counter/blocker があれば未対応
            let has_counter = action
                .get("counter_card_idxs")
                .and_then(|v| v.as_array())
                .map_or(false, |a| !a.is_empty())
                || action
                    .get("counter_event_idxs")
                    .and_then(|v| v.as_array())
                    .map_or(false, |a| !a.is_empty());
            let has_blocker = action.get("blocker").map_or(false, |v| !v.is_null());
            if has_counter || has_blocker {
                return Err("counter/blocker 未対応".into());
            }
            // attacker 情報 (存在チェック)
            let (atk_card_id, atk_power, is_double, is_banish, cost_discard) = {
                let a = match atk_kind {
                    "leader" => &state.players[me].leader,
                    "char" => match state.players[me].characters.get(atk_idx) {
                        Some(c) => c,
                        None => return Ok(()), // attacker 不在 = 攻撃不発 (game.py:1443)
                    },
                    _ => return Err("bad attacker".into()),
                };
                (
                    a.card.card_id.clone(),
                    a.power(),
                    a.is_double_attack_now(),
                    a.is_banish_now(),
                    a.attack_cost_discard_hand_n,
                )
            };
            if cost_discard > 0 || crate::effects::card_has_when(&atk_card_id, "on_attack") {
                return Err("attack cost/on_attack 未対応".into());
            }
            // 防御側盤面の opp_attack trigger
            for ip in std::iter::once(&state.players[opp].leader)
                .chain(state.players[opp].characters.iter())
                .chain(state.players[opp].stages.iter())
            {
                if crate::effects::card_has_when(&ip.card.card_id, "opp_attack")
                    || crate::effects::card_has_when(&ip.card.card_id, "opp_attack_on_leader")
                {
                    return Err("opp_attack trigger 未対応".into());
                }
            }
            let defender_power = state.players[opp].leader.power();
            let damage = if is_double { 2 } else { 1 };
            // 取られる life 上位 damage 枚に trigger があれば未対応
            if atk_power >= defender_power {
                for c in state.players[opp].life.iter().take(damage as usize) {
                    if crate::effects::card_has_when(&c.card_id, "trigger") {
                        return Err("life trigger 未対応".into());
                    }
                }
            }
            // --- 適用 ---
            match atk_kind {
                "leader" => state.players[me].leader.rested = true,
                "char" => state.players[me].characters[atk_idx].rested = true,
                _ => {}
            }
            if atk_power >= defender_power {
                if state.players[opp].life.is_empty() {
                    // life 0 trigger は未対応 → 該当は上で trigger check 済でないが、 life 空は敗北
                    declare_winner(state, me);
                    reset_battle_buffs(state);
                    return Ok(());
                }
                for _ in 0..damage {
                    if state.players[opp].life.is_empty() {
                        break;
                    }
                    let taken = state.players[opp].life.remove(0);
                    state.players[opp].life_lost_this_turn = true;
                    if is_banish {
                        state.players[opp].trash.push(taken);
                    } else {
                        state.players[opp].hand.push(taken);
                    }
                }
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
            let p = &mut state.players[me];
            if hand_idx < 0 || hand_idx as usize >= p.hand.len() {
                return Err(format!("hand_idx 範囲外: {hand_idx}"));
            }
            let card: CardDef = p.hand[hand_idx as usize].clone();
            let eff_cost = (card.cost - p.play_cost_reduction).max(0);
            if p.don_active < eff_cost {
                return Err("not enough don".into());
            }
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
