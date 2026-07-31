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

/// 登場カードの on_play が「順序観測できる zone (deck/trash/life) を並べ替える」primitive を含むか。
/// Python は play_from_trash で登場したキャラの on_play を **enqueue→アクション境界で drain (deferred)**
/// するが、 Rust は inline 発火する。 通常は結果同一だが、 同じ do 内で後続が同 zone を触ると **append 順**
/// がズレて digest MISMATCH (例 OP14-084: バレンタインの search_top_n leftover と 2枚目の field-full trash が
/// 入れ替わる)。 = trigger-queue モデリングが要る領域なので、 この risk がある登場は inline せず **明示 bail**。
/// (単発 play_from_trash で後続 zone 変化が無ければ inline でも一致するが、 文脈判定が局所化できないため
///  安全側で「並べ替え on_play を持つ登場」は一律 bail。 単純 on_play=buff/ko/draw固定 は inline 継続。)
fn on_play_defers_zone_reorder(card_id: &str) -> bool {
    // deferred inline 発火で deck/trash/life の append 順が観測されうる primitive。
    const RISKY: &[&str] = &[
        "search", "search_top_n", "reveal_top_then", "reveal_top_play",
        "reveal_self_life_top_pump_per_cost", "summon_from_deck",
        "mill_self_life_until_n", "mill_opp_life_to_hand", "mill_opp_life_to_trash",
        "scry_life", "scry_all_life_one_to_deck", "scry_all_life_reorder", "peek_self_life_top",
        "put_top_to_life", "life_top_or_bottom_to_hand", "trash_to_deck", "opp_trash_to_deck_bottom",
        "draw_per_hand_to_deck_bottom", "return_to_deck_bottom", "return_to_deck_bottom_multi",
        "play_from_trash", "play_multi_from_trash", "play_from_hand_or_trash", "play_from_trash_or_hand",
    ];
    let Some(ov) = overlay() else { return false };
    let Some(effs) = ov.get(card_id) else { return false };
    for eff in effs {
        if eff.get("when").and_then(|v| v.as_str()) != Some("on_play") {
            continue;
        }
        if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
            for prim in dos {
                if let Some(obj) = prim.as_object() {
                    for k in obj.keys() {
                        if RISKY.contains(&k.as_str()) {
                            return true;
                        }
                        // conditional { do: [...] } の中の risky も拾う (浅い 1 段)。
                        if k == "conditional" {
                            if let Some(inner) = obj.get("conditional")
                                .and_then(|c| c.get("do")).and_then(|d| d.as_array())
                            {
                                for p2 in inner {
                                    if let Some(o2) = p2.as_object() {
                                        if o2.keys().any(|kk| RISKY.contains(&kk.as_str())) {
                                            return true;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    false
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

/// 「手札のこのカードは効果で登場できない」(OP12-036 ゾロ、 effects.py:_no_play_from_hand_via_effect)。
/// overlay の `_no_play_via_effect: true` marker で判定 → play_from_hand 系が候補から除外する。
fn card_no_play_via_effect(card_id: &str) -> bool {
    overlay().and_then(|m| m.get(card_id)).map_or(false, |effs| {
        effs.iter().any(|e| e.get("_no_play_via_effect").and_then(|v| v.as_bool()).unwrap_or(false))
    })
}

/// カードが on_play (登場時) 効果を持つか。 Python は登場カードの on_play を **enqueue→drain (deferred)**
/// するため、 効果解決中に別 primitive (play_from_hand_or_trash 等) から登場したキャラの on_play は
/// 「そのキャラが hand から除去され、 loop が終わった**後**」に走る。 Rust は inline 発火 = hand にまだ
/// 居る状態で on_play が走り、 hand を観測/mutate する on_play (draw/discard/hand-size) がズレる
/// (OP14-091 の on_ko → Mr.5(OP14-094) 登場 → Mr.5 の draw+discard で trash_self_hand の候補が Mr.5 を
/// 含む 5 枚 vs Python 4 枚)。 = trigger-queue モデリング領域。 → こういう登場は inline せず明示 bail。
fn card_has_on_play(card_id: &str) -> bool {
    overlay().and_then(|m| m.get(card_id)).map_or(false, |effs| {
        effs.iter().any(|e| e.get("when").and_then(|v| v.as_str()) == Some("on_play"))
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

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Slot {
    Leader,
    Char(usize),
    Stage(usize),
    /// 発動元が **場に居ない** (= Python の `self_inplay=None`)。 【トリガー】(ライフ札)、 【KO時】(KO 済)、
    /// counter event (手札から trash) 等。 effects.py:256-274 が when in (on_ko/main/counter/trigger) で
    /// self_inplay=None を許容するのと対応。 **target "self" は 0 対象 = no-op になる** (effects.py:2346
    /// `if target_spec in (None,"self") and self_inplay is not None`)。 以前は Slot::Leader を placeholder に
    /// していたが、 それだと "self" が自リーダーへ誤解決するため allow-list で丸ごと bail していた。
    Detached,
}

fn get_ip(p: &Player, s: Slot) -> &InPlay {
    match s {
        Slot::Leader | Slot::Detached => &p.leader,
        Slot::Char(i) => &p.characters[i],
        Slot::Stage(i) => &p.stages[i],
    }
}
fn get_ip_mut(p: &mut Player, s: Slot) -> &mut InPlay {
    match s {
        Slot::Leader | Slot::Detached => &mut p.leader,
        Slot::Char(i) => &mut p.characters[i],
        Slot::Stage(i) => &mut p.stages[i],
    }
}

/// 発動元 InPlay を **場に居る時だけ** 返す (Python の self_inplay 相当)。 src を直接参照する primitive は
/// これを使い、 None なら再現不能として bail する (Slot::Detached で leader に誤解決させない為)。
fn src_ip(p: &Player, s: Slot) -> Option<&InPlay> {
    match s {
        Slot::Detached => None,
        _ => Some(get_ip(p, s)),
    }
}
fn src_ip_mut(p: &mut Player, s: Slot) -> Option<&mut InPlay> {
    match s {
        Slot::Detached => None,
        _ => Some(get_ip_mut(p, s)),
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
    // 自場のドン‼合計 = コストエリア (active+rested) + 付与ドン (leader + 全 chara)。 effects.py:1307
    //   (self_don_ge/le)。 ⚠ 付与ドンを含めないと AttachDon (cost area→chara) で総数が誤減少し、
    //   self_don_ge 条件 (OP15-119 モンキー・D・ルフィ 静的速攻=自場ドン6以上) が MISMATCH する。
    let total_don = |p: &Player| {
        (p.don_active
            + p.don_rested
            + p.leader.attached_dons
            + p.characters.iter().map(|c| c.attached_dons).sum::<i32>()) as i64
    };
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
            // 半角/全角 D を normalize してから一致 (core.py:normalize_card_name = Ｄ→D。 これが無いと
            // OP13-075/モンキー・Ｄ・ルフィ 系 overlay の leader_name 条件が silent no-op、 effects.py:1732)。
            "leader_name" => norm_card_name(&me.leader.card.name) == norm_card_name(v.as_str().unwrap_or("")),
            // リーダー名がリストに含まれる (effects.py:1736、 半角/全角 D normalize)。
            "leader_name_in" => {
                let ldr = norm_card_name(&me.leader.card.name);
                v.as_array().map_or(false, |arr| {
                    arr.iter().any(|x| x.as_str().map_or(false, |s| norm_card_name(s) == ldr))
                })
            }
            "leader_color" => {
                let val = v.as_str().unwrap_or("");
                if val == "多色" {
                    me.leader.card.color.len() >= 2
                } else {
                    me.leader.card.color.iter().any(|c| c == val)
                }
            }
            // 自リーダーが多色 (color 2 色以上) か (effects.py:1643)。
            "leader_multicolor" => (me.leader.card.color.len() >= 2) == v.as_bool().unwrap_or(true),
            // 自場のキャラ数 <= N (effects.py:1156)。
            "self_field_count_le" => (me.characters.len() as i64) <= v.as_i64().unwrap_or(0),
            "self_field_count_ge" => (me.characters.len() as i64) >= v.as_i64().unwrap_or(0),
            // コスト0か8以上のキャラが両陣営に居るか (base_cost、 effects.py:1393)。
            "exists_chara_cost_0_or_ge_8" => {
                let found = me.characters.iter().chain(opp.characters.iter())
                    .any(|c| c.base_cost() == 0 || c.base_cost() >= 8);
                found == v.as_bool().unwrap_or(true)
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
            // on_self_don_returned_to_deck で「一度に N 枚以上戻された」 (effects.py:1370、 OP09-061/EB02-035/P-077)。
            // don 返却 primitive が state.last_returned_don_count に保存。
            "returned_don_count_ge" => (state.last_returned_don_count as i64) >= v.as_i64().unwrap_or(0),
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
            // 直近 KO victim の元々パワー (card.power) >= N / 特徴が list に含まれる (effects.py:1428/1434)。
            // last_chara_ko_victim_card は ko cascade 中のみ set (完了後 None)。
            "victim_truly_original_power_ge" => state
                .last_chara_ko_victim_card
                .as_ref()
                .map_or(false, |vic| (vic.power as i64) >= v.as_i64().unwrap_or(0)),
            "victim_feature_in" => state.last_chara_ko_victim_card.as_ref().map_or(false, |vic| {
                let feats: Vec<&str> = match v {
                    Value::Array(a) => a.iter().filter_map(|x| x.as_str()).collect(),
                    Value::String(s) => vec![s.as_str()],
                    _ => vec![],
                };
                feats.iter().any(|f| vic.features.iter().any(|vf| vf == f))
            }),
            // 相手/自分のレストキャラ数 >= N (effects.py:1250/1326)。
            "opp_rested_chara_count_ge" => {
                (opp.characters.iter().filter(|c| c.rested).count() as i64) >= v.as_i64().unwrap_or(0)
            }
            "self_rested_chara_count_ge" => {
                (me.characters.iter().filter(|c| c.rested).count() as i64) >= v.as_i64().unwrap_or(0)
            }
            // 自/相手のレストカード数 (don_rested + rested chara + leader + stage) >= N (effects.py:1770/1780)。
            "self_rested_cards_count_ge" => {
                let cnt = me.don_rested as i64
                    + me.characters.iter().filter(|c| c.rested).count() as i64
                    + if me.leader.rested { 1 } else { 0 }
                    + me.stages.iter().filter(|s| s.rested).count() as i64;
                cnt >= v.as_i64().unwrap_or(0)
            }
            "opp_rested_cards_count_ge" => {
                let cnt = opp.don_rested as i64
                    + opp.characters.iter().filter(|c| c.rested).count() as i64
                    + if opp.leader.rested { 1 } else { 0 }
                    + opp.stages.iter().filter(|s| s.rested).count() as i64;
                cnt >= v.as_i64().unwrap_or(0)
            }
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
            // 自リーダー/キャラから名前一致 1 枚 (effects.py:2104、 leader 優先→char 順、 AI=先頭)。 OP15-076 counter。
            if t == "self_chara_or_leader_named" {
                let name = v.get("name").and_then(|x| x.as_str()).unwrap_or("");
                let p = &state.players[me_idx];
                if p.leader.card.name == name {
                    return Some(vec![(me_idx, Slot::Leader)]);
                }
                for i in 0..p.characters.len() {
                    if p.characters[i].card.name == name {
                        return Some(vec![(me_idx, Slot::Char(i))]);
                    }
                }
                return Some(vec![]);
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
            // one_self_character_filtered は one_self_chara_filtered の別名 (effects.py:2097)。
            if t == "one_self_chara_filtered" || t == "one_self_character_filtered" {
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
            // 相手キャラから filter 一致 1 枚 (effects.py:2182、 _threat_key=power降順)。 sub-filter:
            //   attached_don_ge / rested / active / blocker / current_power_le / current_cost_eq/le/ge。
            if t == "one_opponent_character_filtered" {
                let fo = v.get("filter").and_then(|f| f.as_object());
                let gi = |k: &str| fo.and_then(|o| o.get(k)).and_then(|x| x.as_i64());
                let gb = |k: &str| fo.and_then(|o| o.get(k)).and_then(|x| x.as_bool()).unwrap_or(false);
                let (adg, rr, ar, br) = (gi("attached_don_ge").unwrap_or(0), gb("rested"), gb("active"), gb("blocker"));
                let (cpl, cce, ccl, ccg) = (gi("current_power_le"), gi("current_cost_eq"), gi("current_cost_le"), gi("current_cost_ge"));
                let base_filt: Option<Value> = fo.map(|o| {
                    let mut m = o.clone();
                    for k in ["attached_don_ge", "rested", "active", "blocker", "current_power_le", "current_cost_eq", "current_cost_le", "current_cost_ge"] {
                        m.remove(k);
                    }
                    Value::Object(m)
                });
                let opp = &state.players[opp_idx];
                let mut cands: Vec<usize> = (0..opp.characters.len())
                    .filter(|&i| {
                        let c = &opp.characters[i];
                        matches_filter(&c.card, base_filt.as_ref())
                            && (adg <= 0 || c.attached_dons as i64 >= adg)
                            && (!rr || c.rested)
                            && (!ar || !c.rested)
                            && (!br || c.is_blocker_now())
                            && cpl.map_or(true, |n| c.power() as i64 <= n)
                            && cce.map_or(true, |n| c.base_cost() as i64 == n)
                            && ccl.map_or(true, |n| c.base_cost() as i64 <= n)
                            && ccg.map_or(true, |n| c.base_cost() as i64 >= n)
                    })
                    .collect();
                cands.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
                return Some(cands.into_iter().take(1).map(|i| (opp_idx, Slot::Char(i))).collect());
            }
            return None;
        }
    };
    let out = match s.as_str() {
        // effects.py:2346 — self_inplay=None (source-gone) なら 0 対象 = no-op。
        "self" => {
            if src == Slot::Detached {
                vec![]
            } else {
                vec![(me_idx, src)]
            }
        }
        // このキャラ以外の自キャラ 1 枚 (power 降順、 effects.py:2951)。 src が Char(i) なら i を除外。
        "other_self_chara" => {
            let p = &state.players[me_idx];
            let src_idx = if let Slot::Char(i) = src { Some(i) } else { None };
            let mut cands: Vec<usize> = (0..p.characters.len()).filter(|&i| Some(i) != src_idx).collect();
            cands.sort_by(|&a, &b| p.characters[b].power().cmp(&p.characters[a].power()));
            cands.into_iter().take(1).map(|i| (me_idx, Slot::Char(i))).collect()
        }
        // effects.py:2345 「自リーダーかキャラ1枚」 = src ではなく AI=最高power の自カード (leader/char)。
        // ties は原順 (leader→char0→…) = 安定ソート。 counter event (source-gone) 等で src と別。
        "self_inplay" => {
            let me = &state.players[me_idx];
            let mut cands: Vec<(Slot, i32)> = vec![(Slot::Leader, me.leader.power())];
            for (i, c) in me.characters.iter().enumerate() {
                cands.push((Slot::Char(i), c.power()));
            }
            cands.sort_by(|a, b| b.1.cmp(&a.1)); // desc power (stable=ties 原順)
            vec![(me_idx, cands[0].0)]
        }
        "self_leader" => vec![(me_idx, Slot::Leader)],
        // 相手リーダー or キャラ 1 枚 (effects.py:2507)。 AI = _opp_value 最大のキャラ → **居なければ
        // リーダー**。 ⚠ 下の one_opponent_ prefix arm はキャラのみ返すので、 キャラ 0 の時に Python の
        // leader fallback と食い違う → 明示 arm が要る。 one_opp_chara_or_leader は alias (effects.py:2395)。
        "one_opponent_inplay_any" | "one_opp_chara_or_leader" => {
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> = (0..opp.characters.len()).collect();
            cands.sort_by(|&a, &b| {
                opp_value(&opp.characters[b])
                    .partial_cmp(&opp_value(&opp.characters[a]))
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            match cands.first() {
                Some(&i) => vec![(opp_idx, Slot::Char(i))],
                None => vec![(opp_idx, Slot::Leader)],
            }
        }
        // effects.py:2389 alias。 prefix arm は "one_opponent_" 始まりしか拾わないので明示。
        "one_opp_character_any" => {
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> = (0..opp.characters.len()).collect();
            cands.sort_by(|&a, &b| {
                opp_value(&opp.characters[b])
                    .partial_cmp(&opp_value(&opp.characters[a]))
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            cands.into_iter().take(1).map(|i| (opp_idx, Slot::Char(i))).collect()
        }
        // 相手リーダー (effects.py:2354、 one_opponent_leader は overlay 別名 OP06-023 等)。
        "opponent_leader" | "one_opponent_leader" => vec![(opp_idx, Slot::Leader)],
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
        // all_opponent_characters_power_le_N = 現 power ≤ N の相手キャラ全員 (effects.py:2368、 OP15-114)。
        os if os.starts_with("all_opponent_characters_power_le_") => {
            let n = parse_after(os, "power_le_").unwrap_or(0);
            (0..state.players[opp_idx].characters.len())
                .filter(|&i| state.players[opp_idx].characters[i].power() <= n)
                .map(|i| (opp_idx, Slot::Char(i)))
                .collect()
        }
        // one_opponent_inplay_cost_le_N = 相手のリーダー or コスト N 以下のキャラ 1 体 (OP05-038 舞踏石 等)。
        // ⚠ Python (effects.py:2924) は **power 降順** で選び、 cost≤N キャラが居なければ leader へ fallback。
        // 汎用 one_opponent_ arm (opp_value sort・leader 非対象) と別扱い = MISMATCH 回避。
        os if os.starts_with("one_opponent_inplay_cost_le_") => {
            let n = parse_after(os, "cost_le_").unwrap_or(0);
            let opp = &state.players[opp_idx];
            let mut chars: Vec<usize> = (0..opp.characters.len())
                .filter(|&i| opp.characters[i].card.cost <= n)
                .collect();
            // power 降順、 tie は board 順維持 (stable、 Python sorted(key=-power) と一致)。
            chars.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
            match chars.first() {
                Some(&i) => vec![(opp_idx, Slot::Char(i))],
                None => vec![(opp_idx, Slot::Leader)],
            }
        }
        // one_opponent_[rested_]character[_(any_)?cost_le_Ncost | _power_le_N | _any]
        // = 相手キャラを filter → opp_value 最大を 1 体 (AI 自動選択、 effects.py:2443/2540/2627)。
        os if os.starts_with("one_opponent_") => {
            let rested_only = os.contains("rested_character");
            let cost_le = parse_after(os, "cost_le_"); // c.card.cost <= n
            // current_cost_le_N = 現在コスト (base_cost、 cost_minus 反映) 版。 通常 cost_le は元コスト
            // (card.cost)。 クロコダイル「コスト0」系 (effects.py:2603)。
            let cost_is_current = os.contains("current_cost_le_");
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
                        let cc = if cost_is_current { c.base_cost() } else { c.card.cost };
                        if cc > n {
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
            // ⚠ Python は spec 毎に sort key が異なる: **明示 "power_le" を含む spec** (one_opponent_
            // character_power_le_N=effects.py:2647 / rested_character_power_le=2716) は _threat_key
            // (= power 降順)、 bare "character_le"/cost_le は _opp_value。 安定ソートで tie は index 順。
            if os.contains("power_le_") {
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
        // any_opponent_character_cost_le_N / _power_le_N = 該当相手キャラ全員 (board 順、 sort 無、
        // effects.py:2618/2632)。 count は呼出側 (rest {target,count} 等) が適用する。
        os if os.starts_with("any_opponent_character_cost_le_") => {
            let n = parse_after(os, "cost_le_").unwrap_or(0);
            let opp = &state.players[opp_idx];
            (0..opp.characters.len())
                .filter(|&i| opp.characters[i].card.cost <= n)
                .map(|i| (opp_idx, Slot::Char(i)))
                .collect()
        }
        os if os.starts_with("any_opponent_character_power_le_") => {
            let n = parse_after(os, "power_le_").unwrap_or(0);
            let opp = &state.players[opp_idx];
            (0..opp.characters.len())
                .filter(|&i| opp.characters[i].power() <= n)
                .map(|i| (opp_idx, Slot::Char(i)))
                .collect()
        }
        // all_opponent_rested_characters_le_Ncost = 相手レストのコストN以下 全員 (effects.py:2732、 sort 無)。
        os if os.starts_with("all_opponent_rested_characters_le_") && os.ends_with("cost") => {
            let n: i32 = os["all_opponent_rested_characters_le_".len()..os.len() - 4].parse().unwrap_or(0);
            let opp = &state.players[opp_idx];
            (0..opp.characters.len())
                .filter(|&i| opp.characters[i].rested && opp.characters[i].card.cost <= n)
                .map(|i| (opp_idx, Slot::Char(i)))
                .collect()
        }
        // any_opp_rested_chara_cost_le_C_n_N = 相手レストのコストC以下 を _threat_key(power降順) で N 体 (effects.py:2781)。
        os if os.starts_with("any_opp_rested_chara_cost_le_") => {
            let rest = &os["any_opp_rested_chara_cost_le_".len()..];
            let Some((c_str, n_str)) = rest.split_once("_n_") else { return None };
            let cost_cap: i32 = c_str.parse().unwrap_or(0);
            let n: usize = n_str.parse().unwrap_or(1);
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> = (0..opp.characters.len())
                .filter(|&i| opp.characters[i].rested && opp.characters[i].card.cost <= cost_cap)
                .collect();
            cands.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
            cands.into_iter().take(n).map(|i| (opp_idx, Slot::Char(i))).collect()
        }
        // any_opp_rested_chara_n_N = 相手レストのキャラ を _threat_key で N 体 (effects.py:2796)。
        os if os.starts_with("any_opp_rested_chara_n_") => {
            let n: usize = os["any_opp_rested_chara_n_".len()..].parse().unwrap_or(1);
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> =
                (0..opp.characters.len()).filter(|&i| opp.characters[i].rested).collect();
            cands.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
            cands.into_iter().take(n).map(|i| (opp_idx, Slot::Char(i))).collect()
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

/// cost_le_dynamic を静的 cost_le に解決 (effects.py:_resolve_dynamic_filter)。 filter に cost_le_dynamic が
/// あれば source から値を計算して cost_le に置換 (無ければ clone をそのまま)。
fn resolve_dynamic_filter(filt: Option<&Value>, state: &GameState, me_idx: usize) -> Option<Value> {
    let filt = filt?;
    let o = filt.as_object()?;
    if !o.contains_key("cost_le_dynamic") {
        return Some(filt.clone());
    }
    let opp_idx = 1 - me_idx;
    let me = &state.players[me_idx];
    let opp = &state.players[opp_idx];
    let src = o.get("cost_le_dynamic").and_then(|x| x.as_str()).unwrap_or("");
    let cost_le: i64 = match src {
        "sum_both_life_count" => (me.life.len() + opp.life.len()) as i64,
        "self_don_total" => {
            let attached: i32 = me.leader.attached_dons
                + me.characters.iter().map(|c| c.attached_dons).sum::<i32>()
                + me.stages.iter().map(|s| s.attached_dons).sum::<i32>();
            (me.don_active + me.don_rested + attached) as i64
        }
        "self_don_active" => me.don_active as i64,
        "opp_life_count" => opp.life.len() as i64,
        "self_life_count" => me.life.len() as i64,
        _ => 99, // 未知 source = 制限なし相当
    };
    let mut m = o.clone();
    m.remove("cost_le_dynamic");
    m.insert("cost_le".to_string(), Value::Number(cost_le.into()));
    Some(Value::Object(m))
}

/// 場 5 枚での効果登場時、 最弱キャラ (power→cost 昇順、 tie は先頭) を 1 枚トラッシュ (core.py:762、
/// 公式 3-7-6-1)。 KO ではない = on_ko trigger 無し (単純除去 + 付与ドン返却)。 満杯でなければ no-op。
fn trash_weakest_for_field_full(state: &mut GameState, me_idx: usize) {
    let me = &mut state.players[me_idx];
    if me.characters.len() < 5 {
        return;
    }
    let mut idx = 0;
    let mut best = (me.characters[0].power(), me.characters[0].card.cost);
    for i in 1..me.characters.len() {
        let key = (me.characters[i].power(), me.characters[i].card.cost);
        if key < best {
            best = key;
            idx = i;
        }
    }
    let removed = me.characters.remove(idx);
    let don = removed.attached_dons;
    me.trash.push(removed.card);
    me.don_rested += don;
}

fn cat_str(c: &Category) -> &'static str {
    match c {
        Category::Leader => "LEADER",
        Category::Character => "CHARACTER",
        Category::Event => "EVENT",
        Category::Stage => "STAGE",
    }
}

/// core.py:normalize_card_name の port = カード名の全角Ｄ↔半角D 表記揺れを半角D に正準化。
/// card.name は既に正準 (Python full_dump 由来) だが、 overlay 参照値は生 JSON = 未正準なので
/// leader_name 等の名前一致で両側を通す (silent no-op 防止)。
fn norm_card_name(s: &str) -> String {
    s.replace('Ｄ', "D")
}

/// effects.py:_walk_prim_names — do ツリーの全 key を集合に集める (list 走査 + dict key 再帰)。
fn walk_prim_names(node: &Value, out: &mut std::collections::BTreeSet<String>) {
    match node {
        Value::Object(o) => {
            for (k, v) in o {
                out.insert(k.clone());
                walk_prim_names(v, out);
            }
        }
        Value::Array(a) => a.iter().for_each(|x| walk_prim_names(x, out)),
        _ => {}
    }
}

/// effects.py:_option_score — choice_effect 選択肢を局面 (相手/自キャラ数・自ライフ) で採点。
/// do 空 = -1.0。 prim 集合を走査し効果種別で加点 (順不同 = 和なので順序非依存)。 スコア自体は digest
/// に載らず「どの option を選ぶか」のみ決める (float 順序差は max 選択に無関係、 tie は Python 同様 first)。
fn option_score(opt: &Value, n_opp: usize, n_me: usize, my_life: usize) -> f64 {
    let do_val = opt.get("do");
    let empty = match do_val {
        Some(Value::Array(a)) => a.is_empty(),
        Some(_) => false,
        None => true,
    };
    if empty {
        return -1.0;
    }
    let mut prims: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    walk_prim_names(do_val.unwrap(), &mut prims);
    let mut score = 0.0f64;
    for pr in &prims {
        score += match pr.as_str() {
            "ko" | "ko_multi" | "ko_all_others" | "return_to_hand" | "return_to_hand_multi"
            | "return_to_deck_bottom" => if n_opp > 0 { 3.0 } else { -0.5 },
            "rest" | "rest_opp_don" | "keep_opp_rested_don_next_refresh" => {
                if n_opp > 0 { 1.5 } else { -0.5 }
            }
            "draw" | "draw_per_self_hand_discarded" => 2.0,
            "search" | "search_top_n" | "play_from_hand" | "play_from_trash" | "summon_from_deck"
            | "reveal_hand_play_split" => 1.8,
            "add_don" | "add_rested_don" | "attach_don" | "attach_rested_don" | "attach_active_don"
            | "untap_don" => 1.5,
            "power_pump" | "give_keyword" | "give_rush" => if n_me > 0 { 1.0 } else { -0.5 },
            "put_top_to_life" | "hand_to_self_life" | "life_to_hand" => {
                if my_life <= 2 { 2.5 } else { 0.8 }
            }
            "trash_opp_hand_random" => 1.2,
            _ => 0.3,
        };
    }
    score
}

/// effects.py:_worst_hand_idx = 最も捨てて惜しくない手札 index (counter→cost→power→相手に割れてる札 の昇順)。
/// min = 最初の最小 (Rust min_by_key も tie は最初 = Python min と一致)。
fn worst_hand_idx(hand: &[crate::state::CardDef], known: &[String]) -> Option<usize> {
    if hand.is_empty() {
        return None;
    }
    (0..hand.len()).min_by_key(|&i| {
        let c = &hand[i];
        (
            c.counter as i64,
            c.cost as i64,
            c.power as i64,
            if known.contains(&c.card_id) { 0 } else { 1 },
        )
    })
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
            // 厳密 "cost": N (= cost_eq エイリアス、 公式「コストN の」、 effects.py:30、 OP14-084 等)。
            // original_cost_eq も印刷コスト一致 (CardDef.cost=印刷値)。
            "cost_eq" | "cost" | "original_cost_eq" => (card.cost as i64) == v.as_i64().unwrap_or(-1),
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
            // ⚠ Python の _matches_filter は truly_original_power_* を扱わない = 無視 (pass)。
            //   Rust の blanket `_ => false` だと Rust だけ弾いて MISMATCH (ST36-005 キッド redirect で発覚)。
            //   Python 準拠で pass (= 制限なし)。 card.power ベースの厳密判定は Python が未実装なので入れない。
            "truly_original_power_ge" | "truly_original_power_le" | "truly_original_power_eq" => true,
            // has_trigger = trigger が「【トリガー】」で始まる (effects.py:10603)。 trigger(bool)=非空 alias。
            "has_trigger" => !v.as_bool().unwrap_or(false) || card.trigger.starts_with("【トリガー】"),
            "trigger" if v.is_boolean() => !v.as_bool().unwrap_or(false) || !card.trigger.is_empty(),
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
        // 「相手の効果でレストにされない」 常在 (OP12-021、 rest 限定免疫)。 effects.py:set_cannot_be_rested_static。
        "set_cannot_be_rested_static" => {
            let tspec = if spec.is_object() { spec.get("target").cloned() } else { Some(Value::String("self".into())) };
            let Some(targets) = resolve_target(tspec.as_ref(), me_idx, opp_idx, src, state) else { return };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).static_cannot_be_rested = true;
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
        // effects.py:544 — self_inplay が居ない (source-gone) or 既レスト なら払えない。
        "rest_self" => Some(src_ip(me, src).map_or(false, |ip| !ip.rested)),
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
        "rest_self_leader_filtered_or_don" | "attach_active_don_to_named_chara" => Some(true),
        // flip_life は payability あり (effects.py:8515)。 face_up: 裏向きライフ≥1、 face_down: 表向き≥1。
        "flip_life_face_up" => {
            let fu = me.face_up_life_count.min(me.life.len() as i32);
            Some((me.life.len() as i32) - fu >= 1)
        }
        "flip_life_face_down" => Some(me.face_up_life_count.min(me.life.len() as i32) >= 1),
        "rest_self_chara_filtered" => {
            let filt = cv.get("filter");
            Some(me.characters.iter().any(|c| !c.rested && matches_filter(&c.card, filt)))
        }
        "reveal_hand_with_filter" | "discard_hand_with_filter" => {
            let (filt, count) = filter_and_count(cv);
            Some(me.hand.iter().filter(|c| matches_filter(c, Some(&filt))).count() >= count)
        }
        // trash_self_hand_random cost: 手札 N 枚以上必要 (effects.py:8267)。 支払いは primitive 委譲。
        "trash_self_hand_random" => {
            let n = if cv.is_object() {
                cv.get("count").or_else(|| cv.get("amount")).and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                cv.as_i64().unwrap_or(1)
            };
            Some((me.hand.len() as i64) >= n)
        }
        // mill_self_life_to_trash cost: ライフ N 枚以上必要 (effects.py:8259)。 支払いは primitive 委譲。
        "mill_self_life_to_trash" => {
            let n = if cv.is_object() {
                cv.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                cv.as_i64().unwrap_or(1)
            };
            Some((me.life.len() as i64) >= n)
        }
        // life_to_hand / life_top_or_bottom_to_hand cost: ライフ非空必要 (effects.py:8255)。
        "life_top_or_bottom_to_hand" | "life_to_hand" => Some(!me.life.is_empty()),
        // return_self_chara_to_hand cost: filter 一致の自キャラ ≥count 必要 (effects.py:8450)。
        "return_self_chara_to_hand" => {
            let (count, filt) = count_and_filter(cv);
            Some(me.characters.iter().filter(|c| matches_filter(&c.card, filt)).count() >= count)
        }
        // discard_hand cost: 手札 ≥ n 必要。
        "discard_hand" => Some((me.hand.len() as i64) >= cv.as_i64().unwrap_or(0)),
        // return_to_hand: other_self_chara cost = このキャラ以外の自キャラが1体以上 (effects.py:8321)。
        "return_to_hand" if cv.as_str() == Some("other_self_chara") => {
            let src_idx = if let Slot::Char(i) = src { Some(i) } else { None };
            Some((0..me.characters.len()).any(|i| Some(i) != src_idx))
        }
        _ => None, // 未対応 cost 型 → bail
    }
}

/// optional cost spec {count, filter} or int (short) を (count, Option<&filter>) に分解。
fn count_and_filter(cv: &Value) -> (usize, Option<&Value>) {
    if let Some(o) = cv.as_object() {
        let count = o.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
        (count, o.get("filter"))
    } else {
        (cv.as_i64().unwrap_or(1) as usize, None)
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
                // effects.py:882 — self_inplay が居なければ rest しない (source-gone)。
                let Some(ip) = src_ip_mut(&mut state.players[me_idx], src) else { return None };
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
        // trash_self_hand_random: Python optional_cost fallback (effects.py:8928) = execute_effect(cs)
        //   = primitive (worst_hand_idx pop + hand_discarded flag + on_self_hand_discarded cascade)。
        "trash_self_hand_random" => {
            if !execute_effect(cs, state, me_idx, src) {
                return None;
            }
        }
        // mill_self_life_to_trash: Python fallback (execute_effect) = primitive (life pop→trash、 trigger 無)。
        "mill_self_life_to_trash" => {
            if !execute_effect(cs, state, me_idx, src) {
                return None;
            }
        }
        // life_top_or_bottom_to_hand / life_to_hand cost: Python fallback = execute_effect (primitive 委譲)。
        "life_top_or_bottom_to_hand" | "life_to_hand" => {
            if !execute_effect(cs, state, me_idx, src) {
                return None;
            }
        }
        // return_self_chara_to_hand: AI=power 昇順で count 枚を手札へ (元順で append + 付与ドン返却、
        // effects.py:8848)。 cv は count_and_filter に渡すため cs から取り出す。
        "return_self_chara_to_hand" => {
            let (count, filt) = count_and_filter(&cv);
            // 候補 index を power 昇順 (stable=元順 ties) で count 枚選択
            let mut cands: Vec<(usize, i32)> = state.players[me_idx]
                .characters
                .iter()
                .enumerate()
                .filter(|(_, c)| matches_filter(&c.card, filt))
                .map(|(i, c)| (i, c.power()))
                .collect();
            cands.sort_by(|a, b| a.1.cmp(&b.1));
            let chosen: std::collections::HashSet<usize> =
                cands.iter().take(count).map(|(i, _)| *i).collect();
            // 元順に走査し chosen を手札へ、 他は残す (hand append 順 = 元 character 順)
            let me = &mut state.players[me_idx];
            let old = std::mem::take(&mut me.characters);
            for (i, c) in old.into_iter().enumerate() {
                if chosen.contains(&i) {
                    let don = c.attached_dons;
                    me.hand.push(c.card);
                    if don > 0 {
                        me.don_rested += don;
                    }
                } else {
                    me.characters.push(c);
                }
            }
        }
        // return_to_hand cost (other_self_chara 等): execute_effect 委譲 (Python も cost として execute_effect、
        // effects.py:8949)。 return_to_hand primitive の cascade を通す。
        "return_to_hand" => {
            if !execute_effect(cs, state, me_idx, src) {
                return None;
            }
        }
        // discard_hand cost: worst_hand_idx で n 枚捨てるだけ (effects.py:8736)。 ⚠ optional_cost_then の
        // discard は flag/on_self_hand_discarded cascade を**発火しない** (counter cost と非対称、 Python 準拠)。
        "discard_hand" => {
            let n = cv.as_i64().unwrap_or(0) as i32;
            let actual = n.min(state.players[me_idx].hand.len() as i32);
            for _ in 0..actual {
                let me = &mut state.players[me_idx];
                let Some(i) = worst_hand_idx(&me.hand, &me.known_hand_card_ids) else { break };
                let c = me.hand.remove(i);
                me.trash.push(c);
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
        // choice_effect (effects.py:3085): 「以下から1つを選ぶ」分岐。 AI は option_score 最大の option を
        // 選び do を実行。 actor は AI 経路では scoring/選択に無関係 (human-pick gating のみ、 self-play は常に AI)。
        "choice_effect" => {
            let Some(spec) = v.as_object() else { return true };
            let Some(options) = spec.get("options").and_then(|x| x.as_array()) else { return true };
            if options.is_empty() {
                return true;
            }
            // if 条件成立の option のみ valid。 unknown 条件は選択不能 → bail (黙って間違えない)。
            let mut valid: Vec<usize> = vec![];
            for (i, opt) in options.iter().enumerate() {
                if let Some(cond) = opt.get("if") {
                    match eval_condition(cond, state, me_idx, Some(src)) {
                        Some(true) => {}
                        Some(false) => continue,
                        None => return false,
                    }
                }
                valid.push(i);
            }
            if valid.is_empty() {
                return true; // 発動可能 option 無し = 不発 (Python continue)
            }
            // 局面採点で最良 option (tie は first = Python max 準拠)。
            let n_opp = state.players[opp_idx].characters.len();
            let n_me = state.players[me_idx].characters.len();
            let my_life = state.players[me_idx].life.len();
            let mut best = valid[0];
            let mut best_s = option_score(&options[valid[0]], n_opp, n_me, my_life);
            for &i in &valid[1..] {
                let s = option_score(&options[i], n_opp, n_me, my_life);
                if s > best_s {
                    best_s = s;
                    best = i;
                }
            }
            let Some(chosen_do) = options[best].get("do").and_then(|x| x.as_array()) else { return true };
            // nested cascade guard: 選んだ do の top-level prim が cascade を起こすなら bail
            // (execute_effect の draw 等は cascade を自前発火せず外側 guard 前提の為、 ここで再適用)。
            if effect_cascade_blocked(chosen_do, state, me_idx) {
                return false;
            }
            for sub in chosen_do {
                if !execute_effect(sub, state, me_idx, src) {
                    return false;
                }
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
        // ⚠ or_don + replace_rest は resolve_target=None または diverge → skip 境界。
        "rest" => {
            // one_opp_chara_or_don (effects.py:3683、 OP12-037): 相手キャラ or ドン 1 枚レスト。 AI =
            // 相手アクティブキャラ (power 降順) 優先 → 無ければ opp.don_active 1 枚 → 無ければ no-op。
            // ドンは Slot でないので resolve_target を通さず inline。 no-op でも true (Python は return False
            // だが do-loop は返値無視 = 実質 no-op、 bail にしない)。 cost_le filter (dict form)。
            let is_chara_or_don = v.as_str() == Some("one_opp_chara_or_don")
                || v.get("type").and_then(|x| x.as_str()) == Some("one_opp_chara_or_don");
            if is_chara_or_don {
                let cost_le = v.get("cost_le").and_then(|x| x.as_i64());
                let opp = &state.players[opp_idx];
                let mut cands: Vec<usize> = (0..opp.characters.len())
                    .filter(|&i| {
                        let c = &opp.characters[i];
                        !c.rested
                            && !c.cannot_be_rested_buff
                            && !c.static_cannot_be_rested
                            && cost_le.map_or(true, |n| c.card.cost as i64 <= n)
                    })
                    .collect();
                cands.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
                if let Some(&i) = cands.first() {
                    if rest_char_with_cascade(state, me_idx, opp_idx, i, src).is_err() {
                        return false;
                    }
                } else if state.players[opp_idx].don_active > 0 {
                    state.players[opp_idx].don_active -= 1;
                    state.players[opp_idx].don_rested += 1;
                }
                return true;
            }
            // {target, count} 形式 (effects.py:3742、 OP14-031): 候補全解決 (one_opponent_character_→
            // any_ 正規化)→active filter→power 降順 (stable)→count 枚をレスト。
            if let Some(o) = v.as_object() {
                if o.contains_key("count") && o.contains_key("target") && !o.contains_key("type") {
                    let rest_count = o.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
                    let cand_spec: Value = match o.get("target").and_then(|x| x.as_str()) {
                        Some(s) if s.starts_with("one_opponent_character_") => {
                            Value::String(format!("any_{}", &s["one_".len()..]))
                        }
                        _ => o.get("target").cloned().unwrap_or(Value::Null),
                    };
                    let Some(cands) = resolve_target(Some(&cand_spec), me_idx, opp_idx, src, state) else {
                        return false;
                    };
                    let mut list: Vec<(usize, Slot)> = cands
                        .into_iter()
                        .filter(|&(pi, sl)| {
                            let ip = get_ip(&state.players[pi], sl);
                            !ip.rested && !ip.cannot_be_rested_buff && !ip.static_cannot_be_rested
                        })
                        .collect();
                    // -power で安定ソート (tie は board 順維持 = Python cand_list.sort(key=-power) 準拠)。
                    list.sort_by(|&(pa, sa), &(pb, sb)| {
                        get_ip(&state.players[pb], sb).power().cmp(&get_ip(&state.players[pa], sa).power())
                    });
                    for (pi, sl) in list.into_iter().take(rest_count) {
                        if let Slot::Char(idx) = sl {
                            if rest_char_with_cascade(state, me_idx, pi, idx, src).is_err() {
                                return false;
                            }
                        }
                    }
                    return true;
                }
            }
            let Some(targets) = resolve_target(Some(v), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                match sl {
                    Slot::Char(idx) => {
                        if rest_char_with_cascade(state, me_idx, pi, idx, src).is_err() {
                            return false;
                        }
                    }
                    _ => {
                        // leader/stage: 当該カードが on_self_rested を持てば cascade 未対応で bail (rare)、
                        // else 単純 rest。
                        let cid = get_ip(&state.players[pi], sl).card.card_id.clone();
                        if card_has_when(&cid, "on_self_rested") {
                            return false;
                        }
                        let ip = get_ip_mut(&mut state.players[pi], sl);
                        if !ip.cannot_be_rested_buff && !ip.static_cannot_be_rested && !ip.rested {
                            ip.rested = true;
                        }
                    }
                }
            }
            true
        }
        // 自キャラ N 枚をアクティブ化 (effects.py:5402)。 spec {target(既定 one_self_character_any), limit(1)}。
        "untap_chara" => {
            let (spec, limit) = if v.is_object() {
                (
                    v.get("target").cloned().unwrap_or(Value::String("one_self_character_any".to_string())),
                    v.get("limit").and_then(|x| x.as_i64()).unwrap_or(1) as usize,
                )
            } else {
                (Value::String("one_self_character_any".to_string()), 1)
            };
            let Some(targets) = resolve_target(Some(&spec), me_idx, opp_idx, src, state) else {
                return false;
            };
            for (pi, sl) in targets.into_iter().take(limit) {
                get_ip_mut(&mut state.players[pi], sl).rested = false;
            }
            true
        }
        // アタック対象変更 (effects.py:5636、 opp_attack/counter で発動)。 AI は候補を順に resolve→先頭 target
        // (dedup)。 leader → no-op (redirect せず=通常 leader battle)、 char → pending_attack_redirect に
        // 防御側 char index を set (transient、 AttackLeader が読み char battle 再解決)。 iid 不要 (index で代替)。
        "redirect_attack" => {
            let mut chosen: Option<Slot> = None;
            if let Some(cands) = v.get("candidates").and_then(|c| c.as_array()) {
                let mut seen: Vec<Slot> = vec![];
                for cand in cands {
                    if let Some(ts) = resolve_target(Some(cand), me_idx, opp_idx, src, state) {
                        for (pi, sl) in ts {
                            if pi == me_idx && !seen.contains(&sl) {
                                seen.push(sl);
                            }
                        }
                    }
                }
                chosen = seen.into_iter().next();
            } else {
                let spec = if v.is_string() { v.clone() } else { Value::String("self_leader".to_string()) };
                if let Some(ts) = resolve_target(Some(&spec), me_idx, opp_idx, src, state) {
                    chosen = ts.into_iter().find(|(pi, _)| *pi == me_idx).map(|(_, sl)| sl);
                }
            }
            if let Some(Slot::Char(i)) = chosen {
                state.pending_attack_redirect = Some(i as i32);
            }
            // leader/stage/none → no-op (通常 leader battle 続行)
            true
        }
        // マルチターゲット KO (effects.py:7401、 OP12-038 等)。 v = target spec のリストを順に解決 → KO。
        // ⚠ cascade (on_ko / on_opp_chara_ko / on_self_chara_ko / replace_ko / replace_leave /
        //   on_self_chara_leave_by_self_effect) が絡む盤面は effect_cascade_blocked が呼出前に bail するので、
        //   ここは「素の除去」だけを Python と同順で再現する。 spec 毎に現盤面へ解決 = Python の逐次除去と同義。
        //   KO 耐性判定は Python の ko_multi と同じ 3 種のみ (ko と違い source power/attribute 耐性は見ない)。
        "ko_multi" => {
            let Some(list) = v.as_array() else { return true }; // Python: 非 list は continue = no-op
            for spec in list {
                let tspec: Value = if spec.is_string()
                    || spec.get("type").is_some()
                    || spec.get("filter").is_some()
                {
                    spec.clone()
                } else {
                    spec.get("target")
                        .cloned()
                        .unwrap_or(Value::String("one_opponent_character_any".into()))
                };
                let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
                let mut victims: Vec<(usize, usize)> = vec![];
                for (pi, sl) in targets {
                    let Slot::Char(idx) = sl else { continue };
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
                    victims.push((pi, idx));
                }
                if !victims.is_empty() {
                    remove_victims(state, victims, RemoveDest::Trash);
                }
            }
            true
        }
        // 効果無効 (effects.py:7648)。 spec = target 文字列 or {target}。 既定 one_opponent_inplay_any。
        // granted_keywords に "効果無効" を足すだけ (Python も同じ近似実装)。 last_negated_iid は
        // dataclass field でない (dynamic attr) = canonical 対象外なので Rust は記録不要。
        "negate_effect" => {
            let target_spec = if v.is_string() {
                v.clone()
            } else {
                v.get("target").cloned().unwrap_or(Value::String("one_opponent_inplay_any".into()))
            };
            let Some(targets) = resolve_target(Some(&target_spec), me_idx, opp_idx, src, state) else {
                return false;
            };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).granted_keywords.insert("効果無効".to_string());
            }
            true
        }
        // 効果無効 (effects.py:8220)。 spec {target, duration(turn|next_opp_turn_end), also_cannot_attack}。
        "disable_effect" => {
            let (target_spec, dur_next, also) = if let Some(o) = v.as_object() {
                (
                    o.get("target").cloned().unwrap_or(Value::String("one_opponent_inplay_any".to_string())),
                    o.get("duration").and_then(|x| x.as_str()) == Some("next_opp_turn_end"),
                    o.get("also_cannot_attack").and_then(|x| x.as_bool()).unwrap_or(false),
                )
            } else {
                (v.clone(), false, false)
            };
            let Some(targets) = resolve_target(Some(&target_spec), me_idx, opp_idx, src, state) else {
                return false;
            };
            if targets.is_empty() {
                return true; // 対象0 = no-op (Python return False も action 継続)
            }
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                if dur_next {
                    ip.effect_disabled_through_opp_turn = true;
                    if also {
                        ip.cannot_attack_through_opp_turn = true;
                    }
                } else {
                    ip.granted_keywords.insert("効果無効".to_string());
                    if also {
                        ip.cannot_attack_until_turn_end = true;
                    }
                }
            }
            true
        }
        // 対象をアクティブ化 (effects.py:4563)。 target = self/self_leader/all_self_characters (既定 self)。
        "untap" => {
            let spec = if v.is_string() { v.clone() } else { Value::String("self".to_string()) };
            let Some(targets) = resolve_target(Some(&spec), me_idx, opp_idx, src, state) else {
                return false;
            };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).rested = false;
            }
            true
        }
        // 自手札 N 枚をデッキ上/下へ (effects.py:7182、 OP08-050)。 AI = コスト最高 (=死札) を N 枚、
        // 反復で pop→ to=top なら deck 先頭 insert / bottom なら末尾 push。 ⚠ Python max は tie で最初の
        // index → Rust max_by_key (tie=最後) でなく first-max を手で求める。 cascade 無し。
        "self_hand_to_deck_bottom" => {
            let (n, to_top) = if let Some(o) = v.as_object() {
                (
                    o.get("amount").and_then(|x| x.as_i64()).unwrap_or(1) as usize,
                    o.get("to").and_then(|x| x.as_str()) == Some("top"),
                )
            } else {
                (v.as_i64().unwrap_or(1) as usize, false)
            };
            let me = &mut state.players[me_idx];
            for _ in 0..n {
                if me.hand.is_empty() {
                    break;
                }
                let mut idx = 0;
                let mut best = me.hand[0].cost;
                for i in 1..me.hand.len() {
                    if me.hand[i].cost > best {
                        best = me.hand[i].cost;
                        idx = i;
                    }
                }
                let card = me.hand.remove(idx);
                if to_top {
                    me.deck.insert(0, card);
                } else {
                    me.deck.push(card);
                }
            }
            true
        }
        // 「指定キャラ/リーダーのアタック中、 相手はブロッカー発動不可」 (effects.py:8187)。
        // target_spec = v (dict で target キー有れば v.target)。 attacker_prevents_blocker_until_turn_end=true。
        "prevent_blocker_for_attacker" => {
            let spec = if v.is_object() && v.get("target").is_some() {
                v.get("target").unwrap().clone()
            } else {
                v.clone()
            };
            let Some(targets) = resolve_target(Some(&spec), me_idx, opp_idx, src, state) else {
                return false;
            };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).attacker_prevents_blocker_until_turn_end = true;
            }
            true
        }
        // 「アタッカーのアタック中、 相手はパワーN以下ブロッカー発動不可」 (effects.py:8205)。
        // spec {amount, target(既定 self=attacker)}。 attacker_prevents_blocker_power_le に amount 設定。
        "prevent_blocker_for_attacker_power_le" => {
            let (amount, spec) = if v.is_object() {
                (
                    v.get("amount").and_then(|x| x.as_i64()).unwrap_or(0) as i32,
                    v.get("target").cloned().unwrap_or(Value::String("self".to_string())),
                )
            } else {
                (v.as_i64().unwrap_or(0) as i32, Value::String("self".to_string()))
            };
            let Some(targets) = resolve_target(Some(&spec), me_idx, opp_idx, src, state) else {
                return false;
            };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).attacker_prevents_blocker_power_le = amount;
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
        // 相手 or 自デッキ上 N 枚を trash (effects.py:mill)。 spec {target:opp|me, count}。
        "mill" => {
            let (target_opp, n) = if let Some(o) = v.as_object() {
                (o.get("target").and_then(|x| x.as_str()).unwrap_or("opp") == "opp",
                 o.get("count").and_then(|x| x.as_i64()).unwrap_or(1))
            } else {
                (true, v.as_i64().unwrap_or(1))
            };
            let pi = if target_opp { opp_idx } else { me_idx };
            for _ in 0..n {
                if state.players[pi].deck.is_empty() {
                    break;
                }
                let c = state.players[pi].deck.remove(0);
                state.players[pi].trash.push(c);
            }
            true
        }
        // 相手ライフ上 N 枚を trash (effects.py:mill_opp_life_to_trash、 効果削り=trigger 無し)。
        "mill_opp_life_to_trash" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            for _ in 0..n {
                if state.players[opp_idx].life.is_empty() {
                    break;
                }
                let c = state.players[opp_idx].life.remove(0);
                state.players[opp_idx].trash.push(c);
            }
            true
        }
        // 相手ライフ上 N 枚を相手手札へ (effects.py:mill_opp_life_to_hand、 効果ライフ削り=trigger 無し)。
        "mill_opp_life_to_hand" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            for _ in 0..n {
                if state.players[opp_idx].life.is_empty() {
                    break;
                }
                let c = state.players[opp_idx].life.remove(0);
                state.players[opp_idx].hand.push(c);
            }
            true
        }
        // トラッシュからキャラ登場 (effects.py:4733 play_from_trash/play_multi_from_trash、 AI 経路=先頭 limit 枚)。
        // 保守実装: CHARACTER のみ / 場が満杯でない / 静的 filter のみ。 STAGE・field-full・dynamic filter・
        // no_effect filter は bail (trash_weakest/動的解決/効果無し判定が複雑)。 登場後 on_play cascade を発火。
        "play_from_trash" | "play_multi_from_trash" => {
            let spec = v.as_object();
            let filt = spec.and_then(|o| o.get("filter"));
            // dynamic filter (cost_le_dynamic 等) / no_effect は未対応 → bail
            if let Some(fo) = filt.and_then(|f| f.as_object()) {
                if fo.keys().any(|k| k.ends_with("_dynamic")) || fo.contains_key("no_effect") {
                    return false;
                }
                // STAGE 登場は別処理 → bail
                if fo.get("category").and_then(|x| x.as_str()) == Some("STAGE") {
                    return false;
                }
            }
            let limit = spec.and_then(|o| o.get("limit")).and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let rested = spec.and_then(|o| o.get("rested")).and_then(|x| x.as_bool()).unwrap_or(false);
            let unique = spec.and_then(|o| o.get("unique_name")).and_then(|x| x.as_bool()).unwrap_or(false);
            let want_eot = spec.and_then(|o| o.get("return_to_deck_bottom_at_turn_end")).and_then(|x| x.as_bool()).unwrap_or(false);
            let pk = spec.and_then(|o| o.get("played_keyword")).and_then(|x| x.as_str()).map(|s| s.to_string());
            // AI: 先頭から limit 枚 (category=CHARACTER + filter + unique_name)。 index 収集。
            let mut chosen: Vec<usize> = vec![];
            let mut seen: Vec<String> = vec![];
            {
                let me = &state.players[me_idx];
                for (i, c) in me.trash.iter().enumerate() {
                    if chosen.len() >= limit {
                        break;
                    }
                    if c.category == crate::state::Category::Character
                        && matches_filter(c, filt)
                        && !(unique && seen.contains(&c.name))
                    {
                        chosen.push(i);
                        seen.push(c.name.clone());
                    }
                }
            }
            if chosen.is_empty() {
                return true; // 候補0 = no-op (AI path は何もしない)
            }
            // 登場カードを先に trash から除去 (公式: 登場でトラッシュを離れて**から** on_play)。
            let cards: Vec<crate::state::CardDef> =
                chosen.iter().map(|&i| state.players[me_idx].trash[i].clone()).collect();
            // 登場キャラの on_play が zone 並べ替えを含む = Python の deferred trigger 順を inline で
            // 再現できない (OP14-084 の search_top_n × field-full trash 順ズレ) → 明示 bail。
            if cards.iter().any(|c| on_play_defers_zone_reorder(&c.card_id)) {
                return false;
            }
            let mut desc = chosen.clone();
            desc.sort_unstable_by(|a, b| b.cmp(a));
            for i in desc {
                state.players[me_idx].trash.remove(i);
            }
            // 各カードを登場 + on_play cascade。 field-full は trash_weakest (3-7-6-1、 KO 無)。
            // on_play が bail したら false (partial は apply_action Err で破棄)。
            for card in cards {
                trash_weakest_for_field_full(state, me_idx);
                let mut ip = InPlay::of(card.clone(), true); // sickness=true
                ip.rested = rested;
                ip.played_from_trash = true;
                ip.return_to_deck_bottom_at_turn_end = want_eot;
                if let Some(k) = &pk {
                    ip.granted_keywords.insert(k.clone());
                }
                state.players[me_idx].characters.push(ip);
                let played_idx = state.players[me_idx].characters.len() - 1;
                state.last_self_chara_played_card = Some(card);
                state.last_self_chara_played_from_trash = true;
                if execute_on_play(state, me_idx, played_idx).is_err() {
                    return false;
                }
            }
            true
        }
        // 手札からキャラ登場 (effects.py:5010 play_from_hand、 コスト無視=効果代替登場)。 AI 経路=
        // cost 降順→power 降順→name 昇順 で並べ 先頭 limit 枚。 保守 bail: 動的 filter(cost_le_dynamic/
        // or/name_in_last_discarded)・no_effect・STAGE・then_life_to_hand(fire_self_life_to_hand cascade)・
        // field-full(trash_weakest)。 登場後 execute_on_play で on_play cascade 発火。
        "play_from_hand" => {
            let spec = v.as_object();
            // cost_le_dynamic を静的化してから使う (self_don_total 等)。
            let resolved = resolve_dynamic_filter(spec.and_then(|o| o.get("filter")), state, me_idx);
            let filt = resolved.as_ref();
            if let Some(fo) = filt.and_then(|f| f.as_object()) {
                if fo.contains_key("or")
                    || fo.contains_key("name_in_last_discarded")
                    || fo.contains_key("no_effect")
                    || fo.get("category").and_then(|x| x.as_str()) == Some("STAGE")
                {
                    return false;
                }
            }
            let limit = spec.and_then(|o| o.get("limit")).and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let rested = spec.and_then(|o| o.get("rested")).and_then(|x| x.as_bool()).unwrap_or(false);
            let unique = spec.and_then(|o| o.get("unique_name")).and_then(|x| x.as_bool()).unwrap_or(false);
            // 候補抽出: (hand_idx, cost, power, name)
            let mut cands: Vec<(usize, i32, i32, String)> = vec![];
            {
                let me = &state.players[me_idx];
                for (i, c) in me.hand.iter().enumerate() {
                    if c.category != crate::state::Category::Character {
                        continue;
                    }
                    if card_no_play_via_effect(&c.card_id) {
                        continue;
                    }
                    if !matches_filter(c, filt) {
                        continue;
                    }
                    cands.push((i, c.cost, c.power, c.name.clone()));
                }
            }
            if cands.is_empty() {
                return true; // 該当手札なし = 不発 (no-op)
            }
            // AI ヒューリスティック: cost 降順 → power 降順 → name 昇順
            cands.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| b.2.cmp(&a.2)).then_with(|| a.3.cmp(&b.3)));
            if unique {
                let mut seen: Vec<String> = vec![];
                cands.retain(|t| {
                    if seen.contains(&t.3) {
                        false
                    } else {
                        seen.push(t.3.clone());
                        true
                    }
                });
            }
            let chosen: Vec<usize> = cands.iter().take(limit).map(|t| t.0).collect();
            // hand から pop (降順 index で ずれ防止)
            let mut desc = chosen.clone();
            desc.sort_unstable_by(|a, b| b.cmp(a));
            let cards: Vec<crate::state::CardDef> =
                desc.iter().map(|&i| state.players[me_idx].hand.remove(i)).collect();
            // then_life_to_hand 有 (OP08-098 カルガラ): Python は on_play を **enqueue** → then_life →
            // drain。 = 登場カードの on_play は then_life 後の state を観測する (OP15-114 ワイパー は
            // then_life でライフ移動後に flip_life cost 不能 → optional_cost_then 不発)。 → place all →
            // then_life → on_play (deferred) → on_self_life_to_hand の順。
            if let Some(n_life) = spec.and_then(|o| o.get("then_life_to_hand")).and_then(|x| x.as_i64()) {
                let mut placed: Vec<usize> = vec![];
                for card in cards {
                    trash_weakest_for_field_full(state, me_idx);
                    let mut ip = InPlay::of(card, true);
                    ip.rested = rested;
                    state.players[me_idx].characters.push(ip);
                    placed.push(state.players[me_idx].characters.len() - 1);
                }
                let mut moved = 0;
                if !placed.is_empty() && !state.players[me_idx].prevent_self_life_to_hand_until_turn_end {
                    for _ in 0..n_life {
                        if state.players[me_idx].life.is_empty() {
                            break;
                        }
                        let c = state.players[me_idx].life.remove(0);
                        state.players[me_idx].hand.push(c);
                        moved += 1;
                    }
                }
                for &pidx in &placed {
                    let card = state.players[me_idx].characters[pidx].card.clone();
                    state.last_self_chara_played_card = Some(card);
                    state.last_self_chara_played_from_trash = false;
                    if execute_on_play(state, me_idx, pidx).is_err() {
                        return false;
                    }
                }
                if moved > 0 && fire_field_when(state, me_idx, "on_self_life_to_hand").is_err() {
                    return false;
                }
                return true;
            }
            for card in cards {
                trash_weakest_for_field_full(state, me_idx); // 場5枚は最弱trash (3-7-6-1、 KO無)
                let mut ip = InPlay::of(card.clone(), true); // sickness=true
                ip.rested = rested;
                state.players[me_idx].characters.push(ip);
                let played_idx = state.players[me_idx].characters.len() - 1;
                state.last_self_chara_played_card = Some(card);
                state.last_self_chara_played_from_trash = false;
                if execute_on_play(state, me_idx, played_idx).is_err() {
                    return false;
                }
            }
            true
        }
        // 手札からイベント発動 (effects.py:3895 play_event_from_hand、 0 コスト代替発動)。 AI=先頭一致 EVENT。
        // トラッシュへ送ってから execute_main_event (event main + on_self_event_played + opp_event_or_trigger)。
        "play_event_from_hand" => {
            let filt = v.as_object().and_then(|o| o.get("filter"));
            let mut chosen: Option<usize> = None;
            {
                let me = &state.players[me_idx];
                for (i, c) in me.hand.iter().enumerate() {
                    if c.category == crate::state::Category::Event && matches_filter(c, filt) {
                        chosen = Some(i);
                        break;
                    }
                }
            }
            let Some(i) = chosen else { return true }; // 該当イベントなし = 不発 (no-op)
            let card = state.players[me_idx].hand.remove(i);
            let cid = card.card_id.clone();
            state.players[me_idx].trash.push(card);
            execute_main_event(state, me_idx, &cid).is_ok()
        }
        // 手札からステージ登場 (effects.py:4981 play_stage_from_hand、 STAGE 専用)。 AI=先頭一致 STAGE。
        // 既存ステージはトラッシュへ置換 (attached_dons を don_rested へ返却)。 登場後 stage on_play 発火。
        "play_stage_from_hand" => {
            let filt = v.as_object().and_then(|o| o.get("filter"));
            let mut chosen: Option<usize> = None;
            {
                let me = &state.players[me_idx];
                for (i, c) in me.hand.iter().enumerate() {
                    if c.category == crate::state::Category::Stage && matches_filter(c, filt) {
                        chosen = Some(i);
                        break;
                    }
                }
            }
            let Some(i) = chosen else { return true }; // 該当ステージなし = 不発 (no-op)
            let card = state.players[me_idx].hand.remove(i);
            let ctx_card = card.clone();
            // 既存ステージを forward 順でトラッシュへ (公式: ステージは1枚まで=置換)
            let old = std::mem::take(&mut state.players[me_idx].stages);
            for s in old {
                let ad = s.attached_dons;
                state.players[me_idx].trash.push(s.card);
                if ad > 0 {
                    state.players[me_idx].don_rested += ad;
                }
            }
            let ip = InPlay::of(card, false); // sickness=false (ステージ)
            state.players[me_idx].stages.push(ip);
            let played_idx = state.players[me_idx].stages.len() - 1;
            // trigger_on_play (effects.py:10661) は category 問わず last_self_chara_played_card を更新
            // (on_self/opp_chara_played 発火のみ CHARACTER 限定)。 通常 PlayStage arm と対称。
            state.last_self_chara_played_card = Some(ctx_card);
            state.last_self_chara_played_from_trash = false;
            execute_stage_on_play(state, me_idx, played_idx).is_ok()
        }
        // 手札 or トラッシュからキャラ登場 (effects.py:7678 play_from_hand_or_trash、 AI=手札優先→トラッシュ)。
        // ⚠ Python は hand 除去を loop 末尾で行う (= summon の on_play が hand を観測すると pop-first だと
        //   timing がズレる)。 → execute_on_play が観測を持たない場合のみ inline 実行、 それ以外は bail:
        //   登場カードに on_play / me 場に on_self_chara_played / opp 場に on_opp_chara_played があれば bail。
        //   guard 通過時は execute_on_play が no-op なので pop-first で安全。 STAGE/dynamic/no_effect/field-full
        //   は保守 bail。 played_from_trash は set しない (Python は trash 由来でも False = last_...from_trash=False)。
        "play_from_hand_or_trash" => {
            let spec = v.as_object();
            let resolved = resolve_dynamic_filter(spec.and_then(|o| o.get("filter")), state, me_idx);
            let filt = resolved.as_ref();
            if let Some(fo) = filt.and_then(|f| f.as_object()) {
                if fo.contains_key("or")
                    || fo.contains_key("name_in_last_discarded")
                    || fo.contains_key("no_effect")
                    || fo.get("category").and_then(|x| x.as_str()) == Some("STAGE")
                {
                    return false;
                }
            }
            let limit = spec.and_then(|o| o.get("limit")).and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let rested = spec.and_then(|o| o.get("rested")).and_then(|x| x.as_bool()).unwrap_or(false);
            let mut found = 0usize;
            // ⭐ Python timing (effects.py:5040): 登場カードは me.hand に残したまま on_play 発火 (on_play が
            // hand を観測)、 loop 末尾で unplayed を new_hand に再構築して置換。 index-based で on_play の
            // hand 追加も追随。 filt は cost_le_dynamic 解決済 static。
            let mut new_hand: Vec<crate::state::CardDef> = vec![];
            let mut i = 0;
            while i < state.players[me_idx].hand.len() {
                let card = state.players[me_idx].hand[i].clone();
                let m = found < limit
                    && card.category == crate::state::Category::Character
                    && matches_filter(&card, filt)
                    && !card_no_play_via_effect(&card.card_id);
                if m {
                    // 登場カードが on_play を持つ = Python の deferred drain (hand 除去後に on_play) を
                    // inline では再現できず hand 観測がズレる → 明示 bail。
                    if card_has_on_play(&card.card_id) {
                        return false;
                    }
                    trash_weakest_for_field_full(state, me_idx);
                    let mut ip = InPlay::of(card.clone(), true);
                    ip.rested = rested;
                    state.players[me_idx].characters.push(ip);
                    let pidx = state.players[me_idx].characters.len() - 1;
                    state.last_self_chara_played_card = Some(card);
                    state.last_self_chara_played_from_trash = false;
                    if execute_on_play(state, me_idx, pidx).is_err() {
                        return false;
                    }
                    found += 1;
                } else {
                    new_hand.push(card);
                }
                i += 1;
            }
            state.players[me_idx].hand = new_hand;
            if found < limit {
                let mut new_trash: Vec<crate::state::CardDef> = vec![];
                let mut ti = 0;
                while ti < state.players[me_idx].trash.len() {
                    let card = state.players[me_idx].trash[ti].clone();
                    let m = found < limit
                        && card.category == crate::state::Category::Character
                        && matches_filter(&card, filt);
                    if m {
                        // trash 由来登場でも on_play deferred 順は同じ問題 → 明示 bail。
                        if card_has_on_play(&card.card_id) {
                            return false;
                        }
                        trash_weakest_for_field_full(state, me_idx);
                        let mut ip = InPlay::of(card.clone(), true);
                        ip.rested = rested;
                        state.players[me_idx].characters.push(ip);
                        let pidx = state.players[me_idx].characters.len() - 1;
                        state.last_self_chara_played_card = Some(card);
                        state.last_self_chara_played_from_trash = false;
                        if execute_on_play(state, me_idx, pidx).is_err() {
                            return false;
                        }
                        found += 1;
                    } else {
                        new_trash.push(card);
                    }
                    ti += 1;
                }
                state.players[me_idx].trash = new_trash;
            }
            true
        }
        // このカード自身を登場させる (effects.py:6179 play_self、 trigger/on_ko 等 source-gone)。
        // src_cid = current_source_card_id (Python: self_inplay有無に関わらず event source と一致)。
        // trash→hand 順で cid+CHARACTER/STAGE を探し pop→登場 (pop-first なので timing 問題なし)。
        // played_from_trash は set しない (Python 準拠)。 field-full(CHARACTER)/source 不明は bail。
        "play_self" => {
            if v.as_bool() == Some(false) {
                return true; // play_self:false = 登場させない (no-op)
            }
            let Some(cid) = state.current_source_card_id.clone() else {
                return false; // source card 不明 → bail
            };
            let rested = v.as_object().and_then(|o| o.get("rested")).and_then(|x| x.as_bool()).unwrap_or(false);
            let found: Option<(bool, usize, crate::state::Category)> = {
                let me = &state.players[me_idx];
                let mut r = None;
                for (i, c) in me.trash.iter().enumerate() {
                    if c.card_id == cid
                        && matches!(c.category, crate::state::Category::Character | crate::state::Category::Stage)
                    {
                        r = Some((true, i, c.category));
                        break;
                    }
                }
                if r.is_none() {
                    for (i, c) in me.hand.iter().enumerate() {
                        if c.card_id == cid
                            && matches!(c.category, crate::state::Category::Character | crate::state::Category::Stage)
                        {
                            r = Some((false, i, c.category));
                            break;
                        }
                    }
                }
                r
            };
            let Some((from_trash, idx, cat)) = found else {
                return true; // 見つからない = no-op (Python continue)
            };
            let card = if from_trash {
                state.players[me_idx].trash.remove(idx)
            } else {
                state.players[me_idx].hand.remove(idx)
            };
            if cat == crate::state::Category::Stage {
                // STAGE 版: 既存ステージ (MAX 超) をトラッシュへ、 sickness=false で登場
                while state.players[me_idx].stages.len() >= 1 {
                    let old = state.players[me_idx].stages.pop().unwrap();
                    let ad = old.attached_dons;
                    state.players[me_idx].trash.push(old.card);
                    if ad > 0 {
                        state.players[me_idx].don_rested += ad;
                    }
                }
                let ip = InPlay::of(card.clone(), false);
                state.players[me_idx].stages.push(ip);
                let pidx = state.players[me_idx].stages.len() - 1;
                state.last_self_chara_played_card = Some(card);
                state.last_self_chara_played_from_trash = false;
                return execute_stage_on_play(state, me_idx, pidx).is_ok();
            }
            // CHARACTER: field full → 最弱キャラを trash (effects.py:6220 can_play_character() →
            // trash_weakest_chara_for_field_full)。 play_self_from_trash と同一 (parity 検証済)。
            trash_weakest_for_field_full(state, me_idx);
            let mut ip = InPlay::of(card.clone(), true); // sickness=true
            ip.rested = rested;
            state.players[me_idx].characters.push(ip);
            let pidx = state.players[me_idx].characters.len() - 1;
            state.last_self_chara_played_card = Some(card);
            state.last_self_chara_played_from_trash = false;
            execute_on_play(state, me_idx, pidx).is_ok()
        }
        // このキャラ自身を trash から登場 (effects.py:5923、 OP14-120 on_ko 自己蘇生)。 src_cid=
        // current_source_card_id で trash から探す (trash のみ、 play_self は hand も見る点が違う)。
        // field-full は trash_weakest (3-7-6-1)。 rested=false、 sickness=true、 on_play cascade。
        "play_self_from_trash" => {
            let Some(cid) = state.current_source_card_id.clone() else {
                return false;
            };
            let idx = state.players[me_idx]
                .trash
                .iter()
                .position(|c| c.card_id == cid && c.category == crate::state::Category::Character);
            let Some(idx) = idx else {
                return true; // trash に無い = no-op (Python return False だが do-loop は返値無視)
            };
            let card = state.players[me_idx].trash.remove(idx);
            trash_weakest_for_field_full(state, me_idx);
            let ip = InPlay::of(card.clone(), true); // sickness=true, rested=false
            state.players[me_idx].characters.push(ip);
            let pidx = state.players[me_idx].characters.len() - 1;
            state.last_self_chara_played_card = Some(card);
            state.last_self_chara_played_from_trash = false;
            execute_on_play(state, me_idx, pidx).is_ok()
        }
        // このカード自身の [when_kind] 効果を再発火 (effects.py:5923、 trigger/life の「このカードの【メイン】
        // 効果を発動」)。 current_source_card_id で overlay を引き、 条件 eval → do 実行 (cost は払わない、 Python
        // 準拠)。 source-gone src=Leader placeholder。 ⚠ do に fire_self_effect 再帰は sample 無 (depth guard 省略)。
        "fire_self_effect" => {
            let when_kind = if v.is_object() {
                v.get("when_kind").and_then(|x| x.as_str()).unwrap_or("main")
            } else {
                v.as_str().unwrap_or("main")
            }
            .to_string();
            let Some(cid) = state.current_source_card_id.clone() else { return true };
            let effs: Vec<Value> = match overlay().and_then(|ov| ov.get(&cid)) {
                Some(e) => e.clone(),
                None => return true,
            };
            for eff in &effs {
                if eff.get("when").and_then(|x| x.as_str()) != Some(when_kind.as_str()) {
                    continue;
                }
                match eval_effect_conditions(eff, state, me_idx, Some(src)) {
                    Some(true) => {}
                    Some(false) => continue,
                    None => return false,
                }
                if let Some(dos) = eff.get("do").and_then(|d| d.as_array()) {
                    if effect_cascade_blocked(dos, state, me_idx) {
                        return false;
                    }
                    for prim in dos {
                        if !execute_effect(prim, state, me_idx, src) {
                            return false;
                        }
                    }
                }
            }
            true
        }
        // 自リーダー/キャラ N 枚をレスト (effects.py:rest_self_cards、 AI=アクティブ中 power 低い順)。 cascade 無し。
        "rest_self_cards" => {
            let n = match v {
                Value::Object(o) => o.get("count").and_then(|x| x.as_i64()).unwrap_or(1),
                _ => v.as_i64().unwrap_or(1),
            } as usize;
            let mut actives: Vec<(Slot, i32)> = vec![];
            {
                let me = &state.players[me_idx];
                if !me.leader.rested {
                    actives.push((Slot::Leader, me.leader.power()));
                }
                for (i, c) in me.characters.iter().enumerate() {
                    if !c.rested {
                        actives.push((Slot::Char(i), c.power()));
                    }
                }
            }
            actives.sort_by(|a, b| a.1.cmp(&b.1)); // power 昇順 (stable=ties 原順)
            for (slot, _) in actives.into_iter().take(n) {
                get_ip_mut(&mut state.players[me_idx], slot).rested = true;
            }
            true
        }
        // 相手のステージ N 枚を KO (effects.py:ko_opp_stage、 cost/cost_le/cost_ge filter)。 player-level。
        // 付与ドン返却は無し (Python 準拠= s.card を trash に append のみ)。
        "ko_opp_stage" => {
            let spec = v.as_object();
            let limit = spec.and_then(|o| o.get("limit")).and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let cost_eq = spec.and_then(|o| o.get("cost")).and_then(|x| x.as_i64());
            let cost_le = spec.and_then(|o| o.get("cost_le")).and_then(|x| x.as_i64());
            let cost_ge = spec.and_then(|o| o.get("cost_ge")).and_then(|x| x.as_i64());
            let matches = |c: i32| -> bool {
                if let Some(e) = cost_eq {
                    if c as i64 != e {
                        return false;
                    }
                }
                if let Some(le) = cost_le {
                    if c as i64 > le {
                        return false;
                    }
                }
                if let Some(ge) = cost_ge {
                    if (c as i64) < ge {
                        return false;
                    }
                }
                true
            };
            let mut removed = 0usize;
            let old = std::mem::take(&mut state.players[opp_idx].stages);
            for s in old {
                if removed < limit && matches(s.card.cost) {
                    state.players[opp_idx].trash.push(s.card);
                    removed += 1;
                } else {
                    state.players[opp_idx].stages.push(s);
                }
            }
            true
        }
        // 自デッキ上 N 枚を見て並べ替え (effects.py:look_top_reorder)。 決定的 (AI 経路)。
        // to: top(順番維持=no-op)/ bottom(上N→下)/ choice(上Nをcost,name昇順)/ split(match_filter で振り分け)。
        "look_top_reorder" => {
            let spec_obj = v.as_object();
            let depth = spec_obj
                .and_then(|o| o.get("depth"))
                .or(if v.is_i64() { Some(v) } else { None })
                .and_then(|x| x.as_i64())
                .unwrap_or(1);
            let to_pos = spec_obj.and_then(|o| o.get("to")).and_then(|x| x.as_str()).unwrap_or("top");
            let me = &mut state.players[me_idx];
            if depth <= 0 || me.deck.is_empty() {
                return true;
            }
            let d = (depth as usize).min(me.deck.len());
            let all = std::mem::take(&mut me.deck);
            let mut it = all.into_iter();
            let top_n: Vec<crate::state::CardDef> = (&mut it).take(d).collect();
            let rest: Vec<crate::state::CardDef> = it.collect();
            match to_pos {
                "bottom" => {
                    me.deck = rest;
                    me.deck.extend(top_n);
                }
                "choice" => {
                    let mut t = top_n;
                    t.sort_by(|a, b| (a.cost, &a.name).cmp(&(b.cost, &b.name)));
                    me.deck = t;
                    me.deck.extend(rest);
                }
                "split" => {
                    let mf = spec_obj.and_then(|o| o.get("match_filter"));
                    let match_to = spec_obj.and_then(|o| o.get("match_to")).and_then(|x| x.as_str()).unwrap_or("hand");
                    let remain_to = spec_obj.and_then(|o| o.get("remain_to")).and_then(|x| x.as_str()).unwrap_or("bottom");
                    me.deck = rest;
                    let (mut matched, mut remain) = (Vec::new(), Vec::new());
                    for c in top_n {
                        if matches_filter(&c, mf) { matched.push(c) } else { remain.push(c) }
                    }
                    match match_to {
                        "hand" => me.hand.extend(matched),
                        "trash" => me.trash.extend(matched),
                        "top" => { let mut nd = matched; nd.append(&mut me.deck); me.deck = nd; }
                        _ => me.deck.extend(matched), // bottom
                    }
                    match remain_to {
                        "trash" => me.trash.extend(remain),
                        "top" => { let mut nd = remain; nd.append(&mut me.deck); me.deck = nd; }
                        "hand" => me.hand.extend(remain),
                        _ => me.deck.extend(remain), // bottom default
                    }
                }
                _ => {
                    // top = 順番維持 (no-op): 元の順で再構築
                    me.deck = top_n;
                    me.deck.extend(rest);
                }
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
        // 相手デッキ上 N 枚を「見る」(effects.py:5974、 OP11-070 プリン等)。 zone は動かさず、
        // acting player の私的知識として last_peeked_opp_deck_top (canonical field) に記録するだけ。
        "peek_opp_deck_top" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            }
            .max(0) as usize;
            let ids: Vec<String> = state.players[opp_idx]
                .deck
                .iter()
                .take(n)
                .map(|c| c.card_id.clone())
                .collect();
            state.last_peeked_opp_deck_top = Some(json!({"viewer_idx": me_idx, "card_ids": ids}));
            true
        }
        // 「元々のパワーが、 選んだキャラと同じになる」(effects.py:4784、 EB01-061 Mr.2 等)。
        // from_target の現在 power を to_target の base_power_override に duration 付きで複写。
        // 対象 0 (from/to どちらか) なら Python は return False = 効果不発 → Rust も false (bail)。
        "set_base_power_copy" => {
            let default_from = Value::String("one_opponent_character_any".into());
            let from_spec = if v.is_object() {
                v.get("from_target").cloned().unwrap_or(default_from)
            } else {
                default_from
            };
            let to_spec = if v.is_object() {
                v.get("to_target").cloned().unwrap_or(Value::String("self".into()))
            } else {
                Value::String("self".into())
            };
            let duration = if v.is_object() {
                v.get("duration").and_then(|x| x.as_str()).unwrap_or("turn").to_string()
            } else {
                "turn".to_string()
            };
            let Some(from_c) = resolve_target(Some(&from_spec), me_idx, opp_idx, src, state) else { return false };
            let Some(&(fp, fs)) = from_c.first() else { return false };
            let copied = get_ip(&state.players[fp], fs).power();
            let Some(to_c) = resolve_target(Some(&to_spec), me_idx, opp_idx, src, state) else { return false };
            if to_c.is_empty() {
                return false;
            }
            for (pi, sl) in to_c {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                match duration.as_str() {
                    "turn" => ip.turn_base_power_override = Some(copied),
                    "next_self_turn_start" => ip.next_turn_base_power_override = Some(copied),
                    _ => ip.base_power_override = Some(copied),
                }
            }
            true
        }
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
        // 自ライフ上 N 枚をトラッシュへ (effects.py:mill_self_life_to_trash、 自害効果)。 trigger 無し。
        "mill_self_life_to_trash" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            let me = &mut state.players[me_idx];
            for _ in 0..n {
                if me.life.is_empty() {
                    break;
                }
                let c = me.life.remove(0);
                me.trash.push(c);
            }
            true
        }
        // 自ライフ上 N 枚を手札へ (effects.py:life_to_hand)。 禁止 flag 時 no-op、 移動時 on_self_life_to_hand 発火。
        "life_to_hand" => {
            if state.players[me_idx].prevent_self_life_to_hand_until_turn_end {
                return true; // Python: 禁止で不発 (return False だが if_prev_succeeded 0 件で影響なし)
            }
            let n = v.as_i64().unwrap_or(0);
            let mut moved = 0;
            for _ in 0..n {
                let me = &mut state.players[me_idx];
                if !me.life.is_empty() {
                    let c = me.life.remove(0);
                    me.hand.push(c);
                    moved += 1;
                }
            }
            if moved > 0 && fire_field_when(state, me_idx, "on_self_life_to_hand").is_err() {
                return false; // cascade (on_self_life_to_hand) 再現不能 → bail
            }
            true
        }
        // ライフの上か下から N 枚を手札へ (effects.py:life_top_or_bottom_to_hand)。 AI=place で top/bottom、
        // card は actor(me) の手札へ (owner=opp でも me.hand、 Python 準拠)。 cascade 無 (life_to_hand と別)。
        "life_top_or_bottom_to_hand" => {
            let (owner_opp, count, bottom) = if let Some(o) = v.as_object() {
                (
                    o.get("owner").and_then(|x| x.as_str()) == Some("opp"),
                    o.get("count").and_then(|x| x.as_i64()).unwrap_or(1),
                    o.get("place").and_then(|x| x.as_str()) == Some("bottom"),
                )
            } else {
                (false, v.as_i64().unwrap_or(1), false)
            };
            if !owner_opp && state.players[me_idx].prevent_self_life_to_hand_until_turn_end {
                return true; // 禁止 = no-op (Python return False も action 継続)
            }
            let pi = if owner_opp { opp_idx } else { me_idx };
            for _ in 0..count {
                if state.players[pi].life.is_empty() {
                    break;
                }
                let card = if bottom {
                    state.players[pi].life.pop().unwrap()
                } else {
                    state.players[pi].life.remove(0)
                };
                state.players[me_idx].hand.push(card);
            }
            true
        }
        // 手札から filter 一致 count 枚までを自ライフ上へ (effects.py:hand_to_self_life)。 AI=先頭一致。 cascade 無。
        "hand_to_self_life" => {
            let (filt, count) = if let Some(o) = v.as_object() {
                (o.get("filter").cloned(), o.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize)
            } else {
                (None, v.as_i64().unwrap_or(1) as usize)
            };
            let me = &mut state.players[me_idx];
            let old = std::mem::take(&mut me.hand);
            let mut moved = 0;
            for c in old {
                if moved < count && matches_filter(&c, filt.as_ref()) {
                    me.life.push(c);
                    moved += 1;
                } else {
                    me.hand.push(c);
                }
            }
            true
        }
        // 自手札 N 枚を捨てる (effects.py:3147 trash_self_hand_random)。 ⚠ 名は random だが AI 経路は
        // _worst_hand_idx で決定的 (counter/cost/power/known)。 捨て後 hand_discarded_by_effect_this_turn=true
        // + on_self_hand_discarded cascade (last_discard context は Python が発火後 None にリセット = 不設定で一致)。
        "trash_self_hand_random" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            // 人間 modal (_picked_hand_idxs) は self-play では無し = AI 経路のみ実装。
            let mut discarded = 0;
            for _ in 0..n {
                let me = &mut state.players[me_idx];
                if me.hand.is_empty() {
                    break;
                }
                let Some(i) = worst_hand_idx(&me.hand, &me.known_hand_card_ids) else { break };
                let c = me.hand.remove(i);
                me.trash.push(c);
                discarded += 1;
            }
            if discarded > 0 {
                state.players[me_idx].hand_discarded_by_effect_this_turn = true;
                if fire_field_when(state, me_idx, "on_self_hand_discarded").is_err() {
                    return false; // cascade (on_self_hand_discarded) 再現不能 → bail
                }
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
        // 「このターン終了時に〜」 予約効果 (effects.py:6752、 OP14-031)。 spec を scheduled list に append
        // (canonical field なので digest に載る)。 ⚠ flush (turn-end 発火) は未実装 = EndPhase で別途 bail。
        "schedule_at_self_turn_end" => {
            state.players[me_idx].scheduled_at_self_turn_end.push(v.clone());
            true
        }
        // 「(target) が相手の元コスト N 以下のキャラへアタック不可」 (effects.py:7653、 OP12-020 リーダー)。
        // 対象に cannot_attack_target_cost_le_until_turn_end=N を set (attack 側は既に read 済)。
        "set_cannot_attack_target_cost_le" => {
            let default_tgt = Value::String("self_leader".into());
            let (tgt, cost_le) = if let Some(o) = v.as_object() {
                (
                    o.get("target").unwrap_or(&default_tgt),
                    o.get("cost_le").and_then(|x| x.as_i64()).unwrap_or(0) as i32,
                )
            } else {
                (&default_tgt, v.as_i64().unwrap_or(0) as i32)
            };
            let Some(targets) = resolve_target(Some(tgt), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).cannot_attack_target_cost_le_until_turn_end = cost_le;
            }
            true
        }
        // 相手レストキャラの次リフレッシュ非アクティブ化 (effects.py:6770、 OP05-094)。 target 既定
        // one_opponent_character_any。 ⚠ Python は rested の対象のみ flag (if t.rested)。
        "keep_opp_rested_chara_next_refresh" => {
            let default = Value::String("one_opponent_character_any".into());
            let tgt = v.get("target").unwrap_or(&default);
            let Some(targets) = resolve_target(Some(tgt), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                if ip.rested {
                    ip.stay_rested_next_refresh = true;
                }
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
            // source-gone (Detached) では Python も self_inplay=None で source 依存の KO 耐性判定を
            // **スキップ** する (effects.py:3352 `if thr >= 0 and self_inplay is not None`)。
            let src_pa: Option<(i32, String)> = src_ip(&state.players[me_idx], src)
                .map(|s| (s.card.power, s.card.attribute.clone()));
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
                    if let Some((src_power, src_attr)) = &src_pa {
                        if t.static_ko_immune_from_source_power_le >= 0
                            && *src_power <= t.static_ko_immune_from_source_power_le
                        {
                            continue;
                        }
                        let req = t.static_ko_immune_from_non_attribute.clone();
                        if !req.is_empty() && !src_attr.contains(&req) {
                            continue;
                        }
                    }
                    victims.push((pi, idx));
                }
            }
            if victims.is_empty() {
                return true; // 全 immune = 除去0・cascade 無し (immune 減算は済)
            }
            // KO cascade 発火要否 (effect_cascade_blocked と同基準)。 無ければ従来の一括除去。
            let vowner = victims[0].0;
            let cascade = me_board_has_when(state, me_idx, "on_opp_chara_ko")
                || me_board_has_when(state, vowner, "on_self_chara_ko")
                || me_board_has_when(state, vowner, "on_ko")
                || me_board_has_when(state, vowner, "replace_ko")
                || me_board_has_when(state, vowner, "replace_leave")
                || me_board_has_when(state, me_idx, "on_self_chara_leave_by_self_effect");
            if !cascade {
                remove_victims(state, victims, RemoveDest::Trash);
                return true;
            }
            // multi-victim cascade (effects.py:3282、 OP15-114 等): target 順に interleave で 除去→on_ko/
            // on_opp_chara_ko/on_self_chara_ko、 after-all で on_self_chara_leave_by_self_effect 1 回。
            // index shift = 同 player の既除去数を引く。 ⚠ cascade が victim board を想定外に変える (further KO/
            // replace) 場合は card_id 照合 or replace で bail (correctness 保守)。
            if victims.len() > 1 {
                let expected: Vec<(usize, usize, String)> = victims
                    .iter()
                    .map(|&(pi, idx)| (pi, idx, state.players[pi].characters[idx].card.card_id.clone()))
                    .collect();
                let mut removed_count: std::collections::HashMap<usize, usize> = std::collections::HashMap::new();
                let mut ko_any = false;
                let mut err = false;
                for (pi, orig_idx, cid) in &expected {
                    let shift = *removed_count.get(pi).unwrap_or(&0);
                    if *orig_idx < shift {
                        err = true;
                        break;
                    }
                    let cur_idx = orig_idx - shift;
                    if cur_idx >= state.players[*pi].characters.len()
                        || &state.players[*pi].characters[cur_idx].card.card_id != cid
                    {
                        err = true; // board が想定外に変化 → bail
                        break;
                    }
                    match try_replace_ko(state, *pi, cur_idx, true, "ko") {
                        Ok(true) => continue, // 置換発動 = victim 残存 (KO 阻止)。 removed_count 増やさず次へ
                        Ok(false) => {}
                        Err(_) => {
                            err = true;
                            break;
                        }
                    }
                    let vdon = state.players[*pi].characters[cur_idx].attached_dons;
                    let removed = state.players[*pi].characters.remove(cur_idx);
                    state.players[*pi].trash.push(removed.card);
                    state.players[*pi].don_rested += vdon;
                    state.players[*pi].chara_ko_taken_this_turn += 1;
                    *removed_count.entry(*pi).or_insert(0) += 1;
                    ko_any = true;
                    // 効果 ko は nested=deferred で victim None (上記 single と同じ)。
                    state.last_chara_ko_victim_card = None;
                    if fire_on_ko(state, *pi, cid).is_err() {
                        err = true;
                    }
                    if !err && fire_field_when(state, me_idx, "on_opp_chara_ko").is_err() {
                        err = true;
                    }
                    if !err && fire_field_when(state, *pi, "on_self_chara_ko").is_err() {
                        err = true;
                    }
                    state.last_chara_ko_victim_card = None;
                    if err {
                        break;
                    }
                }
                if err {
                    return false;
                }
                if ko_any
                    && fire_field_when(state, me_idx, "on_self_chara_leave_by_self_effect").is_err()
                {
                    return false;
                }
                return true;
            }
            let (vpi, vidx) = victims[0];
            // 置換効果 (effect KO = by_opp_effect=true)。 Ok(true)=KO阻止 / Ok(false)=続行 / Err=bail。
            match try_replace_ko(state, vpi, vidx, true, "ko") {
                Ok(true) => return true, // _ko_any=false → on_self_chara_leave 無し
                Ok(false) => {}
                Err(_) => return false,
            }
            // 除去 (remove+trash+付与ドン返却+chara_ko++、 battle_ko_character 相当) → per-victim cascade。
            let vcid = state.players[vpi].characters[vidx].card.card_id.clone();
            let vdon = state.players[vpi].characters[vidx].attached_dons;
            let removed = state.players[vpi].characters.remove(vidx);
            state.players[vpi].trash.push(removed.card);
            state.players[vpi].don_rested += vdon;
            state.players[vpi].chara_ko_taken_this_turn += 1;
            // effects.py:3320 順: on_ko(victim側 source-gone)→ on_opp_chara_ko(me)→ on_self_chara_ko(victim側)
            //   → on_self_chara_leave_by_self_effect(me、 effect 発動者視点)。 各 fire 未対応は Err→false。
            // ⭐ **効果 ko は nested resolution** (main/on_play/activate は _execute_event 内=resolving=True)
            // → Python は trigger_on_self_chara_ko を enqueue し、 その末尾で last_chara_ko_victim_card=None に
            // reset してから deferred で drain する = cascade 解決時 victim=None (victim_* 条件は空振り)。
            // battle ko (do_battle_ko、 resolving=False=immediate) だけ victim を set する (rules.rs)。 = 効果 ko は
            // victim None で発火 (OP15-020 の ko→OP14-041 on_self_chara_ko が Python skip と一致)。
            state.last_chara_ko_victim_card = None;
            let mut cascade_err = fire_on_ko(state, vpi, &vcid).is_err();
            if !cascade_err {
                cascade_err = fire_field_when(state, me_idx, "on_opp_chara_ko").is_err();
            }
            if !cascade_err {
                cascade_err = fire_field_when(state, vpi, "on_self_chara_ko").is_err();
            }
            if !cascade_err {
                cascade_err =
                    fire_field_when(state, me_idx, "on_self_chara_leave_by_self_effect").is_err();
            }
            state.last_chara_ko_victim_card = None;
            if cascade_err {
                return false;
            }
            true
        }
        // 手札に戻す (バウンス)。 protect チェック → 除去 + hand + 付与ドン返却。
        // 手札に戻す (バウンス、 effects.py:return_to_hand)。 opp victim = add_to_hand_publicly(hand+known)、
        // self victim = hand のみ。 cascade (replace_leave/on_self_chara_leave_by_opp_effect、 me の leave_by_self/
        // on_opp_chara_returned_to_hand) 要時は single-victim path (ko/return_to_deck と同構造)、 無ければ一括。
        "return_to_hand" => {
            let tgt_spec: Value = if v.is_object() && v.get("target").is_some() {
                v.get("target").unwrap().clone()
            } else {
                v.clone()
            };
            let Some(targets) = resolve_target(Some(&tgt_spec), me_idx, opp_idx, src, state) else { return false };
            let mut victims: Vec<(usize, usize)> = vec![];
            for &(pi, sl) in &targets {
                if let Slot::Char(idx) = sl {
                    let c = &state.players[pi].characters[idx];
                    if pi == opp_idx && (c.protect_from_opp_effect || c.static_ko_immune) {
                        continue;
                    }
                    victims.push((pi, idx));
                }
            }
            if victims.is_empty() {
                return true;
            }
            let has_opp_victim = victims.iter().any(|&(pi, _)| pi == opp_idx);
            let cascade = me_board_has_when(state, me_idx, "on_self_chara_leave_by_self_effect")
                || me_board_has_when(state, me_idx, "on_opp_chara_returned_to_hand_by_self_effect")
                || (has_opp_victim
                    && (me_board_has_when(state, opp_idx, "on_self_chara_leave_by_opp_effect")
                        || me_board_has_when(state, opp_idx, "replace_leave")));
            if !cascade {
                // 一括: opp=公開手札 (known)、 self=手札のみ。 remove は降順、 push は target 順 (昇順)。
                let mut desc = victims.clone();
                desc.sort_by(|a, b| b.1.cmp(&a.1));
                let mut removed: Vec<(usize, usize, crate::state::CardDef, i32)> = vec![];
                for (pi, idx) in desc {
                    let r = state.players[pi].characters.remove(idx);
                    let don = r.attached_dons;
                    removed.push((pi, idx, r.card, don));
                }
                removed.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.cmp(&b.1)));
                for (pi, _idx, card, don) in removed {
                    if pi == opp_idx {
                        state.players[pi].known_hand_card_ids.push(card.card_id.clone());
                    }
                    state.players[pi].hand.push(card);
                    state.players[pi].don_rested += don;
                }
                return true;
            }
            if victims.len() > 1 {
                return false;
            }
            let (vpi, vidx) = victims[0];
            if vpi == opp_idx {
                match try_replace_ko(state, vpi, vidx, true, "return_to_hand") {
                    Ok(true) => return true,
                    Ok(false) => {}
                    Err(_) => return false,
                }
                let vdon = state.players[vpi].characters[vidx].attached_dons;
                let removed = state.players[vpi].characters.remove(vidx);
                state.players[vpi].known_hand_card_ids.push(removed.card.card_id.clone());
                state.players[vpi].hand.push(removed.card);
                state.players[vpi].don_rested += vdon;
                state.last_chara_ko_victim_card = None; // 効果 cascade は nested=deferred で victim None
                let mut err = fire_field_when(state, vpi, "on_self_chara_leave_by_opp_effect").is_err();
                state.last_chara_ko_victim_card = None;
                if !err {
                    err = fire_field_when(state, me_idx, "on_self_chara_leave_by_self_effect").is_err();
                }
                if !err {
                    err = fire_field_when(state, me_idx, "on_opp_chara_returned_to_hand_by_self_effect").is_err();
                }
                if err {
                    return false;
                }
                true
            } else {
                let vdon = state.players[vpi].characters[vidx].attached_dons;
                let removed = state.players[vpi].characters.remove(vidx);
                state.players[vpi].hand.push(removed.card);
                state.players[vpi].don_rested += vdon;
                if fire_field_when(state, me_idx, "on_self_chara_leave_by_self_effect").is_err() {
                    return false;
                }
                if fire_field_when(state, me_idx, "on_opp_chara_returned_to_hand_by_self_effect").is_err() {
                    return false;
                }
                true
            }
        }
        // デッキ下に戻す (effects.py:5376)。 cascade (opp victim の replace_leave/on_self_chara_leave_by_opp_
        // effect、 me の on_self_chara_leave_by_self_effect) 要時は single-victim path で発火 (ko primitive と
        // 同構造)、 無ければ一括除去。
        "return_to_deck_bottom" => {
            let tgt_spec: Value = if v.is_object() && v.get("target").is_some() {
                v.get("target").unwrap().clone()
            } else {
                v.clone()
            };
            let Some(targets) = resolve_target(Some(&tgt_spec), me_idx, opp_idx, src, state) else { return false };
            let mut victims: Vec<(usize, usize)> = vec![];
            for &(pi, sl) in &targets {
                if let Slot::Char(idx) = sl {
                    let c = &state.players[pi].characters[idx];
                    if pi == opp_idx && (c.protect_from_opp_effect || c.static_ko_immune) {
                        continue;
                    }
                    victims.push((pi, idx));
                }
            }
            if victims.is_empty() {
                return true;
            }
            let has_opp_victim = victims.iter().any(|&(pi, _)| pi == opp_idx);
            let cascade = me_board_has_when(state, me_idx, "on_self_chara_leave_by_self_effect")
                || (has_opp_victim
                    && (me_board_has_when(state, opp_idx, "on_self_chara_leave_by_opp_effect")
                        || me_board_has_when(state, opp_idx, "replace_leave")));
            if !cascade {
                remove_victims(state, victims, RemoveDest::DeckBottom);
                return true;
            }
            if victims.len() > 1 {
                return false; // multi-victim cascade = index shift 複雑 → bail
            }
            let (vpi, vidx) = victims[0];
            if vpi == opp_idx {
                // 置換 (return_to_deck_bottom leave_kind、 by_opp_effect=true)。 Ok(true)=離脱阻止。
                match try_replace_ko(state, vpi, vidx, true, "return_to_deck_bottom") {
                    Ok(true) => return true,
                    Ok(false) => {}
                    Err(_) => return false,
                }
                let vdon = state.players[vpi].characters[vidx].attached_dons;
                let removed = state.players[vpi].characters.remove(vidx);
                state.players[vpi].deck.push(removed.card);
                state.players[vpi].don_rested += vdon;
                // per-victim on_self_chara_leave_by_opp_effect (opp、 victim card、 fire 後 None=Python 12112)。
                state.last_chara_ko_victim_card = None; // 効果 cascade は nested=deferred で victim None
                let mut err = fire_field_when(state, vpi, "on_self_chara_leave_by_opp_effect").is_err();
                state.last_chara_ko_victim_card = None;
                if !err {
                    err = fire_field_when(state, me_idx, "on_self_chara_leave_by_self_effect").is_err();
                }
                if err {
                    return false;
                }
                true
            } else {
                let vdon = state.players[vpi].characters[vidx].attached_dons;
                let removed = state.players[vpi].characters.remove(vidx);
                state.players[vpi].deck.push(removed.card);
                state.players[vpi].don_rested += vdon;
                if fire_field_when(state, me_idx, "on_self_chara_leave_by_self_effect").is_err() {
                    return false;
                }
                true
            }
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
        // 相手リーダーに N ダメージ (effects.py:5384、 EB03-055 on_ko)。 相手ライフ N を相手手札へ (トリガー
        // 判定は省略=公式簡略、 Python 準拠)。 ライフ 0 で受けると【敗北】= on_life_zero (エネル等回復) を試み、
        // まだ 0 なら declare_winner。 opp 場に on_life_zero があれば回復 cascade 再現不能で bail、 無ければ勝利宣言。
        "deal_opp_leader_damage" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            for _ in 0..n {
                if state.players[opp_idx].life.is_empty() {
                    // on_life_zero (回復効果) を持つ相手は cascade 再現不能 → bail。
                    if me_board_has_when(state, opp_idx, "on_life_zero") {
                        return false;
                    }
                    // 回復手段なし → 効果ダメージで敗北宣言 (declare_winner 相当)。
                    if !state.game_over {
                        state.winner = Some(me_idx);
                        state.game_over = true;
                    }
                    return true;
                }
                let taken = state.players[opp_idx].life.remove(0);
                state.players[opp_idx].hand.push(taken);
            }
            true
        }
        // 自ドンを任意枚 rest → rest 1枚につき target に battle_buff +amount (effects.py:rest_self_don_for_
        // battle_buff_per_don、 OP13-001 opp_attack 防御)。 AI = don_active を max まで rest (防御最大化)。
        "rest_self_don_for_battle_buff_per_don" => {
            let target_spec = v.get("target").cloned().unwrap_or(Value::String("self_leader".into()));
            let amount_per = v.get("amount_per_rest").and_then(|x| x.as_i64()).unwrap_or(2000) as i32;
            let max_n = v.get("max").and_then(|x| x.as_i64()).unwrap_or(5) as i32;
            let rest_n = state.players[me_idx].don_active.min(max_n);
            if rest_n <= 0 {
                return true; // active=0 = no-op (Python return False だが do-loop 返値無視)
            }
            state.players[me_idx].don_active -= rest_n;
            state.players[me_idx].don_rested += rest_n;
            let buff = amount_per * rest_n;
            let Some(targets) = resolve_target(Some(&target_spec), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).battle_buff += buff;
            }
            true
        }
        // 自場のドン N 枚 (active 優先→rested) をドンデッキに戻す (effects.py:5302、 replace_leave の do 等)。
        // ⚠ on_self_don_returned_to_deck cascade は me 場に該当 when あれば bail。
        "return_self_don_to_deck" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            } as i32;
            let moved = {
                let me = &mut state.players[me_idx];
                let from_active = n.min(me.don_active);
                me.don_active -= from_active;
                me.don_remaining_in_deck += from_active;
                let from_rested = (n - from_active).min(me.don_rested);
                me.don_rested -= from_rested;
                me.don_remaining_in_deck += from_rested;
                from_active + from_rested
            };
            if moved > 0 && me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
                return false; // cascade 未対応 → bail
            }
            true
        }
        // 自トラッシュから filter 一致 count 枚を手札へ公開追加 (effects.py:7029、 OP14-093 on_ko)。
        // AI = trash 順で先頭 count 枚。 add_to_hand_publicly = hand + known_hand_card_ids。 dynamic filter は bail。
        "search_from_trash" => {
            let filt = v.get("filter");
            if let Some(fo) = filt.and_then(|f| f.as_object()) {
                if fo.keys().any(|k| k.ends_with("_dynamic")) {
                    return false;
                }
            }
            let count = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let me = &mut state.players[me_idx];
            let mut picks: Vec<usize> = vec![];
            for (i, c) in me.trash.iter().enumerate() {
                if picks.len() >= count {
                    break;
                }
                if matches_filter(c, filt) {
                    picks.push(i);
                }
            }
            // 降順 pop (index ずれ防止) → hand + known_hand (Python は sorted(-idx) 順で add_to_hand_publicly)。
            picks.sort_unstable_by(|a, b| b.cmp(a));
            for i in picks {
                let c = me.trash.remove(i);
                me.known_hand_card_ids.push(c.card_id.clone());
                me.hand.push(c);
            }
            true
        }
        // このターン中キャラ登場禁止 (effects.py:5686、 OP14-020 緑ミホーク)。 Phase.END でクリア。
        // block_chara_play / block_chara_play_turn: 共に自陣キャラ登場禁止 flag (effects.py:5544/5707)。
        "block_chara_play" | "block_chara_play_turn" => {
            state.players[me_idx].block_chara_play_until_turn_end = true;
            true
        }
        // このターン中、 自効果ドロー禁止 (effects.py:block_self_draw_turn、 OP12-099 on_self_life_to_hand)。
        "block_self_draw_turn" => {
            state.players[me_idx].block_self_draw_until_turn_end = true;
            true
        }
        // このターン中、 自効果でライフを手札に加えられない (effects.py:prevent_self_life_to_hand_turn)。
        "prevent_self_life_to_hand_turn" => {
            state.players[me_idx].prevent_self_life_to_hand_until_turn_end = true;
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
        // timed base-power override は apply_static_primitive に住むが、 Python は execute 一元管理なので
        // conditional/trigger 経路でも実行される (ST36-003 trigger→conditional→self_leader 元々パワー7000)。
        // 一回書き込み型 (turn_base_power_override 等、 recompute 非依存) なので generic 経路で安全に委譲。
        "set_base_power_timed" => {
            apply_static_primitive(prim, state, me_idx, src);
            true
        }
        // 効果による勝利 (OP09-118 速攻ルフィ on_opp_blocker_use、 effects.py:7669 declare_winner)。
        "win_game" => {
            if !state.game_over {
                state.winner = Some(me_idx);
                state.game_over = true;
            }
            true
        }
        // 自ライフ上 1 枚を公開 (場所変えず) → その cost × per_cost を src に turn pump (OP15-119 ルフィ、
        // effects.py:5902)。 on_opp_blocker_use/opp_event_or_trigger_fired で発火 = src は場のカード (有効)。
        "reveal_self_life_top_pump_per_cost" => {
            let per = if v.is_object() {
                v.get("per_cost").and_then(|x| x.as_i64()).unwrap_or(1000)
            } else {
                1000
            } as i32;
            if !state.players[me_idx].life.is_empty() {
                let cost = state.players[me_idx].life[0].cost;
                // source-gone なら pump 先が無い (Python: self_inplay=None → 対象 0) = no-op
                let Some(ip) = src_ip_mut(&mut state.players[me_idx], src) else { return true };
                ip.turn_buff += per * cost;
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
    // ⚠ dest への push 順は Python の target 順 (= 昇順 idx = `for t in targets`)。 remove は index shift
    // 回避で降順だが、 push は昇順に揃える (multi-victim で trash/hand/deck 順が Python と一致、 OP15-114)。
    victims.sort_by(|a, b| b.1.cmp(&a.1)); // 降順 remove
    let mut removed: Vec<(usize, usize, crate::state::CardDef, i32)> = vec![];
    for (pi, idx) in victims {
        if idx >= state.players[pi].characters.len() {
            continue;
        }
        let r = state.players[pi].characters.remove(idx);
        let don = r.attached_dons;
        removed.push((pi, idx, r.card, don));
    }
    removed.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.cmp(&b.1))); // (pi, idx) 昇順 = target 順で push
    for (pi, _idx, card, don) in removed {
        match dest {
            RemoveDest::Trash => {
                state.players[pi].trash.push(card);
                state.players[pi].chara_ko_taken_this_turn += 1;
            }
            RemoveDest::Hand => state.players[pi].hand.push(card),
            RemoveDest::DeckBottom => state.players[pi].deck.push(card),
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
fn pay_on_play_cost(cost: &Value, state: &mut GameState, me_idx: usize, src: Slot) -> Option<bool> {
    let mut pay_don = 0i32;
    let mut rest_don = 0i32;
    let mut rest_self = false;
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
    let mut discard_n = 0i32;
    for (k, v) in entries {
        match k.as_str() {
            "pay_don" => pay_don += v as i32,
            "rest_self_don" => rest_don += v as i32,
            "discard_hand" => discard_n += v as i32,
            "rest_self" => rest_self = true,
            _ => return None, // 未対応 cost 種別 → skip effect
        }
    }
    // rest_self: source (= 登場カード自身) をレスト。 既レストなら払えない (payability)。
    if rest_self {
        // effects.py:544 — source-gone or 既レスト は払えない
        match src_ip(&state.players[me_idx], src) {
            Some(ip) if !ip.rested => {}
            _ => return Some(false),
        }
        get_ip_mut(&mut state.players[me_idx], src).rested = true;
    }
    // rest_self_don: don_active >= n 必要 (payability)、 active→rested。
    if rest_don > 0 {
        let me = &state.players[me_idx];
        if me.don_active < rest_don {
            return Some(false); // 支払い不能
        }
        let me = &mut state.players[me_idx];
        me.don_active -= rest_don;
        me.don_rested += rest_don;
    }
    // discard_hand: 手札 N 枚以上必要 (_can_pay)、 _worst_hand_idx で捨て (effects.py:_pay_counter_cost)。
    // 捨て後 hand_discarded_by_effect flag + on_self_hand_discarded cascade (last_discard は発火後 None リセット)。
    if discard_n > 0 {
        if (state.players[me_idx].hand.len() as i32) < discard_n {
            return Some(false); // 支払い不能
        }
        let mut discarded = 0;
        for _ in 0..discard_n {
            let me = &mut state.players[me_idx];
            if me.hand.is_empty() {
                break;
            }
            let Some(i) = worst_hand_idx(&me.hand, &me.known_hand_card_ids) else { break };
            let c = me.hand.remove(i);
            me.trash.push(c);
            discarded += 1;
        }
        if discarded > 0 {
            state.players[me_idx].hand_discarded_by_effect_this_turn = true;
            if fire_field_when(state, me_idx, "on_self_hand_discarded").is_err() {
                return None; // cascade 再現不能 → bail
            }
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
            // ko (single) は prim 側で cascade を自前処理 (single victim) or 内部 bail → ここでは block しない。
            "ko_multi" | "ko_all_others" => {
                has(me_idx, "on_opp_chara_ko")
                    || has(opp, "on_self_chara_ko")
                    || has(opp, "on_ko")
                    || has(opp, "replace_ko")
                    || has(opp, "replace_leave")
            }
            // return_to_hand/deck_bottom (single) は prim 側で cascade を自前処理 → ここでは block しない。
            "return_to_hand_multi" | "return_to_deck_bottom_multi" => {
                has(opp, "on_self_chara_leave_by_self_effect") || has(opp, "replace_leave")
            }
            // rest (single-path) は prim 側で on_self_rested cascade を自前発火 → ここでは block しない。
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
pub fn execute_card_effects(
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
            match pay_on_play_cost(cost, state, me_idx, src) {
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

/// レストされた char 自身の【レスト時】(on_self_rested) を発火 (effects.py:trigger_on_self_rested、 targeted)。
/// bundle = rested char の overlay。 条件 (self_turn 等) を src=rested char で eval、 costless のみ発火、
/// cost(once_per_turn は iid-keyed=canonical外)/unknown/未対応 prim は Err で bail。
fn fire_on_self_rested(state: &mut GameState, owner_idx: usize, char_idx: usize) -> Result<(), String> {
    let cid = state.players[owner_idx].characters[char_idx].card.card_id.clone();
    let Some(ov) = overlay() else { return Ok(()) };
    let Some(effs) = ov.get(&cid) else { return Ok(()) };
    if !effs.iter().any(|e| e.get("when").and_then(|v| v.as_str()) == Some("on_self_rested")) {
        return Ok(());
    }
    for eff in effs {
        if eff.get("when").and_then(|v| v.as_str()) != Some("on_self_rested") {
            continue;
        }
        let src = Slot::Char(char_idx);
        match eval_effect_conditions(eff, state, owner_idx, Some(src)) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("on_self_rested 条件 unknown".into()),
        }
        if let Some(cost) = eff.get("cost") {
            if !cost_is_empty(cost) {
                return Err("on_self_rested cost 未対応".into()); // once_per_turn=iid-keyed
            }
        }
        if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
            if effect_cascade_blocked(dos, state, owner_idx) {
                return Err("on_self_rested cascade 未対応".into());
            }
            for prim in dos {
                if !execute_effect(prim, state, owner_idx, src) {
                    return Err("on_self_rested primitive 再現不能".into());
                }
            }
        }
    }
    Ok(())
}

/// 対象 char をレスト + on_self_rested 発火 (rest cascade)。 replace_rest / on_self_chara_rested_by_self_
/// effect (field-wide) は未対応で Err bail。 既 rested/cannot_be_rested は skip。 Err = 呼出側 false。
fn rest_char_with_cascade(
    state: &mut GameState,
    me_idx: usize,
    pi: usize,
    idx: usize,
    src: Slot,
) -> Result<(), String> {
    {
        let ip = &state.players[pi].characters[idx];
        if ip.cannot_be_rested_buff || ip.static_cannot_be_rested || ip.rested {
            return Ok(());
        }
    }
    // 置換効果 (replace_rest、 PRB02-006 ゾロ): victim 自身の overlay を試行。 発動で rest キャンセル。
    // by_opp_chara_effect = 別プレイヤーの CHARACTER 効果でレストされる場合 (src が Char)。
    if me_board_has_when(state, pi, "replace_rest") {
        let by_opp_chara = pi != me_idx && matches!(src, Slot::Char(_));
        if try_replace_rest(state, pi, me_idx, idx, by_opp_chara)? {
            return Ok(()); // 置換発動 = 本来の rest はキャンセル
        }
    }
    if pi == me_idx && me_board_has_when(state, me_idx, "on_self_chara_rested_by_self_effect") {
        return Err("on_self_chara_rested_by_self_effect 未対応".into());
    }
    state.players[pi].characters[idx].rested = true;
    fire_on_self_rested(state, pi, idx)
}

/// rest 効果が victim にかかる前の置換 (when="replace_rest"、 effects.py:try_replace_rest)。
/// victim 自身の overlay の replace_rest を試行。 発動・成功で Ok(true) (本来の rest をキャンセル)。
/// target=self のみ / cost 持ちや未対応 do は Err で bail。
fn try_replace_rest(
    state: &mut GameState,
    victim_pi: usize,
    actor_idx: usize,
    victim_idx: usize,
    by_opp_chara_effect: bool,
) -> Result<bool, String> {
    let _ = actor_idx;
    let vcid = state.players[victim_pi].characters[victim_idx].card.card_id.clone();
    let Some(ov) = overlay() else { return Ok(false) };
    let Some(effs) = ov.get(&vcid) else { return Ok(false) };
    for eff in effs {
        if eff.get("when").and_then(|v| v.as_str()) != Some("replace_rest") {
            continue;
        }
        let if_spec = eff.get("if").and_then(|v| v.as_object());
        let target = if_spec
            .and_then(|o| o.get("target"))
            .and_then(|v| v.as_str())
            .unwrap_or("self");
        if target != "self" {
            continue; // victim 自身が holder の case のみ対応
        }
        let need_opp_chara = if_spec
            .and_then(|o| o.get("by_opp_chara_effect"))
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        if need_opp_chara && !by_opp_chara_effect {
            continue;
        }
        // 残り condition (opp_turn 等) を victim 視点で eval (target/by_opp_* は除外)。
        if let Some(o) = if_spec {
            let mut extra = serde_json::Map::new();
            for (k, val) in o {
                if !matches!(k.as_str(), "target" | "by_opp_chara_effect" | "by_opp_effect") {
                    extra.insert(k.clone(), val.clone());
                }
            }
            if !extra.is_empty() {
                match eval_condition(&Value::Object(extra), state, victim_pi, Some(Slot::Char(victim_idx))) {
                    Some(true) => {}
                    Some(false) => continue,
                    None => return Err("replace_rest 条件 unknown".into()),
                }
            }
        }
        if eff.get("cost").map_or(false, |c| !cost_is_empty(c)) {
            return Err("replace_rest cost 未対応".into());
        }
        // do を holder=victim slot で実行 (rest other_self_chara 等)。 未対応 prim は bail。
        if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
            for prim in dos {
                if !execute_effect(prim, state, victim_pi, Slot::Char(victim_idx)) {
                    return Err("replace_rest do 未対応".into());
                }
            }
        }
        return Ok(true);
    }
    Ok(false)
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
            | "untap_don" | "untap" | "untap_chara" | "rest" | "cost_minus" | "attach_rested_don" | "mill_self_top"
            | "life_to_hand" | "trash_self_hand_random" | "redirect_attack" | "mill_self_life_to_trash"
            | "mill" | "mill_opp_life_to_hand" | "mill_opp_life_to_trash" | "look_top_reorder"
            | "hand_to_self_life" | "life_top_or_bottom_to_hand" | "disable_effect"
            | "stay_rested_next_refresh" | "set_cannot_rest" | "set_cannot_attack" | "put_top_to_life"
            | "optional_discard_hand_for_battle_buff" | "conditional" | "optional_cost_then"
            | "play_from_hand" | "play_from_trash" | "play_multi_from_trash"
            | "rest_self_don_for_battle_buff_per_don"
            // block_self_draw_turn = player-level flag のみ (src 非参照/cascade 無)。 OP12-099 の
            // on_self_life_to_hand [draw, block_self_draw_turn] が OP08-098 then_life 経由で発火。
            | "block_self_draw_turn"
            // reveal_self_life_top_pump_per_cost = src (場のカード) を turn pump。 OP15-119 が
            // on_opp_blocker_use/opp_event_or_trigger_fired で発火 (src 有効)。
            | "reveal_self_life_top_pump_per_cost"
            // win_game = 効果勝利 (OP09-118 on_opp_blocker_use)。 game_over/winner set のみ。
            | "win_game"
            // peek_opp_deck_top = zone 不変 + last_peeked_opp_deck_top 記録のみ (私的情報)。
            // set_base_power_copy = target 解決 → base_power_override 複写 (cascade 無)。
            | "peek_opp_deck_top" | "set_base_power_copy"
            // negate_effect = granted_keywords に "効果無効" を足すだけ (cascade 無)。
            | "negate_effect"
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
pub fn fire_gated_do(
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
            return Err(format!("when-effect primitive 未対応: {key}"));
        }
        if key == "draw" && me_board_has_when(state, me_idx, "on_self_draw_non_draw_phase") {
            return Err("draw cascade (on_self_draw_non_draw_phase) 未対応".into());
        }
    }
    for prim in dos {
        if !execute_effect(prim, state, me_idx, src) {
            let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("?");
            // 診断用に spec も載せる (どの target/amount 形が未対応かを bail 集計から直に読む為)
            let spec = prim.to_string();
            let spec = if spec.len() > 120 { spec[..120].to_string() } else { spec };
            return Err(format!("when-effect primitive 再現不能: {k} {spec}"));
        }
    }
    Ok(())
}

/// 【KO時】(on_ko) を発火 (effects.py:trigger_on_ko、 battle KO 経路 = by_opp_effect=false)。
/// effects.py:_replace_ko_match の port。 Some(true)=対象一致 / Some(false)=不一致 / None=未知 target キーで bail。
/// holder_is_victim = holder slot == victim slot (Rust は instance_id 無しなので位置で identity 代替)。
/// truly_original_power = victim.card.power (印字値、 効果非依存)。
fn replace_ko_match(
    cond: &serde_json::Map<String, Value>,
    holder_is_victim: bool,
    victim: &crate::state::CardDef,
    by_opp_effect: bool,
) -> Option<bool> {
    if cond.get("by_opp_effect").and_then(|v| v.as_bool()).unwrap_or(false) && !by_opp_effect {
        return Some(false);
    }
    if cond.get("by_battle").and_then(|v| v.as_bool()).unwrap_or(false) && by_opp_effect {
        return Some(false);
    }
    match cond.get("target").and_then(|v| v.as_str()).unwrap_or("self") {
        "self" => {
            if !holder_is_victim {
                return Some(false);
            }
        }
        "other_self_chara" => {
            if holder_is_victim {
                return Some(false);
            }
        }
        "any_self_chara" => {}
        _ => return Some(false),
    }
    if let Some(a) = cond.get("target_attribute").and_then(|v| v.as_str()) {
        if !victim.attribute.contains(a) {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_cost_le").and_then(|v| v.as_i64()) {
        if victim.cost as i64 > n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_cost_ge").and_then(|v| v.as_i64()) {
        if (victim.cost as i64) < n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_power_le").and_then(|v| v.as_i64()) {
        if victim.power as i64 > n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_truly_original_power_eq").and_then(|v| v.as_i64()) {
        if victim.power as i64 != n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_power_ge").and_then(|v| v.as_i64()) {
        if (victim.power as i64) < n {
            return Some(false);
        }
    }
    if let Some(f) = cond.get("target_feature").and_then(|v| v.as_str()) {
        if !victim.features.iter().any(|x| x == f) {
            return Some(false);
        }
    }
    if let Some(f) = cond.get("target_feature_contains").and_then(|v| v.as_str()) {
        if !victim.features.iter().any(|x| x.contains(f)) {
            return Some(false);
        }
    }
    if let Some(c) = cond.get("target_color").and_then(|v| v.as_str()) {
        if !victim.color.iter().any(|x| x == c) {
            return Some(false);
        }
    }
    if let Some(ex) = cond.get("target_name_exclude") {
        let hit = match ex {
            Value::String(s) => s == &victim.name,
            Value::Array(a) => a.iter().any(|x| x.as_str() == Some(victim.name.as_str())),
            _ => false,
        };
        if hit {
            return Some(false);
        }
    }
    if let Some(nm) = cond.get("target_name") {
        let ok = match nm {
            Value::String(s) => s == &victim.name,
            Value::Array(a) => a.iter().any(|x| x.as_str() == Some(victim.name.as_str())),
            _ => true,
        };
        if !ok {
            return Some(false);
        }
    }
    Some(true)
}

/// game.py:try_replace_ko の port (置換効果 replace_ko/replace_leave)。 victim は KO しようとするキャラ。
/// Ok(true)=置換発動 (KO/離脱を阻止= victim 残存)、 Ok(false)=該当なし (通常 KO 続行)、 Err=再現不能 bail。
/// ⚠ Phase A: 対象一致した replace は cost/do 未実装で bail。 不一致 (by_opp_effect 相違 / filter 外) だけ
///   Ok(false) で通常 KO へ流す (battle KO=by_opp_effect false のカードが大半なので大量に解決)。
pub fn try_replace_ko(
    state: &mut GameState,
    victim_owner: usize,
    victim_char_idx: usize,
    by_opp_effect: bool,
    leave_kind: &str,
) -> Result<bool, String> {
    let Some(ov) = overlay() else { return Ok(false) };
    let victim_slot = Slot::Char(victim_char_idx);
    let victim_card = get_ip(&state.players[victim_owner], victim_slot).card.clone();
    // holder 走査順: leader → chars → stages (Python と同順、 先頭一致で発動)
    let mut holders: Vec<Slot> = vec![Slot::Leader];
    for i in 0..state.players[victim_owner].characters.len() {
        holders.push(Slot::Char(i));
    }
    for i in 0..state.players[victim_owner].stages.len() {
        holders.push(Slot::Stage(i));
    }
    // extra_cond に回さない target/by_* キー (effects.py:12283 の除外リストと一致)
    const EXCL: &[&str] = &[
        "target", "target_attribute", "target_cost_le", "target_power_le", "target_power_ge",
        "target_feature", "target_feature_contains", "target_color", "target_name_exclude",
        "target_name", "target_rested", "by_opp_effect", "by_battle",
    ];
    let empty = serde_json::Map::new();
    for hslot in holders {
        let hcid = get_ip(&state.players[victim_owner], hslot).card.card_id.clone();
        let Some(effs) = ov.get(&hcid) else { continue };
        for eff in effs {
            let matches_leave = match eff.get("when").and_then(|v| v.as_str()) {
                Some("replace_ko") => leave_kind == "ko",
                Some("replace_leave") => true,
                _ => false,
            };
            if !matches_leave {
                continue;
            }
            let cond = eff.get("if").and_then(|v| v.as_object()).unwrap_or(&empty);
            match replace_ko_match(cond, hslot == victim_slot, &victim_card, by_opp_effect) {
                Some(true) => {}
                Some(false) => continue,
                None => return Err("replace_ko match 未知 target キー".into()),
            }
            // target/by_* 以外の条件 (leader_feature 等) を eval_condition (holder = src)
            let extra: serde_json::Map<String, Value> = cond
                .iter()
                .filter(|(k, _)| !EXCL.contains(&k.as_str()))
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect();
            if !extra.is_empty() {
                match eval_condition(&Value::Object(extra), state, victim_owner, Some(hslot)) {
                    Some(true) => {}
                    Some(false) => continue,
                    None => return Err("replace_ko extra_cond unknown".into()),
                }
            }
            // 対象一致 = 置換発動 (Phase B)。 cost は once_per_turn (canonical 追跡) + discard_hand_with_filter
            // (payability check) に対応、 他 (pay_don/life 等) は bail。 do は cascade 無し・非victim参照の safe のみ。
            let mut has_once = false;
            let mut discard_filter: Option<Value> = None;
            if let Some(cost) = eff.get("cost") {
                let entries: Vec<&Value> = match cost {
                    Value::Array(a) => a.iter().collect(),
                    Value::Object(_) => vec![cost],
                    _ => vec![],
                };
                for cs in entries {
                    if let Some(o) = cs.as_object() {
                        for (k, val) in o {
                            match k.as_str() {
                                "once_per_turn" => has_once = true,
                                "discard_hand_with_filter" => discard_filter = Some(val.clone()),
                                _ => return Err(format!("replace cost 未対応 ({hcid})")),
                            }
                        }
                    }
                }
            }
            // once_per_turn: このターン既発動 (card-id-keyed) なら skip → 通常 KO へ (effects.py:12500)。
            if has_once && state.players[victim_owner].replace_opt_used_cards.contains(&hcid) {
                continue;
            }
            // discard_hand_with_filter cost の payability (= 該当手札不足なら払えない → 通常 KO へ continue)。
            let discard_cost: Option<(Value, usize)> = if let Some(dwf) = &discard_filter {
                let (filt, cnt) = filter_and_count(dwf);
                let avail = state.players[victim_owner]
                    .hand
                    .iter()
                    .filter(|c| matches_filter(c, Some(&filt)))
                    .count();
                if avail < cnt {
                    continue; // 払えない = 置換不発 → 通常 KO
                }
                Some((filt, cnt))
            } else {
                None
            };
            let dos: Vec<Value> =
                eff.get("do").and_then(|v| v.as_array()).cloned().unwrap_or_default();
            for prim in &dos {
                let pk = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("");
                // rest_self_cards / return_self_don_to_deck = 非re-leave・非victim参照の safe do (holder=src)。
                // return_to_deck_bottom (OP15-052 = one_self_character_any を deck へ) = 自 char の return =
                // by_self_effect なので replace(全て by_opp_effect 要求)を再誘発しない = 無限ループ無し。
                // ⚠ 但し返した char の on_self_chara_leave_by_self_effect cascade は execute_effect が自前
                // 発火しないので、 holder owner 場に該当 when あれば bail (再現不能)。
                if !matches!(pk, "rest_self_cards" | "return_self_don_to_deck" | "return_to_deck_bottom") {
                    return Err(format!("replace do 未対応 ({pk})"));
                }
                if pk == "return_to_deck_bottom"
                    && me_board_has_when(state, victim_owner, "on_self_chara_leave_by_self_effect")
                {
                    return Err("replace do return_to_deck_bottom cascade 未対応".into());
                }
            }
            // discard_hand_with_filter cost 支払い (Python _pay_replace_cost、 do 前)。 先頭 cnt 個の matching を
            // 降順 pop → hand_discarded flag + on_self_hand_discarded cascade (未対応なら bail)。 OP15-014。
            if let Some((filt, cnt)) = discard_cost {
                let mut matching: Vec<usize> = state.players[victim_owner]
                    .hand
                    .iter()
                    .enumerate()
                    .filter(|(_, c)| matches_filter(c, Some(&filt)))
                    .map(|(i, _)| i)
                    .take(cnt)
                    .collect();
                matching.sort_unstable_by(|a, b| b.cmp(a));
                let n_disc = matching.len();
                for i in matching {
                    let c = state.players[victim_owner].hand.remove(i);
                    state.players[victim_owner].trash.push(c);
                }
                if n_disc > 0 {
                    state.players[victim_owner].hand_discarded_by_effect_this_turn = true;
                    if fire_field_when(state, victim_owner, "on_self_hand_discarded").is_err() {
                        return Err("replace cost discard cascade 未対応".into());
                    }
                }
            }
            // once_per_turn 使用済マーク (Python _pay_replace_cost、 do 前)。 canonical sorted。
            if has_once {
                let used = &mut state.players[victim_owner].replace_opt_used_cards;
                if !used.contains(&hcid) {
                    used.push(hcid.clone());
                    used.sort_unstable();
                }
            }
            for prim in &dos {
                if !execute_effect(prim, state, victim_owner, hslot) {
                    return Err(format!("replace do 再現不能 ({hcid})"));
                }
            }
            return Ok(true); // 置換発動 = 本来の KO/離脱をキャンセル
        }
    }
    Ok(false)
}

/// victim は既に trash (source-gone) なので src=Slot::Detached (= Python の self_inplay=None、
/// effects.py:256-274 が on_ko で None を許容)。 target "self" は 0 対象 = no-op に解決される。
/// chara_ko_taken_this_turn++ は battle_ko_character 側で実施済 (Python は trigger_on_ko で全 KO 分加算、 同義)。
/// ⚠ 以前は placeholder=Leader だったため self/target 系が自リーダーに誤解決する危険があり narrow
///   allow-list で丸ごと bail していたが、 Detached 化で不要になった (2026-07-31)。 再現できない prim は
///   execute_effect が false を返して bail する。 cost / 未知条件 / draw cascade は従来通り Err。
///   replace_ko/replace_leave は呼出側 (do_battle_ko) で先に bail。
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
        // effects.py:_execute_event 順: 条件 → once → cost → do。
        match eval_effect_conditions(eff, state, owner_idx, None) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("on_ko 条件 unknown".into()),
        }
        if eff.get("once_per_turn").is_some() {
            return Err("on_ko once_per_turn 未対応 (canonical 未化)".into());
        }
        // cost: try_pay_counter_cost が扱う型 (pay_don/discard_hand/rest_self_don/life 系/flip 等) のみ対応
        // (source-gone=Leader placeholder で player-level 安全)。 未対応型は try_pay_counter_cost が Err。
        if let Some(cost) = eff.get("cost") {
            if !cost_is_empty(cost) {
                match try_pay_counter_cost(state, owner_idx, Slot::Detached, cost)? {
                    true => {}
                    false => continue, // 支払い不能 → 効果 skip
                }
            }
        }
        let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
        for prim in dos {
            let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("");
            if k == "draw" && me_board_has_when(state, owner_idx, "on_self_draw_non_draw_phase") {
                return Err("on_ko draw cascade 未対応".into());
            }
        }
        // play_self_from_trash 用に victim の card_id を transient set (Python _execute_event=source)。
        let prev_src = state.current_source_card_id.clone();
        state.current_source_card_id = Some(victim_cid.to_string());
        for prim in dos {
            if !execute_effect(prim, state, owner_idx, Slot::Detached) {
                state.current_source_card_id = prev_src.clone();
                return Err(format!("on_ko primitive 再現不能: {}", prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("?")));
            }
        }
        state.current_source_card_id = prev_src.clone(); // transient を復元 (action 境界で None)
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
    // play_self が発動元カードを特定できるよう source cid を立てる (effects.py:297)。 action 境界では
    // 常に None なので Ok 直前で戻す (Err 時は apply_action が state 破棄で無害)。
    state.current_source_card_id = Some(card_id.to_string());
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
            // ⚠ 以前は placeholder=Leader で self/target 系が自リーダーに誤解決する危険があったため
            //   narrow allow-list を敷いていたが、 src=Slot::Detached 化 (= Python の self_inplay=None と
            //   同義、 "self" は 0 対象) で不要になった (2026-07-31)。 再現不能な prim は execute_effect が
            //   false を返して bail する。 cascade 系の個別 guard だけ残す。
            if k == "draw" && me_board_has_when(state, defender_idx, "on_self_draw_non_draw_phase") {
                return Err("life trigger draw cascade 未対応".into());
            }
            // (rest の on_self_rested cascade は rest_char_with_cascade が発火する = 外側 guard 不要。
            //  cascade が再現不能なら execute_effect が false を返して bail する。 2026-07-31)
        }
        for prim in dos {
            let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("");
            if k == "to_hand_self_trigger" {
                kept_in_hand = true; // このカードを手札に加える (trash でなく hand へ)
                continue;
            }
            if !execute_effect(prim, state, defender_idx, Slot::Detached) {
                return Err(format!("life trigger primitive 再現不能: {}", prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("?")));
            }
        }
    }
    state.current_source_card_id = None; // action 境界では None に戻す
    Ok(kept_in_hand)
}

/// card の trigger 効果の do に play_self が (optional_cost_then/conditional/choice ネスト含め) 含まれるか
/// (game.py:2098 _contains_play_self)。 含む trigger は life-hit 側で taken を trash に pre-place する必要がある。
pub fn trigger_contains_play_self(card_id: &str) -> bool {
    fn scan(steps: &Value) -> bool {
        let Some(arr) = steps.as_array() else { return false };
        for step in arr {
            let Some(obj) = step.as_object() else { continue };
            if obj.get("play_self").map_or(false, json_truthy) {
                return true;
            }
            for val in obj.values() {
                if let Some(vo) = val.as_object() {
                    for sub in ["effect", "do", "then"] {
                        if let Some(s) = vo.get(sub) {
                            if scan(s) {
                                return true;
                            }
                        }
                    }
                } else if val.is_array() && scan(val) {
                    return true;
                }
            }
        }
        false
    }
    let Some(ov) = overlay() else { return false };
    let Some(effs) = ov.get(card_id) else { return false };
    effs.iter().any(|eff| {
        eff.get("when").and_then(|v| v.as_str()) == Some("trigger")
            && eff.get("do").map_or(false, scan)
    })
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
                | "discard_hand" | "discard_hand_with_filter"
        ) {
            return Err(format!("counter cost 未対応: {k}"));
        }
    }
    let gi = |k: &str| obj.get(k).and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    let pay_don = gi("pay_don");
    let rest_don = gi("rest_self_don");
    let discard_n = gi("discard_hand");
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
        if discard_n > 0 && (me.hand.len() as i32) < discard_n {
            return Ok(false);
        }
        if let Some(dwf) = obj.get("discard_hand_with_filter") {
            if dwf.is_object() {
                let (filt, cnt) = filter_and_count(dwf);
                if me.hand.iter().filter(|c| matches_filter(c, Some(&filt))).count() < cnt {
                    return Ok(false);
                }
            }
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
    // --- pay。 Python _pay_counter_cost 順: discard_hand→pay_don→rest_don→…。 discard は先頭。 ---
    // discard_hand: worst_hand_idx で actual 枚捨て + flag + on_self_hand_discarded cascade (発火/bail)。
    if discard_n > 0 {
        let actual = discard_n.min(state.players[me_idx].hand.len() as i32);
        for _ in 0..actual {
            let me = &mut state.players[me_idx];
            let Some(i) = worst_hand_idx(&me.hand, &me.known_hand_card_ids) else { break };
            let c = me.hand.remove(i);
            me.trash.push(c);
        }
        if actual > 0 {
            state.players[me_idx].hand_discarded_by_effect_this_turn = true;
            if fire_field_when(state, me_idx, "on_self_hand_discarded").is_err() {
                return Err("counter cost discard cascade 未対応".into());
            }
        }
    }
    // --- pay (Python _pay_counter_cost の順: pay_don→rest_don→rest_self→life→trash_to_deck→flip) ---
    if pay_don > 0 && !pay_don_field(state, me_idx, pay_don) {
        return Err("pay_don 支払い不能".into());
    }
    // pay_don_field が last_returned_don_count を set 済 → on_self_don_returned_to_deck cascade。
    // ⚠ Python は resolving=True 中 (counter event 解決内) なので deferred。 Rust は即時発火。
    // 順序非依存なら digest 一致 (差分検証が判定)。 未対応 prim は fire_field_when が Err → bail。
    if pay_don > 0 && me_board_has_when(state, me_idx, "on_self_don_returned_to_deck")
        && fire_field_when(state, me_idx, "on_self_don_returned_to_deck").is_err()
    {
        return Err("counter cost pay_don cascade 未対応".into());
    }
    if rest_don > 0 {
        let me = &mut state.players[me_idx];
        let a = rest_don.min(me.don_active);
        me.don_active -= a;
        me.don_rested += a;
    }
    // discard_hand_with_filter: 先頭 cnt 個の matching (hand 順) を降順 pop → flag + cascade (effects.py:867)。
    // Python 順は rest_don 後・rest_self 前。 OP15-057 (EVENT/STAGE 1 枚)。
    if let Some(dwf) = obj.get("discard_hand_with_filter").cloned() {
        if dwf.is_object() {
            let (filt, cnt) = filter_and_count(&dwf);
            let mut matching: Vec<usize> = state.players[me_idx]
                .hand
                .iter()
                .enumerate()
                .filter(|(_, c)| matches_filter(c, Some(&filt)))
                .map(|(i, _)| i)
                .take(cnt)
                .collect();
            matching.sort_unstable_by(|a, b| b.cmp(a)); // 降順 pop
            let n_disc = matching.len();
            for i in matching {
                let c = state.players[me_idx].hand.remove(i);
                state.players[me_idx].trash.push(c);
            }
            if n_disc > 0 {
                state.players[me_idx].hand_discarded_by_effect_this_turn = true;
                if fire_field_when(state, me_idx, "on_self_hand_discarded").is_err() {
                    return Err("counter cost discard_filter cascade 未対応".into());
                }
            }
        }
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
        for (idx, eff) in effs.iter().enumerate() {
            if eff.get("when").and_then(|v| v.as_str()) != Some(when) {
                continue;
            }
            // once_per_turn: cost.once_per_turn or top-level。 mirror 対象 when は event_once_used で追跡、
            // それ以外 (end_of_turn 等 別トラッカー) は従来通り bail。
            let once_opt = eff
                .get("once_per_turn")
                .or_else(|| eff.get("cost").and_then(|c| c.get("once_per_turn")));
            if let Some(o) = once_opt {
                if let Some(shared) = o.as_str() {
                    // 明示キー (共有 namespace)。 effects.py:1009 の key 形式 `key:<opt>` を
                    // once_shared_used (canonical mirror) で追跡する。
                    let key = format!("key:{shared}");
                    if state.players[owner_idx].once_shared_used.contains(&key) {
                        continue; // ターン既発動 (別 when と共有のことがある)
                    }
                } else {
                    if !field_when_once_mirrored(when) {
                        return Err(format!("{when} once_per_turn 未対応")); // 別トラッカー = 追跡不可
                    }
                    if o.as_bool() == Some(true) {
                        let key = format!("{when}:{idx}");
                        if get_ip(&state.players[owner_idx], slot).event_once_used.contains(&key) {
                            continue; // ターン既発動
                        }
                    }
                }
            }
            // 実 cost (once_per_turn 以外) が有れば bail (field-when real cost 未対応)。
            if let Some(cost) = eff.get("cost") {
                let has_real = cost.as_object().map_or(!cost_is_empty(cost), |o| o.keys().any(|k| k != "once_per_turn"));
                if has_real {
                    return Err(format!("{when} cost 未対応"));
                }
            }
            match eval_effect_conditions(eff, state, owner_idx, Some(slot)) {
                Some(true) => {}
                Some(false) => continue,
                None => return Err(format!("{when} 条件 unknown")),
            }
            // once mark (Python _check_and_set は fire 前に set、 mirror も同時)。
            if once_opt.and_then(|o| o.as_bool()) == Some(true) {
                get_ip_mut(&mut state.players[owner_idx], slot).mark_event_once(when, idx as i64);
            }
            if let Some(shared) = once_opt.and_then(|o| o.as_str()) {
                let key = format!("key:{shared}");
                let used = &mut state.players[owner_idx].once_shared_used;
                if !used.contains(&key) {
                    used.push(key);
                    used.sort(); // Python 側も sort して保持 (digest 一致)
                }
            }
            let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
            fire_gated_do(state, owner_idx, slot, dos)?;
        }
    }
    Ok(())
}

/// field-when once の canonical mirror (event_once_used) 対象 when か。 Python effects.py:_FIELD_WHEN_ONCE_MIRROR と一致。
fn field_when_once_mirrored(when: &str) -> bool {
    matches!(
        when,
        "on_self_life_to_hand" | "on_self_life_to_trash" | "on_self_life_taken" | "on_opp_life_taken"
            | "on_self_chara_played" | "on_opp_chara_played" | "on_self_chara_ko" | "on_opp_chara_ko"
            | "on_self_hand_discarded" | "on_self_don_returned_to_deck" | "on_self_event_played"
            | "on_opp_event_or_trigger_fired" | "on_self_chara_leave_by_self_effect" | "on_self_rested"
            | "on_self_trigger_fired"
    )
}

/// 【相手のアタック時】(opp_attack / opp_attack_on_leader / opp_attack_on_chara) を発火 (effects.py:
/// _enqueue_opp_attack_with_cost、 self-play AI 経路)。 全て bit 忠実に再現できたら Ok、 できなければ Err。
///  - costless: 条件成立なら発火 (allow-list、 未対応 target/prim は Err)
///  - cost 持ち: ai_should_fire ヒューリスティックで判定 → skip(=何もしない)なら一致、 fire なら Err
///    (cost 支払い + cascade + 防御 target 解決が要る = 未対応で bail)
///  走査順 = leader → characters → stages (_enqueue_opp_attack_with_cost)。
/// trash_self counter cost の do が source-gone (src=trash 済) で発火して安全か。
/// src (=self) を参照する prim (target "self"/"self_inplay") は Python(None)と Rust(present)でズレるので unsafe。
/// player-level (draw/untap_don 等) や self_leader 等の非 src target は safe。
fn trash_self_do_safe(prim: &Value) -> bool {
    // src (=trash 済 self) を参照する prim (target "self"/"self_inplay") は source-gone 発火で
    // placeholder=leader に誤解決 = unsafe。 player-level (draw/untap_don) や self_leader は safe。
    let Some(o) = prim.as_object() else { return true };
    for (_, v) in o {
        if matches!(v.get("target").and_then(|t| t.as_str()), Some("self") | Some("self_inplay")) {
            return false;
        }
        if matches!(v.as_str(), Some("self") | Some("self_inplay")) {
            return false;
        }
    }
    true
}

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
    // trash_self cost 効果: (source char index, do 配列)。 Python 順 = pay(=trash 全部)→fire(全部 source-gone)。
    let mut trash_self_fires: Vec<(usize, Vec<Value>)> = vec![];
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
            // trash_self cost の deferred 化 (OP11-049/ST22-002/ST24-002): cost が trash_self(+once)のみ・
            // do が source-gone-safe (非 src 参照)・on_self_chara_leave_by_self_effect cascade 無し なら、
            // 通常通り fire を先に回し (source present、 do prim は非 src 参照で source-gone と同値)、 fire 完了
            // 後に source を trash する (Python は pay=trash→fire=source-gone の順だが、 do/cascade 非依存で
            // 最終 digest 一致)。 それ以外は従来通り try_pay が Err bail。
            if let Slot::Char(ci) = slot {
                if let Some(o) = cost.as_object() {
                    if o.get("trash_self").map_or(false, json_truthy)
                        && o.keys().all(|k| k == "trash_self" || k == "once_per_turn")
                        && eff.get("do").and_then(|v| v.as_array())
                            .map_or(true, |arr| arr.iter().all(trash_self_do_safe))
                        // on_self_chara_leave_by_self_effect cascade は source-gone fire で再現不能なので guard。
                        && !me_board_has_when(state, defender_idx, "on_self_chara_leave_by_self_effect")
                        && !me_board_has_when(state, 1 - defender_idx, "on_self_chara_leave_by_self_effect")
                    {
                        if once.and_then(|q| q.as_bool()) == Some(true) {
                            get_ip_mut(&mut state.players[defender_idx], slot).mark_attack_once(idx as i64);
                        }
                        let dos = eff.get("do").and_then(|v| v.as_array()).cloned().unwrap_or_default();
                        trash_self_fires.push((ci, dos));
                        continue;
                    }
                }
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
    // trash_self cost: ⚠ Python は cost 支払い(=trash)で source が場を離れる → event resolve 時に
    //   self_inplay=None (source-gone) で opp_attack は _execute_event が **早期 return = do を発火しない**
    //   (effects.py:270、 opp_attack は on_ko/main/counter/trigger の allow-list 外)。 = ST24-002 キッド&キラー
    //   の untap_don 等は「自身 trash のみ・効果不発」が公式挙動 (self-trash opp_attack の engine 帰結)。
    //   → Rust も source を trash するだけで do は fire しない。 index 降順 remove で shift 回避、 付与ドン→レスト、
    //   KO でなく leave=chara_ko 非加算。 leave cascade は collect 時の guard で無し。
    if !trash_self_fires.is_empty() {
        trash_self_fires.sort_by_key(|(ci, _)| *ci);
        for (ci, _) in trash_self_fires.iter().rev() {
            if *ci < state.players[defender_idx].characters.len() {
                let removed = state.players[defender_idx].characters.remove(*ci);
                let don = removed.attached_dons;
                state.players[defender_idx].trash.push(removed.card);
                state.players[defender_idx].don_rested += don;
            }
        }
    }
    Ok(())
}

/// メインイベントの効果を実行 (effects.py:trigger_main_event)。 event は既にトラッシュ = source-gone
/// (Python も source_iid=None、 effects.py:12923) なので src=Slot::Detached。 target "self" は 0 対象。
pub fn execute_main_event(state: &mut GameState, me_idx: usize, card_id: &str) -> Result<(), String> {
    let opp = 1 - me_idx;
    // trigger_main_event 順 (turn-first FIFO drain): ① event main 効果 → ② on_self_event_played(me)→
    //   ③ opp_event_or_trigger_fired(opp)。 各段 fire は fidelity 保証 (未対応 cost/once/prim は Err bail)。
    execute_card_effects(state, me_idx, card_id, "main", Slot::Detached)?;
    fire_field_when(state, me_idx, "on_self_event_played")?;
    fire_field_when(state, opp, "opp_event_or_trigger_fired")?;
    Ok(())
}

/// 【カウンター】イベントの発動 (game.py:2191 _fire_counter_events + trigger_counter_event)。
/// defender = アタックを受けている側 (= イベントの「自分」)。 各 idx は desc で処理 (idx 不変)。
/// cost (active don ≥ card.cost) を払えなければ skip (trash もしない)。 payable なら active→rested で払い
/// trash → counter 効果発火 (source-gone = Leader placeholder、 fidelity gate で未対応は Err)。
/// ⚠ event-played cascade (on_self_event_played / opp_event_or_trigger_fired) は防御ターンの turn-first 順が
///   delicate → 該当カードが場にあれば bail。 無ければ no-op で安全。
pub fn fire_counter_events(
    state: &mut GameState,
    defender_idx: usize,
    attacker_idx: usize,
    idxs: &[i64],
) -> Result<(), String> {
    if idxs.is_empty() {
        return Ok(());
    }
    let mut sorted: Vec<usize> = idxs.iter().map(|&i| i as usize).collect();
    sorted.sort_unstable();
    sorted.dedup();
    sorted.reverse(); // desc
    for i in sorted {
        if i >= state.players[defender_idx].hand.len() {
            continue;
        }
        if state.players[defender_idx].hand[i].category != crate::state::Category::Event {
            continue;
        }
        let cost = state.players[defender_idx].hand[i].cost;
        if state.players[defender_idx].don_active < cost {
            continue; // 支払い不能 = 発動できない (trash もしない)
        }
        let card = state.players[defender_idx].hand.remove(i);
        let cid = card.card_id.clone();
        state.players[defender_idx].don_rested += cost;
        state.players[defender_idx].don_active -= cost;
        state.players[defender_idx].trash.push(card);
        // trigger_counter_event 順 (effects.py:12875): counter 効果 → opp_event_or_trigger_fired(attacker)
        //   → on_self_event_played(defender)。 各 counter event 毎に発火 (per-event、 Python enqueue+drain 準拠)。
        execute_card_effects(state, defender_idx, &cid, "counter", Slot::Detached)?;
        fire_field_when(state, attacker_idx, "opp_event_or_trigger_fired")?;
        fire_field_when(state, defender_idx, "on_self_event_played")?;
    }
    Ok(())
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
    // trash_self でこの起動源が場から除去されたか (= act_used マークを skip する為)。
    let mut source_gone = false;
    // cost 支払い。 未対応 cost 種別 or cascade を起こす cost は bail (黙って間違えない)。
    if let Some(c) = &cost {
        if let Some(o) = c.as_object() {
            for k in o.keys() {
                if !matches!(k.as_str(), "rest_self" | "pay_don" | "rest_self_don" | "once_per_turn" | "rest_own_card" | "ko_self_with_filter" | "trash_self" | "trash_to_deck") {
                    return Err(format!("activate_main cost 未対応: {k} ({card_id})"));
                }
            }
        }
        // pay_don は on_self_don_returned_to_deck cascade を起こす → 該当時 bail
        let pay_don = c.get("pay_don").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
        if pay_don > 0 && me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
            return Err("activate_main pay_don cascade 未対応".into());
        }
        // trash_self: 起動源自身を場からトラッシュへ (= 自KO 同等、 付与ドンはレストへ)。 cascade 無し
        // (effects.py:13359、 on_ko/on_self_chara_leave は発火しない = 単純除去)。 → src が場から消える
        // ので後続の act_used マーク・自陣 do 参照は無効化 (source_gone)。
        if c.get("trash_self").and_then(|v| v.as_bool()).unwrap_or(false) {
            let me = &mut state.players[me_idx];
            let removed = match src {
                Slot::Char(i) if i < me.characters.len() => me.characters.remove(i),
                Slot::Stage(i) if i < me.stages.len() => me.stages.remove(i),
                _ => return Err("trash_self source 不明".into()),
            };
            let don = removed.attached_dons;
            me.trash.push(removed.card);
            me.don_rested += don;
            source_gone = true;
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
        // trash_to_deck N: トラッシュ上 (front) N 枚をデッキ下 (back) へ (effects.py:13395、 OP05-082)。 cascade 無し。
        let ttd = c.get("trash_to_deck").and_then(|v| v.as_i64()).unwrap_or(0) as usize;
        if ttd > 0 {
            let me = &mut state.players[me_idx];
            let moved = ttd.min(me.trash.len());
            for _ in 0..moved {
                let card = me.trash.remove(0);
                me.deck.push(card);
            }
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
        // ko_self_with_filter (effects.py:13560): filter 一致の自キャラ 先頭 1 枚を自KO。 AI は候補[0]。
        //   → trash + 付与ドン→レスト、 chara_ko_taken++、 on_ko (source-gone) + on_self_chara_ko 発火
        //   (self-ko なので on_opp_chara_ko は無し)。 未対応 on_ko/cascade は fire_on_ko/fire_field_when が bail。
        if let Some(kf) = c.get("ko_self_with_filter") {
            let me = &mut state.players[me_idx];
            if let Some(i) = me.characters.iter().position(|ch| matches_filter(&ch.card, Some(kf))) {
                let removed = me.characters.remove(i);
                let vcid = removed.card.card_id.clone();
                let don = removed.attached_dons;
                me.trash.push(removed.card);
                me.don_rested += don;
                me.chara_ko_taken_this_turn += 1; // trigger_on_ko 相当 (全 KO で加算)
                // last_chara_ko_victim_card set (victim_* 条件用)、 cascade 完了後 None (Python 準拠)。
                state.last_chara_ko_victim_card = None; // 効果 cascade は nested=deferred で victim None
                let mut err: Option<String> = None;
                if let Err(e) = fire_on_ko(state, me_idx, &vcid) {
                    err = Some(e);
                }
                if err.is_none() {
                    if let Err(e) = fire_field_when(state, me_idx, "on_self_chara_ko") {
                        err = Some(e);
                    }
                }
                state.last_chara_ko_victim_card = None;
                if let Some(e) = err {
                    return Err(e);
                }
            }
        }
    }
    // once_per_turn フラグ (effects.py:13743、 default True で発動済マーク)。 ⚠ source_gone (trash_self)
    // 時は起動源が場から消えている → Python は off-field object に setattr する (digest 不変=trash は
    // CardDef のみ) ので Rust は skip (stale index を触らない)。
    let once = cost.as_ref().and_then(|c| c.get("once_per_turn")).and_then(|v| v.as_bool()).unwrap_or(true);
    if once && !source_gone {
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
            ip.static_cannot_be_rested = false;
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
            && !l.static_cannot_be_rested
        {
            attackers.push(("leader".into(), 0));
        }
        for (j, ch) in me.characters.iter().enumerate() {
            if ch.rested
                || ch.cannot_attack_until_turn_end
                || ch.cannot_attack_static
                || ch.cannot_attack_through_opp_turn
                || ch.cannot_be_rested_buff
                || ch.static_cannot_be_rested
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
                    Slot::Leader | Slot::Detached => 0, // legal_actions は場の slot のみ列挙 (Detached 不到達)
                    Slot::Char(j) | Slot::Stage(j) => j,
                };
                out.push(json!({"t": "ActivateMain", "source_kind": kind, "source_idx": sidx, "effect_index": idx}));
            }
        }
    }
    out
}
