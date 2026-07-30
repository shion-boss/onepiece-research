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

/// card_id の overlay に指定 when の効果があるか (戦闘の trigger 有無チェック用)。
pub fn card_has_when(card_id: &str, when: &str) -> bool {
    overlay().and_then(|m| m.get(card_id)).map_or(false, |effs| {
        effs.iter().any(|e| e.get("when").and_then(|v| v.as_str()) == Some(when))
    })
}

/// effects.py:should_fire_trigger = 防御 AI が ライフの【トリガー】を発動すべきか。
/// Some(true)=発動(=強力効果を含む) / Some(false)=発動しない(=手札へ) / None=条件 unknown で判定不能(=呼出側 bail)。
/// 強力効果 = ko/return_to_hand/draw/life_to_hand/rest/ko_self/play_self/play_from_trash/
///           play_multi_from_trash/play_from_hand/fire_self_effect のいずれかの key を do に含む。
pub fn should_fire_trigger(state: &GameState, defender_idx: usize, card_id: &str) -> Option<bool> {
    let Some(ov) = overlay() else { return Some(false) };
    let Some(effs) = ov.get(card_id) else { return Some(false) };
    let trig: Vec<&Value> = effs
        .iter()
        .filter(|e| e.get("when").and_then(|v| v.as_str()) == Some("trigger"))
        .collect();
    if trig.is_empty() {
        return Some(false);
    }
    const STRONG: &[&str] = &[
        "ko", "return_to_hand", "draw", "life_to_hand", "rest", "ko_self", "play_self",
        "play_from_trash", "play_multi_from_trash", "play_from_hand", "fire_self_effect",
    ];
    for eff in trig {
        match eval_effect_conditions(eff, state, defender_idx, None) {
            Some(true) => {}
            Some(false) => continue,
            None => return None, // 条件 unknown → 判定不能 = bail
        }
        if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
            for prim in dos {
                if let Some(o) = prim.as_object() {
                    if o.keys().any(|k| STRONG.contains(&k.as_str())) {
                        return Some(true);
                    }
                }
            }
        }
    }
    Some(false)
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
fn eval_condition(cond: &Value, state: &GameState, me_idx: usize, src: Option<Slot>) -> Option<bool> {
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
            // source (静的効果の発動元カード) がレストか。 src 不明なら判定不能 (None)。
            "self_rested" => match src {
                Some(sl) => get_ip(me, sl).rested == v.as_bool().unwrap_or(true),
                None => return None,
            },
            // 自分の N ターン目以降 (effects.py:1685、 通算 turn_number >= 2*N-1 でフィルタ)
            "self_turn_number_ge" => (state.turn_number as i64) >= 2 * v.as_i64().unwrap_or(0) - 1,
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
            // 自ライフ枚数 <= 相手ライフ枚数 (OP10-114 等)
            "self_life_le_opp" => (me.life.len() <= opp.life.len()) == v.as_bool().unwrap_or(true),
            "self_don_le" => total_don(me) <= v.as_i64().unwrap_or(0),
            "self_don_ge" => total_don(me) >= v.as_i64().unwrap_or(0),
            "self_don_active_ge" => (me.don_active as i64) >= v.as_i64().unwrap_or(0),
            "self_don_active_le" => (me.don_active as i64) <= v.as_i64().unwrap_or(0),
            "self_don_active_eq" => (me.don_active as i64) == v.as_i64().unwrap_or(0),
            // 【ドン‼×N】ゲート = 自リーダー+全キャラの付与ドン合計 N 以上 (effects.py:1690)。
            // ⚠ self_inplay=None (on_ko 等) の _on_ko_victim_attached_don 足し戻しは未対応
            //   (Rust は on_attack/on_play/static でのみ eval = self 常在 → 単純合計で忠実)。
            "self_attached_don_ge" => {
                let total = me.leader.attached_dons as i64
                    + me.characters.iter().map(|c| c.attached_dons as i64).sum::<i64>();
                total >= v.as_i64().unwrap_or(0)
            }
            "opp_attached_don_ge" => {
                let total = opp.leader.attached_dons as i64
                    + opp.characters.iter().map(|c| c.attached_dons as i64).sum::<i64>();
                total >= v.as_i64().unwrap_or(0)
            }
            "self_hand_count_le" => (me.hand.len() as i64) <= v.as_i64().unwrap_or(0),
            "self_hand_count_ge" => (me.hand.len() as i64) >= v.as_i64().unwrap_or(0),
            "opp_hand_count_ge" => (opp.hand.len() as i64) >= v.as_i64().unwrap_or(0),
            "opp_hand_count_le" => (opp.hand.len() as i64) <= v.as_i64().unwrap_or(0),
            // 自ドン総数 - 相手ドン総数 <= N (effects.py:don_diff_le)
            "don_diff_le" => {
                let atk = |p: &Player| (p.don_active + p.don_rested + p.leader.attached_dons
                    + p.characters.iter().map(|c| c.attached_dons).sum::<i32>()) as i64;
                (atk(me) - atk(opp)) <= v.as_i64().unwrap_or(0)
            }
            // このターン中にコスト N 以上のイベントを使用したか (max_event_cost_this_turn)
            "self_event_cost_used_ge" => (me.max_event_cost_this_turn as i64) >= v.as_i64().unwrap_or(0),
            "self_field_count_ge" | "self_chara_count_ge" => (me.characters.len() as i64) >= v.as_i64().unwrap_or(0),
            // 複合 filter (色/特徴/cost 等 + current_power + rested) で自キャラ数 N 以上 (effects.py:1340)
            "self_chara_filtered_count_ge" => {
                let need = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1);
                let filt = v.get("filter");
                let cpge = filt.and_then(|f| f.get("current_power_ge")).and_then(|x| x.as_i64());
                let cple = filt.and_then(|f| f.get("current_power_le")).and_then(|x| x.as_i64());
                let rested_req = v.get("rested_required").and_then(|x| x.as_bool()).unwrap_or(false);
                let base_filt: Option<Value> = filt.map(|f| {
                    let mut o = f.as_object().cloned().unwrap_or_default();
                    o.remove("current_power_ge");
                    o.remove("current_power_le");
                    Value::Object(o)
                });
                let cnt = me.characters.iter().filter(|c| {
                    matches_filter(&c.card, base_filt.as_ref())
                        && (!rested_req || c.rested)
                        && cpge.map_or(true, |t| c.power() as i64 >= t)
                        && cple.map_or(true, |t| (c.power() as i64) <= t)
                }).count() as i64;
                cnt >= need
            }
            // 上の opp 版 (相手キャラを filter で数える、 EB04-007 等)
            "opp_chara_filtered_count_ge" => {
                let need = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1);
                let filt = v.get("filter");
                let cpge = filt.and_then(|f| f.get("current_power_ge")).and_then(|x| x.as_i64());
                let cple = filt.and_then(|f| f.get("current_power_le")).and_then(|x| x.as_i64());
                let rested_req = v.get("rested_required").and_then(|x| x.as_bool()).unwrap_or(false);
                let base_filt: Option<Value> = filt.map(|f| {
                    let mut o = f.as_object().cloned().unwrap_or_default();
                    o.remove("current_power_ge");
                    o.remove("current_power_le");
                    Value::Object(o)
                });
                let cnt = opp.characters.iter().filter(|c| {
                    matches_filter(&c.card, base_filt.as_ref())
                        && (!rested_req || c.rested)
                        && cpge.map_or(true, |t| c.power() as i64 >= t)
                        && cple.map_or(true, |t| (c.power() as i64) <= t)
                }).count() as i64;
                cnt >= need
            }
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
            "not" => match eval_condition(v, state, me_idx, src) {
                Some(b) => !b,
                None => return None,
            },
            "or" => {
                let Some(arr) = v.as_array() else { return None };
                let mut any = false;
                for c in arr {
                    match eval_condition(c, state, me_idx, src) {
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
                    match eval_condition(c, state, me_idx, src) {
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
/// src = 発動元カードの Slot (self_rested 等の source 条件用、 不明なら None)。
fn eval_effect_conditions(eff: &Value, state: &GameState, me_idx: usize, src: Option<Slot>) -> Option<bool> {
    if let Some(cond) = eff.get("if") {
        match eval_condition(cond, state, me_idx, src) {
            Some(true) => {}
            Some(false) => return Some(false),
            None => return None,
        }
    }
    if let Some(conds) = eff.get("conditions").and_then(|v| v.as_array()) {
        for c in conds {
            match eval_condition(c, state, me_idx, src) {
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
            // 自リーダー/キャラから filter 一致 1 枚 (power 降順、 effects.py:2097)。
            if t == "one_self_chara_or_leader_filtered" {
                let filt = v.get("filter");
                let p = &state.players[me_idx];
                let mut cands: Vec<Slot> = vec![];
                if matches_filter(&p.leader.card, filt) {
                    cands.push(Slot::Leader);
                }
                for i in 0..p.characters.len() {
                    if matches_filter(&p.characters[i].card, filt) {
                        cands.push(Slot::Char(i));
                    }
                }
                cands.sort_by(|&a, &b| get_ip(p, b).power().cmp(&get_ip(p, a).power()));
                return Some(cands.into_iter().take(1).map(|sl| (me_idx, sl)).collect());
            }
            // 自キャラのみから filter 一致 1 枚 (current_power/rested_required + power 降順、 effects.py:2111)。
            if t == "one_self_chara_filtered" {
                let cpge = v.get("filter").and_then(|f| f.get("current_power_ge")).and_then(|x| x.as_i64());
                let cple = v.get("filter").and_then(|f| f.get("current_power_le")).and_then(|x| x.as_i64());
                let rested_req = v.get("rested_required").and_then(|x| x.as_bool()).unwrap_or(false);
                let base_filt: Option<Value> = v.get("filter").map(|f| {
                    let mut o = f.as_object().cloned().unwrap_or_default();
                    o.remove("current_power_ge");
                    o.remove("current_power_le");
                    Value::Object(o)
                });
                let p = &state.players[me_idx];
                let mut cands: Vec<usize> = (0..p.characters.len())
                    .filter(|&i| {
                        let c = &p.characters[i];
                        matches_filter(&c.card, base_filt.as_ref())
                            && (!rested_req || c.rested)
                            && cpge.map_or(true, |t| c.power() as i64 >= t)
                            && cple.map_or(true, |t| (c.power() as i64) <= t)
                    })
                    .collect();
                cands.sort_by(|&a, &b| p.characters[b].power().cmp(&p.characters[a].power()));
                return Some(cands.into_iter().take(1).map(|i| (me_idx, Slot::Char(i))).collect());
            }
            return None;
        }
    };
    let out = match s.as_str() {
        "self" | "self_inplay" => vec![(me_idx, src)],
        "self_leader" => vec![(me_idx, Slot::Leader)],
        // 自リーダー or キャラ 1 体、 AI はリーダー優先 (effects.py:2948)
        "self_inplay_choice" => vec![(me_idx, Slot::Leader)],
        // 自キャラ 1 体、 AI は power 降順 (effects.py:2919)
        "one_self_character_any" => {
            let p = &state.players[me_idx];
            let mut cands: Vec<usize> = (0..p.characters.len()).collect();
            cands.sort_by(|&a, &b| p.characters[b].power().cmp(&p.characters[a].power()));
            cands.into_iter().take(1).map(|i| (me_idx, Slot::Char(i))).collect()
        }
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
            let mut power_le = parse_after(os, "power_le_"); // c.power() <= n
            // bare "character_le_N" (= power ≤ N、 opp_value sort、 effects.py:2425)
            if power_le.is_none() && cost_le.is_none() {
                if let Some(n) = parse_after(os, "character_le_") {
                    power_le = Some(n);
                }
            }
            // まだ認識できない filter token (_le_/_ge_ 残) は誤選択回避で bail。
            if cost_le.is_none() && power_le.is_none() && (os.contains("_le_") || os.contains("_ge_")) {
                return None;
            }
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
            // ⚠ Python は spec 毎に sort key が異なる: rested_character_power_le は _threat_key
            // (= power 降順、 effects.py:2716)、 それ以外 (cost_le 等) は _opp_value。 安定ソートで tie は
            // index 順 (= Python stable sort と一致)。
            if rested_only && power_le.is_some() {
                cands.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
            } else {
                cands.sort_by(|&a, &b| {
                    opp_value(&opp.characters[b])
                        .partial_cmp(&opp_value(&opp.characters[a]))
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
            }
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
            "feature_in" => v.as_array().map_or(false, |arr| {
                arr.iter().any(|x| x.as_str().map_or(false, |s| card.features.iter().any(|f| f == s)))
            }),
            "color" => card.color.iter().any(|x| Some(x.as_str()) == v.as_str()),
            // 属性は複数持ち ("斬/特") がある → Python の substring `in` に合わせる (effects.py:10607)
            "attribute" => v.as_str().map_or(false, |a| card.attribute.contains(a)),
            "cost_le" => (card.cost as i64) <= v.as_i64().unwrap_or(0),
            "cost_ge" => (card.cost as i64) >= v.as_i64().unwrap_or(0),
            "cost_eq" => (card.cost as i64) == v.as_i64().unwrap_or(-1),
            "power_le" => (card.power as i64) <= v.as_i64().unwrap_or(0),
            "power_ge" => (card.power as i64) >= v.as_i64().unwrap_or(0),
            "category" => Some(cat_str(&card.category)) == v.as_str(),
            "category_in" => v
                .as_array()
                .map_or(false, |arr| arr.iter().any(|x| x.as_str() == Some(cat_str(&card.category)))),
            "exclude_name" => match v {
                Value::String(s) => card.name != *s,
                Value::Array(a) => !a.iter().any(|x| x.as_str() == Some(card.name.as_str())),
                _ => true,
            },
            "name" => v.as_str() == Some(card.name.as_str()),
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

/// optional cost 1 つの数量+filter を取り出す (spec が int なら count のみ / dict なら count+filter)。
fn spec_count(cv: &Value, default: i64) -> usize {
    if let Some(n) = cv.as_i64() {
        n as usize
    } else {
        cv.get("count").and_then(|x| x.as_i64()).unwrap_or(default) as usize
    }
}

/// filter 付き spec の (filter Value, count) を Python 準拠で取り出す。
/// "filter" キーがあればそれ、 無ければ spec 全体 (count 除く) が filter。
fn filter_and_count(cv: &Value) -> (Value, usize) {
    let count = cv.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
    let filt = if let Some(f) = cv.get("filter") {
        f.clone()
    } else if let Some(obj) = cv.as_object() {
        let mut m = obj.clone();
        m.remove("count");
        Value::Object(m)
    } else {
        Value::Null
    };
    (filt, count)
}

/// optional_cost の 1 コストの支払い可能性を Python の can_pay elif 準拠で判定。
/// None = 未対応 cost 型 (呼出側は bail)、 Some(true/false)=対応済で払える/払えない。
/// ⚠ 決定的 (rng 無し) かつ cascade 無し の cost 型のみ対応。 それ以外 (trash_self_hand_random /
/// discard_hand / life 系 / return_self_* / chara_to_self_life / trash_to_deck 等) は None で bail。
fn cost_payable_one(cs: &Value, state: &GameState, me_idx: usize, src: Slot) -> Option<bool> {
    let obj = cs.as_object()?;
    let (k, cv) = obj.iter().next()?;
    let me = &state.players[me_idx];
    match k.as_str() {
        "pay_don" => {
            let n = cv.as_i64().unwrap_or(0) as i32;
            let cap = me.don_active + me.don_rested + me.leader.attached_dons
                + me.characters.iter().map(|c| c.attached_dons).sum::<i32>();
            Some(cap >= n)
        }
        "rest_self_don" => Some(me.don_active >= cv.as_i64().unwrap_or(0) as i32),
        "rest_self" => Some(!get_ip(me, src).rested), // self_inplay present && !rested
        "rest_self_target_name" | "rest_self_target" => {
            let name = cv.get("name").and_then(|x| x.as_str()).unwrap_or_else(|| cv.as_str().unwrap_or(""));
            Some(me.characters.iter().chain(me.stages.iter()).any(|ip| ip.card.name == name && !ip.rested))
        }
        "rest_self_leader_or_stage_filtered" => {
            let filt = cv.get("filter");
            Some((!me.leader.rested && matches_filter(&me.leader.card, filt))
                || me.stages.iter().any(|s| !s.rested && matches_filter(&s.card, filt)))
        }
        // Python は can_pay 未チェック (= 常に払える扱い、 実体無ければ payment で no-op)。
        "rest_self_leader_filtered_or_don" | "flip_life_face_up" | "flip_life_face_down"
        | "attach_active_don_to_named_chara" => Some(true),
        "rest_self_chara_filtered" => {
            let filt = cv.get("filter");
            Some(me.characters.iter().any(|c| !c.rested && matches_filter(&c.card, filt)))
        }
        "reveal_hand_with_filter" | "discard_hand_with_filter" => {
            let (filt, count) = filter_and_count(cv);
            Some(me.hand.iter().filter(|c| matches_filter(c, Some(&filt))).count() >= count)
        }
        _ => None, // 未対応 cost 型 → bail
    }
}

/// optional_cost の 1 コストを支払う (cost_payable_one が Some(true) を返した型のみ)。
/// None = 未対応 (bail)、 Some(())=支払い完了 (state 変更)。 payability と同じ型集合を網羅。
fn pay_cost_one(cs: &Value, state: &mut GameState, me_idx: usize, src: Slot) -> Option<()> {
    let (k, cv) = {
        let obj = cs.as_object()?;
        let (k, v) = obj.iter().next()?;
        (k.clone(), v.clone())
    };
    match k.as_str() {
        "pay_don" => {
            let n = cv.as_i64().unwrap_or(0) as i32;
            if n > 0 && !pay_don_field(state, me_idx, n) {
                return None;
            }
        }
        "rest_self_don" => {
            let n = cv.as_i64().unwrap_or(0) as i32;
            let me = &mut state.players[me_idx];
            let m = n.min(me.don_active);
            me.don_active -= m;
            me.don_rested += m;
        }
        "rest_self" => {
            if cv == Value::Bool(true) {
                let ip = get_ip_mut(&mut state.players[me_idx], src);
                if !ip.rested {
                    ip.rested = true;
                }
            }
        }
        "rest_self_target_name" | "rest_self_target" => {
            let name = cv.get("name").and_then(|x| x.as_str()).map(|s| s.to_string())
                .unwrap_or_else(|| cv.as_str().unwrap_or("").to_string());
            let me = &mut state.players[me_idx];
            let mut done = false;
            for i in 0..me.characters.len() {
                if me.characters[i].card.name == name && !me.characters[i].rested {
                    me.characters[i].rested = true;
                    done = true;
                    break;
                }
            }
            if !done {
                for i in 0..me.stages.len() {
                    if me.stages[i].card.name == name && !me.stages[i].rested {
                        me.stages[i].rested = true;
                        break;
                    }
                }
            }
        }
        "rest_self_leader_or_stage_filtered" => {
            let count = spec_count(&cv, 1);
            let filt = cv.get("filter");
            // pool 順 = [leader, stage0, stage1...]、 avail = active && filter 一致
            let mut avail: Vec<(Slot, bool)> = vec![]; // (slot, is_stage)
            {
                let me = &state.players[me_idx];
                if !me.leader.rested && matches_filter(&me.leader.card, filt) {
                    avail.push((Slot::Leader, false));
                }
                for i in 0..me.stages.len() {
                    if !me.stages[i].rested && matches_filter(&me.stages[i].card, filt) {
                        avail.push((Slot::Stage(i), true));
                    }
                }
            }
            // AI 簡易: ステージ優先 (key 0)、 leader 最後 (key 1)。 stable sort で元順維持。
            avail.sort_by_key(|(_, is_stage)| if *is_stage { 0 } else { 1 });
            for (sl, _) in avail.into_iter().take(count) {
                get_ip_mut(&mut state.players[me_idx], sl).rested = true;
            }
        }
        "rest_self_leader_filtered_or_don" => {
            let filt = cv.get("filter");
            let me = &mut state.players[me_idx];
            if me.don_active >= 1 {
                me.don_active -= 1;
                me.don_rested += 1;
            } else if !me.leader.rested && matches_filter(&me.leader.card, filt) {
                me.leader.rested = true;
            }
        }
        "rest_self_chara_filtered" => {
            let count = spec_count(&cv, 1);
            let filt = cv.get("filter");
            let mut avail: Vec<(i32, usize)> = vec![]; // (power, char_idx)
            {
                let me = &state.players[me_idx];
                for i in 0..me.characters.len() {
                    if !me.characters[i].rested && matches_filter(&me.characters[i].card, filt) {
                        avail.push((me.characters[i].power(), i));
                    }
                }
            }
            avail.sort_by_key(|(p, _)| *p); // power 昇順、 stable = 元順 tie-break
            for (_, i) in avail.into_iter().take(count) {
                state.players[me_idx].characters[i].rested = true;
            }
        }
        "flip_life_face_up" => {
            let me = &mut state.players[me_idx];
            me.face_up_life_count = (me.face_up_life_count + 1).min(me.life.len() as i32);
        }
        "flip_life_face_down" => {
            let me = &mut state.players[me_idx];
            me.face_up_life_count = (me.face_up_life_count.min(me.life.len() as i32) - 1).max(0);
        }
        "attach_active_don_to_named_chara" => {
            let name = cv.get("name").and_then(|x| x.as_str()).unwrap_or("").to_string();
            let n = cv.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32;
            let me = &mut state.players[me_idx];
            for i in 0..me.characters.len() {
                if me.characters[i].card.name == name {
                    let give = n.min(me.don_active);
                    me.don_active -= give;
                    me.characters[i].attached_dons += give;
                    break;
                }
            }
        }
        "reveal_hand_with_filter" => { /* 公開のみ = state 変更なし */ }
        "discard_hand_with_filter" => {
            let (filt, count) = filter_and_count(&cv);
            let me = &mut state.players[me_idx];
            let old = std::mem::take(&mut me.hand);
            let mut discarded = 0;
            for c in old {
                if discarded < count && matches_filter(&c, Some(&filt)) {
                    me.trash.push(c);
                    discarded += 1;
                } else {
                    me.hand.push(c);
                }
            }
        }
        _ => return None,
    }
    Some(())
}

/// テスト用: 単一 primitive を execute_effect で適用 (src=Leader placeholder)。 返り値 = 処理できたか。
pub fn apply_raw_effect(prim: &Value, state: &mut GameState, me_idx: usize) -> bool {
    execute_effect(prim, state, me_idx, Slot::Leader)
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
            // 公式「X することができる：Y」。 AI 経路 (self-play) = cost/effect 両方払える状態なら発動。
            let empty: Vec<Value> = vec![];
            let cost = v.get("cost").and_then(|x| x.as_array()).unwrap_or(&empty).clone();
            let effect = v.get("effect").and_then(|x| x.as_array()).unwrap_or(&empty).clone();
            // payability (Python can_pay): 全 cost 型が対応かつ払えるか。 未対応 cost 型は None → bail。
            let mut can_pay = true;
            for cs in &cost {
                match cost_payable_one(cs, state, me_idx, src) {
                    None => return false,           // 未対応 cost 型 → bail (誤適用ゼロ)
                    Some(false) => { can_pay = false; break; }
                    Some(true) => {}
                }
            }
            // should_fire 追加条件 (effects.py:8551): effect に hand_to_self_life && 手札空 → 不発
            let mut should_fire = can_pay;
            if should_fire {
                for es in &effect {
                    if es.get("hand_to_self_life").is_some() && state.players[me_idx].hand.is_empty() {
                        should_fire = false;
                        break;
                    }
                }
            }
            // 不発 = Python は return False (state 不変)。 overlay に if_prev_succeeded は 0 件なので
            // 返り値は次 prim に影響しない → no-op を true (match) 扱いにできる (payability は read-only)。
            if !should_fire {
                return true;
            }
            // cascade guard: pay_don の on_self_don_returned_to_deck + effect の nested cascade
            let has_pay_don = cost.iter().any(|c| c.get("pay_don").is_some());
            if has_pay_don && me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
                return false;
            }
            if effect_cascade_blocked(&effect, state, me_idx) {
                return false;
            }
            // cost 支払い (cost_specs 順)。 未対応は None → bail (cost 済でも apply_action Err で全破棄)
            for cs in &cost {
                if pay_cost_one(cs, state, me_idx, src).is_none() {
                    return false;
                }
            }
            // effect 発火 (未対応 prim は false → 呼出側で bail)
            for es in &effect {
                if !execute_effect(es, state, me_idx, src) {
                    return false;
                }
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
        // 自デッキシャッフル (effects.py:5411)。 Python rng.shuffle(me.deck) と同一列 (MT 復元) で並べ替え。
        "shuffle_self_deck" => {
            if !state.has_rng() {
                return false; // rng 未供給 → 再現不能で bail
            }
            let n = state.players[me_idx].deck.len();
            let perm = state.rng_mut().shuffle_perm(n);
            let me = &mut state.players[me_idx];
            let old = std::mem::take(&mut me.deck);
            // Python shuffle は in-place: 結果[i] = 元[perm[i]] (shuffle_perm と同じ index 置換)。
            me.deck = perm.iter().map(|&j| old[j].clone()).collect();
            me.known_bottom_card_ids.clear();
            me.known_top_card_ids.clear();
            true
        }
        // 相手手札からランダム N 枚トラッシュ (effects.py:3199 trash_opp_hand_random / 5347 force_opp_discard)。
        "trash_opp_hand_random" | "force_opp_discard" => {
            if !state.has_rng() {
                return false;
            }
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            for _ in 0..n {
                if state.players[opp_idx].hand.is_empty() {
                    break;
                }
                let len = state.players[opp_idx].hand.len() as u64;
                let idx = state.rng_mut().randrange(len) as usize;
                let c = state.players[opp_idx].hand.remove(idx);
                state.players[opp_idx].trash.push(c);
            }
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
        // 任意 discard で battle buff (effects.py:8003、 OP15-002 ルーシー/OP03-001 エース等)。
        // AI 経路 (self-play): filter マッチ手札の先頭 min(len,max=3) を捨て、 target に +amount_per*枚 (battle)。
        // ⚠ discard>0 で hand_discarded_by_effect_this_turn=true + on_self_hand_discarded cascade
        //   (cascade 有なら bail)。 0 枚 = 見送り (状態不変 = handled)。
        "optional_discard_hand_for_battle_buff" => {
            let default_filt = serde_json::json!({"category_in": ["EVENT", "STAGE"]});
            let filt = v.get("filter").unwrap_or(&default_filt);
            let amount_per = v.get("amount_per_discard").and_then(|x| x.as_i64()).unwrap_or(1000) as i32;
            let target_spec = v.get("target").cloned().unwrap_or_else(|| Value::String("self_leader".into()));
            let max_discard = v.get("max").and_then(|x| x.as_i64()).unwrap_or(3) as i32;
            let matching: Vec<usize> = {
                let me = &state.players[me_idx];
                (0..me.hand.len()).filter(|&i| matches_filter(&me.hand[i], Some(filt))).collect()
            };
            let discard_count = (matching.len() as i32).min(max_discard).max(0) as usize;
            if discard_count == 0 {
                return true; // 見送り = 状態不変
            }
            // cascade guard: me 場に on_self_hand_discarded があれば発火効果を要する → bail
            if me_board_has_when(state, me_idx, "on_self_hand_discarded") {
                return false;
            }
            let Some(targets) = resolve_target(Some(&target_spec), me_idx, opp_idx, src, state) else {
                return false;
            };
            // 先頭 discard_count 枚を捨て。 ⚠ trash への append は index 昇順 (Python discardable 順) に一致させる
            let remove_set: std::collections::BTreeSet<usize> = matching[..discard_count].iter().copied().collect();
            {
                let me = &mut state.players[me_idx];
                let hand = std::mem::take(&mut me.hand);
                let mut discarded = vec![];
                for (i, c) in hand.into_iter().enumerate() {
                    if remove_set.contains(&i) {
                        discarded.push(c);
                    } else {
                        me.hand.push(c);
                    }
                }
                for c in discarded {
                    me.trash.push(c);
                }
            }
            let buff = amount_per * discard_count as i32;
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).battle_buff += buff;
            }
            // trigger_on_self_hand_discarded の副作用 (flag、 cascade は bail 済)
            state.players[me_idx].hand_discarded_by_effect_this_turn = true;
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
        // プレイコスト軽減 (effects.py:5693)。 play_cost_reduction += n。
        "reduce_play_cost" => {
            let n = if let Some(o) = v.as_object() {
                o.get("amount").and_then(|x| x.as_i64()).unwrap_or(1) as i32
            } else {
                v.as_i64().unwrap_or(1) as i32
            };
            state.players[me_idx].play_cost_reduction += n;
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
        // このターン中キャラ登場禁止 (effects.py:5686、 OP14-020 緑ミホーク)。 Phase.END でクリア。
        "block_chara_play" => {
            state.players[me_idx].block_chara_play_until_turn_end = true;
            true
        }
        // 「その後、 <if> の場合、 <do>」 (effects.py:5952)。 条件成立で sub-do を発火。
        "conditional" => {
            let default_cond = serde_json::json!({});
            let cond = v.get("if").unwrap_or(&default_cond);
            match eval_condition(cond, state, me_idx, Some(src)) {
                Some(true) => {}
                Some(false) => return true, // 条件不成立 = 何もしない (= 再現済)
                None => return false,       // 条件 unknown = bail
            }
            let Some(dos) = v.get("do").and_then(|d| d.as_array()) else { return true };
            // nested prim の cascade guard (= 黙って間違えない)
            if effect_cascade_blocked(dos, state, me_idx) {
                return false;
            }
            for prim in dos {
                if !execute_effect(prim, state, me_idx, src) {
                    return false;
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
/// do-list が「未対応 cascade を起こす prim」を含むか (含むなら呼出側は bail = 黙って間違えない)。
/// cascade を起こす prim (draw/ko/return/rest) は、 該当 when を持つカードが場に無い時のみ再現可。
fn effect_cascade_blocked(dos: &[Value], state: &GameState, me_idx: usize) -> bool {
    let opp = 1 - me_idx;
    let has = |pi: usize, w: &str| me_board_has_when(state, pi, w);
    for prim in dos {
        let key = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("");
        let blocked = match key {
            "draw" => has(me_idx, "on_self_draw_non_draw_phase"),
            "ko" | "ko_multi" | "ko_all_others" => {
                has(me_idx, "on_opp_chara_ko")
                    || has(opp, "on_self_chara_ko")
                    || has(opp, "on_ko")
                    || has(opp, "replace_ko")
                    || has(opp, "replace_leave")
            }
            "return_to_hand" | "return_to_hand_multi" | "return_to_deck_bottom"
            | "return_to_deck_bottom_multi" => {
                has(opp, "on_self_chara_leave_by_self_effect") || has(opp, "replace_leave")
            }
            "rest" => has(me_idx, "on_self_rested") || has(opp, "on_self_rested"),
            _ => false,
        };
        if blocked {
            return true;
        }
    }
    false
}

/// card_id の指定 when 効果を fidelity 保証で実行 (on_play/main 共通)。 全効果を bit 完全再現できたら Ok、
/// できなければ Err (= 呼出側で apply_action bail、 黙って間違えない = correctness 保証)。 bail 条件:
///  - 条件 unknown (eval None) / cost 未対応種別 (pay None) / 未対応 primitive (execute_effect false) /
///    未対応 cascade (effect_cascade_blocked)。
/// ⚠ on_opp_chara_played 等の「登場/発動そのもの」由来の cascade は呼出側 (apply_action arm) で別途 guard。
fn execute_card_effects(
    state: &mut GameState,
    me_idx: usize,
    card_id: &str,
    when: &str,
    src: Slot,
) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let Some(effs) = ov.get(card_id) else { return Ok(()) };
    for eff in effs {
        if eff.get("when").and_then(|v| v.as_str()) != Some(when) {
            continue;
        }
        match eval_effect_conditions(eff, state, me_idx, Some(src)) {
            Some(true) => {}
            Some(false) => continue,       // 条件不成立 = Python も発動しない
            None => return Err(format!("{when} 条件 unknown ({card_id})")),
        }
        if let Some(cost) = eff.get("cost") {
            match pay_on_play_cost(cost, state, me_idx) {
                Some(true) => {}
                Some(false) => continue,   // cost 払えない = Python も skip
                None => return Err(format!("{when} cost 未対応 ({card_id})")),
            }
        }
        if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
            if effect_cascade_blocked(dos, state, me_idx) {
                return Err(format!("{when} cascade 未対応 ({card_id})"));
            }
            for prim in dos {
                if !execute_effect(prim, state, me_idx, src) {
                    let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("?");
                    return Err(format!("{when} primitive 未対応: {k} ({card_id})"));
                }
            }
        }
    }
    Ok(())
}

/// キャラ登場時の on_play 効果を実行 (effects.py:trigger_on_play)。 played_idx = me.characters の末尾。
/// 順序: ① 登場カード自身の on_play → ② on_self_chara_played(me 場)→ ③ on_opp_chara_played(opp 場)
/// (turn-first FIFO = Python の _maybe_resolve 順)。 各段 fire は fidelity 保証(未対応は Err で bail)。
pub fn execute_on_play(state: &mut GameState, me_idx: usize, played_idx: usize) -> Result<(), String> {
    let opp = 1 - me_idx;
    let card_id = state.players[me_idx].characters[played_idx].card.card_id.clone();
    // ① 登場カード自身の on_play (OP09-081 相手効果で無効化されていなければ)
    if !state.players[me_idx].opp_on_play_disabled_through_opp_turn {
        execute_card_effects(state, me_idx, &card_id, "on_play", Slot::Char(played_idx))?;
    }
    // ② on_self_chara_played(me)→ ③ on_opp_chara_played(opp)。 last_opp_chara_played_card は
    //   Python が cascade 完了後 None に戻すので Rust は触らず None 維持(= 一致)。
    fire_field_when(state, me_idx, "on_self_chara_played")?;
    fire_field_when(state, opp, "on_opp_chara_played")?;
    Ok(())
}

/// player の場に指定 when 効果を持つカードがあるか (draw cascade guard 用)。
fn me_board_has_when(state: &GameState, pi: usize, when: &str) -> bool {
    let p = &state.players[pi];
    std::iter::once(&p.leader)
        .chain(p.characters.iter())
        .chain(p.stages.iter())
        .any(|ip| card_has_when(&ip.card.card_id, when))
}

/// cost が空 (= costless、 任意/強制コスト無) か。
fn cost_is_empty(cost: &Value) -> bool {
    match cost {
        Value::Object(o) => o.is_empty(),
        Value::Array(a) => a.is_empty(),
        Value::Null => true,
        _ => false,
    }
}

/// on_attack トリガーで発火して安全 (= 更なる cascade を起こさず execute_effect が忠実再現) な primitive。
/// ko/return/rest(on_self_rested)/search/redirect 等は除外 (=呼出側 Err で bail)。 conditional/
/// optional_cost_then は内部で effect_cascade_blocked guard を持つので安全。
fn on_trigger_prim_safe(key: &str) -> bool {
    matches!(
        key,
        "power_pump" | "draw" | "give_keyword" | "add_don" | "add_don_active" | "add_rested_don"
            | "untap_don" | "cost_minus" | "attach_rested_don" | "mill_self_top"
            | "stay_rested_next_refresh" | "set_cannot_rest" | "set_cannot_attack" | "put_top_to_life"
            | "optional_discard_hand_for_battle_buff" | "conditional" | "optional_cost_then"
    )
}

/// 【アタック時】(on_attack) 効果を fidelity 保証で発火 (effects.py:trigger_on_attack、 self-play AI 経路)。
/// costless 効果のみ対応。 全効果を bit 忠実に再現できたら Ok、 できなければ Err (= 戦闘 bail、 差分テスト境界):
///  - cost(real/once_per_turn)持ち → 支払い/once tracking 不能で Err
///  - 条件 unknown(None) → Err
///  - cascade を起こす/未対応 primitive → Err
///  - draw で me 場に on_self_draw_non_draw_phase → cascade で Err
/// src = 攻撃者 Slot (self target 解決用)。 発火中に buff/keyword が乗るので呼出側は attacker を再スナップショットする。
pub fn fire_on_attack(
    state: &mut GameState,
    me_idx: usize,
    is_leader: bool,
    char_idx: usize,
) -> Result<(), String> {
    let src = if is_leader { Slot::Leader } else { Slot::Char(char_idx) };
    let Some(ov) = overlay() else { return Ok(()) };
    let cid = get_ip(&state.players[me_idx], src).card.card_id.clone();
    let Some(effs) = ov.get(&cid) else { return Ok(()) };
    // Python trigger_on_attack: ① 支払いフェーズ (idx 順) で cost を払い once を立てる → 発火 idx 収集
    //   ② 発火は sorted idx 順 (paid_indexes = sorted(set(...)))。 costless と cost 持ちを 1 event に統合。
    let mut fired: Vec<usize> = vec![];
    for (idx, eff) in effs.iter().enumerate() {
        if eff.get("when").and_then(|v| v.as_str()) != Some("on_attack") {
            continue;
        }
        let costless = eff.get("cost").map_or(true, cost_is_empty);
        if costless {
            // costless の top-level once は once_per_turn_used (canonical 除外) 依存 → 追跡不能で bail
            if eff.get("once_per_turn").is_some() {
                return Err("on_attack costless top-level once 未対応".into());
            }
            fired.push(idx); // 条件は発火フェーズで評価 (_execute_event と一致)
            continue;
        }
        // cost 持ち: 条件 → once gate (per-idx canonical) → 支払い → mark。 いずれか不成立で skip/bail。
        match eval_effect_conditions(eff, state, me_idx, Some(src)) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("on_attack 条件 unknown".into()),
        }
        let cost = eff.get("cost").unwrap();
        let once = cost.get("once_per_turn");
        if let Some(o) = once {
            if o.is_string() {
                return Err("on_attack cost string once 未対応".into()); // 共有キー = once_per_turn_used 依存
            }
            if o.as_bool() == Some(true)
                && get_ip(&state.players[me_idx], src).attack_once_used.contains(&(idx as i64))
            {
                continue; // ターン既発動
            }
        }
        // Python 12924: _can_pay_counter_cost で払えなければ skip (未対応 cost でも「払えない」なら bail せず一致)
        if !can_pay_counter_cost_full(state, me_idx, src, cost) {
            continue;
        }
        match try_pay_counter_cost(state, me_idx, src, cost)? {
            true => {}
            false => continue, // 払えない → 効果不発 (公式 4-10)
        }
        if once.and_then(|o| o.as_bool()) == Some(true) {
            get_ip_mut(&mut state.players[me_idx], src).mark_attack_once(idx as i64);
        }
        fired.push(idx);
    }
    // 発火フェーズ: sorted idx 順に条件再評価 + do 発火
    fired.sort_unstable();
    for idx in fired {
        let eff = &effs[idx];
        match eval_effect_conditions(eff, state, me_idx, Some(src)) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("on_attack fire 条件 unknown".into()),
        }
        let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
        fire_gated_do(state, me_idx, src, dos)?;
    }
    Ok(())
}

/// do-array を allow-list gate + draw cascade guard で発火。 全 prim 再現できたら Ok、 不能なら Err。
/// (execute_effect の false = 再現不能。 partial mutation は apply_action Err で全破棄 = 無害)。
fn fire_gated_do(
    state: &mut GameState,
    me_idx: usize,
    src: Slot,
    dos: &[Value],
) -> Result<(), String> {
    for prim in dos {
        let key = prim
            .as_object()
            .and_then(|o| o.keys().next())
            .map(|s| s.as_str())
            .unwrap_or("");
        if !on_trigger_prim_safe(key) {
            return Err(format!("trigger primitive 未対応: {key}"));
        }
        if key == "draw" && me_board_has_when(state, me_idx, "on_self_draw_non_draw_phase") {
            return Err("draw cascade (on_self_draw_non_draw_phase) 未対応".into());
        }
    }
    for prim in dos {
        if !execute_effect(prim, state, me_idx, src) {
            return Err("trigger primitive 再現不能".into());
        }
    }
    Ok(())
}

/// 【KO時】(on_ko) を発火 (effects.py:trigger_on_ko、 battle KO 経路 = by_opp_effect=false)。
/// victim は既に trash (source-gone) なので Slot::Leader を placeholder に player-level の安全 prim のみ発火。
/// chara_ko_taken_this_turn++ は battle_ko_character 側で実施済 (Python は trigger_on_ko で全 KO 分加算、 同義)。
/// ⚠ source-gone: src (=self) を参照する prim / target 系は placeholder=leader に誤解決するため
///   narrow allow-list (draw/add_don/add_rested_don/untap_don/mill_self_top/put_top_to_life = 全て
///   player-level で src 不使用) 限定。 cost / 未知条件 (by_opp_effect/by_battle/self_attached_don_ge 等) /
///   非対応 prim / draw cascade は Err で bail。 replace_ko/replace_leave は呼出側 (do_battle_ko) で先に bail。
pub fn fire_on_ko(state: &mut GameState, owner_idx: usize, victim_cid: &str) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let Some(effs) = ov.get(victim_cid) else { return Ok(()) };
    if !effs.iter().any(|e| e.get("when").and_then(|v| v.as_str()) == Some("on_ko")) {
        return Ok(());
    }
    for eff in effs {
        if eff.get("when").and_then(|v| v.as_str()) != Some("on_ko") {
            continue;
        }
        if eff.get("cost").map_or(false, |c| !cost_is_empty(c)) {
            return Err("on_ko cost 未対応 (source-gone)".into());
        }
        match eval_effect_conditions(eff, state, owner_idx, None) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("on_ko 条件 unknown".into()),
        }
        let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
        for prim in dos {
            let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("");
            // player-level (src 不使用) のみ許可。 target/self 系は placeholder=leader で誤解決するため bail。
            if !matches!(
                k,
                "draw" | "add_don" | "add_don_active" | "add_rested_don" | "untap_don"
                    | "mill_self_top" | "put_top_to_life"
            ) {
                return Err(format!("on_ko primitive 未対応 (source-gone): {k}"));
            }
            if k == "draw" && me_board_has_when(state, owner_idx, "on_self_draw_non_draw_phase") {
                return Err("on_ko draw cascade 未対応".into());
            }
        }
        for prim in dos {
            if !execute_effect(prim, state, owner_idx, Slot::Leader) {
                return Err("on_ko primitive 再現不能".into());
            }
        }
    }
    Ok(())
}

/// ライフカードの【トリガー】を発火 (effects.py:trigger_lifecard_trigger、 AI defender 経路)。
/// should_fire_trigger が Some(true) の時のみ呼ぶ。 戻り値 = kept_in_hand (to_hand_self_trigger で手札保持)。
/// ライフ札は zone limbo (source-gone) なので Slot::Leader placeholder + player-level 安全 prim のみ。
/// ⚠ bail 条件: attacker 場に opp_event_or_trigger_fired / defender 場に on_self_trigger_fired (cascade
///   未実装) / cost / top-level once_per_turn (once_per_turn_used=canonical除外 依存) / 未知条件 / play_self
///   等 target・self 系 prim / draw cascade。 = 保守的に「draw 等 player-level only の trigger」だけ発火。
pub fn fire_life_trigger(
    state: &mut GameState,
    defender_idx: usize,
    attacker_idx: usize,
    card_id: &str,
) -> Result<bool, String> {
    let Some(ov) = overlay() else { return Ok(false) };
    let Some(effs) = ov.get(card_id) else { return Ok(false) };
    // cascade guard (trigger 発火に伴う 2 系トリガー = 未実装)
    if me_board_has_when(state, attacker_idx, "opp_event_or_trigger_fired") {
        return Err("life trigger cascade (opp_event_or_trigger_fired) 未対応".into());
    }
    if me_board_has_when(state, defender_idx, "on_self_trigger_fired") {
        return Err("life trigger cascade (on_self_trigger_fired) 未対応".into());
    }
    let mut kept_in_hand = false;
    for eff in effs {
        if eff.get("when").and_then(|v| v.as_str()) != Some("trigger") {
            continue;
        }
        if eff.get("cost").map_or(false, |c| !cost_is_empty(c)) {
            return Err("life trigger cost 未対応".into());
        }
        if eff.get("once_per_turn").is_some() {
            return Err("life trigger once 未対応".into()); // once_per_turn_used = canonical 除外 依存
        }
        match eval_effect_conditions(eff, state, defender_idx, None) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("life trigger 条件 unknown".into()),
        }
        let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
        // safe prim check (source-gone player-level)。 to_hand_self_trigger は routing flag のみ。
        for prim in dos {
            let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("");
            if k == "to_hand_self_trigger" {
                continue;
            }
            if !matches!(
                k,
                "draw" | "add_don" | "add_don_active" | "add_rested_don" | "untap_don"
                    | "mill_self_top" | "put_top_to_life"
            ) {
                return Err(format!("life trigger primitive 未対応 (source-gone): {k}"));
            }
            if k == "draw" && me_board_has_when(state, defender_idx, "on_self_draw_non_draw_phase") {
                return Err("life trigger draw cascade 未対応".into());
            }
        }
        for prim in dos {
            let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("");
            if k == "to_hand_self_trigger" {
                kept_in_hand = true; // このカードを手札に加える (trash でなく hand へ)
                continue;
            }
            if !execute_effect(prim, state, defender_idx, Slot::Leader) {
                return Err("life trigger primitive 再現不能".into());
            }
        }
    }
    Ok(kept_in_hand)
}

/// JSON 値の truthy 判定 (Python の `if cost.get(k)` 相当: null/false/0/空 以外)。
fn json_truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map_or(true, |f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// on_attack/opp_attack/counter の cost dict を支払う (effects.py:_can_pay_counter_cost + _pay_counter_cost)。
/// Ok(true)=支払い完了 (state 変更)、 Ok(false)=払えない (効果 skip、 state 不変)、 Err=未対応/cascade (bail)。
/// 決定的・非 cascade の subset のみ対応。 once_per_turn key は呼出側で処理済 (ここでは無視)。
/// ⚠ discard_hand / discard_hand_with_filter / trash_self / self_ko / return_self_don_to_deck 等
///    (cascade or AI heuristic 依存) は未対応 key として Err で bail。
fn try_pay_counter_cost(
    state: &mut GameState,
    me_idx: usize,
    self_src: Slot,
    cost: &Value,
) -> Result<bool, String> {
    let Some(obj) = cost.as_object() else { return Ok(true) };
    // 認識できる key のみ (それ以外は Python では無視だが、 誤発火防止で bail)
    for k in obj.keys() {
        if !matches!(
            k.as_str(),
            "once_per_turn" | "pay_don" | "rest_self_don" | "rest_self"
                | "life_to_hand" | "life_top_or_bottom_to_hand" | "trash_to_deck"
                | "reveal_hand_with_filter" | "flip_life_face_down" | "flip_life_face_up"
        ) {
            return Err(format!("counter cost 未対応: {k}"));
        }
    }
    let gi = |k: &str| obj.get(k).and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    let pay_don = gi("pay_don");
    let rest_don = gi("rest_self_don");
    let lth = gi("life_to_hand");
    let ltob = gi("life_top_or_bottom_to_hand");
    let ttd = gi("trash_to_deck");
    let rest_self = obj.get("rest_self").map_or(false, json_truthy);
    let flip_down = obj.get("flip_life_face_down").map_or(false, json_truthy);
    let flip_up = obj.get("flip_life_face_up").map_or(false, json_truthy);
    // --- payability (_can_pay_counter_cost)。 一つでも払えなければ Ok(false) (効果 skip) ---
    {
        let me = &state.players[me_idx];
        let cap = me.don_active + me.don_rested + me.leader.attached_dons
            + me.characters.iter().map(|c| c.attached_dons).sum::<i32>();
        if pay_don > 0 && cap < pay_don {
            return Ok(false);
        }
        if rest_don > 0 && me.don_active < rest_don {
            return Ok(false);
        }
        if rest_self && get_ip(me, self_src).rested {
            return Ok(false);
        }
        if lth > 0 && (me.life.len() as i32) < lth {
            return Ok(false);
        }
        if ltob > 0 && (me.life.len() as i32) < ltob {
            return Ok(false);
        }
        if ttd > 0 && (me.trash.len() as i32) < ttd {
            return Ok(false);
        }
        if let Some(rhf) = obj.get("reveal_hand_with_filter") {
            if rhf.is_object() {
                let (filt, cnt) = filter_and_count(rhf);
                if me.hand.iter().filter(|c| matches_filter(c, Some(&filt))).count() < cnt {
                    return Ok(false);
                }
            }
        }
        if flip_down && me.face_up_life_count.min(me.life.len() as i32) < 1 {
            return Ok(false);
        }
        if flip_up {
            let fu = me.face_up_life_count.min(me.life.len() as i32);
            if (me.life.len() as i32) - fu < 1 {
                return Ok(false);
            }
        }
    }
    // --- cascade guard: pay_don は on_self_don_returned_to_deck を発火しうる ---
    if pay_don > 0 && me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
        return Err("counter cost pay_don cascade 未対応".into());
    }
    // --- pay (Python _pay_counter_cost の順: pay_don→rest_don→rest_self→life→trash_to_deck→flip) ---
    if pay_don > 0 && !pay_don_field(state, me_idx, pay_don) {
        return Err("pay_don 支払い不能".into());
    }
    if rest_don > 0 {
        let me = &mut state.players[me_idx];
        let a = rest_don.min(me.don_active);
        me.don_active -= a;
        me.don_rested += a;
    }
    if rest_self {
        get_ip_mut(&mut state.players[me_idx], self_src).rested = true;
    }
    let lth_total = lth + ltob;
    if lth_total > 0 {
        let me = &mut state.players[me_idx];
        let a = lth_total.min(me.life.len() as i32);
        for _ in 0..a {
            let c = me.life.remove(0);
            me.hand.push(c);
        }
    }
    if ttd > 0 {
        let me = &mut state.players[me_idx];
        let a = ttd.min(me.trash.len() as i32);
        for _ in 0..a {
            let c = me.trash.remove(0);
            me.deck.push(c);
        }
    }
    // reveal_hand_with_filter = 公開のみ (state 変更なし)
    if flip_down {
        let me = &mut state.players[me_idx];
        me.face_up_life_count = (me.face_up_life_count.min(me.life.len() as i32) - 1).max(0);
    }
    if flip_up {
        let me = &mut state.players[me_idx];
        me.face_up_life_count = (me.face_up_life_count + 1).min(me.life.len() as i32);
    }
    Ok(true)
}

/// counter cost 全 key の支払い可能性のみ判定 (effects.py:_can_pay_counter_cost 完全ミラー、 state 不変)。
/// 未対応 key (discard_hand/trash_self 等) も payability だけ確認 → 「払えない未対応 cost」を bail でなく
/// skip にできる (Python は払えなければ continue するため)。 未対応 key の実支払いは try_pay_counter_cost が Err。
fn can_pay_counter_cost_full(
    state: &GameState,
    me_idx: usize,
    self_src: Slot,
    cost: &Value,
) -> bool {
    let Some(obj) = cost.as_object() else { return true };
    let gi = |k: &str| obj.get(k).and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    let me = &state.players[me_idx];
    let discard_n = gi("discard_hand");
    if discard_n > 0 && (me.hand.len() as i32) < discard_n {
        return false;
    }
    let pay_don = gi("pay_don");
    let cap = me.don_active + me.don_rested + me.leader.attached_dons
        + me.characters.iter().map(|c| c.attached_dons).sum::<i32>();
    if pay_don > 0 && cap < pay_don {
        return false;
    }
    let rest_don = gi("rest_self_don");
    if rest_don > 0 && me.don_active < rest_don {
        return false;
    }
    if let Some(dwf) = obj.get("discard_hand_with_filter").filter(|v| v.is_object()) {
        let (filt, cnt) = filter_and_count(dwf);
        if me.hand.iter().filter(|c| matches_filter(c, Some(&filt))).count() < cnt {
            return false;
        }
    }
    if obj.get("rest_self").map_or(false, json_truthy) && get_ip(me, self_src).rested {
        return false;
    }
    let rdon = gi("return_self_don_to_deck");
    if rdon > 0 && (me.don_active + me.don_rested) < rdon {
        return false;
    }
    let lth = gi("life_to_hand");
    if lth > 0 && (me.life.len() as i32) < lth {
        return false;
    }
    let ltob = gi("life_top_or_bottom_to_hand");
    if ltob > 0 && (me.life.len() as i32) < ltob {
        return false;
    }
    let ttd = gi("trash_to_deck");
    if ttd > 0 && (me.trash.len() as i32) < ttd {
        return false;
    }
    if let Some(rhf) = obj.get("reveal_hand_with_filter").filter(|v| v.is_object()) {
        let (filt, cnt) = filter_and_count(rhf);
        if me.hand.iter().filter(|c| matches_filter(c, Some(&filt))).count() < cnt {
            return false;
        }
    }
    // trash_self/self_ko: Python は self_inplay is None で払えない判定。 on/opp_attack の source は
    //   常に present なのでここでは payable (実支払いは try_pay が Err = cascade で bail)。
    if obj.get("flip_life_face_down").map_or(false, json_truthy)
        && me.face_up_life_count.min(me.life.len() as i32) < 1
    {
        return false;
    }
    if obj.get("flip_life_face_up").map_or(false, json_truthy) {
        let fu = me.face_up_life_count.min(me.life.len() as i32);
        if (me.life.len() as i32) - fu < 1 {
            return false;
        }
    }
    true
}

/// effects.py:_ai_should_fire_opp_attack_cost = AI defender が cost 付き opp_attack 効果を発動すべきか EV 判定。
/// state だけ読む自己完結ヒューリスティック (bit 忠実移植)。 ⚠ ONEPIECE_NO_OVERDEFENSE_SKIP 未設定 (差分テスト
/// 既定) = 過剰防御 skip 有効で移植。
fn ai_should_fire_opp_attack_cost(
    eff: &Value,
    source_power: i32,
    attacker_power: i32,
    attacker_cost: i32,
    defended_power: i32,
    life_count: i32,
) -> bool {
    let cost = eff.get("cost").and_then(|c| c.as_object());
    let gc = |k: &str| cost.and_then(|c| c.get(k)).and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    let pay_don = gc("pay_don");
    let rest_don = gc("rest_self_don");
    let discard_n = gc("discard_hand");
    let cost_value = pay_don * 800 + rest_don * 400 + discard_n * 1500;

    let empty: Vec<Value> = vec![];
    let do_list = eff.get("do").and_then(|v| v.as_array()).unwrap_or(&empty);
    let mut do_keys: std::collections::BTreeSet<&str> = std::collections::BTreeSet::new();
    for prim in do_list {
        if let Some(o) = prim.as_object() {
            for k in o.keys() {
                do_keys.insert(k.as_str());
            }
        }
    }
    let has = |keys: &[&str]| keys.iter().any(|k| do_keys.contains(k));

    // 過剰防御防止: 効果が power_pump のみ + 全 battle duration + 効果無しでも耐える → skip
    if do_keys.len() == 1 && do_keys.contains("power_pump") {
        let all_battle = do_list
            .iter()
            .filter(|p| p.get("power_pump").is_some())
            .all(|p| {
                p.get("power_pump")
                    .and_then(|pp| pp.get("duration"))
                    .and_then(|d| d.as_str())
                    == Some("battle")
            });
        if all_battle && defended_power > attacker_power {
            return false;
        }
    }

    let mut benefit = 0;
    if has(&["ko", "ko_multi", "return_to_hand", "return_to_hand_multi"]) {
        let ac = if attacker_cost > 0 { attacker_cost } else { 3 };
        benefit += ac * 1000;
    }
    if do_keys.contains("power_pump") {
        benefit += 2000;
    }
    if has(&["give_keyword", "give_rush"]) {
        benefit += 2500;
    }
    if has(&["draw", "search", "search_top_n"]) {
        benefit += 1500;
    }
    if has(&["prevent_ko", "set_ko_immune", "set_ko_immune_timed", "set_ko_immune_battle_only"]) {
        benefit += if life_count <= 1 { 5000 } else if life_count <= 2 { 3000 } else { 1500 };
    }
    if has(&["add_don", "attach_don", "attach_active_don"]) {
        benefit += 1000;
    }
    if do_keys.contains("redirect_attack") {
        benefit += if life_count <= 1 { 4000 } else if life_count <= 2 { 3000 } else { 2000 };
    }
    // 攻撃確実失敗推定 (発動不要)
    if source_power > 0 && attacker_power + 2000 < source_power {
        return false;
    }
    if life_count <= 1 {
        benefit += 2000;
    }
    benefit > cost_value
}

/// owner の場 (leader→char→stage) の指定 when 効果を発火 (effects.py:_enqueue_field_when + _execute_event
/// の自己完結版)。 costless + 条件成立 + 再現可能 prim のみ発火。 cost/once_per_turn/条件unknown/未対応prim は
/// Err で bail。 source は場のカード (= self_inplay 有、 on_ko と違い src target 解決可)。 cascade nesting は
/// 発火 prim が更に enqueue しない前提 (allow-list が cascade prim を除外)。
pub fn fire_field_when(state: &mut GameState, owner_idx: usize, when: &str) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let n_char = state.players[owner_idx].characters.len();
    let n_stage = state.players[owner_idx].stages.len();
    let mut slots: Vec<Slot> = vec![Slot::Leader];
    slots.extend((0..n_char).map(Slot::Char));
    slots.extend((0..n_stage).map(Slot::Stage));
    for slot in slots {
        let cid = get_ip(&state.players[owner_idx], slot).card.card_id.clone();
        let Some(effs) = ov.get(&cid) else { continue };
        for eff in effs {
            if eff.get("when").and_then(|v| v.as_str()) != Some(when) {
                continue;
            }
            // cost 持ち (once_per_turn 含む) は支払い/追跡が要る → bail
            if let Some(cost) = eff.get("cost") {
                if !cost_is_empty(cost) {
                    return Err(format!("{when} cost 未対応"));
                }
            }
            if eff.get("once_per_turn").is_some() {
                return Err(format!("{when} once_per_turn 未対応"));
            }
            match eval_effect_conditions(eff, state, owner_idx, Some(slot)) {
                Some(true) => {}
                Some(false) => continue,
                None => return Err(format!("{when} 条件 unknown")),
            }
            let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
            fire_gated_do(state, owner_idx, slot, dos)?;
        }
    }
    Ok(())
}

/// 【相手のアタック時】(opp_attack / opp_attack_on_leader / opp_attack_on_chara) を発火 (effects.py:
/// _enqueue_opp_attack_with_cost、 self-play AI 経路)。 全て bit 忠実に再現できたら Ok、 できなければ Err。
///  - costless: 条件成立なら発火 (allow-list、 未対応 target/prim は Err)
///  - cost 持ち: ai_should_fire ヒューリスティックで判定 → skip(=何もしない)なら一致、 fire なら Err
///    (cost 支払い + cascade + 防御 target 解決が要る = 未対応で bail)
///  走査順 = leader → characters → stages (_enqueue_opp_attack_with_cost)。
pub fn fire_opp_attack(
    state: &mut GameState,
    defender_idx: usize,
    when_key: &str,
    attacker_power: i32,
    attacker_cost: i32,
    defended_power: i32,
) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let n_char = state.players[defender_idx].characters.len();
    let n_stage = state.players[defender_idx].stages.len();
    let mut slots: Vec<Slot> = vec![Slot::Leader];
    slots.extend((0..n_char).map(Slot::Char));
    slots.extend((0..n_stage).map(Slot::Stage));
    let life_count = state.players[defender_idx].life.len() as i32;
    // ⚠ Python _enqueue_opp_attack_with_cost: 全 source (leader→chars→stages) の【支払いフェーズ】を
    //   先に回してから、 enqueue した event を後で resolve する = 全 cost 支払いが全 fire に先行する。
    //   これを per-slot 完結にすると、 先に fire した costless(例 OP15-002 の discard)が後続 stage の
    //   discard cost payability を狂わせ MISMATCH になる。 よって collect は全 slot を跨いで行い、
    //   fire は collect 完了後に (slot→idx 順 = source→sorted idx 順で) 実行する。
    let mut fired: Vec<(Slot, usize)> = vec![];
    for slot in slots {
        let cid = get_ip(&state.players[defender_idx], slot).card.card_id.clone();
        let Some(effs) = ov.get(&cid) else { continue };
        for (idx, eff) in effs.iter().enumerate() {
            if eff.get("when").and_then(|v| v.as_str()) != Some(when_key) {
                continue;
            }
            let costless = eff.get("cost").map_or(true, cost_is_empty);
            if costless {
                // costless top-level once は once_per_turn_used (canonical 除外) 依存 → bail
                if eff.get("once_per_turn").is_some() {
                    return Err("opp_attack costless top-level once 未対応".into());
                }
                fired.push((slot, idx)); // 条件は発火フェーズで評価 (_execute_event と一致)
                continue;
            }
            // cost 持ち (AI 経路): 条件 → once gate → can_pay skip → AI EV skip → 支払い → mark
            match eval_effect_conditions(eff, state, defender_idx, Some(slot)) {
                Some(true) => {}
                Some(false) => continue,
                None => return Err("opp_attack 条件 unknown".into()),
            }
            let cost = eff.get("cost").unwrap();
            let once = cost.get("once_per_turn");
            if let Some(o) = once {
                if o.is_string() {
                    return Err("opp_attack cost string once 未対応".into());
                }
                if o.as_bool() == Some(true)
                    && get_ip(&state.players[defender_idx], slot)
                        .attack_once_used
                        .contains(&(idx as i64))
                {
                    continue; // ターン既発動
                }
            }
            // Python 11690: 払えなければ skip (未対応 cost でも「払えない」なら bail せず一致)
            if !can_pay_counter_cost_full(state, defender_idx, slot, cost) {
                continue;
            }
            // AI EV 判定: 発動価値が低ければ skip (= Python _ai_should_fire_opp_attack_cost)
            let src_power = get_ip(&state.players[defender_idx], slot).power();
            if !ai_should_fire_opp_attack_cost(
                eff, src_power, attacker_power, attacker_cost, defended_power, life_count,
            ) {
                continue;
            }
            // 支払い (未対応 cost = discard/trash_self 等は Err で bail)
            match try_pay_counter_cost(state, defender_idx, slot, cost)? {
                true => {}
                false => continue,
            }
            if once.and_then(|o| o.as_bool()) == Some(true) {
                get_ip_mut(&mut state.players[defender_idx], slot).mark_attack_once(idx as i64);
            }
            fired.push((slot, idx));
        }
    }
    // 発火フェーズ: 収集順 (slot→idx = source→sorted idx) に条件再評価 + do 発火
    for (slot, idx) in fired {
        let cid = get_ip(&state.players[defender_idx], slot).card.card_id.clone();
        let Some(effs) = ov.get(&cid) else { continue };
        let eff = &effs[idx];
        match eval_effect_conditions(eff, state, defender_idx, Some(slot)) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("opp_attack fire 条件 unknown".into()),
        }
        let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
        fire_gated_do(state, defender_idx, slot, dos)?;
    }
    Ok(())
}

/// メインイベントの効果を実行 (effects.py:trigger_main_event)。 event はトラッシュ済 = src は leader 仮 placeholder。
pub fn execute_main_event(state: &mut GameState, me_idx: usize, card_id: &str) -> Result<(), String> {
    let opp = 1 - me_idx;
    if me_board_has_when(state, me_idx, "on_self_event_played")
        || me_board_has_when(state, opp, "opp_event_or_trigger_fired")
    {
        return Err("on_self_event_played/opp_event_or_trigger cascade 未対応".into());
    }
    execute_card_effects(state, me_idx, card_id, "main", Slot::Leader)
}

/// ステージ登場時の on_play 効果を実行 (game.py:PlayStage → trigger_on_play)。 played_idx = me.stages の末尾。
pub fn execute_stage_on_play(state: &mut GameState, me_idx: usize, played_idx: usize) -> Result<(), String> {
    let card_id = state.players[me_idx].stages[played_idx].card.card_id.clone();
    execute_card_effects(state, me_idx, &card_id, "on_play", Slot::Stage(played_idx))
}

/// 起動メイン発火 (effects.py:fire_activate_main)。 effect_index の効果を cost 支払い→do 実行。
/// ⚠ rest_self/pay_don/rest_self_don cost のみ対応 (trash_self/discard 等は skip)。 cascade は未対応。
pub fn fire_activate_main(
    state: &mut GameState,
    me_idx: usize,
    card_id: &str,
    effect_index: usize,
    source_kind: &str,
    source_idx: usize,
) -> Result<(), String> {
    let src = match source_kind {
        "leader" => Slot::Leader,
        "char" => Slot::Char(source_idx),
        "stage" => Slot::Stage(source_idx),
        _ => return Err("bad source_kind".into()),
    };
    let (cost, dos): (Option<Value>, Vec<Value>) = {
        let Some(ov) = overlay() else { return Ok(()) };
        let Some(effs) = ov.get(card_id) else { return Ok(()) };
        let Some(eff) = effs.get(effect_index) else { return Err("effect_index 範囲外".into()) };
        (
            eff.get("cost").cloned(),
            eff.get("do").and_then(|v| v.as_array()).cloned().unwrap_or_default(),
        )
    };
    // cost 支払い。 未対応 cost 種別 or cascade を起こす cost は bail (黙って間違えない)。
    if let Some(c) = &cost {
        if let Some(o) = c.as_object() {
            for k in o.keys() {
                if !matches!(k.as_str(), "rest_self" | "pay_don" | "rest_self_don" | "once_per_turn" | "rest_own_card") {
                    return Err(format!("activate_main cost 未対応: {k} ({card_id})"));
                }
            }
        }
        // pay_don は on_self_don_returned_to_deck cascade を起こす → 該当時 bail
        let pay_don = c.get("pay_don").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
        if pay_don > 0 && me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
            return Err("activate_main pay_don cascade 未対応".into());
        }
        if c.get("rest_self").and_then(|v| v.as_bool()).unwrap_or(false) {
            get_ip_mut(&mut state.players[me_idx], src).rested = true;
        }
        if pay_don > 0 {
            let me = &mut state.players[me_idx];
            let taken = pay_don.min(me.don_active);
            me.don_active -= taken;
            me.don_remaining_in_deck += taken;
            let more = (pay_don - taken).min(me.don_rested);
            me.don_rested -= more;
            me.don_remaining_in_deck += more;
        }
        let rest_don = c.get("rest_self_don").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
        if rest_don > 0 {
            let me = &mut state.players[me_idx];
            let n = rest_don.min(me.don_active);
            me.don_active -= n;
            me.don_rested += n;
        }
        // rest_own_card: 自分のアクティブカード count 枚をレスト。 AI は 非リーダー + power 昇順
        // (= リーダー/高power キャラ温存、 effects.py:13720)。 直接 rested = 無 cascade。
        if let Some(ro) = c.get("rest_own_card") {
            let (ro_n, ro_filt) = if let Some(o) = ro.as_object() {
                (o.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize, o.get("filter"))
            } else {
                (ro.as_i64().unwrap_or(1) as usize, None)
            };
            // pool = active leader+chars+stages (matches filter)、 (is_leader, power, Slot)
            let mut pool: Vec<(bool, i32, Slot)> = vec![];
            {
                let me = &state.players[me_idx];
                if !me.leader.rested && matches_filter(&me.leader.card, ro_filt) {
                    pool.push((true, me.leader.power(), Slot::Leader));
                }
                for i in 0..me.characters.len() {
                    let ch = &me.characters[i];
                    if !ch.rested && matches_filter(&ch.card, ro_filt) {
                        pool.push((false, ch.power(), Slot::Char(i)));
                    }
                }
                for i in 0..me.stages.len() {
                    let s = &me.stages[i];
                    if !s.rested && matches_filter(&s.card, ro_filt) {
                        pool.push((false, s.power(), Slot::Stage(i)));
                    }
                }
            }
            if pool.len() < ro_n {
                return Err("rest_own_card 支払い不能".into());
            }
            // (is_leader?1:0, power) 昇順 (安定 = pool 順 tie-break)
            pool.sort_by(|a, b| (a.0 as i32, a.1).cmp(&(b.0 as i32, b.1)));
            for (_, _, sl) in pool.into_iter().take(ro_n) {
                get_ip_mut(&mut state.players[me_idx], sl).rested = true;
            }
        }
    }
    // once_per_turn フラグ (effects.py:13726、 default True で発動済マーク)
    let once = cost.as_ref().and_then(|c| c.get("once_per_turn")).and_then(|v| v.as_bool()).unwrap_or(true);
    if once {
        get_ip_mut(&mut state.players[me_idx], src).act_used = true;
    }
    // do: cascade guard + prim gating
    if effect_cascade_blocked(&dos, state, me_idx) {
        return Err(format!("activate_main cascade 未対応 ({card_id})"));
    }
    for prim in &dos {
        if !execute_effect(prim, state, me_idx, src) {
            let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("?");
            return Err(format!("activate_main primitive 未対応: {k} ({card_id})"));
        }
    }
    Ok(())
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
                match eval_effect_conditions(eff, state, me_idx, Some(src)) {
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

// ============================ legal_actions (game.py:833 の port) ============================
use crate::state::{CardDef, Phase};
use serde_json::json;

/// 手札時のカード固有コスト軽減 (overlay when:"in_hand" の in_hand_cost_minus/plus)。
fn in_hand_cost_minus(state: &GameState, me_idx: usize, card: &CardDef) -> i32 {
    let Some(ov) = overlay() else { return 0 };
    let Some(effs) = ov.get(&card.card_id) else { return 0 };
    let mut total = 0;
    for eff in effs {
        if eff.get("when").and_then(|v| v.as_str()) != Some("in_hand") {
            continue;
        }
        if let Some(cond) = eff.get("if") {
            if eval_condition(cond, state, me_idx, None) != Some(true) {
                continue;
            }
        }
        if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
            for prim in dos {
                let Some(o) = prim.as_object() else { continue };
                if let Some(v) = o.get("in_hand_cost_minus") {
                    total += v.as_i64().or_else(|| v.get("amount").and_then(|x| x.as_i64())).unwrap_or(0) as i32;
                } else if let Some(v) = o.get("in_hand_cost_plus") {
                    total -= v.as_i64().or_else(|| v.get("amount").and_then(|x| x.as_i64())).unwrap_or(0) as i32;
                }
            }
        }
    }
    total
}

/// game.py:_eff_cost = card.cost - play_cost_reduction - in_hand - filtered_reduction (>=0)。
pub fn eff_cost(state: &GameState, me_idx: usize, card: &CardDef) -> i32 {
    let me = &state.players[me_idx];
    let mut filtered = 0i32;
    for r in me.play_cost_reductions_filtered.iter().chain(me.play_cost_reductions_filtered_turn.iter()) {
        if matches_filter(card, r.get("filter")) {
            filtered += r.get("amount").and_then(|x| x.as_i64()).unwrap_or(0) as i32;
        }
    }
    (card.cost - me.play_cost_reduction - in_hand_cost_minus(state, me_idx, card) - filtered).max(0)
}

/// 場のドン返却可能総数 (active+rested+全付与ドン)。 pay_don cost 判定用。
fn pay_don_capacity(me: &Player) -> i32 {
    me.don_active + me.don_rested + me.leader.attached_dons
        + me.characters.iter().map(|c| c.attached_dons).sum::<i32>()
}

/// effects.py:_can_pay_activate_cost = activate_main の cost を支払えるか。
fn can_pay_activate_cost(state: &GameState, me_idx: usize, ip: &InPlay, on_field: bool, cost: &Value) -> bool {
    let me = &state.players[me_idx];
    let Some(o) = cost.as_object() else { return true };
    let gi = |k: &str| o.get(k).and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    let gb = |k: &str| o.get(k).and_then(|v| v.as_bool()).unwrap_or(false);
    if gb("rest_self") && ip.rested {
        return false;
    }
    if gb("trash_self") && !on_field {
        return false;
    }
    if gi("pay_don") > 0 && pay_don_capacity(me) < gi("pay_don") {
        return false;
    }
    if gi("rest_self_don") > 0 && me.don_active < gi("rest_self_don") {
        return false;
    }
    if gi("trash_to_deck") > 0 && (me.trash.len() as i32) < gi("trash_to_deck") {
        return false;
    }
    if gb("return_self_to_hand") && !on_field {
        return false;
    }
    if gi("discard_hand") > 0 && (me.hand.len() as i32) < gi("discard_hand") {
        return false;
    }
    if let Some(dfs) = o.get("discard_hand_with_filter").and_then(|v| v.as_object()) {
        let d_filt = dfs.get("filter");
        let d_count = dfs.get("count").and_then(|v| v.as_i64()).unwrap_or(1) as usize;
        let matching = me.hand.iter().filter(|c| matches_filter(c, d_filt)).count();
        if matching < d_count {
            return false;
        }
    }
    // reveal_hand_with_filter: 該当手札 count 枚以上 (公開のみ、 消費なし)
    if let Some(rfs) = o.get("reveal_hand_with_filter").and_then(|v| v.as_object()) {
        let r_filt = rfs.get("filter");
        let r_count = rfs.get("count").and_then(|v| v.as_i64()).unwrap_or(1) as usize;
        if me.hand.iter().filter(|c| matches_filter(c, r_filt)).count() < r_count {
            return false;
        }
    }
    // ko_self_with_filter: filter 一致の自キャラ 1 枚以上必要 (value 自体が filter)
    if let Some(kf) = o.get("ko_self_with_filter") {
        if !me.characters.iter().any(|c| matches_filter(&c.card, Some(kf))) {
            return false;
        }
    }
    // rest_self_target_name / rest_self_target: name 一致 + アクティブが 1 枚以上必要
    if let Some(rn) = o.get("rest_self_target_name").or_else(|| o.get("rest_self_target")) {
        let name = rn.get("name").and_then(|v| v.as_str()).or_else(|| rn.as_str()).unwrap_or("");
        let ok = me.characters.iter().chain(me.stages.iter())
            .any(|ip| ip.card.name == name && !ip.rested);
        if !ok {
            return false;
        }
    }
    // rest_own_card: filter 一致のアクティブな自カード (leader/char/stage) が count 枚以上必要
    if let Some(ro) = o.get("rest_own_card") {
        let n = ro.get("count").and_then(|v| v.as_i64()).unwrap_or(1) as usize;
        let ro_filt = ro.get("filter");
        let pool = std::iter::once(&me.leader).chain(me.characters.iter()).chain(me.stages.iter())
            .filter(|ip| !ip.rested && matches_filter(&ip.card, ro_filt))
            .count();
        if pool < n {
            return false;
        }
    }
    // once_per_turn (default True) ゲート: 発動済なら払えない (effects.py:13096)。
    let once = o.get("once_per_turn").and_then(|v| v.as_bool()).unwrap_or(true);
    if once && ip.act_used {
        return false;
    }
    true
}

/// game.py:legal_actions の port (canonical action dict の list を返す)。 self-play (human_player_idx=None) の
/// AI モード相当 (sacrifice は最弱1体)。 ⚠ audit hook は非対象。
pub fn legal_actions(state: &GameState) -> Vec<Value> {
    let mut out: Vec<Value> = vec![];
    if state.game_over || state.phase != Phase::Main {
        return out;
    }
    let me_idx = state.turn_player_idx;
    let me = &state.players[me_idx];
    out.push(json!({"t": "EndPhase"}));

    let field_full = me.characters.len() >= 5;
    let chara_play_blocked = me.block_chara_play_until_turn_end;
    let cost_block = me.block_chara_play_cost_ge_threshold;
    let cost_play_blocked = |c: &CardDef| cost_block >= 0 && c.cost >= cost_block;

    if !chara_play_blocked && !field_full {
        for (i, c) in me.hand.iter().enumerate() {
            if c.category != Category::Character || cost_play_blocked(c) {
                continue;
            }
            if eff_cost(state, me_idx, c) <= me.don_active {
                out.push(json!({"t": "PlayCharacter", "hand_idx": i}));
            }
        }
    } else if !chara_play_blocked {
        // 場 5 枚: AI = 最弱1体 sacrifice
        for (i, c) in me.hand.iter().enumerate() {
            if c.category != Category::Character || cost_play_blocked(c) {
                continue;
            }
            if eff_cost(state, me_idx, c) > me.don_active || me.characters.is_empty() {
                continue;
            }
            let sac = (0..me.characters.len())
                .min_by_key(|&j| (me.characters[j].power(), me.characters[j].card.cost))
                .unwrap();
            out.push(json!({"t": "PlayCharacter", "hand_idx": i, "sacrifice_idx": sac}));
        }
    }

    for (i, c) in me.hand.iter().enumerate() {
        if c.category == Category::Event && eff_cost(state, me_idx, c) <= me.don_active {
            out.push(json!({"t": "PlayEvent", "hand_idx": i}));
        }
    }
    for (i, c) in me.hand.iter().enumerate() {
        if c.category == Category::Stage && eff_cost(state, me_idx, c) <= me.don_active {
            out.push(json!({"t": "PlayStage", "hand_idx": i}));
        }
    }

    if me.don_active >= 1 {
        out.push(json!({"t": "AttachDonToLeader", "n": 1}));
        for j in 0..me.characters.len() {
            out.push(json!({"t": "AttachDonToCharacter", "target_idx": j, "n": 1}));
        }
    }

    // 戦闘 (turn 1/2 はバトル不可)
    let can_battle = state.turn_number > 2;
    if can_battle {
        // attacker 候補 (kind, idx) と、 速攻:キャラ 専用 (chara_only)
        let mut attackers: Vec<(String, usize)> = vec![];
        let mut chara_only: Vec<usize> = vec![];
        let l = &me.leader;
        if !l.rested
            && !l.cannot_attack_until_turn_end
            && !l.cannot_attack_static
            && !l.cannot_attack_through_opp_turn
            && !l.cannot_be_rested_buff
        {
            attackers.push(("leader".into(), 0));
        }
        for (j, ch) in me.characters.iter().enumerate() {
            if ch.rested
                || ch.cannot_attack_until_turn_end
                || ch.cannot_attack_static
                || ch.cannot_attack_through_opp_turn
                || ch.cannot_be_rested_buff
            {
                continue;
            }
            if ch.summoning_sickness && !ch.is_rush_now() {
                if ch.is_rush_chara_only_now() {
                    chara_only.push(j);
                }
                continue;
            }
            attackers.push(("char".into(), j));
        }

        let opp = &state.players[1 - me_idx];
        let opp_taunts: Vec<usize> = (0..opp.characters.len())
            .filter(|&k| opp.characters[k].attack_taunt)
            .collect();
        let can_attack_target = |atk: &InPlay, target_cost: i32| -> bool {
            let cap = atk.cannot_attack_target_cost_le_until_turn_end;
            cap < 0 || target_cost > cap
        };
        let atk_ref = |kind: &str, idx: usize| -> &InPlay {
            if kind == "leader" { &me.leader } else { &me.characters[idx] }
        };

        for (kind, idx) in &attackers {
            let atk = atk_ref(kind, *idx);
            let active_ok = atk.granted_keywords.contains("アクティブアタック可");
            if !opp_taunts.is_empty() {
                for &t in &opp_taunts {
                    let tgt = &opp.characters[t];
                    if (tgt.rested || active_ok) && can_attack_target(atk, tgt.card.cost) {
                        out.push(json!({"t": "AttackCharacter", "attacker_kind": kind, "attacker_idx": idx, "target_idx": t}));
                    }
                }
            } else {
                if !me.cannot_attack_leader_until_turn_end {
                    out.push(json!({"t": "AttackLeader", "attacker_kind": kind, "attacker_idx": idx}));
                }
                for t in 0..opp.characters.len() {
                    let tgt = &opp.characters[t];
                    if (tgt.rested || active_ok) && can_attack_target(atk, tgt.card.cost) {
                        out.push(json!({"t": "AttackCharacter", "attacker_kind": kind, "attacker_idx": idx, "target_idx": t}));
                    }
                }
            }
        }
        for &j in &chara_only {
            let atk = &me.characters[j];
            let active_ok = atk.granted_keywords.contains("アクティブアタック可");
            if !opp_taunts.is_empty() {
                for &t in &opp_taunts {
                    if opp.characters[t].rested || active_ok {
                        out.push(json!({"t": "AttackCharacter", "attacker_kind": "char", "attacker_idx": j, "target_idx": t}));
                    }
                }
            } else {
                for t in 0..opp.characters.len() {
                    if opp.characters[t].rested || active_ok {
                        out.push(json!({"t": "AttackCharacter", "attacker_kind": "char", "attacker_idx": j, "target_idx": t}));
                    }
                }
            }
        }
    }

    // ActivateMain (list_activate_main_effects: cost payable + 条件成立)
    if let Some(ov) = overlay() {
        let n_char = me.characters.len();
        let n_stage = me.stages.len();
        let mut slots: Vec<(Slot, &str)> = vec![(Slot::Leader, "leader")];
        for j in 0..n_char { slots.push((Slot::Char(j), "char")); }
        for j in 0..n_stage { slots.push((Slot::Stage(j), "stage")); }
        for (slot, kind) in slots {
            let ip = get_ip(me, slot);
            let cid = ip.card.card_id.clone();
            let Some(effs) = ov.get(&cid) else { continue };
            let on_field = matches!(slot, Slot::Char(_) | Slot::Stage(_));
            for (idx, eff) in effs.iter().enumerate() {
                if eff.get("when").and_then(|v| v.as_str()) != Some("activate_main") {
                    continue;
                }
                let cost = eff.get("cost").cloned().unwrap_or_else(|| json!({}));
                if !can_pay_activate_cost(state, me_idx, ip, on_field, &cost) {
                    continue;
                }
                match eval_effect_conditions(eff, state, me_idx, Some(slot)) {
                    Some(true) => {}
                    _ => continue,
                }
                let sidx = match slot {
                    Slot::Leader => 0,
                    Slot::Char(j) | Slot::Stage(j) => j,
                };
                out.push(json!({"t": "ActivateMain", "source_kind": kind, "source_idx": sidx, "effect_index": idx}));
            }
        }
    }
    out
}
