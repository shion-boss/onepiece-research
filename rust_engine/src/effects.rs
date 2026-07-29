//! 効果システム (Rust)。 engine/effects.py のミラー (Phase R3)。
//!
//! まず静的効果 (evaluate_static_effects = on_attached_don 系) を移植。 fidelity 原則:
//! **完全に理解できる効果だけ適用、 未知の条件/target/primitive は skip** (= 誤適用ゼロ)。
//! → 全 primitive/条件/target が既知のカードのみ Python と一致。 未対応カードは diverge (差分テストが境界)。

use crate::state::{Category, GameState, InPlay, Player};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::OnceLock;

static OVERLAY: OnceLock<HashMap<String, Vec<Value>>> = OnceLock::new();

/// db/card_effects.json を読み込む (Rust が静的効果評価に使う)。
pub fn load_overlay(json_str: &str) -> Result<(), String> {
    if OVERLAY.get().is_some() {
        return Ok(());
    }
    let raw: HashMap<String, Value> = serde_json::from_str(json_str).map_err(|e| e.to_string())?;
    let mut map = HashMap::new();
    for (cid, v) in raw {
        map.insert(cid, v.as_array().cloned().unwrap_or_default());
    }
    let _ = OVERLAY.set(map);
    Ok(())
}

fn overlay() -> Option<&'static HashMap<String, Vec<Value>>> {
    OVERLAY.get()
}

#[derive(Clone, Copy)]
enum Slot {
    Leader,
    Char(usize),
    Stage(usize),
}

fn get_ip(p: &Player, s: Slot) -> &InPlay {
    match s {
        Slot::Leader => &p.leader,
        Slot::Char(i) => &p.characters[i],
        Slot::Stage(i) => &p.stages[i],
    }
}
fn get_ip_mut(p: &mut Player, s: Slot) -> &mut InPlay {
    match s {
        Slot::Leader => &mut p.leader,
        Slot::Char(i) => &mut p.characters[i],
        Slot::Stage(i) => &mut p.stages[i],
    }
}

fn as_i(v: Option<&Value>, d: i64) -> i64 {
    v.and_then(|x| x.as_i64()).unwrap_or(d)
}
fn as_s<'a>(v: Option<&'a Value>, d: &'a str) -> &'a str {
    v.and_then(|x| x.as_str()).unwrap_or(d)
}

/// 条件評価。 Some(bool)=全キー既知、 None=未知キーあり (→ 呼出側は effect を skip)。
fn eval_condition(cond: &Value, state: &GameState, me_idx: usize) -> Option<bool> {
    let obj = match cond.as_object() {
        Some(o) => o,
        None => return Some(true),
    };
    let me = &state.players[me_idx];
    let opp = &state.players[1 - me_idx];
    let total_don = |p: &Player| (p.don_active + p.don_rested) as i64;
    let mut result = true;
    for (k, v) in obj {
        let ok = match k.as_str() {
            "opp_turn" => (state.turn_player_idx != me_idx) == v.as_bool().unwrap_or(true),
            "self_turn" => (state.turn_player_idx == me_idx) == v.as_bool().unwrap_or(true),
            "leader_feature" => me.leader.card.features.iter().any(|f| f == v.as_str().unwrap_or("")),
            "leader_features_any" => v.as_array().map_or(false, |arr| {
                arr.iter().any(|x| me.leader.card.features.iter().any(|f| Some(f.as_str()) == x.as_str()))
            }),
            "leader_name" => me.leader.card.name == v.as_str().unwrap_or(""),
            "leader_color" => {
                let val = v.as_str().unwrap_or("");
                if val == "多色" {
                    me.leader.card.color.len() >= 2
                } else {
                    me.leader.card.color.iter().any(|c| c == val)
                }
            }
            "leader_attribute" | "self_leader_attribute" => me.leader.card.attribute == v.as_str().unwrap_or(""),
            "opp_leader_attribute" => opp.leader.card.attribute == v.as_str().unwrap_or(""),
            "self_life_le" => (me.life.len() as i64) <= v.as_i64().unwrap_or(0),
            "self_life_ge" => (me.life.len() as i64) >= v.as_i64().unwrap_or(0),
            "opp_life_le" => (opp.life.len() as i64) <= v.as_i64().unwrap_or(0),
            "opp_life_ge" => (opp.life.len() as i64) >= v.as_i64().unwrap_or(0),
            "self_don_le" => total_don(me) <= v.as_i64().unwrap_or(0),
            "self_don_ge" => total_don(me) >= v.as_i64().unwrap_or(0),
            "self_don_active_ge" => (me.don_active as i64) >= v.as_i64().unwrap_or(0),
            "self_don_active_eq" => (me.don_active as i64) == v.as_i64().unwrap_or(0),
            "self_hand_count_le" => (me.hand.len() as i64) <= v.as_i64().unwrap_or(0),
            "self_hand_count_ge" => (me.hand.len() as i64) >= v.as_i64().unwrap_or(0),
            "self_field_count_ge" | "self_chara_count_ge" => (me.characters.len() as i64) >= v.as_i64().unwrap_or(0),
            "opp_don_count_ge" => total_don(opp) >= v.as_i64().unwrap_or(0),
            "self_trash_count_ge" => (me.trash.len() as i64) >= v.as_i64().unwrap_or(0),
            "self_trash_count_le" => (me.trash.len() as i64) <= v.as_i64().unwrap_or(0),
            "self_trash_event_count_ge" => {
                (me.trash.iter().filter(|c| c.category == Category::Event).count() as i64) >= v.as_i64().unwrap_or(0)
            }
            "self_trash_event_count_le" => {
                (me.trash.iter().filter(|c| c.category == Category::Event).count() as i64) <= v.as_i64().unwrap_or(0)
            }
            "self_trash_chara_count_ge" => {
                (me.trash.iter().filter(|c| c.category == Category::Character).count() as i64) >= v.as_i64().unwrap_or(0)
            }
            "not" => match eval_condition(v, state, me_idx) {
                Some(b) => !b,
                None => return None,
            },
            "or" => {
                let Some(arr) = v.as_array() else { return None };
                let mut any = false;
                for c in arr {
                    match eval_condition(c, state, me_idx) {
                        Some(true) => any = true,
                        Some(false) => {}
                        None => return None,
                    }
                }
                any
            }
            "and" => {
                let Some(arr) = v.as_array() else { return None };
                let mut all = true;
                for c in arr {
                    match eval_condition(c, state, me_idx) {
                        Some(true) => {}
                        Some(false) => all = false,
                        None => return None,
                    }
                }
                all
            }
            _ => return None, // 未知条件キー → 評価不能 → skip
        };
        if !ok {
            result = false;
        }
    }
    Some(result)
}

/// effect の "if" (単一 dict) + "conditions" (dict の list) を AND 評価 (Python eval_all_conditions 相当)。
fn eval_effect_conditions(eff: &Value, state: &GameState, me_idx: usize) -> Option<bool> {
    if let Some(cond) = eff.get("if") {
        match eval_condition(cond, state, me_idx) {
            Some(true) => {}
            Some(false) => return Some(false),
            None => return None,
        }
    }
    if let Some(conds) = eff.get("conditions").and_then(|v| v.as_array()) {
        for c in conds {
            match eval_condition(c, state, me_idx) {
                Some(true) => {}
                Some(false) => return Some(false),
                None => return None,
            }
        }
    }
    Some(true)
}

/// target spec → 対象 (player_idx, Slot) のリスト。 None=未知 target (→ primitive skip)。
fn resolve_target(
    spec: Option<&Value>,
    me_idx: usize,
    opp_idx: usize,
    src: Slot,
    state: &GameState,
) -> Option<Vec<(usize, Slot)>> {
    let s = match spec {
        Some(v) if v.is_string() => v.as_str().unwrap().to_string(),
        None => "self".to_string(),
        Some(v) => {
            // {"type": "all_self_chara_filtered", "filter": {...}}
            let t = v.get("type").and_then(|x| x.as_str()).unwrap_or("");
            if t == "all_self_chara_filtered" {
                let filt = v.get("filter");
                let p = &state.players[me_idx];
                let mut out = vec![];
                for (i, c) in p.characters.iter().enumerate() {
                    if matches_filter(&c.card, filt) {
                        out.push((me_idx, Slot::Char(i)));
                    }
                }
                return Some(out);
            }
            if t == "all_self_chara_named" {
                let name = v.get("name").and_then(|x| x.as_str()).unwrap_or("");
                let p = &state.players[me_idx];
                return Some(
                    (0..p.characters.len())
                        .filter(|&i| p.characters[i].card.name == name)
                        .map(|i| (me_idx, Slot::Char(i)))
                        .collect(),
                );
            }
            return None;
        }
    };
    let out = match s.as_str() {
        "self" | "self_inplay" => vec![(me_idx, src)],
        "self_leader" => vec![(me_idx, Slot::Leader)],
        "all_self_characters" => (0..state.players[me_idx].characters.len())
            .map(|i| (me_idx, Slot::Char(i)))
            .collect(),
        "all_self_team" => {
            let mut v = vec![(me_idx, Slot::Leader)];
            v.extend((0..state.players[me_idx].characters.len()).map(|i| (me_idx, Slot::Char(i))));
            v
        }
        "all_opp_characters" | "all_opponent_characters" => (0..state.players[opp_idx].characters.len())
            .map(|i| (opp_idx, Slot::Char(i)))
            .collect(),
        _ => return None,
    };
    Some(out)
}

fn matches_filter(card: &crate::state::CardDef, filt: Option<&Value>) -> bool {
    let Some(f) = filt.and_then(|x| x.as_object()) else { return true };
    for (k, v) in f {
        let ok = match k.as_str() {
            "feature" => card.features.iter().any(|x| Some(x.as_str()) == v.as_str()),
            "color" => card.color.iter().any(|x| Some(x.as_str()) == v.as_str()),
            "attribute" => Some(card.attribute.as_str()) == v.as_str(),
            "cost_le" => (card.cost as i64) <= v.as_i64().unwrap_or(0),
            "cost_ge" => (card.cost as i64) >= v.as_i64().unwrap_or(0),
            _ => return false, // 未知 filter キー → 不一致扱い (安全側)
        };
        if !ok {
            return false;
        }
    }
    true
}

/// 静的 primitive を適用。 未知 primitive/target は skip (誤適用ゼロ)。
fn apply_static_primitive(prim: &Value, state: &mut GameState, me_idx: usize, src: Slot) {
    let opp_idx = 1 - me_idx;
    let Some((key, spec)) = prim.as_object().and_then(|o| o.iter().next()) else { return };
    match key.as_str() {
        "power_pump" => {
            // 静的 context では duration は static 強制 (effects.py:10783) → static_buff += amount。
            let mut amount = as_i(spec.get("amount"), 0) as i32;
            if let Some(ap) = spec.get("amount_per") {
                let source = ap.get("source").and_then(|v| v.as_str()).unwrap_or("");
                let mult = as_i(ap.get("multiplier"), 1000) as i32;
                let divisor = as_i(ap.get("divisor"), 1).max(1) as i32;
                let me = &state.players[me_idx];
                let opp = &state.players[opp_idx];
                let atk = |p: &Player| p.leader.attached_dons + p.characters.iter().map(|c| c.attached_dons).sum::<i32>();
                let src_val: i32 = match source {
                    "self_don_rest" => me.don_rested,
                    "self_don_active" => me.don_active,
                    "self_don_total" => me.don_active + me.don_rested + atk(me),
                    "self_field_count" => me.characters.len() as i32,
                    "self_hand_count" => me.hand.len() as i32,
                    "self_trash_count" => me.trash.len() as i32,
                    "self_trash_event_count" => me.trash.iter().filter(|c| c.category == Category::Event).count() as i32,
                    "self_trash_chara_count" => me.trash.iter().filter(|c| c.category == Category::Character).count() as i32,
                    "self_chara_feature_count" => {
                        let feat = ap.get("feature").and_then(|v| v.as_str()).unwrap_or("");
                        me.characters.iter().filter(|c| c.card.features.iter().any(|f| f == feat)).count() as i32
                    }
                    "self_distinct_chara_name_count" => {
                        me.characters.iter().map(|c| c.card.name.clone()).collect::<std::collections::BTreeSet<_>>().len() as i32
                    }
                    "opp_don_total" => opp.don_active + opp.don_rested + atk(opp),
                    _ => return, // 未知 source → skip
                };
                amount += (src_val / divisor) * mult;
            }
            let ff = spec.get("feature_filter").and_then(|v| v.as_str()).map(|s| s.to_string());
            let Some(targets) = resolve_target(spec.get("target"), me_idx, opp_idx, src, state) else { return };
            for (pi, sl) in targets {
                if let Some(f) = &ff {
                    if !get_ip(&state.players[pi], sl).card.features.iter().any(|x| x == f) {
                        continue;
                    }
                }
                get_ip_mut(&mut state.players[pi], sl).static_buff += amount;
            }
        }
        "give_keyword" => {
            let kw = as_s(spec.get("keyword"), "").to_string();
            let Some(targets) = resolve_target(spec.get("target"), me_idx, opp_idx, src, state) else { return };
            if kw.is_empty() {
                return;
            }
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).static_granted_keywords.insert(kw.clone());
            }
        }
        "set_ko_immune" => {
            let tspec = if spec.is_string() || spec.is_object() { Some(spec) } else { None };
            let Some(targets) = resolve_target(tspec, me_idx, opp_idx, src, state) else { return };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).static_ko_immune = true;
            }
        }
        "set_base_power" => {
            let amount = as_i(spec.get("amount"), 0) as i32;
            let Some(targets) = resolve_target(spec.get("target"), me_idx, opp_idx, src, state) else { return };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).base_power_override = Some(amount);
            }
        }
        // 元々のパワーを duration 付きで上書き (effects.py:4673)。 静的 context では duration="static"→base_power_override。
        "set_base_power_timed" => {
            let amount = as_i(spec.get("amount"), 0) as i32;
            let duration = spec.get("duration").and_then(|v| v.as_str()).unwrap_or("turn").to_string();
            let Some(targets) = resolve_target(spec.get("target"), me_idx, opp_idx, src, state) else { return };
            let turn_number = state.turn_number;
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                match duration.as_str() {
                    "turn" => ip.turn_base_power_override = Some(amount),
                    "next_self_turn_start" => ip.next_turn_base_power_override = Some(amount),
                    "next_opp_turn_end" | "next_opp_end_phase" => {
                        ip.next_opp_turn_end_base_power_override = Some(amount);
                        ip.next_opp_turn_end_base_power_override_applier_idx = me_idx as i32;
                        ip.next_opp_turn_end_base_power_override_applied_turn = turn_number;
                    }
                    _ => ip.base_power_override = Some(amount),
                }
            }
        }
        "set_protect_from_opp_effect_static" => {
            let Some(targets) = resolve_target(spec.get("target"), me_idx, opp_idx, src, state) else { return };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).protect_from_opp_effect = true;
            }
        }
        // 「相手キャラは自分の効果で離れない」 (OP14-079 黒クロコ) = 相手キャラ全員に protect。
        "set_opp_protect_static" => {
            for i in 0..state.players[opp_idx].characters.len() {
                state.players[opp_idx].characters[i].protect_from_opp_effect = true;
            }
        }
        "set_cannot_attack_static" => {
            let Some(targets) = resolve_target(spec.get("target"), me_idx, opp_idx, src, state) else { return };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).cannot_attack_static = true;
            }
        }
        // 「元々のコストを X にする / +N」: base_cost_override (effects.py:10993)
        "set_base_cost" => {
            let Some(targets) = resolve_target(spec.get("target"), me_idx, opp_idx, src, state) else { return };
            if let Some(amount) = spec.get("amount").and_then(|v| v.as_i64()) {
                for (pi, sl) in targets {
                    get_ip_mut(&mut state.players[pi], sl).base_cost_override = Some(amount as i32);
                }
            } else if let Some(delta) = spec.get("delta").and_then(|v| v.as_i64()) {
                for (pi, sl) in targets {
                    let ip = get_ip_mut(&mut state.players[pi], sl);
                    let cur = ip.base_cost_override.unwrap_or(ip.card.cost);
                    ip.base_cost_override = Some((cur + delta as i32).max(0));
                }
            } else if let Some(dp) = spec.get("delta_per") {
                let sk = dp.get("source").and_then(|v| v.as_str()).unwrap_or("");
                if sk != "self_trash_count" {
                    return; // 未知 source → skip
                }
                let divisor = dp.get("divisor").and_then(|v| v.as_i64()).unwrap_or(1).max(1);
                let mult = dp.get("multiplier").and_then(|v| v.as_i64()).unwrap_or(1);
                let delta = ((state.players[me_idx].trash.len() as i64) / divisor) * mult;
                for (pi, sl) in targets {
                    let ip = get_ip_mut(&mut state.players[pi], sl);
                    let cur = ip.base_cost_override.unwrap_or(ip.card.cost);
                    ip.base_cost_override = Some((cur + delta as i32).max(0));
                }
            }
        }
        // filter 付き 場のキャラ base_cost 変更 (effects.py:11030)
        "set_base_cost_filtered_static" => {
            let filt = spec.get("filter");
            let scope = spec.get("scope").and_then(|v| v.as_str()).unwrap_or("self");
            let pool = if scope == "self" { me_idx } else { opp_idx };
            let n = state.players[pool].characters.len();
            let delta = spec.get("delta").and_then(|v| v.as_i64());
            let amount = spec.get("amount").and_then(|v| v.as_i64());
            for i in 0..n {
                if !matches_filter(&state.players[pool].characters[i].card, filt) {
                    continue;
                }
                let ip = &mut state.players[pool].characters[i];
                if let Some(d) = delta {
                    let cur = ip.base_cost_override.unwrap_or(ip.card.cost);
                    ip.base_cost_override = Some((cur + d as i32).max(0));
                } else if let Some(a) = amount {
                    ip.base_cost_override = Some(a as i32);
                }
            }
        }
        _ => {} // 未対応 primitive → skip (該当カードは diverge = 差分テストが示す)
    }
}

/// 非静的 primitive を実行 (on_play 等)。 返り値 = 処理できたか (false=未対応→呼出側でカードが diverge)。
/// fidelity 原則: 未対応 primitive は何もしない (誤適用ゼロ)。 rng を使う primitive
/// (trash_self_hand_random 等) は Rust で bit 再現不可なので未対応扱い。
fn execute_effect(prim: &Value, state: &mut GameState, me_idx: usize, _src: Slot) -> bool {
    let Some((key, v)) = prim.as_object().and_then(|o| o.iter().next()) else { return true };
    match key.as_str() {
        // ドロー N (effects.py:3121)。 block_self_draw 中は不発。
        "draw" => {
            let n = v.as_i64().unwrap_or(0) as i32;
            let me = &mut state.players[me_idx];
            if me.block_self_draw_until_turn_end {
                return true;
            }
            for _ in 0..n {
                if me.deck.is_empty() {
                    break;
                }
                let c = me.deck.remove(0);
                let cid = c.card_id.clone();
                if !me.known_top_card_ids.is_empty() && me.known_top_card_ids[0] == cid {
                    me.known_top_card_ids.remove(0);
                } else if let Some(p) = me.known_top_card_ids.iter().position(|x| *x == cid) {
                    me.known_top_card_ids.remove(p);
                }
                me.hand.push(c);
                me.cards_drawn_count += 1;
            }
            true
        }
        _ => false, // 未対応 primitive → skip (該当カードは diverge)
    }
}

/// on_play の cost を AI 自動支払い (effects.py: AI は auto-pay)。
/// Some(true)=支払い済で発動 / Some(false)=支払い不能で skip / None=未対応 cost 種別で skip。
/// ⚠ pay_don のみ対応 (deterministic)。 discard_hand(random)/rest_self/once_per_turn 等は未対応 → skip。
fn pay_on_play_cost(cost: &Value, state: &mut GameState, me_idx: usize) -> Option<bool> {
    let mut pay_don = 0i32;
    let entries: Vec<(String, i64)> = if let Some(o) = cost.as_object() {
        o.iter().map(|(k, v)| (k.clone(), v.as_i64().unwrap_or(0))).collect()
    } else if let Some(arr) = cost.as_array() {
        arr.iter()
            .filter_map(|x| x.as_object())
            .flat_map(|o| o.iter().map(|(k, v)| (k.clone(), v.as_i64().unwrap_or(0))))
            .collect()
    } else {
        return None;
    };
    for (k, v) in entries {
        match k.as_str() {
            "pay_don" => pay_don += v as i32,
            _ => return None, // 未対応 cost 種別 → skip effect
        }
    }
    if pay_don > 0 {
        let me = &state.players[me_idx];
        let capacity = me.don_active + me.don_rested + me.leader.attached_dons
            + me.characters.iter().map(|c| c.attached_dons).sum::<i32>();
        if capacity < pay_don {
            return Some(false); // 支払い不能
        }
        let me = &mut state.players[me_idx];
        let mut removed = 0;
        let taken = pay_don.min(me.don_active);
        me.don_active -= taken;
        me.don_remaining_in_deck += taken;
        removed += taken;
        if removed < pay_don {
            let more = (pay_don - removed).min(me.don_rested);
            me.don_rested -= more;
            me.don_remaining_in_deck += more;
            removed += more;
        }
        if removed < pay_don {
            return None; // area 不足 → 付与ドン払い (稀、 power 依存) は未対応 → skip
        }
        state.last_returned_don_count = removed;
    }
    Some(true)
}

/// キャラ登場時の on_play 効果を実行 (effects.py:trigger_on_play)。 played_idx = me.characters の末尾。
/// ⚠ on_opp_chara_played (相手側トリガー) + event queue cascade は未対応 (該当カードは diverge)。
pub fn execute_on_play(state: &mut GameState, me_idx: usize, played_idx: usize) {
    let Some(ov) = overlay() else { return };
    let card_id = state.players[me_idx].characters[played_idx].card.card_id.clone();
    let Some(effs) = ov.get(&card_id) else { return };
    for eff in effs {
        if eff.get("when").and_then(|v| v.as_str()) != Some("on_play") {
            continue;
        }
        match eval_effect_conditions(eff, state, me_idx) {
            Some(true) => {}
            _ => continue,
        }
        // cost (AI 自動支払い)。 支払い不能/未対応なら effect skip。
        if let Some(cost) = eff.get("cost") {
            match pay_on_play_cost(cost, state, me_idx) {
                Some(true) => {}
                _ => continue,
            }
        }
        if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
            for prim in dos {
                execute_effect(prim, state, me_idx, Slot::Char(played_idx));
            }
        }
    }
}

/// game.py:evaluate_static_effects の移植 (on_attached_don 常在)。
pub fn evaluate_static_effects(state: &mut GameState) {
    let Some(ov) = overlay() else { return };
    // 全 InPlay の静的フラグをリセット (effects.py:10733-10753)
    for p in state.players.iter_mut() {
        p.hand_counter_boost = None;
        for ip in std::iter::once(&mut p.leader)
            .chain(p.characters.iter_mut())
            .chain(p.stages.iter_mut())
        {
            ip.static_buff = 0;
            ip.static_ko_immune = false;
            ip.static_ko_immune_from_source_power_le = -1;
            ip.static_ko_immune_from_non_attribute = String::new();
            ip.base_power_override = None;
            ip.base_cost_override = None;
            ip.attack_taunt = false;
            ip.cannot_attack_static = false;
            ip.protect_from_opp_effect = false;
            ip.ko_immune_battle_attributes_in.clear();
            ip.ko_immune_battle_attributes_not_in.clear();
            ip.battle_ko_immune_static = false;
            ip.battle_ko_immune_vs_leader = false;
            ip.battle_pump_vs_attribute.clear();
            ip.static_granted_keywords.clear();
        }
        p.play_cost_reductions_filtered = vec![];
    }
    // ターンプレイヤー側を先に処理 (公式 1-3-4)
    let turn_idx = state.turn_player_idx;
    for &me_idx in &[turn_idx, 1 - turn_idx] {
        let slots: Vec<Slot> = {
            let p = &state.players[me_idx];
            let mut v = vec![Slot::Leader];
            v.extend((0..p.characters.len()).map(Slot::Char));
            v.extend((0..p.stages.len()).map(Slot::Stage));
            v
        };
        for src in slots {
            let (card_id, attached, negated) = {
                let ip = get_ip(&state.players[me_idx], src);
                (
                    ip.card.card_id.clone(),
                    ip.attached_dons,
                    ip.granted_keywords.contains("効果無効"),
                )
            };
            if negated {
                continue;
            }
            let Some(effs) = ov.get(&card_id) else { continue };
            for eff in effs {
                if eff.get("when").and_then(|v| v.as_str()) != Some("on_attached_don") {
                    continue;
                }
                let n_req = as_i(eff.get("n"), 1) as i32;
                if attached < n_req {
                    continue;
                }
                // ⚠ Python eval_all_conditions は "if" (単一 dict) と "conditions" (dict の list) の
                // 両方を AND 評価する。 conditions を見落とすと過剰適用になる (OP13-099 虚の玉座で発覚)。
                match eval_effect_conditions(eff, state, me_idx) {
                    Some(true) => {}
                    _ => continue, // false or 未知 → skip
                }
                if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
                    for prim in dos {
                        apply_static_primitive(prim, state, me_idx, src);
                    }
                }
            }
        }
    }
}
