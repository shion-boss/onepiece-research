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

static ROLES: OnceLock<HashMap<String, String>> = OnceLock::new();

/// db/card_roles.json を読み込む (card_id → primary_role)。 _opp_value の role bonus 用。
pub fn load_roles(json_str: &str) -> Result<(), String> {
    if ROLES.get().is_some() {
        return Ok(());
    }
    let raw: HashMap<String, Value> = serde_json::from_str(json_str).map_err(|e| e.to_string())?;
    let mut map = HashMap::new();
    for (cid, v) in raw {
        if let Some(role) = v.get("primary_role").and_then(|x| x.as_str()) {
            map.insert(cid, role.to_string());
        }
    }
    let _ = ROLES.set(map);
    Ok(())
}

fn role_of(card_id: &str) -> Option<&'static str> {
    ROLES.get().and_then(|m| m.get(card_id)).map(|s| s.as_str())
}

/// effects.py:_opp_value = AI が除去/対象に選ぶ相手キャラの価値。 max が選ばれる。
fn opp_value(ip: &InPlay) -> f64 {
    let mut val = (ip.card.cost as f64) * 1000.0 + (ip.power() as f64);
    if ip.is_blocker_now() {
        val += 3000.0;
    }
    if let Some(role) = role_of(&ip.card.card_id) {
        val += match role {
            "finisher" => 5000.0,
            "blocker" => 2500.0,
            "draw" | "search" => 2000.0,
            "removal" | "negation" | "disruption" | "ramp" | "recovery" | "support" | "synergy" => 1500.0,
            _ => 0.0,
        };
    }
    val
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
        // one_opponent_[rested_]character[_(any_)?cost_le_Ncost | _power_le_N | _any]
        // = 相手キャラを filter → opp_value 最大を 1 体 (AI 自動選択、 effects.py:2443/2540/2627)。
        os if os.starts_with("one_opponent_") => {
            let rested_only = os.contains("rested_character");
            let cost_le = parse_after(os, "cost_le_"); // c.card.cost <= n
            let power_le = parse_after(os, "power_le_"); // c.power() <= n
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> = (0..opp.characters.len())
                .filter(|&i| {
                    let c = &opp.characters[i];
                    if rested_only && !c.rested {
                        return false;
                    }
                    if let Some(n) = cost_le {
                        if c.card.cost > n {
                            return false;
                        }
                    }
                    if let Some(n) = power_le {
                        if c.power() > n {
                            return false;
                        }
                    }
                    true
                })
                .collect();
            // -opp_value で安定ソート → 先頭 (ties は index 順 = Python stable sort と一致)
            cands.sort_by(|&a, &b| {
                opp_value(&opp.characters[b])
                    .partial_cmp(&opp_value(&opp.characters[a]))
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            cands.into_iter().take(1).map(|i| (opp_idx, Slot::Char(i))).collect()
        }
        _ => return None,
    };
    Some(out)
}

/// spec 文字列中の marker 直後の数字を取り出す (例: "cost_le_3cost" の "cost_le_" → 3)。
fn parse_after(s: &str, marker: &str) -> Option<i32> {
    let pos = s.find(marker)?;
    let rest = &s[pos + marker.len()..];
    let num: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    num.parse().ok()
}

fn cat_str(c: &Category) -> &'static str {
    match c {
        Category::Leader => "LEADER",
        Category::Character => "CHARACTER",
        Category::Event => "EVENT",
        Category::Stage => "STAGE",
    }
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
            "cost_eq" => (card.cost as i64) == v.as_i64().unwrap_or(-1),
            "power_le" => (card.power as i64) <= v.as_i64().unwrap_or(0),
            "power_ge" => (card.power as i64) >= v.as_i64().unwrap_or(0),
            "category" => Some(cat_str(&card.category)) == v.as_str(),
            "exclude_name" => match v {
                Value::String(s) => card.name != *s,
                Value::Array(a) => !a.iter().any(|x| x.as_str() == Some(card.name.as_str())),
                _ => true,
            },
            "name_in" => v
                .as_array()
                .map_or(false, |arr| arr.iter().any(|x| x.as_str() == Some(card.name.as_str()))),
            "feature_contains" => card
                .features
                .iter()
                .any(|x| x.contains(v.as_str().unwrap_or(""))),
            "or" | "or_clauses" => v
                .as_array()
                .map_or(false, |arr| arr.iter().any(|clause| matches_filter(card, Some(clause)))),
            "exclude_card_id" => match v {
                Value::String(s) => card.card_id != *s,
                Value::Array(a) => !a.iter().any(|x| x.as_str() == Some(card.card_id.as_str())),
                _ => true,
            },
            _ => return false, // 未知 filter キー → 不一致扱い (安全側)
        };
        if !ok {
            return false;
        }
    }
    true
}

/// power_pump の amount 計算 (base + amount_per: source//divisor*mult)。 None=未知 source (→ skip)。
fn pump_amount(spec: &Value, state: &GameState, me_idx: usize, opp_idx: usize) -> Option<i32> {
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
            _ => return None,
        };
        amount += (src_val / divisor) * mult;
    }
    Some(amount)
}

/// 静的 primitive を適用。 未知 primitive/target は skip (誤適用ゼロ)。
fn apply_static_primitive(prim: &Value, state: &mut GameState, me_idx: usize, src: Slot) {
    let opp_idx = 1 - me_idx;
    let Some((key, spec)) = prim.as_object().and_then(|o| o.iter().next()) else { return };
    match key.as_str() {
        "power_pump" => {
            // 静的 context では duration は static 強制 (effects.py:10783) → static_buff += amount。
            let Some(amount) = pump_amount(spec, state, me_idx, opp_idx) else { return };
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
fn execute_effect(prim: &Value, state: &mut GameState, me_idx: usize, src: Slot) -> bool {
    let opp_idx = 1 - me_idx;
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
        // on_play power_pump (duration 別 buff)。 対象選択が要る target は resolve_target=None → skip。
        "power_pump" => {
            let Some(amount) = pump_amount(v, state, me_idx, opp_idx) else { return false };
            let ff = v.get("feature_filter").and_then(|x| x.as_str()).map(|s| s.to_string());
            let Some(targets) = resolve_target(v.get("target"), me_idx, opp_idx, src, state) else { return false };
            let duration = v.get("duration").and_then(|x| x.as_str()).unwrap_or("turn").to_string();
            let turn_number = state.turn_number;
            for (pi, sl) in targets {
                if let Some(f) = &ff {
                    if !get_ip(&state.players[pi], sl).card.features.iter().any(|x| x == f) {
                        continue;
                    }
                }
                let ip = get_ip_mut(&mut state.players[pi], sl);
                match duration.as_str() {
                    "static" => ip.static_buff += amount,
                    "battle" => ip.battle_buff += amount,
                    "next_self_turn_start" => ip.next_turn_buff += amount,
                    "next_opp_turn_end" | "next_opp_end_phase" => {
                        ip.next_opp_turn_end_buff += amount;
                        ip.next_opp_turn_end_applier_idx = me_idx as i32;
                        ip.next_opp_turn_end_applied_turn = turn_number;
                    }
                    "next_self_turn_end" => {
                        ip.next_self_turn_end_buff += amount;
                        ip.next_self_turn_end_applier_idx = me_idx as i32;
                        ip.next_self_turn_end_applied_turn = turn_number;
                    }
                    _ => ip.turn_buff += amount, // "turn" 既定
                }
            }
            true
        }
        // レスト (effects.py:3761)。 string spec (one_opponent_*) = _opp_value 最大を選ぶ。
        // ⚠ or_don/{count,target} 変種 + replace_rest は resolve_target=None または diverge → skip 境界。
        "rest" => {
            let Some(targets) = resolve_target(Some(v), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                if ip.cannot_be_rested_buff || ip.rested {
                    continue;
                }
                ip.rested = true;
            }
            true
        }
        // ドンデッキから N 枚をレストで追加 (effects.py:4536)。
        "add_rested_don" => {
            let n = (v.as_i64().unwrap_or(0) as i32).min(state.players[me_idx].don_remaining_in_deck);
            let me = &mut state.players[me_idx];
            me.don_rested += n;
            me.don_remaining_in_deck -= n;
            true
        }
        // レストドンを N 枚アクティブに (effects.py:4544)。 "all" = 全部。
        "untap_don" => {
            let me = &mut state.players[me_idx];
            let n = if v.as_str() == Some("all") {
                me.don_rested
            } else {
                (v.as_i64().unwrap_or(0) as i32).min(me.don_rested)
            };
            me.don_rested -= n;
            me.don_active += n;
            true
        }
        // 自デッキ上 N 枚を trash (effects.py:6059)。
        "mill_self_top" => {
            let n = if let Some(o) = v.as_object() {
                o.get("amount").and_then(|x| x.as_i64()).unwrap_or(1) as i32
            } else {
                v.as_i64().unwrap_or(1) as i32
            };
            let me = &mut state.players[me_idx];
            for _ in 0..n {
                if me.deck.is_empty() {
                    break;
                }
                let c = me.deck.remove(0);
                me.trash.push(c);
            }
            true
        }
        // キーワード付与 (effects.py:4628)。 keywords list は AI 優先度で 1 つ選択。
        // duration: turn→granted_keywords / next_opp_turn_end→granted_keywords_through_opp_turn+applier。
        "give_keyword" => {
            let keyword = if let Some(kws) = v.get("keywords").and_then(|x| x.as_array()) {
                let kwstrs: Vec<&str> = kws.iter().filter_map(|k| k.as_str()).collect();
                let priority = ["ブロッカー", "ダブルアタック", "バニッシュ", "速攻"];
                priority
                    .iter()
                    .find(|p| kwstrs.contains(p))
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| kwstrs.first().map(|s| s.to_string()).unwrap_or_default())
            } else {
                v.get("keyword").and_then(|x| x.as_str()).unwrap_or("速攻").to_string()
            };
            if keyword.is_empty() {
                return false;
            }
            let next_opp = v.get("duration").and_then(|x| x.as_str()) == Some("next_opp_turn_end");
            let Some(targets) = resolve_target(v.get("target"), me_idx, opp_idx, src, state) else { return false };
            let turn_number = state.turn_number;
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                if next_opp {
                    ip.granted_keywords_through_opp_turn.insert(keyword.clone());
                    ip.granted_keywords_through_opp_turn_applier_idx = me_idx as i32;
                    ip.granted_keywords_through_opp_turn_applied_turn = turn_number;
                } else {
                    ip.granted_keywords.insert(keyword.clone());
                }
            }
            true
        }
        // 任意コスト効果 (effects.py:8245)。「Xできる:Y」= AI は cost+effect payable なら発動。
        // ⚠ pay_don/rest_self_don cost + 実装済 effect のみ対応。 他の cost/effect は skip (fidelity)。
        "optional_cost_then" => {
            let empty: Vec<Value> = vec![];
            let cost = v.get("cost").and_then(|x| x.as_array()).unwrap_or(&empty);
            let effect = v.get("effect").and_then(|x| x.as_array()).unwrap_or(&empty);
            let mut pay_don = 0i32;
            let mut rest_don = 0i32;
            for cs in cost {
                let Some((k, cv)) = cs.as_object().and_then(|o| o.iter().next()) else { return false };
                match k.as_str() {
                    "pay_don" => pay_don += cv.as_i64().unwrap_or(0) as i32,
                    "rest_self_don" => rest_don += cv.as_i64().unwrap_or(0) as i32,
                    _ => return false, // 未対応 cost → skip
                }
            }
            for es in effect {
                let Some((k, _)) = es.as_object().and_then(|o| o.iter().next()) else { return false };
                if !is_handled_effect(k) {
                    return false; // 未対応 effect → skip (paid してから失敗を防ぐ)
                }
            }
            {
                let me = &state.players[me_idx];
                let cap = me.don_active + me.don_rested + me.leader.attached_dons
                    + me.characters.iter().map(|c| c.attached_dons).sum::<i32>();
                if me.don_active < rest_don || cap < pay_don {
                    return false; // 支払い不能 → 不発
                }
            }
            if rest_don > 0 {
                let me = &mut state.players[me_idx];
                let n = rest_don.min(me.don_active);
                me.don_active -= n;
                me.don_rested += n;
            }
            if pay_don > 0 && !pay_don_field(state, me_idx, pay_don) {
                return false;
            }
            for es in effect {
                execute_effect(es, state, me_idx, src);
            }
            true
        }
        // ドンデッキから N 枚をアクティブで追加 (effects.py:4526)。
        "add_don" | "add_don_active" => {
            let n = (v.as_i64().unwrap_or(0) as i32).min(state.players[me_idx].don_remaining_in_deck);
            let me = &mut state.players[me_idx];
            me.don_active += n;
            me.don_remaining_in_deck -= n;
            true
        }
        // 自デッキ上 N 枚をライフに (effects.py:4619)。
        "put_top_to_life" => {
            let n = v.as_i64().unwrap_or(0) as i32;
            let me = &mut state.players[me_idx];
            for _ in 0..n {
                if me.deck.is_empty() {
                    break;
                }
                let c = me.deck.remove(0);
                me.life.push(c);
            }
            true
        }
        // コスト修正 (effects.py:5613)。 amount(負=コスト+)を duration 別に。 selecting target 可。
        "cost_minus" => {
            let (target_val, amount, next_opp) = if let Some(o) = v.as_object() {
                (
                    o.get("target").cloned(),
                    o.get("amount").and_then(|x| x.as_i64()).unwrap_or(1) as i32,
                    o.get("duration").and_then(|x| x.as_str()) == Some("next_opp_turn_end"),
                )
            } else {
                // v=int → target one_opponent_character_any
                (Some(Value::String("one_opponent_character_any".into())), v.as_i64().unwrap_or(1) as i32, false)
            };
            let Some(targets) = resolve_target(target_val.as_ref(), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                if next_opp {
                    ip.cost_minus_through_opp_turn += amount;
                } else {
                    ip.cost_minus_until_turn_end += amount;
                }
            }
            true
        }
        // 次リフレッシュ非アクティブ (effects.py:5599)。 selecting target。
        "stay_rested_next_refresh" => {
            let Some(targets) = resolve_target(Some(v), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).stay_rested_next_refresh = true;
            }
            true
        }
        // レストドンを target に付与 (effects.py:5736)。 source=don_rested。
        "attach_rested_don" => {
            let count = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32;
            let target_val = v.get("target").cloned().unwrap_or(Value::String("self_leader".into()));
            let Some(targets) = resolve_target(Some(&target_val), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                let take = count.min(state.players[me_idx].don_rested);
                if take <= 0 {
                    continue;
                }
                state.players[me_idx].don_rested -= take;
                get_ip_mut(&mut state.players[pi], sl).attached_dons += take;
            }
            true
        }
        // KO (effects.py:3245)。 免疫チェック → 除去 + trash + 付与ドン返却 + chara_ko_taken。
        // ⚠ replace_ko / KO trigger cascade は未対応 → 該当 victim は diverge (差分テストが除外)。
        "ko" => {
            let Some(targets) = resolve_target(Some(v), me_idx, opp_idx, src, state) else { return false };
            let (src_power, src_attr) = {
                let s = get_ip(&state.players[me_idx], src);
                (s.card.power, s.card.attribute.clone())
            };
            let mut victims: Vec<(usize, usize)> = vec![];
            for &(pi, sl) in &targets {
                if let Slot::Char(idx) = sl {
                    let t = &mut state.players[pi].characters[idx];
                    if t.protect_from_opp_effect {
                        continue;
                    }
                    if t.ko_per_turn_immune_remaining > 0 {
                        t.ko_per_turn_immune_remaining -= 1;
                        continue;
                    }
                    if t.ko_immune_until_turn_end || t.static_ko_immune || t.ko_immune_through_opp_turn {
                        continue;
                    }
                    if t.static_ko_immune_from_source_power_le >= 0
                        && src_power <= t.static_ko_immune_from_source_power_le
                    {
                        continue;
                    }
                    let req = t.static_ko_immune_from_non_attribute.clone();
                    if !req.is_empty() && !src_attr.contains(&req) {
                        continue;
                    }
                    victims.push((pi, idx));
                }
            }
            remove_victims(state, victims, RemoveDest::Trash);
            true
        }
        // 手札に戻す (バウンス)。 protect チェック → 除去 + hand + 付与ドン返却。
        "return_to_hand" => {
            let Some(targets) = resolve_target(Some(v), me_idx, opp_idx, src, state) else { return false };
            let victims = collect_unprotected(state, &targets);
            remove_victims(state, victims, RemoveDest::Hand);
            true
        }
        // デッキ下に戻す。 protect チェック → 除去 + deck 末尾 + 付与ドン返却。
        "return_to_deck_bottom" => {
            let Some(targets) = resolve_target(Some(v), me_idx, opp_idx, src, state) else { return false };
            let victims = collect_unprotected(state, &targets);
            remove_victims(state, victims, RemoveDest::DeckBottom);
            true
        }
        // デッキ上 N 枚を見て filter マッチ先頭 M 枚を手札、 残りをデッキ下 (effects.py:4037)。
        // ⚠ destination=hand + rest_remain=bottom のみ対応 (play/life/trash/top_or_bottom は skip)。
        // AI 選択 = 決定的 (filter マッチの先頭 limit 枚 = deck 順)。
        "search_top_n" => {
            let destination = v.get("destination").and_then(|x| x.as_str()).unwrap_or("hand");
            let rest_remain = v.get("rest_remain").and_then(|x| x.as_str()).unwrap_or("bottom");
            if destination != "hand" || !(rest_remain == "bottom" || rest_remain == "trash") {
                return false;
            }
            let rest_to_trash = rest_remain == "trash";
            let depth = v.get("depth").and_then(|x| x.as_i64()).unwrap_or(5) as usize;
            let limit = v.get("limit").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let public = v.get("public").and_then(|x| x.as_bool()).unwrap_or(false);
            let filt = v.get("filter");
            let me = &mut state.players[me_idx];
            if me.deck.is_empty() {
                return true;
            }
            let d = depth.min(me.deck.len());
            let seen: Vec<crate::state::CardDef> = me.deck.drain(0..d).collect();
            let mut picked = 0;
            let mut remaining: Vec<crate::state::CardDef> = vec![];
            for c in seen {
                if picked < limit && matches_filter(&c, filt) {
                    let cid = c.card_id.clone();
                    me.hand.push(c);
                    if public {
                        me.known_hand_card_ids.push(cid);
                    }
                    picked += 1;
                } else {
                    remaining.push(c);
                }
            }
            for c in remaining {
                if rest_to_trash {
                    me.trash.push(c);
                } else {
                    me.known_bottom_card_ids.push(c.card_id.clone());
                    me.deck.push(c);
                }
            }
            true
        }
        // レスト不能 (effects.py:6024)。 cannot_be_rested_buff + applier tracking。
        "set_cannot_rest" => {
            let target_val = if v.is_string() {
                v.clone()
            } else {
                v.get("target").cloned().unwrap_or(Value::String("all_self_characters".into()))
            };
            let count = v.get("count").and_then(|x| x.as_i64()).unwrap_or(99) as usize;
            let Some(targets) = resolve_target(Some(&target_val), me_idx, opp_idx, src, state) else { return false };
            let tn = state.turn_number;
            for (pi, sl) in targets.into_iter().take(count) {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                ip.cannot_be_rested_buff = true;
                ip.cannot_be_rested_applier_idx = me_idx as i32;
                ip.cannot_be_rested_applied_turn = tn;
            }
            true
        }
        // アタック不能 (effects.py:5566)。 duration turn→until_turn_end / next_opp_turn_end→through_opp_turn。
        "set_cannot_attack" => {
            let (target_val, next_opp, count) = if let Some(o) = v.as_object() {
                (
                    o.get("target").cloned().unwrap_or(Value::String("one_opponent_character_any".into())),
                    o.get("duration").and_then(|x| x.as_str()) == Some("next_opp_turn_end"),
                    o.get("count").and_then(|x| x.as_i64()).unwrap_or(99) as usize,
                )
            } else {
                (v.clone(), false, 99)
            };
            let Some(targets) = resolve_target(Some(&target_val), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets.into_iter().take(count) {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                if next_opp {
                    ip.cannot_attack_through_opp_turn = true;
                } else {
                    ip.cannot_attack_until_turn_end = true;
                }
            }
            true
        }
        _ => false, // 未対応 primitive → skip (該当カードは diverge)
    }
}

enum RemoveDest {
    Trash,
    Hand,
    DeckBottom,
}

/// protect_from_opp_effect でない victim (player_idx, char_idx) を集める。
fn collect_unprotected(state: &GameState, targets: &[(usize, Slot)]) -> Vec<(usize, usize)> {
    let mut v = vec![];
    for &(pi, sl) in targets {
        if let Slot::Char(idx) = sl {
            if !state.players[pi].characters[idx].protect_from_opp_effect {
                v.push((pi, idx));
            }
        }
    }
    v
}

/// victim キャラを場から除去し dest へ (付与ドンはレストで返却)。 index 降順で remove。
/// ⚠ KO/離脱 trigger cascade は未対応 (該当 victim は diverge)。
fn remove_victims(state: &mut GameState, mut victims: Vec<(usize, usize)>, dest: RemoveDest) {
    victims.sort_by(|a, b| b.1.cmp(&a.1));
    for (pi, idx) in victims {
        if idx >= state.players[pi].characters.len() {
            continue;
        }
        let removed = state.players[pi].characters.remove(idx);
        let don = removed.attached_dons;
        match dest {
            RemoveDest::Trash => {
                state.players[pi].trash.push(removed.card);
                state.players[pi].chara_ko_taken_this_turn += 1;
            }
            RemoveDest::Hand => state.players[pi].hand.push(removed.card),
            RemoveDest::DeckBottom => state.players[pi].deck.push(removed.card),
        }
        state.players[pi].don_rested += don;
    }
}

/// ドン-N を場から支払い (active→rested→付与、 don_remaining+=、 last_returned_don_count)。 area 不足で払えなければ false。
fn pay_don_field(state: &mut GameState, me_idx: usize, n: i32) -> bool {
    let me = &mut state.players[me_idx];
    let mut removed = 0;
    let taken = n.min(me.don_active);
    me.don_active -= taken;
    me.don_remaining_in_deck += taken;
    removed += taken;
    if removed < n {
        let more = (n - removed).min(me.don_rested);
        me.don_rested -= more;
        me.don_remaining_in_deck += more;
        removed += more;
    }
    if removed < n {
        return false; // 付与ドン払い (power 依存) は未対応
    }
    state.last_returned_don_count = removed;
    true
}

/// execute_effect が対応する effect primitive か (optional_cost_then の dry-check 用)。
fn is_handled_effect(key: &str) -> bool {
    matches!(
        key,
        "draw" | "power_pump" | "rest" | "ko" | "return_to_hand" | "return_to_deck_bottom"
            | "add_rested_don" | "untap_don" | "mill_self_top" | "give_keyword" | "add_don"
            | "add_don_active" | "put_top_to_life" | "cost_minus" | "stay_rested_next_refresh"
            | "attach_rested_don"
    )
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

/// card_id の指定 when 効果を実行 (条件チェック→cost 支払い→do 実行)。 on_play/main 共通。
fn execute_card_effects(state: &mut GameState, me_idx: usize, card_id: &str, when: &str, src: Slot) {
    let Some(ov) = overlay() else { return };
    // effs は static OVERLAY 由来 (state と disjoint) なので clone 不要で iterate 可。
    let Some(effs) = ov.get(card_id) else { return };
    for eff in effs {
        if eff.get("when").and_then(|v| v.as_str()) != Some(when) {
            continue;
        }
        match eval_effect_conditions(eff, state, me_idx) {
            Some(true) => {}
            _ => continue,
        }
        if let Some(cost) = eff.get("cost") {
            match pay_on_play_cost(cost, state, me_idx) {
                Some(true) => {}
                _ => continue,
            }
        }
        if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
            for prim in dos {
                execute_effect(prim, state, me_idx, src);
            }
        }
    }
}

/// キャラ登場時の on_play 効果を実行 (effects.py:trigger_on_play)。 played_idx = me.characters の末尾。
/// ⚠ on_opp_chara_played (相手側トリガー) + event queue cascade は未対応 (該当カードは diverge)。
pub fn execute_on_play(state: &mut GameState, me_idx: usize, played_idx: usize) {
    let card_id = state.players[me_idx].characters[played_idx].card.card_id.clone();
    execute_card_effects(state, me_idx, &card_id, "on_play", Slot::Char(played_idx));
}

/// メインイベントの効果を実行 (effects.py:trigger_main_event)。 event はトラッシュ済 = src は leader 仮 placeholder。
pub fn execute_main_event(state: &mut GameState, me_idx: usize, card_id: &str) {
    execute_card_effects(state, me_idx, card_id, "main", Slot::Leader);
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
