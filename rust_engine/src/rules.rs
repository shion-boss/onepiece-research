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
    // 常在 (= ルール置換) を張り直した **後** に敗北判定 (公式 9-2、 game.py:_check_rule_defeat)。
    check_rule_defeat(state);
}

/// 公式 9-2 敗北判定処理のうち **デッキ0枚** (9-2-1-2)。 game.py:_check_rule_defeat のミラー。
/// 1-2-2 + 9-1-2 = 敗北条件を満たしたら次のルール処理 (= 即座) に敗北する。
/// ルール置換 deck_out_wins (OP03-040) / deck_out_defer (OP15-022) は静的なので
/// evaluate_static_effects が毎回張り直す (= 無効化されたら消える)。
pub fn check_rule_defeat(state: &mut GameState) {
    if state.game_over {
        return;
    }
    let empty: Vec<usize> = (0..state.players.len())
        .filter(|&i| state.players[i].deck.is_empty())
        .collect();
    // 「デッキが0枚に **なった**」 事実を記録 (OP15-022 の遅延敗北はこれで確定し、
    // 後からデッキが戻っても取り消されない)。 END フェイズの判定がこのフラグを読む。
    for &i in &empty {
        if state.players[i].deck_out_defer {
            state.players[i].deck_hit_zero_this_turn = true;
        }
    }
    if empty.is_empty() {
        return;
    }
    // 勝利置換が最優先 (= 敗北条件を満たすが敗北せず勝利する)
    for &i in &empty {
        if state.players[i].deck_out_wins {
            declare_winner(state, i);
            return;
        }
    }
    let losers: Vec<usize> = empty
        .into_iter()
        .filter(|&i| !state.players[i].deck_out_defer)
        .collect();
    if losers.is_empty() {
        return;
    }
    if losers.len() == 2 {
        state.game_over = true;
        state.winner = None;
        return;
    }
    declare_winner(state, 1 - losers[0]);
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
    // 「その後、 このバトル終了時、 このキャラを持ち主のデッキの下に置く」 (OP02-064 ボン・クレー)。
    // Python も バトル終了フック (game.py:_reset_battle_buffs、 公式 7-1-5-1) 本体で flush する
    // ので、 AttackLeader / AttackCharacter のどちらの経路でも同じ位置で処理される。
    // トリガー (on_self_chara_leave_by_self_effect) は Python も発火しないので発火しない。
    for p in state.players.iter_mut() {
        let mut i = 0;
        while i < p.characters.len() {
            if p.characters[i].return_to_deck_bottom_at_battle_end {
                let mut ip = p.characters.remove(i);
                ip.return_to_deck_bottom_at_battle_end = false;
                let don = ip.attached_dons;
                p.deck.push(ip.card);
                p.don_rested += don; // 公式 6-5-5-4: 付与ドンはレストでコストエリアへ
            } else {
                i += 1;
            }
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

/// game.py:_battle_attr_bonus = combatant が「属性X とバトルする時 +N」を持ち opponent が属性X の時 N。
/// ⚠ **バトル中だけの補正ではない**。 公式 (ST05-010 ゼット / cardqa) は 「このターン中 +3000」 で、
///   2 回バトルすれば **合計 +6000** = 発動のたびに turn_buff に累積する。
///   Python は `_apply_battle_attr_pump` が turn_buff へ積む。 Rust はこのケースを
///   **明示 bail** にして 「黙って違う状態を作らない」 を守る (該当 2 枚のみ = self-play 影響は無視できる)。
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
                    // 公式 (cardqa_op_16, OP16-118、 qid 37c3a1f9cb07): 「カウンター+2000 になる」
                    // = 印刷 counter を置換 (SET)。 加算だと印刷 +1000 の札が +3000 になり公式違反。
                    base = b.get("amount").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
                }
            }
            total += base;
            p.trash.push(card);
        }
    }
    total
}

/// バトル KO 実行: victim キャラを trash へ、 付与ドン→レスト。
/// (被 KO 数の加算は fire_on_ko 側 = 全 KO 経路の共通フック)
/// (trigger cascade は呼出側で bail 済 = last_chara_ko_victim_card は cascade 完了後 None に戻るので触らない)
fn battle_ko_character(state: &mut GameState, owner: usize, idx: usize) {
    if idx >= state.players[owner].characters.len() {
        return;
    }
    let removed = state.players[owner].characters.remove(idx);
    let don = removed.attached_dons;
    state.players[owner].trash.push(removed.card);
    state.players[owner].don_rested += don;
    // ⚠ chara_ko_taken_this_turn は fire_on_ko に集約した (Python trigger_on_ko と同じ位置)。
    //   ここで足すと do_battle_ko → fire_on_ko で **二重加算** になる。
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
    attacker_slot: Option<crate::effects::Slot>,
) -> Result<(), String> {
    let vcid = state.players[victim_owner].characters[victim_idx].card.card_id.clone();
    let vcard = state.players[victim_owner].characters[victim_idx].card.clone();
    // KO 時点の 「元々のパワー」 (効果で書き換わっている場合がある、 公式 4-9-2-1 / OP14-053 ビスタ)。
    let vcard_top = state.players[victim_owner].characters[victim_idx].truly_original_power();
    // replace_ko/replace_leave 置換効果 (game.py:1949、 battle KO は by_opp_effect=false)。 対象一致で
    // 置換発動→ KO 阻止 (victim 残存、 on_ko cascade 無し)。 不一致 (by_opp_effect 相違等) は通常 KO へ。
    if crate::effects::try_replace_ko(state, victim_owner, victim_idx, false, "ko")? {
        return Ok(());
    }
    // EB02-030: 「バトルでKOされる場合、 代わりに手札1枚を捨てる」 (per-InPlay フラグ = 効果
    //   発動時に場にいたキャラのみ、 cardqa_eb_02)。 手札があれば KO の代わりに 1 捨てで生存。
    //   ⚠ Rust は discard-save の実行を未実装 = 該当時は明示 bail (silent divergence を防ぐ)。
    //   Python は game.py で実装済 (survive)。 = 発動後登場キャラは per-InPlay フラグが無いので
    //   両エンジンとも通常 KO へ進む (bit 一致)。
    if state.players[victim_owner].characters[victim_idx].battle_ko_save_discard_until_turn_end
        && !state.players[victim_owner].hand.is_empty()
    {
        return Err("battle_ko_save_discard 未対応".into());
    }
    // 【このキャラのバトルによって相手のキャラをKOした時】は KO 実行の **前** に発火する
    // (game.py:1591 は KO 判定直後 = victim 除去前ではないが、 Python の呼出順に合わせる)。
    let pending_battle_ko: Option<crate::effects::Slot> =
        if fire_self_battle_ko && crate::effects::card_has_when(attacker_cid, "on_self_battle_ko") {
            match attacker_slot {
                Some(sl) => Some(sl),
                None => return Err("on_self_battle_ko: attacker slot 不明".into()),
            }
        } else {
            None
        };
    // 公式 Q&A (cardqa_op_09/op_10): 効果を無効にされたキャラの【KO時】は発動しない。
    // ⚠ 除去の **直前** に記録する (fire_on_ko が take して消費)。 効果 KO 経路には入れていたが
    //   バトル KO 経路だけ抜けており、 「効果無効」 を持つ victim の on_ko を Rust だけが発火して
    //   いた (OP14-100 アブサロム、 掃引 MISMATCH、 2026-08-04)。
    crate::effects::note_ko_victim_negated_pub(state, victim_owner, victim_idx);
    battle_ko_character(state, victim_owner, victim_idx);
    // game.py 準拠の順: trigger_on_ko (victim 側) → on_opp_chara_ko (攻撃側) → on_self_chara_ko (victim 側)。
    // Python trigger_on_ko が last_chara_ko_victim_card=victim を set (victim_* 条件用)、 cascade 完了後 None。
    state.last_chara_ko_victim_card = Some(vcard);
    state.rust_ko_victim_truly_original_power = Some(vcard_top);
    // ⭐ 1 回の KO から **同時に** 発動する効果 (victim の【KO時】/ 場の 「キャラがKOされた時」/
    //   「バトルでKOした時」) は **全部発動させてから** キューを流す (公式 cardqa_op_10、
    //   OP10-042 ウソップ(L) × OP10-090 フランキー × OP04-092 レベッカ:
    //   「リーダーの【相手のターン中】効果が、 【KO時】効果で登場したキャラの【登場時】効果よりも
    //    **必ず先に発動します**」)。 途中でドレインすると 【KO時】で登場したキャラの【登場時】が
    //   まだ発動していない同時発動ぶんより先に走る。 Python game.py の KO グループと同則。
    let ko_prev_resolving = state.rust_resolving;
    state.rust_resolving = true;
    // ⚠ **解決順は 「ターンプレイヤーの効果が先」** (公式 1-3-4)。 Python は 4 つとも enqueue して
    //   から `_pop_next_event` (= turn_player 優先 → 同 owner 内 FIFO) で取り出すので、 Rust の
    //   固定順 (on_ko → opp_chara_ko → self_chara_ko → battle_ko) だと owner が turn player で
    //   ない側から走って乖離する。 enqueue 順を保ったまま owner で安定分割して同順を作る。
    let tp = state.turn_player_idx;
    // (step, owner) を Python の enqueue 順で並べる
    let ko_steps: [(u8, usize); 4] = [
        (0, victim_owner),   // trigger_on_ko          (victim の【KO時】)
        (1, attacker_owner), // on_opp_chara_ko        (攻撃側の場)
        (2, victim_owner),   // on_self_chara_ko       (victim 側の場)
        (3, attacker_owner), // on_self_battle_ko      (バトルでKOした時)
    ];
    let mut ordered: Vec<u8> = ko_steps.iter().filter(|(_, o)| *o == tp).map(|(s, _)| *s).collect();
    ordered.extend(ko_steps.iter().filter(|(_, o)| *o != tp).map(|(s, _)| *s));
    let mut err: Option<String> = None;
    for step in ordered {
        if err.is_some() {
            break;
        }
        let r = match step {
            0 => crate::effects::fire_on_ko(state, victim_owner, &vcid, false),
            1 => crate::effects::fire_field_when(state, attacker_owner, "on_opp_chara_ko"),
            2 => crate::effects::fire_field_when(state, victim_owner, "on_self_chara_ko"),
            _ => match pending_battle_ko {
                // 「このキャラのバトルによって相手のキャラをKOした時」
                Some(sl) => {
                    crate::effects::fire_on_self_battle_ko(state, attacker_owner, attacker_cid, sl)
                }
                None => Ok(()),
            },
        };
        if let Err(e) = r {
            err = Some(e);
        }
    }
    state.last_chara_ko_victim_card = None;
    state.rust_ko_victim_truly_original_power = None;
    // KO グループの発動が全部終わってからドレインする (上記の同時発動ルール)。
    state.rust_resolving = ko_prev_resolving;
    if err.is_none() && !ko_prev_resolving {
        if let Err(e) = crate::effects::maybe_resolve(state) {
            err = Some(e);
        }
    }
    match err {
        Some(e) => Err(e),
        None => Ok(()),
    }
}

/// game.py:_reset_turn_buff = ターン終了時のバフ/フラグクリア (applier-tracking 含む)。
/// ⭐ 「次の X のターン終了時まで」 は **適用後 最初に訪れる X のターン終了** で切れる
/// (公式 cardqa_op_01 / OP01-085 Mr.3: 「相手のターン中に登場させた場合の 『次の相手のターン
/// 終了時』 は **そのターンの終了時**」)。 applied_turn < turn_number (strict) だと 相手ターン中に
/// 適用した効果が 1 サイクル長く残る → `<=` に是正 (2026-08-10、 Python game.py と同一)。
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
            ip.battle_ko_save_discard_until_turn_end = false;
            ip.blocker_disabled_until_turn_end = false;
            ip.cannot_attack_until_turn_end = false;
            ip.cost_minus_until_turn_end = 0;
            ip.attacker_prevents_blocker_until_turn_end = false;
            ip.attacker_prevents_blocker_power_le = -1;
            ip.cannot_attack_target_cost_le_until_turn_end = -1;
            ip.turn_base_power_override = None;
            ip.turn_base_power_override_is_original = false; // 公式 4-9-2-1 の 「元々の」 書き換えフラグも同時に落とす (game.py:556)
        }
        p.play_cost_reduction = 0;
        p.block_chara_play_until_turn_end = false;
        p.block_hand_play_until_turn_end = false;
        p.opp_on_play_disabled_through_opp_turn = false;
        p.block_self_draw_until_turn_end = false;
        p.block_chara_effect_untap_don_until_turn_end = false;
        p.cannot_attack_leader_until_turn_end = false;
        p.life_lost_this_turn = false;
        p.leader_battled_opp_chara_this_turn = false;
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
                && ip.next_opp_turn_end_applied_turn <= turn_number
                && ended != ip.next_opp_turn_end_applier_idx
            {
                ip.next_opp_turn_end_buff = 0;
                ip.next_opp_turn_end_applier_idx = -1;
                ip.next_opp_turn_end_applied_turn = 0;
            }
            if (ip.next_self_turn_end_buff != 0 || ip.next_self_turn_end_applier_idx >= 0)
                && ip.next_self_turn_end_applier_idx >= 0
                && ip.next_self_turn_end_applied_turn <= turn_number
                && ended == ip.next_self_turn_end_applier_idx
            {
                ip.next_self_turn_end_buff = 0;
                ip.next_self_turn_end_applier_idx = -1;
                ip.next_self_turn_end_applied_turn = 0;
            }
            if ip.cannot_be_rested_buff
                && ip.cannot_be_rested_applier_idx >= 0
                && ip.cannot_be_rested_applied_turn <= turn_number
                && ended != ip.cannot_be_rested_applier_idx
            {
                ip.cannot_be_rested_buff = false;
                ip.cannot_be_rested_applier_idx = -1;
                ip.cannot_be_rested_applied_turn = 0;
            }
            if ip.next_opp_turn_end_base_power_override.is_some()
                && ip.next_opp_turn_end_base_power_override_applier_idx >= 0
                && ip.next_opp_turn_end_base_power_override_applied_turn <= turn_number
                && ended != ip.next_opp_turn_end_base_power_override_applier_idx
            {
                ip.next_opp_turn_end_base_power_override = None;
                ip.next_opp_turn_end_base_power_override_is_original = false; // game.py:627
                ip.next_opp_turn_end_base_power_override_applier_idx = -1;
                ip.next_opp_turn_end_base_power_override_applied_turn = 0;
            }
            if ip.next_opp_turn_end_base_cost_override.is_some()
                && ip.next_opp_turn_end_base_cost_override_applier_idx >= 0
                && ip.next_opp_turn_end_base_cost_override_applied_turn <= turn_number
                && ended != ip.next_opp_turn_end_base_cost_override_applier_idx
            {
                ip.next_opp_turn_end_base_cost_override = None;
                ip.next_opp_turn_end_base_cost_override_applier_idx = -1;
                ip.next_opp_turn_end_base_cost_override_applied_turn = 0;
            }
            if ip.attack_cost_discard_hand_n > 0
                && ip.attack_cost_discard_hand_applier_idx >= 0
                && ip.attack_cost_discard_hand_applied_turn <= turn_number
                && ended != ip.attack_cost_discard_hand_applier_idx
            {
                ip.attack_cost_discard_hand_n = 0;
                ip.attack_cost_discard_hand_applier_idx = -1;
                ip.attack_cost_discard_hand_applied_turn = 0;
            }
            if !ip.granted_keywords_through_opp_turn.is_empty()
                && ip.granted_keywords_through_opp_turn_applier_idx >= 0
                && ip.granted_keywords_through_opp_turn_applied_turn <= turn_number
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
                p.leader.attack_once_used.clear();
                p.leader.event_once_used.clear();
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
                    c.attack_once_used.clear();
                    c.event_once_used.clear();
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
                    s.attack_once_used.clear();
                    s.event_once_used.clear();
                }
                for c in p.characters.iter_mut() {
                    c.summoning_sickness = false;
                }
                p.leader.next_turn_buff = 0;
                p.leader.next_turn_base_power_override = None;
                p.leader.next_turn_base_power_override_is_original = false; // game.py:712
                for c in p.characters.iter_mut() {
                    c.next_turn_buff = 0;
                    c.next_turn_base_power_override = None;
                    c.next_turn_base_power_override_is_original = false; // game.py:716
                }
                for s in p.stages.iter_mut() {
                    s.next_turn_buff = 0;
                    s.next_turn_base_power_override = None;
                    s.next_turn_base_power_override_is_original = false; // game.py:720
                }
                p.once_per_turn_used.clear();
                p.replace_opt_used_cards.clear(); // replace once の canonical mirror (game.py:695)
                p.once_shared_used.clear(); // 明示キー once の canonical mirror (game.py:697)
            }
            // ターン開始時トリガー (game.py:707、 turn_number==1 含む全ターン)。
            // turn player の on_turn_start → 非turn player の opp_turn_start の順 (turn-first)。
            // Python trigger_turn_start は **両陣営を enqueue してから 1 回ドレイン** する
            // (= ターン側の効果の do が誘発したものより、 非ターン側の opp_turn_start が先)。
            let opp = 1 - me;
            crate::effects::enqueue_turn_start(state, me, opp)?;
            state.phase = Phase::Draw;
        }
        Phase::Draw => {
            if !(state.turn_number == 1 && state.turn_player_idx == 0) {
                let p = &mut state.players[me];
                if p.deck.is_empty() {
                    if p.deck_out_wins {
                        declare_winner(state, me);
                        return Ok(());
                    }
                    // OP15-022 ブルック: デッキ0 でも即敗北せず、 そのターン終了時に敗北
                    // (game.py の deck_out_defer と同じ。 引けずに DON へ進む)。
                    if p.deck_out_defer {
                        state.phase = Phase::Don;
                        return Ok(());
                    }
                    declare_winner(state, 1 - me);
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
            // ドンフェイズ修飾 (game.py:743): リーダー overlay の when:"don_phase_modifier" の
            // auto_attach_to_leader = 配られたドンのうち N 枚を自リーダーに自動付与 (OP13-003)。
            if n > 0 {
                crate::effects::apply_don_phase_modifier(state, me)?;
            }
            state.phase = Phase::Main;
        }
        Phase::Main => {
            state.phase = Phase::End;
        }
        Phase::End => {
            // ⭐ 遅延デッキアウト敗北 (OP15-022): 「デッキが0枚になったターン終了時に敗北」。
            //   両者該当なら **同時敗北** = 引き分け (cardqa_op_15、 game.py と同順)。
            // ⭐ 「今0枚か」 ではなく 「このターンに0枚になったか」 で判定 (game.py と一致、
            //    cardqa_op_15: 補充しても / 無効化されても そのターン終了時に敗北)。
            // ⚠ END フェイズ中に 0 枚になった場合はフラグが立つ前にここへ来るので、
            //    **今 0 枚か** も併せて見る (game.py と同条件)。
            let deck_out: Vec<usize> = (0..state.players.len())
                .filter(|&i| state.players[i].deck_hit_zero_this_turn
                    || (state.players[i].deck_out_defer && state.players[i].deck.is_empty()))
                .collect();
            for p in state.players.iter_mut() {
                p.deck_hit_zero_this_turn = false; // 判定はターンごと
            }
            if !deck_out.is_empty() && !state.game_over {
                if deck_out.len() == 2 {
                    state.game_over = true;
                    state.winner = None;
                } else {
                    declare_winner(state, 1 - deck_out[0]);
                }
                return Ok(());
            }
            // ターン終了時処理 (trigger_end_of_turn 前半、 effects.py:11414)。 Python 順: 予約効果 flush →
            // return_to_deck → trash → (下の) end_of_turn トリガー。
            // 1. scheduled_at_self_turn_end flush (source-gone、 safe prim のみ = fire_gated_do、 未対応は bail)。
            //    Python は list を clear してから saved copy を実行 → mem::take で同順 (bail 時は state 破棄=無害)。
            let scheduled =
                std::mem::take(&mut state.players[me].scheduled_at_self_turn_end);
            for spec in &scheduled {
                // 発動元 category を復元 (= src=Leader placeholder でも 「キャラの効果」 gate を効かせる)
                state.rust_scheduled_src_category = spec
                    .get("_src_category")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                let r = if let Some(dos) = spec.get("do").and_then(|d| d.as_array()) {
                    crate::effects::fire_gated_do(state, me, crate::effects::Slot::Leader, dos)
                } else {
                    Ok(())
                };
                state.rust_scheduled_src_category = None;
                r?;
            }
            // 2. return_to_deck_bottom_at_turn_end: 一時登場キャラを持ち主デッキ下へ (付与ドン→レスト)。
            // ⭐ 「このキャラが場を離れる場合、 代わりに〜」 の置換は **ターン終了時の離脱にも** かかる
            //    (公式 cardqa_eb_04 / EB04-044 コビー)。 effects.py と同順・同 leave_kind でミラー。
            {
                let mut i = 0;
                while i < state.players[me].characters.len() {
                    if !state.players[me].characters[i].return_to_deck_bottom_at_turn_end {
                        i += 1;
                        continue;
                    }
                    if crate::effects::try_replace_ko(state, me, i, false, "return_to_deck_bottom")? {
                        // 置換成立 = 場に残る。 一時登場の期限は消化済 (Python と一致)。
                        if i < state.players[me].characters.len() {
                            state.players[me].characters[i].return_to_deck_bottom_at_turn_end = false;
                        }
                        i += 1;
                        continue;
                    }
                    if i >= state.players[me].characters.len() {
                        continue;   // 置換の do 内で既に場を離れた
                    }
                    let p = &mut state.players[me];
                    let ip = p.characters.remove(i);
                    let don = ip.attached_dons;
                    p.deck.push(ip.card);
                    p.don_rested += don;
                }
            }
            // 3. trash_at_self_turn_end: 自己犠牲 (trash、 effects.py:11434)。
            {
                let mut i = 0;
                while i < state.players[me].characters.len() {
                    if !state.players[me].characters[i].trash_at_self_turn_end {
                        i += 1;
                        continue;
                    }
                    if crate::effects::try_replace_ko(state, me, i, false, "trash")? {
                        if i < state.players[me].characters.len() {
                            state.players[me].characters[i].trash_at_self_turn_end = false;
                        }
                        i += 1;
                        continue;
                    }
                    if i >= state.players[me].characters.len() {
                        continue;
                    }
                    let p = &mut state.players[me];
                    let ip = p.characters.remove(i);
                    let don = ip.attached_dons;
                    p.trash.push(ip.card);
                    p.don_rested += don;
                }
            }
            // on-field end_of_turn (me) / opp_end_of_turn (opp)。 Python trigger_end_of_turn と同じく
            // **走査 (コスト支払い) → カード単位で enqueue → 最後に 1 回ドレイン** の 2 相
            // (= do が誘発した効果や 後続カードのコスト判定の順序を Python と揃える)。
            // cost/once/unknown/未対応prim は Err で bail = 黙って間違えない。
            crate::effects::fire_end_of_turn_batch(state, me)?;
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

/// ライフ 1 枚ぶんの解決 (Python game.py:_resolve_life_taken の port)。
///
/// 戦闘ダメージ (rules.rs の damage ループ) と 効果ダメージ (effects.rs の
/// `deal_opp_leader_damage`) の **両方から呼ぶ**。 2026-08-12 まで効果ダメージ側は
/// 独自実装で、 【トリガー】が発動する局面を明示 bail していた (play_self の trash routing が
/// 戦闘経路と揃わないため)。 Python は 1 つの関数を共有しているので、 Rust も共有すれば
/// 順序ごと一致する。
///
/// - `is_banish`  : バニッシュ (= trash 直行、 【トリガー】も life 移動 when も無し)
/// - `by_effect`  : 効果ダメージ。 `on_self_life_taken` (= 戦闘専用) を発火せず、
///                  attacker 側は `_fire_opp_life_left_by_effect` と同じ when を使う
/// - `fire_attacker_side`: 「相手のライフにダメージを与えた時」 は 1 アタック 1 回
///                  (【ダブルアタック】の 2 発目は false、 公式 cardqa_op_03)
pub(crate) fn resolve_life_taken(
    state: &mut GameState,
    me: usize,
    opp: usize,
    is_banish: bool,
    by_effect: bool,
    fire_attacker_side: bool,
) -> Result<(), String> {
    if state.players[opp].life.is_empty() {
        return Ok(());
    }
    let taken_face_up = state.players[opp].life_face_up.remove(0);
    let taken = state.players[opp].life.remove(0);
    state.players[opp].life_lost_this_turn = true;
    // ⭐ 「ルール上、 自分の表向きのライフは **手札に加わる代わりにデッキの下** に
    //   置かれる」 (ST13-003、 公式 cardqa_st_13)。 【トリガー】は 「手札に加える
    //   代わりに公開して発動する」 置換 (10-1-5) なので、 手札に加わらない =
    //   **発動できない**。 Python game.py:_resolve_life_taken の同位置と対。
    if taken_face_up && state.players[opp].face_up_life_to_deck_bottom {
        let fire_zero_r = state.players[opp].life.is_empty();
        state.players[opp].deck.push(taken);
        // ⚠ 行き先はデッキの下なので **手札/トラッシュ系 when は発火しない**。
        //   attacker 側の 「相手のライフが離れた時」 と defender 側の
        //   「ダメージを受けた時」 は発火する (ライフは離れ、 ダメージも与えた)。
        if fire_attacker_side {
            crate::effects::fire_field_when(state, me, "on_opp_life_taken")?;
        }
        // ⚠ 「ダメージを受けた時」 は **戦闘ダメージ専用** (Python も by_effect では発火しない)。
        if !by_effect {
            crate::effects::fire_field_when(state, opp, "on_self_life_taken")?;
        }
        if fire_zero_r {
            let lcid0 = state.players[opp].leader.card.card_id.clone();
            if crate::effects::card_has_when(&lcid0, "on_life_zero") {
                crate::effects::fire_on_life_zero(state, opp)?;
            }
        }
        return Ok(());
    }
    // ⭐ 公式 (cardqa_op_05 / OP05-098 エネル): 「自分のライフが0枚になった時」 は
    //   **0 になった瞬間の事象**。 この後 ライフ札の【トリガー】でライフが戻っても
    //   発動できる。 ⚠ ただし **発動は ライフ処理が終わってから**
    //   (公式 cardqa_op_11 / OP11-102 ケイミー × エネル: ターンプレイヤーの効果が先)。
    //   Python game.py:_resolve_life_taken の **末尾** と同位置で発火する。
    let fire_zero = state.players[opp].life.is_empty();
    let cid = taken.card_id.clone();
    if is_banish {
        // バニッシュ = trash 直行、 _resolve_life_taken を通らない = life 移動 trigger 無
        state.players[opp].trash.push(taken);
        return Ok(());
    }
    let went_to_hand = match crate::effects::should_fire_trigger(state, opp, &cid) {
        Some(false) => {
            state.players[opp].hand.push(taken); // トリガー不発 → 手札
            true
        }
        Some(true) if crate::effects::trigger_contains_play_self(&cid) => {
            // play_self trigger (game.py:2117): taken を trash[0] に pre-place してから発火し、
            // play_self が current_source_card_id で自身を探して登場させる。
            // ⭐ Python の消費判定は identity (`_c is taken`) だが、 CardDef は **repository 共有
            //   instance** = 同名カードは全て同一 object。 よって Python の still_in_trash loop
            //   (`for _c in trash: if _c is taken`) は trash 内の任意の同名 cid に一致し、 先頭を pop
            //   → routing する。 = position(cid) で先頭を探して routing する position ベースが同名複製
            //   込みで Python と完全一致 (k≥1 の bail は不要だった)。 見つからない = play_self が全消費
            //   (played_self=True, went_to_hand=false)。
            state.players[opp].trash.insert(0, taken);
            let kept = crate::effects::fire_life_trigger(state, opp, me, &cid)?;
            match state.players[opp].trash.iter().position(|c| c.card_id == cid) {
                Some(pos) => {
                    // still_in_trash → played_self=False → life 札 (共有 object の任意 1 枚) を routing。
                    let t = state.players[opp].trash.remove(pos);
                    if kept {
                        state.players[opp].hand.push(t);
                        true
                    } else {
                        state.players[opp].trash.push(t);
                        false
                    }
                }
                // trash に cid 無し = play_self が taken を登場させた (played_self、 went_to_hand=false)
                None => false,
            }
        }
        Some(true) => {
            // トリガー発火 (kept_in_hand で routing)。 未対応 trigger は Err で bail。
            let kept = crate::effects::fire_life_trigger(state, opp, me, &cid)?;
            if kept {
                state.players[opp].hand.push(taken);
                true
            } else {
                state.players[opp].trash.push(taken);
                false
            }
        }
        None => return Err("life trigger (unknown) 未対応".into()),
    };
    // 公式 10-1-5 直後の life 移動トリガー (trigger_on_opp_life_taken、 went_to_hand で分岐)。
    // ⭐ 「相手のライフに **ダメージを与えた時**」 は 1 アタックにつき **1 回**
    //   (公式 cardqa_op_03: 【ダブルアタック】で2ダメージでも 「いいえ、 1回のみ」)。
    //   defender 側 (ライフが手札/トラッシュへ移動した時) は カードごとの事象なので毎 hit。
    if by_effect {
        // 効果ダメージ: Python は `_fire_opp_life_left_by_effect` を通す
        // (= on_opp_life_taken + on_self_life_to_hand/to_trash、 **on_self_life_taken は無し**)。
        if crate::effects::fire_opp_life_left_by_effect(
            state, me, opp, if went_to_hand { "hand" } else { "trash" },
        )
        .is_err()
        {
            return Err("効果ダメージの life 移動 when 未対応".into());
        }
    } else {
        if fire_attacker_side {
            crate::effects::fire_field_when(state, me, "on_opp_life_taken")?;
        }
        if went_to_hand {
            crate::effects::fire_field_when(state, opp, "on_self_life_to_hand")?;
        } else {
            crate::effects::fire_field_when(state, opp, "on_self_life_to_trash")?;
        }
        // ⚠ 「ダメージを受けた時」 は **戦闘ダメージ専用** (Python も by_effect では発火しない)。
        crate::effects::fire_field_when(state, opp, "on_self_life_taken")?;
    }
    // ⭐ 「自分のライフが0枚になった時」 は **ライフ処理の後** に発動する
    //   (Python game.py:_resolve_life_taken の末尾と同位置)。 ここで発火すると
    //   【トリガー】 → ターンプレイヤーの反応 → 非ターンプレイヤーの on_life_zero
    //   の順になり、 公式 (cardqa_op_11) と一致する。
    if fire_zero {
        let lcid0 = state.players[opp].leader.card.card_id.clone();
        if crate::effects::card_has_when(&lcid0, "on_life_zero") {
            crate::effects::fire_on_life_zero(state, opp)?;
        }
    }
    Ok(())
}

/// action を state に適用 (副作用)。 Python apply_action ラッパ相当: impl 後に _recompute_static の
/// ownership 部分を反映 (静的効果 eval は R3)。
/// ResolveChoice を解決する。 picks で候補を絞って FORCED_TARGETS に注入し、
/// 中断した primitive を再実行 → 退避した残り do を流す。
fn resolve_choice_action(state: &mut GameState, action: &Value) -> Result<(), String> {
    let Some(pc) = state.pending_choice.take() else { return Ok(()) };
    let picks: Vec<usize> = action
        .get("picks")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|x| x.as_u64().map(|u| u as usize)).collect())
        .unwrap_or_default();
    let chosen: Vec<(usize, crate::effects::Slot)> = picks
        .iter()
        .filter_map(|&i| pc.cand_slots.get(i))
        .map(|&(pi, code)| (pi, crate::effects::code_to_slot(code)))
        .collect();
    let src = crate::effects::code_to_slot(pc.src_slot);
    crate::effects::set_choice_suspended(false);
    // ⭐ 注入先は kind で切り替える:
    //   target 系 (target_pick) → FORCED_TARGETS ((player, Slot) の組)
    //   index 系 (search_top_n 等) → FORCED_PICKS (zone 内の元 index)
    if pc.kind == "target_pick" {
        crate::effects::set_forced_targets(Some(chosen));
    } else {
        let idxs: Vec<usize> = picks
            .iter()
            .filter_map(|&i| pc.cand_slots.get(i))
            .map(|&(_pi, code)| code as usize)
            .collect();
        crate::effects::set_forced_picks(Some(idxs));
    }
    if !crate::effects::execute_effect_pub(&pc.prim, state, pc.me_idx, src) {
        crate::effects::set_forced_targets(None);
        crate::effects::set_forced_picks(None);
        return Err("ResolveChoice: 再実行した primitive が未対応".into());
    }
    crate::effects::set_forced_targets(None);
    crate::effects::set_forced_picks(None);
    // 退避しておいた残り do を流す (再度中断したら再び pending_choice が立つ)
    for (ci, prim) in pc.remaining_do.iter().enumerate() {
        if !crate::effects::execute_effect_pub(prim, state, pc.me_idx, src) {
            return Err("ResolveChoice: 残り do の primitive が未対応".into());
        }
        if crate::effects::suspend_if_choice(state, &pc.remaining_do, ci, prim, src, pc.me_idx) {
            break;
        }
    }
    Ok(())
}

pub fn apply_action(state: &mut GameState, action: &Value) -> Result<(), String> {
    // ⛔ 選択列挙モードは **target_pick のみ** 追従済。 他 kind は未実装なので、
    //   pending_choice が立っていない状態で列挙モードに入るのは まだ許さない…
    //   ではなく、 「未対応の選択サイトに当たったら中で bail する」 方式に移行した。
    //   ⚠ 実装済 kind が増えるまでは env `ONEPIECE_RUST_CHOICE=1` を明示した時だけ通す
    //     (既定は従来どおり全面 bail = 黙って別のゲームを進めない)。
    // ⭐ 選択列挙モードは **site-specific bail** へ移行済:
    //   - target_pick (= resolve_target 経由 21 サイト) は `pick_one_or_suspend` で実装
    //   - 未移植の選択 primitive 35 件 / 複数候補の発動コストは **その場で bail**
    //   なので全面 gate は不要。 「bit 一致 か 明示 bail」 は各サイトが保証する。
    // ⭐ ResolveChoice = 立っている選択を 1 アクションとして解決する (Python と同形)。
    //   picks を FORCED_TARGETS に注入して **その primitive を再実行** し、 続けて
    //   退避しておいた残り do を流す (Rust には continuation が無いので replay 方式)。
    if action.get("t").and_then(|v| v.as_str()) == Some("ResolveChoice") {
        let r = resolve_choice_action(state, action);
        if r.is_ok() {
            recompute_static(state);
            for p in state.players.iter_mut() {
                normalize_known_hand(p);
            }
        }
        return r;
    }
    crate::effects::set_choice_suspended(false);
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
            crate::effects::consume_filtered_turn_reduction(state, me, &card); // 「次に」=1枚 (OP02-025)
            let p = &mut state.players[me];
            let sickness = !card.is_rush();
            p.characters.push(InPlay::of(card.clone(), sickness));
            p.cards_played_count += 1;
            let played_idx = p.characters.len() - 1;
            // trigger_on_play context (Python は on_play 有無に関わらず設定、 effects.py:10640)
            state.last_self_chara_played_card = Some(card);
            state.last_self_chara_played_from_trash = false; // 手札からの登場
            // on_play 効果 + 登場 cascade を fidelity 保証で実行 (未対応は Err で bail = 黙って間違えない)。
            // 通常の登場 (手札からプレイ) は 「キャラの効果による登場」 ではない
            // (cardqa_op_12 / OP12-081)。 transient を必ずリセットしてから発火する
            // (⚠ #[serde(skip)] なので前の効果の値が残る)。
            state.rust_play_source_is_field_chara = false;
            crate::effects::execute_on_play(state, me, played_idx)?;
            Ok(())
        }
        "AttachDonToLeader" => {
            let n = {
                let p = &mut state.players[me];
                let n = (geti(action, "n", 0) as i32).min(p.don_active);
                p.don_active -= n;
                p.leader.attached_dons += n;
                p.dons_used_count += n;
                n
            };
            // 【このリーダーか自分のキャラにドンが付与された時】(game.py、 OP02-002)。
            // ⭐ **付与されたドン 1 枚につき 1 回** 発火 (cardqa_op_02、 2026-08-17 是正)。
            if n > 0 {
                crate::effects::fire_on_self_don_attached_n(state, me, n)?;
            }
            Ok(())
        }
        "AttachDonToCharacter" => {
            let idx = geti(action, "target_idx", -1);
            let n = {
                let p = &mut state.players[me];
                if idx < 0 || idx as usize >= p.characters.len() {
                    return Err(format!("target_idx 範囲外: {idx}"));
                }
                let n = (geti(action, "n", 0) as i32).min(p.don_active);
                p.don_active -= n;
                p.characters[idx as usize].attached_dons += n;
                p.dons_used_count += n;
                n
            };
            if n > 0 {
                crate::effects::fire_on_self_don_attached_n(state, me, n)?;
            }
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
            let counter_events: Vec<i64> = action
                .get("counter_event_idxs")
                .and_then(|v| v.as_array())
                .map(|a| a.iter().filter_map(|x| x.as_i64()).collect())
                .unwrap_or_default();
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
            // アタック時 手札捨てコスト (game.py:1467、 OP08-043 エドワード等)。
            // 「自身の手札 N 枚を捨てなければアタックできない」。 手札不足ならアタック不発 (Ok no-op)。
            // ⚠ Python は state.rng.randrange でランダムに捨てる → Rust も同じ MT 列を消費して再現。
            if cost_discard > 0 {
                // ⚠ Python は「アタック不能」を state 不変の早期 return で表す (game.py:1471) が、
                //   Rust の方策はそれを「何も起きない合法手」と見て選び続け **無限ループ** する。
                //   選択肢から外すため明示 bail にする (state は変えないので誤りは作らない)。
                if (state.players[me].hand.len() as i32) < cost_discard {
                    return Err("attack cost 手札不足 (アタック不能)".into());
                }
                for _ in 0..cost_discard {
                    let n = state.players[me].hand.len() as u64;
                    if n == 0 {
                        break;
                    }
                    let idx = state.rng_mut().randrange(n) as usize;
                    let c = state.players[me].hand.remove(idx);
                    state.players[me].trash.push(c);
                }
            }
            // attacker.rested = true (game.py:1466、 on_attack 発火前)
            if is_leader {
                state.players[me].leader.rested = true;
            } else {
                state.players[me].characters[atk_idx].rested = true;
            }
            // 「このキャラがレストになった時」(on_self_rested): アタック宣言でレスト → 発火
            // (公式 cardqa_op_14 677c149d0045)。 char attacker のみ (leader は on_self_rested
            // を持たない = Python trigger_on_self_rested も no-op)。 自己起因 = by_opp_effect=false。
            if !is_leader {
                let prev_ko_by_opp = state.last_ko_by_opp_effect;
                state.last_ko_by_opp_effect = false;
                let r = crate::effects::fire_on_self_rested_impl(state, me, atk_idx, true);
                state.last_ko_by_opp_effect = prev_ko_by_opp;
                r?;
            }
            // 【アタック時】(on_attack) 発火 (game.py:1467、 costless slice のみ、 未対応は Err で bail)
            // ⚠ on_attack でアタッカー自身が場を離れる (自 trash / 自 KO) ことがある。 Python は
            //   attacker を object 参照で保持して以降も同じ実体を読むが、 Rust は位置 index なので
            //   一意トークンで追跡し、 見失ったら明示 bail (以前はここから先の index 参照で panic)。
            let atk_tok = if is_leader {
                None
            } else {
                crate::effects::tag_src(state, me, crate::effects::Slot::Char(atk_idx))
            };
            let atk_cid_dbg = if is_leader {
                String::new()
            } else {
                state.players[me].characters[atk_idx].card.card_id.clone()
            };
            // target spec "opponent_attacker" / 条件 "opp_attacker_attribute" の参照先
            // (Python は game.py でアタック宣言時に current_attacker_iid を set する。 同じ順)。
            state.current_attacker_tok = crate::effects::tag_src(
                state,
                me,
                if is_leader { crate::effects::Slot::Leader } else { crate::effects::Slot::Char(atk_idx) },
            );
            state.current_attacker_attribute = Some(if is_leader {
                state.players[me].leader.card.attribute.clone()
            } else {
                state.players[me].characters[atk_idx].card.attribute.clone()
            });
            crate::effects::fire_on_attack(state, me, is_leader, atk_idx)?;
            // ⭐ Python は attacker を object 参照で保持するので、 on_attack で自身が場を離れても
            //   そのオブジェクトを読み続けてバトルを解決する。 Rust は fire_gated_do / cost 支払いが
            //   離場直前のスナップショットを state.rust_detached_src に残すので、 それを使う。
            let mut atk_gone: Option<InPlay> = None;
            let atk_idx = if is_leader {
                atk_idx
            } else {
                match crate::effects::find_tagged(state, me, atk_tok) {
                    crate::effects::Slot::Char(i) => i,
                    _ => match state.rust_detached_src.take() {
                        Some(ip) => {
                            atk_gone = Some(ip);
                            usize::MAX
                        }
                        None => {
                            crate::effects::note_unknown_key("atk_lost", &atk_cid_dbg);
                            return Err(
                                "attacker が on_attack 中に場を離れた (スナップショット無し)".into(),
                            );
                        }
                    },
                }
            };

            // 【相手のアタック時】(opp_attack + on_leader) 発火 (game.py:1476、 defended_target=leader)。
            // AI が発動しない (skip) なら一致、 cost effect fire は Err (防御 EV heuristic 移植済)。
            let atk_cost = match &atk_gone {
                Some(g) => g.card.cost,
                None if is_leader => state.players[me].leader.card.cost,
                None => state.players[me].characters[atk_idx].card.cost,
            };
            let ap = match &atk_gone {
                Some(g) => g.power(),
                None if is_leader => state.players[me].leader.power(),
                None => state.players[me].characters[atk_idx].power(),
            };
            let dp = state.players[opp].leader.power();
            // ブロッカー idx を opp_attack 発火**前**に捕捉した card_id と対で保持。 Python は blocker_iid で
            // 安定解決 (game.py:1602) するが、 Rust は canonical に iid が無く位置 idx で解決する。 opp_attack の
            // 【相手のアタック時】(ST24-002 自 trash 等) が defender char を除去/並替すると idx が別 char を指す
            // → 黙って違う blocker をブロックすると MISMATCH。 shift 検知時は明示 bail (iid tracking 不能)。
            let declared_blocker_tok: Option<u64> = action
                .get("blocker")
                .and_then(|b| if b.is_null() { None } else { b.get("idx").and_then(|v| v.as_i64()) })
                .map(|i| i as usize)
                .filter(|&bi| bi < state.players[opp].characters.len())
                .and_then(|bi| crate::effects::tag_src(state, opp, crate::effects::Slot::Char(bi)));
            // ⚠ 【相手のアタック時】は **アタッカー自身を除去しうる** (相手の除去効果)。 その場合も
            //   Python は object 参照でバトルを続行するので、 発火前にスナップショットを退避する。
            let atk_pre_opp: Option<InPlay> = if is_leader {
                None
            } else {
                state.players[me].characters.get(atk_idx).cloned()
            };
            crate::effects::fire_opp_attack(state, opp, "opp_attack", ap, atk_cost, dp)?;
            let dp2 = state.players[opp].leader.power();
            crate::effects::fire_opp_attack(state, opp, "opp_attack_on_leader", ap, atk_cost, dp2)?;
            // opp_attack で defender の盤面が動いても、 タグで宣言ブロッカーの現在位置を取り直す
            // (Python の blocker_iid 解決と等価)。 場から消えていれば「ブロッカー消失」= ブロック無効
            // (game.py:1608)。
            let blocker_now: Option<usize> = declared_blocker_tok.and_then(|tok| {
                match crate::effects::find_tagged(state, opp, Some(tok)) {
                    crate::effects::Slot::Char(i) => Some(i),
                    _ => None,
                }
            });
            // on_attack/opp_attack で power/keyword が変化しうるので attacker を再スナップショット。
            // ⚠ trigger の途中で attacker 自身が場を離れることがある (自 trash / 相手の除去)。 Python は
            //   attacker を **オブジェクト参照** で保持し離場後も同じ実体で解決を続けるが、 Rust は位置
            //   index なので追跡できない → 明示 bail (以前はここで index out of bounds panic していた)。
            let attacker: InPlay = if let Some(g) = &atk_gone {
                g.clone()
            } else if is_leader {
                state.players[me].leader.clone()
            } else {
                match crate::effects::peek_tagged(state, me, state.current_attacker_tok) {
                    crate::effects::Slot::Char(i) => state.players[me].characters[i].clone(),
                    // opp_attack 中に離場した場合は発火前スナップショットで続行する
                    // (Python は object 参照でバトルを継続する)。
                    _ => match atk_pre_opp.clone().or_else(|| state.rust_detached_src.take()) {
                        Some(ip) => ip,
                        None => {
                            return Err(
                                "attacker が on_attack/opp_attack 中に場を離れた (スナップショット無し)"
                                    .into(),
                            )
                        }
                    },
                }
            };
            let atk_power_base = attacker.power();
            let is_double = attacker.is_double_attack_now();
            let is_banish = attacker.is_banish_now();
            let no_block = attacker.has_no_block_now();
            // === アタック対象変更 (game.py:1472): opp_attack の redirect_attack が pending_attack_redirect を set ===
            // Some(char_idx) = 相手キャラへ redirect → char battle 再解決して return。 None = 通常 leader battle。
            // (leader redirect は primitive 側で no-op = None のまま扱う)。
            if let Some(ri) = state.pending_attack_redirect {
                state.pending_attack_redirect = None;
                let ri = ri as usize;
                if ri >= state.players[opp].characters.len() {
                    reset_battle_buffs(state); // target 消失 = 空打ち (game.py:1484)
                    return Ok(());
                }
                // 対象変更先が **キャラ** = リーダーはキャラとバトルした (cardqa_op_12 / OP12-020)
                if is_leader {
                    state.players[me].leader_battled_opp_chara_this_turn = true;
                }
                // カウンターフェイズ: counter events (defender=opp) → counter cards。
                // 公式 (cardqa_st_02): 当事者が場を離れていたら **カウンターステップもスキップ**
                // される (= カウンター札を無駄に消費しない)。 game.py と対。
                if !is_leader
                    && crate::effects::peek_tagged(state, me, state.current_attacker_tok)
                        == crate::effects::Slot::Detached
                {
                    reset_battle_buffs(state);
                    return Ok(());
                }
                crate::effects::fire_counter_events(state, opp, me, &counter_events)?;
                let counter_added = spend_counters(&mut state.players[opp], &counter_cards);
                // 公式 (cardqa_op_01/op_05/op_12/st_02/st_03): カウンターステップ終了時に
                // **アタックしているキャラが場に存在しない場合、 ダメージステップには移行せず
                // バトルは終了する**。 2026-08-04 まで両エンジンとも object 参照 / スナップショットで
                // バトルを続行していた (= 差分では見えない共有バグ)。 Python game.py:_battle_aborted と対。
                if !is_leader
                    && crate::effects::peek_tagged(state, me, state.current_attacker_tok)
                        == crate::effects::Slot::Detached
                {
                    reset_battle_buffs(state);
                    return Ok(());
                }
                if ri >= state.players[opp].characters.len() {
                    reset_battle_buffs(state);
                    return Ok(());
                }
                // battle: Python redirect は attr bonus 無し (game.py:1502/1520)。 免疫 = ko_immune/属性のみ。
                let atk_power = attacker.power();
                let (def_power, immune) = {
                    let t = &state.players[opp].characters[ri];
                    (
                        t.power() + counter_added,
                        t.ko_immune_until_turn_end || battle_ko_immune_by_attribute(t, &attacker),
                    )
                };
                if atk_power >= def_power && !immune {
                    do_battle_ko(state, opp, ri, me, &atk_cid, true, Some(if is_leader { crate::effects::Slot::Leader } else { crate::effects::Slot::Char(atk_idx) }))?;
                }
                reset_battle_buffs(state);
                return Ok(());
            }
            // === ブロックステップ (7-1-2) ===
            let blocker_idx: Option<usize> = if no_block { None } else { blocker_now };
            let mut is_blocked = false;
            let mut blk_idx = 0usize;
            if let Some(bi) = blocker_idx {
                // ブロッカーは **キャラ** なので、 リーダーのアタックなら 「キャラとバトル」
                // (cardqa_op_12 / OP12-020。 Python game.py の actual_target = blocker と同位置)。
                if is_leader && bi < state.players[opp].characters.len() {
                    state.players[me].leader_battled_opp_chara_this_turn = true;
                }
                let valid = bi < state.players[opp].characters.len() && {
                    let b = &state.players[opp].characters[bi];
                    !b.rested && b.is_blocker_now() && !b.blocker_disabled_until_turn_end
                        // 公式: 「レストにできない」 は【ブロッカー】の発動も止める
                        // (レストにすることが必要な行動だから)。 game.py と対。
                        && !b.cannot_be_rested_buff && !b.static_cannot_be_rested
                };
                if valid {
                    let bcid = state.players[opp].characters[bi].card.card_id.clone();
                    state.players[opp].characters[bi].rested = true;
                    is_blocked = true;
                    blk_idx = bi;
                    // 公式: 同時発動の誘発は **ターンプレイヤー先** (game.py:1685 と対)。
                    //   ① attacker (= ターンプレイヤー, me) の【相手がブロッカー発動時】
                    //      (on_opp_blocker_use、 OP09-118 等) → ② blocker (= 非ターンプレイヤー,
                    //      opp) の【ブロック時】(on_block、 source=blocker slot)。
                    //   cardqa_op_09: ロジャーの勝利判定が しのぶの【ブロック時】より先に解決 →
                    //   その時点で相手ライフ 1 枚 = 勝利しない。 是正前は on_block 先で誤って勝利
                    //   していた (= Python/Rust 共有バグ)。
                    crate::effects::fire_field_when(state, me, "on_opp_blocker_use")?;
                    if crate::effects::card_has_when(&bcid, "on_block") {
                        crate::effects::execute_card_effects(
                            state, opp, &bcid, "on_block", crate::effects::Slot::Char(bi),
                        )?;
                    }
                    // game.py:1632 fizzle: blocker が【ブロック時】等で場から消えた → アタック不発。
                    // (Rust は iid 無しなので slot 位置 + card_id 一致で blocker 残存を近似。 win_game で
                    //  game_over でも Python は battle を継続する = 早期 return しない。)
                    if bi >= state.players[opp].characters.len()
                        || state.players[opp].characters[bi].card.card_id != bcid
                    {
                        reset_battle_buffs(state);
                        return Ok(());
                    }
                }
                // 不正ブロッカーは無視 = リーダーへ続行 (game.py:1591-1605)
            }
            // === カウンターフェイズ (7-1-3): counter events → counter cards ===
            // 公式 (cardqa_st_02): 当事者が場を離れていたら **カウンターステップもスキップ**
            // される (= カウンター札を無駄に消費しない)。 game.py と対。
            if !is_leader
                && crate::effects::peek_tagged(state, me, state.current_attacker_tok)
                    == crate::effects::Slot::Detached
            {
                reset_battle_buffs(state);
                return Ok(());
            }
            crate::effects::fire_counter_events(state, opp, me, &counter_events)?;
            let counter_added = spend_counters(&mut state.players[opp], &counter_cards);
            // 公式 (cardqa_op_01/op_05/op_12/st_02/st_03): カウンターステップ終了時に
            // **アタックしているキャラが場に存在しない場合、 ダメージステップには移行せず
            // バトルは終了する**。 2026-08-04 まで両エンジンとも object 参照 / スナップショットで
            // バトルを続行していた (= 差分では見えない共有バグ)。 Python game.py:_battle_aborted と対。
            if !is_leader
                && crate::effects::peek_tagged(state, me, state.current_attacker_tok) == crate::effects::Slot::Detached
            {
                reset_battle_buffs(state);
                return Ok(());
            }
            if is_blocked && blk_idx >= state.players[opp].characters.len() {
                reset_battle_buffs(state);
                return Ok(());
            }

            if is_blocked {
                // ブロッカー vs アタッカー (勝てば blocker KO、 負ければ生存、 リーダーへの damage 無)
                if !attacker.battle_pump_vs_attribute.is_empty()
                    || !state.players[opp].characters[blk_idx].battle_pump_vs_attribute.is_empty()
                {
                    // 「属性X とバトルする時、 このターン中 +N」 は turn_buff への **累積**
                    // (Python _apply_battle_attr_pump)。 Rust 未追従 → 明示 bail。
                    return Err("battle_pump_vs_attribute の turn 累積は Rust 未実装".into());
                }
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
                    // EB02-030 の バトルKO 代替救済 (per-InPlay) は do_battle_ko 内で判定 (両経路統一)。
                    do_battle_ko(state, opp, blk_idx, me, &atk_cid, true, Some(if is_leader { crate::effects::Slot::Leader } else { crate::effects::Slot::Char(atk_idx) }))?;
                }
                reset_battle_buffs(state);
                return Ok(());
            }

            // === 非ブロック: リーダーへのダメージ (leader へは attr bonus 無) ===
            let def_power = state.players[opp].leader.power() + counter_added;
            if atk_power_base >= def_power {
                let damage = if is_double { 2 } else { 1 };
                if state.players[opp].life.is_empty() {
                    // ライフ 0 トリガー (game.py:1760、 OP05-098 紫エネル等「デッキ上 1 枚をライフへ」)。
                    // 先に発火させ、 **それでもまだ 0 なら** 敗北宣言 (回復すれば試合続行)。
                    // src = 相手リーダー (Python も source_iid=leader.instance_id)。
                    let lcid = state.players[opp].leader.card.card_id.clone();
                    if crate::effects::card_has_when(&lcid, "on_life_zero") {
                        crate::effects::fire_on_life_zero(state, opp)?;
                    }
                    if state.players[opp].life.is_empty() {
                        // 敗北宣言 (game.py:1765 は reset_battle_buffs せず return)
                        declare_winner(state, me);
                        return Ok(());
                    }
                }
                // per-hit 処理 (Python _resolve_life_taken)。 トリガー発火は board を変えうるので hit ごとに
                // should_fire を再評価 (一括 pre-check 不可)。 発火は fire_life_trigger (source-gone 安全 subset、
                // 未対応 trigger は Err bail)。 発火成立で kept_in_hand=false → trash、 不発 → hand。
                for hit_i in 0..damage {
                    if state.players[opp].life.is_empty() {
                        break;
                    }
                    resolve_life_taken(state, me, opp, is_banish, false, hit_i == 0)?;
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
            let counter_events: Vec<i64> = action
                .get("counter_event_idxs")
                .and_then(|v| v.as_array())
                .map(|a| a.iter().filter_map(|x| x.as_i64()).collect())
                .unwrap_or_default();
            let attacker_exists = match atk_kind {
                "leader" => true,
                "char" => atk_idx < state.players[me].characters.len(),
                _ => return Err("bad attacker".into()),
            };
            if !attacker_exists {
                return Ok(());
            }
            let is_leader = atk_kind == "leader";
            let (atk_cid, cost_discard, _ret_at_battle_end) = {
                let a = if is_leader { &state.players[me].leader } else { &state.players[me].characters[atk_idx] };
                (a.card.card_id.clone(), a.attack_cost_discard_hand_n, a.return_to_deck_bottom_at_battle_end)
            };
            // アタック時 手札捨てコスト (game.py:1467、 OP08-043 エドワード等)。
            // 「自身の手札 N 枚を捨てなければアタックできない」。 手札不足ならアタック不発 (Ok no-op)。
            // ⚠ Python は state.rng.randrange でランダムに捨てる → Rust も同じ MT 列を消費して再現。
            if cost_discard > 0 {
                // ⚠ Python は「アタック不能」を state 不変の早期 return で表す (game.py:1471) が、
                //   Rust の方策はそれを「何も起きない合法手」と見て選び続け **無限ループ** する。
                //   選択肢から外すため明示 bail にする (state は変えないので誤りは作らない)。
                if (state.players[me].hand.len() as i32) < cost_discard {
                    return Err("attack cost 手札不足 (アタック不能)".into());
                }
                for _ in 0..cost_discard {
                    let n = state.players[me].hand.len() as u64;
                    if n == 0 {
                        break;
                    }
                    let idx = state.rng_mut().randrange(n) as usize;
                    let c = state.players[me].hand.remove(idx);
                    state.players[me].trash.push(c);
                }
            }
            // attacker.rested = true (game.py:1833、 on_attack 発火前、 target-check より先)
            if is_leader {
                state.players[me].leader.rested = true;
            } else {
                state.players[me].characters[atk_idx].rested = true;
            }
            // 「このキャラがレストになった時」(on_self_rested): アタック宣言でレスト → 発火
            // (公式 cardqa_op_14 677c149d0045)。 char attacker のみ、 自己起因 = by_opp_effect=false。
            if !is_leader {
                let prev_ko_by_opp = state.last_ko_by_opp_effect;
                state.last_ko_by_opp_effect = false;
                let r = crate::effects::fire_on_self_rested_impl(state, me, atk_idx, true);
                state.last_ko_by_opp_effect = prev_ko_by_opp;
                r?;
            }
            // 【アタック時】(on_attack) 発火 (costless slice のみ、 未対応は Err)
            // ⚠ on_attack でアタッカー自身が場を離れる (自 trash / 自 KO) ことがある。 Python は
            //   attacker を object 参照で保持して以降も同じ実体を読むが、 Rust は位置 index なので
            //   一意トークンで追跡し、 見失ったら明示 bail (以前はここから先の index 参照で panic)。
            let atk_tok = if is_leader {
                None
            } else {
                crate::effects::tag_src(state, me, crate::effects::Slot::Char(atk_idx))
            };
            // ⭐ アタック **対象** も一意トークンで追う。 Python は target を object 参照で持つので
            //   【アタック時】が対象を KO したら 「対象消失 = 空打ち」 になる。 Rust は位置 index の
            //   **長さ** しか見ておらず、 後ろのキャラが繰り上がって **別のキャラを殴っていた**
            //   (OP15-036 が OP15-050 を KO → shift した OP15-051 とバトル、 2026-08-04 掃引で発覚)。
            //   memory の 「iid vs 位置 idx」 = 深い MISMATCH 3 クラスの 1 つ。
            let tgt_tok = if tgt_idx >= 0 && (tgt_idx as usize) < state.players[opp].characters.len()
            {
                crate::effects::tag_src(state, opp, crate::effects::Slot::Char(tgt_idx as usize))
            } else {
                None
            };
            let atk_cid_dbg = if is_leader {
                String::new()
            } else {
                state.players[me].characters[atk_idx].card.card_id.clone()
            };
            // target spec "opponent_attacker" / 条件 "opp_attacker_attribute" の参照先
            // (Python は game.py でアタック宣言時に current_attacker_iid を set する。 同じ順)。
            state.current_attacker_tok = crate::effects::tag_src(
                state,
                me,
                if is_leader { crate::effects::Slot::Leader } else { crate::effects::Slot::Char(atk_idx) },
            );
            state.current_attacker_attribute = Some(if is_leader {
                state.players[me].leader.card.attribute.clone()
            } else {
                state.players[me].characters[atk_idx].card.attribute.clone()
            });
            crate::effects::fire_on_attack(state, me, is_leader, atk_idx)?;
            // ⭐ Python は attacker を object 参照で保持するので、 on_attack で自身が場を離れても
            //   そのオブジェクトを読み続けてバトルを解決する。 Rust は fire_gated_do / cost 支払いが
            //   離場直前のスナップショットを state.rust_detached_src に残すので、 それを使う。
            let mut atk_gone: Option<InPlay> = None;
            let atk_idx = if is_leader {
                atk_idx
            } else {
                match crate::effects::find_tagged(state, me, atk_tok) {
                    crate::effects::Slot::Char(i) => i,
                    _ => match state.rust_detached_src.take() {
                        Some(ip) => {
                            atk_gone = Some(ip);
                            usize::MAX
                        }
                        None => {
                            crate::effects::note_unknown_key("atk_lost", &atk_cid_dbg);
                            return Err(
                                "attacker が on_attack 中に場を離れた (スナップショット無し)".into(),
                            );
                        }
                    },
                }
            };

            // 【相手のアタック時】(opp_attack + on_chara) 発火 (game.py:1843、 defended_target=対象キャラ)。
            // target 消失時 (= 通常起きない、 fire は bail) は defended_power=0 で扱う。
            let atk_cost = match &atk_gone {
                Some(g) => g.card.cost,
                None if is_leader => state.players[me].leader.card.cost,
                None => state.players[me].characters[atk_idx].card.cost,
            };
            let ap = match &atk_gone {
                Some(g) => g.power(),
                None if is_leader => state.players[me].leader.power(),
                None => state.players[me].characters[atk_idx].power(),
            };
            // ⚠ tgt_idx は on_attack で盤面が動くと stale。 常にタグから引き直す。
            let cur_tgt = |st: &GameState| -> i64 {
                match crate::effects::peek_tagged(st, opp, tgt_tok) {
                    crate::effects::Slot::Char(i) => i as i64,
                    _ => -1,
                }
            };
            let dp = match cur_tgt(state) {
                i if i >= 0 => state.players[opp].characters[i as usize].power(),
                _ => 0,
            };
            // 【相手のアタック時】がアタッカー自身を除去しうる → 発火前スナップショットを退避。
            let atk_pre_opp: Option<InPlay> = if is_leader {
                None
            } else {
                state.players[me].characters.get(atk_idx).cloned()
            };
            crate::effects::fire_opp_attack(state, opp, "opp_attack", ap, atk_cost, dp)?;
            let dp2 = match cur_tgt(state) {
                i if i >= 0 => state.players[opp].characters[i as usize].power(),
                _ => 0,
            };
            crate::effects::fire_opp_attack(state, opp, "opp_attack_on_chara", ap, atk_cost, dp2)?;
            // target 存在チェック (on_attack/opp_attack 後、 消失 = 空打ち = reset+Ok、 game.py:1849)。
            // ⚠ 「長さ」 ではなく **タグ** で見る。 対象が KO されて後ろが繰り上がると
            //   index は生きたままなので、 長さ判定だと別のキャラを殴ってしまう。
            let tgt_idx = cur_tgt(state);
            if tgt_idx < 0 {
                reset_battle_buffs(state);
                return Ok(());
            }
            // on_attack で power/keyword が変化しうるので再スナップショット。
            // ⚠ AttackLeader 側と同じく、 trigger 中に attacker が場を離れると index が無効 → 明示 bail。
            let attacker: InPlay = if let Some(g) = &atk_gone {
                g.clone()
            } else if is_leader {
                state.players[me].leader.clone()
            } else {
                match crate::effects::peek_tagged(state, me, state.current_attacker_tok) {
                    crate::effects::Slot::Char(i) => state.players[me].characters[i].clone(),
                    // opp_attack 中に離場 → 発火前スナップショットで継続 (Python は object 参照)。
                    _ => match atk_pre_opp.clone().or_else(|| state.rust_detached_src.take()) {
                        Some(ip) => ip,
                        None => {
                            return Err(
                                "attacker が on_attack 中に場を離れた (スナップショット無し)".into(),
                            )
                        }
                    },
                }
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
                        // 公式: 「レストにできない」 は【ブロッカー】の発動も止める
                        // (レストにすることが必要な行動だから)。 game.py と対。
                        && !b.cannot_be_rested_buff && !b.static_cannot_be_rested
                };
                if valid {
                    let bcid = state.players[opp].characters[bi].card.card_id.clone();
                    state.players[opp].characters[bi].rested = true;
                    actual_idx = bi;
                    // AttackCharacter は【ブロック時】(on_block) のみ発火 (on_opp_blocker_use は非対称で不発火、
                    //   game.py:1895)。 ⚠ Python は fizzle return せず actual_target=blocker (object ref) 継続。
                    if crate::effects::card_has_when(&bcid, "on_block") {
                        // on_block で盤面が動いてもブロッカーを見失わないようタグで追う。
                        let btok = crate::effects::tag_src(state, opp, crate::effects::Slot::Char(bi));
                        crate::effects::execute_card_effects(
                            state, opp, &bcid, "on_block", crate::effects::Slot::Char(bi),
                        )?;
                        match crate::effects::find_tagged(state, opp, btok) {
                            crate::effects::Slot::Char(i) => actual_idx = i,
                            // 場を離れた = Python は object-ref を保持して battle を続けるが、
                            // 盤面に居ないので Rust では再現不能 → 明示 bail。
                            _ => {
                                return Err(
                                    "on_block で blocker 消失 (AttackChar object-ref 再現不能)".into(),
                                )
                            }
                        }
                    }
                }
            }
            // リーダーが **キャラ** とバトルする局面を記録 (cardqa_op_12 / OP12-020、
            // Python game.py の Pre-counter snapshot と同位置)。
            if is_leader {
                state.players[me].leader_battled_opp_chara_this_turn = true;
            }
            // === カウンター: counter events → counter cards ===
            // ⚠ 【カウンター】イベントが盤面を動かす (KO / バウンス) と actual_idx が stale になる。
            //   タグで追い、 消えていたら bail (Python は object-ref でバトルを続けるが index では不能)。
            let act_tok = crate::effects::tag_src(state, opp, crate::effects::Slot::Char(actual_idx));
            // 公式 (cardqa_st_02): 当事者が場を離れていたら **カウンターステップもスキップ**
            // される (= カウンター札を無駄に消費しない)。 game.py と対。
            if !is_leader
                && crate::effects::peek_tagged(state, me, state.current_attacker_tok)
                    == crate::effects::Slot::Detached
            {
                reset_battle_buffs(state);
                return Ok(());
            }
            crate::effects::fire_counter_events(state, opp, me, &counter_events)?;
            // 公式: カウンターで対象が場を離れたら **バトル中断** (ダメージステップに移行しない)。
            // 以前は 「object-ref 再現不能」 として bail していたが、 公式どおり中断が正しい。
            actual_idx = match crate::effects::find_tagged(state, opp, act_tok) {
                crate::effects::Slot::Char(i) => i,
                _ => {
                    reset_battle_buffs(state);
                    return Ok(());
                }
            };
            let counter_added = spend_counters(&mut state.players[opp], &counter_cards);
            // 公式 (cardqa_op_01/op_05/op_12/st_02/st_03): カウンターステップ終了時に
            // **アタックしているキャラが場に存在しない場合、 ダメージステップには移行せず
            // バトルは終了する**。 2026-08-04 まで両エンジンとも object 参照 / スナップショットで
            // バトルを続行していた (= 差分では見えない共有バグ)。 Python game.py:_battle_aborted と対。
            if !is_leader
                && crate::effects::peek_tagged(state, me, state.current_attacker_tok) == crate::effects::Slot::Detached
            {
                reset_battle_buffs(state);
                return Ok(());
            }
            // === バトル解決 (attr bonus 両方向) ===
            if !attacker.battle_pump_vs_attribute.is_empty()
                || !state.players[opp].characters[actual_idx].battle_pump_vs_attribute.is_empty()
            {
                return Err("battle_pump_vs_attribute の turn 累積は Rust 未実装".into());
            }
            let (atk_power, def_power, immune) = {
                let target = &state.players[opp].characters[actual_idx];
                let ap = attacker.power() + battle_attr_bonus(&attacker, target);
                let dp = target.power() + counter_added + battle_attr_bonus(target, &attacker);
                let imm = target.ko_immune_until_turn_end || battle_ko_immune_by_attribute(target, &attacker);
                (ap, dp, imm)
            };
            if atk_power >= def_power && !immune {
                do_battle_ko(state, opp, actual_idx, me, &atk_cid, false, None)?;
            }
            // バトルした相手キャラを記録 (game.py:2009 `last_battled_opp_iid`、 条件
            // opp_just_battled_* / target spec opp_just_battled 用)。
            state.last_battled_opp = Some((opp, actual_idx));
            // バトル終了時: 【このキャラがバトルした時】(on_self_battled、 game.py:2006、 ST02-010)。
            // AttackCharacter は常に char vs char バトルなので成立時は必ず発火。 attacker が場に
            // 残っている場合のみ (Python の `attacker in [me.leader, *me.characters]`)。
            if crate::effects::card_has_when(&atk_cid, "on_self_battled") {
                let cur = crate::effects::peek_tagged(state, me, state.current_attacker_tok);
                let cur = if is_leader { crate::effects::Slot::Leader } else { cur };
                if cur != crate::effects::Slot::Detached {
                    crate::effects::fire_on_self_battled(state, me, &atk_cid, cur)?;
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
            crate::effects::fire_activate_main(state, me, &cid, effect_index, source_kind, source_idx)?;
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
            crate::effects::consume_filtered_turn_reduction(state, me, &card); // 「次に」=1枚 (OP02-025)
            let p = &mut state.players[me];
            let card_id = card.card_id.clone();
            let ccost = card.cost;
            p.trash.push(card);
            p.cards_played_count += 1;
            p.max_event_cost_this_turn = p.max_event_cost_this_turn.max(ccost);
            crate::effects::execute_main_event(state, me, &card_id)?;
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
            crate::effects::consume_filtered_turn_reduction(state, me, &card); // 「次に」=1枚 (OP02-025)
            let p = &mut state.players[me];
            p.stages.push(InPlay::of(card.clone(), false)); // stage は召喚酔い無
            p.cards_played_count += 1;
            let played_idx = p.stages.len() - 1;
            // trigger_on_play context (effects.py:10640、 stage も trigger_on_play を通る)
            state.last_self_chara_played_card = Some(card.clone());
            state.last_self_chara_played_from_trash = false;
            // 通常のステージ登場も 「キャラの効果による登場」 ではない (cardqa_op_12)。
            state.rust_play_source_is_field_chara = false;
            // stage の on_play 効果 (未対応 primitive は diverge)
            crate::effects::execute_stage_on_play(state, me, played_idx)?;
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
