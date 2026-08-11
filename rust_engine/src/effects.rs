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

pub fn overlay() -> Option<&'static HashMap<String, Vec<Value>>> {
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
        // ⚠ 条件だけでなく **発動コストの payability** も見る (公式 10-1-5 + 4-10、 2026-08-11)。
        //   払えないなら発動できず カードは手札に加わる。 Python `_trigger_effect_activatable` と同則。
        if let Some(cost) = eff.get("cost").and_then(|v| v.as_object()) {
            let real: Vec<(&String, &Value)> =
                cost.iter().filter(|(k, _)| k.as_str() != "once_per_turn").collect();
            if !real.is_empty() {
                let me = &state.players[defender_idx];
                let mut payable = true;
                for (k, v) in real {
                    let n = v.as_i64().unwrap_or(0) as i32;
                    match k.as_str() {
                        "pay_don" => {
                            if pay_don_capacity(me) < n {
                                payable = false;
                            }
                        }
                        "rest_self_don" => {
                            if me.don_active < n {
                                payable = false;
                            }
                        }
                        "discard_hand" => {
                            if (me.hand.len() as i32) < n {
                                payable = false;
                            }
                        }
                        // 未知の cost キーは判定不能 → bail (黙って乖離しない)
                        _ => return None,
                    }
                }
                if !payable {
                    continue;
                }
            }
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

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
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
/// ⚠ 範囲外 (= 効果解決の途中で場が縮み slot が stale になった) も None を返す。 panic は
///    「黙って間違えない」不変条件の外 (プロセスが死んで self-play が止まる) なので許容しない。
fn src_ip(p: &Player, s: Slot) -> Option<&InPlay> {
    match s {
        Slot::Detached => None,
        Slot::Leader => Some(&p.leader),
        Slot::Char(i) => p.characters.get(i),
        Slot::Stage(i) => p.stages.get(i),
    }
}
fn src_ip_mut(p: &mut Player, s: Slot) -> Option<&mut InPlay> {
    match s {
        Slot::Detached => None,
        Slot::Leader => Some(&mut p.leader),
        Slot::Char(i) => p.characters.get_mut(i),
        Slot::Stage(i) => p.stages.get_mut(i),
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
            // === 全カード掃引で「条件 unknown」上位に出た述語を Python から一括移植 (2026-07-31) ===
            // 自分の レストドン >= N (effects.py:1336)
            "self_don_rested_ge" => me.don_rested as i64 >= v.as_i64().unwrap_or(0),
            // --- 掃引 2 巡目で上位に出た述語 (2026-07-31) ---
            "self_chara_count_le" => (me.characters.len() as i64) <= v.as_i64().unwrap_or(0),
            "self_don_count_eq" => (me.don_active + me.don_rested) as i64 == v.as_i64().unwrap_or(0),
            "life_zero_either" => {
                v.as_bool().unwrap_or(true) == (me.life.is_empty() || opp.life.is_empty())
            }
            "opp_life_lost_this_turn" => v.as_bool().unwrap_or(true) == opp.life_lost_this_turn,
            // 「自分の **特徴X を持つ** キャラが場を離れた時」 (OP16-041 バギー 等)。
            // このイベントで場を離れた victim の **いずれか** が特徴を持てば成立。
            "leave_victim_feature_in" => {
                let feats: Vec<String> = match v {
                    Value::Array(a) => a.iter().filter_map(|x| x.as_str().map(String::from)).collect(),
                    Value::String(x) => vec![x.clone()],
                    _ => vec![],
                };
                state
                    .rust_leave_by_self_victims
                    .iter()
                    .any(|c| feats.iter().any(|f| c.features.iter().any(|cf| cf == f)))
            }
            // 公式 (cardqa_op_12 / OP12-020 ゾロ): 「このターン中、 このリーダーが **相手のキャラと**
            // バトルしている場合」。 実際にバトルした相手で判定 (ブロッカー/対象変更でリーダーと
            // バトルしたなら不成立)。
            "self_leader_battled_opp_chara_this_turn" => {
                v.as_bool().unwrap_or(true) == me.leader_battled_opp_chara_this_turn
            }
            "self_hand_discarded_by_effect_this_turn" => {
                v.as_bool().unwrap_or(true) == me.hand_discarded_by_effect_this_turn
            }
            // 自場の filter 一致キャラの「カード名の異なる」数 >= N (OP16-038)
            "self_distinct_name_count_filtered_ge" => {
                let filt = v.get("filter");
                let need = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1);
                let names: std::collections::BTreeSet<&str> = me
                    .characters
                    .iter()
                    .filter(|c| matches_filter_ip(&c, filt))
                    .map(|c| c.card.name.as_str())
                    .collect();
                names.len() as i64 >= need
            }
            // 手札破棄を起こした効果の発動元カードの特徴に v を含むか (effects.py:actor_source_feature_contains、
            // OP12-040 クザン)。 Python は last_discard_source_inplay、 Rust は fire_hand_discarded が
            // 載せる transient を見る。 未設定 = 発動元不明 → False (Python も src None で False)。
            "actor_source_feature_contains" => {
                let needle = v.as_str().unwrap_or("");
                match &state.current_discard_source_features {
                    Some(fs) => fs.join("/").contains(needle),
                    None => false,
                }
            }
            // --- 掃引 5 巡目の述語 (2026-08-01) ---
            "self_inplay_summoning_sickness" => {
                src.and_then(|sl| src_ip(me, sl)).map_or(false, |ip| ip.summoning_sickness)
            }
            // 自キャラのうち現在パワー N 以上が count 枚【以下】 (effects.py:self_chara_power_ge_count_le)
            "self_chara_power_ge_count_le" => {
                let pg = v.get("power").or_else(|| v.get("power_ge")).and_then(|x| x.as_i64()).unwrap_or(5000);
                let cap = v.get("count").and_then(|x| x.as_i64()).unwrap_or(2);
                (me.characters.iter().filter(|c| c.power() as i64 >= pg).count() as i64) <= cap
            }
            "self_stage_named" => {
                let name = v.as_str().unwrap_or("");
                me.stages.iter().any(|st| name_matches(&st.card, name))
            }
            "self_chara_count_lt_opp" => me.characters.len() < opp.characters.len(),
            "self_hand_eq" => (me.hand.len() as i64) == v.as_i64().unwrap_or(0),
            // --- 掃引 4 巡目の述語 (2026-08-01) ---
            "self_leader_attached_don_ge" => me.leader.attached_dons as i64 >= v.as_i64().unwrap_or(0),
            "leader_power_ge" => me.leader.power() as i64 >= v.as_i64().unwrap_or(0),
            "total_life_ge" => (me.life.len() + opp.life.len()) as i64 >= v.as_i64().unwrap_or(0),
            // 相手の場に 現在コスト N 以下 / 現在パワー N 以上 のキャラが居るか
            "exists_opp_chara_cost_le" => {
                let n = v.as_i64().unwrap_or(0);
                opp.characters.iter().any(|c| c.base_cost() as i64 <= n)
            }
            "exists_opp_chara_power_ge" => {
                let n = v.as_i64().unwrap_or(0);
                opp.characters.iter().any(|c| c.power() as i64 >= n)
            }
            // 自分の場のドン (コストエリア) が 0 か 8 以上 (ST10-002 ルフィ)
            "self_field_don_zero_or_ge_8" => {
                let fd = me.don_active + me.don_rested;
                fd == 0 || fd >= 8
            }
            // 自場 (リーダー+キャラ) に指定名が全て居るか。 power_eq 指定時は元々パワー一致に限定。
            // ⚠ overlay の names は未正規化なので normalize_card_name を通す (全角Ｄ→D)。
            "self_field_named_all_with_power" => {
                let names: Vec<String> = v
                    .get("names")
                    .and_then(|x| x.as_array())
                    .map(|a| a.iter().filter_map(|x| x.as_str()).map(norm_card_name).collect())
                    .unwrap_or_default();
                // 公式テキストが 「元々のパワー」 の場合は `truly_original_power_eq` key
                // (= 表記と spec key の整合、 overlay 命名規約)。 どちらも印刷パワー比較。
                let power_eq = v
                    .get("power_eq")
                    .or_else(|| v.get("truly_original_power_eq"))
                    .and_then(|x| x.as_i64());
                names.iter().all(|nm| {
                    std::iter::once(&me.leader).chain(me.characters.iter()).any(|c| {
                        norm_card_name(&c.card.name) == *nm
                            && power_eq.map_or(true, |p| c.card.power as i64 == p)
                    })
                })
            }
            // アタックしてきた相手キャラの属性 (effects.py:opp_attacker_attribute、 OP11-088 シュウ)。
            // 「アタックしてきた相手キャラの属性が v か」 (effects.py:1371、 OP11-088 シュウ)。
            // Python は current_attacker_iid → InPlay の attribute。 Rust は宣言時に立てた
            // current_attacker_attribute (transient) を見る。 文脈外 (None) は条件不成立。
            "opp_attacker_attribute" => match &state.current_attacker_attribute {
                Some(attr) => attr.contains(v.as_str().unwrap_or("")),
                None => false,
            },
            // --- 掃引 3 巡目の述語 (2026-07-31) ---
            "self_trash_has_named_all" => {
                let names: Vec<&str> = v.as_array().map_or_else(
                    || v.as_str().into_iter().collect(),
                    |a| a.iter().filter_map(|x| x.as_str()).collect(),
                );
                names.iter().all(|n| me.trash.iter().any(|c| c.name == *n))
            }
            // 「自分の他の <name> が存在しない」 = 自身を除いた同名キャラ 0。 src 不明は False。
            "self_chara_unique_name" => {
                let name = v.as_str().unwrap_or("");
                match src {
                    Some(Slot::Char(si)) => !me
                        .characters
                        .iter()
                        .enumerate()
                        .any(|(i, c)| i != si && name_matches(&c.card, name)),
                    Some(_) => !me.characters.iter().any(|c| name_matches(&c.card, name)),
                    None => false,
                }
            }
            "either_player_don_total_eq_10" => {
                state.players.iter().any(|p| p.don_active + p.don_rested == 10)
            }
            "self_chara_power_ge" => {
                let n = v.as_i64().unwrap_or(0);
                me.characters.iter().any(|c| c.power() as i64 >= n)
            }
            // 手札に「v を含む特徴」のカードがあるか (部分一致)
            "self_hand_has_feature" => {
                let f = v.as_str().unwrap_or("");
                me.hand.iter().any(|c| c.features.iter().any(|x| x.contains(f)))
            }
            "self_chara_filtered_count_le" => {
                let filt = v.get("filter");
                let need = v.get("count").and_then(|x| x.as_i64()).unwrap_or(0);
                (me.characters.iter().filter(|c| matches_filter_ip(&c, filt)).count() as i64) <= need
            }
            "self_inplay_attached_dons_ge" => {
                let n = v.as_i64().unwrap_or(0);
                src.and_then(|sl| src_ip(me, sl)).map_or(false, |ip| ip.attached_dons as i64 >= n)
            }
            "has_face_up_life" => {
                let present = me.face_up_life_count.min(me.life.len() as i32) > 0;
                v.as_bool().unwrap_or(true) == present
            }
            "self_leader_power_le" => (me.leader.power() as i64) <= v.as_i64().unwrap_or(0),
            // 自キャラ (リーダー除く) の現在コスト合計 >= N
            "self_chara_cost_sum_ge" => {
                let total: i32 = me.characters.iter().map(|c| c.base_cost()).sum();
                total as i64 >= v.as_i64().unwrap_or(0)
            }
            // ⚠ **キャラ0枚では成立しない** (公式 cardqa_op_16 / OP16-022: 「自分のキャラが0枚の時、
            //   この【起動メイン】効果でドン‼をアクティブにできますか？」 → 「いいえ」)。
            //   2026-08-11 に Python と同時に是正 (従来は vacuous True)。
            "self_chara_only_feature" => {
                let f = v.as_str().unwrap_or("");
                !me.characters.is_empty()
                    && me.characters.iter().all(|c| c.card.features.iter().any(|x| x == f))
            }
            // 自分の場のドン (コストエリア active+rested) が 0 か 3 以上 (effects.py:self_field_don_zero_or_ge_3)
            "self_field_don_zero_or_ge_3" => {
                let fd = me.don_active + me.don_rested;
                fd == 0 || fd >= 3
            }
            // 自キャラ数 - 相手キャラ数 が N 以下 (effects.py:1659、 OP10-098)。
            "chara_diff_le" => {
                (me.characters.len() as i64 - opp.characters.len() as i64) <= v.as_i64().unwrap_or(0)
            }
            // このターン中に相手のキャラが KO されたか (effects.py:1774、 OP16-100)。
            "opp_chara_ko_this_turn" => {
                (opp.chara_ko_taken_this_turn > 0) == v.as_bool().unwrap_or(true)
            }
            // 相手の場のキャラ (leader 含まず) が N 枚以上 (effects.py:1196、 OP07-073)。
            "opp_field_count_ge" => opp.characters.len() as i64 >= v.as_i64().unwrap_or(0),
            // 直前にバトルした相手キャラがまだ場に居るか (effects.py:1147、 ST08-013)。
            "opp_just_battled_present" => {
                let present = match state.last_battled_opp {
                    Some((pi, ci)) => pi == 1 - me_idx && ci < opp.characters.len(),
                    None => false,
                };
                v.as_bool().unwrap_or(true) == present
            }
            // 直前にバトルした相手キャラのコストが N 以下か (effects.py:1154、 OP04-047)。
            "opp_just_battled_cost_le" => match state.last_battled_opp {
                Some((pi, ci)) if pi == 1 - me_idx && ci < opp.characters.len() => {
                    (opp.characters[ci].card.cost as i64) <= v.as_i64().unwrap_or(0)
                }
                _ => false,
            },
            // このキャラ自身の現在コスト (base_cost) が N 以上 (effects.py:1836、 OP16-084)。
            "self_inplay_cost_ge" => match src.and_then(|sl| src_ip(&state.players[me_idx], sl)) {
                Some(ip) => (ip.base_cost() as i64) >= v.as_i64().unwrap_or(0),
                None => false,
            },
            // どちらかの場にコスト N 以上のキャラが居るか (effects.py:1208、 leader 除く、 現コスト)。
            "exists_chara_cost_ge" => {
                let n = v.as_i64().unwrap_or(0) as i32;
                me.characters.iter().chain(opp.characters.iter()).any(|c| c.base_cost() >= n)
            }
            // 自分のコストエリアのドン (active+rested) が N 枚以上 (effects.py:1401)。
            "self_don_count_ge" => (me.don_active + me.don_rested) as i64 >= v.as_i64().unwrap_or(0),
            // 直近 KO が「相手の効果由来」か (effects.py:1452、 OP11-035/OP11-024)。
            "by_opp_effect" => v.as_bool().unwrap_or(true) == state.last_ko_by_opp_effect,
            // 直近 KO がバトル由来か (= 効果由来でない、 effects.py:1459)。
            "by_battle" => v.as_bool().unwrap_or(true) == !state.last_ko_by_opp_effect,
            // 「キャラの『name』がいる場合この効果は無効」 = 両陣営に該当名が居ないか
            // (effects.py:1149、 OP05-100 エネル)。
            "either_side_chara_named_absent" => {
                let name = if v.is_object() {
                    v.get("name").and_then(|x| x.as_str()).unwrap_or("").to_string()
                } else {
                    v.as_str().unwrap_or("").to_string()
                };
                !me.characters.iter().chain(opp.characters.iter()).any(|c| name_matches(&c.card, &name))
            }
            // 自分の場に カード名 v のキャラが いない (effects.py:1214、 OP08-005 / OP03-027)。
            "self_chara_named_absent" => {
                let name = v.as_str().unwrap_or("");
                !me.characters.iter().any(|c| name_matches(&c.card, name))
            }
            // リーダー名が文字列 v を含む (effects.py:1754、 OP16-015)。 表記揺れは norm_card_name で吸収。
            "leader_name_contains" => {
                norm_card_name(&me.leader.card.name).contains(&norm_card_name(v.as_str().unwrap_or("")))
            }
            // 自手札 - 相手手札 が N 以下 (effects.py:1309、 OP09-092)。
            "self_hand_diff_le" => {
                (me.hand.len() as i64 - opp.hand.len() as i64) <= v.as_i64().unwrap_or(0)
            }
            // 相手の元々パワー X 以上のキャラ (任意で leader 含む) が N 体以上 (effects.py:1410、 OP09-005)。
            "opp_inplay_truly_original_power_ge_count" => {
                let thr = v.get("power_ge").and_then(|x| x.as_i64()).unwrap_or(0) as i32;
                let need = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
                let incl = v.get("include_leader").and_then(|x| x.as_bool()).unwrap_or(false);
                let mut n = opp.characters.iter().filter(|ip| ip.card.power >= thr).count();
                if incl && opp.leader.card.power >= thr {
                    n += 1;
                }
                n >= need
            }
            // 相手の元々パワー 6000 以上の リーダー/キャラ が N 体以上
            "opp_inplay_truly_original_power_ge_6000_count_ge" => {
                let n = std::iter::once(&opp.leader)
                    .chain(opp.characters.iter())
                    .filter(|ip| ip.card.power >= 6000)
                    .count() as i64;
                n >= v.as_i64().unwrap_or(0)
            }
            // 相手キャラの filter 一致数が N 以下
            "opp_chara_filtered_count_le" => {
                let filt = v.get("filter");
                let limit = v.get("count").and_then(|x| x.as_i64()).unwrap_or(0);
                (opp.characters.iter().filter(|c| matches_filter_ip(&c, filt)).count() as i64) <= limit
            }
            // 発動元が召喚酔い中 (= このキャラが登場したターン)。 src 不明なら False (Python 準拠)。
            "self_summoning_sickness" => {
                v.as_bool().unwrap_or(true)
                    == src.and_then(|sl| src_ip(me, sl)).map_or(false, |ip| ip.summoning_sickness)
            }
            // どちらかの場に「現在コスト」N 以下のキャラが居るか (effects.py:exists_chara_cost_le)
            "exists_chara_cost_le" => {
                let n = v.as_i64().unwrap_or(0);
                me.characters.iter().chain(opp.characters.iter()).any(|c| c.base_cost() as i64 <= n)
            }
            // 発動元が場に居てアクティブ (effects.py:1330)。 source-gone は False (unknown ではない)。
            "self_not_rested" => src.and_then(|sl| src_ip(me, sl)).map_or(false, |ip| !ip.rested),
            // 直近に登場した自キャラが【トリガー】持ちか (effects.py:1486)
            "played_self_chara_has_trigger" => match &state.last_self_chara_played_card {
                Some(c) => v.as_bool().unwrap_or(true) == !c.trigger.is_empty(),
                None => false,
            },
            // 直近に登場した自キャラに overlay 効果が無いか (effects.py:1469)
            "played_self_chara_has_no_effect" => match &state.last_self_chara_played_card {
                Some(c) => {
                    let has = overlay().and_then(|m| m.get(&c.card_id)).map_or(false, |e| !e.is_empty());
                    v.as_bool().unwrap_or(true) == !has
                }
                None => false,
            },
            // 直近に登場した自キャラの特徴がリストのいずれかに一致 (effects.py:1500)
            "played_self_chara_feature_in" => match &state.last_self_chara_played_card {
                Some(c) => v.as_array().map_or_else(
                    || v.as_str().map_or(false, |x| c.features.iter().any(|f| f == x)),
                    |arr| arr.iter().any(|x| x.as_str().map_or(false, |sx| c.features.iter().any(|f| f == sx))),
                ),
                None => false,
            },
            // 直近に登場した **相手** キャラの元々コスト >= N (effects.py:1464)
            // 公式 (cardqa_op_12 / OP12-081): 「キャラの効果でキャラを登場させた時」 =
            // **場にあるキャラ** の効果のみ。【トリガー】効果による登場では発動しない。
            "played_chara_by_field_chara_effect" => {
                state.last_chara_played_by_field_chara == v.as_bool().unwrap_or(true)
            }
            "played_chara_truly_original_cost_ge" => match &state.last_opp_chara_played_card {
                Some(c) => c.cost as i64 >= v.as_i64().unwrap_or(0),
                None => false,
            },
            // 直近に登場した自キャラがトラッシュ由来か (effects.py:1496)
            "played_from_trash" => v.as_bool().unwrap_or(true) == state.last_self_chara_played_from_trash,
            // 元々パワー (= 印字値 card.power、 公式 4-9) N 以上の自キャラが居る/居ない
            "self_chara_truly_original_power_ge" => {
                let n = v.as_i64().unwrap_or(0);
                me.characters.iter().any(|c| c.card.power as i64 >= n)
            }
            "self_chara_no_truly_original_power_ge" => {
                let n = v.as_i64().unwrap_or(0);
                !me.characters.iter().any(|c| c.card.power as i64 >= n)
            }
            // 自キャラが全員 特徴 v を持つ。 ⚠ キャラ 0 枚は不成立 (公式 cardqa_op_13 /
            // OP13-097「場にキャラ0枚→KOできない」。 vacuously true にしない、 effects.py:1393)
            "self_all_chara_feature" => {
                let f = v.as_str().unwrap_or("");
                !me.characters.is_empty()
                    && me.characters.iter().all(|c| c.card.features.iter().any(|x| x == f))
            }
            // 自キャラが全員「v を含む特徴」を持つ (部分一致)。 ⚠ キャラ 0 枚は不成立 (同上、 effects.py:1398)
            "self_all_chara_feature_contains" | "self_chara_only_feature_contains" => {
                let f = v.as_str().unwrap_or("");
                !me.characters.is_empty()
                    && me.characters.iter().all(|c| c.card.features.iter().any(|x| x.contains(f)))
            }
            // 特徴 v を持つ自キャラが count 枚以上 (effects.py:1428)
            "self_chara_feature_count_ge" => {
                let f = v.get("feature").and_then(|x| x.as_str()).unwrap_or("");
                let need = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1);
                me.characters.iter().filter(|c| c.card.features.iter().any(|x| x == f)).count() as i64 >= need
            }
            // コスト cost_ge 以上の自キャラが n 枚以上 (effects.py:1653)
            "self_chara_cost_ge_count" => {
                let cg = v.get("cost_ge").and_then(|x| x.as_i64()).unwrap_or(0);
                let need = v.get("n").and_then(|x| x.as_i64()).unwrap_or(1);
                // 素の 「コストN以上」 = 現在コスト (base_cost、 修正込み)。 印刷 c.card.cost だと
                // buff で 6 になった自身を見落とす (cardqa st_14: ST14-009/ST14-003)。
                me.characters.iter().filter(|c| c.base_cost() as i64 >= cg).count() as i64 >= need
            }
            // 自リーダーの特徴に v を含むものがある (部分一致)
            "leader_feature_contains" => {
                let f = v.as_str().unwrap_or("");
                me.leader.card.features.iter().any(|x| x.contains(f))
            }
            "self_deck_count_le" => (me.deck.len() as i64) <= v.as_i64().unwrap_or(0),
            "total_life_le" => (me.life.len() + opp.life.len()) as i64 <= v.as_i64().unwrap_or(0),
            "self_life_plus_hand_le" => (me.life.len() + me.hand.len()) as i64 <= v.as_i64().unwrap_or(0),
            "self_life_lt_opp" => v.as_bool().unwrap_or(true) == (me.life.len() < opp.life.len()),
            "self_leader_active" => v.as_bool().unwrap_or(true) == !me.leader.rested,
            "opp_don_count_le" => total_don(opp) <= v.as_i64().unwrap_or(0),
            // 発動元自身の現在パワー >= N (effects.py:self_power_ge / self_inplay_power_ge)
            "self_power_ge" | "self_inplay_power_ge" => {
                let n = v.as_i64().unwrap_or(0);
                src.and_then(|sl| src_ip(me, sl)).map_or(false, |ip| ip.power() as i64 >= n)
            }
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
            // leader_color_multi は overlay の別名 (effects.py:1833)
            "leader_multicolor" | "leader_color_multi" => (me.leader.card.color.len() >= 2) == v.as_bool().unwrap_or(true),
            // 自場のキャラ数 <= N (effects.py:1156)。
            "self_field_count_le" => (me.characters.len() as i64) <= v.as_i64().unwrap_or(0),
            "self_field_count_ge" | "self_chara_count_ge" => (me.characters.len() as i64) >= v.as_i64().unwrap_or(0),
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
            // 「自分のドン‼すべてがレストの場合」 (cardqa_op_02、 OP02-027)。 コストエリアの
            // アクティブドン 0 かつ キャラ/リーダーへの付与ドンが 0 (付与ドンはレストではない)。
            "self_all_don_rested" => {
                let attached = me.leader.attached_dons
                    + me.characters.iter().map(|c| c.attached_dons).sum::<i32>();
                let all_rested = me.don_active == 0 && attached == 0;
                v.as_bool().unwrap_or(true) == all_rested
            }
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
            // ⭐ 「元々のパワー」 は **効果で書き換わる** (公式 4-9-2-1)。 印刷値ではなく
            //   **KO 時点の値** を見る (OP14-053 ビスタ × OP13-002 エース、 2026-08-11)。
            "victim_truly_original_power_ge" => state
                .last_chara_ko_victim_card
                .as_ref()
                .map_or(false, |vic| {
                    let vp = state
                        .rust_ko_victim_truly_original_power
                        .unwrap_or(vic.power);
                    (vp as i64) >= v.as_i64().unwrap_or(0)
                }),
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
                    matches_filter_ip(&c, base_filt.as_ref())
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
                    matches_filter_ip(&c, base_filt.as_ref())
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
            _ => {
                // 未知条件キー → 評価不能 → skip。 診断にキー名だけを記録する
                // (オブジェクト全体を記録すると同居する既知キーまで数えてしまう)。
                if crate::selfplay::DIAG_ON.load(std::sync::atomic::Ordering::Relaxed) {
                    if let Ok(mut m) = crate::selfplay::UNKNOWN_CONDS.lock() {
                        *m.entry(k.clone()).or_insert(0) += 1;
                    }
                }
                return None;
            }
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
    // ⭐ 公式 「**相手は**自身の…キャラ1枚を…」 = **選ぶのは相手** (cardqa_op_09)。
    //   相手は自分の損害が最小になる 1 枚を選ぶ = opp_value 昇順。
    //   (Python effects.py:_resolve_target 入口の _chooser_opp と同順)
    if let Some(o) = spec.and_then(|v| v.as_object()) {
        if o.get("chooser").and_then(|x| x.as_str()) == Some("opp") {
            let t = o.get("type").or_else(|| o.get("target")).and_then(|x| x.as_str());
            let mut cands: Vec<(usize, Slot)> = vec![];
            if let Some(ts) = t {
                let any_t = if ts.starts_with("one_opponent_") {
                    format!("any_{}", &ts["one_".len()..])
                } else {
                    ts.to_string()
                };
                let mut any_spec = o.clone();
                any_spec.remove("chooser");
                any_spec.insert("type".into(), Value::String(any_t));
                any_spec.remove("target");
                let sv = Value::Object(any_spec);
                cands = resolve_target(Some(&sv), me_idx, opp_idx, src, state).unwrap_or_default();
                if cands.is_empty() {
                    // `any_` 版が無い spec (one_opponent_character_filtered 等) の保険:
                    // 相手キャラ全体を filter で絞る (Python 側と同じ fallback)。
                    let filt = o.get("filter").cloned();
                    let opp = &state.players[opp_idx];
                    cands = (0..opp.characters.len())
                        .filter(|&i| matches_filter_ip(&opp.characters[i], filt.as_ref()))
                        .map(|i| (opp_idx, Slot::Char(i)))
                        .collect();
                }
            }
            if cands.is_empty() {
                return Some(vec![]);
            }
            // opp_value 昇順 (tie は board 順 = Python の instance_id 昇順と同じ並び)
            cands.sort_by(|a, b| {
                let va = opp_value(get_ip(&state.players[a.0], a.1));
                let vb = opp_value(get_ip(&state.players[b.0], b.1));
                va.partial_cmp(&vb).unwrap_or(std::cmp::Ordering::Equal)
            });
            return Some(vec![cands[0]]);
        }
    }

    let s = match spec {
        Some(v) if v.is_string() => v.as_str().unwrap().to_string(),
        None => "self".to_string(),
        Some(v) => {
            // 動的 filter (cost_le_dynamic / name_in_last_discarded / or) を **入口で** 静的化する。
            // Python の _resolve_target は dict spec 全てに _resolve_dynamic_filter を掛ける
            // (effects.py:2109)。 ⚠ Rust は個別 primitive でしか解決しておらず、 ko/return_to_hand
            //   等 の one_opponent_character_filtered が cost_le_dynamic を未解決のまま
            //   matches_filter に渡していた = 未知キーで 0 対象 = 効果不発
            //   (OP05-102 ゲダツ 「相手のライフの枚数以下のコスト」 等、 overlay で 24 箇所)。
            let _dyn_owned: Value;
            let v: &Value = if v.get("filter").is_some() {
                match resolve_dynamic_filter(v.get("filter"), state, me_idx) {
                    Some(rf) if Some(&rf) != v.get("filter") => {
                        let mut o = v.as_object().cloned().unwrap_or_default();
                        o.insert("filter".to_string(), rf);
                        _dyn_owned = Value::Object(o);
                        &_dyn_owned
                    }
                    _ => v,
                }
            } else {
                v
            };
            // {"type": "all_self_chara_filtered", "filter": {...}}
            // chara/character 表記揺れ alias (effects.py:_TYPE_ALIASES)。 これが無いと該当 overlay が
            // 未知 type 扱いで bail (Python 側は 2026-06-05 に同じ理由で silent no-op bug を修正済)。
            let t = match v.get("type").and_then(|x| x.as_str()).unwrap_or("") {
                "one_opp_chara_filtered" => "one_opponent_character_filtered",
                "one_opp_chara_any" => "one_opponent_character_any",
                "one_self_character_filtered" => "one_self_chara_filtered",
                other => other,
            };
            // {"type": "one_opponent_inplay_filtered", "filter": {...}} = 相手リーダー/キャラから
            // filter 一致 1 枚 (effects.py:2288、 threat_key = power 降順、 leader も候補)。
            // {"type": "one_inplay_either_filtered", "filter": {...}} = **両陣営** のリーダー/キャラ
            // から filter 一致 1 枚 (effects.py の同名 arm)。 公式が 「相手の」 と書いていない
            // 「キャラ1枚まで」 は 自陣も対象 (= 複数弾の Q&A で明示された一般則、 2026-08-04)。
            // ⚠ Python `_either_pick_one` は **相手側を opp_value 降順で 1 枚**、 居なければ
            //   **自陣の先頭** (board 順)。 両陣営を混ぜて power 降順にしてはいけない。
            if t == "one_inplay_either_filtered" {
                let filt = v.get("filter");
                let collect_side = |pi: usize, state: &GameState| -> Vec<Slot> {
                    let p = &state.players[pi];
                    let mut out: Vec<Slot> = vec![];
                    if matches_filter_ip(&p.leader, filt) {
                        out.push(Slot::Leader);
                    }
                    for i in 0..p.characters.len() {
                        if matches_filter_ip(&p.characters[i], filt) {
                            out.push(Slot::Char(i));
                        }
                    }
                    out
                };
                let mut opp_cands = collect_side(opp_idx, state);
                if !opp_cands.is_empty() {
                    let opp = &state.players[opp_idx];
                    let val = |sl: &Slot| -> f64 {
                        match sl {
                            Slot::Leader => opp_value(&opp.leader),
                            Slot::Char(i) => opp_value(&opp.characters[*i]),
                            _ => 0.0,
                        }
                    };
                    opp_cands.sort_by(|a, b| {
                        val(b).partial_cmp(&val(a)).unwrap_or(std::cmp::Ordering::Equal)
                    });
                    return Some(vec![(opp_idx, opp_cands[0])]);
                }
                // ⭐ **必須形** (spec の "mandatory": true = 公式が 「キャラN枚を」 で 「まで」 が無い)
                //   は 0 枚を選べないので、 相手候補が居なければ **自陣から選ぶ義務** がある。
                //   AI は最も惜しくない駒 (Python `_sacrifice_key` = 効果価値 → パワー昇順) を出す。
                //   任意形 (「まで」) は従来どおり 0 枚 = 自陣を差し出さない。
                if v.get("mandatory").and_then(|x| x.as_bool()).unwrap_or(false) {
                    let mut self_cands = collect_side(me_idx, state);
                    if !self_cands.is_empty() {
                        let me_p = &state.players[me_idx];
                        // Python `_sacrifice_key` は **パワー昇順のみ** (effects.py:863)。
                        // 余計な key を足すと同点時の選択が Python とズレる。
                        let key = |sl: &Slot| -> i32 {
                            match sl {
                                Slot::Leader => me_p.leader.power(),
                                Slot::Char(i) => me_p.characters[*i].power(),
                                _ => 0,
                            }
                        };
                        self_cands.sort_by_key(|sl| key(sl));
                        return Some(vec![(me_idx, self_cands[0])]);
                    }
                }
                // ⚠ 任意形では AI は自陣を auto-pick しない (Python `_either_pick_one` と対)。
                return Some(vec![]);
            }
            if t == "one_opponent_inplay_filtered" {
                let filt = v.get("filter");
                let opp = &state.players[opp_idx];
                let mut cands: Vec<(Slot, i32)> = vec![];
                if matches_filter_ip(&opp.leader, filt) {
                    cands.push((Slot::Leader, opp.leader.power()));
                }
                for i in 0..opp.characters.len() {
                    if matches_filter_ip(&opp.characters[i], filt) {
                        cands.push((Slot::Char(i), opp.characters[i].power()));
                    }
                }
                // Python は [leader, *characters] の順に集めてから power 降順で stable sort。
                cands.sort_by(|a, b| b.1.cmp(&a.1));
                return Some(cands.into_iter().take(1).map(|(sl, _)| (opp_idx, sl)).collect());
            }
            // 自キャラ全員 (filter 一致)。 rested / current_power_ge/le / limit を尊重
            // (effects.py:2187、 OP16-001 エース = current_power_ge 8000)。
            // 自リーダー + キャラ全員 (filter 一致)。 limit 指定で power 降順 N 枚 (effects.py:2221)。
            if t == "all_self_team_filtered" {
                let filt = v.get("filter");
                let p = &state.players[me_idx];
                let mut cands: Vec<(Slot, i32)> = vec![];
                if matches_filter_ip(&p.leader, filt) {
                    cands.push((Slot::Leader, p.leader.power()));
                }
                for i in 0..p.characters.len() {
                    if matches_filter_ip(&p.characters[i], filt) {
                        cands.push((Slot::Char(i), p.characters[i].power()));
                    }
                }
                if let Some(limit) = v.get("limit").and_then(|x| x.as_i64()) {
                    cands.sort_by(|a, b| b.1.cmp(&a.1));
                    cands.truncate(limit.max(0) as usize);
                }
                return Some(cands.into_iter().map(|(sl, _)| (me_idx, sl)).collect());
            }
            if t == "all_self_chara_filtered" {
                // rested は target 直下が優先、 無ければ filter 直書きを honor (Python 同様)。
                // filter 側は matches_filter が未知キーを不一致扱いにするので strip して渡す。
                let rested_req = v
                    .get("rested")
                    .and_then(|x| x.as_bool())
                    .or_else(|| v.get("filter").and_then(|f| f.get("rested")).and_then(|x| x.as_bool()));
                let filt: Option<Value> = v.get("filter").map(|f| {
                    let mut o = f.as_object().cloned().unwrap_or_default();
                    o.remove("rested");
                    Value::Object(o)
                });
                let filt = filt.as_ref();
                let cpge = v.get("current_power_ge").and_then(|x| x.as_i64()).map(|x| x as i32);
                let cple = v.get("current_power_le").and_then(|x| x.as_i64()).map(|x| x as i32);
                let p = &state.players[me_idx];
                let mut cands: Vec<usize> = (0..p.characters.len())
                    .filter(|&i| {
                        let c = &p.characters[i];
                        matches_filter_ip(&c, filt)
                            && rested_req.map_or(true, |r| c.rested == r)
                            && cpge.map_or(true, |n| c.power() >= n)
                            && cple.map_or(true, |n| c.power() <= n)
                    })
                    .collect();
                if let Some(limit) = v.get("limit").and_then(|x| x.as_i64()) {
                    // _threat_key = power 降順 (stable)
                    cands.sort_by(|&a, &b| p.characters[b].power().cmp(&p.characters[a].power()));
                    cands.truncate(limit.max(0) as usize);
                }
                return Some(cands.into_iter().map(|i| (me_idx, Slot::Char(i))).collect());
            }
            // 自キャラから名前一致 1 枚 (effects.py:2108)。 ⚠ overlay の name は未正規化の場合が
            // あるので norm_card_name で両側を揃える (全角Ｄ→D)。
            if t == "self_chara_named" {
                let name = norm_card_name(v.get("name").and_then(|x| x.as_str()).unwrap_or(""));
                let p = &state.players[me_idx];
                return Some(
                    (0..p.characters.len())
                        .filter(|&i| name_matches(&p.characters[i].card, &name))
                        .take(1)
                        .map(|i| (me_idx, Slot::Char(i)))
                        .collect(),
                );
            }
            if t == "all_self_chara_named" {
                let name = v.get("name").and_then(|x| x.as_str()).unwrap_or("");
                let p = &state.players[me_idx];
                return Some(
                    (0..p.characters.len())
                        .filter(|&i| name_matches(&p.characters[i].card, name))
                        .map(|i| (me_idx, Slot::Char(i)))
                        .collect(),
                );
            }
            // 自リーダー/キャラから名前一致 1 枚 (effects.py:2104、 leader 優先→char 順、 AI=先頭)。 OP15-076 counter。
            if t == "self_chara_or_leader_named" {
                let name = v.get("name").and_then(|x| x.as_str()).unwrap_or("");
                let p = &state.players[me_idx];
                if name_matches(&p.leader.card, name) {
                    return Some(vec![(me_idx, Slot::Leader)]);
                }
                for i in 0..p.characters.len() {
                    if name_matches(&p.characters[i].card, name) {
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
                if matches_filter_ip(&p.leader, filt) {
                    cands.push(Slot::Leader);
                }
                for i in 0..p.characters.len() {
                    if matches_filter_ip(&p.characters[i], filt) {
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
                // rested は target 直下の rested_required と filter 直書き の両方を honor する
                // (Python も同様。 記法が割れており、 honor しないと 「レスト限定」 が silent に
                // 消える = ST02-009_r1 で実害があった)。 filter 側は matches_filter が
                // 未知キーを不一致扱いにするので 必ず strip してから渡す。
                let rested_req = v.get("rested_required").and_then(|x| x.as_bool()).unwrap_or(false)
                    || v.get("filter").and_then(|f| f.get("rested")).and_then(|x| x.as_bool()).unwrap_or(false);
                let active_req = v
                    .get("filter")
                    .and_then(|f| f.get("active"))
                    .and_then(|x| x.as_bool())
                    .unwrap_or(false);
                let base_filt: Option<Value> = v.get("filter").map(|f| {
                    let mut o = f.as_object().cloned().unwrap_or_default();
                    o.remove("current_power_ge");
                    o.remove("current_power_le");
                    o.remove("rested");
                    o.remove("active");
                    Value::Object(o)
                });
                let p = &state.players[me_idx];
                let mut cands: Vec<usize> = (0..p.characters.len())
                    .filter(|&i| {
                        let c = &p.characters[i];
                        matches_filter_ip(&c, base_filt.as_ref())
                            && (!rested_req || c.rested)
                            && (!active_req || !c.rested)
                            && cpge.map_or(true, |t| c.power() as i64 >= t)
                            && cple.map_or(true, |t| (c.power() as i64) <= t)
                    })
                    .collect();
                cands.sort_by(|&a, &b| p.characters[b].power().cmp(&p.characters[a].power()));
                return Some(cands.into_iter().take(1).map(|i| (me_idx, Slot::Char(i))).collect());
            }
            // 相手キャラから filter 一致 1 枚 (effects.py:2182、 _threat_key=power降順)。 sub-filter:
            //   attached_don_ge / rested / active / blocker / current_power_le / current_cost_eq/le/ge。
            // 相手キャラ全員 (filter 一致)。 limit 指定で opp_value 降順に N 枚まで (effects.py:2260)。
            if t == "all_opponent_chara_filtered" {
                let filt = v.get("filter");
                let opp = &state.players[opp_idx];
                let mut cands: Vec<usize> = (0..opp.characters.len())
                    .filter(|&i| matches_filter_ip(&opp.characters[i], filt))
                    .collect();
                match v.get("limit").and_then(|x| x.as_i64()) {
                    Some(lim) => {
                        cands.sort_by(|&a, &b| {
                            opp_value(&opp.characters[b])
                                .partial_cmp(&opp_value(&opp.characters[a]))
                                .unwrap_or(std::cmp::Ordering::Equal)
                        });
                        return Some(cands.into_iter().take(lim as usize).map(|i| (opp_idx, Slot::Char(i))).collect());
                    }
                    None => return Some(cands.into_iter().map(|i| (opp_idx, Slot::Char(i))).collect()),
                }
            }
            if t == "one_opponent_character_filtered" || t == "one_character_either_filtered" {
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
                let ok = |c: &InPlay| -> bool {
                    matches_filter_ip(&c, base_filt.as_ref())
                        && (adg <= 0 || c.attached_dons as i64 >= adg)
                        && (!rr || c.rested)
                        && (!ar || !c.rested)
                        && (!br || c.is_blocker_now())
                        && cpl.map_or(true, |n| c.power() as i64 <= n)
                        && cce.map_or(true, |n| c.base_cost() as i64 == n)
                        && ccl.map_or(true, |n| c.base_cost() as i64 <= n)
                        && ccg.map_or(true, |n| c.base_cost() as i64 >= n)
                };
                let opp = &state.players[opp_idx];
                let mut cands: Vec<usize> =
                    (0..opp.characters.len()).filter(|&i| ok(&opp.characters[i])).collect();
                if t == "one_character_either_filtered" {
                    // **両陣営** 版 (公式が 「相手の」 と書いていない 「キャラ1枚まで」)。
                    // Python `_either_pick_one`: 相手側を opp_value 降順で 1 枚、 居なければ自陣先頭。
                    if !cands.is_empty() {
                        cands.sort_by(|&a, &b| {
                            opp_value(&opp.characters[b])
                                .partial_cmp(&opp_value(&opp.characters[a]))
                                .unwrap_or(std::cmp::Ordering::Equal)
                        });
                        return Some(vec![(opp_idx, Slot::Char(cands[0]))]);
                    }
                    // ⚠ AI は自陣を auto-pick しない。 この spec 群は公式が全て
                    // 「キャラN枚**まで**」 = 0 枚可 (overlay 64 件確認済、 必須形は無い)。
                    // 相手が居ないのに自分のキャラを送るのはほぼ常に悪手 (Python `_either_pick_one` と対)。
                    return Some(vec![]);
                }
                cands.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
                return Some(cands.into_iter().take(1).map(|i| (opp_idx, Slot::Char(i))).collect());
            }
            return None;
        }
    };
    // ⭐ 公式は 「コストN以下」 と 「**元々の**コストN以下」 を区別する (effects.py:_resolve_target と対)。
    //   - 「コストN以下」       = 効果修正を反映した **現在のコスト** (InPlay::base_cost)
    //     cardqa_op_02「本来のコストが8以上のキャラが、他の効果で7コスト以下になった場合…はい、できます」
    //   - 「元々のコストN以下」  = **印刷コスト** (CardDef.cost)
    //     cardqa_eb_03「元々のコストが4以上で、他の効果によって現在のコストが3以下になっているキャラを…」
    //                 →「いいえ、できません」
    //   ⚠ 分岐ごとに判定を書くと必ず漏れるので **入口で正規化** する。 spec 名を素の形に畳み、
    //     どちらのコストを見るかは `use_printed_cost` 1 箇所で決める。
    let use_printed_cost = s.contains("_truly_original_cost_");
    let s = if use_printed_cost { s.replace("_truly_original_cost_", "_cost_") } else { s };
    let cost_of = |ip: &InPlay| -> i32 { if use_printed_cost { ip.card.cost } else { ip.base_cost() } };
    //   パワーも同じ書き分け (cardqa: 「元々のパワーが6000以下のキャラが効果で7000以上となって
    //   いる場合、 この【メイン】効果でKOできますか？」 → 「いいえ。 **現在のパワー**が6000以下の
    //   キャラをKOできます」)。 素の 「パワーN以下」 = 現在パワー / 「元々のパワー」 = 印刷パワー。
    let use_printed_power = s.contains("_truly_original_power_");
    let s = if use_printed_power { s.replace("_truly_original_power_", "_power_") } else { s };
    let power_of = |ip: &InPlay| -> i32 { if use_printed_power { ip.card.power } else { ip.power() } };
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
        // 相手の【ブロッカー】持ちキャラ 1 枚 (effects.py:2504、 opp_value 降順)
        "one_opp_chara_blocker" => {
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> = (0..opp.characters.len())
                .filter(|&i| opp.characters[i].is_blocker_now())
                .collect();
            cands.sort_by(|&a, &b| {
                opp_value(&opp.characters[b])
                    .partial_cmp(&opp_value(&opp.characters[a]))
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            cands.into_iter().take(1).map(|i| (opp_idx, Slot::Char(i))).collect()
        }
        // 自分のリーダー or キャラ 1 枚 (effects.py:one_self_team_any、 power 降順)
        // 公式 「リーダーかキャラ1枚に持ち主のレストのドン‼」 = 修飾なし = **両陣営** (cardqa_op_15)。
        // AI は自陣を選ぶ (= 従来 one_self_team_any と同挙動を維持)。 Python と同順。
        "one_team_any_either" => {
            let me = &state.players[me_idx];
            let mut cands: Vec<(Slot, i32)> = vec![(Slot::Leader, me.leader.power())];
            for (i, c) in me.characters.iter().enumerate() {
                cands.push((Slot::Char(i), c.power()));
            }
            cands.sort_by(|a, b| b.1.cmp(&a.1));
            vec![(me_idx, cands[0].0)]
        }
        "one_self_team_any" => {
            let me = &state.players[me_idx];
            let mut cands: Vec<(Slot, i32)> = vec![(Slot::Leader, me.leader.power())];
            for (i, c) in me.characters.iter().enumerate() {
                cands.push((Slot::Char(i), c.power()));
            }
            cands.sort_by(|a, b| b.1.cmp(&a.1));
            vec![(me_idx, cands[0].0)]
        }
        // one_self_character_cost_le_N(cost) (effects.py:2720) = 自分の元コスト N 以下のキャラ 1 枚 (power 降順)
        os if os.starts_with("one_self_character_cost_le_") => {
            let n = parse_after(os, "cost_le_").unwrap_or(0);
            let me = &state.players[me_idx];
            let mut cands: Vec<usize> = (0..me.characters.len())
                .filter(|&i| cost_of(&me.characters[i]) <= n)
                .collect();
            cands.sort_by(|&a, &b| me.characters[b].power().cmp(&me.characters[a].power()));
            cands.into_iter().take(1).map(|i| (me_idx, Slot::Char(i))).collect()
        }
        // one_self_character_cost_eq_N (effects.py:2803) = 自分の元コスト N ぴったりのキャラ 1 枚 (power 降順)
        os if os.starts_with("one_self_character_cost_eq_") => {
            let n = parse_after(os, "cost_eq_").unwrap_or(-1);
            let me = &state.players[me_idx];
            let mut cands: Vec<usize> = (0..me.characters.len())
                .filter(|&i| cost_of(&me.characters[i]) == n)
                .collect();
            cands.sort_by(|&a, &b| me.characters[b].power().cmp(&me.characters[a].power()));
            cands.into_iter().take(1).map(|i| (me_idx, Slot::Char(i))).collect()
        }
        // any_opp_inplay_n_N (effects.py:2816) = 相手のリーダーかキャラ 合計 N 枚まで。
        // AI: キャラを power 降順で優先、 N 体未満ならリーダーを補充。
        os if os.starts_with("any_opp_inplay_n_") => {
            let n = parse_after(os, "_n_").unwrap_or(1).max(0) as usize;
            let opp = &state.players[opp_idx];
            let mut chara: Vec<usize> = (0..opp.characters.len()).collect();
            chara.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
            let mut out: Vec<(usize, Slot)> =
                chara.iter().map(|&i| (opp_idx, Slot::Char(i))).collect();
            if out.len() < n {
                out.push((opp_idx, Slot::Leader));
            }
            out.truncate(n);
            out
        }
        // opp_just_negated_(power|cost)_le_N = 直前に negate した相手キャラを、 power/cost 閾値を
        // 満たす場合のみ返す (effects.py:2316、 「その後、 そのキャラのコストがX以下ならKO」 OP09-098)。
        os if os.starts_with("opp_just_negated_power_le_")
            || os.starts_with("opp_just_negated_cost_le_") =>
        {
            let is_power = os.starts_with("opp_just_negated_power_le_");
            let thr = parse_after(os, "_le_").unwrap_or(0);
            // Python は iid で opp.characters を走査 = 場を離れていれば [] (index 越境も同義)。
            // リーダーは Python 側も opp.characters しか見ない = 対象外。
            match state.last_negated {
                Some((pi, Slot::Char(ci)))
                    if pi == opp_idx && ci < state.players[pi].characters.len() =>
                {
                    let ip = &state.players[pi].characters[ci];
                    let val = if is_power { ip.power() } else { ip.base_cost() };
                    if val <= thr { vec![(pi, Slot::Char(ci))] } else { vec![] }
                }
                _ => vec![],
            }
        }
        // opp_just_negated_any = 直前に negate した相手のリーダー or キャラ (effects.py の
        // 同名 spec)。 「1 枚までを、 効果を無効にし、 パワー-N」 の後半を 同一の 1 枚 に当てる
        // (OP09-097 闇水)。 場を離れていれば [] (= Python の iid 照合と等価)。
        // 「相手のレストのキャラ1枚までを選ぶ。 選んだキャラのコストが付与ドン枚数と同じ場合、 KO」
        // (OP15-031 プリンプリン、 effects.py:2580)。 Python と同じ簡略: KO が成立する選択のみ候補化
        // (= base_cost == attached_dons の レストキャラ)。 sort は _opp_value 降順。
        "one_opponent_rested_character_don_eq_cost" => {
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> = (0..opp.characters.len())
                .filter(|&i| {
                    let c = &opp.characters[i];
                    c.rested && c.base_cost() == c.attached_dons
                })
                .collect();
            cands.sort_by(|&a, &b| {
                opp_value(&opp.characters[b])
                    .partial_cmp(&opp_value(&opp.characters[a]))
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            cands.into_iter().take(1).map(|i| (opp_idx, Slot::Char(i))).collect()
        }
        "opp_just_negated_any" => match state.last_negated {
            Some((pi, Slot::Char(ci)))
                if pi == opp_idx && ci < state.players[pi].characters.len() =>
            {
                vec![(pi, Slot::Char(ci))]
            }
            Some((pi, Slot::Leader)) if pi == opp_idx => vec![(pi, Slot::Leader)],
            _ => vec![],
        },
        // 両陣営から 1 枚 (公式が 「相手の」 と書いていない 「キャラ1枚まで」)。
        // Python `_either_pick_one`: 相手側を opp_value 降順で 1 枚、 居なければ自陣の先頭。
        "one_character_either_any" => {
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> = (0..opp.characters.len()).collect();
            if !cands.is_empty() {
                cands.sort_by(|&a, &b| {
                    opp_value(&opp.characters[b])
                        .partial_cmp(&opp_value(&opp.characters[a]))
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
                return Some(vec![(opp_idx, Slot::Char(cands[0]))]);
            }
            // ⚠ AI は自陣を auto-pick しない (Python `_either_pick_one` と対)。
            vec![]
        }
        // 両陣営、 元々のパワー N ぴったり 1 枚 (EB03-027 マーガレット等)。
        os if os.starts_with("one_character_either_power_eq_") => {
            let n = parse_after(os, "power_eq_").unwrap_or(0);
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> =
                (0..opp.characters.len()).filter(|&i| power_of(&opp.characters[i]) == n).collect();
            if !cands.is_empty() {
                cands.sort_by(|&a, &b| {
                    opp_value(&opp.characters[b])
                        .partial_cmp(&opp_value(&opp.characters[a]))
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
                return Some(vec![(opp_idx, Slot::Char(cands[0]))]);
            }
            // ⚠ AI は自陣を auto-pick しない (Python `_either_pick_one` と対)。
            vec![]
        }
        // 両陣営、 コスト N ぴったり 1 枚。 素の 「コストN の」 は現在コスト、
        // 「元々のコストN の」 は入口正規化で cost_of が印刷コストを返す。
        os if os.starts_with("one_character_either_cost_eq_") => {
            let n = parse_after(os, "cost_eq_").unwrap_or(0);
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> =
                (0..opp.characters.len()).filter(|&i| cost_of(&opp.characters[i]) == n).collect();
            if !cands.is_empty() {
                cands.sort_by(|&a, &b| {
                    opp_value(&opp.characters[b])
                        .partial_cmp(&opp_value(&opp.characters[a]))
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
                return Some(vec![(opp_idx, Slot::Char(cands[0]))]);
            }
            // ⚠ AI は自陣を auto-pick しない (Python `_either_pick_one` と対)。
            vec![]
        }
        // one_character_either_cost_le_N = 両陣営のキャラから 元コスト N 以下 1 枚 (相手優先 power 降順)
        // ⚠ overlay の `one_inplay_cost_le_N` 表記も同 semantics (effects.py:2626、 OP02-062 等)。
        os if os.starts_with("one_character_either_cost_le_") || os.starts_with("one_inplay_cost_le_") => {
            let n = parse_after(os, "cost_le_").unwrap_or(0);
            // ⚠ Python は **相手キャラを優先** する (effects.py: opp_cands を _opp_value 降順で
            //   ソートし、 居れば必ずそこから 1 体。 居ない時だけ自陣の先頭)。 両陣営を混ぜて
            //   power 降順にすると 高パワーの自キャラが選ばれ、 **自分自身を手札に戻す** 等の
            //   誤動作になる (OP10-046 キュロスが自分を戻して場に出ない、 2026-08-03 発覚)。
            let opp = &state.players[opp_idx];
            let mut opp_cands: Vec<usize> =
                (0..opp.characters.len()).filter(|&i| cost_of(&opp.characters[i]) <= n).collect();
            if !opp_cands.is_empty() {
                opp_cands.sort_by(|&a, &b| {
                    opp_value(&opp.characters[b])
                        .partial_cmp(&opp_value(&opp.characters[a]))
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
                return Some(vec![(opp_idx, Slot::Char(opp_cands[0]))]);
            }
            // ⚠ AI は自陣を auto-pick しない (Python `_either_pick_one` と対)。
            vec![]
        }
        // 「このキャラ以外の自分のリーダーかキャラ 1 枚」 (effects.py:2334、 ST01-005)。
        // 発動元を除外して power 降順 1 枚 (tie は leader→char の board 順 = 安定ソート)。
        "self_team_except_self" => {
            let me = &state.players[me_idx];
            let src_idx = if let Slot::Char(i) = src { Some(i) } else { None };
            let mut cands: Vec<(Slot, i32)> = vec![];
            if !matches!(src, Slot::Leader) {
                cands.push((Slot::Leader, me.leader.power()));
            }
            for (i, c) in me.characters.iter().enumerate() {
                if Some(i) != src_idx {
                    cands.push((Slot::Char(i), c.power()));
                }
            }
            cands.sort_by(|a, b| b.1.cmp(&a.1));
            match cands.first() {
                Some(&(sl, _)) => vec![(me_idx, sl)],
                None => vec![],
            }
        }
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
        // one_self_inplay_feature_X = 自分のリーダーかキャラで 特徴 X を持つ 1 体
        // (effects.py:3318、 OP15-114 ワイパー 「自分の特徴《空島》を持つ、 リーダーかキャラ1枚」)。
        // ⚠ AI 選択基準は Python と同じく **power 降順 + 安定ソート** (= 同値ならリーダー優先)。
        os if os.starts_with("one_self_inplay_feature_") => {
            let feat = &os["one_self_inplay_feature_".len()..];
            let p = &state.players[me_idx];
            let mut cands: Vec<Slot> = Vec::new();
            if p.leader.card.features.iter().any(|f| f == feat) {
                cands.push(Slot::Leader);
            }
            for (i, ip) in p.characters.iter().enumerate() {
                if ip.card.features.iter().any(|f| f == feat) {
                    cands.push(Slot::Char(i));
                }
            }
            cands.sort_by_key(|&sl| -(src_ip(p, sl).map(|ip| ip.power()).unwrap_or(0)));
            cands.into_iter().take(1).map(|sl| (me_idx, sl)).collect()
        }
        // all_self_inplay_feature_X = 自分のリーダーかキャラで 特徴 X を持つ全員 (effects.py:3332)。
        // Python は [leader] + characters の順 (power ソートなし)。
        os if os.starts_with("all_self_inplay_feature_") => {
            let feat = &os["all_self_inplay_feature_".len()..];
            let p = &state.players[me_idx];
            let mut out: Vec<(usize, Slot)> = Vec::new();
            if p.leader.card.features.iter().any(|f| f == feat) {
                out.push((me_idx, Slot::Leader));
            }
            for (i, ip) in p.characters.iter().enumerate() {
                if ip.card.features.iter().any(|f| f == feat) {
                    out.push((me_idx, Slot::Char(i)));
                }
            }
            out
        }
        // all_self_chara(cters)_cost_le_N = 自分のコスト N 以下のキャラ全員 (effects.py:2577、 OP06-096)。
        os if os.starts_with("all_self_chara_cost_le_")
            || os.starts_with("all_self_characters_cost_le_")
            || os.starts_with("all_self_character_cost_le_") =>
        {
            let n = parse_after(os, "cost_le_").unwrap_or(0);
            (0..state.players[me_idx].characters.len())
                .filter(|&i| cost_of(&state.players[me_idx].characters[i]) <= n)
                .map(|i| (me_idx, Slot::Char(i)))
                .collect()
        }
        // all_chara_either_cost_le_N = 両陣営の元コスト N 以下キャラ全員 (effects.py:2615、 相手→自分の順)。
        os if os.starts_with("all_chara_either_cost_le_") => {
            let n = parse_after(os, "cost_le_").unwrap_or(0);
            let mut out: Vec<(usize, Slot)> = (0..state.players[opp_idx].characters.len())
                .filter(|&i| cost_of(&state.players[opp_idx].characters[i]) <= n)
                .map(|i| (opp_idx, Slot::Char(i)))
                .collect();
            out.extend(
                (0..state.players[me_idx].characters.len())
                    .filter(|&i| cost_of(&state.players[me_idx].characters[i]) <= n)
                    .map(|i| (me_idx, Slot::Char(i))),
            );
            out
        }
        // 「その後、 そのカードを〜」 = 直前 power_pump 対象 (effects.py:2355、 OP07-095/OP11-059)。
        // Python は last_pumped_iid で me.leader/characters を走査 = 場外なら 0 対象。
        "self_just_buffed" => match state.last_pumped {
            Some((pi, -1)) if pi == me_idx => vec![(me_idx, Slot::Leader)],
            Some((pi, ci)) if pi == me_idx && ci >= 0 && (ci as usize) < state.players[me_idx].characters.len() => {
                vec![(me_idx, Slot::Char(ci as usize))]
            }
            _ => vec![],
        },
        // one_opponent_character_(any_)cost_le_N = 元コスト N 以下の相手キャラ 1 体
        // (effects.py:2606、 opp_value 降順)。 `any_` infix は冗長 alias。
        os if os.starts_with("one_opponent_character_cost_le_")
            || os.starts_with("one_opponent_character_any_cost_le_") =>
        {
            let n = parse_after(os, "cost_le_").unwrap_or(0);
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> =
                (0..opp.characters.len()).filter(|&i| cost_of(&opp.characters[i]) <= n).collect();
            cands.sort_by(|&a, &b| {
                opp_value(&opp.characters[b])
                    .partial_cmp(&opp_value(&opp.characters[a]))
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            cands.into_iter().take(1).map(|i| (opp_idx, Slot::Char(i))).collect()
        }
        // one_opponent_character_power_le_N = 現パワー N 以下の相手キャラ 1 体 (effects.py:2698、 power 降順)。
        os if os.starts_with("one_opponent_character_power_le_") => {
            let n = parse_after(os, "power_le_").unwrap_or(0);
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> =
                (0..opp.characters.len()).filter(|&i| power_of(&opp.characters[i]) <= n).collect();
            cands.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
            cands.into_iter().take(1).map(|i| (opp_idx, Slot::Char(i))).collect()
        }
        // 「相手のドン N 枚以上付与キャラ 1 体」 (effects.py:2717、 OP15-001)。 threat_key = power 降順。
        os if os.starts_with("one_opponent_character_attached_don_ge_") => {
            let n = parse_after(os, "don_ge_").unwrap_or(0);
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> =
                (0..opp.characters.len()).filter(|&i| opp.characters[i].attached_dons >= n).collect();
            cands.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
            cands.into_iter().take(1).map(|i| (opp_idx, Slot::Char(i))).collect()
        }
        // 「自分の【アタック時】効果を持たないキャラ 1 枚」 (effects.py:2421、 EB03-001)。 power 降順。
        "one_self_chara_no_on_attack_effect" => {
            let me = &state.players[me_idx];
            let mut cands: Vec<usize> = (0..me.characters.len())
                .filter(|&i| !card_has_when(&me.characters[i].card.card_id, "on_attack"))
                .collect();
            cands.sort_by(|&a, &b| me.characters[b].power().cmp(&me.characters[a].power()));
            cands.into_iter().take(1).map(|i| (me_idx, Slot::Char(i))).collect()
        }
        // one_self_(character|chara)_named_X = 名前一致の自キャラ 1 枚 (effects.py:2926)。
        os if os.starts_with("one_self_character_named_") || os.starts_with("one_self_chara_named_") => {
            let name = norm_card_name(
                os.trim_start_matches("one_self_character_named_")
                    .trim_start_matches("one_self_chara_named_"),
            );
            let me = &state.players[me_idx];
            (0..me.characters.len())
                .filter(|&i| name_matches(&me.characters[i].card, &name))
                .take(1)
                .map(|i| (me_idx, Slot::Char(i)))
                .collect()
        }
        // any_opp_rested_chara_or_stage_n_N = 相手のレストのキャラ/ステージ 合計 N 枚まで
        // (effects.py:2881、 OP14-021)。 候補順 = characters → stages、 その後 power 降順。
        os if os.starts_with("any_opp_rested_chara_or_stage_n_") => {
            let n = parse_after(os, "_n_").unwrap_or(1).max(0) as usize;
            let opp = &state.players[opp_idx];
            let mut cands: Vec<(Slot, i32)> = vec![];
            for i in 0..opp.characters.len() {
                if opp.characters[i].rested {
                    cands.push((Slot::Char(i), opp.characters[i].power()));
                }
            }
            for i in 0..opp.stages.len() {
                if opp.stages[i].rested {
                    cands.push((Slot::Stage(i), opp.stages[i].power()));
                }
            }
            cands.sort_by(|a, b| b.1.cmp(&a.1)); // _threat_key = power 降順 (stable)
            cands.into_iter().take(n).map(|(sl, _)| (opp_idx, sl)).collect()
        }
        // 「自分のキャラ 1 枚」 の別名 (effects.py:2398、 one_self_character_any と同 semantics、 power 降順)。
        "any_self_chara" => {
            let me = &state.players[me_idx];
            let mut cands: Vec<usize> = (0..me.characters.len()).collect();
            cands.sort_by(|&a, &b| me.characters[b].power().cmp(&me.characters[a].power()));
            cands.into_iter().take(1).map(|i| (me_idx, Slot::Char(i))).collect()
        }
        // 「自分のコスト N 以下で【登場時】効果を持たないキャラ 1 枚」 (effects.py:2745、 PRB01-001)。
        os if os.starts_with("one_self_chara_no_on_play_cost_le_") => {
            let n = parse_after(os, "cost_le_").unwrap_or(0);
            let me = &state.players[me_idx];
            let mut cands: Vec<usize> = (0..me.characters.len())
                .filter(|&i| {
                    cost_of(&me.characters[i]) <= n && !card_has_on_play(&me.characters[i].card.card_id)
                })
                .collect();
            cands.sort_by(|&a, &b| me.characters[b].power().cmp(&me.characters[a].power()));
            cands.into_iter().take(1).map(|i| (me_idx, Slot::Char(i))).collect()
        }
        // 「自分の元々の効果のないキャラ 1 枚」 (effects.py:2428、 power 降順)。
        "one_self_chara_no_effect" => {
            let me = &state.players[me_idx];
            let mut cands: Vec<usize> = (0..me.characters.len())
                .filter(|&i| card_has_no_effect(&me.characters[i].card.card_id))
                .collect();
            cands.sort_by(|&a, &b| me.characters[b].power().cmp(&me.characters[a].power()));
            cands.into_iter().take(1).map(|i| (me_idx, Slot::Char(i))).collect()
        }
        // 「相手の元々の効果のないキャラ 1 枚」 (effects.py:2443、 opp_value 降順)。
        "one_opp_chara_no_effect" => {
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> = (0..opp.characters.len())
                .filter(|&i| card_has_no_effect(&opp.characters[i].card.card_id))
                .collect();
            cands.sort_by(|&a, &b| {
                opp_value(&opp.characters[b])
                    .partial_cmp(&opp_value(&opp.characters[a]))
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            cands.into_iter().take(1).map(|i| (opp_idx, Slot::Char(i))).collect()
        }
        // 「相手のアタックしているリーダーかキャラ」 (effects.py:2460、 OP04-069)。
        // Python は state.current_attacker_iid → opp.leader/characters を走査。 Rust は
        // current_attacker_tok (アタック宣言時に打つ一意トークン) で追う。 場外/文脈外は 0 対象。
        "opponent_attacker" => match peek_tagged(state, opp_idx, state.current_attacker_tok) {
            Slot::Detached => vec![],
            sl => vec![(opp_idx, sl)],
        },
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
                .filter(|&i| power_of(&state.players[opp_idx].characters[i]) <= n)
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
                .filter(|&i| cost_of(&opp.characters[i]) <= n)
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
            let cost_le = parse_after(os, "cost_le_"); // cost_of(&c) <= n
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
            // power_eq_N = 「元々のパワー N ぴったり」 (effects.py:2730、 CardDef.power で判定)。
            // ⚠ 下の未知トークン guard は _le_/_ge_ しか見ておらず _eq_ を素通ししていたため、
            //   EB03-025 ヒナ 「元々のパワー6000のキャラ1枚を手札に戻す」 が **無条件で最大脅威**
            //   を戻していた (パワー7000 を戻す = MISMATCH、 2026-08-03 全カード差分掃引で発覚)。
            let power_eq = parse_after(os, "power_eq_");
            // cost_eq_N = 「コスト N ぴったり」 (effects.py:2810、 元コスト card.cost)。
            // ⚠ Python の正規表現は `one_opponent_character_cost_(?:eq_)?(\d+)$` なので
            //   **裸の cost_N** (= one_opponent_character_cost_0) も 「ぴったり N」 として扱う。
            //   Rust は _le_/_ge_/_eq_ しか見ておらず、 裸形は filter 無しで通って
            //   **最大脅威を無条件 KO** していた (OP03-096、 2026-08-03 発覚)。
            let cost_eq = parse_after(os, "cost_eq_").or_else(|| {
                // 裸 cost_N: "..._cost_<digits>" (末尾 "cost" 付き表記も許容)。
                // cost_le_N / cost_ge_N は num が数字だけにならないので誤爆しない。
                let base = os.strip_suffix("cost").unwrap_or(os);
                let idx = base.rfind("_cost_")?;
                let num = &base[idx + "_cost_".len()..];
                if num.is_empty() || !num.chars().all(|c| c.is_ascii_digit()) {
                    return None;
                }
                num.parse().ok()
            });
            // まだ認識できない filter token (_le_/_ge_/_eq_ 残) は誤選択回避で bail。
            if cost_le.is_none()
                && power_le.is_none()
                && power_eq.is_none()
                && cost_eq.is_none()
                && (os.contains("_le_") || os.contains("_ge_") || os.contains("_eq_"))
            {
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
                        let cc = cost_of(c);
                        if cc > n {
                            return false;
                        }
                    }
                    if let Some(n) = power_le {
                        if power_of(c) > n {
                            return false;
                        }
                    }
                    // power_eq も 素の 「パワー」 なら現在値 (「元々のパワー」 なら spec 名が
                    // _truly_original_power_ を含み power_of が印刷値を返す)。
                    if let Some(n) = power_eq {
                        if power_of(c) != n {
                            return false;
                        }
                    }
                    // cost_eq (公式 「コストN の」) も 素の 「コスト」 なので **現在コスト**。
                    // 「元々のコストN」 なら spec 名が _truly_original_cost_ を含み cost_of が印刷値を返す。
                    if let Some(n) = cost_eq {
                        if cost_of(c) != n {
                            return false;
                        }
                    }
                    true
                })
                .collect();
            // ⚠ Python は spec 毎に sort key が異なる: **明示 "power_le" を含む spec** (one_opponent_
            // character_power_le_N=effects.py:2647 / rested_character_power_le=2716) は _threat_key
            // (= power 降順)、 bare "character_le"/cost_le は _opp_value。 安定ソートで tie は index 順。
            // power_eq_N も Python は _threat_key (effects.py:2742 `cands.sort(key=_threat_key)`)。
            if os.contains("power_le_") || os.contains("power_eq_") || os.contains("cost_eq_") {
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
        // ⚠ OP14-069 は `any_opponent_character_le_Ncost` の引数順違い表記も使う (effects.py:2663)。
        os if os.starts_with("any_opponent_character_cost_le_")
            || (os.starts_with("any_opponent_character_le_") && os.ends_with("cost")) =>
        {
            let n = if os.starts_with("any_opponent_character_cost_le_") {
                parse_after(os, "cost_le_").unwrap_or(0)
            } else {
                os.trim_start_matches("any_opponent_character_le_")
                    .trim_end_matches("cost")
                    .parse::<i32>()
                    .unwrap_or(0)
            };
            let opp = &state.players[opp_idx];
            (0..opp.characters.len())
                .filter(|&i| cost_of(&opp.characters[i]) <= n)
                .map(|i| (opp_idx, Slot::Char(i)))
                .collect()
        }
        os if os.starts_with("any_opponent_character_power_le_") => {
            let n = parse_after(os, "power_le_").unwrap_or(0);
            let opp = &state.players[opp_idx];
            (0..opp.characters.len())
                .filter(|&i| power_of(&opp.characters[i]) <= n)
                .map(|i| (opp_idx, Slot::Char(i)))
                .collect()
        }
        // all_opponent_rested_characters_le_Ncost = 相手レストのコストN以下 全員 (effects.py:2732、 sort 無)。
        os if os.starts_with("all_opponent_rested_characters_le_") && os.ends_with("cost") => {
            let n: i32 = os["all_opponent_rested_characters_le_".len()..os.len() - 4].parse().unwrap_or(0);
            let opp = &state.players[opp_idx];
            (0..opp.characters.len())
                .filter(|&i| opp.characters[i].rested && cost_of(&opp.characters[i]) <= n)
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
                .filter(|&i| opp.characters[i].rested && cost_of(&opp.characters[i]) <= cost_cap)
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
        _ => {
            // 未対応 target spec = bail (Python は [] を返すが、 実装済 spec との区別が付かないので
            // 黙って no-op にはしない)。 診断のため spec 名を記録する。
            note_unknown_key("target", &s);
            return None;
        }
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
    if !o.contains_key("cost_le_dynamic")
        && !o.contains_key("or")
        && !o.contains_key("name_in_last_discarded")
    {
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
    // EB02-039: 「捨てたカードと同名」 = 直前に cost で捨てたカード名で絞る (effects.py:10545)。
    if m.remove("name_in_last_discarded").map_or(false, |v| v.as_bool() != Some(false)) {
        m.insert(
            "name_in".to_string(),
            Value::Array(
                state.last_discarded_names.iter().map(|n| Value::String(n.clone())).collect(),
            ),
        );
    }
    if o.contains_key("cost_le_dynamic") {
        m.remove("cost_le_dynamic");
        m.insert("cost_le".to_string(), Value::Number(cost_le.into()));
    }
    // or 節も再帰的に解決 (effects.py:10570)。
    if let Some(Value::Array(subs)) = m.get("or").cloned() {
        let resolved: Vec<Value> = subs
            .iter()
            .map(|sub| resolve_dynamic_filter(Some(sub), state, me_idx).unwrap_or(sub.clone()))
            .collect();
        m.insert("or".to_string(), Value::Array(resolved));
    }
    Some(Value::Object(m))
}

/// play_from_hand_or_trash の登場配置 (effects.py:7767 `_place_pfhot`)。 STAGE なら MAX 超過分を
/// トラッシュ (付与ドンは rested へ返却) してから append、 それ以外はキャラエリア (満杯なら最弱破棄)。
/// 登場後に on_play を発火する (キュー経由なので実行は解決境界まで defer される)。
fn place_played_card(
    state: &mut GameState,
    me_idx: usize,
    card: crate::state::CardDef,
    rested: bool,
    cat: crate::state::Category,
) -> Result<(), String> {
    if cat == crate::state::Category::Stage {
        while state.players[me_idx].stages.len() >= 1 {
            let old = state.players[me_idx].stages.pop().unwrap();
            let ad = old.attached_dons;
            state.players[me_idx].trash.push(old.card);
            state.players[me_idx].don_rested += ad;
        }
        let mut ip = InPlay::of(card, true);
        ip.rested = rested;
        state.players[me_idx].stages.push(ip);
        let pidx = state.players[me_idx].stages.len() - 1;
        return execute_stage_on_play(state, me_idx, pidx);
    }
    trash_weakest_for_field_full(state, me_idx);
    let mut ip = InPlay::of(card.clone(), true);
    ip.rested = rested;
    state.players[me_idx].characters.push(ip);
    let pidx = state.players[me_idx].characters.len() - 1;
    state.last_self_chara_played_card = Some(card);
    state.last_self_chara_played_from_trash = false;
    execute_on_play(state, me_idx, pidx)
}

thread_local! {
    static SRC_TAG_SEQ: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}

/// 発動元 InPlay に一意トークンを打つ。 返り値を find_tagged に渡すと現在位置が取れる。
/// 場外 (Detached / 範囲外) なら None = 追跡不要。
pub(crate) fn tag_src(state: &mut GameState, me_idx: usize, src: Slot) -> Option<u64> {
    let tok = SRC_TAG_SEQ.with(|c| {
        let v = c.get() + 1;
        c.set(v);
        v
    });
    let ip = src_ip_mut(&mut state.players[me_idx], src)?;
    ip.rust_src_tag.push(tok);
    Some(tok)
}

/// find_tagged のタグを消さない版。 継続的に位置を追う用途 (アタッカー等)。
pub(crate) fn peek_tagged(state: &GameState, me_idx: usize, tok: Option<u64>) -> Slot {
    let Some(tok) = tok else { return Slot::Detached };
    let pl = &state.players[me_idx];
    if pl.leader.rust_src_tag.contains(&tok) {
        return Slot::Leader;
    }
    for i in 0..pl.characters.len() {
        if pl.characters[i].rust_src_tag.contains(&tok) {
            return Slot::Char(i);
        }
    }
    for i in 0..pl.stages.len() {
        if pl.stages[i].rust_src_tag.contains(&tok) {
            return Slot::Stage(i);
        }
    }
    Slot::Detached
}

/// カードが「元々の効果を持たない」 (overlay 未登録 or 空) か (effects.py:2432 `_no_effect`)。
fn card_has_no_effect(card_id: &str) -> bool {
    overlay().and_then(|m| m.get(card_id)).map_or(true, |effs| effs.is_empty())
}

/// tag_src で打ったトークンを探して現在の Slot を返す (見つかればタグは消す)。
/// 見つからない = 発動元が場を離れた → Python の self_inplay は生きているが場外 = Slot::Detached 相当。
pub(crate) fn find_tagged(state: &mut GameState, me_idx: usize, tok: Option<u64>) -> Slot {
    let Some(tok) = tok else { return Slot::Detached };
    let mut found = Slot::Detached;
    let mut drop_tok = |ip: &mut InPlay| -> bool {
        if ip.rust_src_tag.contains(&tok) {
            ip.rust_src_tag.retain(|x| *x != tok);
            true
        } else {
            false
        }
    };
    for pi in 0..2 {
        let pl = &mut state.players[pi];
        if drop_tok(&mut pl.leader) && pi == me_idx {
            found = Slot::Leader;
        }
        for i in 0..pl.characters.len() {
            if drop_tok(&mut pl.characters[i]) && pi == me_idx {
                found = Slot::Char(i);
            }
        }
        for i in 0..pl.stages.len() {
            if drop_tok(&mut pl.stages[i]) && pi == me_idx {
                found = Slot::Stage(i);
            }
        }
    }
    found
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
/// `db/card_alt_names.json` = 「ルール上、このカードはカード名を「X」としても扱う」 の別名テーブル。
/// 該当カード (16 枚) は自身の名前に加えて別名でも参照される (effects.py:card_names)。
/// ⚠ 「カード名の異なるキャラ」 の **種類数え** では別名を数えない (公式 Q&A)。
/// overlay 読込時 (load_overlay) に同じディレクトリから読む。 未ロードなら別名なし = 自名のみ。
static ALT_NAMES: std::sync::OnceLock<std::collections::HashMap<String, Vec<String>>> =
    std::sync::OnceLock::new();

pub fn load_alt_names(path: &str) {
    let map = std::fs::read_to_string(path)
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .and_then(|v| v.get("alt_names").cloned())
        .and_then(|v| v.as_object().cloned())
        .map(|o| {
            o.into_iter()
                .map(|(k, v)| {
                    let names = v
                        .as_array()
                        .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
                        .unwrap_or_default();
                    (k, names)
                })
                .collect()
        })
        .unwrap_or_default();
    let _ = ALT_NAMES.set(map);
}

fn alt_names(card_id: &str) -> &'static [String] {
    ALT_NAMES
        .get()
        .and_then(|m| m.get(card_id))
        .map(|v| v.as_slice())
        .unwrap_or(&[])
}

/// カード名一致 (別名ルール込み、 表記ゆれは norm_card_name で吸収)。 effects.py:name_matches。
fn name_matches(card: &crate::state::CardDef, target: &str) -> bool {
    let t = norm_card_name(target);
    if norm_card_name(&card.name) == t {
        return true;
    }
    alt_names(&card.card_id).iter().any(|n| norm_card_name(n) == t)
}

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
fn option_score(
    opt: &Value,
    n_opp: usize,
    n_me: usize,
    my_life: usize,
    opp_life: usize,
    opp_hand: usize,
) -> f64 {
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
            // ⚠ 相手の手札が空なら空振り (Python _option_score と同順)。
            "trash_opp_hand_random" | "opp_discard_own_choice" | "force_opp_discard"
            | "opp_hand_to_deck_bottom" => if opp_hand > 0 { 1.2 } else { -0.5 },
            // 相手ライフ削り。 ライフ 0 なら空振り (cardqa_st_20: 空振り選択肢も選べる)。
            "mill_opp_life_to_trash" | "mill_opp_life_to_hand" | "deal_opp_leader_damage" => {
                if opp_life > 0 { 2.0 } else { -0.5 }
            }
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

/// **場に出ている InPlay** に対する filter 判定 (= コストは公式どおり現在値で見る)。
///
/// ⭐ 公式 (ルール 1-3-6-2 + cardqa_op_02): 素の 「コストN以下」 は **効果修正後の現在コスト**。
///   `matches_filter` は `CardDef` しか受け取らないので **印刷コスト固定** で、 場のキャラに
///   対して使うと 「コストを下げてから除去する」 実在ラインが機能しない (Python `_matches_filter_ip` と対)。
///
/// plain な `cost_le/ge/eq` / `cost` を `InPlay::base_cost()` で判定し、 残りは `matches_filter` に委譲。
/// 「元々のコスト」 は `truly_original_cost_*` (印刷値) なので委譲側でそのまま正しい。
fn matches_filter_ip(ip: &InPlay, filt: Option<&Value>) -> bool {
    let Some(f) = filt.and_then(|x| x.as_object()) else { return true };
    // OR 結合 (or / or_clauses) の各サブ filter も **InPlay = 現在値** で判定する。
    // CardDef 版に丸投げすると OR の中の cost/power だけ印刷値になり、 素の「コストN」裁定が
    // 経路依存で食い違う (P-084「コスト3と4はアタックできない」= 現在コスト、 cardqa)。
    // Python `_matches_filter_ip` と対。
    if f.contains_key("or") || f.contains_key("or_clauses") {
        for or_key in ["or", "or_clauses"] {
            if let Some(subs) = f.get(or_key).and_then(|x| x.as_array()) {
                if !subs.iter().any(|sub| matches_filter_ip(ip, Some(sub))) {
                    return false;
                }
            }
        }
        let mut rest = f.clone();
        rest.remove("or");
        rest.remove("or_clauses");
        if rest.is_empty() {
            return true;
        }
        return matches_filter_ip(ip, Some(&Value::Object(rest)));
    }
    // ⭐ 「元々のパワー」 は **効果で書き換わる** (公式 4-9-2-1 「元々のパワーをある数値に
    //   する効果」)。 CardDef へ丸投げすると印刷値固定になる (cardqa_op_10 / EB01-061 Mr.2:
    //   【アタック時】で元々のパワーが2000以上になったキャラは 「元々2000以下をKO」 の対象外)。
    //   Python `_matches_filter_ip` と同順・同キーで先に判定して strip する。
    const TOP: [&str; 3] = ["truly_original_power_le", "truly_original_power_ge",
                            "truly_original_power_eq"];
    let mut f_owned;
    let mut f = f;
    if TOP.iter().any(|k| f.contains_key(*k)) {
        let top = ip.truly_original_power() as i64;
        let g = |k: &str| f.get(k).and_then(|x| x.as_i64());
        if g("truly_original_power_le").map_or(false, |n| top > n) { return false; }
        if g("truly_original_power_ge").map_or(false, |n| top < n) { return false; }
        if g("truly_original_power_eq").map_or(false, |n| top != n) { return false; }
        f_owned = f.clone();
        for k in TOP { f_owned.remove(k); }
        f = &f_owned;
    }
    const PLAIN: [&str; 7] = ["cost_le", "cost_ge", "cost_eq", "cost",
                              "power_le", "power_ge", "power_eq"];
    if !PLAIN.iter().any(|k| f.contains_key(*k)) {
        return matches_filter(&ip.card, Some(&Value::Object(f.clone())));
    }
    let cur = ip.base_cost() as i64;
    let gi = |k: &str| f.get(k).and_then(|x| x.as_i64());
    if gi("cost_le").map_or(false, |n| cur > n) { return false; }
    if gi("cost_ge").map_or(false, |n| cur < n) { return false; }
    if gi("cost_eq").map_or(false, |n| cur != n) { return false; }
    if gi("cost").map_or(false, |n| cur != n) { return false; }
    let pw = ip.power() as i64;
    if gi("power_le").map_or(false, |n| pw > n) { return false; }
    if gi("power_ge").map_or(false, |n| pw < n) { return false; }
    if gi("power_eq").map_or(false, |n| pw != n) { return false; }
    let mut rest = f.clone();
    for k in PLAIN { rest.remove(k); }
    matches_filter(&ip.card, Some(&Value::Object(rest)))
}

/// **手札のカード** に対する filter 判定。 素の「コストN以下/以上/ぴったり」は 手札での
/// 現在コスト (= 印字コスト − in_hand_cost_minus) で判定する。 Python `_matches_filter_hand` と対。
/// (cardqa_st_23 ST23-001 ウタ 「手札のこのカードは…コスト-4」 → OP01-047 ロー cost3以下 で
/// 登場可。 印字コスト固定だと弾かれ 公式違反)。 ihm<=0 (= 手札コスト修正なし) では
/// matches_filter と完全一致 = 挙動不変。
fn matches_filter_hand(card: &crate::state::CardDef, filt: Option<&Value>, ihm: i32) -> bool {
    if ihm <= 0 {
        return matches_filter(card, filt);
    }
    let Some(f) = filt.and_then(|x| x.as_object()) else { return true };
    let eff = (card.cost - ihm).max(0) as i64;
    if f.contains_key("or") || f.contains_key("or_clauses") {
        for or_key in ["or", "or_clauses"] {
            if let Some(subs) = f.get(or_key).and_then(|x| x.as_array()) {
                if !subs.iter().any(|sub| matches_filter_hand(card, Some(sub), ihm)) {
                    return false;
                }
            }
        }
        let mut rest = f.clone();
        rest.remove("or");
        rest.remove("or_clauses");
        if rest.is_empty() {
            return true;
        }
        return matches_filter_hand(card, Some(&Value::Object(rest)), ihm);
    }
    const PLAIN: [&str; 4] = ["cost_le", "cost_ge", "cost_eq", "cost"];
    if !PLAIN.iter().any(|k| f.contains_key(*k)) {
        return matches_filter(card, filt);
    }
    let gi = |k: &str| f.get(k).and_then(|x| x.as_i64());
    if gi("cost_le").map_or(false, |n| eff > n) { return false; }
    if gi("cost_ge").map_or(false, |n| eff < n) { return false; }
    if gi("cost_eq").map_or(false, |n| eff != n) { return false; }
    if gi("cost").map_or(false, |n| eff != n) { return false; }
    let mut rest = f.clone();
    for k in PLAIN { rest.remove(k); }
    matches_filter(card, Some(&Value::Object(rest)))
}

/// このターン中の 「キャラ(カード)を登場できない」 系ペナルティで、 効果による登場が
/// 禁止されているか。 公式は 「登場できない」 = 通常プレイも効果登場も一律禁止
/// (cardqa_op_13、 OP13-023 ウタ: 【登場時】で 「元々のコスト5以上を登場できない」 を付与後、
/// 同ターンの【KO時】play_from_hand でコスト5を登場できない = 「いいえ」)。 OP14-020 ミホーク同型。
/// ステージは対象外 (= CHARACTER 限定)、 しきい値は印刷コスト (public 「元々のコスト」)。
fn char_summon_blocked(me: &crate::state::Player, card: &crate::state::CardDef) -> bool {
    if card.category != crate::state::Category::Character {
        return false;
    }
    if me.block_chara_play_until_turn_end {
        return true;
    }
    let thr = me.block_chara_play_cost_ge_threshold;
    thr >= 0 && card.cost >= thr
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
            // ⭐ 公式 「**元々の**コストN以下/以上」 (2026-08-04 追加、 effects.py と対)。
            // 公式は 「コスト」(効果修正後の現在値) と 「元々のコスト」(印刷値) を区別する。
            // CardDef は印刷値しか持たないので、 このキーは常に card.cost で判定する。
            "truly_original_cost_le" => (card.cost as i64) <= v.as_i64().unwrap_or(0),
            "truly_original_cost_ge" => (card.cost as i64) >= v.as_i64().unwrap_or(0),
            "truly_original_cost_eq" => (card.cost as i64) == v.as_i64().unwrap_or(-1),
            "power_le" => (card.power as i64) <= v.as_i64().unwrap_or(0),
            "power_ge" => (card.power as i64) >= v.as_i64().unwrap_or(0),
            // power_eq (overlay 30 箇所)。 未実装だと `_ => return false` に落ち、 filter 付き
            // コスト (discard_hand_with_filter 等) の対象が 0 枚 → **効果ごと不発** になる
            // (ST30-008 / OP16-014、 2026-08-03 直接発火の差分検証で発覚)。
            "power_eq" => (card.power as i64) == v.as_i64().unwrap_or(0),
            "category" => Some(cat_str(&card.category)) == v.as_str(),
            "category_in" => v
                .as_array()
                .map_or(false, |arr| arr.iter().any(|x| x.as_str() == Some(cat_str(&card.category)))),
            // ⚠ 名前照合は **必ず name_matches** を通す (Python の _matches_filter と同じ)。
            //   生文字列比較だと 全角Ｄ / 半角D の表記ゆれ と 別名ルール
            //   (db/card_alt_names.json) を取りこぼす。 overlay 側は全角、 cards.json 由来の
            //   card.name は半角、 という組み合わせが実在し、 exclude_name が効かず
            //   **除外すべきカードを登場させていた** (OP12-056 ガープ、 2026-08-03 発覚)。
            //   影響範囲: name 150 / exclude_name 256 / name_in 22 箇所。
            "exclude_name" => match v {
                Value::String(s) => !name_matches(card, &norm_card_name(s)),
                Value::Array(a) => !a
                    .iter()
                    .filter_map(|x| x.as_str())
                    .any(|x| name_matches(card, &norm_card_name(x))),
                _ => true,
            },
            "name" => v.as_str().map_or(false, |s| name_matches(card, &norm_card_name(s))),
            "name_in" => v.as_array().map_or(false, |arr| {
                arr.iter()
                    .filter_map(|x| x.as_str())
                    .any(|x| name_matches(card, &norm_card_name(x)))
            }),
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
            // card_id: 特定 card_id のみに限定 (OP09-052)。 未実装だと Rust 側で
            // `_ => return false` に落ちて 0 対象 = 効果が不発になる。
            "card_id" => v.as_str().map_or(true, |s| card.card_id == s),
            // name_exclude: exclude_name の表記ゆれ (OP10-058)。 Python は両方を honor する。
            "name_exclude" => v
                .as_str()
                .map_or(true, |s| !name_matches(card, &norm_card_name(s))),
            // feature_or_name: 特徴 か カード名 の いずれか に マッチ (OP08-053/OP12-116)。
            "feature_or_name" => {
                let feat_ok = v
                    .get("feature")
                    .and_then(|x| x.as_str())
                    .map_or(false, |f| card.features.iter().any(|cf| cf == f));
                let name_ok = v
                    .get("name")
                    .and_then(|x| x.as_str())
                    .map_or(false, |n| name_matches(card, &norm_card_name(n)));
                feat_ok || name_ok
            }
            // 「元々のパワー」 = CardDef の印字値 (効果によるバフ / set_base_power を含まない)。
            // Python の _matches_filter も card.power で判定する (effects.py)。
            // ⚠ かつて 「Python は扱わない = pass」 というコメント付きで素通ししていたが 誤り。
            //   素通しすると 「元々のパワー5000以下のキャラをKO」 (EB01-010) が パワー7000 の
            //   キャラも KO できてしまい MISMATCH になる (2026-08-03 全カード差分掃引で発覚)。
            "truly_original_power_ge" => card.power >= v.as_i64().unwrap_or(0) as i32,
            "truly_original_power_le" => card.power <= v.as_i64().unwrap_or(0) as i32,
            "truly_original_power_eq" => card.power == v.as_i64().unwrap_or(0) as i32,
            // Python の _matches_filter が扱わない key は 制限なし (= pass) として素通りする。
            // no_effect / name_in_last_discarded(解決済) 等。 Rust だけ弾くと MISMATCH になる。
            // no_effect = 「元々の効果のないキャラカード」 (overlay 10 箇所、 全て
            // play_from_hand / play_from_trash)。 Python は _matches_filter でなく各
            // 登場 primitive 側で _card_has_no_effect を適用する (effects.py:4898 他)。
            // ⚠ Rust は素通ししており、 効果持ちカードまで登場対象になっていた
            //   (EB02-022 ウソップ / OP02-045 三刀流 鬼斬り 等、 2026-08-03 発覚)。
            "no_effect" => !v.as_bool().unwrap_or(true) || card_has_no_effect(&card.card_id),
            "name_in_last_discarded" => true,
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
            // ⚠ Python は `feature` (target の兄弟キー) を読む (effects.py の feature_filter 変数)。
            //   Rust は overlay に 1 度も存在しない "feature_filter" を読んでおり **死にキー**
            //   だった = 特徴フィルタが効かず全キャラに buff していた (OP02-019 ラクヨウ
            //   「『白ひげ海賊団』を含む特徴を持つキャラすべてを +1000」、 2026-08-03 発覚)。
            let ff = spec
                .get("feature")
                .or_else(|| spec.get("feature_filter"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
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
            // ⭐ 「元々の」 パワー書き換えか (公式 4-9-2-1、 Python effects.py の静的分岐と同則)。
            let is_orig = spec.get("original").and_then(|x| x.as_bool()).unwrap_or(false);
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                ip.base_power_override = Some(if is_orig { ip.base_power_override.filter(|_| ip.base_power_override_is_original).map_or(amount, |c| c.max(amount)) } else { amount });
                ip.base_power_override_is_original = is_orig;
            }
        }
        // 元々のパワーを duration 付きで上書き (effects.py:4673)。 静的 context では duration="static"→base_power_override。
        "set_base_power_timed" => {
            let amount = as_i(spec.get("amount"), 0) as i32;
            let duration = spec.get("duration").and_then(|v| v.as_str()).unwrap_or("turn").to_string();
            let Some(targets) = resolve_target(spec.get("target"), me_idx, opp_idx, src, state) else { return };
            let turn_number = state.turn_number;
            // ⭐ 「元々の」 パワー書き換えか (公式 4-9-2-1)。 overlay の original フラグ。
            let is_orig = spec.get("original").and_then(|x| x.as_bool()).unwrap_or(false);
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                match duration.as_str() {
                    "turn" => {
                        ip.turn_base_power_override = Some(if is_orig { ip.turn_base_power_override.filter(|_| ip.turn_base_power_override_is_original).map_or(amount, |c| c.max(amount)) } else { amount });
                        ip.turn_base_power_override_is_original = is_orig;
                    }
                    "next_self_turn_start" => {
                        ip.next_turn_base_power_override = Some(if is_orig { ip.next_turn_base_power_override.filter(|_| ip.next_turn_base_power_override_is_original).map_or(amount, |c| c.max(amount)) } else { amount });
                        ip.next_turn_base_power_override_is_original = is_orig;
                    }
                    "next_opp_turn_end" | "next_opp_end_phase" => {
                        ip.next_opp_turn_end_base_power_override = Some(if is_orig { ip.next_opp_turn_end_base_power_override.filter(|_| ip.next_opp_turn_end_base_power_override_is_original).map_or(amount, |c| c.max(amount)) } else { amount });
                        ip.next_opp_turn_end_base_power_override_is_original = is_orig;
                        ip.next_opp_turn_end_base_power_override_applier_idx = me_idx as i32;
                        ip.next_opp_turn_end_base_power_override_applied_turn = turn_number;
                    }
                    _ => {
                        ip.base_power_override = Some(if is_orig { ip.base_power_override.filter(|_| ip.base_power_override_is_original).map_or(amount, |c| c.max(amount)) } else { amount });
                        ip.base_power_override_is_original = is_orig;
                    }
                }
            }
        }
        // 「このキャラの元々のパワーは、 選んだキャラと同じパワーになる」 の静的版 (effects.py:4998、
        //   OP14-053 ビスタ等)。 duration="static" が既定 → base_power_override。
        //   ⚠ 以前は execute_effect (動的 context) にしか実装が無く、 ここ (静的 context、
        //   on_attached_don 経由) は catch-all `_ => {}` で黙って no-op していた
        //   (MISMATCH、 2026-08-06 parity sweep で検出)。
        "set_base_power_copy" => {
            let from_spec = spec.get("from_target").cloned()
                .unwrap_or_else(|| Value::String("one_opponent_character_any".into()));
            let to_spec = spec.get("to_target").cloned()
                .unwrap_or_else(|| Value::String("self".into()));
            let duration = spec.get("duration").and_then(|v| v.as_str()).unwrap_or("turn").to_string();
            let Some(from_c) = resolve_target(Some(&from_spec), me_idx, opp_idx, src, state) else { return };
            let Some(&(fp, fs)) = from_c.first() else { return };
            // ⭐ コピー元が 「元々のパワー」 か 現在パワーか (公式の書き分け、 2026-08-11)。
            //   「自分のリーダーの **元々の** パワーと同じ」 = OP14-053 ビスタ のみ from_original:true。
            let copied = {
                let sip = get_ip(&state.players[fp], fs);
                if spec.get("from_original").and_then(|x| x.as_bool()).unwrap_or(false) {
                    sip.truly_original_power()
                } else {
                    sip.power()
                }
            };
            // ⭐ 「元々の」 パワー書き換えか (公式 4-9-2-1、 Python と同じ overlay フラグ)。
            let is_orig_copy = spec.get("original").and_then(|x| x.as_bool()).unwrap_or(false);
            let Some(to_c) = resolve_target(Some(&to_spec), me_idx, opp_idx, src, state) else { return };
            for (pi, sl) in to_c {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                match duration.as_str() {
                    "turn" => {
                        ip.turn_base_power_override = Some(if is_orig_copy { ip.turn_base_power_override.filter(|_| ip.turn_base_power_override_is_original).map_or(copied, |c| c.max(copied)) } else { copied });
                        ip.turn_base_power_override_is_original = is_orig_copy;
                    }
                    "next_self_turn_start" => {
                        ip.next_turn_base_power_override = Some(if is_orig_copy { ip.next_turn_base_power_override.filter(|_| ip.next_turn_base_power_override_is_original).map_or(copied, |c| c.max(copied)) } else { copied });
                        ip.next_turn_base_power_override_is_original = is_orig_copy;
                    }
                    _ => {
                        ip.base_power_override = Some(if is_orig_copy { ip.base_power_override.filter(|_| ip.base_power_override_is_original).map_or(copied, |c| c.max(copied)) } else { copied });
                        ip.base_power_override_is_original = is_orig_copy;
                    }
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
                if !matches_filter_ip(&state.players[pool].characters[i], filt) {
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
        // --- 2026-08-02 追加: Python の evaluate_static_effects にあって Rust に無かった 15 種。
        //     未実装だと **黙って効果が消える** (静的フラグは digest に載るので本来 MISMATCH)。
        // 「自分の特徴《SWORD》キャラは登場ターンにキャラへアタックできる」 (effects.py:6851、 OP11-001)。
        "static_swords_attack_chara" => {
            for ip in state.players[me_idx].characters.iter_mut() {
                if ip.card.features.iter().any(|f| f == "SWORD") {
                    ip.granted_keywords.insert("速攻：キャラ".to_string());
                }
            }
        }
        // 「(条件) の場合、 **このキャラ** は登場したターンにキャラへアタックできる」
        // (EB02-019 ロロノア・ゾロ 「相手のキャラが2枚以上いる場合、…」、 effects.py:7615)。
        // ⭐ 条件は recompute_static ごとに再評価 = **アタック時点** で判定 (cardqa_eb_02:
        //   登場時 2 枚 → 後に 1 枚 になったら 「いいえ、 できません」)。 その為 granted_keywords
        //   ではなく **static_granted_keywords** に入れる (= 毎回クリアされ条件が外れたら消える)。
        "static_self_attack_chara_if" => {
            let ok = eval_condition(spec, state, me_idx, Some(src)).unwrap_or(false);
            if ok {
                get_ip_mut(&mut state.players[me_idx], src)
                    .static_granted_keywords
                    .insert("速攻：キャラ".to_string());
            }
        }
        // 「相手はこのキャラを狙わなければならない」 (effects.py:10970)。
        "set_attack_taunt" => {
            let tspec = if spec.is_string() { spec.clone() } else { Value::String("self".into()) };
            if let Some(ts) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) {
                for (pi, sl) in ts {
                    get_ip_mut(&mut state.players[pi], sl).attack_taunt = true;
                }
            }
        }
        // 「このキャラは、 相手のアクティブのキャラにもアタックできる」 (effects.py:7367)。
        // = "アクティブアタック可" キーワード付与。 【ドン‼×N】 の静的効果なので
        // evaluate_static_effects 経由で毎回付け直す。
        // ⚠ 非静的側 (execute_effect) には実装済みだったが apply_static_primitive に無く、
        //   OP01-021 フランキー 等の 【ドン‼×1】 版が Rust だけ無効だった (2026-08-03 発覚)。
        "give_attack_active_chara" => {
            let tspec = if spec.is_string() { spec.clone() } else { Value::String("self".into()) };
            if let Some(ts) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) {
                for (pi, sl) in ts {
                    get_ip_mut(&mut state.players[pi], sl)
                        .granted_keywords
                        .insert("アクティブアタック可".to_string());
                }
            }
        }
        // 「相手はキャラの『X』以外にアタックできない」 (effects.py:10979)。 自陣の name 一致に taunt。
        "cannot_attack_target_except" => {
            let name = if spec.is_object() {
                spec.get("name").and_then(|x| x.as_str()).unwrap_or("").to_string()
            } else {
                spec.as_str().unwrap_or("").to_string()
            };
            for c in state.players[me_idx].characters.iter_mut() {
                if name_matches(&c.card, &name) {
                    c.attack_taunt = true;
                }
            }
        }
        // 速攻の静的付与 (effects.py:11099)。 static_granted_keywords へ (ドンが外れれば消える)。
        "give_rush" => {
            let tspec = if spec.is_string() { spec.clone() } else { Value::String("self".into()) };
            if let Some(ts) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) {
                for (pi, sl) in ts {
                    get_ip_mut(&mut state.players[pi], sl)
                        .static_granted_keywords
                        .insert("速攻".to_string());
                }
            }
        }
        // 「バトルで KO されない」 静的 (effects.py:10931 / 11049)。
        "set_battle_ko_immune" | "set_ko_immune_battle_only" => {
            let tspec = if spec.is_object() {
                spec.get("target").cloned().unwrap_or(Value::String("self".into()))
            } else if spec.is_string() {
                spec.clone()
            } else {
                Value::String("self".into())
            };
            if let Some(ts) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) {
                for (pi, sl) in ts {
                    get_ip_mut(&mut state.players[pi], sl).battle_ko_immune_static = true;
                }
            }
        }
        // 「リーダーとのバトルでは KO されない」 (effects.py:10920)。
        "set_battle_ko_immune_vs_leader" => {
            let tspec = if spec.is_object() {
                spec.get("target").cloned().unwrap_or(Value::String("self".into()))
            } else {
                Value::String("self".into())
            };
            if let Some(ts) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) {
                for (pi, sl) in ts {
                    get_ip_mut(&mut state.players[pi], sl).battle_ko_immune_vs_leader = true;
                }
            }
        }
        // 「属性 X とのバトル中 +N」 (effects.py:10911)。
        "set_battle_pump_vs_attribute" => {
            let attr = spec.get("attribute").and_then(|x| x.as_str()).unwrap_or("").to_string();
            let amount = spec.get("amount").and_then(|x| x.as_i64()).unwrap_or(0) as i32;
            let tspec = spec.get("target").cloned().unwrap_or(Value::String("self".into()));
            if attr.is_empty() {
                return;
            }
            if let Some(ts) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) {
                for (pi, sl) in ts {
                    get_ip_mut(&mut state.players[pi], sl)
                        .battle_pump_vs_attribute
                        .insert(attr.clone(), amount);
                }
            }
        }
        // 「属性 X (を持たないカード) とのバトルで KO されない」 (effects.py:11061)。
        "set_immune_attribute_in_battle" => {
            let (tspec, attrs, negate) = if spec.is_object() {
                let a = match spec.get("attributes") {
                    Some(Value::Array(arr)) => {
                        arr.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect()
                    }
                    Some(Value::String(s2)) => vec![s2.clone()],
                    _ => vec![],
                };
                (
                    spec.get("target").cloned().unwrap_or(Value::String("self".into())),
                    a,
                    spec.get("negate").and_then(|x| x.as_bool()).unwrap_or(false),
                )
            } else {
                (
                    Value::String("self".into()),
                    vec![spec.as_str().unwrap_or("").to_string()],
                    false,
                )
            };
            if let Some(ts) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) {
                for (pi, sl) in ts {
                    let ip = get_ip_mut(&mut state.players[pi], sl);
                    for a in &attrs {
                        if negate {
                            ip.ko_immune_battle_attributes_not_in.insert(a.clone());
                        } else {
                            ip.ko_immune_battle_attributes_in.insert(a.clone());
                        }
                    }
                }
            }
        }
        // 「属性 X を持たないカードの効果で KO されない」 (effects.py:10943)。
        "set_ko_immune_from_non_attribute" => {
            let attr = if spec.is_object() {
                spec.get("attribute").and_then(|x| x.as_str()).unwrap_or("").to_string()
            } else {
                spec.as_str().unwrap_or("").to_string()
            };
            let tspec = if spec.is_object() {
                spec.get("target").cloned().unwrap_or(Value::String("self".into()))
            } else {
                Value::String("self".into())
            };
            if let Some(ts) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) {
                for (pi, sl) in ts {
                    get_ip_mut(&mut state.players[pi], sl).static_ko_immune_from_non_attribute =
                        attr.clone();
                }
            }
        }
        // 「元々のパワー N 以下のカードの効果で KO されない」 (effects.py:10950)。
        "set_ko_immune_from_source_power_le" => {
            let thr = spec.get("threshold").and_then(|x| x.as_i64()).unwrap_or(0) as i32;
            let tspec = spec.get("target").cloned().unwrap_or(Value::String("self".into()));
            if let Some(ts) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) {
                for (pi, sl) in ts {
                    get_ip_mut(&mut state.players[pi], sl).static_ko_immune_from_source_power_le = thr;
                }
            }
        }
        // KO 耐性 (期限付き、 effects.py:7287 set_ko_immune_timed)。 duration="next_opp_turn_end" →
        //   ko_immune_through_opp_turn / それ以外 (既定 "turn") → ko_immune_until_turn_end。
        //   ⚠ execute_effect (動的) には既に実装済だったが、 静的 context (on_attached_don 経由、
        //   ST14-009 ビッグ・マム海賊団) はここに無く catch-all `_ => {}` で無反応だった
        //   (set_base_power_copy と同型の穴、 2026-08-06)。
        "set_ko_immune_timed" => {
            let duration = spec.get("duration").and_then(|x| x.as_str()).unwrap_or("next_opp_turn_end").to_string();
            if let Some(ts) = resolve_target(spec.get("target"), me_idx, opp_idx, src, state) {
                for (pi, sl) in ts {
                    let ip = get_ip_mut(&mut state.players[pi], sl);
                    if duration == "next_opp_turn_end" {
                        ip.ko_immune_through_opp_turn = true;
                    } else {
                        ip.ko_immune_until_turn_end = true;
                    }
                }
            }
        }
        // 「(filter) キャラはアタックできない」 (effects.py:10996)。 scope = self|opp|both。
        "set_cannot_attack_filtered_static" => {
            let filt = spec.get("filter").cloned();
            let scope = spec.get("scope").and_then(|x| x.as_str()).unwrap_or("both").to_string();
            if scope == "self" || scope == "both" {
                for c in state.players[me_idx].characters.iter_mut() {
                    if matches_filter_ip(&c, filt.as_ref()) {
                        c.cannot_attack_static = true;
                    }
                }
            }
            if scope == "opp" || scope == "both" {
                for c in state.players[opp_idx].characters.iter_mut() {
                    if matches_filter_ip(&c, filt.as_ref()) {
                        c.cannot_attack_static = true;
                    }
                }
            }
        }
        // 「(exclude_filter に該当しない) 自キャラは効果無効」 (effects.py:11009)。
        "set_effect_negate_filtered_static" => {
            let excl = spec.get("exclude_filter").cloned();
            for c in state.players[me_idx].characters.iter_mut() {
                if !matches_filter_ip(&c, excl.as_ref()) {
                    c.static_granted_keywords.insert("効果無効".to_string());
                }
            }
        }
        // 「(filter) カードの登場コストが N 少ない」 静的 (effects.py:11079)。
        "reduce_play_cost_filtered_static" => {
            let entry = json!({
                "filter": spec.get("filter").cloned().unwrap_or(json!({})),
                "amount": spec.get("amount").and_then(|x| x.as_i64()).unwrap_or(1),
            });
            state.players[me_idx].play_cost_reductions_filtered.push(entry);
        }
        // 「デッキ切れで勝つ」 (effects.py:10993)。
        "set_deck_out_wins" => {
            state.players[me_idx].deck_out_wins = true;
        }
        // 公式 (OP15-022 ブルック リーダー): 「ルール上、 自分はデッキが0枚でも敗北せず、
        // デッキが0枚になったターン終了時に敗北する」 (effects.py:set_deck_out_defer)。
        "set_deck_out_defer" => {
            state.players[me_idx].deck_out_defer = true;
        }
        // 「手札の (filter) カードのカウンター +N」 静的 (effects.py:11138、 OP16-118)。
        "set_hand_counter_boost" => {
            state.players[me_idx].hand_counter_boost = Some(spec.clone());
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
        // 公式: 「レストにできない」 状態では レストを要するコストを払えない。
        "rest_self" => Some(src_ip(me, src).map_or(false, |ip| {
            !ip.rested && !ip.cannot_be_rested_buff && !ip.static_cannot_be_rested
        })),
        "rest_self_target_name" | "rest_self_target" => {
            let name = cv.get("name").and_then(|x| x.as_str()).unwrap_or_else(|| cv.as_str().unwrap_or(""));
            Some(me.characters.iter().chain(me.stages.iter()).any(|ip| name_matches(&ip.card, name) && !ip.rested))
        }
        "rest_self_leader_or_stage_filtered" => {
            let filt = cv.get("filter");
            Some((!me.leader.rested && matches_filter_ip(&me.leader, filt))
                || me.stages.iter().any(|s| !s.rested && matches_filter_ip(&s, filt)))
        }
        // Python は can_pay 未チェック (= 常に払える扱い、 実体無ければ payment で no-op)。
        // 「自分の、属性X を持つリーダー **か** ドン‼1枚をレストにできる：」 (ST32-001 錦えもん)。
        // ⚠ Python (effects.py:8722) は **アクティブな filter 一致リーダー OR アクティブドン≥1**
        //   でなければ払えない。 無条件 Some(true) にしていたため、 リーダーがレスト済 かつ
        //   ドン 0 (= 登場コストで使い切った) の局面で **Rust だけ効果をタダ撃ちしていた**
        //   (draw 2 + 手札1捨てが発動、 2026-08-04 の全カード掃引で発覚)。
        "rest_self_leader_filtered_or_don" => {
            let filt = cv.get("filter");
            let leader_ok = !me.leader.rested && matches_filter_ip(&me.leader, filt);
            Some(leader_ok || me.don_active >= 1)
        }
        // 「自分の『X』1枚にアクティブのドンN枚を付与できる：」 (EB04-009/OP12-016/019 レイリー等)。
        // Python (effects.py:8688) は **該当名のキャラが場に居て かつ アクティブドンが N 枚以上**
        // でなければ払えない。 ⚠ かつて無条件 Some(true) としていたため、 払えない盤面でも
        // Rust だけ効果が発動していた (EB04-009 で -2000 が乗る MISMATCH、 2026-08-03 発覚)。
        // ⚠ Python は card.name の完全一致で見る (name_matches の別名展開は使わない)。
        "attach_active_don_to_named_chara" => {
            let name = cv.get("name").and_then(|x| x.as_str()).unwrap_or("");
            let n = cv.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32;
            let me = &state.players[me_idx];
            Some(me.don_active >= n && me.characters.iter().any(|c| c.card.name == name))
        }
        // flip_life は payability あり (effects.py:8515)。 face_up: 裏向きライフ≥1、 face_down: 表向き≥1。
        "flip_life_face_up" => {
            let fu = me.face_up_life_count.min(me.life.len() as i32);
            Some((me.life.len() as i32) - fu >= 1)
        }
        "flip_life_face_down" => Some(me.face_up_life_count.min(me.life.len() as i32) >= 1),
        "rest_self_chara_filtered" => {
            let filt = cv.get("filter");
            Some(me.characters.iter().any(|c| !c.rested && matches_filter_ip(&c, filt)))
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
        // rest_own_card: 自分のアクティブなカード N 枚をレスト (Python effects.py の
        // payability と対)。 リーダー + キャラ + ステージ から filter 一致の **アクティブ** を数える。
        // ⚠ 「レストにできない」 は レストを要するコストも払えなくする (公式、 2026-08-04)。
        "rest_own_card" => {
            let (n, filt) = count_and_filter(cv);
            let mut cnt = 0usize;
            if !me.leader.rested && matches_filter_ip(&me.leader, filt)
                && !me.leader.cannot_be_rested_buff && !me.leader.static_cannot_be_rested { cnt += 1; }
            for c in me.characters.iter().chain(me.stages.iter()) {
                if !c.rested && matches_filter_ip(c, filt)
                    && !c.cannot_be_rested_buff && !c.static_cannot_be_rested { cnt += 1; }
            }
            Some(cnt >= n)
        }
        "return_self_chara_to_hand" => {
            let (count, filt) = count_and_filter(cv);
            Some(me.characters.iter().filter(|c| matches_filter_ip(&c, filt)).count() >= count)
        }
        // ⭐ targeted-removal を **コスト** に持つ形 (OP04-055 疫災弾:
        //   「コスト4以下のキャラ1枚を、持ち主のデッキの下に置くことができる：…」)。
        //   対象が 1 枚も居なければ払えない。 一次情報 (cardqa_st_06):
        //   「"発動コスト" はその一部のみを支払うことはできません。 …一部あるいは全部が
        //    支払えない場合、 その効果を発動することができません。」
        //   Python `optional_cost_then` の payability と対 (2026-08-05 是正)。
        "return_to_deck_bottom" => {
            let opp_idx = 1 - me_idx;
            Some(resolve_target(Some(cv), me_idx, opp_idx, src, state)
                .map_or(false, |t| !t.is_empty()))
        }
        // trash_self_named_hand_or_field cost: 手札か自ステージに該当名が必要 (effects.py:8464、 OP06-033)。
        "trash_self_named_hand_or_field" => {
            let name = if cv.is_object() {
                cv.get("name").and_then(|x| x.as_str()).unwrap_or("").to_string()
            } else {
                cv.as_str().unwrap_or("").to_string()
            };
            Some(
                me.stages.iter().any(|s| name_matches(&s.card, &name))
                    || me.hand.iter().any(|c| name_matches(c, &name)),
            )
        }
        // discard_hand cost: 手札 ≥ n 必要。
        "discard_hand" => Some((me.hand.len() as i64) >= cv.as_i64().unwrap_or(0)),
        // return_to_hand: other_self_chara cost = このキャラ以外の自キャラが1体以上 (effects.py:8321)。
        "return_to_hand" if cv.as_str() == Some("other_self_chara") => {
            let src_idx = if let Slot::Char(i) = src { Some(i) } else { None };
            Some((0..me.characters.len()).any(|i| Some(i) != src_idx))
        }
        // power_pump cost = 自リーダー/自身を弱体化して払う (effects.py:8407、 EB03-006 ナミ系)。
        // Python は target=self_leader なら常に払える扱い。 target=self で source-gone かつ
        // 自キャラも居ない場合のみ不可。
        "power_pump" => {
            let tgt = cv.get("target").and_then(|x| x.as_str()).unwrap_or("self");
            let amt = cv.get("amount").and_then(|x| x.as_i64()).unwrap_or(0);
            if amt < 0 && tgt == "self" && me.characters.is_empty() && src_ip(me, src).is_none() {
                Some(false)
            } else {
                Some(true)
            }
        }
        // return_self_don_to_deck cost = 場のドン (active+rested) が N 枚以上 (effects.py:8400)。
        "return_self_don_to_deck" => {
            let n = if cv.is_object() {
                cv.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                cv.as_i64().unwrap_or(1)
            };
            Some((me.don_active + me.don_rested) as i64 >= n)
        }
        // return_self_to_hand / return_self_to_trash cost = 自身が場のキャラである必要 (effects.py:8379)。
        "return_self_to_hand" | "return_self_to_trash" => {
            Some(matches!(src, Slot::Char(i) if i < me.characters.len()))
        }
        // return_self_to_deck_bottom cost = 自身が場 (キャラ or ステージ) に居る必要 (effects.py:8394)。
        "return_self_to_deck_bottom" => Some(matches!(src, Slot::Char(_) | Slot::Stage(_))),
        // Python が payability を判定するキー (effects.py:8340 以降の elif 連鎖)。 ここに載っている
        // キーは **Rust も同じ判定をしないと「Python は払えないのに Rust は払う」divergence** になる。
        // ⚠ 以前ここを「未知キーは払える」既定にしたが、 それだと下記キーで判定が食い違う。
        "chara_to_self_life" => {
            let filt = cv.get("target").and_then(|t| t.get("filter"));
            Some(me.characters.iter().any(|c| matches_filter_ip(&c, filt)))
        }
        "ko_self_chara" => {
            let (n, filt, excl) = if cv.is_object() {
                (cv.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize,
                 cv.get("filter"),
                 cv.get("exclude_self").and_then(|x| x.as_bool()).unwrap_or(false))
            } else {
                (cv.as_i64().unwrap_or(1) as usize, None, false)
            };
            let src_idx = if let Slot::Char(i) = src { Some(i) } else { None };
            // 効果でKOされないキャラ (フクロウ OP03-088 等) は 自KOコストの弾にできない
            // (公式 cardqa_op_05)。 通常の ko primitive と同じ免疫則 (Python effects.py 参照)。
            let cnt = (0..me.characters.len())
                .filter(|&i| {
                    let c = &me.characters[i];
                    matches_filter_ip(c, filt)
                        && !(excl && Some(i) == src_idx)
                        && !(c.static_ko_immune || c.ko_immune_until_turn_end
                             || c.ko_immune_through_opp_turn)
                })
                .count();
            Some(cnt >= n)
        }
        "trash_to_deck" => {
            let (limit, filt) = if cv.is_object() {
                (cv.get("limit").and_then(|x| x.as_i64()).unwrap_or(1) as usize, cv.get("filter"))
            } else {
                (cv.as_i64().unwrap_or(1) as usize, None)
            };
            Some(me.trash.iter().filter(|c| matches_filter(c, filt)).count() >= limit)
        }
        "return_self_chara_to_deck_bottom" => {
            let (n, filt) = if cv.is_object() {
                (cv.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize, cv.get("filter"))
            } else {
                (cv.as_i64().unwrap_or(1) as usize, None)
            };
            // 公式 「**このキャラ以外**の自分のキャラ1枚を…できる」 (OP05-056)。
            // 発動元を除外しないと、 他に自キャラが居ない盤面でも払えてしまう。
            let _ex = cv.get("except_self").and_then(|x| x.as_bool()).unwrap_or(false);
            let _si = if let Slot::Char(i) = src { Some(i) } else { None };
            Some(me.characters.iter().enumerate()
                .filter(|(i, c)| matches_filter_ip(c, filt)
                        && !(_ex && Some(*i) == _si))
                .count() >= n)
        }
        // ⚠ Python (effects.py:8637) は **filter 一致** の枚数で払えるか見る。 count だけ見ると
        //   「コスト1のステージ」 指定を無視して 別コストのステージで払えると誤判定する (OP06-102)。
        "stage_to_deck_bottom" => {
            let (n, filt, either) = stage_count_and_filter(cv);
            let mut cnt = me.stages.iter().filter(|s| matches_filter_ip(s, filt.as_ref())).count();
            if either {
                cnt += state.players[1 - me_idx]
                    .stages
                    .iter()
                    .filter(|s| matches_filter_ip(s, filt.as_ref()))
                    .count();
            }
            Some(cnt >= n)
        }
        "attach_opp_don_to_opp_chara" => {
            let (n, from_cost) = if cv.is_object() {
                (cv.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32,
                 cv.get("from_cost_area").and_then(|x| x.as_bool()).unwrap_or(false))
            } else {
                (cv.as_i64().unwrap_or(1) as i32, false)
            };
            let opp = &state.players[1 - me_idx];
            let avail = opp.don_rested + if from_cost { opp.don_active } else { 0 };
            Some(!opp.characters.is_empty() && avail >= n)
        }
        // 「自分の(filter)カード N 枚をレストにできる」 (effects.py の rest_self_cards payability)。
        // ⚠ 2026-08-05 まで **両エンジンとも** payability を見ておらず、 レストにできる自カードが
        //   0 でも効果が発火していた (= overlay 共通のため差分検証では沈黙するクラス)。
        "rest_self_cards" | "rest_self_cards_filtered" => {
            let (n, filt) = count_and_filter(cv);
            let mut cnt = 0usize;
            if !me.leader.rested
                && matches_filter_ip(&me.leader, filt)
                && !me.leader.cannot_be_rested_buff
                && !me.leader.static_cannot_be_rested
            {
                cnt += 1;
            }
            for c in me.characters.iter().chain(me.stages.iter()) {
                if !c.rested
                    && matches_filter_ip(c, filt)
                    && !c.cannot_be_rested_buff
                    && !c.static_cannot_be_rested
                {
                    cnt += 1;
                }
            }
            // 公式 cardqa_op_14 (OP14-029 たしぎ): 「自分のカード N 枚」 = リーダー/キャラ/
            // **ステージ/ドン‼** の 4 ゾーン合計。 ドンは特徴を持たないので filter 無し
            // (= rest_self_cards、 rest_self_cards_filtered ではない) の時だけ頭数に入る。
            if k == "rest_self_cards" && filt.map_or(true, |f| f.as_object().map_or(true, |o| o.is_empty())) {
                cnt += me.don_active.max(0) as usize;
            }
            Some(cnt >= n)
        }
        "mill_self_top" => {
            let n = if cv.is_object() {
                cv.get("amount").or_else(|| cv.get("count")).and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                cv.as_i64().unwrap_or(1)
            } as usize;
            Some(me.deck.len() >= n)
        }
        "hand_to_deck_bottom" => {
            let n = if cv.is_object() {
                cv.get("count").or_else(|| cv.get("amount")).and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                cv.as_i64().unwrap_or(1)
            } as usize;
            Some(me.hand.len() >= n)
        }
        // 「自分の手札から『X』1枚を、登場できる：効果」 (OP05-111 ホトリ)。
        "play_from_hand_named_set" => {
            let names: Vec<&str> = cv
                .get("names")
                .and_then(|x| x.as_array())
                .map(|a| a.iter().filter_map(|v| v.as_str()).collect())
                .unwrap_or_default();
            let n = cv.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            Some(me.hand.iter().filter(|c| names.contains(&c.name.as_str())).count() >= n)
        }
        // 「このキャラの付与ドン‼を…コストエリアにレストで戻すことができる」 (ST28-004)。
        "return_attached_don_to_cost_rested" => {
            let n = if cv.is_object() {
                cv.get("count").or_else(|| cv.get("amount")).and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                cv.as_i64().unwrap_or(1)
            } as i32;
            let cur = match src {
                Slot::Leader => me.leader.attached_dons,
                Slot::Char(i) => me.characters.get(i).map(|c| c.attached_dons).unwrap_or(0),
                Slot::Stage(i) => me.stages.get(i).map(|c| c.attached_dons).unwrap_or(0),
                // 発動元が場を離れている。 Python の self_inplay は場外でも生きたオブジェクトを
                // 読むので 0 と決め打つと乖離しうる → **bail** (黙って間違えない)。
                Slot::Detached => return None,
            };
            Some(cur >= n)
        }
        // ここに無いキーは Python も payability を見ていない = 「払える」扱いで primitive に委譲。
        _ => {
            note_unknown_key("optional_cost", k);
            Some(true)
        }
    }
}

/// fire_self_effect の再帰深度 (Python の state._fire_self_depth 相当、 canonical ではない)。
static FIRE_SELF_DEPTH: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// fire_self_effect の再帰深度を抜ける時に必ず戻す (途中 return が多いので RAII)。
struct FireSelfGuard(usize);
impl Drop for FireSelfGuard {
    fn drop(&mut self) {
        FIRE_SELF_DEPTH.store(self.0, std::sync::atomic::Ordering::Relaxed);
    }
}


/// 未対応キーの内訳を記録 (診断時のみ)。 cat = "optional_cost" / "on_play_cost" / "activate_cost" 等。
/// 「cost 未対応」 としか出ないと どの支払い種別が足りないか分からないので、 条件と同じ粒度で残す。
pub(crate) fn note_unknown_key(cat: &str, key: &str) {
    if !crate::selfplay::DIAG_ON.load(std::sync::atomic::Ordering::Relaxed) {
        return;
    }
    if let Ok(mut m) = crate::selfplay::UNKNOWN_CONDS.lock() {
        *m.entry(format!("[{cat}] {key}")).or_insert(0) += 1;
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

/// `stage_to_deck_bottom` の spec を (枚数, filter) に分解する。
/// ⚠ この cost だけ **filter が兄弟キーとして直に書かれる** 形式で、 Python は
///   `{k: v for k, v in spec.items() if k != "count"}` を filter にしている
///   (effects.py:8633/9034)。 spec が数値なら count のみ・filter なし。
/// 戻り値の 3 番目 = side が "either" (= 両陣営) か。 既定 "self"。
/// ⚠ 公式は **コスト節でも** 「自分の」/「相手の」/(修飾なし) を書き分ける (Python 側コメント参照)。
fn stage_count_and_filter(cv: &Value) -> (usize, Option<Value>, bool) {
    if let Some(o) = cv.as_object() {
        let count = o.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
        let either = o.get("side").and_then(|x| x.as_str()) == Some("either");
        let filt: serde_json::Map<String, Value> = o
            .iter()
            .filter(|(k, _)| k.as_str() != "count" && k.as_str() != "side")
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        (count, if filt.is_empty() { None } else { Some(Value::Object(filt)) }, either)
    } else {
        (cv.as_i64().unwrap_or(1) as usize, None, false)
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
            // ⚠ Python は optional_cost_then の cost も **execute_effect 経由** (effects.py:9155) で
            //   払うので、 pay_don primitive の
            //   `trigger_on_self_don_returned_to_deck` が必ず発火する。 Rust は pay_cost_one が
            //   独自に払っていて この cascade を落としていた (OP06-075 の ドン-1 で相手場の
            //   OP06-076 人斬り鎌ぞうが発動せず、 2026-08-04 掃引 MISMATCH)。
            //   pay_don_field が last_returned_don_count を set 済。
            if n > 0 && me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
                enqueue_field_when(state, me_idx, "on_self_don_returned_to_deck");
                maybe_resolve(state).ok()?;
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
                // effects.py:882 — self_inplay が居なければ何もしない (= 支払い成功扱い)。
                // ⚠ 以前は None (= bail) を返していたが Python は skip するだけ。
                if let Some(ip) = src_ip_mut(&mut state.players[me_idx], src) {
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
                if name_matches(&me.characters[i].card, &name) && !me.characters[i].rested {
                    me.characters[i].rested = true;
                    done = true;
                    break;
                }
            }
            if !done {
                for i in 0..me.stages.len() {
                    if name_matches(&me.stages[i].card, &name) && !me.stages[i].rested {
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
                if !me.leader.rested && matches_filter_ip(&me.leader, filt) {
                    avail.push((Slot::Leader, false));
                }
                for i in 0..me.stages.len() {
                    if !me.stages[i].rested && matches_filter_ip(&me.stages[i], filt) {
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
            } else if !me.leader.rested && matches_filter_ip(&me.leader, filt) {
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
                    if !me.characters[i].rested && matches_filter_ip(&me.characters[i], filt) {
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
            // ⚠ Python (effects.py:8804) は card.name の **完全一致**。 name_matches で別名を
            //   展開すると payability (完全一致) と支払いで対象が食い違う。
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
            let mut names: Vec<String> = vec![];
            for c in old {
                if discarded < count && matches_filter(&c, Some(&filt)) {
                    names.push(c.name.clone());
                    me.trash.push(c);
                    discarded += 1;
                } else {
                    me.hand.push(c);
                }
            }
            // EB02-039 の name_in_last_discarded 用に記録 (effects.py:8877)。
            state.last_discarded_names = names;
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
        // ⚠ return_self_don_to_deck の専用アームは **置かない**。
        //   Python は同じコストに 3 実装を持ち 順序が違う:
        //     _pay_counter_cost (on_attack/counter)      … rested 優先 (2026-07-17 の意図的変更)
        //     primitive (optional_cost_then から呼ばれる) … active 優先
        //     置換効果コスト                              … active 優先
        //   pay_cost_one は optional_cost_then 用なので、 Python 同様 **primitive に委譲**して
        //   active 優先にする。 かつてここに rested 優先を置いており OP09-070 等で MISMATCH
        //   (付与できるレストドン数が変わり attach_rested_don の結果がズレる、 2026-08-03 発覚)。
        // return_self_to_trash cost: 発動元自身をトラッシュへ (effects.py:8433)。 付与ドンはレストへ。
        "return_self_to_trash" => {
            match src {
                Slot::Char(i) if i < state.players[me_idx].characters.len() => {
                let ip = state.players[me_idx].characters.remove(i);
                    let don = ip.attached_dons;
                    state.players[me_idx].trash.push(ip.card);
                    state.players[me_idx].don_rested += don;
                }
                Slot::Stage(i) if i < state.players[me_idx].stages.len() => {
                    let ip = state.players[me_idx].stages.remove(i);
                    let don = ip.attached_dons;
                    state.players[me_idx].trash.push(ip.card);
                    state.players[me_idx].don_rested += don;
                }
                _ => {}
            }
        }
        // 「このカードを持ち主のデッキの下に置く」 cost (effects.py:8776)。 付与ドンはレストへ。
        "return_self_to_deck_bottom" => {
            match src {
                Slot::Char(i) if i < state.players[me_idx].characters.len() => {
                let ip = state.players[me_idx].characters.remove(i);
                    let don = ip.attached_dons;
                    state.players[me_idx].deck.push(ip.card);
                    state.players[me_idx].don_rested += don;
                }
                Slot::Stage(i) if i < state.players[me_idx].stages.len() => {
                    let ip = state.players[me_idx].stages.remove(i);
                    let don = ip.attached_dons;
                    state.players[me_idx].deck.push(ip.card);
                    state.players[me_idx].don_rested += don;
                }
                _ => {}
            }
        }
        // 「自分の(コスト N の)ステージ 1 枚を持ち主のデッキの下に置く」 cost (effects.py:9028)。
        // Python は **stage の並び順 (最古順)** に filter 一致を先頭から count 枚。 sort しない。
        // 付与ドンは公式 6-5-5-4 と同じくレストでコストエリアへ (Python 同順)。
        // ⚠ これが未実装で OP06-102 カマキリの起動メインが bail していた (2026-08-04)。
        "stage_to_deck_bottom" => {
            let (count, filt, either) = stage_count_and_filter(&cv);
            // side="either" は **相手側を先に** 走査 (Python の sb_owners と同順)。
            // 持ち主のデッキに戻すので append 先は各 owner の deck。
            let order: Vec<usize> = if either {
                vec![1 - me_idx, me_idx]
            } else {
                vec![me_idx]
            };
            let mut moved = 0usize;
            for pi in order {
                if moved >= count {
                    break;
                }
                let pl = &mut state.players[pi];
                let stages = std::mem::take(&mut pl.stages);
                for s in stages {
                    if moved < count && matches_filter_ip(&s, filt.as_ref()) {
                        let don = s.attached_dons;
                        pl.deck.push(s.card);
                        pl.don_rested += don;
                        moved += 1;
                    } else {
                        pl.stages.push(s);
                    }
                }
            }
        }
        // 「自分のキャラ N 枚を持ち主のデッキの下に置く」 cost (effects.py:8967)。
        // AI は power 昇順 (= 最も惜しくない) から。 deck append 順 = 元 character 順。
        "return_self_chara_to_deck_bottom" => {
            let (count, filt) = count_and_filter(&cv);
            let _ex = cv.get("except_self").and_then(|x| x.as_bool()).unwrap_or(false);
            let _si = if let Slot::Char(i) = src { Some(i) } else { None };
            let mut cands: Vec<(usize, i32)> = state.players[me_idx]
                .characters
                .iter()
                .enumerate()
                .filter(|(i, c)| matches_filter_ip(c, filt) && !(_ex && Some(*i) == _si))
                .map(|(i, c)| (i, c.power()))
                .collect();
            cands.sort_by(|a, b| a.1.cmp(&b.1));
            let chosen: std::collections::HashSet<usize> =
                cands.iter().take(count).map(|(i, _)| *i).collect();
            let me = &mut state.players[me_idx];
            let old = std::mem::take(&mut me.characters);
            for (i, c) in old.into_iter().enumerate() {
                if chosen.contains(&i) {
                    let don = c.attached_dons;
                    me.deck.push(c.card);
                    if don > 0 {
                        me.don_rested += don;
                    }
                } else {
                    me.characters.push(c);
                }
            }
            // ⚠ 「自分の効果で自分のキャラが場を離れた」 = leave-by-self トリガーの対象
            //   (公式 cardqa_op_16 / OP16-041 バギー: 虜の矢のコストで自キャラが手札に
            //    戻った時も 「場を離れた時」 効果は発動する)。 任意コストの離脱 3 経路とも
            //   発火が抜けていた (2026-08-10 是正、 Python effects.py と同位置)。
            if fire_leave_by_self_effect(state, me_idx).is_err() {
                return None;
            }
        }
        // rest_own_card: AI は 非リーダー + power 昇順 (= リーダー/高power を温存、
        // effects.py:13720 と同順)。 直接 rested = cascade 無し。
        "rest_own_card" => {
            let (n, filt) = count_and_filter(&cv);
            let mut pool: Vec<(bool, i32, Slot)> = vec![];
            {
                let me = &state.players[me_idx];
                if !me.leader.rested && matches_filter_ip(&me.leader, filt)
                    && !me.leader.cannot_be_rested_buff && !me.leader.static_cannot_be_rested {
                    pool.push((true, me.leader.power(), Slot::Leader));
                }
                for i in 0..me.characters.len() {
                    let c = &me.characters[i];
                    if !c.rested && matches_filter_ip(c, filt)
                        && !c.cannot_be_rested_buff && !c.static_cannot_be_rested {
                        pool.push((false, c.power(), Slot::Char(i)));
                    }
                }
                for i in 0..me.stages.len() {
                    let c = &me.stages[i];
                    if !c.rested && matches_filter_ip(c, filt)
                        && !c.cannot_be_rested_buff && !c.static_cannot_be_rested {
                        pool.push((false, c.power(), Slot::Stage(i)));
                    }
                }
            }
            if pool.len() < n { return None; }
            pool.sort_by(|a, b| (a.0, a.1).cmp(&(b.0, b.1)));
            for (_, _, sl) in pool.into_iter().take(n) {
                get_ip_mut(&mut state.players[me_idx], sl).rested = true;
            }
        }
        "return_self_chara_to_hand" => {
            let (count, filt) = count_and_filter(&cv);
            // 候補 index を power 昇順 (stable=元順 ties) で count 枚選択
            let mut cands: Vec<(usize, i32)> = state.players[me_idx]
                .characters
                .iter()
                .enumerate()
                .filter(|(_, c)| matches_filter_ip(&c, filt))
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
            // ⚠ 「自分の効果で自分のキャラが場を離れた」 = leave-by-self トリガーの対象
            //   (公式 cardqa_op_16 / OP16-041 バギー: 虜の矢のコストで自キャラが手札に
            //    戻った時も 「場を離れた時」 効果は発動する)。 任意コストの離脱 3 経路とも
            //   発火が抜けていた (2026-08-10 是正、 Python effects.py と同位置)。
            if fire_leave_by_self_effect(state, me_idx).is_err() {
                return None;
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
        // 相手キャラに相手のドンを付与する cost (effects.py:attach_opp_don_to_opp_chara)。
        // = attach_rested_don の to_opp 版に委譲する。
        "attach_opp_don_to_opp_chara" => {
            let n = if cv.is_object() {
                cv.get("count").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                cv.as_i64().unwrap_or(1)
            };
            let from_cost = cv.get("from_cost_area").and_then(|x| x.as_bool()).unwrap_or(false);
            // ⚠ Python は `max(opp.characters, key=lambda c: c.power)` = **現パワー最大**
            //   (同点なら先頭)。 one_opponent_character_any へ委譲すると _threat_key/opp_value
            //   の脅威度順になり 同点時に別のキャラを選ぶ (OP15-003 アルビダ / OP15-023 アーロン、
            //   2026-08-03 発覚)。 Python と同じ選び方を直接書く。
            let opp_idx2 = 1 - me_idx;
            let Some(ti) = (0..state.players[opp_idx2].characters.len()).max_by_key(|&i| {
                // max_by_key は tie で **最後** を返すので、 Python の max (最初) に合わせ
                // index を負符号で第 2 キーにする。
                (state.players[opp_idx2].characters[i].power(), -(i as i32))
            }) else {
                return Some(()); // 相手キャラ 0 = 何もしない (payability で弾かれる想定)
            };
            let n = n as i32;
            let opp_p = &mut state.players[opp_idx2];
            let mut take = n.min(opp_p.don_rested);
            opp_p.don_rested -= take;
            if from_cost && take < n {
                let more = (n - take).min(opp_p.don_active);
                opp_p.don_active -= more;
                take += more;
            }
            opp_p.characters[ti].attached_dons += take;
        }
        // ko_self_chara **cost 版**: Python (effects.py の cost ループ) は トラッシュ送りと
        // 付与ドンのレスト戻しだけ を行い、 【KO時】/on_self_chara_ko/leave_by_self_effect を
        // **一切発火しない** (do-effect 版と非対称)。 chara_ko_taken_this_turn も増えない。
        // ⚠ execute_effect に委譲すると do-effect 版が走ってトリガーが発火し MISMATCH になる
        //   (EB04-048 ルッチ / OP06-083 等、 2026-08-03 全カード差分掃引で発覚)。
        // 犠牲順は Python と同じ power 昇順。
        "ko_self_chara" => {
            let (n, filt, excl) = if cv.is_object() {
                (
                    cv.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize,
                    cv.get("filter").cloned(),
                    cv.get("exclude_self").and_then(|x| x.as_bool()).unwrap_or(false),
                )
            } else {
                (cv.as_i64().unwrap_or(1) as usize, None, false)
            };
            let src_idx = if let Slot::Char(i) = src { Some(i) } else { None };
            let mut cands: Vec<usize> = (0..state.players[me_idx].characters.len())
                .filter(|&i| {
                    let c = &state.players[me_idx].characters[i];
                    matches_filter_ip(c, filt.as_ref())
                        && !(excl && Some(i) == src_idx)
                        // 効果KO免疫のキャラは自KOコストの対象外 (payability と同則、cardqa_op_05)
                        && !(c.static_ko_immune || c.ko_immune_until_turn_end
                             || c.ko_immune_through_opp_turn)
                })
                .collect();
            cands.sort_by_key(|&i| state.players[me_idx].characters[i].power());
            cands.truncate(n);
            cands.sort_unstable_by(|a, b| b.cmp(a)); // 後ろから除去して index を保つ
            for i in cands {
                let ip = state.players[me_idx].characters.remove(i);
                let don = ip.attached_dons;
                state.players[me_idx].trash.push(ip.card);
                state.players[me_idx].don_rested += don;
            }
            // ⚠ 「自分の効果で自分のキャラが場を離れた」 = leave-by-self トリガーの対象
            //   (公式 cardqa_op_16 / OP16-041 バギー: 虜の矢のコストで自キャラが手札に
            //    戻った時も 「場を離れた時」 効果は発動する)。 任意コストの離脱 3 経路とも
            //   発火が抜けていた (2026-08-10 是正、 Python effects.py と同位置)。
            if fire_leave_by_self_effect(state, me_idx).is_err() {
                return None;
            }
        }
        // 上記以外の cost は対応する primitive にそのまま委譲する (Python effects.py:8659 の汎用パス)。
        // 未実装 primitive なら execute_effect が false を返し、 呼出側が bail する = 黙って無視しない。
        _ => {
            if !execute_effect(cs, state, me_idx, src) {
                return None;
            }
        }
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
/// **同時離脱** primitive (effects.py:`_SIMULTANEOUS_LEAVE_PRIMS`)。 これらは 1 事象として扱い、
/// 置換 holder を 「バッチ開始時の盤面」 から決める + 置換コストは holder ごとに 1 回。
/// ⚠ `ko` も all_* target なら同時離脱 (単体でもバッチを開いて損はない)。
const SIMULTANEOUS_LEAVE_PRIMS: &[&str] = &[
    "ko", "ko_multi", "ko_all_others", "ko_total_power_le",
    "return_to_hand_multi", "return_to_deck_bottom_multi",
];

fn execute_effect(prim: &Value, state: &mut GameState, me_idx: usize, src: Slot) -> bool {
    // ⭐ 「キャラの効果でキャラを登場させた時」 (cardqa_op_12 / OP12-081) の判定用。
    //   いま実行中の効果の発動元が **場のキャラ** かを保持 (入れ子は内側優先で save/restore)。
    //   Python の state._effect_source_ip と同じ役割。
    let _prev_pf = state.rust_play_source_is_field_chara;
    state.rust_play_source_is_field_chara = matches!(src, Slot::Char(_));
    // ⭐ leave victim スナップショット (Python execute_effect と同位置)。 最外側だけ。
    let snap_owner = state.rust_leave_victim_snapshot.is_none();
    if snap_owner {
        state.rust_leave_victim_snapshot = Some(
            state.players[me_idx].characters.iter().map(|c| c.card.clone()).collect(),
        );
    }
    // 同時離脱バッチ (Python `_LeaveBatch`): 最外側だけが有効 (入れ子は開き直さない)。
    let opened = state.rust_leave_batch_holders.is_none()
        && prim.as_object().map_or(false, |o| {
            o.keys().any(|k| SIMULTANEOUS_LEAVE_PRIMS.contains(&k.as_str()))
        });
    if opened {
        let mut snap: Vec<(usize, Option<u64>, String)> = Vec::new();
        for pi in 0..2 {
            let n_ch = state.players[pi].characters.len();
            let n_st = state.players[pi].stages.len();
            let mut slots: Vec<Slot> = vec![Slot::Leader];
            slots.extend((0..n_ch).map(Slot::Char));
            slots.extend((0..n_st).map(Slot::Stage));
            for sl in slots {
                let cid = get_ip(&state.players[pi], sl).card.card_id.clone();
                let tok = tag_src(state, pi, sl);
                snap.push((pi, tok, cid));
            }
        }
        state.rust_leave_batch_holders = Some(snap);
        state.rust_leave_batch_paid.clear();
        state.rust_leave_batch_declined.clear();
    }
    let _r = execute_effect_inner(prim, state, me_idx, src);
    if opened {
        if let Some(snap) = state.rust_leave_batch_holders.take() {
            for (pi, tok, _) in snap {
                let _ = find_tagged(state, pi, tok); // タグ回収
            }
        }
        state.rust_leave_batch_paid.clear();
        state.rust_leave_batch_declined.clear();
    }
    if snap_owner {
        state.rust_leave_victim_snapshot = None;
    }
    state.rust_play_source_is_field_chara = _prev_pf;
    _r
}

fn execute_effect_inner(prim: &Value, state: &mut GameState, me_idx: usize, src: Slot) -> bool {
    let opp_idx = 1 - me_idx;
    let Some((key, v)) = prim.as_object().and_then(|o| o.iter().next()) else { return true };
    match key.as_str() {
        // ドロー N (effects.py:3121)。 block_self_draw 中は不発。
        "draw" => {
            let n = v.as_i64().unwrap_or(0) as i32;
            let mut drew = false;
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
                drew = true;
            }
            // 「ドローフェイズ以外でカードを引いた時」 (effects.py:3676、 OP05-053)。
            if drew && me_board_has_when(state, me_idx, "on_self_draw_non_draw_phase")
                && fire_on_self_draw_non_draw_phase(state, me_idx).is_err()
            {
                return false;
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
            // 局面採点で最良 option (tie は first = Python max/min 準拠)。
            // ⭐ 「**相手は**以下から1つを選ぶ」 (actor="opp") は **相手が選ぶ** ので、
            //   発動者視点スコアの **最小** = 相手にとって最も損の小さい選択肢を取る
            //   (Python effects.py の _pick と同じ。 2026-08-07 是正)。
            let actor_is_opp =
                spec.get("actor").and_then(|x| x.as_str()) == Some("opp");
            let n_opp = state.players[opp_idx].characters.len();
            let n_me = state.players[me_idx].characters.len();
            let my_life = state.players[me_idx].life.len();
            let opp_life = state.players[opp_idx].life.len();
            let opp_hand = state.players[opp_idx].hand.len();
            let mut best = valid[0];
            let mut best_s =
                option_score(&options[valid[0]], n_opp, n_me, my_life, opp_life, opp_hand);
            for &i in &valid[1..] {
                let s = option_score(&options[i], n_opp, n_me, my_life, opp_life, opp_hand);
                let better = if actor_is_opp { s < best_s } else { s > best_s };
                if better {
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
            // ⚠ 静的側と同じく Python は `feature` (target の兄弟キー) を読む。
            //   "feature_filter" は overlay に 1 度も存在しない死にキー (2026-08-03)。
            let ff = v
                .get("feature")
                .or_else(|| v.get("feature_filter"))
                .and_then(|x| x.as_str())
                .map(|s| s.to_string());
            let Some(targets) = resolve_target(v.get("target"), me_idx, opp_idx, src, state) else { return false };
            // soshite (= 「その後、 そのカードを〜」、 target spec self_just_buffed) 用に直近 pump
            // 対象を記録する (effects.py:3616 `last_pumped_iid`)。 対象 0 なら更新しない。
            if let Some(&(pi, sl)) = targets.first() {
                state.last_pumped = Some((
                    pi,
                    match sl {
                        Slot::Leader => -1,
                        Slot::Char(ci) => ci as i32,
                        _ => -2,
                    },
                ));
            }
            let duration = v.get("duration").and_then(|x| x.as_str()).unwrap_or("turn").to_string();
            let turn_number = state.turn_number;
            // 「パワー0にする」 (素の) = その時点の現在パワーぶんの固定マイナス (per-target)。
            // 公式 cardqa_op_07 / OP07-002 アイン: 代入でなく -現在パワー (EB04-010 も同型)。
            let to_zero = v.get("to_zero").and_then(|x| x.as_bool()).unwrap_or(false);
            for (pi, sl) in targets {
                if let Some(f) = &ff {
                    if !get_ip(&state.players[pi], sl).card.features.iter().any(|x| x == f) {
                        continue;
                    }
                }
                let amt = if to_zero { -get_ip(&state.players[pi], sl).power() } else { amount };
                let ip = get_ip_mut(&mut state.players[pi], sl);
                match duration.as_str() {
                    "static" => ip.static_buff += amt,
                    "battle" => ip.battle_buff += amt,
                    "next_self_turn_start" => ip.next_turn_buff += amt,
                    "next_opp_turn_end" | "next_opp_end_phase" => {
                        ip.next_opp_turn_end_buff += amt;
                        ip.next_opp_turn_end_applier_idx = me_idx as i32;
                        ip.next_opp_turn_end_applied_turn = turn_number;
                    }
                    "next_self_turn_end" => {
                        ip.next_self_turn_end_buff += amt;
                        ip.next_self_turn_end_applier_idx = me_idx as i32;
                        ip.next_self_turn_end_applied_turn = turn_number;
                    }
                    _ => ip.turn_buff += amt, // "turn" 既定
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
            // 公式 「相手の**カード**1枚をレスト」 = リーダー/キャラ/ステージ/ドン (cardqa_op_14)。
            // AI 順は Python (effects.py の one_opp_card_any) と同じ:
            //   キャラ (power 降順) → リーダー → ドン → ステージ。
            let is_opp_card_any = v.as_str() == Some("one_opp_card_any")
                || v.get("type").and_then(|x| x.as_str()) == Some("one_opp_card_any");
            if is_opp_card_any {
                let restable = |ip: &InPlay| {
                    !ip.rested && !ip.cannot_be_rested_buff && !ip.static_cannot_be_rested
                };
                let mut chosen: Option<usize> = None;
                {
                    let opp = &state.players[opp_idx];
                    let mut cands: Vec<usize> = (0..opp.characters.len())
                        .filter(|&i| restable(&opp.characters[i]))
                        .collect();
                    cands.sort_by(|&a, &b| {
                        opp.characters[b].power().cmp(&opp.characters[a].power())
                    });
                    chosen = cands.first().copied();
                }
                if let Some(i) = chosen {
                    if let Err(e) = rest_char_with_cascade(state, me_idx, opp_idx, i, src) {
                        note_prim_err(&e);
                        return false;
                    }
                    return true;
                }
                if restable(&state.players[opp_idx].leader) {
                    state.players[opp_idx].leader.rested = true;
                    return true;
                }
                if state.players[opp_idx].don_active > 0 {
                    state.players[opp_idx].don_active -= 1;
                    state.players[opp_idx].don_rested += 1;
                    return true;
                }
                let si = (0..state.players[opp_idx].stages.len())
                    .find(|&i| restable(&state.players[opp_idx].stages[i]));
                if let Some(i) = si {
                    state.players[opp_idx].stages[i].rested = true;
                }
                return true;
            }
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
                    if let Err(e) = rest_char_with_cascade(state, me_idx, opp_idx, i, src) {
                        note_prim_err(&e);
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
                            if let Err(e) = rest_char_with_cascade(state, me_idx, pi, idx, src) {
                                note_prim_err(&e);
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
                        if let Err(e) = rest_char_with_cascade(state, me_idx, pi, idx, src) {
                            note_prim_err(&e);
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
            let mut kom_any = false;
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
                if victims.is_empty() {
                    continue;
                }
                // cascade (【KO時】/ on_opp_chara_ko / on_self_chara_ko / replace_ko) が絡むかを判定。
                // 絡まなければ従来通り一括除去、 絡むなら Python と同じ順で 1 体ずつ処理する。
                let vowner = victims[0].0;
                let cascade = me_board_has_when(state, me_idx, "on_opp_chara_ko")
                    || me_board_has_when(state, vowner, "on_self_chara_ko")
                    || me_board_has_when(state, vowner, "on_ko")
                    || me_board_has_when(state, vowner, "replace_ko")
                    || me_board_has_when(state, vowner, "replace_leave");
                if !cascade {
                    remove_victims(state, victims, RemoveDest::Trash);
                    kom_any = true;
                    continue;
                }
                // ⚠ 複数 victim × cascade は除去順で index が動き Python の object 参照と対応が取れない
                //   → 単体のみ対応、 複数なら明示 bail (誤対応を作らない)。
                if victims.len() > 1 {
                    return false;
                }
                let (vpi, vidx) = victims[0];
                match try_replace_ko(state, vpi, vidx, true, "ko") {
                    Ok(true) => continue, // 置換発動 = KO 阻止
                    Ok(false) => {}
                    Err(_) => return false,
                }
                if vidx >= state.players[vpi].characters.len() {
                    continue;
                }
                note_ko_victim_negated(state, vpi, vidx);
                let removed = state.players[vpi].characters.remove(vidx);
                let cid = removed.card.card_id.clone();
                let don = removed.attached_dons;
                state.players[vpi].trash.push(removed.card);
                state.players[vpi].don_rested += don;
                kom_any = true;
                // Python の trigger_on_ko (= 全 KO 経路の共通フック、 effects.py:12942) は
                // 冒頭で owner.chara_ko_taken_this_turn を加算する。 overlay/on_ko の有無に
                // 依らないので ko_multi でも増える (EB04-059、 2026-08-03 発覚)。
                // Python 順: on_ko (victim 側 source-gone) → on_opp_chara_ko (me) → on_self_chara_ko (victim 側)
                if fire_on_ko(state, vpi, &cid, true).is_err() {
                    return false;
                }
                if fire_field_when(state, me_idx, "on_opp_chara_ko").is_err() {
                    return false;
                }
                if fire_field_when(state, vpi, "on_self_chara_ko").is_err() {
                    return false;
                }
            }
            // 1 体でも KO したら最後に 1 回だけ (effects.py:ko_multi 末尾)
            if kom_any && me_board_has_when(state, me_idx, "on_self_chara_leave_by_self_effect")
                && fire_leave_by_self_effect(state, me_idx).is_err()
            {
                return false;
            }
            true
        }
        // マルチターゲット版 (effects.py:return_to_deck_bottom_multi)。 spec リストを順に解決 → 除去。
        // dedup は「除去済は board から消える」で自然に成立する (cascade 無しの前提)。
        "return_to_deck_bottom_multi" => {
            let Some(list) = v.as_array() else { return true };
            let mut any_removed = false;
            // Python (effects.py:7555) は spec ごとに現盤面へ解決し、 対象を 1 体ずつ即座に処理する
            // (= 除去で index が動くので都度解決)。 相手キャラは protect/ko_immune を尊重し、
            // replace_ko/replace_leave があれば置換を試みる。
            for spec in list {
                let tgt_spec: Value = if spec.is_string() {
                    spec.clone()
                } else {
                    spec.get("target").cloned().unwrap_or(Value::String("one_opponent_character_any".into()))
                };
                let Some(targets) = resolve_target(Some(&tgt_spec), me_idx, opp_idx, src, state) else {
                    note_unknown_key("rtdb_multi", "target 未対応");
                    return false;
                };
                // 除去で index がずれるので、 大きい index から処理する (同一 spec 内の相対順は
                // Python の逐次 remove と一致する = 各 victim は独立に自陣/敵陣から抜けるだけ)。
                let mut idxs: Vec<(usize, usize)> = targets
                    .iter()
                    .filter_map(|&(pi, sl)| if let Slot::Char(i) = sl { Some((pi, i)) } else { None })
                    .collect();
                idxs.sort_by(|a, b| b.1.cmp(&a.1));
                for (pi, idx) in idxs {
                    if idx >= state.players[pi].characters.len() {
                        continue;
                    }
                    if pi == opp_idx {
                        let c = &state.players[pi].characters[idx];
                        if c.protect_from_opp_effect || c.static_ko_immune {
                            continue;
                        }
                        match try_replace_ko(state, pi, idx, true, "return_to_deck_bottom") {
                            Ok(true) => continue, // 置換発動 = デッキ下へは行かない
                            Ok(false) => {}
                            Err(_) => {
                                note_unknown_key("rtdb_multi", "replace 再現不能");
                                return false;
                            }
                        }
                    }
                    remove_victims(state, vec![(pi, idx)], RemoveDest::DeckBottom);
                    any_removed = true;
                }
            }
            // Python は loop 全体の後に 1 回だけ actor 側の【自分の効果で場を離れた時】を発火
            // (effects.py:7588 `if _rdm_any`)。
            if any_removed
                && me_board_has_when(state, me_idx, "on_self_chara_leave_by_self_effect")
                && fire_leave_by_self_effect(state, me_idx).is_err()
            {
                return false;
            }
            true
        }
        // 自キャラを持ち主のライフへ (effects.py:chara_to_self_life、 KO ではないので KO時トリガー無し)。
        // AI は top 既定。 ⚠ 付与ドンは **active** へ戻す (Python 準拠、 他の離場と非対称)。
        "chara_to_self_life" => {
            let tspec = if v.is_object() {
                v.get("target").cloned().unwrap_or(Value::String("one_self_character_any".into()))
            } else {
                v.clone()
            };
            let place_bottom = v.get("place").and_then(|x| x.as_str()) == Some("bottom");
            let face_up = v.get("face_up").and_then(|x| x.as_bool()).unwrap_or(false);
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
            // ⚠ 対象 0 枚は「忠実に再現した結果 何も起きない」= true。 Python の return False は
            //   caller (do-loop / optional_cost_then) が無視するので、 false にすると bail に化ける。
            if targets.is_empty() {
                return true;
            }
            if me_board_has_when(state, me_idx, "on_self_chara_leave_by_self_effect") {
                return false; // leave cascade 再現不能 → bail
            }
            let mut idxs: Vec<usize> = targets
                .iter()
                .filter(|&&(pi, _)| pi == me_idx)
                .filter_map(|&(_, sl)| if let Slot::Char(i) = sl { Some(i) } else { None })
                .collect();
            idxs.sort_unstable();
            for i in idxs.into_iter().rev() {
                let me = &mut state.players[me_idx];
                if i >= me.characters.len() {
                    continue;
                }
                let removed = me.characters.remove(i);
            let neg_ip = removed.clone();
                me.don_active += removed.attached_dons;
                if place_bottom {
                    me.life.push(removed.card);
                } else {
                    me.life.insert(0, removed.card);
                }
                if face_up {
                    me.face_up_life_count = (me.face_up_life_count + 1).min(me.life.len() as i32);
                    // 「ライフに表向きで置かれた時」 = 公開領域 → 本人も反応しうる (cardqa_op_08)
                    let card = neg_ip.card.clone();
                    note_public_departure(state, me_idx, &card);
                }
            }
            true
        }
        // 自分のトラッシュから filter 一致 N 枚を手札へ (effects.py:trash_to_hand)。
        "trash_to_hand" => {
            let filt = v.get("filter");
            let limit = v.get("limit").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let mut found = 0usize;
            let mut rest: Vec<crate::state::CardDef> = vec![];
            for card in std::mem::take(&mut state.players[me_idx].trash) {
                if found < limit && matches_filter(&card, filt) {
                    state.players[me_idx].hand.push(card);
                    found += 1;
                } else {
                    rest.push(card);
                }
            }
            state.players[me_idx].trash = rest;
            true
        }
        // 相手キャラを持ち主のライフへ (effects.py:to_opp_life)。 KO ではないので【KO時】は発火しない。
        // 付与ドンはレストでコストエリアへ (6-5-5-4)。 protect_from_opp_effect は尊重。
        "to_opp_life" => {
            let tspec = if v.is_string() {
                v.clone()
            } else {
                v.get("target").cloned().unwrap_or(Value::String("one_opponent_character_any".into()))
            };
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
            let mut idxs: Vec<usize> = targets
                .iter()
                .filter(|&&(pi, _)| pi == opp_idx)
                .filter_map(|&(_, sl)| if let Slot::Char(i) = sl { Some(i) } else { None })
                .filter(|&i| !state.players[opp_idx].characters[i].protect_from_opp_effect)
                .collect();
            idxs.sort_unstable();
            for i in idxs.into_iter().rev() {
                let o = &mut state.players[opp_idx];
                if i >= o.characters.len() {
                    continue;
                }
                let removed = o.characters.remove(i);
                o.don_rested += removed.attached_dons;
                o.life.push(removed.card);
            }
            true
        }
        // 相手が自身の場のドン N 枚をドンデッキへ (effects.py:return_opp_don)。 active 優先 → rested。
        "return_opp_don" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            } as i32;
            // ⭐ 公式 「**相手は**自身の場のドン‼N枚を…戻す」 = **相手が選ぶ** ので
            //   **レストのドンから** 返す (アクティブはこのターンまだ使える)。
            //   2026-08-07 まで active 優先 = 行動側に都合のよい選択だった (Python と同時是正)。
            let o = &mut state.players[opp_idx];
            let r = n.min(o.don_rested);
            o.don_rested -= r;
            o.don_remaining_in_deck += r;
            let a = (n - r).min(o.don_active);
            o.don_active -= a;
            o.don_remaining_in_deck += a;
            true
        }
        // このキャラ以外の自キャラ全てをデッキ下へ (effects.py:other_self_charas_to_deck_bottom)。
        // 自分のキャラすべてをトラッシュ (effects.py:3290、 OP13-082 五老星)。 KO ではない = 【KO時】は
        // 発火しないが 「自分の効果で場を離れた」 trigger は発火する。 付与ドンはレストで返却。
        "trash_all_self_chara" => {
            let victims: Vec<(usize, usize)> =
                (0..state.players[me_idx].characters.len()).map(|i| (me_idx, i)).collect();
            // 「トラッシュに置く」 = 公開領域 → 離脱本人も反応しうる (cardqa_op_08、 除去前に控える)
            let departed_cards: Vec<CardDef> = state.players[me_idx]
                .characters
                .iter()
                .map(|c| c.card.clone())
                .collect();
            if !victims.is_empty() {
                // ⚠ 公式は 「トラッシュに置く」 = KO ではない → 被 KO 数に数えない。
                //   RemoveDest::Trash だと chara_ko_taken_this_turn が誤って増えていた。
                remove_victims(state, victims, RemoveDest::TrashNoKo);
                for card in &departed_cards {
                    note_public_departure(state, me_idx, card);
                }
                if me_board_has_when(state, me_idx, "on_self_chara_leave_by_self_effect")
                    && fire_leave_by_self_effect(state, me_idx).is_err()
                {
                    return false;
                }
            }
            true
        }
        // 「コスト N 以上かつ (動的閾値) 以下の 『XXX』 1 枚を手札から登場」 (effects.py:5266、 OP08-062)。
        // 「コスト N 以上かつ (動的閾値) 以下の 『XXX』 1 枚を手札から登場」 (effects.py:5285、 OP08-062)。
        // ⚠ 2026-08-01 の Python 修正で挙動が変わった (cloud の効果テスト backfill 由来):
        //   ① name の代わりに name_filter (= _matches_filter 互換 dict) も取る (P-090 スムージー)
        //   ② AI 選択が「手札順で最初」 → **cost 降順 → power 降順 → name 昇順** に変更
        //   ③ 登場後に trigger_on_play を発火する
        "play_from_hand_named_with_dynamic_cost" => {
            let name = norm_card_name(v.get("name").and_then(|x| x.as_str()).unwrap_or(""));
            let name_filter = v.get("name_filter").cloned();
            let cost_ge = v.get("cost_ge").and_then(|x| x.as_i64()).unwrap_or(0) as i32;
            let cl_src = v.get("cost_le_source").and_then(|x| x.as_str()).unwrap_or("opp_don_total");
            let don_total = |pl: &crate::state::Player| -> i32 {
                pl.don_active
                    + pl.don_rested
                    + pl.leader.attached_dons
                    + pl.characters.iter().map(|c| c.attached_dons).sum::<i32>()
            };
            let cost_le = match cl_src {
                "opp_don_total" => don_total(&state.players[opp_idx]),
                "self_don_total" => don_total(&state.players[me_idx]),
                _ => v.get("cost_le").and_then(|x| x.as_i64()).unwrap_or(99) as i32,
            };
            let me = &state.players[me_idx];
            let mut cands: Vec<usize> = (0..me.hand.len())
                .filter(|&i| {
                    let c = &me.hand[i];
                    if c.category != crate::state::Category::Character {
                        return false;
                    }
                    let name_ok = match &name_filter {
                        Some(f) => matches_filter(c, Some(f)),
                        None => norm_card_name(&c.name) == name,
                    };
                    name_ok && c.cost >= cost_ge && c.cost <= cost_le && !char_summon_blocked(me, c)
                })
                .collect();
            if cands.is_empty() {
                return true; // Python は return False = 忠実な no-op
            }
            // cost 降順 → power 降順 → name 昇順 (effects.py:5323)
            cands.sort_by(|&a, &b| {
                let (ca, cb) = (&me.hand[a], &me.hand[b]);
                (-cb.cost, -cb.power, ca.name.clone()).cmp(&(-ca.cost, -ca.power, cb.name.clone()))
            });
            let idx = cands[0];
            // ⚠ Python は append → pop(idx) の順 (field-full trash が先、 hand 除去は後)。
            //   on_play は pop 後に発火するので pop-first でも観測差は出ない。
            trash_weakest_for_field_full(state, me_idx);
            let card = state.players[me_idx].hand.remove(idx);
            let ip = InPlay::of(card.clone(), true);
            state.players[me_idx].characters.push(ip);
            let pidx = state.players[me_idx].characters.len() - 1;
            state.last_self_chara_played_card = Some(card);
            state.last_self_chara_played_from_trash = false;
            if execute_on_play(state, me_idx, pidx).is_err() {
                return false;
            }
            true
        }
        // 自分の (filter) キャラ 2 枚の元々パワーをこのターン中入れ替える (effects.py:6529、 OP14-001)。
        // AI は元々パワー昇順で最小と最大のペアを選ぶ。 2 枚未満なら不発 (Python も return False = no-op)。
        "swap_self_power" => {
            let filt = v.get("filter").cloned();
            let mut cands: Vec<usize> = (0..state.players[me_idx].characters.len())
                .filter(|&i| matches_filter_ip(&state.players[me_idx].characters[i], filt.as_ref()))
                .collect();
            if cands.len() < 2 {
                return true;
            }
            // Python: cands.sort(key=card.power) は stable = 同 power は元順維持
            cands.sort_by_key(|&i| state.players[me_idx].characters[i].card.power);
            let (a, b) = (cands[0], cands[cands.len() - 1]);
            let pa = state.players[me_idx].characters[a].card.power;
            let pb = state.players[me_idx].characters[b].card.power;
            state.players[me_idx].characters[a].turn_base_power_override = Some(pb);
            state.players[me_idx].characters[b].turn_base_power_override = Some(pa);
            true
        }
        // 「自分の (filter) キャラを任意の枚数 KO してよい。 KO 1 枚につきリーダー +M」
        // (effects.py:3429、 OP06-095)。 AI は全該当を KO。 KO 時トリガーは prim 側で発火。
        "ko_self_chara_then_pump_leader_per" => {
            let filt = v.get("filter").cloned();
            let amount = v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1000) as i32;
            let duration = v.get("duration").and_then(|x| x.as_str()).unwrap_or("turn").to_string();
            let toks: Vec<Option<u64>> = (0..state.players[me_idx].characters.len())
                .filter(|&i| matches_filter_ip(&state.players[me_idx].characters[i], filt.as_ref()))
                .collect::<Vec<_>>()
                .into_iter()
                .map(|i| tag_src(state, me_idx, Slot::Char(i)))
                .collect();
            let mut ko_count = 0i32;
            for tok in toks {
                let Slot::Char(idx) = find_tagged(state, me_idx, tok) else { continue };
                let vcid = state.players[me_idx].characters[idx].card.card_id.clone();
                let vdon = state.players[me_idx].characters[idx].attached_dons;
                note_ko_victim_negated(state, me_idx, idx);
                let removed = state.players[me_idx].characters.remove(idx);
                let _ko_vic = removed.card.clone();
                let _ko_vtop = removed.truly_original_power(); // KO 時点の元々のパワー (公式 4-9-2-1) // KO victim 文脈 (victim_truly_original_power_ge / victim_feature_in 用)
                state.players[me_idx].trash.push(removed.card);
                state.players[me_idx].don_rested += vdon;
                ko_count += 1;
                // 自分の効果による自陣 KO = by_opp_effect=false。
                // ⚠ 「Python が加算しない (opp 起因のみ)」 というコメントが付いていたが **誤り**。
                //   trigger_on_ko (= 全 KO 経路の共通フック、 effects.py:12942) が冒頭で
                //   owner.chara_ko_taken_this_turn を無条件加算する (OP06-095、 2026-08-03 発覚)。
                //   同種の誤解が ko_self_chara / ko_multi / ko_self_with_filter にもあった。
                state.last_chara_ko_victim_card = Some(_ko_vic);
                state.rust_ko_victim_truly_original_power = Some(_ko_vtop); // Python は payload で victim を運ぶ (2026-08-11)
                if fire_on_ko(state, me_idx, &vcid, false).is_err() {
                    return false;
                }
                if fire_field_when(state, me_idx, "on_self_chara_ko").is_err() {
                    return false;
                }
                state.last_chara_ko_victim_card = None;
            }
            if ko_count > 0 {
                let prim = json!({"power_pump": {
                    "target": "self_leader", "amount": amount * ko_count, "duration": duration
                }});
                return execute_effect(&prim, state, me_idx, src);
            }
            true
        }
        // 自分のライフの表向きカードすべてをトラッシュ (effects.py:6800、 ST13-002)。 count-only モデルで
        // 表向き札は top に居るので上から face_up_life_count 枚。
        "trash_all_face_up_life" => {
            let me = &mut state.players[me_idx];
            let n = me.face_up_life_count.min(me.life.len() as i32);
            for _ in 0..n {
                if me.life.is_empty() {
                    break;
                }
                let c = me.life.remove(0);
                me.trash.push(c);
            }
            me.face_up_life_count = 0;
            true
        }
        // 自分の手札が N 枚になるように捨てる (effects.py:5563)。 AI は worst_hand_idx から。
        "self_hand_to_size" => {
            let target = if v.is_object() {
                v.get("size").and_then(|x| x.as_i64()).unwrap_or(5) as usize
            } else {
                v.as_i64().unwrap_or(5) as usize
            };
            while state.players[me_idx].hand.len() > target {
                let me = &mut state.players[me_idx];
                let Some(i) = worst_hand_idx(&me.hand, &me.known_hand_card_ids) else { break };
                let c = me.hand.remove(i);
                me.trash.push(c);
            }
            true
        }
        // 相手の場のドン枚数に合わせて自分の場のドンをドンデッキへ戻す (effects.py:6694、 OP08-074)。
        // 超過分を rested 優先で返す (= active を残す)。
        "return_self_don_to_match_opp" => {
            let opp_total = state.players[opp_idx].don_active + state.players[opp_idx].don_rested;
            let me = &mut state.players[me_idx];
            let excess = (me.don_active + me.don_rested - opp_total).max(0);
            let ret_rested = excess.min(me.don_rested);
            me.don_rested -= ret_rested;
            me.don_remaining_in_deck += ret_rested;
            let ret_active = excess - ret_rested;
            if ret_active > 0 {
                me.don_active -= ret_active;
                me.don_remaining_in_deck += ret_active;
            }
            true
        }
        // 「相手のドン N 枚以上付与のレストキャラ M 枚までは次の相手リフレッシュでアクティブにならない」
        // (effects.py:6854、 OP15-025/OP14-035)。 AI は脅威度 (power 降順) 優先。
        "keep_opp_rested_chara_with_don_ge_next_refresh" => {
            let don_ge = v.get("don_ge").and_then(|x| x.as_i64()).unwrap_or(1) as i32;
            let limit = v.get("limit").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let cle = v.get("cost_le").and_then(|x| x.as_i64()).map(|x| x as i32);
            let cge = v.get("cost_ge").and_then(|x| x.as_i64()).map(|x| x as i32);
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> = (0..opp.characters.len())
                .filter(|&i| {
                    let c = &opp.characters[i];
                    let cc = c.card.cost;
                    c.rested
                        && c.attached_dons >= don_ge
                        && cle.map_or(true, |x| cc <= x)
                        && cge.map_or(true, |x| cc >= x)
                })
                .collect();
            // _threat_key = power 降順 (effects.py:740、 stable なので同値は元順維持)
            cands.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
            for i in cands.into_iter().take(limit) {
                state.players[opp_idx].characters[i].stay_rested_next_refresh = true;
            }
            true
        }
        // 相手キャラを相手のライフ上へ表向きで置く (effects.py:7212、 EB01-053)。 KO ではない。
        "chara_to_opp_life" => {
            let tspec = if v.is_string() {
                v.clone()
            } else {
                v.get("target").cloned().unwrap_or(Value::String("one_opponent_character_any".into()))
            };
            // 「置く：相手は手札1枚を捨てる」 の後段は 実際に置いた場合のみ (OP09-101 クザン、 cardqa)。
            let then_specs = if v.is_object() {
                v.get("then").and_then(|x| x.as_array()).cloned().unwrap_or_default()
            } else {
                Vec::new()
            };
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else {
                return false;
            };
            if targets.is_empty() {
                return true; // Python は return False = 後続を止めない no-op
            }
            // 除去で index がずれるので降順に処理する (Python は object 参照で逐次)。
            let mut idxs: Vec<usize> = targets
                .iter()
                .filter(|&&(pi, _)| pi == opp_idx)
                .filter_map(|&(_, sl)| if let Slot::Char(i) = sl { Some(i) } else { None })
                .collect();
            idxs.sort_by(|a, b| b.cmp(a));
            let mut placed = 0usize;
            for i in idxs {
                if i >= state.players[opp_idx].characters.len() {
                    continue;
                }
                let mut t = state.players[opp_idx].characters.remove(i);
                if t.attached_dons > 0 {
                    state.players[opp_idx].don_rested += t.attached_dons;
                    t.attached_dons = 0;
                }
                state.players[opp_idx].life.insert(0, t.card);
                placed += 1;
            }
            if placed > 0 {
                for es in &then_specs {
                    if !execute_effect(es, state, me_idx, src) {
                        return false;
                    }
                }
            }
            true
        }
        // 「自分の付与ドン N 枚をコストエリアにレストで戻す」 (effects.py:6639、 ST28-004)。
        // 発動元の付与ドンから優先消費 → 不足分は leader → characters の順。
        "return_attached_don_to_cost_rested" => {
            let n = if v.is_object() {
                v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32
            } else {
                v.as_i64().unwrap_or(1) as i32
            };
            let mut removed = 0i32;
            if let Some(ip) = src_ip_mut(&mut state.players[me_idx], src) {
                if ip.attached_dons > 0 {
                    let take = ip.attached_dons.min(n);
                    ip.attached_dons -= take;
                    removed += take;
                }
            }
            if removed < n {
                // leader → characters の順 (Python の [me.leader, *me.characters])。 src はスキップ。
                if src != Slot::Leader && state.players[me_idx].leader.attached_dons > 0 {
                    let take = state.players[me_idx].leader.attached_dons.min(n - removed);
                    state.players[me_idx].leader.attached_dons -= take;
                    removed += take;
                }
                for i in 0..state.players[me_idx].characters.len() {
                    if removed >= n {
                        break;
                    }
                    if src == Slot::Char(i) {
                        continue;
                    }
                    let take = state.players[me_idx].characters[i].attached_dons.min(n - removed);
                    state.players[me_idx].characters[i].attached_dons -= take;
                    removed += take;
                }
            }
            state.players[me_idx].don_rested += removed;
            true
        }
        // 「自分のリーダーとキャラ 1 枚の元々パワーを入れ替える」 (effects.py:6715、 OP14-009)。
        // AI は最高 power の自キャラ (max = 同値なら先頭)。
        "swap_base_power_self_leader_chara" => {
            if state.players[me_idx].characters.is_empty() {
                return true; // Python は return False = no-op
            }
            let me = &state.players[me_idx];
            let mut best = 0usize;
            for i in 1..me.characters.len() {
                if me.characters[i].power() > me.characters[best].power() {
                    best = i;
                }
            }
            let ld_base = me.leader.turn_base_power_override.unwrap_or(me.leader.card.power);
            let ch_base = me.characters[best].turn_base_power_override.unwrap_or(me.characters[best].card.power);
            state.players[me_idx].leader.turn_base_power_override = Some(ch_base);
            state.players[me_idx].characters[best].turn_base_power_override = Some(ld_base);
            true
        }
        // 「任意のコストを宣言 → 相手デッキ上を公開、 一致なら効果」 (effects.py:4299、 OP11-066 等)。
        // AI は相手デッキの最頻コストを宣言 (tie は低コスト優先)。
        "declare_cost_reveal_then" => {
            let opp = &state.players[opp_idx];
            if opp.deck.is_empty() {
                return true; // Python は return False = no-op
            }
            let mut counts: std::collections::HashMap<i32, usize> = std::collections::HashMap::new();
            for c in &opp.deck {
                *counts.entry(c.cost).or_insert(0) += 1;
            }
            // min(key=(-count, cost)) = 出現数降順 → コスト昇順
            let mut best: Option<(i32, usize)> = None;
            for (&cost, &cnt) in &counts {
                best = match best {
                    Some((bc, bn)) if (bn, std::cmp::Reverse(bc)) >= (cnt, std::cmp::Reverse(cost)) => Some((bc, bn)),
                    _ => Some((cost, cnt)),
                };
            }
            let declared = best.map(|(c, _)| c).unwrap_or(0);
            let revealed_cost = opp.deck[0].cost;
            if revealed_cost == declared {
                let specs = v.get("effect").and_then(|x| x.as_array()).cloned().unwrap_or_default();
                for es in &specs {
                    if !execute_effect(es, state, me_idx, src) {
                        return false;
                    }
                }
            }
            true
        }
        // 自分の手札 N 枚をデッキの上に置く (effects.py:6634、 ST17-001/ST22-001)。
        // Python は self_hand_to_deck_bottom(to="top") に委譲する。
        "discard_self_to_deck_top" => {
            let n = if v.is_object() {
                v.get("count").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            if state.players[me_idx].hand.is_empty() {
                return true; // Python は return False = 後続を止めない no-op
            }
            let prim = json!({"self_hand_to_deck_bottom": {"amount": n, "to": "top"}});
            return execute_effect(&prim, state, me_idx, src);
        }
        // 「相手のドン N 枚をドンデッキに戻す」 (effects.py:6340、 return_opp_don の alias、 OP02-085)。
        // active 優先。 戻した枚数 > 0 なら相手視点の【自分のドンがドンデッキに戻った時】を発火。
        "opp_don_to_deck" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1) as i32
            } else {
                v.as_i64().unwrap_or(1) as i32
            };
            let opp = &mut state.players[opp_idx];
            let from_active = opp.don_active.min(n);
            opp.don_active -= from_active;
            let from_rested = opp.don_rested.min(n - from_active);
            opp.don_rested -= from_rested;
            let removed = from_active + from_rested;
            opp.don_remaining_in_deck += removed;
            if removed > 0 {
                state.last_returned_don_count = removed;
                // ⚠ Python(trigger_on_self_don_returned_to_deck) は enqueue → _maybe_resolve なので、
                //   **効果の解決中は後回し** になる (resolving=True で _maybe_resolve が no-op)。
                //   Rust が inline 発火していると 「KO が先に起きて盤面が縮む」 = 対象がズレる
                //   (OP06-075 のドン-1 → 相手 OP06-076 の KO、 2026-08-04 掃引)。 必ず enqueue。
if me_board_has_when(state, opp_idx, "on_self_don_returned_to_deck") {
                    enqueue_field_when(state, opp_idx, "on_self_don_returned_to_deck");
                    if maybe_resolve(state).is_err() {
                        return false;
                    }
                }
            }
            true
        }
        // このキャラを持ち主の手札に戻す (effects.py:7716)。 場に居なければ no-op。
        "return_self_to_hand" => {
            if let Slot::Char(i) = src {
                if i < state.players[me_idx].characters.len() {
                let ip = state.players[me_idx].characters.remove(i);
                    let don = ip.attached_dons;
                    state.players[me_idx].don_rested += don;
                    state.players[me_idx].hand.push(ip.card);
                }
            }
            true
        }
        // 速攻付与 (effects.py:4670)。 target は str / {"type":..} / {"target":..}、 既定 self。
        "give_rush" => {
            let tspec: Value = if v.is_object() {
                if v.get("type").is_some() {
                    v.clone()
                } else {
                    v.get("target").cloned().unwrap_or(Value::String("self".into()))
                }
            } else if v.is_string() {
                v.clone()
            } else {
                Value::String("self".into())
            };
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else {
                return false;
            };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).summoning_sickness = false;
            }
            true
        }
        // 「相手は自身のトラッシュから (filter) N 枚をデッキの下に置く」 (effects.py:6456、 OP15-091)。
        "opp_trash_to_deck_bottom" => {
            let (count, filt) = if v.is_object() {
                (v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize, v.get("filter").cloned())
            } else {
                (v.as_i64().unwrap_or(1) as usize, None)
            };
            // ⭐ 「**相手は**…好きな順番でデッキの下に置く」 = **相手が選ぶ**。
            //   相手は最も惜しくない札 (cost 低 → power 低 → 元の順) から出す
            //   (Python effects.py:_worst_trash_order と同順)。
            //   ⚠ worst_hand_idx (counter 基準) は **トラッシュには使えない**
            //     (トラッシュからカウンターは切れない)。
            let opp = &mut state.players[opp_idx];
            let mut cand: Vec<usize> = (0..opp.trash.len())
                .filter(|&i| matches_filter(&opp.trash[i], filt.as_ref()))
                .collect();
            cand.sort_by(|&a, &b| {
                let ca = (opp.trash[a].cost, opp.trash[a].power, a);
                let cb = (opp.trash[b].cost, opp.trash[b].power, b);
                ca.cmp(&cb)
            });
            let order: Vec<usize> = cand.into_iter().take(count).collect();
            if order.is_empty() {
                // Python は該当 0 で return False だが、 Rust の false は **bail** を意味する。
                // 状態は不変なので no-op = true が正しい (旧実装と同じ扱い)。
                return true;
            }
            // ⚠ デッキ下へ積む順は **選んだ順 (= 惜しくない順)**。 Python の
            //   `picked = [trash[i] for i in _order[:count]]` と一致させる
            //   (元のトラッシュ順で積むと count>1 でデッキ底の並びがズレて MISMATCH)。
            let chosen: std::collections::HashSet<usize> = order.iter().copied().collect();
            let picked: Vec<crate::state::CardDef> =
                order.iter().map(|&i| opp.trash[i].clone()).collect();
            let old = std::mem::take(&mut opp.trash);
            for (i, c) in old.into_iter().enumerate() {
                if !chosen.contains(&i) {
                    opp.trash.push(c);
                }
            }
            opp.deck.extend(picked);
            true
        }
        // 「相手のレストのドン N 枚までは次の相手リフレッシュでアクティブにならない」
        // (effects.py:6117、 OP10-033 ナミ)。
        "keep_opp_rested_don_next_refresh" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1) as i32
            } else {
                v.as_i64().unwrap_or(1) as i32
            };
            let opp = &mut state.players[opp_idx];
            opp.next_refresh_kept_rested_don += n.min(opp.don_rested);
            true
        }
        // デッキから filter 一致のキャラを登場 (effects.py:4036、 OP11-022)。 AI は先頭から limit 枚、
        // 最後にデッキをシャッフル (公式 8-7-3-3、 rng 消費順も Python 準拠)。
        "summon_from_deck" => {
            let spec = v.as_object();
            let filt = spec.and_then(|o| o.get("filter")).cloned();
            let limit = spec.and_then(|o| o.get("limit")).and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let rested = spec.and_then(|o| o.get("rested")).and_then(|x| x.as_bool()).unwrap_or(false);
            let sickness = spec.and_then(|o| o.get("sickness")).and_then(|x| x.as_bool()).unwrap_or(true);
            let mut found = 0usize;
            let mut remaining: Vec<crate::state::CardDef> = vec![];
            let old = std::mem::take(&mut state.players[me_idx].deck);
            for c in old {
                if found < limit
                    && c.category == crate::state::Category::Character
                    && matches_filter(&c, filt.as_ref())
                    && !char_summon_blocked(&state.players[me_idx], &c)
                {
                    trash_weakest_for_field_full(state, me_idx);
                    let mut ip = InPlay::of(c.clone(), sickness);
                    ip.rested = rested;
                    state.players[me_idx].characters.push(ip);
                    let pidx = state.players[me_idx].characters.len() - 1;
                    state.last_self_chara_played_card = Some(c);
                    state.last_self_chara_played_from_trash = false;
                    if execute_on_play(state, me_idx, pidx).is_err() {
                        return false;
                    }
                    found += 1;
                } else {
                    remaining.push(c);
                }
            }
            state.players[me_idx].deck = remaining;
            let len = state.players[me_idx].deck.len();
            let perm = state.rng_mut().shuffle_perm(len);
            let old = std::mem::take(&mut state.players[me_idx].deck);
            state.players[me_idx].deck = perm.iter().map(|&j| old[j].clone()).collect();
            state.players[me_idx].known_bottom_card_ids.clear();
            state.players[me_idx].known_top_card_ids.clear();
            true
        }
        // 「(target)は、 このターン中、 属性(X)を得る」 (effects.py:6768、 OP15-093)。
        "give_attribute" => {
            let attr = v.get("attribute").and_then(|x| x.as_str()).unwrap_or("").to_string();
            let tspec = v.get("target").cloned().unwrap_or(Value::String("self".into()));
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else {
                return false;
            };
            if !attr.is_empty() {
                for (pi, sl) in targets {
                    get_ip_mut(&mut state.players[pi], sl).granted_attributes.insert(attr.clone());
                }
            }
            true
        }
        // 「このターン中、 (filter) キャラの登場コストが N 少なくなる」 (effects.py:6686、 OP02-025)。
        "reduce_play_cost_filtered_turn" => {
            let entry = json!({
                "filter": v.get("filter").cloned().unwrap_or(json!({})),
                "amount": v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1),
            });
            state.players[me_idx].play_cost_reductions_filtered_turn.push(entry);
            true
        }
        // 「自分のライフすべてを見て好きな順番で置く」 (effects.py:8232)。 AI は
        // (トリガー有, カウンター, パワー) 降順で並べ替える。
        "scry_all_life_reorder" => {
            // ⚠ 2026-08-11 是正: 従来 「owner を無視して常に自ライフ」 だった (Python も同じ誤り)。
            //   公式 EB01-052 ヴィオラ は 「**相手の**ライフすべてを見て、 好きな順番で置く」 =
            //   並べるのは **こちら**、 対象は相手のライフ。 ST13-012 マキノ は 「自分のライフ」。
            let owner_opp = v.get("owner").and_then(|x| x.as_str()) == Some("opp");
            let pi = if owner_opp { opp_idx } else { me_idx };
            if state.players[pi].life.is_empty() {
                return true; // Python は return False = 忠実な no-op
            }
            let mut life = std::mem::take(&mut state.players[pi].life);
            // Python: sort(key=(trig, counter, power), reverse=(owner != "opp"))
            //   自分のライフ = 強い札を上 / 相手のライフ = 弱い札を上 (相手が得をしない順)
            life.sort_by(|a, b| {
                let ka = (!a.trigger.is_empty() as i32, a.counter, a.power);
                let kb = (!b.trigger.is_empty() as i32, b.counter, b.power);
                if owner_opp { ka.cmp(&kb) } else { kb.cmp(&ka) }
            });
            state.players[pi].life = life;
            true
        }
        // 「自分のライフすべてを裏向きにする」 (effects.py:6804、 OP08-075)。
        "set_all_life_face_down" => {
            state.players[me_idx].face_up_life_count = 0;
            true
        }
        // 「自分の手札 N 枚をデッキの下に置く」 = self_hand_to_deck_bottom の alias (effects.py:6470)。
        "hand_to_deck_bottom" => {
            let n = if v.is_object() {
                v.get("count").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            let prim = json!({"self_hand_to_deck_bottom": {"amount": n, "to": "bottom"}});
            return execute_effect(&prim, state, me_idx, src);
        }
        // 「このターン終了時、 このキャラをトラッシュに置く」 予約 (effects.py:6830、 OP03-005)。
        "schedule_self_trash_at_turn_end" => {
            if let Some(ip) = src_ip_mut(&mut state.players[me_idx], src) {
                ip.trash_at_self_turn_end = true;
            }
            true
        }
        // 「(target) は次の相手ターン終了時まで KO されない」 (effects.py:7024)。
        "set_ko_immune_timed" => {
            let tspec = v.get("target").cloned().unwrap_or(Value::String("self".into()));
            let through = v.get("duration").and_then(|x| x.as_str()).unwrap_or("next_opp_turn_end")
                == "next_opp_turn_end";
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else {
                return false;
            };
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                if through {
                    ip.ko_immune_through_opp_turn = true;
                } else {
                    ip.ko_immune_until_turn_end = true;
                }
            }
            true
        }
        // 「自分のデッキから (filter) N 枚までを手札に加え、 デッキをシャッフル」 (effects.py:4428)。
        // AI は (cost, power) 降順で limit 枚。 公開して加える (= 相手に見える = known_hand)。
        "search" => {
            let filt = v.get("filter").cloned();
            let limit = v.get("limit").and_then(|x| x.as_i64()).unwrap_or(1).max(0) as usize;
            let me = &state.players[me_idx];
            let mut idxs: Vec<usize> =
                (0..me.deck.len()).filter(|&i| matches_filter(&me.deck[i], filt.as_ref())).collect();
            // Python: sorted(key=(cost, power), reverse=True) = stable な降順
            idxs.sort_by(|&a, &b| {
                (me.deck[b].cost, me.deck[b].power).cmp(&(me.deck[a].cost, me.deck[a].power))
            });
            idxs.truncate(limit);
            let chosen: std::collections::BTreeSet<usize> = idxs.iter().copied().collect();
            let picked: Vec<crate::state::CardDef> = idxs.iter().map(|&i| me.deck[i].clone()).collect();
            let kept: Vec<crate::state::CardDef> = (0..me.deck.len())
                .filter(|i| !chosen.contains(i))
                .map(|i| me.deck[i].clone())
                .collect();
            state.players[me_idx].deck = kept;
            for c in picked {
                state.players[me_idx].known_hand_card_ids.push(c.card_id.clone());
                state.players[me_idx].hand.push(c);
            }
            let len = state.players[me_idx].deck.len();
            let perm = state.rng_mut().shuffle_perm(len);
            let old = std::mem::take(&mut state.players[me_idx].deck);
            state.players[me_idx].deck = perm.iter().map(|&j| old[j].clone()).collect();
            state.players[me_idx].known_bottom_card_ids.clear();
            state.players[me_idx].known_top_card_ids.clear();
            true
        }
        // 「相手は手札が N 枚になるように捨てる」 (effects.py:6699、 OP05-058)。 AI は worst_hand_idx。
        "opp_hand_to_size" => {
            let target = if v.is_object() {
                v.get("size").and_then(|x| x.as_i64()).unwrap_or(5) as usize
            } else {
                v.as_i64().unwrap_or(5) as usize
            };
            while state.players[opp_idx].hand.len() > target {
                let o = &mut state.players[opp_idx];
                let Some(i) = worst_hand_idx(&o.hand, &o.known_hand_card_ids) else { break };
                let c = o.hand.remove(i);
                o.trash.push(c);
            }
            true
        }
        // 「このターン中、 元々のコスト N 以上のキャラを登場できない」 (effects.py:5596、 OP13-023)。
        "block_chara_play_cost_ge" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(7) as i32
            } else {
                v.as_i64().unwrap_or(7) as i32
            };
            state.players[me_idx].block_chara_play_cost_ge_threshold = n;
            true
        }
        // 「自分の手札が N 枚になるように引く」 (effects.py:5572、 OP02-051)。 不足分のみ。
        "draw_to_hand_size" => {
            let target = if v.is_object() {
                v.get("size").and_then(|x| x.as_i64()).unwrap_or(3) as usize
            } else {
                v.as_i64().unwrap_or(3) as usize
            };
            if state.players[me_idx].block_self_draw_until_turn_end {
                return true; // このターン中ドロー禁止 → 不発
            }
            let need = target.saturating_sub(state.players[me_idx].hand.len());
            if need > 0 {
                // Python は me.draw(need) = 通常ドローと同じ経路 (known_top 追随 + カウンタ)。
                // ⚠ do-primitive の draw と違い on_self_draw_non_draw_phase は発火しない
                //   (effects.py:5580 は me.draw を直接呼ぶ)。
                return execute_effect(&json!({"draw": need}), state, me_idx, src);
            }
            true
        }
        // 「自分はこのターン中、 リーダーにアタックできない」 (effects.py:6695、 OP06-026)。
        "block_self_attack_leader_turn" => {
            state.players[me_idx].cannot_attack_leader_until_turn_end = true;
            true
        }
        // 「自分の手札すべてをデッキの下に置き、 置いた枚数分引く」 (effects.py:6481、 P-046)。
        "draw_per_hand_to_deck_bottom" => {
            let n = state.players[me_idx].hand.len();
            if n == 0 {
                return true; // Python は return False = 忠実な no-op
            }
            let hand = std::mem::take(&mut state.players[me_idx].hand);
            state.players[me_idx].deck.extend(hand);
            if state.players[me_idx].block_self_draw_until_turn_end {
                return true;
            }
            return execute_effect(&json!({"draw": n}), state, me_idx, src);
        }
        // 「相手の手札 N 枚を公開する」 (effects.py:6627、 OP01-105)。 公開のみ = known_hand に記録。
        "reveal_opp_hand" => {
            // ⚠ true = 「手札を(全部)公開する」 (OP07-090 モルガンズ)。 数値ならその枚数。
            //   as_i64() は bool に対し None を返すので 既定 2 に落ちていた (2026-08-03 発覚)。
            let n = if v.as_bool() == Some(true) {
                state.players[opp_idx].hand.len()
            } else if v.is_object() {
                v.get("count").and_then(|x| x.as_i64()).unwrap_or(2) as usize
            } else {
                v.as_i64().unwrap_or(2) as usize
            };
            let opp = &mut state.players[opp_idx];
            let ids: Vec<String> = opp.hand.iter().take(n).map(|c| c.card_id.clone()).collect();
            for cid in ids {
                if !opp.known_hand_card_ids.contains(&cid) {
                    opp.known_hand_card_ids.push(cid);
                }
            }
            true
        }
        // 「付与ドン 1 枚につきパワー±N」 (effects.py:5929、 OP15-008)。
        "power_pump_per_target_attached_don" => {
            let tspec = v.get("target").cloned()
                .unwrap_or(Value::String("all_opponent_characters".into()));
            let amount_per = v.get("amount_per_don").and_then(|x| x.as_i64()).unwrap_or(-1000) as i32;
            let duration = v.get("duration").and_then(|x| x.as_str()).unwrap_or("turn").to_string();
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else {
                return false;
            };
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                let buff = amount_per * ip.attached_dons;
                if buff == 0 {
                    continue;
                }
                match duration.as_str() {
                    "static" => ip.static_buff += buff,
                    "battle" => ip.battle_buff += buff,
                    _ => ip.turn_buff += buff,
                }
            }
            true
        }
        // 「相手の (filter) キャラ 2 枚の元々パワーを入れ替える」 (effects.py:6512、 OP14-017)。
        // AI は最弱と最強を入替 (= 弱体化最大化)。 既定 filter = power_le 9000。
        "swap_opp_power" => {
            let filt = v.get("filter").cloned().unwrap_or(json!({"power_le": 9000}));
            let opp = &state.players[opp_idx];
            let mut cands: Vec<usize> = (0..opp.characters.len())
                .filter(|&i| matches_filter_ip(&opp.characters[i], Some(&filt)))
                .collect();
            if cands.len() < 2 {
                return true; // Python は return False = 忠実な no-op
            }
            cands.sort_by_key(|&i| opp.characters[i].card.power);
            let (w, st) = (cands[0], cands[cands.len() - 1]);
            let wp = opp.characters[w].card.power;
            let sp = opp.characters[st].card.power;
            state.players[opp_idx].characters[w].turn_base_power_override = Some(sp);
            state.players[opp_idx].characters[st].turn_base_power_override = Some(wp);
            true
        }
        // 「このキャラはターンに N 回、 相手の効果で KO されない」 (effects.py:7170、 OP10-118)。
        "set_ko_per_turn_immune" => {
            let (tspec, n) = if v.is_object() {
                (
                    v.get("target").cloned().unwrap_or(Value::String("self".into())),
                    v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32,
                )
            } else {
                (Value::String("self".into()), v.as_i64().unwrap_or(1) as i32)
            };
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else {
                return false;
            };
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                ip.ko_per_turn_immune_max = ip.ko_per_turn_immune_max.max(n);
                if ip.ko_per_turn_immune_remaining < n {
                    ip.ko_per_turn_immune_remaining = n;
                }
            }
            true
        }
        // 「自分のキャラ 1 枚を手札に戻し、 戻したキャラと異なる色のコスト N 以下のキャラを登場」
        // (effects.py:5027、 OP01-002 / EB01-020)。 AI は (power, cost) 最小を戻し、 手札の
        // 異色候補から power 最大を登場。 ⚠ 登場は InPlay.of のみ (Python も on_play を発火しない)。
        "bounce_self_chara_then_play_diff_color" => {
            let cost_le = v.get("play_cost_le").and_then(|x| x.as_i64()).unwrap_or(2) as i32;
            if state.players[me_idx].characters.is_empty() {
                return true;
            }
            let me = &state.players[me_idx];
            // Python: min(key=(power, cost)) = 先頭優先
            let mut vi = 0usize;
            for i in 1..me.characters.len() {
                let k = (me.characters[i].power(), me.characters[i].card.cost);
                let b = (me.characters[vi].power(), me.characters[vi].card.cost);
                if k < b {
                    vi = i;
                }
            }
            let victim = state.players[me_idx].characters.remove(vi);
            let colors = victim.card.color.clone();
            let don = victim.attached_dons;
            state.players[me_idx].hand.push(victim.card);
            state.players[me_idx].don_rested += don;
            let me = &state.players[me_idx];
            let mut cands: Vec<usize> = (0..me.hand.len())
                .filter(|&i| {
                    let c = &me.hand[i];
                    c.category == crate::state::Category::Character
                        && c.cost <= cost_le
                        && !c.color.iter().any(|x| colors.contains(x))
                })
                .collect();
            if cands.is_empty() {
                return true;
            }
            // power 降順 (stable = 元順 tie-break)
            cands.sort_by(|&a, &b| me.hand[b].power.cmp(&me.hand[a].power));
            let card = state.players[me_idx].hand.remove(cands[0]);
            state.players[me_idx].characters.push(InPlay::of(card, true));
            true
        }
        // 「ドン!! -N」: 場のドン (コストエリア active→rested→付与ドン) を N 枚ドンデッキへ
        // (effects.py:4655 / _pay_don_from_field:791)。 戻した枚数 > 0 なら don-returned trigger。
        "pay_don" => {
            let n = v.as_i64().unwrap_or(0) as i32;
            let mut removed = 0i32;
            {
                let me = &mut state.players[me_idx];
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
            }
            if removed < n {
                // area 不足 → 付与ドンから (power 昇順で温存)。 Python は [*characters, leader] を
                // power でソートするので同じ順を作る。
                let me = &state.players[me_idx];
                let mut order: Vec<i32> = (0..me.characters.len() as i32).collect();
                order.push(-1); // leader
                order.sort_by_key(|&i| {
                    if i < 0 { me.leader.power() } else { me.characters[i as usize].power() }
                });
                for i in order {
                    if removed >= n {
                        break;
                    }
                    let me = &mut state.players[me_idx];
                    let ip = if i < 0 { &mut me.leader } else { &mut me.characters[i as usize] };
                    let take = (n - removed).min(ip.attached_dons);
                    ip.attached_dons -= take;
                    me.don_remaining_in_deck += take;
                    removed += take;
                }
            }
            if removed > 0 {
                state.last_returned_don_count = removed;
                // ⚠ Python(trigger_on_self_don_returned_to_deck) は enqueue → _maybe_resolve なので、
                //   **効果の解決中は後回し** になる (resolving=True で _maybe_resolve が no-op)。
                //   Rust が inline 発火していると 「KO が先に起きて盤面が縮む」 = 対象がズレる
                //   (OP06-075 のドン-1 → 相手 OP06-076 の KO、 2026-08-04 掃引)。 必ず enqueue。
if me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
                    enqueue_field_when(state, me_idx, "on_self_don_returned_to_deck");
                    if maybe_resolve(state).is_err() {
                        return false;
                    }
                }
            }
            true
        }
        // 「相手はカード N 枚を引く」 (effects.py:6799、 OP07-090)。
        "force_opp_draw" => {
            let n = if v.is_object() {
                v.get("count").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            for _ in 0..n {
                let o = &mut state.players[opp_idx];
                if o.deck.is_empty() {
                    break;
                }
                let c = o.deck.remove(0);
                let cid = c.card_id.clone();
                if let Some(p) = o.known_top_card_ids.iter().position(|x| *x == cid) {
                    o.known_top_card_ids.remove(p);
                }
                o.hand.push(c);
                o.cards_drawn_count += 1;
            }
            true
        }
        // ターン終了時まで KO 耐性付与 (effects.py:5656)。 target は str / dict / 既定 self。
        "prevent_ko" => {
            let tspec: Value = if v.is_string() {
                v.clone()
            } else if v.is_object() {
                v.get("target").cloned().unwrap_or_else(|| v.clone())
            } else {
                Value::String("self".into())
            };
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else {
                return false;
            };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).ko_immune_until_turn_end = true;
            }
            true
        }
        // 「自分の (filter) キャラ 1 枚につき 1 引き、 その後同数捨てる」 (effects.py:6661、 EB04-011)。
        "draw_per_self_chara_then_discard" => {
            let filt = v.get("filter").cloned();
            let cnt = state.players[me_idx]
                .characters
                .iter()
                .filter(|c| matches_filter_ip(&c, filt.as_ref()))
                .count();
            if cnt == 0 {
                return true;
            }
            if !execute_effect(&json!({"draw": cnt}), state, me_idx, src) {
                return false;
            }
            for _ in 0..cnt {
                let me = &mut state.players[me_idx];
                let Some(i) = worst_hand_idx(&me.hand, &me.known_hand_card_ids) else { break };
                let c = me.hand.remove(i);
                me.trash.push(c);
            }
            true
        }
        // マルチターゲット bounce (effects.py:7530、 OP04-044)。 spec ごとに現盤面へ解決し逐次処理。
        "return_to_hand_multi" => {
            let Some(list) = v.as_array() else { return true };
            let mut any = false;
            for spec in list {
                let tspec: Value = if spec.is_string() {
                    spec.clone()
                } else {
                    spec.get("target").cloned()
                        .unwrap_or(Value::String("one_opponent_character_any".into()))
                };
                let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else {
                    return false;
                };
                let toks: Vec<(usize, Option<u64>)> = targets
                    .iter()
                    .filter(|&&(_, sl)| matches!(sl, Slot::Char(_)))
                    .map(|&(pi, sl)| (pi, tag_src(state, pi, sl)))
                    .collect();
                for (pi, tok) in toks {
                    let Slot::Char(idx) = find_tagged(state, pi, tok) else { continue };
                    if pi != opp_idx {
                        // 自陣キャラの bounce (「自分の〜すべてを、 持ち主の手札に戻す」 ST26-001
                        // おそばマスク 等)。 Python は 2026-08-03 に分岐を追加 (effects.py の
                        // `elif t in me.characters`)。 置換 (replace_ko/leave) は通さず、
                        // 付与ドンはレストへ戻して手札に加えるだけ。
                let ip = state.players[pi].characters.remove(idx);
                        let don = ip.attached_dons;
                        state.players[pi].hand.push(ip.card);
                        state.players[pi].don_rested += don;
                        any = true;
                        continue;
                    }
                    {
                        let c = &state.players[pi].characters[idx];
                        if c.protect_from_opp_effect || c.static_ko_immune {
                            continue;
                        }
                    }
                    match try_replace_ko(state, pi, idx, true, "return_to_hand") {
                        Ok(true) => continue,
                        Ok(false) => {}
                        Err(e) => {
                            note_unknown_key("rth", &format!("replace: {e}"));
                            return false;
                        }
                    }
                let ip = state.players[pi].characters.remove(idx);
                    let don = ip.attached_dons;
                    state.players[pi].known_hand_card_ids.push(ip.card.card_id.clone());
                    state.players[pi].hand.push(ip.card);
                    state.players[pi].don_rested += don;
                    any = true;
                }
            }
            if any {
                if fire_leave_by_self_effect(state, me_idx).is_err()
                    || fire_field_when(state, me_idx, "on_opp_chara_returned_to_hand_by_self_effect")
                        .is_err()
                {
                    return false;
                }
            }
            true
        }
        // 「相手はこのバトル中、 コスト N 以下のキャラのブロッカーを発動できない」
        // (effects.py:6618、 OP02-061)。 duration に関わらず "ブロック不可" キーワード付与。
        "prevent_opp_blocker_for_cost_le" => {
            let cost_le = v.get("cost_le").and_then(|x| x.as_i64()).unwrap_or(5) as i32;
            for c in state.players[opp_idx].characters.iter_mut() {
                if c.card.cost <= cost_le {
                    c.granted_keywords.insert("ブロック不可".to_string());
                }
            }
            true
        }
        // このキャラ (発動元) 自身を KO (effects.py:3331、 OP16-014 マルコの replace_leave do)。
        // 【KO時】+【自分のキャラがKOされた時】を発火 (自分の効果なので by_opp_effect=false)。
        "ko_self" => {
            // KO victim 文脈 (victim_truly_original_power_ge / victim_feature_in) は match の外へ運ぶ。
            let (pi, removed_cid, don, ko_vic) = match src {
                Slot::Char(i) if i < state.players[me_idx].characters.len() => {
                note_ko_victim_negated(state, me_idx, i);
                let ip = state.players[me_idx].characters.remove(i);
                    let d = ip.attached_dons;
                    let cid = ip.card.card_id.clone();
                    let vic = ip.card.clone();
                    let vtop = ip.truly_original_power();
                    state.players[me_idx].trash.push(ip.card);
                    (Some(me_idx), Some(cid), d, Some((vic, vtop)))
                }
                Slot::Stage(i) if i < state.players[me_idx].stages.len() => {
                    let ip = state.players[me_idx].stages.remove(i);
                    let d = ip.attached_dons;
                    let cid = ip.card.card_id.clone();
                    let vic = ip.card.clone();
                    let vtop = ip.truly_original_power();
                    state.players[me_idx].trash.push(ip.card);
                    (Some(me_idx), Some(cid), d, Some((vic, vtop)))
                }
                _ => (None, None, 0, None),
            };
            if let (Some(pi), Some(cid)) = (pi, removed_cid) {
                state.players[pi].don_rested += don;
                let (kv, kvtop) = match ko_vic { Some((a, b)) => (Some(a), Some(b)), None => (None, None) };
                state.last_chara_ko_victim_card = kv; // Python は payload で victim を運ぶ (2026-08-11)
                state.rust_ko_victim_truly_original_power = kvtop;
                if fire_on_ko(state, pi, &cid, false).is_err()
                    || fire_field_when(state, pi, "on_self_chara_ko").is_err()
                {
                    return false;
                }
                state.last_chara_ko_victim_card = None;
            }
            true
        }
        // 「相手の手札 1 枚を公開し、 イベントなら相手ライフ N 枚をデッキ下へ」 (effects.py:6968、 OP01-063)。
        // AI は rng でランダム 1 枚公開 (Python と同じ MT 列を消費する)。
        "reveal_opp_hand_and_if_event_mill_life" => {
            let mill_n = if v.is_object() {
                v.get("mill_life").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                1
            };
            if state.players[opp_idx].hand.is_empty() {
                return true; // Python は return False = 忠実な no-op
            }
            let n = state.players[opp_idx].hand.len() as u64;
            let idx = state.rng_mut().randrange(n) as usize;
            let is_event = state.players[opp_idx].hand[idx].category == crate::state::Category::Event;
            if is_event {
                for _ in 0..mill_n {
                    let o = &mut state.players[opp_idx];
                    if o.life.is_empty() {
                        break;
                    }
                    let c = o.life.remove(0);
                    o.deck.push(c);
                }
            }
            true
        }
        // 自分のアクティブドン N 枚をレストにする (effects.py:5406)。
        "rest_self_don" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1) as i32
            } else {
                v.as_i64().unwrap_or(1) as i32
            };
            let me = &mut state.players[me_idx];
            let actual = n.min(me.don_active);
            me.don_active -= actual;
            me.don_rested += actual;
            true
        }
        // 「ドン!! -N: 相手のドンを N 枚ドンデッキに戻す」 (effects.py:4699)。 active 優先。
        "don_minus_opp" => {
            let n = if v.is_object() {
                v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32
            } else {
                v.as_i64().unwrap_or(1) as i32
            };
            // ⭐ 「相手は自身の場のドン!!を戻す」 = 持ち主 (相手) が選ぶ → レストから返す
            //    (cardqa_op_16 qid 59c4ab538c2d、 return_opp_don と同じ chooser 帰属)。
            //    OP16-074 のみが使用 (全走査済)。
            let opp = &mut state.players[opp_idx];
            let taken = n.min(opp.don_rested);
            opp.don_rested -= taken;
            opp.don_remaining_in_deck += taken;
            let more = (n - taken).min(opp.don_active);
            opp.don_active -= more;
            opp.don_remaining_in_deck += more;
            let removed = taken + more;
            // 公式 Q&A (cardqa_op_06 / op_02) で裁定済: 「相手のカードの効果で自分のドン!!が
            // ドン!!デッキに戻された時」 も 「場のドン!!が戻された時」 を満たす (= 発動できる)。
            // Python も 2026-08-04 に実装 (それまで両エンジンとも未発火だった)。
            // owner = **戻された側** = opp_idx。
            if removed > 0 {
                state.last_returned_don_count = removed;
                if me_board_has_when(state, opp_idx, "on_self_don_returned_to_deck") {
                    enqueue_field_when(state, opp_idx, "on_self_don_returned_to_deck");
                    if maybe_resolve(state).is_err() {
                        return false;
                    }
                }
            }
            true
        }
        // 「デッキ上 N 枚を見て好きな順に並べ替え上に置く」 (effects.py:8033、 OP06-059)。
        // AI = (トリガー有, カウンター, パワー) 降順で上に。
        "scry_deck_reorder" => {
            let depth = if v.is_object() {
                v.get("depth").and_then(|x| x.as_i64()).unwrap_or(1) as usize
            } else {
                v.as_i64().unwrap_or(1) as usize
            };
            let me = &mut state.players[me_idx];
            if me.deck.is_empty() {
                return true; // Python は return False = 忠実な no-op
            }
            let d = depth.min(me.deck.len());
            let mut seen: Vec<crate::state::CardDef> = me.deck.drain(..d).collect();
            seen.sort_by(|a, b| {
                let ka = (!a.trigger.is_empty() as i32, a.counter, a.power);
                let kb = (!b.trigger.is_empty() as i32, b.counter, b.power);
                kb.cmp(&ka)
            });
            for (i, c) in seen.into_iter().enumerate() {
                me.deck.insert(i, c);
            }
            true
        }
        // 「自分か相手のライフ上 N 枚を見て上か下に置く」 (effects.py:8073、 ST20-003)。
        // AI = 自ライフなら価値高を上、 相手ライフなら価値低を上。
        "view_life_top_choose_position" => {
            let (owner, depth) = if v.is_object() {
                (
                    v.get("owner").and_then(|x| x.as_str()).unwrap_or("self").to_string(),
                    v.get("depth").and_then(|x| x.as_i64()).unwrap_or(1) as usize,
                )
            } else {
                ("self".to_string(), v.as_i64().unwrap_or(1) as usize)
            };
            let is_self = owner == "self" || owner == "either";
            let pi = if is_self { me_idx } else { opp_idx };
            if state.players[pi].life.is_empty() {
                return true;
            }
            let d = depth.min(state.players[pi].life.len());
            let mut seen: Vec<crate::state::CardDef> =
                state.players[pi].life.drain(..d).collect();
            let key = |c: &crate::state::CardDef| (!c.trigger.is_empty() as i32, c.counter, c.power);
            if is_self {
                seen.sort_by(|a, b| key(b).cmp(&key(a)));
            } else {
                seen.sort_by(|a, b| key(a).cmp(&key(b)));
            }
            for (i, c) in seen.into_iter().enumerate() {
                state.players[pi].life.insert(i, c);
            }
            true
        }
        // 「相手のレストのリーダー/キャラ N 枚は次の相手リフレッシュでアクティブにならない」
        // (effects.py:6995、 OP07-059)。 AI = power 降順。
        "keep_opp_rested_inplay_next_refresh" => {
            let limit = v.get("limit").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let opp = &state.players[opp_idx];
            // Python の cands 順 = [leader (rested なら), *rested characters]
            let mut cands: Vec<(Slot, i32)> = vec![];
            if opp.leader.rested {
                cands.push((Slot::Leader, opp.leader.power()));
            }
            for i in 0..opp.characters.len() {
                if opp.characters[i].rested {
                    cands.push((Slot::Char(i), opp.characters[i].power()));
                }
            }
            if cands.is_empty() {
                return true; // Python は return False = 忠実な no-op
            }
            cands.sort_by(|a, b| b.1.cmp(&a.1)); // _threat_key = power 降順 (stable)
            for (sl, _) in cands.into_iter().take(limit) {
                get_ip_mut(&mut state.players[opp_idx], sl).stay_rested_next_refresh = true;
            }
            true
        }
        // 「次の相手のメインフェイズ開始時に〜」 の予約 (effects.py:5976、 PRB02-005)。
        "schedule_at_opp_main_phase_start" => {
            state.players[me_idx].delayed_at_opp_main_phase_start.push(v.clone());
            true
        }
        // 「自分のキャラすべてはこのターン中、 バトルKO される場合代わりに手札1捨て」
        // (effects.py:grant_turn_battle_ko_save_discard、 EB02-030)。
        // ⚠ 「自分のキャラすべて」 は発動時点で場にいるキャラのスナップショット。 発動後に
        //   登場したキャラは対象外 (cardqa_eb_02) なので per-InPlay フラグを現在の各キャラに付与。
        "grant_turn_battle_ko_save_discard" => {
            for ch in state.players[me_idx].characters.iter_mut() {
                ch.battle_ko_save_discard_until_turn_end = true;
            }
            true
        }
        // 「デッキ上 N 枚をトラッシュ。 (filter) だった場合 then」 (effects.py:6180、 OP08-096)。
        "mill_top_then" => {
            let n = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1);
            let filt = v.get("filter").cloned();
            let mut matched = false;
            for _ in 0..n {
                let me = &mut state.players[me_idx];
                if me.deck.is_empty() {
                    break;
                }
                let c = me.deck.remove(0);
                if matches_filter(&c, filt.as_ref()) {
                    matched = true;
                }
                me.trash.push(c);
            }
            if matched {
                if let Some(then) = v.get("then").and_then(|x| x.as_array()).cloned() {
                    for es in &then {
                        if !execute_effect(es, state, me_idx, src) {
                            return false;
                        }
                    }
                }
            }
            true
        }
        // 「自分の特徴 X を持つステージ 1 枚をデッキから場に出す」 (effects.py:6372、 OP13-079)。
        // 既存ステージは trash (付与ドンはレストへ)。 最後にデッキをシャッフル。
        "summon_stage_from_deck_with_feature" => {
            let feature = if v.is_object() {
                v.get("feature").and_then(|x| x.as_str()).unwrap_or("").to_string()
            } else {
                v.as_str().unwrap_or("").to_string()
            };
            let found = (0..state.players[me_idx].deck.len()).find(|&i| {
                let c = &state.players[me_idx].deck[i];
                c.category == crate::state::Category::Stage && c.features.iter().any(|f| f == &feature)
            });
            if let Some(i) = found {
                let card = state.players[me_idx].deck.remove(i);
                while !state.players[me_idx].stages.is_empty() {
                    let old = state.players[me_idx].stages.remove(0);
                    let ad = old.attached_dons;
                    state.players[me_idx].trash.push(old.card);
                    state.players[me_idx].don_rested += ad;
                }
                state.players[me_idx].stages.push(InPlay::of(card, false));
            }
            let len = state.players[me_idx].deck.len();
            let perm = state.rng_mut().shuffle_perm(len);
            let old = std::mem::take(&mut state.players[me_idx].deck);
            state.players[me_idx].deck = perm.iter().map(|&j| old[j].clone()).collect();
            state.players[me_idx].known_bottom_card_ids.clear();
            state.players[me_idx].known_top_card_ids.clear();
            true
        }
        // 「相手はアクティブドン 1 枚をドンデッキに戻してもよい。 しなかった場合 (target) -N」
        // (effects.py:6788、 OP15-059)。 opp モデル = ドンがあれば返して debuff を回避。
        "opp_may_return_active_don_else_debuff" => {
            let amount = v.get("amount").and_then(|x| x.as_i64()).unwrap_or(-2000);
            let tspec = v.get("target").cloned()
                .unwrap_or(Value::String("one_opponent_inplay_any".into()));
            if state.players[opp_idx].don_active >= 1 {
                state.players[opp_idx].don_active -= 1;
                state.players[opp_idx].don_remaining_in_deck += 1;
                true
            } else {
                let prim = json!({"power_pump": {
                    "target": tspec, "amount": amount, "duration": "turn"
                }});
                execute_effect(&prim, state, me_idx, src)
            }
        }
        // 「自分の場のキャラを任意の枚数手札に戻してよい。 (target) は戻した 1 枚につき +M」
        // (effects.py:6750、 P-059)。 AI = pump 対象以外を全戻し。
        "return_self_charas_then_pump_per" => {
            let amount = v.get("amount").and_then(|x| x.as_i64()).unwrap_or(2000);
            let duration = v.get("duration").and_then(|x| x.as_str()).unwrap_or("battle").to_string();
            let tspec = v.get("target").cloned().unwrap_or(Value::String("self_inplay".into()));
            let pump_slot = resolve_target(Some(&tspec), me_idx, opp_idx, src, state)
                .and_then(|ts| ts.into_iter().next());
            let keep = match pump_slot {
                Some((pi, Slot::Char(i))) if pi == me_idx => Some(i),
                _ => None,
            };
            let mut returned = 0i64;
            let me = &mut state.players[me_idx];
            let old = std::mem::take(&mut me.characters);
            for (i, c) in old.into_iter().enumerate() {
                if Some(i) == keep {
                    me.characters.push(c);
                    continue;
                }
                let don = c.attached_dons;
                me.hand.push(c.card);
                me.don_rested += don;
                returned += 1;
            }
            if pump_slot.is_some() && returned > 0 {
                let prim = json!({"power_pump": {
                    "target": tspec, "amount": amount * returned, "duration": duration
                }});
                return execute_effect(&prim, state, me_idx, src);
            }
            true
        }
        // 「手札から (filter) キャラ N 枚までを任意で 0 コスト登場」 (effects.py:5206、 OP11-024)。
        // AI = cost 降順 → power 降順 → name 昇順 で limit 枚。 hand は降順 pop。
        "play_from_hand_choice" => {
            let filt = v.get("filter").cloned();
            let limit = v.get("limit").and_then(|x| x.as_i64()).unwrap_or(1).max(0) as usize;
            let rested = v.get("rested").and_then(|x| x.as_bool()).unwrap_or(false);
            let cat = match v.get("category").and_then(|x| x.as_str()).unwrap_or("CHARACTER") {
                "STAGE" => crate::state::Category::Stage,
                "EVENT" => crate::state::Category::Event,
                _ => crate::state::Category::Character,
            };
            let me = &state.players[me_idx];
            let mut cands: Vec<usize> = (0..me.hand.len())
                .filter(|&i| {
                    me.hand[i].category == cat
                        && matches_filter(&me.hand[i], filt.as_ref())
                        && !card_no_play_via_effect(&me.hand[i].card_id)
                })
                .collect();
            cands.sort_by(|&a, &b| {
                let (ca, cb) = (&me.hand[a], &me.hand[b]);
                (-cb.cost, -cb.power, ca.name.clone()).cmp(&(-ca.cost, -ca.power, cb.name.clone()))
            });
            cands.truncate(limit);
            cands.sort_unstable_by(|a, b| b.cmp(a)); // hand pop は降順
            let cards: Vec<crate::state::CardDef> =
                cands.iter().map(|&i| state.players[me_idx].hand.remove(i)).collect();
            for card in cards {
                if place_played_card(state, me_idx, card, rested, cat).is_err() {
                    return false;
                }
            }
            true
        }
        // 「自分のトラッシュの (filter) イベント 1 枚の【メイン】効果を発動」 (effects.py:6400、 EB03-031)。
        // AI = trash 順で先頭 1 枚。 イベントはトラッシュに残る。 再帰は fire_self_depth で制限。
        "fire_event_main_from_trash" => {
            let filt = v.get("filter").cloned();
            let chosen = state.players[me_idx]
                .trash
                .iter()
                .find(|c| {
                    c.category == crate::state::Category::Event && matches_filter(c, filt.as_ref())
                })
                .map(|c| c.card_id.clone());
            let Some(cid) = chosen else { return true };
            // main 効果を再発火 (fire_self_effect と同じ経路 = 条件/cost/cascade は共通ガード)。
            let prim = json!({"fire_self_effect": {"when_kind": "main", "_card_id": cid}});
            execute_effect(&prim, state, me_idx, src)
        }
        // setup_modifier 専用 (ゲーム開始時のドンデッキ枚数)。 do として実行される文脈は無いが、
        // 万一走っても no-op が正しい (実際の反映は deck の don_deck_size で行う)。
        "set_don_deck_size" => true,
        // 「自分のライフの上から N 枚を表向きにする」 (effects.py:6831)。
        "flip_life_face_up_effect" => {
            let n = if v.is_object() {
                v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32
            } else {
                v.as_i64().unwrap_or(1) as i32
            };
            let me = &mut state.players[me_idx];
            me.face_up_life_count = (me.face_up_life_count + n).min(me.life.len() as i32);
            true
        }
        // 「自分の付与ドン N 枚までを、 特徴 X を持つ自キャラ 1 枚に付与する」
        // (effects.py:6924、 EB02-009)。 AI = 移動元は power 昇順の先頭、 移動先は特徴一致の先頭。
        "transfer_attached_don_to_feature" => {
            let feature = v.get("feature").and_then(|x| x.as_str()).unwrap_or("").to_string();
            let count = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32;
            let me = &state.players[me_idx];
            // 取り出し元 = leader + characters のうち attached_dons > 0 (Python の順)
            let mut sources: Vec<(Slot, i32)> = vec![];
            if me.leader.attached_dons > 0 {
                sources.push((Slot::Leader, me.leader.power()));
            }
            for i in 0..me.characters.len() {
                if me.characters[i].attached_dons > 0 {
                    sources.push((Slot::Char(i), me.characters[i].power()));
                }
            }
            if sources.is_empty() {
                return true; // Python は return False = 忠実な no-op
            }
            let target = (0..me.characters.len())
                .find(|&i| me.characters[i].card.features.iter().any(|f| f == &feature));
            let Some(ti) = target else { return true };
            sources.sort_by(|a, b| a.1.cmp(&b.1)); // power 昇順 (stable)
            let src_slot = sources[0].0;
            if src_slot == Slot::Char(ti) {
                return true; // 同一カード間の移動は無意味 (Python も実質 no-op)
            }
            let moved = {
                let ip = get_ip_mut(&mut state.players[me_idx], src_slot);
                let m = count.min(ip.attached_dons);
                ip.attached_dons -= m;
                m
            };
            state.players[me_idx].characters[ti].attached_dons += moved;
            true
        }
        // 「このキャラ以外のキャラすべてを KO」 (effects.py:7375、 OP01-094 カイドウ)。
        // Python の順: 自陣 (発動元を除く) → 相手陣、 各 victim ごとに耐性/置換/KO時トリガー、
        // 最後に on_self_chara_leave_by_self_effect を 1 回。 タグ追跡で盤面ずれを吸収する。
        "ko_all_others" => {
            let src_idx = if let Slot::Char(i) = src { Some(i) } else { None };
            let mut toks: Vec<(usize, Option<u64>)> = vec![];
            for i in 0..state.players[me_idx].characters.len() {
                if Some(i) == src_idx {
                    continue;
                }
                let t = tag_src(state, me_idx, Slot::Char(i));
                toks.push((me_idx, t));
            }
            for i in 0..state.players[opp_idx].characters.len() {
                let t = tag_src(state, opp_idx, Slot::Char(i));
                toks.push((opp_idx, t));
            }
            let mut ko_any = false;
            for (pi, tok) in toks {
                let Slot::Char(idx) = find_tagged(state, pi, tok) else { continue };
                let by_opp = pi == opp_idx; // victim から見て「相手の効果」か
                {
                    let t = &mut state.players[pi].characters[idx];
                    if by_opp && t.protect_from_opp_effect {
                        continue;
                    }
                    if t.ko_per_turn_immune_remaining > 0 {
                        t.ko_per_turn_immune_remaining -= 1;
                        continue;
                    }
                    if t.ko_immune_until_turn_end || t.static_ko_immune || t.ko_immune_through_opp_turn {
                        continue;
                    }
                }
                match try_replace_ko(state, pi, idx, by_opp, "ko") {
                    Ok(true) => continue,
                    Ok(false) => {}
                    Err(_) => return false,
                }
                let vcid = state.players[pi].characters[idx].card.card_id.clone();
                note_ko_victim_negated(state, pi, idx);
                let ip = state.players[pi].characters.remove(idx);
                let don = ip.attached_dons;
                let _ko_vic = ip.card.clone();
                let _ko_vtop = ip.truly_original_power(); // KO 時点の元々のパワー (公式 4-9-2-1) // KO victim 文脈 (victim_truly_original_power_ge / victim_feature_in 用)
                state.players[pi].trash.push(ip.card);
                state.players[pi].don_rested += don;
                if by_opp {
                }
                ko_any = true;
                state.last_chara_ko_victim_card = Some(_ko_vic);
                state.rust_ko_victim_truly_original_power = Some(_ko_vtop); // Python は payload で victim を運ぶ (2026-08-11)
                if fire_on_ko(state, pi, &vcid, by_opp).is_err() {
                    return false;
                }
                // 相手 victim のときだけ 発動側の【相手のキャラがKOされた時】が発火する。
                if by_opp && fire_field_when(state, me_idx, "on_opp_chara_ko").is_err() {
                    return false;
                }
                if fire_field_when(state, pi, "on_self_chara_ko").is_err() {
                    return false;
                }
                state.last_chara_ko_victim_card = None;
            }
            if ko_any && fire_leave_by_self_effect(state, me_idx).is_err()
            {
                return false;
            }
            true
        }
        // このキャラをトラッシュに置く (effects.py:7761)。 付与ドンはレストへ。
        "return_self_to_trash" => {
            if let Slot::Char(i) = src {
                if i < state.players[me_idx].characters.len() {
                let ip = state.players[me_idx].characters.remove(i);
                    let don = ip.attached_dons;
                    state.players[me_idx].don_rested += don;
                    state.players[me_idx].trash.push(ip.card);
                }
            }
            true
        }
        // 「A するか B する」 (effects.py:9062)。 AI heuristic: life_count なら 自ライフ≤1 で option 1、
        // それ以外は option 0 (公式テキスト先頭)。
        "choice" => {
            let (options, heuristic) = if v.is_object() {
                (
                    v.get("options").and_then(|x| x.as_array()).cloned().unwrap_or_default(),
                    // Python の既定は "life_count" (effects.py:9091 spec_val.get(..., "life_count"))
                    v.get("heuristic").and_then(|x| x.as_str()).unwrap_or("life_count").to_string(),
                )
            } else {
                (v.as_array().cloned().unwrap_or_default(), "life_count".to_string())
            };
            if options.is_empty() {
                return true;
            }
            let mut idx = 0usize;
            if heuristic == "life_count" && state.players[me_idx].life.len() <= 1 && options.len() >= 2 {
                idx = 1;
            }
            // chosen は do リスト or {"do": [...]} のどちらも許容 (Python 同様)。
            let chosen = &options[idx];
            let inner: Vec<Value> = if let Some(d) = chosen.get("do").and_then(|x| x.as_array()) {
                d.clone()
            } else if let Some(a) = chosen.as_array() {
                a.clone()
            } else {
                vec![chosen.clone()]
            };
            for sub in &inner {
                if !execute_effect(sub, state, me_idx, src) {
                    return false;
                }
            }
            true
        }
        "other_self_charas_to_deck_bottom" => {
            if me_board_has_when(state, me_idx, "on_self_chara_leave_by_self_effect") {
                return false; // leave cascade 再現不能 → bail
            }
            let src_idx = if let Slot::Char(i) = src { Some(i) } else { None };
            let victims: Vec<(usize, usize)> = (0..state.players[me_idx].characters.len())
                .filter(|&i| Some(i) != src_idx)
                .map(|i| (me_idx, i))
                .collect();
            if !victims.is_empty() {
                remove_victims(state, victims, RemoveDest::DeckBottom);
            }
            true
        }
        // 「このターン中【ブロッカー】を発動できない」 (effects.py:disable_blocker、 OP12-051 等)。
        "disable_blocker" => {
            let tspec = if v.is_object() {
                v.get("target").cloned().unwrap_or(Value::String("one_opponent_character_any".into()))
            } else {
                v.clone()
            };
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).blocker_disabled_until_turn_end = true;
            }
            true
        }
        // 「このカードの【メイン】効果を発動する」= fire_self_effect(when_kind="main") の shorthand。
        "fire_self_main" => {
            let spec = json!({"when_kind": "main"});
            execute_effect(&json!({"fire_self_effect": spec}), state, me_idx, src)
        }
        // 「(条件) でない場合、 このキャラを持ち主のデッキの下に置く」 (effects.py、 P-098 等)。
        "return_self_to_deck_bottom_if_condition" => {
            let cond = v.get("if_not");
            if let Some(c) = cond {
                match eval_condition(c, state, me_idx, Some(src)) {
                    Some(true) => return true,  // 条件成立 → 発動しない (no-op)
                    Some(false) => {}
                    None => return false,       // 条件不明 → bail
                }
            }
            let Slot::Char(i) = src else { return true };
            if i >= state.players[me_idx].characters.len() {
                return true;
            }
            if me_board_has_when(state, me_idx, "on_self_chara_leave_by_self_effect") {
                return false; // leave cascade 再現不能
            }
            let me = &mut state.players[me_idx];
            let removed = me.characters.remove(i);
            me.don_rested += removed.attached_dons;
            me.deck.push(removed.card);
            true
        }
        // ⭐ 公式 「**相手は**(自身の)手札N枚を捨てる」 = **手札の持ち主 (相手) が選ぶ**
        // (cardqa_op_01「手札の持ち主である相手が選びます」/ cardqa_st_18)。
        // ⚠ 対照: 「**相手の**手札N枚を捨てる」 は発動者が **裏向きで** 選ぶ (cardqa_op_03/st_10)
        //   = ランダムが忠実なモデル → そちらは trash_opp_hand_random のまま。
        // AI は worst_hand_idx (= counter 低 → cost 低 → power 低。 防御札を温存)。
        "opp_discard_own_choice" => {
            let n = if v.is_object() {
                v.get("amount").or_else(|| v.get("count")).and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            // 人間相手の pick は Python が pending_choice で halt するので、 ここには
            // AI 経路 (= 選択の余地なし or AI 所有) だけが来る。 picks 注入経路も同順で処理。
            // 「相手は自身の手札を捨てる」= 持ち主 (opp) が捨てる → その opp 視点で
            // 「効果で手札が捨てられた」を発火 (Python trigger_on_self_hand_discarded(opp,…))。
            // cascade を要する場合は Python に委ねて bail (flag のみ Rust で立てる)。
            let mut moved = 0i32;
            if let Some(picks) = v.get("_opp_hand_picks").and_then(|x| x.as_array()) {
                let mut idxs: Vec<usize> = picks
                    .iter()
                    .filter_map(|x| x.as_i64())
                    .map(|i| i as usize)
                    .collect();
                idxs.sort_unstable();
                idxs.dedup();
                let o = &mut state.players[opp_idx];
                for i in idxs.into_iter().rev() {
                    if i < o.hand.len() {
                        let c = o.hand.remove(i);
                        o.trash.push(c);
                        moved += 1;
                    }
                }
                if moved > 0 {
                    if me_board_has_when(state, opp_idx, "on_self_hand_discarded") {
                        return false;
                    }
                    state.players[opp_idx].hand_discarded_by_effect_this_turn = true;
                }
                return true;
            }
            for _ in 0..n {
                let o = &mut state.players[opp_idx];
                if o.hand.is_empty() {
                    break;
                }
                let Some(i) = worst_hand_idx(&o.hand, &o.known_hand_card_ids) else { break };
                let c = o.hand.remove(i);
                o.trash.push(c);
                moved += 1;
            }
            if moved > 0 {
                if me_board_has_when(state, opp_idx, "on_self_hand_discarded") {
                    return false;
                }
                state.players[opp_idx].hand_discarded_by_effect_this_turn = true;
            }
            true
        }
        // 相手は自身の手札 N 枚をデッキ下へ (effects.py:opp_hand_to_deck_bottom)。 AI は worst_hand_idx。
        "opp_hand_to_deck_bottom" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            };
            for _ in 0..n {
                let o = &mut state.players[opp_idx];
                if o.hand.is_empty() {
                    break;
                }
                let Some(i) = worst_hand_idx(&o.hand, &o.known_hand_card_ids) else { break };
                let c = o.hand.remove(i);
                o.deck.push(c);
            }
            true
        }
        // 期間限定のコスト変更 (effects.py:set_base_cost_timed、 EB02-041 メリー号等)。
        // spec {target, amount | delta, duration}。 amount は絶対値、 delta は現在値からの増減 (下限 0)。
        "set_base_cost_timed" => {
            let tspec = v.get("target").cloned().unwrap_or(Value::String("self".into()));
            let duration = v.get("duration").and_then(|x| x.as_str()).unwrap_or("next_opp_turn_end").to_string();
            let amount = v.get("amount").and_then(|x| x.as_i64());
            let delta = v.get("delta").and_then(|x| x.as_i64()).unwrap_or(0);
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
            let turn = state.turn_number;
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                let new_val = match amount {
                    Some(a) => a as i32,
                    None => {
                        let cur = ip
                            .next_opp_turn_end_base_cost_override
                            .or(ip.base_cost_override)
                            .unwrap_or(ip.card.cost);
                        (cur + delta as i32).max(0)
                    }
                };
                ip.next_opp_turn_end_base_cost_override = Some(new_val);
                if duration == "next_opp_turn_end" {
                    ip.next_opp_turn_end_base_cost_override_applier_idx = me_idx as i32;
                    ip.next_opp_turn_end_base_cost_override_applied_turn = turn;
                }
            }
            true
        }
        // 自分の filter 一致キャラに「次の相手ターン終了時まで効果で KO されない」(OP09-033)。
        "give_ko_immune_through_opp_turn" => {
            let filt = v.get("filter");
            for c in state.players[me_idx].characters.iter_mut() {
                if matches_filter_ip(&c, filt) {
                    c.ko_immune_through_opp_turn = true;
                }
            }
            true
        }
        // 【トリガー】「このカードを手札に加える」 (effects.py:to_hand_self_trigger)。 flag のみ。
        "to_hand_self_trigger" => {
            state.last_trigger_kept_in_hand = true;
            true
        }
        // 「(範囲) のキャラ N 枚までをレストにする」 (effects.py:rest_multi)。 dict 形 {target,count} は
        // 全解決 → active かつレスト可能を power 降順に count 体。 list 形は各 spec を順に解決。
        "rest_multi" => {
            let do_rest = |state: &mut GameState, targets: Vec<(usize, Slot)>, count: usize| {
                let mut cands: Vec<(usize, Slot, i32)> = targets
                    .into_iter()
                    .filter(|&(pi, sl)| {
                        let ip = get_ip(&state.players[pi], sl);
                        !ip.rested && !ip.cannot_be_rested_buff && !ip.static_cannot_be_rested
                    })
                    .map(|(pi, sl)| {
                        let p = get_ip(&state.players[pi], sl).power();
                        (pi, sl, p)
                    })
                    .collect();
                cands.sort_by(|a, b| b.2.cmp(&a.2)); // power 降順
                for (pi, sl, _) in cands.into_iter().take(count) {
                    get_ip_mut(&mut state.players[pi], sl).rested = true;
                }
            };
            if v.is_object() && v.get("count").is_some() {
                let tspec = v.get("target").cloned().unwrap_or(Value::String("any_opponent_character_any".into()));
                let count = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
                let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
                do_rest(state, targets, count);
                return true;
            }
            let Some(list) = v.as_array() else { return false };
            for spec in list {
                // 「相手のキャラかドン」 特殊 spec (effects.py:3725、 OP06-035)。 resolve_target は
                // ドンを表現できないので専用分岐: アクティブ相手キャラ (power 降順) 優先 → 無ければ
                // アクティブドン 1 枚をレスト。
                let is_chara_or_don = spec.as_str() == Some("one_opp_chara_or_don")
                    || spec.get("type").and_then(|x| x.as_str()) == Some("one_opp_chara_or_don");
                if is_chara_or_don {
                    let cost_le = spec.get("cost_le").and_then(|x| x.as_i64()).map(|x| x as i32);
                    let opp = &state.players[opp_idx];
                    let mut cands: Vec<usize> = (0..opp.characters.len())
                        .filter(|&i| {
                            let c = &opp.characters[i];
                            !c.rested
                                && !c.cannot_be_rested_buff
                                && !c.static_cannot_be_rested
                                && cost_le.map_or(true, |n| c.card.cost <= n)
                        })
                        .collect();
                    cands.sort_by(|&a, &b| opp.characters[b].power().cmp(&opp.characters[a].power()));
                    if let Some(&i) = cands.first() {
                        state.players[opp_idx].characters[i].rested = true;
                    } else if state.players[opp_idx].don_active > 0 {
                        state.players[opp_idx].don_active -= 1;
                        state.players[opp_idx].don_rested += 1;
                    }
                    continue;
                }
                let Some(targets) = resolve_target(Some(spec), me_idx, opp_idx, src, state) else { return false };
                do_rest(state, targets, 1);
            }
            true
        }
        // 「トラッシュに置く」= 非 KO の離場 (effects.py:chara_to_trash)。 KO 耐性は受けず【KO時】も
        // 発動しないが、 protect_from_opp_effect と replace_leave / leave トリガーは効く → cascade は bail。
        "chara_to_trash" => {
            let Some(targets) = resolve_target(Some(v), me_idx, opp_idx, src, state) else {
                return false;
            };
            // Python (effects.py:3500) は解決順に 1 体ずつ処理する (置換で盤面が動く)。 タグで追う。
            let toks: Vec<(usize, Option<u64>)> = targets
                .iter()
                .filter(|&&(_, sl)| matches!(sl, Slot::Char(_)))
                .map(|&(pi, sl)| (pi, tag_src(state, pi, sl)))
                .collect();
            let mut any = false;
            for (pi, tok) in toks {
                let Slot::Char(idx) = find_tagged(state, pi, tok) else { continue };
                if pi == opp_idx {
                    if state.players[pi].characters[idx].protect_from_opp_effect {
                        continue;
                    }
                    match try_replace_ko(state, pi, idx, true, "chara_to_trash") {
                        Ok(true) => continue,
                        Ok(false) => {}
                        Err(_) => return false,
                    }
                }
                let ip = state.players[pi].characters.remove(idx);
                let don = ip.attached_dons;
                let departed = ip.card.clone();
                state.players[pi].trash.push(ip.card);
                state.players[pi].don_rested += don;
                if pi == me_idx {
                    // 自陣の 「トラッシュに置く」 = 公開領域 (cardqa_op_08、 Python も me 側のみ記録)
                    note_public_departure(state, me_idx, &departed);
                }
                any = true;
            }
            if any
                && fire_leave_by_self_effect(state, me_idx).is_err()
            {
                return false;
            }
            true
        }
        // 自ライフ全部を見て 1 枚をデッキへ + 残りを並べ替え (effects.py:scry_all_life_one_to_deck)。
        // AI 判断 = 価値 (トリガー有無, カウンター, パワー) 最大をデッキへ、 残りも価値降順でライフに積む。
        "scry_all_life_one_to_deck" => {
            if state.players[me_idx].life.is_empty() {
                return true; // ライフ空 = 不発
            }
            let to_bottom = v.get("to").and_then(|x| x.as_str()) == Some("bottom");
            let mut life = std::mem::take(&mut state.players[me_idx].life);
            let key = |c: &crate::state::CardDef| {
                (if c.trigger.is_empty() { 0 } else { 1 }, c.counter, c.power)
            };
            life.sort_by(|a, b| key(b).cmp(&key(a))); // 価値降順 (安定 = tie は元順)
            let to_deck = life.remove(0);
            state.players[me_idx].life = life;
            if to_bottom {
                state.players[me_idx].deck.push(to_deck);
            } else {
                state.players[me_idx].deck.insert(0, to_deck);
            }
            true
        }
        // 「相手のキャラ N 枚までを、 パワー合計が X 以下になるように KO」 (effects.py:ko_total_power_le)。
        // AI = 合計 <= cap の組合せのうち (除去 power 合計, 枚数) 最大。 ⚠ KO cascade 盤面は bail。
        "ko_total_power_le" => {
            let max_count = v.get("max_count").and_then(|x| x.as_i64()).unwrap_or(2) as usize;
            let cap = v.get("total_power_le").and_then(|x| x.as_i64()).unwrap_or(4000) as i32;
            let pool: Vec<usize> = (0..state.players[opp_idx].characters.len())
                .filter(|&i| {
                    let c = &state.players[opp_idx].characters[i];
                    !(c.protect_from_opp_effect
                        || c.static_ko_immune
                        || c.ko_immune_until_turn_end
                        || c.ko_immune_through_opp_turn
                        || c.ko_per_turn_immune_remaining > 0)
                })
                .collect();
            // 全組合せ (pool は最大 5 なので 2^5 で十分)
            let mut best: Vec<usize> = vec![];
            let mut best_key = (-1i32, -1i64);
            for mask in 1u32..(1u32 << pool.len()) {
                let combo: Vec<usize> = (0..pool.len())
                    .filter(|&b| mask & (1 << b) != 0)
                    .map(|b| pool[b])
                    .collect();
                if combo.len() > max_count {
                    continue;
                }
                let sum: i32 = combo.iter().map(|&i| state.players[opp_idx].characters[i].power()).sum();
                if sum <= cap {
                    let key = (sum, combo.len() as i64);
                    if key > best_key {
                        best_key = key;
                        best = combo;
                    }
                }
            }
            if best.is_empty() {
                return true;
            }
            // ko と同じ逐次処理 (タグ追跡 + 置換 + KO cascade)。
            let toks: Vec<Option<u64>> =
                best.into_iter().map(|i| tag_src(state, opp_idx, Slot::Char(i))).collect();
            let mut ko_any = false;
            for tok in toks {
                let Slot::Char(idx) = find_tagged(state, opp_idx, tok) else { continue };
                match try_replace_ko(state, opp_idx, idx, true, "ko") {
                    Ok(true) => continue,
                    Ok(false) => {}
                    Err(_) => return false,
                }
                let vcid = state.players[opp_idx].characters[idx].card.card_id.clone();
                note_ko_victim_negated(state, opp_idx, idx);
                let ip = state.players[opp_idx].characters.remove(idx);
                let don = ip.attached_dons;
                let _ko_vic = ip.card.clone();
                let _ko_vtop = ip.truly_original_power(); // KO 時点の元々のパワー (公式 4-9-2-1) // KO victim 文脈 (victim_truly_original_power_ge / victim_feature_in 用)
                state.players[opp_idx].trash.push(ip.card);
                state.players[opp_idx].don_rested += don;
                ko_any = true;
                state.last_chara_ko_victim_card = Some(_ko_vic);
                state.rust_ko_victim_truly_original_power = Some(_ko_vtop); // Python は payload で victim を運ぶ (2026-08-11)
                if fire_on_ko(state, opp_idx, &vcid, true).is_err()
                    || fire_field_when(state, me_idx, "on_opp_chara_ko").is_err()
                    || fire_field_when(state, opp_idx, "on_self_chara_ko").is_err()
                {
                    return false;
                }
                state.last_chara_ko_victim_card = None;
            }
            if ko_any && fire_leave_by_self_effect(state, me_idx).is_err()
            {
                return false;
            }
            true
        }
        // 相手は手札を全てデッキに戻しシャッフル → N 枚ドロー (effects.py:opp_hand_to_deck_then_draw)。
        "opp_hand_to_deck_then_draw" => {
            let n = if v.is_object() {
                v.get("draw").and_then(|x| x.as_i64()).unwrap_or(5)
            } else {
                v.as_i64().unwrap_or(5)
            };
            {
                let o = &mut state.players[opp_idx];
                let hand = std::mem::take(&mut o.hand);
                o.deck.extend(hand);
                o.known_bottom_card_ids.clear();
                o.known_top_card_ids.clear();
            }
            let len = state.players[opp_idx].deck.len();
            let perm = state.rng_mut().shuffle_perm(len);
            let old = std::mem::take(&mut state.players[opp_idx].deck);
            state.players[opp_idx].deck = perm.iter().map(|&j| old[j].clone()).collect();
            let o = &mut state.players[opp_idx];
            let mut drawn = 0;
            for _ in 0..n {
                if o.deck.is_empty() {
                    break;
                }
                let c = o.deck.remove(0);
                o.hand.push(c);
                drawn += 1;
            }
            o.cards_drawn_count += drawn;
            true
        }
        // 自ライフが N 枚になるように上からトラッシュ (effects.py:mill_self_life_until_n)。
        "mill_self_life_until_n" => {
            let target = if v.is_object() {
                v.get("target_count").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            }
            .max(0) as usize;
            while state.players[me_idx].life.len() > target {
                let c = state.players[me_idx].life.remove(0);
                state.players[me_idx].trash.push(c);
            }
            true
        }
        // 「次の相手ターン終了時まで相手の【登場時】効果を無効」(effects.py、 OP09-081 ティーチ)。
        "disable_opp_on_play_through_opp_turn" => {
            state.players[opp_idx].opp_on_play_disabled_through_opp_turn = true;
            true
        }
        // 「相手は自身の手札から (cost_le) キャラ N 枚までを登場させる」(effects.py:force_opp_play_from_hand)。
        // AI/人間とも最善は「出す」なので power 降順に count 体。 ⚠ require_prior_bounce は
        // 直前 bounce の成否 (Python の transient) が Rust に無いので bail (誤発火を作らない)。
        "force_opp_play_from_hand" => {
            // 「そうした場合 (= 直前 bounce が起きた場合)」 gate (effects.py:5420)。
            if v.get("require_prior_bounce").and_then(|x| x.as_bool()).unwrap_or(false)
                && !state.last_return_to_hand_success
            {
                return true; // Python は continue = 後続 primitive へ (no-op)
            }
            let cost_le = v.get("cost_le").and_then(|x| x.as_i64());
            let count = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let mut cands: Vec<usize> = (0..state.players[opp_idx].hand.len())
                .filter(|&i| {
                    let c = &state.players[opp_idx].hand[i];
                    c.category == crate::state::Category::Character
                        && cost_le.map_or(true, |n| c.cost as i64 <= n)
                })
                .collect();
            cands.sort_by(|&a, &b| {
                state.players[opp_idx].hand[b].power.cmp(&state.players[opp_idx].hand[a].power)
            });
            let mut picked: Vec<usize> = vec![];
            for &i in cands.iter() {
                if picked.len() >= count || state.players[opp_idx].characters.len() >= 5 {
                    break;
                }
                let card = state.players[opp_idx].hand[i].clone();
                state.players[opp_idx].characters.push(InPlay::of(card, true));
                picked.push(i);
            }
            picked.sort_unstable();
            for i in picked.into_iter().rev() {
                state.players[opp_idx].hand.remove(i);
            }
            true
        }
        // 自分の付与済ドン合計 N 枚までを自キャラ 1 枚に再配分 (effects.py:move_attached_don、 OP07-001)。
        // 付与元の優先度: レスト中キャラ → 他 active キャラ → リーダー (leader の付与ドンは最後)。
        "move_attached_don" => {
            let max_n = v
                .get("count")
                .or_else(|| v.get("amount"))
                .and_then(|x| x.as_i64())
                .unwrap_or(2) as i32;
            let tspec = v.get("target").cloned().unwrap_or(Value::String("one_self_character_any".into()));
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
            let Some(&(tpi, tsl)) = targets.first() else { return true };
            if tpi != me_idx {
                return true;
            }
            let tgt_idx = if let Slot::Char(i) = tsl { Some(i) } else { None };
            // 付与元候補を Python と同じ順で並べる
            let mut srcs: Vec<Slot> = vec![];
            {
                let me = &state.players[me_idx];
                for (i, c) in me.characters.iter().enumerate() {
                    if Some(i) != tgt_idx && c.rested && c.attached_dons > 0 {
                        srcs.push(Slot::Char(i));
                    }
                }
                for (i, c) in me.characters.iter().enumerate() {
                    if Some(i) != tgt_idx && !c.rested && c.attached_dons > 0 {
                        srcs.push(Slot::Char(i));
                    }
                }
                if !matches!(tsl, Slot::Leader) && me.leader.attached_dons > 0 {
                    srcs.push(Slot::Leader);
                }
            }
            let mut moved = 0;
            for sl in srcs {
                if moved >= max_n {
                    break;
                }
                let avail = get_ip(&state.players[me_idx], sl).attached_dons;
                let take = avail.min(max_n - moved);
                if take <= 0 {
                    continue;
                }
                get_ip_mut(&mut state.players[me_idx], sl).attached_dons -= take;
                moved += take;
            }
            if moved > 0 {
                get_ip_mut(&mut state.players[me_idx], tsl).attached_dons += moved;
            }
            true
        }
        // 手札から指定名を 1 枚ずつ登場 (effects.py:play_from_hand_named_set、 ST13-006 / OP16-116)。
        // ⚠ overlay の names は未正規化 → norm_card_name で全角Ｄ→D を揃える (揃えないと silent no-op)。
        // 手札除去は Python 同様「全部登場させてから降順 pop」= 登場時効果は手札を未除去で観測する。
        "play_from_hand_named_set" => {
            let names: Vec<String> = v
                .get("names")
                .and_then(|x| x.as_array())
                .map(|a| a.iter().filter_map(|x| x.as_str()).map(norm_card_name).collect())
                .unwrap_or_default();
            let rested = v.get("rested").and_then(|x| x.as_bool()).unwrap_or(false);
            let mut extra = v.get("filter").cloned().unwrap_or(json!({}));
            for k2 in ["cost_eq", "cost_le"] {
                if let Some(x) = v.get(k2) {
                    extra[k2] = x.clone();
                }
            }
            let mut consumed: Vec<usize> = vec![];
            for nm in &names {
                let mut hit: Option<usize> = None;
                for i in 0..state.players[me_idx].hand.len() {
                    if consumed.contains(&i) {
                        continue;
                    }
                    let c = &state.players[me_idx].hand[i];
                    if c.category != crate::state::Category::Character
                        || norm_card_name(&c.name) != *nm
                        || !matches_filter(c, Some(&extra))
                        || char_summon_blocked(&state.players[me_idx], c)
                    {
                        continue;
                    }
                    hit = Some(i);
                    break;
                }
                let Some(i) = hit else { continue };
                trash_weakest_for_field_full(state, me_idx);
                let card = state.players[me_idx].hand[i].clone();
                let mut ip = InPlay::of(card.clone(), true);
                ip.rested = rested;
                state.players[me_idx].characters.push(ip);
                let pidx = state.players[me_idx].characters.len() - 1;
                state.last_self_chara_played_card = Some(card);
                state.last_self_chara_played_from_trash = false;
                consumed.push(i);
                if execute_on_play(state, me_idx, pidx).is_err() {
                    return false;
                }
            }
            consumed.sort_unstable();
            for i in consumed.into_iter().rev() {
                if i < state.players[me_idx].hand.len() {
                    state.players[me_idx].hand.remove(i);
                }
            }
            true
        }
        // 手札 or トラッシュの filter 一致カードを自ライフ上へ (effects.py:hand_or_trash_to_self_life)。
        // from_zone: both (手札優先→trash) | trash。 face_up=true で表向き枚数を加算。
        "hand_or_trash_to_self_life" => {
            if let Some(cond) = v.get("if") {
                match eval_condition(cond, state, me_idx, Some(src)) {
                    Some(true) => {}
                    Some(false) => return true,
                    None => return false,
                }
            }
            let filt = v.get("filter");
            let count = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let from_zone = v.get("from_zone").and_then(|x| x.as_str()).unwrap_or("both");
            let face_up = v.get("face_up").and_then(|x| x.as_bool()).unwrap_or(false);
            let mut hand_idx: Vec<usize> = if from_zone == "trash" {
                vec![]
            } else {
                (0..state.players[me_idx].hand.len())
                    .filter(|&i| matches_filter(&state.players[me_idx].hand[i], filt))
                    .collect()
            };
            hand_idx.truncate(count);
            let need = count.saturating_sub(hand_idx.len());
            let mut trash_idx: Vec<usize> = (0..state.players[me_idx].trash.len())
                .filter(|&i| matches_filter(&state.players[me_idx].trash[i], filt))
                .collect();
            trash_idx.truncate(need);
            let mut added = 0;
            for &i in hand_idx.iter() {
                let c = state.players[me_idx].hand[i].clone();
                state.players[me_idx].life.insert(0, c);
                added += 1;
            }
            for &i in trash_idx.iter() {
                let c = state.players[me_idx].trash[i].clone();
                state.players[me_idx].life.insert(0, c);
                added += 1;
            }
            for &i in hand_idx.iter().rev() {
                if i < state.players[me_idx].hand.len() {
                    state.players[me_idx].hand.remove(i);
                }
            }
            for &i in trash_idx.iter().rev() {
                if i < state.players[me_idx].trash.len() {
                    state.players[me_idx].trash.remove(i);
                }
            }
            if face_up && added > 0 {
                let me = &mut state.players[me_idx];
                me.face_up_life_count = (me.face_up_life_count + added).min(me.life.len() as i32);
            }
            true
        }
        // 条件分岐つき置換 (effects.py:replace_ko_complex)。 branches を上から評価し、
        // 最初に成立した branch の do を実行 (排他)。 どれも不成立なら不発 (Python は return False)。
        "replace_ko_complex" => {
            let branches = if v.is_object() {
                v.get("branches").and_then(|x| x.as_array()).cloned().unwrap_or_default()
            } else {
                v.as_array().cloned().unwrap_or_default()
            };
            let mut chosen: Option<Value> = None;
            for br in &branches {
                let cond = br.get("if").cloned().unwrap_or(json!({}));
                match eval_condition(&cond, state, me_idx, Some(src)) {
                    Some(true) => {
                        chosen = Some(br.clone());
                        break;
                    }
                    Some(false) => continue,
                    None => return false, // 条件不明 → bail
                }
            }
            let Some(br) = chosen else { return true }; // 該当なし = 不発 (何も起きない)
            if let Some(dos) = br.get("do").and_then(|x| x.as_array()) {
                for sub in dos {
                    if !execute_effect(sub, state, me_idx, src) {
                        return false;
                    }
                }
            }
            true
        }
        // 「対象は、 次の相手ターン終了時まで、 アタックする際 自身の手札 N 枚を捨てなければ
        // アタックできない」 (effects.py:set_attack_cost_discard_hand、 OP08-043)。
        "set_attack_cost_discard_hand" => {
            let tspec = v
                .get("target")
                .cloned()
                .unwrap_or(Value::String("all_opponent_characters".into()));
            let n = v.get("n").and_then(|x| x.as_i64()).unwrap_or(2) as i32;
            let duration = v.get("duration").and_then(|x| x.as_str()).unwrap_or("next_opp_turn_end");
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
            let turn = state.turn_number;
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                ip.attack_cost_discard_hand_n = ip.attack_cost_discard_hand_n.max(n);
                if duration == "next_opp_turn_end" {
                    ip.attack_cost_discard_hand_applier_idx = me_idx as i32;
                    ip.attack_cost_discard_hand_applied_turn = turn;
                }
            }
            true
        }
        // 「捨てた枚数分カードを引く」 (effects.py:draw_per_self_hand_discarded、 OP12-040 クザン)。
        // 枚数は fire_hand_discarded_n が載せた transient を読む。 0 なら不発 (Python も return False)。
        "draw_per_self_hand_discarded" => {
            let n = state.current_discard_count;
            if n <= 0 {
                return true; // 不発 = 何も起きない (再現できている)
            }
            let me = &mut state.players[me_idx];
            if me.block_self_draw_until_turn_end {
                return true;
            }
            let mut drawn = 0;
            for _ in 0..n {
                if me.deck.is_empty() {
                    break;
                }
                let c = me.deck.remove(0);
                me.hand.push(c);
                drawn += 1;
            }
            me.cards_drawn_count += drawn;
            true
        }
        // 複数対象の power 変更 (effects.py:power_pump_multi)。 count_source 指定時は対象数を
        // 場の状況から算出し、 同一 target_spec をその数だけ並べる (ST31-004 ルフィ)。 dedup 付き。
        "power_pump_multi" => {
            let amount = v.get("amount").and_then(|x| x.as_i64()).unwrap_or(0) as i32;
            let duration = v.get("duration").and_then(|x| x.as_str()).unwrap_or("turn").to_string();
            let specs: Vec<Value> = match v.get("count_source").and_then(|x| x.as_str()) {
                Some(csrc) => {
                    let feat = v.get("feature").and_then(|x| x.as_str()).unwrap_or("");
                    let me = &state.players[me_idx];
                    let n = match csrc {
                        "self_field_feature_count" => std::iter::once(&me.leader)
                            .chain(me.characters.iter())
                            .chain(me.stages.iter())
                            .filter(|ip| ip.card.features.iter().any(|f| f == feat))
                            .count(),
                        "self_chara_feature_count" => me
                            .characters
                            .iter()
                            .filter(|c| c.card.features.iter().any(|f| f == feat))
                            .count(),
                        _ => 0,
                    };
                    let ct = v
                        .get("count_target")
                        .cloned()
                        .unwrap_or(Value::String("one_opponent_character_any".into()));
                    vec![ct; n]
                }
                None => v.get("target_specs").and_then(|x| x.as_array()).cloned().unwrap_or_default(),
            };
            let turn = state.turn_number;
            let mut already: Vec<(usize, Slot)> = vec![];
            for spec in specs {
                let tspec = if spec.is_string() {
                    spec.clone()
                } else {
                    spec.get("target").cloned().unwrap_or(Value::String("self".into()))
                };
                let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
                for (pi, sl) in targets {
                    if already.contains(&(pi, sl)) {
                        continue;
                    }
                    already.push((pi, sl));
                    let ip = get_ip_mut(&mut state.players[pi], sl);
                    match duration.as_str() {
                        "next_opp_turn_end" => {
                            ip.next_opp_turn_end_buff += amount;
                            ip.next_opp_turn_end_applier_idx = me_idx as i32;
                            ip.next_opp_turn_end_applied_turn = turn;
                        }
                        "static" => ip.static_buff += amount,
                        "battle" => ip.battle_buff += amount,
                        _ => ip.turn_buff += amount,
                    }
                }
            }
            true
        }
        // 自分のトラッシュから filter 一致 N 枚をデッキへ (effects.py:trash_to_deck)。
        // spec {filter, limit, to: top|bottom, shuffle}。 該当 0 枚は不発 (何も起きない = true)。
        "trash_to_deck" => {
            let filt = v.get("filter");
            let limit = v.get("limit").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let to_top = v.get("to").and_then(|x| x.as_str()) == Some("top");
            let do_shuffle = v.get("shuffle").and_then(|x| x.as_bool()).unwrap_or(false);
            let mut picked: Vec<crate::state::CardDef> = vec![];
            let mut rest: Vec<crate::state::CardDef> = vec![];
            for card in std::mem::take(&mut state.players[me_idx].trash) {
                if picked.len() < limit && matches_filter(&card, filt) {
                    picked.push(card);
                } else {
                    rest.push(card);
                }
            }
            state.players[me_idx].trash = rest;
            if picked.is_empty() {
                return true; // 公式 4-10 不発 = 何も起きない (再現できている)
            }
            if to_top {
                let mut d = picked;
                d.extend(std::mem::take(&mut state.players[me_idx].deck));
                state.players[me_idx].deck = d;
            } else {
                state.players[me_idx].deck.extend(picked);
            }
            if do_shuffle {
                let n = state.players[me_idx].deck.len();
                let perm = state.rng_mut().shuffle_perm(n);
                let old = std::mem::take(&mut state.players[me_idx].deck);
                state.players[me_idx].deck = perm.iter().map(|&j| old[j].clone()).collect();
            }
            true
        }
        // 自分の (filter) キャラを N 枚 KO (effects.py:ko_self_chara)。 犠牲順 = power 昇順。
        // ⚠ KO cascade が絡む盤面は再現不能で bail。
        "ko_self_chara" => {
            let count = if v.is_object() {
                v.get("count").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            } as usize;
            let filt = v.get("filter");
            let excl = v.get("exclude_self").and_then(|x| x.as_bool()).unwrap_or(false);
            let src_idx = if let Slot::Char(i) = src { Some(i) } else { None };
            let mut cands: Vec<usize> = (0..state.players[me_idx].characters.len())
                .filter(|&i| {
                    matches_filter_ip(&state.players[me_idx].characters[i], filt)
                        && !(excl && Some(i) == src_idx)
                })
                .collect();
            cands.sort_by_key(|&i| state.players[me_idx].characters[i].power());
            let victims: Vec<(usize, usize)> =
                cands.into_iter().take(count).map(|i| (me_idx, i)).collect();
            if victims.is_empty() {
                return true;
            }
            // Python (effects.py:3396) は victim ごとに逐次除去 → on_ko → on_self_chara_ko を発火し、
            // 最後に on_self_chara_leave_by_self_effect を 1 回。 自分の効果による自陣 KO なので
            // on_opp_chara_ko は発火しない。 chara_ko_taken_this_turn も加算しない。
            // ⚠ replace_ko/replace_leave は Python が ko_self_chara では呼ばないので考慮不要。
            let toks: Vec<Option<u64>> = victims
                .into_iter()
                .map(|(pi, i)| tag_src(state, pi, Slot::Char(i)))
                .collect();
            let mut ko_any = false;
            for tok in toks {
                let Slot::Char(i) = find_tagged(state, me_idx, tok) else { continue };
                let vcid = state.players[me_idx].characters[i].card.card_id.clone();
                note_ko_victim_negated(state, me_idx, i);
                let ip = state.players[me_idx].characters.remove(i);
                let don = ip.attached_dons;
                let departed = ip.card.clone();
                let _ko_vic = ip.card.clone();
                let _ko_vtop = ip.truly_original_power(); // KO 時点の元々のパワー (公式 4-9-2-1) // KO victim 文脈 (victim_truly_original_power_ge / victim_feature_in 用)
                state.players[me_idx].trash.push(ip.card);
                state.players[me_idx].don_rested += don;
                note_public_departure(state, me_idx, &departed); // 公開領域 (cardqa_op_08)
                ko_any = true;
                // Python は trigger_on_ko (= 全 KO 経路の共通フック、 effects.py:12942) の
                // 冒頭で owner.chara_ko_taken_this_turn を加算する。 overlay 有無・on_ko 有無に
                // 依らず加算されるので、 自分の効果による自陣 KO でも増える。
                // ⚠ かつて 「chara_ko_taken_this_turn も加算しない」 とコメントして省いていたが
                //   誤り (OP04-079 オオロンブス で MISMATCH、 2026-08-03 全カード差分掃引で発覚)。
                state.last_chara_ko_victim_card = Some(_ko_vic);
                state.rust_ko_victim_truly_original_power = Some(_ko_vtop); // Python は payload で victim を運ぶ (2026-08-11)
                if fire_on_ko(state, me_idx, &vcid, false).is_err() {
                    return false;
                }
                if fire_field_when(state, me_idx, "on_self_chara_ko").is_err() {
                    return false;
                }
                state.last_chara_ko_victim_card = None;
            }
            if ko_any && fire_leave_by_self_effect(state, me_idx).is_err() {
                return false;
            }
            true
        }
        // 「このターン中、 バトルで KO されない」 (effects.py:set_battle_ko_immune)。
        "set_battle_ko_immune" => {
            let tspec = if v.is_object() {
                v.get("target").cloned().unwrap_or(Value::String("self".into()))
            } else {
                v.clone()
            };
            let duration = v.get("duration").and_then(|x| x.as_str()).unwrap_or("turn").to_string();
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                match duration.as_str() {
                    "static" => ip.battle_ko_immune_static = true,
                    "next_self_turn_start" | "next_opp_turn_end" => {
                        ip.battle_ko_immune_through_opp_turn = true
                    }
                    _ => ip.battle_ko_immune_until_turn_end = true,
                }
            }
            true
        }
        // 自分の (filter) カード N 枚をレスト (effects.py:rest_self_cards_filtered)。
        // active 候補が count 未満なら不発 (何も起きない = true)。 AI は power 昇順で選ぶ。
        "rest_self_cards_filtered" => {
            let count = if v.is_object() {
                v.get("count").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            } as usize;
            let filt = v.get("filter");
            let mut cands: Vec<(Slot, i32)> = vec![];
            {
                let me = &state.players[me_idx];
                if !me.leader.rested && matches_filter_ip(&me.leader, filt) {
                    cands.push((Slot::Leader, me.leader.power()));
                }
                for (i, c) in me.characters.iter().enumerate() {
                    if !c.rested && matches_filter_ip(&c, filt) {
                        cands.push((Slot::Char(i), c.power()));
                    }
                }
                for (i, st) in me.stages.iter().enumerate() {
                    if !st.rested && matches_filter_ip(&st, filt) {
                        cands.push((Slot::Stage(i), st.power()));
                    }
                }
            }
            if cands.len() < count {
                return true; // active 不足 = 不発 (再現できている)
            }
            cands.sort_by_key(|&(_, p)| p);
            for (sl, _) in cands.into_iter().take(count) {
                get_ip_mut(&mut state.players[me_idx], sl).rested = true;
            }
            true
        }
        // デッキ上 N 枚を公開し、 filter 一致があれば then、 無ければ else を実行 → 公開分を
        // rest_remain (top/bottom/trash) へ (effects.py:reveal_top_then)。 デッキ空は不発 (false)。
        "reveal_top_then" => {
            let depth = v.get("depth").and_then(|x| x.as_i64()).unwrap_or(1).max(0) as usize;
            let filt = v.get("filter");
            let rest_remain = v.get("rest_remain").and_then(|x| x.as_str()).unwrap_or("bottom").to_string();
            // 「(条件)の場合、…。その後、公開カードをデッキの下に置く」= 「デッキの下」が条件節内の
            // カード用。 条件不成立時は rest_remain_unmatched へ (未指定なら rest_remain)。
            // EB01-029 わりいおれ死んだ: cardqa_eb_01 「コスト3以下 → デッキの上に裏向きで戻す」。
            let rest_remain_unmatched = v.get("rest_remain_unmatched").and_then(|x| x.as_str())
                .unwrap_or(rest_remain.as_str()).to_string();
            if state.players[me_idx].deck.is_empty() {
                return true; // デッキ空 = 不発 (再現できている)
            }
            let n = depth.min(state.players[me_idx].deck.len());
            let revealed: Vec<crate::state::CardDef> =
                state.players[me_idx].deck.drain(0..n).collect();
            let matched = revealed.iter().any(|c| matches_filter(c, filt));
            let branch = if matched { v.get("then") } else { v.get("else") };
            if let Some(specs) = branch.and_then(|x| x.as_array()) {
                for spec in specs {
                    if !execute_effect(spec, state, me_idx, src) {
                        return false;
                    }
                }
            }
            let effective_rest = if matched { rest_remain.as_str() } else { rest_remain_unmatched.as_str() };
            let me = &mut state.players[me_idx];
            match effective_rest {
                "top" => {
                    let mut d = revealed;
                    d.extend(std::mem::take(&mut me.deck));
                    me.deck = d;
                }
                "trash" => me.trash.extend(revealed),
                _ => me.deck.extend(revealed),
            }
            true
        }
        // デッキ上 1 枚を公開し、 CHARACTER かつ filter 一致なら登場、 残りは rest_remain へ
        // (effects.py:reveal_top_play)。 AI は「登場できるなら登場」(Python の人間 modal は AI では auto)。
        "reveal_top_play" | "reveal_life_top_play" => {
            let from_life = key == "reveal_life_top_play";
            let filt = v.get("filter");
            let rested_flag = v.get("rested").and_then(|x| x.as_bool()).unwrap_or(false);
            let rest_remain = v.get("rest_remain").and_then(|x| x.as_str()).unwrap_or("bottom").to_string();
            let empty = if from_life {
                state.players[me_idx].life.is_empty()
            } else {
                state.players[me_idx].deck.is_empty()
            };
            if empty {
                return true; // 空 = 不発 (再現できている)
            }
            let revealed = if from_life {
                state.players[me_idx].life.remove(0)
            } else {
                state.players[me_idx].deck.remove(0)
            };
            let matched = revealed.category == crate::state::Category::Character
                && matches_filter(&revealed, filt)
                && !char_summon_blocked(&state.players[me_idx], &revealed);
            if matched {
                trash_weakest_for_field_full(state, me_idx);
                let mut ip = InPlay::of(revealed.clone(), true); // sickness=true
                ip.rested = rested_flag;
                state.players[me_idx].characters.push(ip);
                let pidx = state.players[me_idx].characters.len() - 1;
                state.last_self_chara_played_card = Some(revealed);
                state.last_self_chara_played_from_trash = false;
                if execute_on_play(state, me_idx, pidx).is_err() {
                    return false;
                }
                // 「登場させた場合、 <then>」 (effects.py の then ループ)。
                // ⚠ 未実装で、 ST13-007 サボ / ST13-010 エース の 「リーダー+2000」 が
                //   Rust だけ乗っていなかった (2026-08-03 全カード差分掃引で発覚)。
                if let Some(then) = v.get("then").and_then(|x| x.as_array()) {
                    let then = then.clone();
                    for prim in &then {
                        if !execute_effect(prim, state, me_idx, src) {
                            return false;
                        }
                    }
                }
                return true;
            }
            // 非マッチ。
            // ⚠ ライフ由来は **公開しただけ** なので ライフの元の位置に戻す (公式: ライフ枚数不変)。
            //   デッキへ送っていたため ライフが減り デッキが増えていた (Python は matched の時だけ
            //   life.pop(0) する = 非マッチではそもそも取り出さない)。
            let me = &mut state.players[me_idx];
            if from_life {
                me.life.insert(0, revealed);
            } else {
                match rest_remain.as_str() {
                    "top" => me.deck.insert(0, revealed),
                    "trash" => me.trash.push(revealed),
                    _ => me.deck.push(revealed),
                }
            }
            true
        }
        // ライフ上 N 枚を見て上/下に置き直す (effects.py:scry_life)。 AI 判断 = 自ライフなら
        // 有用札 (トリガー持ち or カウンター2000以上) を上に残す / 相手ライフなら有用札を下に埋める。
        "scry_life" => {
            let owner = v.get("owner").and_then(|x| x.as_str()).unwrap_or("self").to_string();
            let depth = if v.is_object() {
                v.get("depth").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            }
            .max(0) as usize;
            let is_good = |c: &crate::state::CardDef| !c.trigger.is_empty() || c.counter >= 2000;
            let target = match owner.as_str() {
                "opp" => opp_idx,
                "self" => me_idx,
                _ => {
                    // self_or_opp: 相手の上ライフが強いなら妨害しに行く (Python の AI 分岐)
                    let o = &state.players[opp_idx];
                    if o.life.first().map_or(false, |c| is_good(c)) { opp_idx } else { me_idx }
                }
            };
            if state.players[target].life.is_empty() {
                return true; // ライフ空 = 不発 (再現できている)
            }
            let is_self = target == me_idx;
            let n = depth.min(state.players[target].life.len());
            let life = std::mem::take(&mut state.players[target].life);
            let (seen, rest) = life.split_at(n);
            let mut top_grp = vec![];
            let mut bot_grp = vec![];
            for c in seen {
                let keep_top = if is_self { is_good(c) } else { !is_good(c) };
                if keep_top { top_grp.push(c.clone()) } else { bot_grp.push(c.clone()) }
            }
            let mut newlife = top_grp;
            newlife.extend_from_slice(rest);
            newlife.extend(bot_grp);
            state.players[target].life = newlife;
            true
        }
        // 「このターンの後に自分のターンを追加で得る」 (effects.py:extra_turn)。 flag のみ。
        "extra_turn" => {
            state.extra_turn_pending = true;
            true
        }
        // 相手のアクティブドンを N 枚レストにする (effects.py:6436、 ST02-008 等)。 不足はそのまま。
        "rest_opp_don" => {
            let n = if v.is_object() {
                v.get("amount").and_then(|x| x.as_i64()).unwrap_or(1)
            } else {
                v.as_i64().unwrap_or(1)
            } as i32;
            let o = &mut state.players[opp_idx];
            let taken = n.min(o.don_active);
            o.don_active -= taken;
            o.don_rested += taken;
            true
        }
        // 「アクティブのキャラにもアタックできる」= キーワード付与 (effects.py:give_attack_active_chara)。
        "give_attack_active_chara" => {
            let tspec = if v.is_string() { v.clone() } else {
                v.get("target").cloned().unwrap_or(Value::String("self".into()))
            };
            let Some(targets) = resolve_target(Some(&tspec), me_idx, opp_idx, src, state) else { return false };
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl)
                    .granted_keywords
                    .insert("アクティブアタック可".to_string());
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
            let first = targets.first().cloned();
            for (pi, sl) in targets {
                get_ip_mut(&mut state.players[pi], sl).granted_keywords.insert("効果無効".to_string());
            }
            // 「その後、 そのキャラの〜」 (opp_just_negated_*) 用に直近 negate 対象を記録
            // (effects.py:7666)。 リーダーも記録する (opp_just_negated_any が対象にする)。
            // 0 対象なら None で clear (= 前回の対象が残ると別カードに当たる)。
            state.last_negated = match first {
                Some((pi, sl @ (Slot::Char(_) | Slot::Leader))) => Some((pi, sl)),
                _ => None,
            };
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
            // ⚠ 「このターン中、 キャラの効果でドン‼をアクティブにできない」 が立っていれば不発
            //   (EB04-016 / OP10-030 の自己ロック、 effects.py と同条件)。
            //   発動元がキャラの時だけ効く (リーダー/ステージ効果は対象外)。
            if state.players[me_idx].block_chara_effect_untap_don_until_turn_end {
                // 予約効果 (schedule_at_self_turn_end) の flush は src=Leader placeholder なので、
                // 予約時に保存した発動元 category も見る (effects.py と同条件)。
                let is_chara = matches!(src, Slot::Char(i)
                    if i < state.players[me_idx].characters.len()
                       && state.players[me_idx].characters[i].card.category
                          == crate::state::Category::Character)
                    || state.rust_scheduled_src_category.as_deref() == Some("CHARACTER");
                if is_chara {
                    return true; // Python は continue = 忠実な no-op
                }
            }
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
            let mut moved = 0;
            for _ in 0..n {
                if state.players[opp_idx].life.is_empty() {
                    break;
                }
                let c = state.players[opp_idx].life.remove(0);
                state.players[opp_idx].trash.push(c);
                moved += 1;
            }
            // ⭐ 効果で相手ライフが離れた時も 「相手のライフが離れた時」 は発火する
            // (cardqa_op_08 / OP08-105 ボニー: 「相手の効果によって手札やトラッシュに移動した時…
            //  できますか？」→「はい、できます」)。 Python `_fire_opp_life_left_by_effect` と対。
            // ⚠ ライフカードの【トリガー】は発動しない (公式 10-1-5) / `on_self_life_taken`
            //   (= ダメージを受けた時) は戦闘ダメージ専用なのでここでは発火しない。
            if moved > 0 {
                // ⚠ execute_effect は bool を返すので ? は使えない。 発火に失敗したら
                //   黙って進めず **false = 明示 bail** に落とす (不変条件: 黙って間違えない)。
                if fire_opp_life_left_by_effect(state, me_idx, opp_idx, "trash").is_err() {
                    return false;
                }
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
            let mut moved = 0;
            for _ in 0..n {
                if state.players[opp_idx].life.is_empty() {
                    break;
                }
                let c = state.players[opp_idx].life.remove(0);
                state.players[opp_idx].hand.push(c);
                moved += 1;
            }
            // ⭐ 効果で相手ライフが離れた時も 「相手のライフが離れた時」 は発火する
            // (cardqa_op_08 / OP08-105 ボニー: 「相手の効果によって手札やトラッシュに移動した時…
            //  できますか？」→「はい、できます」)。 Python `_fire_opp_life_left_by_effect` と対。
            // ⚠ ライフカードの【トリガー】は発動しない (公式 10-1-5) / `on_self_life_taken`
            //   (= ダメージを受けた時) は戦闘ダメージ専用なのでここでは発火しない。
            if moved > 0 {
                if fire_opp_life_left_by_effect(state, me_idx, opp_idx, "hand").is_err() {
                    return false;
                }
            }
            true
        }
        // トラッシュからキャラ登場 (effects.py:4733 play_from_trash/play_multi_from_trash、 AI 経路=先頭 limit 枚)。
        // 保守実装: CHARACTER のみ / 場が満杯でない / 静的 filter のみ。 STAGE・field-full・dynamic filter・
        // no_effect filter は bail (trash_weakest/動的解決/効果無し判定が複雑)。 登場後 on_play cascade を発火。
        "play_from_trash" | "play_multi_from_trash" => {
            let spec = v.as_object();
            let filt = spec.and_then(|o| o.get("filter"));
            // filter.category == STAGE なら ステージとして登場 (effects.py:2026-05-31 拡張、 OP13-092)。
            // 既存ステージがあれば持ち主のトラッシュへ (公式 上限 1)。 sickness/rested 無関係。
            if filt.and_then(|f| f.get("category")).and_then(|x| x.as_str()) == Some("STAGE") {
                let limit = spec.and_then(|o| o.get("limit")).and_then(|x| x.as_i64()).unwrap_or(1) as usize;
                let mut placed = 0usize;
                while placed < limit {
                    let idx = state.players[me_idx].trash.iter().position(|c| {
                        c.category == crate::state::Category::Stage && matches_filter(c, filt)
                    });
                    let Some(idx) = idx else { break };
                    if !state.players[me_idx].stages.is_empty() {
                        let old = state.players[me_idx].stages.remove(0);
                        let ad = old.attached_dons;
                        state.players[me_idx].trash.push(old.card);
                        state.players[me_idx].don_rested += ad;
                    }
                    let card = state.players[me_idx].trash.remove(idx);
                    let ip = InPlay::of(card, false);
                    state.players[me_idx].stages.push(ip);
                    let pidx = state.players[me_idx].stages.len() - 1;
                    if execute_stage_on_play(state, me_idx, pidx).is_err() {
                        return false;
                    }
                    placed += 1;
                }
                return true;
            }
            // 動的 filter は resolve_dynamic_filter で静的化済 (cost_le_dynamic / or /
            // name_in_last_discarded)。 未知 key は matches_filter が Python 同様 pass する。
            // STAGE 登場は上で専用処理済。
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
                        && !char_summon_blocked(me, c)
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
            // (旧: 登場キャラの on_play が zone 並べ替えを含むと inline 発火では順序がズレるため bail
            //  していたが、 trigger キュー導入で on_play は resolving 中なら後回しになり Python と
            //  同じ順序になったため撤去。 2026-08-01)
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
        // 「自分の手札から (filter) キャラカード reveal_limit 枚までを公開する。 公開したカードの
        //   うち1枚を登場させ、 残りがコスト extra_rested_cost_le 以下ならレストで登場させる」
        //   (effects.py:4556、 OP10-058 レベッカ)。
        // AI 経路 = 盤面最大化: (cost, power) 降順の先頭を active、 以降で コスト条件を満たす
        // 最初の 1 枚を rested。 コスト超のカードはレスト登場できないので **公開のみ (手札に残る)**。
        "reveal_hand_play_split" => {
            let spec = v.as_object();
            let resolved = resolve_dynamic_filter(spec.and_then(|o| o.get("filter")), state, me_idx);
            let filt = resolved.as_ref();
            let reveal_limit =
                spec.and_then(|o| o.get("reveal_limit")).and_then(|x| x.as_i64()).unwrap_or(2) as usize;
            let rest_cost_le =
                spec.and_then(|o| o.get("extra_rested_cost_le")).and_then(|x| x.as_i64()).unwrap_or(4) as i32;
            // 候補 = 手札の CHARACTER で filter 一致 かつ 効果で登場可能 (hand 順を保つ)
            let mut cands: Vec<(usize, i32, i32)> = vec![]; // (hand_idx, cost, power)
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
                    cands.push((i, c.cost, c.power));
                }
            }
            if cands.is_empty() {
                return true; // 該当手札なし = 不発 (Python も log のみ)
            }
            // (cost, power) 降順。 sort_by は stable = 同値は hand 順 (Python の sorted 同様)。
            let mut ordered = cands.clone();
            ordered.sort_by(|a, b| (b.1, b.2).cmp(&(a.1, a.2)));
            let mut reveal_set: Vec<usize> = vec![ordered[0].0];
            if let Some(t) = ordered[1..].iter().find(|t| t.1 <= rest_cost_le) {
                reveal_set.push(t.0);
            }
            reveal_set.truncate(reveal_limit);
            // active 枠 = コスト超のカードを優先 (レスト登場できない為)、 無ければ reveal_set 全体。
            // ⚠ Python の `max()` は **最初の最大** を返す (Rust の max_by_key は最後) → 手で first-max。
            let active_idx = {
                let me = &state.players[me_idx];
                let big: Vec<usize> =
                    reveal_set.iter().copied().filter(|&i| me.hand[i].cost > rest_cost_le).collect();
                let pool = if big.is_empty() { &reveal_set } else { &big };
                let mut best = pool[0];
                let mut bestk = (me.hand[best].cost, me.hand[best].power);
                for &i in &pool[1..] {
                    let k = (me.hand[i].cost, me.hand[i].power);
                    if k > bestk {
                        best = i;
                        bestk = k;
                    }
                }
                best
            };
            // 登場する (hand_idx, rested) を hand から抜く **前** に確定する (Python 同順)。
            let mut plays: Vec<(usize, bool)> = vec![(active_idx, false)];
            {
                let me = &state.players[me_idx];
                for &i in &reveal_set {
                    if i == active_idx {
                        continue;
                    }
                    if me.hand[i].cost <= rest_cost_le {
                        plays.push((i, true));
                    }
                    // コスト超 = レスト登場できず 「公開のみ」 で手札に残る
                }
            }
            let play_cards: Vec<(crate::state::CardDef, bool)> = {
                let me = &state.players[me_idx];
                plays.iter().map(|&(i, r)| (me.hand[i].clone(), r)).collect()
            };
            let mut desc: Vec<usize> = plays.iter().map(|&(i, _)| i).collect();
            desc.sort_unstable_by(|a, b| b.cmp(a)); // 降順 pop で index ずれ防止
            for i in desc {
                state.players[me_idx].hand.remove(i);
            }
            for (card, rested) in play_cards {
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
        "play_from_hand" => {
            let spec = v.as_object();
            // cost_le_dynamic を静的化してから使う (self_don_total 等)。
            let resolved = resolve_dynamic_filter(spec.and_then(|o| o.get("filter")), state, me_idx);
            let filt = resolved.as_ref();
            // ⚠ Python の play_from_hand は CHARACTER のみ登場させる (effects.py:5117) ので、
            // filter.category が STAGE 等でも「該当なし = no-op」 が正しい (bail 不要)。
            let limit = spec.and_then(|o| o.get("limit")).and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let rested = spec.and_then(|o| o.get("rested")).and_then(|x| x.as_bool()).unwrap_or(false);
            let unique = spec.and_then(|o| o.get("unique_name")).and_then(|x| x.as_bool()).unwrap_or(false);
            // 公式が 素の 「カード…登場させる」 (= ST31-002 ジンベエ) は ステージも 対象。 opt-in flag、
            // 既定 false = 従来どおり CHARACTER 専用。 cardqa_st_31 で サニー号 (STAGE) 登場が 「はい」。
            let include_stage =
                spec.and_then(|o| o.get("include_stage")).and_then(|x| x.as_bool()).unwrap_or(false);
            // 候補抽出: (hand_idx, cost, power, name)
            let mut cands: Vec<(usize, i32, i32, String)> = vec![];
            {
                let me = &state.players[me_idx];
                for (i, c) in me.hand.iter().enumerate() {
                    let cat_ok = c.category == crate::state::Category::Character
                        || (include_stage && c.category == crate::state::Category::Stage);
                    if !cat_ok {
                        continue;
                    }
                    if card_no_play_via_effect(&c.card_id) {
                        continue;
                    }
                    if char_summon_blocked(me, c) {
                        continue; // OP13-023 / OP14-020: 「登場できない」 ペナルティ (効果登場も禁止)
                    }
                    // 「コストN以下」 は 手札での現在コスト で判定 (= ST23-001 ウタ、 cardqa_st_23)。
                    // 手札コスト修正なし (ihm=0) のカードは matches_filter と完全一致 = 挙動不変。
                    let ihm = in_hand_cost_minus(state, me_idx, c);
                    if !matches_filter_hand(c, filt, ihm) {
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
                if moved > 0 && fire_self_life_to_hand(state, me_idx).is_err() {
                    return false;
                }
                return true;
            }
            // then_draw 有 (OP09-103 コアラ): 「登場させた場合、カード1枚を引く」。 then_life と同じく
            // Python は on_play を enqueue → draw → drain なので、 place all → draw → deferred on_play。
            // 登場 0 枚なら draw 不発 (公式「場合」 前文不成立、 cardqa_op_09)。
            if let Some(n_draw) = spec.and_then(|o| o.get("then_draw")).and_then(|x| x.as_i64()) {
                let mut placed: Vec<usize> = vec![];
                for card in cards {
                    trash_weakest_for_field_full(state, me_idx);
                    let mut ip = InPlay::of(card, true);
                    ip.rested = rested;
                    state.players[me_idx].characters.push(ip);
                    placed.push(state.players[me_idx].characters.len() - 1);
                }
                if !placed.is_empty() && !state.players[me_idx].block_self_draw_until_turn_end {
                    let mut drew = false;
                    for _ in 0..n_draw {
                        if state.players[me_idx].deck.is_empty() {
                            break;
                        }
                        let c = state.players[me_idx].deck.remove(0);
                        let cid = c.card_id.clone();
                        let me = &mut state.players[me_idx];
                        if !me.known_top_card_ids.is_empty() && me.known_top_card_ids[0] == cid {
                            me.known_top_card_ids.remove(0);
                        } else if let Some(p) = me.known_top_card_ids.iter().position(|x| *x == cid) {
                            me.known_top_card_ids.remove(p);
                        }
                        me.hand.push(c);
                        me.cards_drawn_count += 1;
                        drew = true;
                    }
                    if drew
                        && me_board_has_when(state, me_idx, "on_self_draw_non_draw_phase")
                        && fire_on_self_draw_non_draw_phase(state, me_idx).is_err()
                    {
                        return false;
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
                return true;
            }
            for card in cards {
                // include_stage で STAGE を選んだ場合は play_stage_from_hand と同じ 置換 + on_play。
                if card.category == crate::state::Category::Stage {
                    let ctx_card = card.clone();
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
                    state.last_self_chara_played_card = Some(ctx_card);
                    state.last_self_chara_played_from_trash = false;
                    if execute_stage_on_play(state, me_idx, played_idx).is_err() {
                        return false;
                    }
                    continue;
                }
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
            // filter.category が STAGE ならステージとして登場 (OP16-102 ハチノス、 effects.py:7761)。
            let target_cat = match filt
                .and_then(|f| f.get("category"))
                .and_then(|x| x.as_str())
                .unwrap_or("CHARACTER")
            {
                "STAGE" => crate::state::Category::Stage,
                "EVENT" => crate::state::Category::Event,
                "LEADER" => crate::state::Category::Leader,
                _ => crate::state::Category::Character,
            };
            let limit = spec.and_then(|o| o.get("limit")).and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let rested = spec.and_then(|o| o.get("rested")).and_then(|x| x.as_bool()).unwrap_or(false);
            let mut found = 0usize;
            // ⭐ Python timing (effects.py:7878): 登場カードは me.hand に残したまま on_play 発火 (on_play が
            // hand を観測)、 loop 末尾で unplayed を new_hand に再構築して置換。 index-based で on_play の
            // hand 追加も追随。 on_play は trigger キューで defer されるので Python と同じ順序になる。
            let mut new_hand: Vec<crate::state::CardDef> = vec![];
            let mut i = 0;
            while i < state.players[me_idx].hand.len() {
                let card = state.players[me_idx].hand[i].clone();
                let m = found < limit
                    && card.category == target_cat
                    && matches_filter(&card, filt)
                    && !card_no_play_via_effect(&card.card_id)
                    && !char_summon_blocked(&state.players[me_idx], &card);
                if m {
                    if place_played_card(state, me_idx, card.clone(), rested, target_cat).is_err() {
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
                        && card.category == target_cat
                        && matches_filter(&card, filt)
                        && !char_summon_blocked(&state.players[me_idx], &card);
                    if m {
                        if place_played_card(state, me_idx, card.clone(), rested, target_cat).is_err()
                        {
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
            // Python (effects.py:play_self) は self_inplay → current_source_card_id の順で source を解決。
            // src が場に居る場合はそれを使う (以前は current_source_card_id のみ見て bail していた)。
            // _card_id 明示指定 (fire_event_main_from_trash が「トラッシュのイベント」を指すのに使う)。
            let cid_opt = v
                .get("_card_id")
                .and_then(|x| x.as_str())
                .map(|s2| s2.to_string())
                .or_else(|| src_ip(&state.players[me_idx], src).map(|ip| ip.card.card_id.clone()))
                .or_else(|| state.current_source_card_id.clone());
            let Some(cid) = cid_opt else {
                return false; // source card 不明 → bail
            };
            // 既に場に居る (= 発動元自身が場) なら二重登場しない (effects.py:play_self の iid guard)
            if matches!(src, Slot::Char(_)) {
                return true;
            }
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
            // source は「場に居る発動元」優先、 無ければ current_source_card_id (source-gone 経路)。
            // Python (effects.py:fire_self_effect) も self_inplay → current_source_card_id の順。
            let cid_opt = src_ip(&state.players[me_idx], src)
                .map(|ip| ip.card.card_id.clone())
                .or_else(|| state.current_source_card_id.clone());
            let Some(cid) = cid_opt else { return true };
            // 再帰は深度 2 で打ち切り (Python の state._fire_self_depth 相当)
            let depth = FIRE_SELF_DEPTH.load(std::sync::atomic::Ordering::Relaxed);
            if depth >= 2 {
                return true;
            }
            FIRE_SELF_DEPTH.store(depth + 1, std::sync::atomic::Ordering::Relaxed);
            let _guard = FireSelfGuard(depth);
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
                    None => {
                        note_unknown_key("fse", "条件 unknown");
                        note_prim_err("fire_self_effect: 内側 条件 unknown");
                        return false;
                    }
                }
                if let Some(dos) = eff.get("do").and_then(|d| d.as_array()) {
                    if effect_cascade_blocked(dos, state, me_idx) {
                        let bk = dos
                            .iter()
                            .find(|d| effect_cascade_blocked(std::slice::from_ref(d), state, me_idx))
                            .and_then(|d| d.as_object())
                            .and_then(|o| o.keys().next())
                            .map(|x| x.as_str())
                            .unwrap_or("?")
                            .to_string();
                        note_unknown_key("fse", &format!("cascade:{bk}"));
                        note_prim_err(&format!("fire_self_effect: 内側 cascade {bk}"));
                        return false;
                    }
                    for prim in dos {
                        if !execute_effect(prim, state, me_idx, src) {
                            let pk = prim.as_object().and_then(|o| o.keys().next()).map(|x| x.as_str()).unwrap_or("?");
                            note_unknown_key("fse", pk);
                            note_prim_err(&format!("fire_self_effect: 内側 prim {pk}"));
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
                // 公式 cardqa_op_14: ステージも 「自分のカード」 に含まれる。
                for (i, st_ip) in me.stages.iter().enumerate() {
                    if !st_ip.rested {
                        actives.push((Slot::Stage(i), st_ip.power()));
                    }
                }
            }
            actives.sort_by(|a, b| a.1.cmp(&b.1)); // power 昇順 (stable=ties 原順)
            let picked = actives.len().min(n);
            for (slot, _) in actives.into_iter().take(n) {
                get_ip_mut(&mut state.players[me_idx], slot).rested = true;
            }
            // 場のカードで足りない分は アクティブのドン‼ をレストにして払う (4 ゾーン合計)。
            let don_rest = (n - picked).min(state.players[me_idx].don_active.max(0) as usize) as i32;
            if don_rest > 0 {
                state.players[me_idx].don_active -= don_rest;
                state.players[me_idx].don_rested += don_rest;
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
                    None => {
                        note_unknown_key(
                            "oct_payable",
                            cs.as_object().and_then(|o| o.keys().next()).map(|x| x.as_str()).unwrap_or("?"),
                        );
                        return false; // 未対応 cost 型 → bail (誤適用ゼロ)
                    }
                    Some(false) => { can_pay = false; break; }
                    Some(true) => {}
                }
            }
            // should_fire 追加条件 (effects.py:8948): effect に hand_to_self_life && 手札空 → 不発。
            // ⚠ 判定はコスト支払い **前** なので、 コスト自身が手札を増やす型 (OP08-117 トリガー
            //   「ライフの上から1枚を手札に加えることができる：手札1枚までをライフの上に加える」)
            //   では guard を外す (支払い後は手札 1 枚 = 空回りしない)。
            let cost_fills_hand = cost.iter().any(|cs| {
                cs.get("life_to_hand").is_some() || cs.get("life_top_or_bottom_to_hand").is_some()
            });
            let mut should_fire = can_pay;
            if should_fire && !cost_fills_hand {
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
            // (pay_don の on_self_don_returned_to_deck cascade は primitive 側で発火するので guard 不要)
            if effect_cascade_blocked(&effect, state, me_idx) {
                note_unknown_key("oct_cascade", "effect");
                return false;
            }
            // cost 支払い (cost_specs 順)。 未対応は None → bail (cost 済でも apply_action Err で全破棄)
            // ⚠ cost が自陣を除去する系 (ko_self_chara 等) だと、 支払い後に src (位置 index) が
            //   別カードを指す / 範囲外になる。 そのまま effect の "self" を解決すると **別キャラに
            //   適用** するか panic する (OP03-012 / OP06-083 / OP13-053、 効果スモークで検出)。
            //   Python は self_inplay を object 参照で追うので影響を受けない。 → ズレたら明示 bail。
            let src_cid_before: Option<String> =
                src_ip(&state.players[me_idx], src).map(|ip| ip.card.card_id.clone());
            // 発動元に一時タグを打つ = cost 後に位置 index が動いても一意に再取得できる
            // (Python の self_inplay object 参照の代替)。 同名複数でも取り違えない。
            let src_tok = tag_src(state, me_idx, src);
            // ⚠ cost は複数あり **各コストの間** でも盤面が動く。 例 OP04-111 ヘラ:
            //   [ko_self_chara(他のホーミーズ1枚), rest_self] の順で、 1 つ目の KO により
            //   発動元の位置 index が 1 つ手前にズレる → そのままだと 2 つ目の rest_self が
            //   **別のキャラをレスト** する (Python は self_inplay を object 参照で持つので無影響)。
            //   効果ループ側と同じく 段ごとにタグで引き直す。
            let mut pay_src = src;
            for cs in &cost {
                if pay_cost_one(cs, state, me_idx, pay_src).is_none() {
                    let k = cs.as_object().and_then(|o| o.keys().next()).map(|x| x.as_str()).unwrap_or("?");
                    note_unknown_key("oct_pay", k);
                    return false;
                }
                if !matches!(pay_src, Slot::Detached) {
                    pay_src = peek_tagged(state, me_idx, src_tok);
                }
            }
            // cost が **別の** キャラを除去した場合、 src の index は 1 つ手前にズレるだけで
            // 発動元自身は場に残っている (Python は object 参照なので影響なし)。 同 card_id が
            // 盤面に 1 つだけなら一意に追随できる (曖昧なら従来通り bail = 誤対応を作らない)。
            // タグを回収して発動元の現在位置を求める。 見つからない = cost で場を離れた
            // (Python の self_inplay は生きているが場外 → "self" 対象 0 件 = Slot::Detached と等価)。
            let src = match src {
                Slot::Detached => Slot::Detached,
                _ => {
                    let snap = src_ip(&state.players[me_idx], src).cloned();
                    let found = find_tagged(state, me_idx, src_tok);
                    if found == Slot::Detached && snap.is_some() {
                        state.rust_detached_src = snap;
                    }
                    found
                }
            };
            let _ = &src_cid_before;
            // effect 発火 (未対応 prim は false → 呼出側で bail)。
            // ⚠ effect の **各段の間** でも盤面は動く (例 OP02-062: return_to_hand で自陣の
            //   別キャラが手札に戻る → 発動元の位置 index が 1 つ手前にズレる)。 cost 後に
            //   1 度だけ解決した src を使い回すと 次段の "self" が別キャラを指すか
            //   get_ip_mut で範囲外 panic する (= 不変条件違反)。 Python は self_inplay を
            //   object 参照で持つので影響を受けない。 → 段ごとにタグで引き直す。
            let step_tok = tag_src(state, me_idx, src);
            let mut src = src;
            for es in &effect {
                if !execute_effect(es, state, me_idx, src) {
                    let k = es.as_object().and_then(|o| o.keys().next()).map(|x| x.as_str()).unwrap_or("?");
                    note_unknown_key(
                        "oct_effect",
                        &format!("{k} {}", es.to_string().chars().take(70).collect::<String>()),
                    );
                    find_tagged(state, me_idx, step_tok); // タグ回収
                    return false;
                }
                // 次段のために現在位置を引き直す (場を離れていれば Detached = "self" 0 件)。
                if !matches!(src, Slot::Detached) {
                    let next = peek_tagged(state, me_idx, step_tok);
                    if matches!(next, Slot::Detached) {
                        if let Some(snap) = src_ip(&state.players[me_idx], src).cloned() {
                            state.rust_detached_src = Some(snap);
                        }
                    }
                    src = next;
                }
            }
            find_tagged(state, me_idx, step_tok); // タグ回収
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
            let mut moved = 0i32;
            for _ in 0..n {
                if state.players[opp_idx].hand.is_empty() {
                    break;
                }
                let len = state.players[opp_idx].hand.len() as u64;
                let idx = state.rng_mut().randrange(len) as usize;
                let c = state.players[opp_idx].hand.remove(idx);
                state.players[opp_idx].trash.push(c);
                moved += 1;
            }
            // 相手 (= 手札の持ち主 opp) 視点で「効果で手札が捨てられた」を発火する。
            // Python: trigger_on_self_hand_discarded(opp,…) が flag + on_self_hand_discarded cascade。
            // 公式 cardqa: 相手効果の手札破棄でも ST33-004 のコスト-3 / OP14-045【速攻】は発動する。
            // cascade を要する (opp 場に on_self_hand_discarded がある) 場合は Python に委ねて bail。
            if moved > 0 {
                if me_board_has_when(state, opp_idx, "on_self_hand_discarded") {
                    return false;
                }
                state.players[opp_idx].hand_discarded_by_effect_this_turn = true;
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
            // 対象 0 = Python も `return False` (= 後続 do を止めない no-op、 _chain 未使用) → 不発扱い。
            let Some(&(fp, fs)) = from_c.first() else { return true };
            // ⭐ コピー元が 「元々のパワー」 か 現在パワーか (公式の書き分け、 2026-08-11)。
            //   「自分のリーダーの **元々の** パワーと同じ」 = OP14-053 ビスタ のみ from_original:true。
            let copied = {
                let sip = get_ip(&state.players[fp], fs);
                if v.get("from_original").and_then(|x| x.as_bool()).unwrap_or(false) {
                    sip.truly_original_power()
                } else {
                    sip.power()
                }
            };
            let Some(to_c) = resolve_target(Some(&to_spec), me_idx, opp_idx, src, state) else { return false };
            if to_c.is_empty() {
                return true;
            }
            // ⭐ 「元々の」 パワー書き換えか (公式 4-9-2-1、 Python と同じ overlay フラグ)。
            let is_orig_copy = v.get("original").and_then(|x| x.as_bool()).unwrap_or(false);
            for (pi, sl) in to_c {
                let ip = get_ip_mut(&mut state.players[pi], sl);
                match duration.as_str() {
                    "turn" => {
                        ip.turn_base_power_override = Some(if is_orig_copy { ip.turn_base_power_override.filter(|_| ip.turn_base_power_override_is_original).map_or(copied, |c| c.max(copied)) } else { copied });
                        ip.turn_base_power_override_is_original = is_orig_copy;
                    }
                    "next_self_turn_start" => {
                        ip.next_turn_base_power_override = Some(if is_orig_copy { ip.next_turn_base_power_override.filter(|_| ip.next_turn_base_power_override_is_original).map_or(copied, |c| c.max(copied)) } else { copied });
                        ip.next_turn_base_power_override_is_original = is_orig_copy;
                    }
                    _ => {
                        ip.base_power_override = Some(if is_orig_copy { ip.base_power_override.filter(|_| ip.base_power_override_is_original).map_or(copied, |c| c.max(copied)) } else { copied });
                        ip.base_power_override_is_original = is_orig_copy;
                    }
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
            if moved > 0 && fire_self_life_to_hand(state, me_idx).is_err() {
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
                if fire_hand_discarded_n(state, me_idx, src, discarded).is_err() {
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
            // ⭐ 発動元 category を予約データに残す (effects.py と同形。 cardqa_eb_02 / cardqa_st_24、
            //   OP10-030 スモーカーの 「キャラの効果でドン‼をアクティブにできない」 を
            //   ターン終了時の予約 untap_don にも効かせる為)。 flush は src=Leader placeholder
            //   なので、 ここで持たせないと gate が通らない。
            let mut sched = v.clone();
            if let Some(o) = sched.as_object_mut() {
                let cat = match src {
                    Slot::Char(i) if i < state.players[me_idx].characters.len() => {
                        match state.players[me_idx].characters[i].card.category {
                            crate::state::Category::Character => Value::String("CHARACTER".into()),
                            crate::state::Category::Leader => Value::String("LEADER".into()),
                            crate::state::Category::Stage => Value::String("STAGE".into()),
                            crate::state::Category::Event => Value::String("EVENT".into()),
                        }
                    }
                    Slot::Leader => Value::String("LEADER".into()),
                    Slot::Stage(_) => Value::String("STAGE".into()),
                    _ => Value::Null,
                };
                o.insert("_src_category".to_string(), cat);
            }
            state.players[me_idx].scheduled_at_self_turn_end.push(sched);
            true
        }
        // 「(target) が相手の元コスト N 以下のキャラへアタック不可」 (effects.py:7653、 OP12-020 リーダー)。
        // 対象に cannot_attack_target_cost_le_until_turn_end=N を set (attack 側は既に read 済)。
        "set_cannot_attack_target_cost_le" => {
            let default_tgt = Value::String("self_leader".into());
            let (tgt, cost_le) = if let Some(o) = v.as_object() {
                (
                    o.get("target").unwrap_or(&default_tgt),
                    // 公式 「元々のコスト」 = 印刷コスト。 消費側は card.cost と比べる (Python 準拠)
                    o.get("truly_original_cost_le").and_then(|x| x.as_i64()).unwrap_or(0) as i32,
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
        // レストのドンを付与 (effects.py:5821)。
        // ⚠ 供給元は **to_opp なら相手の**ドン (OP15-008/015/025/028 「相手のキャラに相手のレストのドンを
        //   付与」= 相手の tempo 妨害)。 ここを常に me から引いていたため **ドンがプレイヤー間を移動** し、
        //   全カード掃引の保存則チェックで検出された (INV-don-total p0 10→7 / p1 10→13、 2026-07-31)。
        // from_cost_area=true なら rested 不足分を active からも取る。 per_target=true は各 target に count 枚、
        // 既定は先頭 target にまとめて count 枚 (effects.py:5894)。
        "attach_rested_don" => {
            let count = v.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32;
            let to_opp = v.get("to_opp").and_then(|x| x.as_bool()).unwrap_or(false);
            let from_cost_area = v.get("from_cost_area").and_then(|x| x.as_bool()).unwrap_or(false);
            let per_target = v.get("per_target").and_then(|x| x.as_bool()).unwrap_or(false);
            // 公式 「**持ち主の**レストのドン‼」 = ドン源は **対象カードの所有者** (cardqa_op_15)。
            // to_opp は片側に up-front 固定する旧 flag なので両陣営 target では使えない。
            let owner_of_target = v.get("owner_of_target").and_then(|x| x.as_bool()).unwrap_or(false);
            let owner = if to_opp { opp_idx } else { me_idx };
            let target_val = v.get("target").cloned().unwrap_or(Value::String("self_leader".into()));
            let Some(targets) = resolve_target(Some(&target_val), me_idx, opp_idx, src, state) else { return false };
            if targets.is_empty() {
                return true;
            }
            let mut take_from_owner = |state: &mut GameState, k: i32, pi_of_target: usize| -> i32 {
                let src_owner = if owner_of_target { pi_of_target } else { owner };
                let p = &mut state.players[src_owner];
                let mut taken = k.min(p.don_rested);
                p.don_rested -= taken;
                if from_cost_area && taken < k {
                    let more = (k - taken).min(p.don_active);
                    p.don_active -= more;
                    taken += more;
                }
                taken
            };
            if per_target {
                // max_targets = 「キャラ N 枚まで に 1 枚ずつ」 の N (OP08-001 チョッパー
                // 「自分の《動物》か《ドラム王国》キャラ **3枚まで** に…1枚ずつまで」)。
                // ⚠ Python/Rust とも未実装で **全対象** に配っていた (2026-08-03 発覚)。
                let targets = match v.get("max_targets").and_then(|x| x.as_i64()) {
                    Some(mt) => targets.into_iter().take(mt.max(0) as usize).collect::<Vec<_>>(),
                    None => targets,
                };
                for (pi, sl) in targets {
                    let give = take_from_owner(state, count, pi);
                    if give <= 0 {
                        break;
                    }
                    get_ip_mut(&mut state.players[pi], sl).attached_dons += give;
                }
            } else {
                let (pi, sl) = targets[0];
                let give = take_from_owner(state, count, pi);
                if give > 0 {
                    get_ip_mut(&mut state.players[pi], sl).attached_dons += give;
                }
            }
            true
        }
        // KO (effects.py:3245)。 免疫チェック → 除去 + trash + 付与ドン返却 + chara_ko_taken。
        // ⚠ replace_ko / KO trigger cascade は未対応 → 該当 victim は diverge (差分テストが除外)。
        "ko" => {
            let Some(targets) = resolve_target(Some(v), me_idx, opp_idx, src, state) else {
                note_unknown_key("ko", "target 未対応");
                return false;
            };
            // Python (effects.py:3336) は解決順に 1 体ずつ処理し、 各段で「まだ相手の場に居るか」を
            // object 参照で見る (置換効果 replace_leave が別キャラを場から抜くと index が総ずれする)。
            // Rust は位置 index なので一意トークンで追跡して同じ意味論にする。
            // ⚠ 相手キャラ以外 (自陣/リーダー) は Python が `if t in opp.characters` で弾く = 対象外。
            let toks: Vec<Option<u64>> = targets
                .iter()
                .filter(|&&(pi, sl)| pi == opp_idx && matches!(sl, Slot::Char(_)))
                .map(|&(pi, sl)| tag_src(state, pi, sl))
                .collect();
            // ⚠ **複数対象の `ko` は同時離脱**。 Python は _LeaveBatch を開き、 置換の可否を
            //   **バッチ開始時の盤面** で決める (順序非依存。 cardqa_op_10 / OP10-032 たしぎ)。
            //   Rust は逐次処理なので、 置換 holder が居る multi-target では **bail** する
            //   (= 黙って順序依存の結果を作らない)。 単体 KO は従来どおり。
            // source-gone (Detached) では Python も self_inplay=None で source 依存の KO 耐性判定を
            // **スキップ** する (effects.py:3352 `if thr >= 0 and self_inplay is not None`)。
            let src_pa: Option<(i32, String)> = src_ip(&state.players[me_idx], src)
                .map(|s| (s.card.power, s.card.attribute.clone()));
            let mut ko_any = false;
            for tok in toks {
                let Slot::Char(idx) = find_tagged(state, opp_idx, tok) else { continue };
                {
                    let t = &mut state.players[opp_idx].characters[idx];
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
                }
                // 置換効果 (KO される場合、 代わりに〜)。 Ok(true)=KO 阻止 / Err=再現不能
                match try_replace_ko(state, opp_idx, idx, true, "ko") {
                    Ok(true) => continue,
                    Ok(false) => {}
                    Err(e) => {
                        note_unknown_key("ko", &format!("replace: {e}"));
                        return false;
                    }
                }
                let vcid = state.players[opp_idx].characters[idx].card.card_id.clone();
                let vdon = state.players[opp_idx].characters[idx].attached_dons;
                note_ko_victim_negated(state, opp_idx, idx);
                let removed = state.players[opp_idx].characters.remove(idx);
                let _ko_vic = removed.card.clone();
                let _ko_vtop = removed.truly_original_power(); // KO 時点の元々のパワー (公式 4-9-2-1) // KO victim 文脈 (victim_truly_original_power_ge / victim_feature_in 用)
                state.players[opp_idx].trash.push(removed.card);
                state.players[opp_idx].don_rested += vdon;
                ko_any = true;
                // effects.py:3391 順: on_ko(victim側) → on_opp_chara_ko(me) → on_self_chara_ko(victim側)。
                // ⭐ 効果 ko は nested resolution = Python は trigger を enqueue し、 その末尾で
                // last_chara_ko_victim_card=None に戻してから deferred drain する = victim None で発火。
                state.last_chara_ko_victim_card = Some(_ko_vic);
                state.rust_ko_victim_truly_original_power = Some(_ko_vtop); // Python は payload で victim を運ぶ (2026-08-11)
                if fire_on_ko(state, opp_idx, &vcid, true).is_err() {
                    note_unknown_key("ko", "on_ko");
                    return false;
                }
                if fire_field_when(state, me_idx, "on_opp_chara_ko").is_err() {
                    note_unknown_key("ko", "on_opp_chara_ko");
                    return false;
                }
                if fire_field_when(state, opp_idx, "on_self_chara_ko").is_err() {
                    note_unknown_key("ko", "on_self_chara_ko");
                    return false;
                }
                state.last_chara_ko_victim_card = None;
            }
            // 「キャラが自分の効果で場を離れた時」 は loop 後に 1 回だけ (effects.py:3394)。
            if ko_any && fire_leave_by_self_effect(state, me_idx).is_err() {
                note_unknown_key("ko", "leave_by_self");
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
            let Some(targets) = resolve_target(Some(&tgt_spec), me_idx, opp_idx, src, state) else {
                return false;
            };
            // Python (effects.py:3941) は targets を順に 1 体ずつ処理する (置換で盤面が動く)。
            // タグで追跡し、 相手キャラは protect/ko_immune/置換を尊重 + 離脱 trigger を都度発火。
            let toks: Vec<(usize, Option<u64>)> = targets
                .iter()
                .filter(|&&(_, sl)| matches!(sl, Slot::Char(_)))
                .map(|&(pi, sl)| (pi, tag_src(state, pi, sl)))
                .collect();
            let mut any = false;
            for (pi, tok) in toks {
                let Slot::Char(idx) = find_tagged(state, pi, tok) else { continue };
                if pi == opp_idx {
                    {
                        let c = &state.players[pi].characters[idx];
                        if c.protect_from_opp_effect || c.static_ko_immune {
                            continue;
                        }
                    }
                    match try_replace_ko(state, pi, idx, true, "return_to_hand") {
                        Ok(true) => continue,
                        Ok(false) => {}
                        Err(e) => {
                            note_unknown_key("rth", &format!("replace: {e}"));
                            return false;
                        }
                    }
                let ip = state.players[pi].characters.remove(idx);
                    let don = ip.attached_dons;
                    state.players[pi].known_hand_card_ids.push(ip.card.card_id.clone());
                    state.players[pi].hand.push(ip.card);
                    state.players[pi].don_rested += don;
                    any = true;
                    // 相手効果による離脱 → victim 側の【自分のキャラが相手の効果で場を離れた時】
                    state.last_chara_ko_victim_card = None;
                    if let Err(e) = fire_field_when(state, pi, "on_self_chara_leave_by_opp_effect") {
                        note_unknown_key("rth", &format!("leave_by_opp: {e}"));
                        return false;
                    }
                    state.last_chara_ko_victim_card = None;
                } else {
                    // 両陣営 target の自キャラ bounce (持ち主 = me の手札へ、 known には載せない)。
                let ip = state.players[pi].characters.remove(idx);
                    let don = ip.attached_dons;
                    state.players[pi].hand.push(ip.card);
                    state.players[pi].don_rested += don;
                    any = true;
                }
            }
            // OP13-119 「そうした場合」 gate 用 (effects.py:3970)。
            state.last_return_to_hand_success = any;
            if any {
                if let Err(e) = fire_leave_by_self_effect(state, me_idx) {
                    note_unknown_key("rth", &format!("leave_by_self: {e}"));
                    return false;
                }
                if let Err(e) =
                    fire_field_when(state, me_idx, "on_opp_chara_returned_to_hand_by_self_effect")
                {
                    note_unknown_key("rth", &format!("returned_by_self: {e}"));
                    return false;
                }
            }
            true
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
            let Some(targets) = resolve_target(Some(&tgt_spec), me_idx, opp_idx, src, state) else {
                return false;
            };
            // Python (effects.py:5376) は targets を順に 1 体ずつ処理する。 タグ追跡で index ずれを吸収。
            let toks: Vec<(usize, Option<u64>)> = targets
                .iter()
                .filter(|&&(_, sl)| matches!(sl, Slot::Char(_)))
                .map(|&(pi, sl)| (pi, tag_src(state, pi, sl)))
                .collect();
            let mut any = false;
            for (pi, tok) in toks {
                let Slot::Char(idx) = find_tagged(state, pi, tok) else { continue };
                if pi == opp_idx {
                    {
                        let c = &state.players[pi].characters[idx];
                        if c.protect_from_opp_effect || c.static_ko_immune {
                            continue;
                        }
                    }
                    match try_replace_ko(state, pi, idx, true, "return_to_deck_bottom") {
                        Ok(true) => continue,
                        Ok(false) => {}
                        Err(e) => {
                            note_unknown_key("rtdb", &format!("replace: {e}"));
                            return false;
                        }
                    }
                }
                let ip = state.players[pi].characters.remove(idx);
                let don = ip.attached_dons;
                state.players[pi].deck.push(ip.card);
                state.players[pi].don_rested += don;
                any = true;
                if pi == opp_idx {
                    state.last_chara_ko_victim_card = None;
                    if let Err(e) = fire_field_when(state, pi, "on_self_chara_leave_by_opp_effect") {
                        note_unknown_key("rtdb", &format!("leave_by_opp: {e}"));
                        return false;
                    }
                    state.last_chara_ko_victim_card = None;
                }
            }
            if any {
                if let Err(e) = fire_leave_by_self_effect(state, me_idx) {
                    note_unknown_key("rtdb", &format!("leave_by_self: {e}"));
                    return false;
                }
            }
            true
        }
        // デッキ上 N 枚を見て filter マッチ先頭 M 枚を手札、 残りをデッキ下 (effects.py:4037)。
        // ⚠ destination=hand + rest_remain=bottom のみ対応 (play/life/trash/top_or_bottom は skip)。
        // AI 選択 = 決定的 (filter マッチの先頭 limit 枚 = deck 順)。
        "search_top_n" => {
            let destination = v.get("destination").and_then(|x| x.as_str()).unwrap_or("hand");
            let rest_remain = v.get("rest_remain").and_then(|x| x.as_str()).unwrap_or("bottom");
            if !matches!(destination, "hand" | "play" | "trash" | "life" | "life_face_up")
                || !(rest_remain == "bottom" || rest_remain == "trash" || rest_remain == "top_or_bottom")
            {
                return false;
            }
            let rested_flag = v.get("rested").and_then(|x| x.as_bool()).unwrap_or(false);
            let rest_to_trash = rest_remain == "trash";
            let rest_top_or_bottom = rest_remain == "top_or_bottom";
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
            let mut to_play: Vec<crate::state::CardDef> = vec![];
            for c in seen {
                if picked < limit && matches_filter(&c, filt) {
                    let cid = c.card_id.clone();
                    match destination {
                        "play" => to_play.push(c),
                        "trash" => me.trash.push(c),
                        "life" | "life_face_up" => {
                            me.life.insert(0, c);
                            if destination == "life_face_up" {
                                me.face_up_life_count =
                                    (me.face_up_life_count + 1).min(me.life.len() as i32);
                            }
                        }
                        _ => {
                            me.hand.push(c);
                            if public {
                                me.known_hand_card_ids.push(cid);
                            }
                        }
                    }
                    picked += 1;
                } else {
                    remaining.push(c);
                }
            }
            // destination="play": CHARACTER は登場 (field-full は最弱 trash / sickness=true)、
            // STAGE はステージ登場、 それ以外は手札へフォールバック (effects.py:4193)。
            for c in to_play {
                match c.category {
                    crate::state::Category::Stage => {
                        while state.players[me_idx].stages.len() >= 1 {
                            let old = state.players[me_idx].stages.pop().unwrap();
                            let ad = old.attached_dons;
                            state.players[me_idx].trash.push(old.card);
                            state.players[me_idx].don_rested += ad;
                        }
                        let ip = InPlay::of(c, false);
                        state.players[me_idx].stages.push(ip);
                        let pidx = state.players[me_idx].stages.len() - 1;
                        if execute_stage_on_play(state, me_idx, pidx).is_err() {
                            return false;
                        }
                    }
                    crate::state::Category::Character => {
                        trash_weakest_for_field_full(state, me_idx);
                        let mut ip = InPlay::of(c.clone(), true);
                        ip.rested = rested_flag;
                        state.players[me_idx].characters.push(ip);
                        let pidx = state.players[me_idx].characters.len() - 1;
                        state.last_self_chara_played_card = Some(c);
                        state.last_self_chara_played_from_trash = false;
                        if execute_on_play(state, me_idx, pidx).is_err() {
                            return false;
                        }
                    }
                    _ => state.players[me_idx].hand.push(c),
                }
            }
            let me = &mut state.players[me_idx];
            // rest_remain="top_or_bottom" (effects.py:4249): 「残りをデッキの上または下に置く」。
            // AI 判断 = 次ターンに払えるコスト (don_active+1 以下) の中で power/1000 + counter/1000 が
            // 最大の 1 枚を **上** へ (= 次ドロー確定)、 残りは下へ。 tie は先に現れた方 (Python は > 比較)。
            if rest_top_or_bottom && !remaining.is_empty() {
                let cap = me.don_active + 1;
                let mut best_i: Option<usize> = None;
                let mut best_v = 0.0f64;
                for (i, c) in remaining.iter().enumerate() {
                    if c.cost > cap {
                        continue;
                    }
                    let v = c.power as f64 / 1000.0 + c.counter as f64 / 1000.0;
                    if v > best_v {
                        best_v = v;
                        best_i = Some(i);
                    }
                }
                if let Some(i) = best_i {
                    let top_card = remaining.remove(i);
                    me.known_top_card_ids.push(top_card.card_id.clone());
                    me.deck.insert(0, top_card);
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
                // ⭐ 「自分のライフが0枚になった時」 は **0 になった瞬間の事象** (cardqa_op_05 /
                //   OP05-098 エネル)。 効果ダメージ経路も Python `_resolve_life_taken` を通るので
                //   同じ位置で発火する。 ⚠ 上の 「ライフ空で on_life_zero 持ち → bail」 guard に
                //   よりここへ来る時点で 相手は on_life_zero を持たない or ライフが残っていた。
                if state.players[opp_idx].life.is_empty() {
                    let lcid0 = state.players[opp_idx].leader.card.card_id.clone();
                    if card_has_when(&lcid0, "on_life_zero")
                        && fire_on_life_zero(state, opp_idx).is_err()
                    {
                        return false; // 未対応 = 明示 bail (呼出側で Err)
                    }
                }
                let cid = taken.card_id.clone();
                // ⭐ 効果ダメージでも **ライフ札の【トリガー】は発動できる** (公式 cardqa_eb_03 /
                //   rules 7-1-4-1-1-2 line 180: 「1ダメージ → 相手はライフ上1枚を手札へ or
                //   トリガー発動」)。 旧実装は hand.push 直行 = トリガー握り潰し (Python と同型なので
                //   差分検証では沈黙)。 Python (engine/effects.py:deal_opp_leader_damage →
                //   game.py:_resolve_life_taken(by_effect=True)) がトリガーを正しく発動する。
                // ⚠ トリガーが **発動する** 局面は Rust では bail (= Python が source of truth)。
                //   効果ダメージ経路の play_self trash routing は 戦闘 (rules.rs) と微妙に順序が
                //   異なり bit 一致が難しい (= 対象 2 枚 / 稀ケース)。 Rust の不変条件
                //   「Python と bit 一致 or 明示 bail」 に従い、 トリガー発動時は bail する。
                //   トリガー無し (= 手札へ) の局面だけ inline で bit 一致させる。
                let went_to_hand = match crate::effects::should_fire_trigger(state, opp_idx, &cid) {
                    Some(false) => {
                        state.players[opp_idx].hand.push(taken);
                        true
                    }
                    _ => return false,
                };
                // ⭐ 効果で相手ライフが離れた時も 「相手のライフが離れた時」 は発火する
                // (cardqa_op_08 / OP08-105 ボニー)。 Python `_fire_opp_life_left_by_effect` と対称。
                // ⚠ `on_self_life_taken` (= ダメージを受けた時) は戦闘ダメージ専用なので発火しない。
                // enqueue+単一 resolve (inline 直呼び禁止、 fire_self_life_to_hand と同じ理由)。
                if fire_opp_life_left_by_effect(
                    state, me_idx, opp_idx, if went_to_hand { "hand" } else { "trash" },
                ).is_err() {
                    return false;
                }
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
            // 「ドンをドンデッキに戻した時」 (EB02-035 / P-077)。 発火できるので bail 不要。
            if moved > 0 {
                state.last_returned_don_count = moved;
                // ⚠ Python(trigger_on_self_don_returned_to_deck) は enqueue → _maybe_resolve なので、
                //   **効果の解決中は後回し** になる (resolving=True で _maybe_resolve が no-op)。
                //   Rust が inline 発火していると 「KO が先に起きて盤面が縮む」 = 対象がズレる
                //   (OP06-075 のドン-1 → 相手 OP06-076 の KO、 2026-08-04 掃引)。 必ず enqueue。
if me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
                    enqueue_field_when(state, me_idx, "on_self_don_returned_to_deck");
                    if maybe_resolve(state).is_err() {
                        return false;
                    }
                }
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
        // 「その後、 このバトル終了時、 このキャラを持ち主のデッキの下に置く」 (effects.py:6934、
        // OP02-064 ボン・クレー)。 発動元に flag を立てるだけで、 実際の移動は バトル終了フック
        // (rules.rs:reset_battle_buffs) が行う。 発動元が場に居ない (Detached) 時は Python も
        // `if self_inplay is not None` で no-op。
        "schedule_self_return_to_deck_bottom_at_battle_end" => {
            if let Some(ip) = src_ip_mut(&mut state.players[me_idx], src) {
                ip.return_to_deck_bottom_at_battle_end = true;
            }
            true
        }
        // このターン中、 自効果ドロー禁止 (effects.py:block_self_draw_turn、 OP12-099 on_self_life_to_hand)。
        "block_self_draw_turn" => {
            state.players[me_idx].block_self_draw_until_turn_end = true;
            true
        }
        // 「自分は、 このターン中、 キャラの効果でドン‼をアクティブにできない」
        // (EB04-016 トリ / OP10-030 スモーカー の 「その後、」 節、 effects.py と同名 primitive)。
        "block_chara_effect_untap_don_turn" => {
            state.players[me_idx].block_chara_effect_untap_don_until_turn_end = true;
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
    /// KO としてトラッシュへ (= このターンの被 KO 数に数える)。
    Trash,
    /// **KO ではなく** 「トラッシュに置く」 (= 被 KO 数に数えない、【KO時】も発火しない)。
    /// 公式は 「KOする」 と 「トラッシュに置く」 を書き分けている (OP13-082 五老星)。
    TrashNoKo,
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
            // 「トラッシュに置く」 = KO ではないので被 KO 数を増やさない (Python も増やさない)。
            RemoveDest::TrashNoKo => state.players[pi].trash.push(card),
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
        // area 不足 → 付与ドンから (effects.py:815、 power 昇順で温存。 Python の
        // sorted([*characters, leader], key=power) は安定ソート = tie は characters→leader の順)。
        let mut order: Vec<Slot> = (0..me.characters.len()).map(Slot::Char).collect();
        order.push(Slot::Leader);
        order.sort_by_key(|&s| get_ip(me, s).power());
        for s in order {
            if removed >= n {
                break;
            }
            let ip = get_ip_mut(me, s);
            let take = (n - removed).min(ip.attached_dons);
            ip.attached_dons -= take;
            me.don_remaining_in_deck += take;
            removed += take;
        }
    }
    if removed < n {
        return false; // 場のドンを全部返しても足りない (Python は部分払いだが Rust は bail = 保守的)
    }
    state.last_returned_don_count = removed;
    true
}


/// on_play / main / on_ko / on_block 等 when-effect の cost を支払う (effects.py:391 の AI 経路)。
/// Python は `real_cost = cost - once_per_turn` を `_can_pay_counter_cost` → `_pay_counter_cost` に
/// 通す = counter cost と同一機構。 Rust も同じ経路に委譲する (独自実装だと対応 cost 種別がズレる)。
/// Some(true)=支払い済で発動 / Some(false)=支払い不能で skip / None=未対応 cost 種別で bail。
/// ⚠ once_per_turn は呼出側 (execute_card_effects) の gate が扱う。
fn pay_on_play_cost(cost: &Value, state: &mut GameState, me_idx: usize, src: Slot) -> Option<bool> {
    let real: Value = match cost {
        Value::Object(o) => Value::Object(
            o.iter().filter(|(k, _)| k.as_str() != "once_per_turn").map(|(k, v)| (k.clone(), v.clone())).collect(),
        ),
        Value::Array(_) => cost.clone(),
        _ => return None,
    };
    if cost_is_empty(&real) {
        return Some(true);
    }
    match try_pay_counter_cost(state, me_idx, src, &real) {
        Ok(paid) => Some(paid),
        Err(_) => None,
    }
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
            // draw は prim 側で on_self_draw_non_draw_phase を自前発火する → block 不要。
            // ko (single) は prim 側で cascade を自前処理 (single victim) or 内部 bail → ここでは block しない。
            // ko_multi は prim 側で cascade を自前処理 (single victim) or 明示 bail するので block しない。
            // ko_all_others は prim 側でタグ追跡の逐次 KO + cascade を自前処理する → block 不要。
            // return_to_hand/deck_bottom (single) は prim 側で cascade を自前処理 → ここでは block しない。
            // return_to_deck_bottom_multi も prim 側で actor 側 leave trigger を発火 + 相手 replace は
            // 明示 bail するので block 不要 (OP06-056)。
            // return_to_hand_multi は prim 側で leave trigger を発火 + 置換も処理する → block 不要。
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
    // 発動元が 「効果無効」 なら主要 when は発動しない (effects.py:_execute_event の gate)。
    if src_effect_negated(state, me_idx, src, when) {
        return Ok(());
    }
    // ⚠ 公式 「**相手は**…してもよい」 (bundle 直下 actor:"opp" / optional) は
    //   **相手の側で解決し、 相手が決める** (cardqa_op_12、 OP12-075 ミス・オールサンデー)。
    //   Rust は未実装なので **bail** する。 素通りさせると Rust だけ発動者側に解決して黙って乖離。

    // 発火追跡 (診断時のみ)。 「デッキに入っている」≠「効果が実行された」を区別する。
    if effs.iter().any(|e| e.get("when").and_then(|v| v.as_str()) == Some(when)) {
        crate::selfplay::note_fired(card_id);
    }
    for (idx, eff) in effs.iter().enumerate() {
        if eff.get("when").and_then(|v| v.as_str()) != Some(when) {
            continue;
        }
        // 【ターン1回】 ガード (effects.py:352 `_check_and_set_once_per_turn`)。 Python は
        // once_per_turn_used (iid キー、 canonical 外) で判定するが、 mirror 対象 when は
        // InPlay.event_once_used / Player.once_shared_used に同じ内容が載るので Rust はそれを見る。
        // mirror 外 when (= main/counter/trigger 等 source が場に無い) は追跡不能 → bail。
        let once_opt = eff
            .get("once_per_turn")
            .or_else(|| eff.get("cost").and_then(|c| c.get("once_per_turn")));
        if let Some(o) = once_opt {
            if let Some(shared) = o.as_str() {
                let key = format!("key:{shared}");
                if state.players[me_idx].once_shared_used.contains(&key) {
                    continue;
                }
            } else if o.as_bool() == Some(true) {
                if !field_when_once_mirrored(when) || src == Slot::Detached {
                    return Err(format!("{when} once_per_turn 未対応 ({card_id})"));
                }
                let key = format!("{when}:{idx}");
                match src_ip(&state.players[me_idx], src) {
                    Some(ip) if ip.event_once_used.contains(&key) => continue,
                    Some(_) => {}
                    None => return Err(format!("{when} once_per_turn: src 不在 ({card_id})")),
                }
            }
        }
        match eval_effect_conditions(eff, state, me_idx, Some(src)) {
            Some(true) => {}
            Some(false) => continue,       // 条件不成立 = Python も発動しない
            None => return Err(format!("{when} 条件 unknown ({card_id})")),
        }
        // once mark は条件成立後 = Python (_check_and_set は cost/条件より前だが、 条件不成立時は
        // そもそも _check_and_set まで来ない: effects.py:340 で if 条件 → 352 で once) と同順。
        if once_opt.and_then(|o| o.as_bool()) == Some(true) {
            if let Some(ip) = src_ip_mut(&mut state.players[me_idx], src) {
                ip.mark_event_once(when, idx as i64);
            }
        }
        if let Some(shared) = once_opt.and_then(|o| o.as_str()) {
            let key = format!("key:{shared}");
            let used = &mut state.players[me_idx].once_shared_used;
            if !used.contains(&key) {
                used.push(key);
                used.sort();
            }
        }
        if let Some(cost) = eff.get("cost") {
            match pay_on_play_cost(cost, state, me_idx, src) {
                Some(true) => {}
                Some(false) => continue,   // cost 払えない = Python も skip
                None => return Err(format!("{when} cost 未対応 ({card_id})")),
            }
        }
        // ⭐ 公式 「**相手は**…してもよい」 (bundle 直下 actor:"opp") = **相手の側で解決する**
        //   (cardqa_op_12、 OP12-075 ミス・オールサンデー: 「相手がドン!!を追加するかどうかを
        //   決めます」)。 効果の 「自分」 は相手プレイヤー。 発動元は相手の場に無いので
        //   src は使わない (Python も self_inplay=None で実行)。 AI は 「してもよい」 を行使する。
        if eff.get("actor").and_then(|v| v.as_str()) == Some("opp") {
            if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
                for prim in dos.iter() {
                    if !execute_effect(prim, state, 1 - me_idx, Slot::Detached) {
                        let k = prim.as_object().and_then(|o| o.keys().next())
                            .map(|s| s.as_str()).unwrap_or("?");
                        return Err(format!("{when} actor:opp primitive 未対応: {k} ({card_id})"));
                    }
                }
            }
            continue;
        }
        if let Some(dos) = eff.get("do").and_then(|v| v.as_array()) {
            if effect_cascade_blocked(dos, state, me_idx) {
                return Err(format!("{when} cascade 未対応 ({card_id})"));
            }
            // do の途中で盤面が動いても発動元を見失わないよう一意トークンで追跡する
            // (Python の self_inplay object 参照と等価。 場外に出たら Detached)。
            let mut cur = src;
            let mut tok = tag_src(state, me_idx, cur);
            for prim in dos.iter() {
                let snap = src_ip(&state.players[me_idx], cur).cloned();
                if !execute_effect(prim, state, me_idx, cur) {
                    let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("?");
                    find_tagged(state, me_idx, tok);
                    return Err(format!("{when} primitive 未対応: {k} ({card_id})"));
                }
                cur = find_tagged(state, me_idx, tok);
                if cur == Slot::Detached {
                    // 発動元がこの primitive で場を離れた → 直前スナップショットを残す
                    // (アタック解決が attacker の power/cost を読むため)。
                    if snap.is_some() {
                        state.rust_detached_src = snap;
                    }
                    tok = None;
                } else {
                    tok = tag_src(state, me_idx, cur);
                }
            }
            find_tagged(state, me_idx, tok);
        }
    }
    Ok(())
}

/// レストされた char 自身の【レスト時】(on_self_rested) を発火 (effects.py:trigger_on_self_rested、 targeted)。
/// bundle = rested char の overlay。 条件 (self_turn 等) を src=rested char で eval、 costless のみ発火、
/// cost(once_per_turn は iid-keyed=canonical外)/unknown/未対応 prim は Err で bail。
pub fn fire_on_self_rested(state: &mut GameState, owner_idx: usize, char_idx: usize) -> Result<(), String> {
    fire_on_self_rested_impl(state, owner_idx, char_idx, false)
}

/// costless_only=true (アタック由来の自己レスト): cost 持ちの on_self_rested は発火せず skip する
/// (bail でなく continue)。 cost 持ちは optional (OP14-021/070) か by_opp 系 (OP14-070/PRB02-009) で
/// 自分のアタックでは発火すべきでない。 costless の【自分のターン中】系だけがアタックで発火する
/// (公式 cardqa_op_14 677c149d0045)。 Python trigger_on_self_rested の costless_only と bit 一致。
pub fn fire_on_self_rested_impl(state: &mut GameState, owner_idx: usize, char_idx: usize, costless_only: bool) -> Result<(), String> {
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
        // costless_only: cost 持ち (once_per_turn のみは costless 扱い) は skip。
        if costless_only {
            if let Some(cost) = eff.get("cost") {
                let cost_has_real = cost.as_object().map_or(false, |o| {
                    o.keys().any(|k| k != "once_per_turn")
                });
                if cost_has_real {
                    continue;
                }
            }
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
/// 直近に primitive 内部で発生した Err 文字列 (execute_effect は bool しか返せないので、 bail の
/// 理由を診断で読めるようにする為の置き場)。 correctness には影響しない。
pub static LAST_PRIM_ERR: std::sync::Mutex<String> = std::sync::Mutex::new(String::new());

pub fn note_prim_err(e: &str) {
    if let Ok(mut m) = LAST_PRIM_ERR.lock() {
        *m = e.to_string();
    }
}

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
    // ⚠ 「**キャラ**が自分の効果でレストになった時」 は 持ち主を修飾していない = **両陣営**
    //   (2026-08-10 に Python `_fire_rested_triggers` を両陣営へ是正)。 発火側 (me_idx) の場に
    //   反応カードがあれば、 レストされたのが どちらの陣営でも 未対応 bail にする。
    if me_board_has_when(state, me_idx, "on_self_chara_rested_by_self_effect") {
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
    // ⭐ 「キャラの効果でキャラを登場させた時」 (cardqa_op_12 / OP12-081) 判定用。
    //   ここは **効果由来の登場** 経路 (play_from_hand 等) からも通常登場からも呼ばれるので、
    //   呼出側が state.rust_play_source_is_field_chara に立てた値をそのまま反映する。
    state.last_chara_played_by_field_chara = state.rust_play_source_is_field_chara;
    let card_id = state.players[me_idx].characters[played_idx].card.card_id.clone();
    // Python (effects.py:trigger_on_play) は ①②③ を **enqueue** してから _maybe_resolve を呼ぶ。
    // _maybe_resolve は resolving=true (= 既にトリガー解決中) なら no-op なので、 **トリガーの中で
    // 登場したキャラの on_play は後回し** になる (外側の do-list が zone 操作を終えてから発火)。
    // ここを inline 実行していたため zone 並べ替えを含む on_play で順序がズレ bail していた。
    if !state.players[me_idx].opp_on_play_disabled_through_opp_turn {
        enqueue_trigger(state, "on_play", me_idx, &card_id, Slot::Char(played_idx));
    }
    // ⚠ 「自分のキャラが登場した時」 は **場の全カード** が反応する field-when (Python
    //   trigger_on_play → `_enqueue_field_when(me, "on_self_chara_played")`)。 登場カードを
    //   card_id に載せた marker を積むと 「登場カード自身の効果だけ」 を発火してしまう
    //   (2026-08-10: リーダー OP14-041 の 「相手のターン中 自分のキャラ登場時 1ドロー」 が
    //    丸ごと不発になり MISMATCH)。 反応集合は enqueue 時にカード単位で確定させる。
    enqueue_field_when(state, me_idx, "on_self_chara_played");
    // payload-aware 条件 `played_chara_truly_original_cost_ge` (OP12-081 コアラ) の参照先。
    // ⚠ Rust は この field を **一度も set していなかった** ため条件が常に false = 相手の
    //   【相手がキャラを登場させた時】が丸ごと不発だった (2026-08-04 掃引 MISMATCH)。
    //   Python (effects.py:10959) と同じく enqueue の直前に set し、 drain 後に None へ戻す。
    state.last_opp_chara_played_card =
        Some(state.players[me_idx].characters[played_idx].card.clone());
    enqueue_field_when(state, opp, "on_opp_chara_played");
    let r = maybe_resolve(state);
    state.last_opp_chara_played_card = None;
    r
}

/// キューに積まれたトリガー 1 件 (Python effects.py:TriggerEvent の移植)。
/// slot は発火元の位置。 drain 時に card_id 照合し、 ズレていれば一意な位置へ追随 (曖昧なら bail)。
#[derive(Clone, Debug, PartialEq)]
pub struct PendingTrigger {
    pub when: String,
    pub owner_idx: usize,
    pub card_id: String,
    pub slot: Slot,
    /// 発火元を一意に追う token (enqueue 時に打つ)。 drain までに盤面が動いても位置を復元できる
    /// = Python の source_iid 相当。 同名複数でも取り違えない。
    pub tok: Option<u64>,
    /// Python の `payload["effect_indexes"]` 相当。 Some = **コスト支払い済で do だけ残っている**
    /// 効果の index 列 (end_of_turn / opp_end_of_turn)。 None = when 一致の効果を通常判定で発火。
    pub eff_idxs: Option<Vec<usize>>,
}

/// トリガーをキューに積む (Python:enqueue_event)。
fn enqueue_trigger(state: &mut GameState, when: &str, owner_idx: usize, card_id: &str, slot: Slot) {
    let tok = tag_src(state, owner_idx, slot);
    state.rust_event_queue.push(PendingTrigger {
        when: when.to_string(),
        owner_idx,
        card_id: card_id.to_string(),
        slot,
        tok,
        eff_idxs: None,
    });
}

/// 場全体の field-when を **キューに積む** (= Python の trigger_* + _maybe_resolve と同じ挙動)。
///
/// Python は trigger_on_self_don_returned_to_deck 等で enqueue → _maybe_resolve を呼ぶが、
/// _maybe_resolve は `state.resolving` (= 既に効果解決中) なら早期 return する。 つまり
/// **効果の内側で起きたカスケードは、 その効果の do を終えてから** FIFO 順で処理される。
/// inline 発火すると順序が逆になり、 両方が KO する盤面でトラッシュの並びが入れ替わる
/// (OP06-074 ゼファーのコストが OP06-076 人斬り鎌ぞうの誘発を呼ぶ、 2026-08-04 発覚)。
///
/// 解決中でなければ Python 同様その場で drain される (maybe_resolve が回る)。
///
/// ⭐ **反応集合は enqueue 時に確定する** (2026-08-10)。 Python `_enqueue_field_when` は
/// 「その when を持つカード」 を **enqueue した瞬間の場から カード単位で** 積む。 以前の Rust は
/// 1 件だけ積んで **drain 時に場を走査** していたため、 enqueue と drain の間に盤面が動くと
/// **反応するカードの集合そのもの** が食い違った (= 順序を揃えても消えない差、
/// [[reference_rust_mismatch_root_cause_taxonomy]] 2b)。
fn enqueue_field_when(state: &mut GameState, owner_idx: usize, when: &str) {
    let toks = snapshot_field_toks(state, owner_idx);
    for (tok, cid) in toks {
        if !card_has_when(&cid, when) {
            continue;
        }
        state.rust_event_queue.push(PendingTrigger {
            when: when.to_string(),
            owner_idx,
            card_id: cid,
            slot: Slot::Leader, // field-when は tok で位置を引き直す (slot は未使用)
            tok,
            eff_idxs: None,
        });
    }
}

/// 自己効果で自分のライフが手札に加わった時の on_self_life_to_hand 発火 (effects.py:
/// fire_self_life_to_hand)。 ⚠ `fire_field_when` (inline 即時発火) を直接呼んではいけない —
/// Python は enqueue → _maybe_resolve なので、 これがネストして呼ばれた場合 (= 他の on_attack/
/// on_ko 等の do-list 実行中) は resolving=true により後回しになる。 inline 直呼びだと
/// ネスト元の do-list 残りより先に発火してしまう (OP08-098 カルガラの on_attack →
/// play_from_hand(then_life_to_hand) → ここが該当、 2026-08-07 発覚)。
fn fire_self_life_to_hand(state: &mut GameState, owner_idx: usize) -> Result<(), String> {
    enqueue_field_when(state, owner_idx, "on_self_life_to_hand");
    // ⭐ 「相手のライフが離れた時」 (on_opp_life_taken) は **離れ方を問わない**
    //   (公式 cardqa_op_08、 OP08-105 ボニー = 相手が自分の効果で自ライフを手札に加えた時も発動)。
    //   fire_opp_life_left_by_effect (= 自分が相手のライフを取り除く経路) と対称に、
    //   **自分でライフを手札へ移した** 経路でも観測側 (相手) に発火させる。
    enqueue_field_when(state, 1 - owner_idx, "on_opp_life_taken");
    maybe_resolve(state)
}

/// 効果で相手のライフが離れた時のトリガー発火 (effects.py:_fire_opp_life_left_by_effect)。
/// on_opp_life_taken (me 側) + on_self_life_to_hand/on_self_life_to_trash (opp 側、 dest で分岐) を
/// **enqueue してから 1 回だけ** maybe_resolve する (= fire_self_life_to_hand と同じ理由で
/// inline 直呼び禁止)。 dest: "hand" | "trash" | それ以外 (= opp 側トリガー無し、 deck 等)。
fn fire_opp_life_left_by_effect(
    state: &mut GameState,
    me_idx: usize,
    opp_idx: usize,
    dest: &str,
) -> Result<(), String> {
    enqueue_field_when(state, me_idx, "on_opp_life_taken");
    match dest {
        "hand" => enqueue_field_when(state, opp_idx, "on_self_life_to_hand"),
        "trash" => enqueue_field_when(state, opp_idx, "on_self_life_to_trash"),
        _ => {}
    }
    maybe_resolve(state)
}

/// Python:_pop_next_event = ターンプレイヤー側を優先し、 同 owner 内は FIFO。
fn pop_next_event(state: &mut GameState) -> Option<PendingTrigger> {
    if state.rust_event_queue.is_empty() {
        return None;
    }
    let turn_idx = state.turn_player_idx;
    let pos = state
        .rust_event_queue
        .iter()
        .position(|e| e.owner_idx == turn_idx)
        .unwrap_or(0);
    Some(state.rust_event_queue.remove(pos))
}

/// Python:_maybe_resolve + resolve_triggers = 再入なら no-op、 そうでなければ空になるまで drain。
pub fn maybe_resolve(state: &mut GameState) -> Result<(), String> {
    if state.rust_resolving || state.rust_event_queue.is_empty() {
        return Ok(());
    }
    state.rust_resolving = true;
    let r = (|| -> Result<(), String> {
        while let Some(evt) = pop_next_event(state) {
            execute_pending(state, &evt)?;
        }
        Ok(())
    })();
    state.rust_resolving = false;
    r
}

/// キューから取り出した 1 件を実行。 on_play は発火元スロットの card_id を照合し、
/// ズレていたら同 card_id が一意な位置へ追随する (曖昧なら明示 bail = 誤発火を作らない)。
fn execute_pending(state: &mut GameState, evt: &PendingTrigger) -> Result<(), String> {
    // コスト支払い済 (= end_of_turn / opp_end_of_turn) は do だけを解決する。
    if evt.eff_idxs.is_some() {
        return run_explicit_idx_event(state, evt);
    }
    match evt.when.as_str() {
        "on_play" => {
            let me = evt.owner_idx;
            // enqueue 時に打ったトークンで発火元の現在位置を復元する (Python の source_iid 相当)。
            // 見つからない = drain 前に場を離れた → Python も self_inplay=None で早期 return。
            let slot = match evt.slot {
                Slot::Char(_) => match find_tagged(state, me, evt.tok) {
                    Slot::Char(i) => Slot::Char(i),
                    _ => return Ok(()),
                },
                other => {
                    find_tagged(state, me, evt.tok);
                    other
                }
            };
            execute_card_effects(state, me, &evt.card_id, "on_play", slot)
        }
        // field-when は **enqueue 時にカード単位でスナップショット** 済 (card_id + tok)。
        // card_id 空 = 旧形式 (場全体を drain 時に走査) は残っていないはずだが、 保険で従来経路へ。
        w if !evt.card_id.is_empty() => {
            fire_field_when_one(state, evt.owner_idx, w, evt.tok, &evt.card_id.clone())
        }
        w => fire_field_when(state, evt.owner_idx, w),
    }
}

/// player の場に指定 when 効果を持つカードがあるか (draw cascade guard 用)。
fn me_board_has_when(state: &GameState, pi: usize, when: &str) -> bool {
    let p = &state.players[pi];
    if std::iter::once(&p.leader)
        .chain(p.characters.iter())
        .chain(p.stages.iter())
        .any(|ip| card_has_when(&ip.card.card_id, when))
    {
        return true;
    }
    // ⭐ 「離脱した本人」 が反応するケース (cardqa_op_08 / OP08-046) は、 発火時点で本人が
    //   **もう盤面に居ない** ので上の走査では拾えない。 ここで false を返すと呼出側が
    //   `me_board_has_when(..) && fire_field_when(..)` で短絡し、 fire_field_when 内の bail guard に
    //   **到達しないまま Rust だけ無反応** = 黙って乖離する (MISMATCH)。 公開領域も見て true を返し、
    //   必ず fire_field_when へ流して そこで明示 bail させる。
    if when == "on_self_chara_leave_by_self_effect" {
        return public_zone_has_leave_actor(state, pi, when);
    }
    false
}

/// 自分のトラッシュ / 表向きライフに、 指定 when を持つ **CHARACTER** が居るか。
/// (= 「離脱した本人が反応する」 可能性がある局面か。 過剰検出でよい = bail に倒す為)
fn public_zone_has_leave_actor(state: &GameState, pi: usize, when: &str) -> bool {
    let Some(ov) = overlay() else { return false };
    state.rust_departed_to_public.iter().any(|(owner, cid)| {
        *owner == pi
            && ov.get(cid).map_or(false, |b| {
                b.iter().any(|e| e.get("when").and_then(|w| w.as_str()) == Some(when))
            })
    })
}

/// 「自分の効果で場を離れ、 行き先が公開領域 (トラッシュ / 表向きライフ)」 を台帳に記録する
/// (effects.py:`_note_public_departure`)。 公式 cardqa_op_08 / OP08-046 シャクヤク:
/// 離脱した **本人** も on_self_chara_leave_by_self_effect を発動できる (公開領域行きの時のみ)。
/// ⚠ 「キャラが」 の文面なので **CHARACTER のみ** (STAGE は対象外)。
/// 直後の `fire_leave_by_self_effect` が consume + clear する。
pub(crate) fn note_public_departure(state: &mut GameState, owner_idx: usize, card: &CardDef) {
    if overlay().is_none() {
        return;
    }
    if card.category != crate::state::Category::Character {
        return;
    }
    state
        .rust_departed_to_public
        .push((owner_idx, card.card_id.clone()));
}

/// 「キャラが自分の効果で場を離れた時」 の発火 (effects.py:
/// `trigger_on_self_chara_leave_by_self_effect`)。 場のカードの反応 (= 通常の field-when) に加えて、
/// **離脱した本人** (台帳 = 公開領域行きのみ) の効果も発動させる。
pub(crate) fn fire_leave_by_self_effect(state: &mut GameState, actor_idx: usize) -> Result<(), String> {
    const WHEN: &str = "on_self_chara_leave_by_self_effect";
    // ⭐ victim 文脈 (Python trigger_on_self_chara_leave_by_self_effect と同じ差分計算)。
    if let Some(snap) = state.rust_leave_victim_snapshot.clone() {
        let mut after: Vec<String> = state.players[actor_idx]
            .characters
            .iter()
            .map(|c| c.card.card_id.clone())
            .collect();
        let mut gone: Vec<CardDef> = Vec::new();
        for c in snap {
            if let Some(pos) = after.iter().position(|x| *x == c.card_id) {
                after.remove(pos); // 残っている 1 枚を相殺 (multiset 差分)
            } else {
                gone.push(c);
            }
        }
        state.rust_leave_by_self_victims = gone;
    }
    fire_field_when(state, actor_idx, WHEN)?;
    // 台帳は 「誰が反応したか」 に関わらず ここで空にする (Python も同じ = 取りこぼしを残さない)。
    let departed: Vec<(usize, String)> = std::mem::take(&mut state.rust_departed_to_public);
    let Some(ov) = overlay() else { return Ok(()) };
    for (owner, cid) in departed {
        if owner != actor_idx {
            continue; // 「自分の」 効果で離れた **自分の** カードのみ
        }
        let Some(effs) = ov.get(&cid) else { continue };
        for eff in effs.iter() {
            if eff.get("when").and_then(|v| v.as_str()) != Some(WHEN) {
                continue;
            }
            // 場外 (= Python の self_inplay=None) なので Slot::Detached で解決する。
            match eval_effect_conditions(eff, state, actor_idx, Some(Slot::Detached)) {
                Some(true) => {}
                Some(false) => continue,
                None => return Err(format!("{WHEN} 条件 unknown (離脱本人)")),
            }
            if eff.get("once_per_turn").is_some()
                || eff.get("cost").map_or(false, |c| !cost_is_empty(c))
            {
                return Err(format!("{WHEN} once/cost 未対応 (離脱本人)"));
            }
            crate::selfplay::note_fired(&cid);
            let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
            fire_gated_do(state, actor_idx, Slot::Detached, dos)?;
        }
    }
    Ok(())
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
            // rest_opp_don = 相手コストエリアの active→rested のみ (src 非参照、 cascade 無)。
            // give_attack_active_chara = キーワード付与のみ。
            | "rest_opp_don" | "give_attack_active_chara"
            // return_to_hand = prim 側で leave cascade を自前判定 or bail するので安全。
            | "return_to_hand"
            // 以下も prim 側で cascade を自前判定 or 明示 bail する (= 黙って発火漏れにしない)。
            | "return_to_deck_bottom" | "return_to_deck_bottom_multi" | "return_to_hand_multi"
            | "reveal_top_play" | "reveal_life_top_play" | "reveal_top_then"
            | "trash_to_hand" | "trash_to_deck" | "to_opp_life" | "return_opp_don"
            | "chara_to_trash" | "chara_to_self_life" | "scry_life" | "scry_all_life_one_to_deck"
            | "mill_self_life_until_n" | "set_base_cost_timed" | "give_ko_immune_through_opp_turn"
            | "to_hand_self_trigger" | "rest_multi" | "ko_total_power_le" | "ko_multi"
            | "opp_hand_to_deck_bottom" | "opp_discard_own_choice"
            | "opp_hand_to_deck_then_draw" | "extra_turn"
            | "disable_blocker" | "disable_opp_on_play_through_opp_turn" | "set_battle_ko_immune"
            | "rest_self_cards_filtered" | "ko_self_chara" | "fire_self_main"
            | "replace_ko_complex" | "draw_per_self_hand_discarded"
            // negate_effect = granted_keywords に "効果無効" を足すだけ (cascade 無)。
            | "negate_effect"
            // ko = prim 側で cascade を自前処理 (single/multi victim) or 内部 bail するので安全。
            | "ko"
            // search_top_n = デッキ上 N 枚を見て 1 枚手札へ + 残りをデッキ下 (rng 消費順も Python 準拠)。
            | "search_top_n"
            // 2026-08-02 実装分。 いずれも player-level か prim 側で cascade を自前処理/明示 bail する。
            | "trash_all_face_up_life" | "self_hand_to_size" | "return_self_don_to_match_opp"
            | "keep_opp_rested_chara_with_don_ge_next_refresh" | "swap_self_power"
            | "ko_self_chara_then_pump_leader_per" | "chara_to_opp_life"
            | "return_attached_don_to_cost_rested" | "swap_base_power_self_leader_chara"
            | "declare_cost_reveal_then" | "self_hand_to_deck_bottom" | "choice_effect"
            | "play_from_hand_or_trash" | "play_from_hand_named_with_dynamic_cost"
            | "power_pump_multi" | "trash_all_self_chara" | "choice"
            | "discard_self_to_deck_top" | "opp_don_to_deck" | "summon_from_deck"
            | "return_self_to_hand" | "give_rush" | "opp_trash_to_deck_bottom"
            | "keep_opp_rested_don_next_refresh" | "give_attribute"
            | "reduce_play_cost_filtered_turn" | "trash_opp_hand_random"
            | "set_all_life_face_down" | "hand_to_deck_bottom"
            | "schedule_self_trash_at_turn_end" | "set_ko_immune_timed"
            | "opp_hand_to_size" | "block_chara_play_cost_ge" | "draw_to_hand_size"
            | "block_self_attack_leader_turn" | "draw_per_hand_to_deck_bottom"
            | "reveal_opp_hand" | "power_pump_per_target_attached_don" | "swap_opp_power"
            | "set_ko_per_turn_immune" | "bounce_self_chara_then_play_diff_color"
            | "pay_don" | "prevent_blocker_for_attacker_power_le" | "force_opp_draw"
            | "prevent_ko" | "draw_per_self_chara_then_discard"
            | "prevent_opp_blocker_for_cost_le" | "reveal_opp_hand_and_if_event_mill_life"
            | "don_minus_opp" | "set_base_power_timed" | "return_self_to_trash" | "rest_self_don"
            | "scry_deck_reorder" | "view_life_top_choose_position"
            | "keep_opp_rested_inplay_next_refresh" | "schedule_at_opp_main_phase_start"
            | "grant_turn_battle_ko_save_discard" | "mill_top_then"
            | "summon_stage_from_deck_with_feature" | "opp_may_return_active_don_else_debuff"
            | "return_self_charas_then_pump_per" | "play_from_hand_choice"
            | "fire_event_main_from_trash" | "set_don_deck_size"
            | "flip_life_face_up_effect" | "transfer_attached_don_to_feature" | "ko_all_others"
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
    // 発動元が 「効果無効」 なら 【アタック時】 は発動しない (effects.py の gate)。
    if src_effect_negated(state, me_idx, src, "on_attack") {
        return Ok(());
    }
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
            // ⚠ Python (trigger_on_attack) は cost.once_per_turn の **値を見ず** entry index
            //   (attacker.attack_once_used) で gate する = 文字列キーでも共有されず bool と同じ。
            //   Rust だけ文字列で bail していたため、 overlay に共有キーを入れた途端 134 件の
            //   bail が出た (2026-08-03)。 Python 準拠で値によらず index gate にする。
            if !o.is_null()
                && get_ip(&state.players[me_idx], src).attack_once_used.contains(&(idx as i64))
            {
                continue; // ターン既発動
            }
        }
        // Python 12924: _can_pay_counter_cost で払えなければ skip (未対応 cost でも「払えない」なら bail せず一致)
        if !can_pay_counter_cost_full(state, me_idx, src, cost) {
            continue;
        }
        // cost が発動元自身を場から除く (trash_self / self_ko / return_self_to_hand) ことがある。
        // 直前スナップショットを残して以降の参照 (アタック解決の power/cost) を成立させる。
        let snap = src_ip(&state.players[me_idx], src).cloned();
        let tok = tag_src(state, me_idx, src);
        let paid = try_pay_counter_cost(state, me_idx, src, cost)?;
        let after = find_tagged(state, me_idx, tok);
        if after == Slot::Detached && snap.is_some() {
            state.rust_detached_src = snap;
        }
        if !paid {
            continue; // 払えない → 効果不発 (公式 4-10)
        }
        if once.and_then(|o| o.as_bool()) == Some(true) {
            if let Some(ip) = src_ip_mut(&mut state.players[me_idx], after) {
                ip.mark_attack_once(idx as i64);
            }
        }
        fired.push(idx);
    }
    // 発火フェーズ: sorted idx 順に条件再評価 + do 発火。
    // ⚠ Python (trigger_on_attack) は on_attack を **enqueue** して return するだけで、
    //   実際の do 実行は resolve_triggers の中 (resolving=true) で走る。 その間に do の中で
    //   登場したキャラ/ステージの on_play (play_from_hand/play_stage_from_hand 等) は
    //   enqueue されるだけで後回しになる。 ここで resolving guard を張らずに fire_gated_do を
    //   直接呼ぶと、 nested な execute_on_play/execute_stage_on_play が即座に drain してしまい
    //   外側の do-list 残り (このケースでは then_life_to_hand → on_self_life_to_hand cascade)
    //   より **先に** 後続カードの on_play が発火する (OP08-098 カルガラの on_attack で
    //   ワイパー→アッパーヤード の連鎖が draw/block_self_draw_turn より先に走っていた、
    //   2026-08-07 発覚)。 fire_on_ko / fire_life_trigger と同じ resolving guard を張る。
    fired.sort_unstable();
    let prev_resolving = state.rust_resolving;
    state.rust_resolving = true;
    let r = (|| -> Result<(), String> {
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
    })();
    state.rust_resolving = prev_resolving;
    if r.is_ok() && !prev_resolving {
        maybe_resolve(state)?;
    }
    r
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

    }
    // ⚠ do の途中で発動元が場を離れる (自 trash / 自 KO) ことがある。 Python は self_inplay を
    //   object 参照で保持するので、 離場後もそのオブジェクトを読み続ける。 Rust は位置 index なので
    //   一意トークンで追い、 見失ったら直前スナップショットを rust_detached_src に残す
    //   (= 呼出側 (アタック解決等) が power/cost を読める)。
    let mut cur = src;
    let mut tok = tag_src(state, me_idx, cur);
    for prim in dos {
        let snap = src_ip(&state.players[me_idx], cur).cloned();
        if !execute_effect(prim, state, me_idx, cur) {
            find_tagged(state, me_idx, tok);
            let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("?");
            // 診断用に spec も載せる (どの target/amount 形が未対応かを bail 集計から直に読む為)
            // ⚠ UTF-8 の途中で切ると panic するので char 境界で truncate する
            let spec: String = prim.to_string().chars().take(110).collect();
            return Err(format!("when-effect primitive 再現不能: {k} {spec}"));
        }
        cur = find_tagged(state, me_idx, tok);
        if cur == Slot::Detached {
            // 発動元がこの primitive で場を離れた → 直前スナップショットを残して以降 Detached。
            if snap.is_some() {
                state.rust_detached_src = snap;
            }
            tok = None;
        } else {
            tok = tag_src(state, me_idx, cur);
        }
    }
    find_tagged(state, me_idx, tok);
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
    victim_cur_cost: i32,
    victim_cur_power: i32,
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
    // ⭐ 素の `target_cost_*` / `target_power_*` = **現在値** /
    //    `target_truly_original_*` = **印刷値** (Python `_replace_ko_match` と対)。
    if let Some(n) = cond.get("target_cost_le").and_then(|v| v.as_i64()) {
        if victim_cur_cost as i64 > n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_cost_ge").and_then(|v| v.as_i64()) {
        if (victim_cur_cost as i64) < n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_truly_original_cost_le").and_then(|v| v.as_i64()) {
        if victim.cost as i64 > n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_truly_original_cost_ge").and_then(|v| v.as_i64()) {
        if (victim.cost as i64) < n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_power_le").and_then(|v| v.as_i64()) {
        if victim_cur_power as i64 > n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_power_ge").and_then(|v| v.as_i64()) {
        if (victim_cur_power as i64) < n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_truly_original_power_le").and_then(|v| v.as_i64()) {
        if victim.power as i64 > n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_truly_original_power_ge").and_then(|v| v.as_i64()) {
        if (victim.power as i64) < n {
            return Some(false);
        }
    }
    if let Some(n) = cond.get("target_truly_original_power_eq").and_then(|v| v.as_i64()) {
        if victim.power as i64 != n {
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
/// ⚠ **同時離脱** (= 1 つの効果で複数キャラが同時に場を離れる) の置換コストは、 公式では
/// holder ごとに **1 回だけ** (cardqa_op_15、 OP15-090 ペローナ: 「手札1枚で2枚とも残すか、
/// 何もせず2枚とも離れるか」)。 Python は _LeaveBatch でこれを実装している。
/// Rust は victim ごとに try_replace_ko を呼ぶ実装のままなので、 **置換 holder が場に居る
/// 盤面では bail** して黙った乖離 (= コストの二重払い) を作らない。

pub fn try_replace_ko(
    state: &mut GameState,
    victim_owner: usize,
    victim_char_idx: usize,
    by_opp_effect: bool,
    leave_kind: &str,
) -> Result<bool, String> {
    let Some(ov) = overlay() else { return Ok(false) };
    let victim_slot = Slot::Char(victim_char_idx);
    let victim_ip = get_ip(&state.players[victim_owner], victim_slot);
    let victim_card = victim_ip.card.clone();
    // 素の 「コスト/パワー N 以下」 は **現在値** (公式 4-9 が定義するのは 「元々の」 の意味だけ)。
    let (victim_cur_cost, victim_cur_power) = (victim_ip.base_cost(), victim_ip.power());
    // holder 走査順: leader → chars → stages (Python と同順、 先頭一致で発動)。
    // ⭐ **同時離脱バッチ中は 「バッチ開始時の盤面」** から holder を決める (順序非依存、
    //   cardqa_op_10 / OP10-032 たしぎ)。 現盤面で探すと 「先に処理した victim が holder 自身
    //   だった」 場合に holder が見つからず、 iteration 順で裁定が変わってしまう。
    let batch_snap: Option<Vec<(Option<u64>, String)>> = state
        .rust_leave_batch_holders
        .as_ref()
        .map(|snap| {
            snap.iter()
                .filter(|(pi, _, _)| *pi == victim_owner)
                .map(|(_, tok, cid)| (*tok, cid.clone()))
                .collect()
        });
    let mut holders: Vec<(Slot, Option<u64>)> = Vec::new();
    if let Some(snap) = batch_snap {
        for (tok, cid) in snap {
            let sl = peek_tagged(state, victim_owner, tok);
            if matches!(sl, Slot::Detached) {
                // holder 自身が このバッチで既に場を離れた。 Python は object 参照で処理を続ける
                // (場外の holder でも置換を宣言できる) が、 Rust は場外 InPlay を持たない → 明示 bail。
                if ov.get(&cid).map_or(false, |effs| {
                    effs.iter().any(|e| {
                        matches!(e.get("when").and_then(|v| v.as_str()),
                                 Some("replace_ko") | Some("replace_leave"))
                    })
                }) {
                    return Err("同時離脱バッチ: 場外 holder の置換 未対応".into());
                }
                continue;
            }
            holders.push((sl, tok));
        }
    } else {
        holders.push((Slot::Leader, None));
        for i in 0..state.players[victim_owner].characters.len() {
            holders.push((Slot::Char(i), None));
        }
        for i in 0..state.players[victim_owner].stages.len() {
            holders.push((Slot::Stage(i), None));
        }
    }
    // extra_cond に回さない target/by_* キー (effects.py:12283 の除外リストと一致)
    // ⚠ ここに載っていない target_* キーは 「extra_cond」 として eval_condition に回るが、
    //   eval_condition は victim を知らないので **常に false** になり 置換が不発になる。
    //   Python 側 (effects.py) の除外リストと 1:1 で揃える。
    //   target_cost_ge / target_truly_original_power_eq は 2026-08-03 に Python へ追加された
    //   (ST30-009 リトルオーズJr. の replace_leave 条件漏れ修正、 クラウド commit 3444423)。
    const EXCL: &[&str] = &[
        "target", "target_attribute", "target_cost_le", "target_cost_ge",
        "target_truly_original_cost_le", "target_truly_original_cost_ge",
        "target_power_le", "target_power_ge",
        "target_truly_original_power_le", "target_truly_original_power_ge",
        "target_truly_original_power_eq",
        "target_feature", "target_feature_contains", "target_color", "target_name_exclude",
        "target_name", "target_rested", "by_opp_effect", "by_battle",
    ];
    let empty = serde_json::Map::new();
    for (hslot, htok) in holders {
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
            match replace_ko_match(cond, hslot == victim_slot, &victim_card,
                                   victim_cur_cost, victim_cur_power, by_opp_effect) {
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
            // ⭐ **同時離脱は 1 事象** = victim に依らない条件 (トラッシュ枚数等) は
            //   **バッチ開始時の状態** で 1 度だけ判定する (cardqa_op_11 / OP11-001 コビー:
            //   先に離れた victim がトラッシュを増やした状態を後の victim に使えない)。
            //   victim 依存の条件 (replace_ko_match の target_*) は victim ごとに判定する。
            let when_key = eff.get("when").and_then(|v| v.as_str()).unwrap_or("").to_string();
            if let Some(t) = htok {
                if state
                    .rust_leave_batch_declined
                    .iter()
                    .any(|(tk, w)| *tk == t && w == &when_key)
                {
                    continue; // このバッチでは 「代替しない」 と決定済
                }
            }
            if !extra.is_empty() {
                match eval_condition(&Value::Object(extra), state, victim_owner, Some(hslot)) {
                    Some(true) => {}
                    Some(false) => {
                        if let Some(t) = htok {
                            state.rust_leave_batch_declined.push((t, when_key.clone()));
                        }
                        continue;
                    }
                    None => return Err("replace_ko extra_cond unknown".into()),
                }
            }
            // 対象一致 = 置換発動 (Phase B)。 cost は once_per_turn (canonical 追跡) + discard_hand_with_filter
            // (payability check) に対応、 他 (pay_don/life 等) は bail。 do は cascade 無し・非victim参照の safe のみ。
            let mut has_once = false;
            let mut discard_filter: Option<Value> = None;
            let mut rest_ls: Option<Value> = None;
            let mut discard_plain: usize = 0;
            let mut rest_cards: Option<Value> = None;
            let mut trash_holder = false;
            let mut ret_don: i32 = 0;
            let mut rand_discard: usize = 0;
            let mut mill_life: usize = 0;
            let mut rest_don_cost: i32 = 0;
            let mut life_to_hand_cost: usize = 0;
            let mut rest_holder_self = false;
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
                                // 「自分の (filter) リーダーかステージ N 枚をレストにできる」
                                // (effects.py:8586/12664、 OP04-082 コロシアム等)。
                                "rest_self_leader_or_stage_filtered" => {
                                    rest_ls = Some(val.clone())
                                }
                                // 「代わりに自分の手札 N 枚を捨てる」 (OP12-053 等)。 filter 無し版。
                                "discard_hand" => {
                                    discard_plain = val.as_i64().unwrap_or(0) as usize
                                }
                                // 「代わりに自分のカード N 枚をレストにできる」 (OP16-033 モーリー)。
                                "rest_self_cards" => rest_cards = Some(val.clone()),
                                // 「代わりにこのキャラをレストにできる」 (OP10-032 たしぎ /
                                // OP12-027 コウシロウ / ST30-011 バギー)。 holder がアクティブ
                                // でなければ置換不発 (cardqa_op_10)。
                                "rest_self" => rest_holder_self = json_truthy(val),
                                // 「代わりにこのキャラをトラッシュに置き」 (OP08-045 サッチ)。
                                // holder が場のキャラなら常に払える (effects.py:12545)。
                                "trash_self" => trash_holder = json_truthy(val),
                                // 「代わりに自分の場のドン N 枚をドンデッキに戻す」 (EB04-031)。
                                "return_self_don_to_deck" => {
                                    ret_don = val.as_i64().unwrap_or(1) as i32
                                }
                                // 「代わりに自分の手札 N 枚をランダムに捨てる」 (OP12-048)。
                                "trash_self_hand_random" => {
                                    rand_discard = val.as_i64().unwrap_or(1) as usize
                                }
                                // 「代わりに自分のライフの上か下から N 枚をトラッシュに置く」
                                // (effects.py:12593/12629、 ST09-010 エース)。 ライフが N 枚未満なら
                                // 置換不能 (= 通常 KO へ)。 効果でのライフ移動なのでトリガーは発動しない。
                                "mill_self_life_to_trash" => {
                                    mill_life = if val.is_object() {
                                        val.get("amount").and_then(|x| x.as_i64()).unwrap_or(1) as usize
                                    } else {
                                        val.as_i64().unwrap_or(1) as usize
                                    }
                                }
                                // 「代わりに自分の(アクティブの)ドン‼ N 枚をレストにできる」
                                // (effects.py:_can_pay_replace_cost/_pay_replace_cost、 P-111 ロビン /
                                // OP10-074 ピーカ)。 アクティブが N 枚未満なら置換不能 (= 通常離脱)。
                                // 「代わりに自分のライフの上から N 枚を手札に加える」
                                // (OP15-098 ルフィ / OP15-105 ボニー)。 ⚠ 公式 cardqa_op_15 の
                                // 「同時離脱は 1 事象 = 支払いも 1 回」 を成立させる為に、 overlay 側で
                                // do ではなく **cost** に置いてある (do は victim ごとに走るので
                                // dedup が効かない)。 ライフが N 枚未満なら置換不能 = 通常離脱へ。
                                "life_to_hand" => {
                                    life_to_hand_cost = val.as_i64().unwrap_or(1) as usize
                                }
                                "rest_self_don" => {
                                    rest_don_cost = if val.is_object() {
                                        val.get("amount").and_then(|x| x.as_i64()).unwrap_or(1) as i32
                                    } else {
                                        val.as_i64().unwrap_or(1) as i32
                                    }
                                }
                                _ => return Err(format!("replace cost 未対応 ({hcid}:{k})")),
                            }
                        }
                    }
                }
            }
            // once_per_turn: このターン既発動 (card-id-keyed) なら skip → 通常 KO へ (effects.py:12500)。
            // ⭐ **同時離脱は 1 事象** = 同じ holder の置換コストは **1 回だけ**
            //   (cardqa_op_15 / OP15-090 ペローナ)。 Python は _batch_already_paid で
            //   can_pay/pay を丸ごと skip するので、 Rust も解析済みコストを 0 にして
            //   payability も支払いも no-op にする (once の再判定/再マークも起きない)。
            let when_str = eff.get("when").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let batch_already_paid = match htok {
                Some(t) => state
                    .rust_leave_batch_paid
                    .iter()
                    .any(|(tk, w)| *tk == t && w == &when_str),
                None => false,
            };
            if batch_already_paid {
                has_once = false;
                discard_filter = None;
                rest_ls = None;
                discard_plain = 0;
                rest_cards = None;
                trash_holder = false;
                ret_don = 0;
                rand_discard = 0;
                mill_life = 0;
                rest_don_cost = 0;
                life_to_hand_cost = 0;
                rest_holder_self = false;
            }
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
            // return_self_don_to_deck の payability: 場のドンが N 枚以上 (effects.py:12564)。
            if ret_don > 0 {
                let pl = &state.players[victim_owner];
                if pl.don_active + pl.don_rested < ret_don {
                    continue;
                }
            }
            // mill_self_life_to_trash の payability: ライフが N 枚以上 (effects.py:12593)。
            if mill_life > 0 && state.players[victim_owner].life.len() < mill_life {
                continue;
            }
            // rest_self_don の payability: アクティブドンが N 枚以上 (effects.py:_can_pay_replace_cost)。
            if rest_don_cost > 0 && state.players[victim_owner].don_active < rest_don_cost {
                continue;
            }
            // life_to_hand の payability: ライフが N 枚以上 かつ 「ライフを手札に加えられない」
            // 禁止中でない (effects.py:_can_pay_replace_cost)。 足りなければ置換不発 → 通常離脱。
            if life_to_hand_cost > 0 {
                let pl = &state.players[victim_owner];
                if pl.life.len() < life_to_hand_cost || pl.prevent_self_life_to_hand_until_turn_end {
                    continue;
                }
            }
            // trash_self_hand_random の payability: 手札が N 枚以上。
            if rand_discard > 0 && state.players[victim_owner].hand.len() < rand_discard {
                continue;
            }
            // trash_self の payability: holder が場のキャラである必要 (effects.py:12550)。
            if trash_holder && !matches!(hslot, Slot::Char(_)) {
                continue;
            }
            // rest_self の payability: holder がアクティブ (レスト禁止中でない) 必要 (cardqa_op_10、
            // OP10-032 たしぎ)。 既レスト/レスト禁止なら置換不発 → 通常離脱。
            if rest_holder_self {
                let hip = get_ip(&state.players[victim_owner], hslot);
                if hip.rested || hip.cannot_be_rested_buff || hip.static_cannot_be_rested {
                    continue;
                }
            }
            // rest_self_cards の payability: 自リーダー+キャラのアクティブが N 枚以上 (effects.py:12584)。
            if let Some(rc) = &rest_cards {
                let n = if rc.is_object() {
                    rc.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize
                } else {
                    rc.as_i64().unwrap_or(1) as usize
                };
                let pl = &state.players[victim_owner];
                let avail = std::iter::once(&pl.leader)
                    .chain(pl.characters.iter())
                    .filter(|ip| !ip.rested)
                    .count();
                if avail < n {
                    continue;
                }
            }
            // discard_hand (filter 無し) の payability: 手札が足りなければ置換不発 → 通常 KO。
            if discard_plain > 0 && state.players[victim_owner].hand.len() < discard_plain {
                continue;
            }
            // rest_self_leader_or_stage_filtered の payability: leader + stages のアクティブ かつ
            // filter 一致が N 枚以上 (effects.py:8593)。 足りなければ置換不発 → 通常 KO。
            if let Some(rl) = &rest_ls {
                let (filt, n) = if rl.is_object() {
                    (rl.get("filter").cloned(), rl.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize)
                } else {
                    (None, rl.as_i64().unwrap_or(1) as usize)
                };
                let pl = &state.players[victim_owner];
                let avail = std::iter::once(&pl.leader)
                    .chain(pl.stages.iter())
                    .filter(|ip| !ip.rested && matches_filter_ip(&ip, filt.as_ref()))
                    .count();
                if avail < n {
                    continue;
                }
            }
            let dos: Vec<Value> =
                eff.get("do").and_then(|v| v.as_array()).cloned().unwrap_or_default();
            // ⭐ `conditional` は 「コロン後の条件は効果のみを gate」 の是正 (2026-08-05) で
            //   replace の do にも現れるようになった。 中身は普通の primitive 列なので、
            //   **入れ子を平坦化してから** 同じ allow-list で検査する (中に危険な prim が
            //   隠れていたら従来どおり bail する = 安全性は変わらない)。
            let mut flat: Vec<&Value> = Vec::new();
            fn _flatten<'a>(arr: &'a [Value], out: &mut Vec<&'a Value>) {
                for p in arr {
                    if let Some(c) = p.get("conditional") {
                        if let Some(inner) = c.get("do").and_then(|x| x.as_array()) {
                            _flatten(inner, out);
                            continue;
                        }
                    }
                    out.push(p);
                }
            }
            _flatten(&dos, &mut flat);
            for prim in flat {
                let pk = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("");
                // rest_self_cards / return_self_don_to_deck = 非re-leave・非victim参照の safe do (holder=src)。
                // return_to_deck_bottom (OP15-052 = one_self_character_any を deck へ) = 自 char の return =
                // by_self_effect なので replace(全て by_opp_effect 要求)を再誘発しない = 無限ループ無し。
                // ⚠ 但し返した char の on_self_chara_leave_by_self_effect cascade は execute_effect が自前
                // 発火しないので、 holder owner 場に該当 when あれば bail (再現不能)。
                // 追加 (2026-08-01): player-level で victim を参照せず、 場からの離脱も起こさない
                // primitive は replace の do として安全 (= replace を再誘発しない = 無限ループ無し)。
                //   draw / life_to_hand / mill_self_life_to_trash / trash_to_deck / trash_self_hand_random
                //   / power_pump (holder=src への buff) / flip_life_face_up_effect
                // ⚠ rest / return_self_to_* は「離脱・レスト」を起こし replace を再誘発しうるので除外のまま。
                // 追加 (2026-08-02): rest = prim 側で on_self_rested cascade を自前発火/bail する。
                // ko_self = holder 自身の KO (prim 側で on_ko/on_self_chara_ko を発火、 replace は
                // 再誘発しない = victim は既に場外)。 rest_self_don = コストエリア操作のみ。
                if !matches!(pk, "rest_self_cards" | "return_self_don_to_deck" | "return_to_deck_bottom"
                    | "draw" | "life_to_hand" | "mill_self_life_to_trash" | "trash_to_deck"
                    | "trash_self_hand_random" | "power_pump" | "flip_life_face_up_effect"
                    | "rest" | "ko_self" | "rest_self_don" | "return_self_to_trash"
                    // return_self_to_hand = holder 自身を手札へ (prim 側は leave trigger を発火しない
                    // = Python も同様) → replace を再誘発しない。
                    | "return_self_to_hand") {
                    return Err(format!("replace do 未対応 ({pk})"));
                }
                if pk == "return_to_deck_bottom"
                    && me_board_has_when(state, victim_owner, "on_self_chara_leave_by_self_effect")
                {
                    return Err("replace do return_to_deck_bottom cascade 未対応".into());
                }
            }
            // このバッチでは この holder×when は支払い済 (以降の victim には無償で適用)。
            if let Some(t) = htok {
                if !batch_already_paid {
                    state.rust_leave_batch_paid.push((t, when_str.clone()));
                }
            }
            // return_self_don_to_deck 支払い (effects.py:12572)。 active 優先。
            if ret_don > 0 {
                let pl = &mut state.players[victim_owner];
                let taken = ret_don.min(pl.don_active);
                pl.don_active -= taken;
                pl.don_remaining_in_deck += taken;
                let more = (ret_don - taken).min(pl.don_rested);
                pl.don_rested -= more;
                pl.don_remaining_in_deck += more;
            }
            // mill_self_life_to_trash 支払い (effects.py:12629)。 ライフ上から N 枚をトラッシュへ。
            // ⚠ 効果でのライフ移動なので【トリガー】は発動しない (公式 10-1-5)。
            // life_to_hand 支払い (effects.py:_pay_replace_cost)。 ライフ上から N 枚を手札へ。
            // ⚠ do 版 primitive と同じく 「ライフが手札に加わった」 トリガーを発火する。
            if life_to_hand_cost > 0 {
                let mut moved = 0;
                for _ in 0..life_to_hand_cost {
                    let pl = &mut state.players[victim_owner];
                    if pl.life.is_empty() {
                        break;
                    }
                    let c = pl.life.remove(0);
                    pl.hand.push(c);
                    moved += 1;
                }
                if moved > 0 {
                    fire_self_life_to_hand(state, victim_owner)?;
                }
            }
            for _ in 0..mill_life {
                let pl = &mut state.players[victim_owner];
                if pl.life.is_empty() {
                    break;
                }
                let c = pl.life.remove(0);
                pl.trash.push(c);
            }
            // rest_self_don 支払い (effects.py:_pay_replace_cost)。 アクティブドン N 枚をレストへ。
            if rest_don_cost > 0 {
                let pl = &mut state.players[victim_owner];
                let actual = rest_don_cost.min(pl.don_active);
                pl.don_active -= actual;
                pl.don_rested += actual;
            }
            // trash_self_hand_random 支払い (effects.py:12662)。 ⚠ 名前に反して AI は
            // worst_hand_idx (= 最悪札) を捨てる (rng は消費しない)。
            let mut rand_actual = 0i32;
            for _ in 0..rand_discard {
                let pl = &mut state.players[victim_owner];
                let Some(i) = worst_hand_idx(&pl.hand, &pl.known_hand_card_ids) else { break };
                let c = pl.hand.remove(i);
                pl.trash.push(c);
                rand_actual += 1;
            }
            // 置換コストの手札捨ても 「効果で手札が捨てられた」 (cardqa_op_12、 OP12-053 ボルサリーノ
            // → リーダー OP12-040 クザン の on_self_hand_discarded 発火 + flag)。 発動元 = holder。
            // cascade 再現不能なら Err bail (Python は必ず解決するので bail は「未追従」= 安全)。
            if rand_actual > 0 {
                state.players[victim_owner].hand_discarded_by_effect_this_turn = true;
                fire_hand_discarded_n(state, victim_owner, hslot, rand_actual)?;
            }
            // trash_self 支払い: holder を場からトラッシュへ (effects.py:12622)。 付与ドンはレストへ。
            // ⚠ victim == holder のケース (if.target=self) では victim が場から消えるので、
            //    呼出側は「置換発動 = 通常 KO しない」= Ok(true) を返す前提。
            if trash_holder {
                if let Slot::Char(hi) = hslot {
                    if hi < state.players[victim_owner].characters.len() {
                        let ip = state.players[victim_owner].characters.remove(hi);
                        let don = ip.attached_dons;
                        state.players[victim_owner].trash.push(ip.card);
                        state.players[victim_owner].don_rested += don;
                    }
                }
            }
            // rest_self は払える判定専用 (Python _pay_replace_cost は no-op)。 実際のレストは
            // do の `rest: self` (execute_effect) が行い、 「レストになった時」 トリガーを発火する。
            let _ = rest_holder_self;
            // rest_self_cards 支払い (effects.py:12686、 AI は power 昇順で N 枚レスト)。
            if let Some(rc) = &rest_cards {
                let n = if rc.is_object() {
                    rc.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize
                } else {
                    rc.as_i64().unwrap_or(1) as usize
                };
                let pl = &state.players[victim_owner];
                // Python は [leader, *characters] を power 昇順 (stable) で並べる。 -1 = leader。
                let mut order: Vec<i32> = vec![];
                if !pl.leader.rested {
                    order.push(-1);
                }
                for i in 0..pl.characters.len() {
                    if !pl.characters[i].rested {
                        order.push(i as i32);
                    }
                }
                order.sort_by_key(|&i| {
                    if i < 0 { pl.leader.power() } else { pl.characters[i as usize].power() }
                });
                for i in order.into_iter().take(n) {
                    let pl = &mut state.players[victim_owner];
                    if i < 0 {
                        pl.leader.rested = true;
                    } else {
                        pl.characters[i as usize].rested = true;
                    }
                }
            }
            // discard_hand 支払い (AI は worst_hand_idx から)。
            // ⚠ Python (effects.py:_pay_replace_cost) は毎回 hand を (power, cost) 昇順で **in-place
            //    ソート** して先頭を捨てる = 手札の並び順そのものが変わる (digest に効く)。 同じ手順を再現。
            //    捨て後は on_self_hand_discarded cascade + flag を発火 (cardqa_op_12 の一般則、
            //    cascade 再現不能なら Err bail)。
            let mut plain_actual = 0i32;
            for _ in 0..discard_plain {
                let pl = &mut state.players[victim_owner];
                if pl.hand.is_empty() {
                    break;
                }
                pl.hand.sort_by(|a, b| (a.power, a.cost).cmp(&(b.power, b.cost)));
                let c = pl.hand.remove(0);
                pl.trash.push(c);
                plain_actual += 1;
            }
            if plain_actual > 0 {
                state.players[victim_owner].hand_discarded_by_effect_this_turn = true;
                fire_hand_discarded_n(state, victim_owner, hslot, plain_actual)?;
            }
            // rest_self_leader_or_stage_filtered 支払い (effects.py:12664)。 ⚠ ステージ優先で rest
            // (リーダー温存)、 1 枚のみ (Python は break)。
            if let Some(rl) = &rest_ls {
                let filt = if rl.is_object() { rl.get("filter").cloned() } else { None };
                let pl = &mut state.players[victim_owner];
                let mut done = false;
                for ip in pl.stages.iter_mut() {
                    if !ip.rested && matches_filter_ip(&ip, filt.as_ref()) {
                        ip.rested = true;
                        done = true;
                        break;
                    }
                }
                if !done && !pl.leader.rested && matches_filter_ip(&pl.leader, filt.as_ref()) {
                    pl.leader.rested = true;
                }
            }
            // discard_hand_with_filter cost 支払い (Python _pay_replace_cost、 do 前)。 先頭 cnt 個の matching を
            //   trash へ。 捨て後は on_self_hand_discarded cascade + flag を発火 (cardqa_op_12 の一般則。
            //   選び方=filter でも 「手札が捨てられた」 事実は同じ。 cascade 再現不能なら Err bail)。
            if let Some((filt, cnt)) = discard_cost {
                let pl = &mut state.players[victim_owner];
                let hand = std::mem::take(&mut pl.hand);
                let mut discarded = 0usize;
                for c in hand {
                    if discarded < cnt && matches_filter(&c, Some(&filt)) {
                        pl.trash.push(c);
                        discarded += 1;
                    } else {
                        pl.hand.push(c);
                    }
                }
                if discarded > 0 {
                    state.players[victim_owner].hand_discarded_by_effect_this_turn = true;
                    fire_hand_discarded_n(state, victim_owner, hslot, discarded as i32)?;
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
/// KO する InPlay の 「効果無効」 状態を transient に記録する (除去の **直前** に呼ぶ)。
/// 公式 Q&A: 無効化されたキャラの【KO時】は発動しない (effects.py:_ip_effect_negated と同じ判定)。
fn note_ko_victim_negated(state: &mut GameState, pi: usize, idx: usize) {
    let neg = state.players[pi]
        .characters
        .get(idx)
        .map(|ip| {
            ip.granted_keywords.contains("効果無効")
                || ip.static_granted_keywords.contains("効果無効")
                || ip.effect_disabled_through_opp_turn
        })
        .unwrap_or(false);
    state.ko_victim_effect_negated = neg;
}

/// rules.rs (バトル KO) から呼ぶための公開ラッパ。
pub fn note_ko_victim_negated_pub(state: &mut GameState, pi: usize, idx: usize) {
    note_ko_victim_negated(state, pi, idx);
}

/// 除去済みの InPlay から直接 「効果無効」 を記録する (index が使えない経路用)。
fn note_ko_victim_negated_ip(state: &mut GameState, ip: &InPlay) {
    state.ko_victim_effect_negated = ip.granted_keywords.contains("効果無効")
        || ip.static_granted_keywords.contains("効果無効")
        || ip.effect_disabled_through_opp_turn;
}

pub fn fire_on_ko(
    state: &mut GameState,
    owner_idx: usize,
    victim_cid: &str,
    by_opp_effect: bool,
) -> Result<(), String> {
    if !note_ko_and_should_fire(state, owner_idx, victim_cid, by_opp_effect) {
        return Ok(());
    }
    run_on_ko_effects(state, owner_idx, victim_cid)
}

/// `fire_on_ko` の **前半** (= KO された瞬間に必ず起きる記録) だけを行い、【KO時】の do を
/// 実行すべきかを返す。 起動メインの発動コストによる自KO (公式 8-4-1-3〜5 / cardqa_op_14) は
/// **記録は即時・do は本体解決後** なので、 呼出側がこの 2 段を分けて使う。
/// Python も trigger_on_ko で 「被KO数の加算 → 効果無効 gate → enqueue」 の順に分かれている。
pub(crate) fn note_ko_and_should_fire(
    state: &mut GameState,
    owner_idx: usize,
    victim_cid: &str,
    by_opp_effect: bool,
) -> bool {
    // 条件 by_opp_effect / by_battle 用 (Python は trigger_on_ko の引数を state に伝搬)。
    state.last_ko_by_opp_effect = by_opp_effect;
    // ⚠ このターンの被 KO 数は **全 KO 経路の共通フック** で数える (Python trigger_on_ko:13022 と
    //   同じ位置 = 効果無効 gate より前、 overlay 有無より前 = バニラキャラの KO も数える)。
    //   以前は呼出側 10 箇所が個別に加算しており、 ko_self (OP16-014 マルコの replace_leave) など
    //   加算漏れの経路があった (2026-08-04 の置換差分パスで発覚)。 ここに集約する。
    state.players[owner_idx].chara_ko_taken_this_turn += 1;
    // 公式 Q&A (cardqa_op_09/op_10): 効果を無効にされたキャラの【KO時】は発動しない。
    // 記録は note_ko_victim_negated が除去直前に行う。 読んだら必ず clear (次の KO に漏らさない)。
    let victim_negated = std::mem::take(&mut state.ko_victim_effect_negated);
    if victim_negated {
        return false;
    }
    let Some(ov) = overlay() else { return false };
    let Some(effs) = ov.get(victim_cid) else { return false };
    if !effs.iter().any(|e| e.get("when").and_then(|v| v.as_str()) == Some("on_ko")) {
        return false;
    }
    crate::selfplay::note_fired(victim_cid);
    true
}

/// `fire_on_ko` の **後半** (=【KO時】 do の実行)。 `note_ko_and_should_fire` が true を返した後に呼ぶ。
pub(crate) fn run_on_ko_effects(
    state: &mut GameState,
    owner_idx: usize,
    victim_cid: &str,
) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let Some(effs) = ov.get(victim_cid) else { return Ok(()) };
    // Python (trigger_on_ko) は on_ko を **enqueue** して _maybe_resolve を呼ぶ = do-list は
    // resolve_triggers の中 (resolving=true) で走る。 その間に do の中で登場したキャラの on_play
    // (play_from_hand_or_trash 等) は enqueue されるだけで後回しになる (= 手札走査ループの途中で
    // 割り込まない)。 Rust は on_ko を直接実行するだけで resolving を立てていなかったため、 nested
    // な execute_on_play が即座に drain (inline 実行) してしまい、 play_from_hand_or_trash の
    // index-based hand ループが「実行中に書き換わった hand」を読んで手札を 1 枚喪失させていた
    // (OP14-091 Mr.2・ボン・クレー の on_ko → Mr.5(ジェム) 登場 → draw2+discard1 が
    //  play_from_hand_or_trash のループ内で inline 発火、 2026-08-07 広域スキャンで発覚)。
    // fire_life_trigger と同じ resolving guard を張る。
    let prev_resolving = state.rust_resolving;
    state.rust_resolving = true;
    let r = (|| -> Result<(), String> {
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
    })();
    state.rust_resolving = prev_resolving;
    if r.is_ok() && !prev_resolving {
        maybe_resolve(state)?;
    }
    r
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
    crate::selfplay::note_fired(card_id);
    // ⚠ 2 系トリガー (attacker の【相手がイベント/トリガーを発動した時】、 defender の
    //   【自分のトリガーが発動した時】) は Python では trigger 本体の後に enqueue され FIFO で drain
    //   される (effects.py:trigger_lifecard_trigger)。 → 本体発火後に同じ順で inline 発火する
    //   (以前はここで一律 bail していた)。
    // play_self が発動元カードを特定できるよう source cid を立てる (effects.py:297)。 action 境界では
    // 常に None なので Ok 直前で戻す (Err 時は apply_action が state 破棄で無害)。
    state.current_source_card_id = Some(card_id.to_string());
    // 【トリガー】は InPlay を持たないので、 発動元の特徴も transient に載せる
    // (actor_source_feature_contains 用、 cardqa_op_12)。
    state.current_source_card_features = state.players[defender_idx]
        .life
        .iter()
        .chain(state.players[defender_idx].trash.iter())
        .find(|c| c.card_id == card_id)
        .map(|c| c.features.clone());
    // Python の trigger_lifecard_trigger は event を enqueue して _maybe_resolve を呼ぶ = トリガーの
    // do-list は **resolve_triggers の中** で走る。 その間 resolving=true なので、 do の中で登場した
    // キャラの on_play は enqueue されるだけで後回しになる。 Rust も同じ文脈を作る。
    let prev_resolving = state.rust_resolving;
    state.rust_resolving = true;
    // ⚠ on_self_trigger_fired 除外の snapshot (effects.py:trigger_lifecard_trigger の
    //   pre_trigger_field_iids と同じ役目)。 【トリガー】解決 (play_self 等) の **前** に場に
    //   居たカードだけを対象にする — この trigger 自身で登場したカードは、 その同じ発火を
    //   自身の on_self_trigger_fired で拾わない (公式: OP13-106 コニー cardqa、 「いいえ」)。
    let pre_trigger_toks = snapshot_field_toks(state, defender_idx);
    let mut kept_in_hand = false;
    for (eff_idx, eff) in effs.iter().enumerate() {
        if eff.get("when").and_then(|v| v.as_str()) != Some("trigger") {
            continue;
        }
        // 【ターン1回】: ライフトリガーは source_iid が無いので Python の自動キーは
        // `{card_id}:trigger:{idx}` (card_id ベース = instance 非依存) になり、
        // once_shared_used に canonical mirror されている (effects.py:1009)。 それを見る。
        let once_opt = eff
            .get("once_per_turn")
            .or_else(|| eff.get("cost").and_then(|c| c.get("once_per_turn")));
        let once_key: Option<String> = match once_opt {
            Some(o) if o.as_bool() == Some(true) => Some(format!("{card_id}:trigger:{eff_idx}")),
            Some(o) => o.as_str().map(|k| format!("key:{k}")),
            None => None,
        };
        if let Some(k) = &once_key {
            if state.players[defender_idx].once_shared_used.contains(k) {
                continue; // ターン既発動
            }
        }
        // Python は _check_and_set_once_per_turn を cost 判定より **前** に呼ぶ (= 判定時点で
        // 使用済みフラグが立つ) ので、 ここで mark してから cost に進む。
        if let Some(k) = &once_key {
            let used = &mut state.players[defender_idx].once_shared_used;
            if !used.contains(k) {
                used.push(k.clone());
                used.sort();
            }
        }
        // cost 持ちトリガー (overlay 実績: pay_don 16 / discard_hand 1 / once_per_turn 1)。
        // on_ko と同じく try_pay_counter_cost に委譲する (source-gone = Slot::Detached)。
        // once_per_turn は iid-keyed で Rust から追跡できないので従来通り bail。
        if let Some(cost) = eff.get("cost") {
            if !cost_is_empty(cost) {
                match try_pay_counter_cost(state, defender_idx, Slot::Detached, cost)? {
                    true => {}
                    false => continue, // 支払い不能 → この効果は発動しない
                }
            }
        }
        if false {
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
                let inner = LAST_PRIM_ERR.lock().map(|m| m.clone()).unwrap_or_default();
                return Err(format!("life trigger primitive 再現不能: {} [{}]",
                    prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("?"), inner));
            }
        }
    }
    state.current_source_card_id = None; // action 境界では None に戻す
    // ⭐ Python は 本体を enqueue → `_maybe_resolve` で **解決し切って** から reactive を積む
    //   (effects.py:trigger_lifecard_trigger の 「トリガー効果を先に drain してから reactive を
    //   積む」)。 Rust は本体を inline 実行するので、 ここで明示的に drain しないと 本体の登場が
    //   誘発した on_play が reactive より **後** に走る。
    drain_if_outer(state, prev_resolving)?;
    // Python の enqueue 順: ① trigger 本体 → ② attacker の opp_event_or_trigger_fired
    //   → ③ defender の on_self_trigger_fired。 Python は 1 つ積むごとに drain するので
    //   Rust も 各発火の後に drain_if_outer を挟む。
    fire_field_when(state, attacker_idx, "opp_event_or_trigger_fired")?;
    drain_if_outer(state, prev_resolving)?;
    // ⭐ 「**相手が【トリガー】を発動した時**」 (= トリガー限定、 イベントでは発動しない)。
    //   公式 (cardqa_op_05 / OP05-109 パガヤ): 「【トリガー】が発動した時」 に 「自分の/相手の」 の
    //   修飾が無い効果は **両陣営** の発動で反応する。 opp_event_or_trigger_fired はイベントでも
    //   発動してしまうので別 when (opp_event_played が 「イベント限定」 を持つのと対称)。
    fire_field_when(state, attacker_idx, "opp_trigger_fired")?;
    drain_if_outer(state, prev_resolving)?;
    fire_field_when_with_toks(state, defender_idx, "on_self_trigger_fired", pre_trigger_toks)?;
    drain_if_outer(state, prev_resolving)?;
    // resolving を戻し、 外側に居なければ溜まった on_play 等をここで drain する。
    state.rust_resolving = prev_resolving;
    if !prev_resolving {
        maybe_resolve(state)?;
    }
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
                // trash_self / self_ko = 発動元自身を場から除去 (effects.py:934)。 self_ko は KO 扱いで
                // 【KO時】が発火するので、 該当 when を持つ盤面は下の payability で bail する。
                | "trash_self" | "self_ko" | "return_self_to_hand"
                // return_self_don_to_deck: 場のドン N 枚をドンデッキへ (effects.py:889)。
                // ⭐ rested を優先して返す (active DON を温存 = 常に tempo 同等以上)。
                | "return_self_don_to_deck"
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
    let rdon = gi("return_self_don_to_deck");
    let rest_self = obj.get("rest_self").map_or(false, json_truthy);
    let flip_down = obj.get("flip_life_face_down").map_or(false, json_truthy);
    let flip_up = obj.get("flip_life_face_up").map_or(false, json_truthy);
    let trash_self = obj.get("trash_self").map_or(false, json_truthy);
    let self_ko = obj.get("self_ko").map_or(false, json_truthy);
    let ret_self_hand = obj.get("return_self_to_hand").map_or(false, json_truthy);
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
        // effects.py:570 — trash_self / self_ko / return_self_to_hand は source 不在なら払えない
        if (trash_self || self_ko || ret_self_hand) && src_ip(me, self_src).is_none() {
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
            if fire_hand_discarded_n(state, me_idx, self_src, actual).is_err() {
                return Err("counter cost discard cascade 未対応".into());
            }
        }
    }
    // --- pay (Python _pay_counter_cost の順: pay_don→rest_don→rest_self→life→trash_to_deck→flip) ---
    if pay_don > 0 && !pay_don_field(state, me_idx, pay_don) {
        return Err("pay_don 支払い不能".into());
    }
    // pay_don_field が last_returned_don_count を set 済 → on_self_don_returned_to_deck cascade。
    // Python は enqueue → _maybe_resolve なので **効果解決の内側なら do の後** に回る。
    // return_self_don_to_deck 側と同じくキューに載せて順序を合わせる (2026-08-04)。
    if pay_don > 0 && me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
        enqueue_field_when(state, me_idx, "on_self_don_returned_to_deck");
        maybe_resolve(state)?;
    }
    if rest_don > 0 {
        let me = &mut state.players[me_idx];
        let a = rest_don.min(me.don_active);
        me.don_active -= a;
        me.don_rested += a;
    }
    // return_self_don_to_deck: 場のドン N 枚をドンデッキへ (effects.py:889)。 rested 優先で返す。
    if rdon > 0 {
        let moved = {
            let me = &mut state.players[me_idx];
            let from_rested = me.don_rested.min(rdon);
            me.don_rested -= from_rested;
            me.don_remaining_in_deck += from_rested;
            let from_active = (rdon - from_rested).min(me.don_active);
            me.don_active -= from_active;
            me.don_remaining_in_deck += from_active;
            from_rested + from_active
        };
        if moved > 0 {
            state.last_returned_don_count = moved;
            // Python (trigger_on_self_don_returned_to_deck) は enqueue → _maybe_resolve。
            // 効果解決の内側なら _maybe_resolve は早期 return するので **do の後** に回る。
            // inline 発火すると順序が逆になる (OP06-074 ゼファーのコストが OP06-076
            // 人斬り鎌ぞうの誘発を呼び、 2 枚 KO の並びが入れ替わる、 2026-08-04 発覚)。
            if me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
                enqueue_field_when(state, me_idx, "on_self_don_returned_to_deck");
                maybe_resolve(state)?;
            }
        }
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
                if fire_hand_discarded_n(state, me_idx, self_src, n_disc as i32).is_err() {
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
    // trash_self / self_ko / return_self_to_hand: source 自身を場から除去 (effects.py:934)。
    // ⚠ self_ko は KO 扱いで【KO時】/on_self_chara_ko、 trash_self は on_self_chara_leave_by_self_effect
    //   が発火する。 該当 when を持つ盤面は cascade 再現不能なので bail (黙って発火漏れにしない)。
    if trash_self || self_ko || ret_self_hand {
        if self_ko
            && (crate::effects::me_board_has_when(state, me_idx, "on_self_chara_ko")
                || crate::effects::me_board_has_when(state, 1 - me_idx, "on_opp_chara_ko"))
        {
            return Err("counter cost self_ko cascade 未対応".into());
        }
        if ret_self_hand
            && crate::effects::me_board_has_when(state, me_idx, "on_self_chara_leave_by_self_effect")
        {
            return Err("counter cost return_self_to_hand cascade 未対応".into());
        }
        let me = &mut state.players[me_idx];
        let removed = match self_src {
            Slot::Char(i) if i < me.characters.len() => Some(me.characters.remove(i)),
            Slot::Stage(i) if i < me.stages.len() => Some(me.stages.remove(i)),
            _ => None,
        };
        if let Some(r) = removed {
            // 【KO時】 gate 用に 「効果無効」 を move 前に記録 (trash 送りのときだけ意味を持つ)。
            let neg = r.granted_keywords.contains("効果無効")
                || r.static_granted_keywords.contains("効果無効")
                || r.effect_disabled_through_opp_turn;
            state.ko_victim_effect_negated = neg;
            let don = r.attached_dons;
            if ret_self_hand {
                me.hand.push(r.card);
            } else {
                me.trash.push(r.card);
            }
            me.don_rested += don; // 6-5-5-4: 付与ドンはレストで戻る
            // self_ko は victim 自身の【KO時】も発火する (source-gone)
            if self_ko {
                let cid = state.players[me_idx].trash.last().map(|c| c.card_id.clone());
                if let Some(cid) = cid {
                    if card_has_when(&cid, "on_ko") {
                        fire_on_ko(state, me_idx, &cid, false)?;
                    }
                }
            } else if !ret_self_hand {
                // 「トラッシュに置く」 コスト = 公開領域 → 本人も含めて leave-by-self を発火
                // (effects.py:_pay_counter_cost の else 分岐と同順)。
                let card = state.players[me_idx].trash.last().cloned();
                if let Some(card) = card {
                    note_public_departure(state, me_idx, &card);
                }
                fire_leave_by_self_effect(state, me_idx)?;
            }
        }
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
    // 公式 (3 弾で繰り返し): 「レストにできない」 は **レストにすることが必要な行動**
    //   (アタック /【ブロッカー】発動 / レストを要するコストの支払い) をできなくする。
    //   レスト済 だけでなく 「レストにできない」 状態でも払えない (2026-08-04 是正)。
    if obj.get("rest_self").map_or(false, json_truthy) {
        let ip = get_ip(me, self_src);
        if ip.rested || ip.cannot_be_rested_buff || ip.static_cannot_be_rested {
            return false;
        }
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
/// `fire_field_when` の対象走査集合を **今の盤面** から作る (leader + characters + stages に
/// 一意トークンを打つ)。 呼出タイミングを分離できるよう `fire_field_when_with_toks` と分けてある
/// (= 「do 実行前の盤面」 を snapshot してから do を実行し、 その後で snapshot 済トークンだけを
/// 対象に発火したいケース、 例: `fire_life_trigger` の on_self_trigger_fired 除外、 のため)。
pub(crate) fn snapshot_field_toks(state: &mut GameState, owner_idx: usize) -> Vec<(Option<u64>, String)> {
    let n_char = state.players[owner_idx].characters.len();
    let n_stage = state.players[owner_idx].stages.len();
    let mut slots: Vec<Slot> = vec![Slot::Leader];
    slots.extend((0..n_char).map(Slot::Char));
    slots.extend((0..n_stage).map(Slot::Stage));
    slots
        .iter()
        .map(|&sl| {
            let cid = get_ip(&state.players[owner_idx], sl).card.card_id.clone();
            (tag_src(state, owner_idx, sl), cid)
        })
        .collect()
}

pub fn fire_field_when(state: &mut GameState, owner_idx: usize, when: &str) -> Result<(), String> {
    if overlay().is_none() {
        return Ok(());
    }
    // ⚠ Python は走査対象を loop 開始前にリスト化する (= 途中で盤面が動いても元の集合を回す)。
    //   Rust は位置 index なので、 効果/コストが盤面を動かすと後続 slot が別カードを指す or 範囲外
    //   (= index out of bounds で panic していた、 EB01-021 の end_of_turn cost で検出)。
    //   一意トークンで各 source を追跡し、 場を離れたものは明示 bail する。
    let toks = snapshot_field_toks(state, owner_idx);
    fire_field_when_with_toks(state, owner_idx, when, toks)
}

/// `fire_field_when` の本体だが、 走査対象トークンを呼出側から受け取る版。
/// `snapshot_field_toks` を **いつ** 呼ぶかを呼出側が選べる (= "before" some other do-list を
/// 実行して盤面が変わった後でも、 変化前の集合だけを対象にできる)。
/// Python `_maybe_resolve` 相当 = 「外側が resolving でなければ その場でキューを drain」。
///
/// ⚠ Rust の when 発火は `rust_resolving = true` の下で do を **inline** 実行するので、
/// do の中で起きた登場 (`execute_on_play` の enqueue) は 呼出側が最後にまとめて drain するまで
/// 積まれたままになる。 Python は 本体を enqueue → `_maybe_resolve` で **その場で** 解決し切って
/// から次の reactive を積むので、 間に挟まる drain を省くと **本体の登場効果が reactive より
/// 後に走る** (2026-08-10、 OP05-106 シュラ【トリガー】のデッキ操作が OP05-109 パガヤ の
/// ドローより後になり 引くカードが変わった = MISMATCH)。
pub(crate) fn drain_if_outer(state: &mut GameState, prev_resolving: bool) -> Result<(), String> {
    if prev_resolving {
        return Ok(()); // 外側が解決中 = Python の _maybe_resolve は no-op
    }
    state.rust_resolving = false;
    let r = maybe_resolve(state);
    state.rust_resolving = true;
    r
}

pub(crate) fn fire_field_when_with_toks(
    state: &mut GameState,
    owner_idx: usize,
    when: &str,
    toks: Vec<(Option<u64>, String)>,
) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    // ⭐ 「離脱したカード自身」 も反応する例外 (cardqa_op_08 / OP08-046 シャクヤク)。
    //   公式: 「このキャラがトラッシュに置かれた時か、 ライフに表向きで置かれた時、 この
    //   【自分のターン中】効果を発動できます」 = 場を離れた **本人** も発動できる (行き先が
    //   公開領域の時のみ)。 Python は _note_public_departure の台帳で本人を追加 enqueue する。
    //   Rust は台帳を持たないので、 **その when を持つカードが自分のトラッシュ/表向きライフに
    //   存在する局面では明示 bail** する (= 黙って発火漏れを作らない。 過剰 bail は許容)。
    //   本人参加しうるのは **OP08-046 の 1 枚だけ** なので影響範囲は極小
    //   (OP07-038 は LEADER = 場を離れない、 OP08-056 は STAGE で下の CHARACTER 判定が弾く)。
    for (tok, cid) in toks {
        fire_field_when_one(state, owner_idx, when, tok, &cid)?;
    }
    Ok(())
}

/// `fire_field_when_with_toks` の **1 カード分**。 キューから 1 件ずつ取り出して発火する経路
/// (= Python `_execute_event` がイベント 1 件 = カード 1 枚を処理するのと同じ粒度) で使う。
pub(crate) fn fire_field_when_one(
    state: &mut GameState,
    owner_idx: usize,
    when: &str,
    tok: Option<u64>,
    cid: &str,
) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    {
        // 先行 source の効果/コストがこの source を場から除いた場合、 Python は場外オブジェクトの
        // まま処理を続ける (bundle は card_id 引き)。 Rust は Slot::Detached で続行する
        // (= "self" 対象は 0 件、 場外への変更は digest に現れないので等価)。
        let slot = find_tagged(state, owner_idx, tok);
        let Some(effs) = ov.get(cid) else { return Ok(()) };
        for (idx, eff) in effs.iter().enumerate() {
            if eff.get("when").and_then(|v| v.as_str()) != Some(when) {
                continue;
            }
            // 発動元が 「効果無効」 なら発動しない (effects.py:_execute_event の gate)。
            // src_effect_negated は list 済 when (end_of_turn/opp_end_of_turn 等) のみ true を返すので、
            // fire_field_when が扱う他の when (on_self_chara_ko 等) は素通り = Python と一致。
            if src_effect_negated(state, owner_idx, slot, when) {
                continue;
            }
            crate::selfplay::note_fired(cid); // ⚠ cid は &str (1 カード分に分割した際の型)
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
            // 実 cost (once_per_turn 以外) の扱い。 end_of_turn / opp_end_of_turn は Python が
            // AI heuristic で 払う/払わない を決める専用経路 (effects.py:11572) を持つのでそれを再現。
            // それ以外の field-when は real cost 未対応 → bail。
            let mut eot_paid = false;
            if let Some(cost) = eff.get("cost") {
                let has_real = cost.as_object().map_or(!cost_is_empty(cost), |o| o.keys().any(|k| k != "once_per_turn"));
                if has_real {
                    if when != "end_of_turn" && when != "opp_end_of_turn" {
                        return Err(format!("{when} cost 未対応"));
                    }
                    if !end_of_turn_cost_is_real(cost) {
                        return Err(format!("{when} cost 未対応 (非 EOT cost 種別)"));
                    }
                    // cost-bearing optional: 条件 → 支払可否 → AI heuristic の順 (Python 同順)。
                    match eval_effect_conditions(eff, state, owner_idx, Some(slot)) {
                        Some(true) => {}
                        Some(false) => continue,
                        None => return Err(format!("{when} 条件 unknown")),
                    }
                    if !can_pay_end_of_turn_cost(state, owner_idx, slot, cost) {
                        continue;
                    }
                    if !ai_should_fire_end_of_turn_cost(state, owner_idx, slot, eff) {
                        continue;
                    }
                    if pay_end_of_turn_cost(state, owner_idx, slot, cost, idx, when).is_err() {
                        return Err(format!("{when} cost 支払い再現不能"));
                    }
                    eot_paid = true;
                }
            }
            let _ = eot_paid;
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

/// ライフ 0 トリガー (effects.py:trigger_on_life_zero、 OP05-098 紫エネル「デッキ上1枚をライフへ」)。
/// source = 自リーダー (永続 InPlay) なので once_per_turn は event_once_used の canonical mirror で追跡できる。
/// 呼出側は発火後に life が回復したか再判定する (回復していれば敗北宣言しない)。
pub fn fire_on_life_zero(state: &mut GameState, owner_idx: usize) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let cid = state.players[owner_idx].leader.card.card_id.clone();
    let Some(effs) = ov.get(&cid) else { return Ok(()) };
    for (idx, eff) in effs.iter().enumerate() {
        if eff.get("when").and_then(|v| v.as_str()) != Some("on_life_zero") {
            continue;
        }
        match eval_effect_conditions(eff, state, owner_idx, Some(Slot::Leader)) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("on_life_zero 条件 unknown".into()),
        }
        // cost は once_per_turn のみ対応 (overlay 実績: OP05-098 系のみ)。 他の cost は bail。
        if let Some(cost) = eff.get("cost") {
            let only_once = cost.as_object().map_or(true, |o| o.keys().all(|k| k == "once_per_turn"));
            if !only_once {
                return Err("on_life_zero cost 未対応".into());
            }
            if cost.get("once_per_turn").and_then(|v| v.as_bool()) == Some(true) {
                let key = format!("on_life_zero:{idx}");
                if state.players[owner_idx].leader.event_once_used.contains(&key) {
                    continue; // ターン既発動
                }
                state.players[owner_idx].leader.mark_event_once("on_life_zero", idx as i64);
            }
        }
        let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
        fire_gated_do(state, owner_idx, Slot::Leader, dos)?;
    }
    Ok(())
}

/// 【このキャラがバトルした時】(on_self_battled、 effects.py:12054、 ST02-010)。 attacker 所有者視点。
/// ⚠ once_per_turn は `_self_battled_{iid}` の iid キーで once_per_turn_used に入る = canonical 外
/// なので追跡不能 → 該当効果は明示 bail。
pub fn fire_on_self_battled(
    state: &mut GameState,
    me_idx: usize,
    card_id: &str,
    src: Slot,
) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let Some(effs) = ov.get(card_id) else { return Ok(()) };
    for (idx, eff) in effs.iter().enumerate() {
        if eff.get("when").and_then(|v| v.as_str()) != Some("on_self_battled") {
            continue;
        }
        crate::selfplay::note_fired(card_id);
        match eval_effect_conditions(eff, state, me_idx, Some(src)) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("on_self_battled 条件 unknown".into()),
        }
        // 【ターン1回】: Python は `_self_battled_{iid}` で判定しつつ event_once_used へ mirror する。
        if eff.get("cost").and_then(|c| c.get("once_per_turn")).is_some() {
            let key = format!("on_self_battled:{idx}");
            match src_ip(&state.players[me_idx], src) {
                Some(ip) if ip.event_once_used.contains(&key) => continue,
                Some(_) => {}
                None => return Err("on_self_battled: src 不在".into()),
            }
            if let Some(ip) = src_ip_mut(&mut state.players[me_idx], src) {
                ip.mark_event_once("on_self_battled", idx as i64);
            }
        }
        let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
        for prim in dos {
            if !on_trigger_prim_safe(prim.as_object().and_then(|o| o.keys().next()).map(|x| x.as_str()).unwrap_or("")) {
                return Err(format!(
                    "on_self_battled primitive 未対応: {}",
                    prim.as_object().and_then(|o| o.keys().next()).map(|x| x.as_str()).unwrap_or("?")
                ));
            }
            if !execute_effect(prim, state, me_idx, src) {
                return Err("on_self_battled primitive 再現不能".into());
            }
        }
    }
    Ok(())
}

/// 【自分がドローフェイズ以外でカードを引いた時】(effects.py:12011、 OP05-053)。
/// ⚠ 走査対象は me.characters のみ (leader/stage は対象外)。 once_per_turn は iid キーで
/// canonical 外なので該当効果は明示 bail。
fn fire_on_self_draw_non_draw_phase(state: &mut GameState, me_idx: usize) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let n = state.players[me_idx].characters.len();
    let toks: Vec<(Option<u64>, String)> = (0..n)
        .map(|i| {
            let cid = state.players[me_idx].characters[i].card.card_id.clone();
            (tag_src(state, me_idx, Slot::Char(i)), cid)
        })
        .collect();
    for (tok, cid) in toks {
        let slot = find_tagged(state, me_idx, tok);
        let Some(effs) = ov.get(&cid) else { continue };
        for (idx, eff) in effs.iter().enumerate() {
            if eff.get("when").and_then(|v| v.as_str()) != Some("on_self_draw_non_draw_phase") {
                continue;
            }
            crate::selfplay::note_fired(&cid);
            match eval_effect_conditions(eff, state, me_idx, Some(slot)) {
                Some(true) => {}
                Some(false) => continue,
                None => return Err("on_self_draw_non_draw_phase 条件 unknown".into()),
            }
            // 【ターン1回】: Python は `_self_draw_nondp_{iid}` (canonical 外) で判定するが、
            // 同時に InPlay.event_once_used へ mirror している (effects.py:12036) のでそれを見る。
            if eff.get("cost").and_then(|c| c.get("once_per_turn")).is_some() {
                let key = format!("on_self_draw_non_draw_phase:{idx}");
                match src_ip(&state.players[me_idx], slot) {
                    Some(ip) if ip.event_once_used.contains(&key) => continue,
                    Some(_) => {}
                    None => return Err("on_self_draw_non_draw_phase: src 不在".into()),
                }
                if let Some(ip) = src_ip_mut(&mut state.players[me_idx], slot) {
                    ip.mark_event_once("on_self_draw_non_draw_phase", idx as i64);
                }
            }
            let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
            fire_gated_do(state, me_idx, slot, dos)?;
        }
    }
    Ok(())
}

/// 【このキャラのバトルによって相手のキャラを KO した時】(effects.py:11945、 OP04-086)。
/// attacker 本人の効果だけを self-scope で発火する。
pub fn fire_on_self_battle_ko(
    state: &mut GameState,
    me_idx: usize,
    card_id: &str,
    src: Slot,
) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let Some(effs) = ov.get(card_id) else { return Ok(()) };
    for (idx, eff) in effs.iter().enumerate() {
        if eff.get("when").and_then(|v| v.as_str()) != Some("on_self_battle_ko") {
            continue;
        }
        crate::selfplay::note_fired(card_id);
        match eval_effect_conditions(eff, state, me_idx, Some(src)) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("on_self_battle_ko 条件 unknown".into()),
        }
        // 【ターン1回】: Python は `_self_battle_ko_{iid}` で判定しつつ event_once_used へ mirror。
        if eff.get("cost").and_then(|c| c.get("once_per_turn")).is_some() {
            let key = format!("on_self_battle_ko:{idx}");
            match src_ip(&state.players[me_idx], src) {
                Some(ip) if ip.event_once_used.contains(&key) => continue,
                Some(_) => {}
                None => return Err("on_self_battle_ko: src 不在".into()),
            }
            if let Some(ip) = src_ip_mut(&mut state.players[me_idx], src) {
                ip.mark_event_once("on_self_battle_ko", idx as i64);
            }
        }
        let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
        fire_gated_do(state, me_idx, src, dos)?;
    }
    Ok(())
}

/// 【このリーダーか自分のキャラにドンが付与された時】(effects.py:12044、 OP02-002)。
/// 走査対象は me.leader + me.characters (stage は対象外)。 cost 無し前提 (overlay 実績)。
pub fn fire_on_self_don_attached(state: &mut GameState, me_idx: usize) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let mut slots: Vec<Slot> = vec![Slot::Leader];
    slots.extend((0..state.players[me_idx].characters.len()).map(Slot::Char));
    let toks: Vec<(Option<u64>, String)> = slots
        .iter()
        .map(|&sl| {
            let cid = get_ip(&state.players[me_idx], sl).card.card_id.clone();
            (tag_src(state, me_idx, sl), cid)
        })
        .collect();
    for (tok, cid) in toks {
        let slot = find_tagged(state, me_idx, tok);
        let Some(effs) = ov.get(&cid) else { continue };
        for eff in effs {
            if eff.get("when").and_then(|v| v.as_str()) != Some("on_self_don_attached") {
                continue;
            }
            crate::selfplay::note_fired(&cid);
            match eval_effect_conditions(eff, state, me_idx, Some(slot)) {
                Some(true) => {}
                Some(false) => continue,
                None => return Err("on_self_don_attached 条件 unknown".into()),
            }
            if eff.get("cost").map_or(false, |c| !cost_is_empty(c)) {
                return Err("on_self_don_attached cost 未対応".into());
            }
            let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
            fire_gated_do(state, me_idx, slot, dos)?;
        }
    }
    Ok(())
}

/// ドンフェイズ修飾 (game.py:743、 OP13-003 赤紫ロジャー)。 リーダー overlay の
/// when:"don_phase_modifier" → auto_attach_to_leader N でアクティブドン N 枚を自リーダーへ付与。
pub fn apply_don_phase_modifier(state: &mut GameState, me_idx: usize) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let cid = state.players[me_idx].leader.card.card_id.clone();
    let Some(effs) = ov.get(&cid) else { return Ok(()) };
    for eff in effs {
        if eff.get("when").and_then(|v| v.as_str()) != Some("don_phase_modifier") {
            continue;
        }
        crate::selfplay::note_fired(&cid);
        match eval_effect_conditions(eff, state, me_idx, Some(Slot::Leader)) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err("don_phase_modifier 条件 unknown".into()),
        }
        let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
        for prim in dos {
            let n = prim.get("auto_attach_to_leader").and_then(|x| x.as_i64()).unwrap_or(0) as i32;
            if n > 0 {
                let p = &mut state.players[me_idx];
                let take = n.min(p.don_active);
                p.don_active -= take;
                p.leader.attached_dons += take;
            }
        }
    }
    Ok(())
}

/// ターン開始時の自動効果 (公式 6-2-1-1-2) を Python `trigger_turn_start` と同じモデルで。
/// = ターン側 on_turn_start と 非ターン側 opp_turn_start を **両方 enqueue してから 1 回ドレイン**。
/// (カードごとに即発火すると、 ターン側の do が誘発した効果が 非ターン側より先に走ってしまう)
pub fn enqueue_turn_start(state: &mut GameState, me_idx: usize, opp_idx: usize) -> Result<(), String> {
    if overlay().is_none() {
        return Ok(());
    }
    enqueue_field_when(state, me_idx, "on_turn_start");
    enqueue_field_when(state, opp_idx, "opp_turn_start");
    maybe_resolve(state)
}

/// エンドフェイズの自動効果 (公式 6-6-1-1) を Python `trigger_end_of_turn` と同じモデルで処理する。
///
/// ⭐ Python は **「両陣営を走査してコストを払い、 カード単位でイベントを enqueue」 → 最後に
///   1 回ドレイン** という 2 相構造 (effects.py:trigger_end_of_turn)。 Rust は従来 カードごとに
///   「コスト → do」 を **その場で** 実行していたため、
///   - do が誘発した効果 (登場の on_play 等) が **次のカードの end_of_turn より先に** 走る
///   - 後続カードのコスト判定が 「先行カードの do 適用後」 の盤面を見る
///   の 2 点で Python と乖離しうる (公式 8-4-1-3〜5 と同じ 「コスト由来は後」 の話の系)。
///   → 走査 (コスト支払い) と 解決 (do) を分けて Python と同順にする。
///
/// 順序: ターン側【自分のターン終了時】→ 非ターン側【相手のターン終了時】 (turn-first)。
pub fn fire_end_of_turn_batch(state: &mut GameState, me_idx: usize) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    for (owner_idx, when) in [(me_idx, "end_of_turn"), (1 - me_idx, "opp_end_of_turn")] {
        let toks = snapshot_field_toks(state, owner_idx);
        for (tok, cid) in toks {
            let Some(effs) = ov.get(&cid) else { continue };
            if !effs.iter().any(|e| e.get("when").and_then(|v| v.as_str()) == Some(when)) {
                continue;
            }
            let mut forced: Vec<usize> = Vec::new();
            for (idx, eff) in effs.iter().enumerate() {
                if eff.get("when").and_then(|v| v.as_str()) != Some(when) {
                    continue;
                }
                // ⚠ find_tagged は **タグを消費する** ので走査中は peek で位置を引く
                //   (消費すると 2 つ目以降の効果が Slot::Detached になり丸ごと不発になる)。
                let slot = peek_tagged(state, owner_idx, tok);
                let cost = eff.get("cost").cloned().unwrap_or(Value::Null);
                let cost_once = cost.get("once_per_turn").and_then(|v| v.as_bool()) == Some(true);
                // Python: cost.once_per_turn 済 (= `_end_of_turn_used_<idx>`) なら走査段で skip。
                // canonical mirror は event_once_used (`<when>:<idx>`)。
                if cost_once {
                    let key = format!("{when}:{idx}");
                    if get_ip(&state.players[owner_idx], slot).event_once_used.contains(&key) {
                        continue;
                    }
                }
                if !end_of_turn_cost_is_real(&cost) {
                    // 強制効果 (cost なし / once_per_turn のみ) = 条件は **解決時** に評価する
                    //   (Python も走査段では条件を見ない)。
                    forced.push(idx);
                    continue;
                }
                // cost-bearing optional: 条件 → 支払可否 → AI heuristic → 支払い (Python 同順)。
                match eval_effect_conditions(eff, state, owner_idx, Some(slot)) {
                    Some(true) => {}
                    Some(false) => continue,
                    None => return Err(format!("{when} 条件 unknown")),
                }
                if !can_pay_end_of_turn_cost(state, owner_idx, slot, &cost) {
                    continue;
                }
                if !ai_should_fire_end_of_turn_cost(state, owner_idx, slot, eff) {
                    continue;
                }
                // ⚠ 支払いで誘発したトリガーは Python と同じく **ここで** キューに積まれ、
                //   resolving 外なのでその場でドレインされる (= 既に積んだカードイベントも回る)。
                pay_end_of_turn_cost(state, owner_idx, slot, &cost, idx, when)?;
                forced.push(idx);
            }
            if !forced.is_empty() {
                // 解決時に位置を引き直せるよう、 走査タグとは別のトークンを打ち直す
                // (コストで場を離れた場合は Detached → tok2=None = Python の self_inplay 不在と等価)。
                let slot = peek_tagged(state, owner_idx, tok);
                let tok2 = tag_src(state, owner_idx, slot);
                state.rust_event_queue.push(PendingTrigger {
                    when: when.to_string(),
                    owner_idx,
                    card_id: cid.clone(),
                    slot: Slot::Leader,
                    tok: tok2,
                    eff_idxs: Some(forced),
                });
            }
            let _ = find_tagged(state, owner_idx, tok); // 走査用タグを回収
        }
    }
    maybe_resolve(state)
}

/// キューから取り出した 「コスト支払い済 + do だけ残っている」 イベントの解決
/// (Python `_execute_event` の `payload["effect_indexes"]` 分岐)。
fn run_explicit_idx_event(state: &mut GameState, evt: &PendingTrigger) -> Result<(), String> {
    let Some(ov) = overlay() else { return Ok(()) };
    let Some(effs) = ov.get(&evt.card_id) else { return Ok(()) };
    let owner_idx = evt.owner_idx;
    let when = evt.when.as_str();
    let idxs = evt.eff_idxs.clone().unwrap_or_default();
    for idx in idxs {
        let Some(eff) = effs.get(idx) else { continue };
        if eff.get("when").and_then(|v| v.as_str()) != Some(when) {
            continue;
        }
        // 場を離れていても解決する (Python: cost_paid_explicit で self_inplay=None を許容)。
        // ⚠ 複数 index を回すので peek (非消費)。 回収はループ後に 1 回。
        let slot = peek_tagged(state, owner_idx, evt.tok);
        // cost 既払いなので if 句のみ再評価 (条件変動の可能性に備える) = Python 同順。
        match eval_effect_conditions(eff, state, owner_idx, Some(slot)) {
            Some(true) => {}
            Some(false) => continue,
            None => return Err(format!("{when} 条件 unknown (cost 後)")),
        }
        // 【ターン1回】 ガード: **top-level** の once_per_turn のみ (cost 経由は支払い時に処理済)。
        let once_opt = eff.get("once_per_turn");
        if let Some(o) = once_opt {
            if let Some(shared) = o.as_str() {
                let key = format!("key:{shared}");
                if state.players[owner_idx].once_shared_used.contains(&key) {
                    continue;
                }
                let used = &mut state.players[owner_idx].once_shared_used;
                used.push(key);
                used.sort();
            } else if o.as_bool() == Some(true) {
                if !field_when_once_mirrored(when) {
                    return Err(format!("{when} once_per_turn 未対応"));
                }
                let key = format!("{when}:{idx}");
                if get_ip(&state.players[owner_idx], slot).event_once_used.contains(&key) {
                    continue;
                }
                get_ip_mut(&mut state.players[owner_idx], slot).mark_event_once(when, idx as i64);
            }
        }
        crate::selfplay::note_fired(&evt.card_id);
        let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { continue };
        fire_gated_do(state, owner_idx, slot, dos)?;
    }
    let _ = find_tagged(state, owner_idx, evt.tok); // タグ回収
    Ok(())
}

/// end_of_turn の cost が user-optional 支払いを伴うか (effects.py:11220 `_end_of_turn_cost_is_real`)。
fn end_of_turn_cost_is_real(cost: &Value) -> bool {
    let Some(o) = cost.as_object() else { return false };
    [
        "trash_self", "return_self_to_hand", "return_self_chara_to_hand", "discard_hand",
        "discard_hand_with_filter", "pay_don", "rest_self_don", "ko_self_with_filter", "rest_self",
    ]
    .iter()
    .any(|k| o.contains_key(*k))
}

/// end_of_turn cost が支払い可能か (effects.py:11243 `_can_pay_end_of_turn_cost`)。
fn can_pay_end_of_turn_cost(state: &GameState, owner: usize, src: Slot, cost: &Value) -> bool {
    let Some(o) = cost.as_object() else { return true };
    let pl = &state.players[owner];
    let geti = |k: &str| o.get(k).and_then(|x| x.as_i64()).unwrap_or(0) as i32;
    if geti("pay_don") > 0 && pl.don_active + pl.don_rested < geti("pay_don") {
        return false;
    }
    if geti("rest_self_don") > 0 && pl.don_active < geti("rest_self_don") {
        return false;
    }
    if geti("discard_hand") > 0 && (pl.hand.len() as i32) < geti("discard_hand") {
        return false;
    }
    let on_field = matches!(src, Slot::Char(_) | Slot::Stage(_));
    if o.contains_key("return_self_to_hand") && !on_field {
        return false;
    }
    if o.contains_key("trash_self") && !on_field {
        return false;
    }
    if let Some(rsc) = o.get("return_self_chara_to_hand") {
        let (filt, need) = if rsc.is_object() {
            (rsc.get("filter").cloned(), rsc.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize)
        } else {
            (None, 1)
        };
        if pl.characters.iter().filter(|c| matches_filter_ip(&c, filt.as_ref())).count() < need {
            return false;
        }
    }
    if let Some(ksf) = o.get("ko_self_with_filter") {
        if !pl.characters.iter().any(|c| matches_filter_ip(&c, Some(ksf))) {
            return false;
        }
    }
    true
}

/// AI が cost 付き end_of_turn 効果を自発発動するかの EV heuristic (effects.py:11393)。
fn ai_should_fire_end_of_turn_cost(state: &GameState, owner: usize, src: Slot, eff: &Value) -> bool {
    let cost = eff.get("cost").cloned().unwrap_or(json!({}));
    let co = cost.as_object().cloned().unwrap_or_default();
    let mut do_keys: std::collections::HashSet<String> = std::collections::HashSet::new();
    if let Some(dos) = eff.get("do").and_then(|d| d.as_array()) {
        for prim in dos {
            if let Some(o) = prim.as_object() {
                for k in o.keys() {
                    do_keys.insert(k.clone());
                }
            }
        }
    }
    let geti = |k: &str| co.get(k).and_then(|x| x.as_i64()).unwrap_or(0) as i64;
    let (pay_don, rest_don, discard_n) = (geti("pay_don"), geti("rest_self_don"), geti("discard_hand"));
    let mut cost_value = pay_don * 800 + rest_don * 400 + discard_n * 1500;
    let Some(sip) = src_ip(&state.players[owner], src) else { return false };
    let (ccost, cpower) = (sip.card.cost as i64, sip.card.power as i64);
    if co.contains_key("trash_self") {
        cost_value += ccost * 1000 + cpower / 2;
    }
    if co.contains_key("return_self_to_hand") {
        cost_value += ccost * 500 + cpower / 4;
    }
    if co.contains_key("rest_self") && !sip.rested {
        cost_value += 600;
    }
    let has = |k: &str| do_keys.contains(k);
    let mut benefit: i64 = 0;
    if has("draw") {
        benefit += 1500;
    }
    if has("search") || has("search_top_n") {
        benefit += 2000;
    }
    if has("add_don") {
        benefit += 1000;
    }
    if has("untap_don") {
        benefit += 800 + state.players[1 - owner].don_active as i64 * 50;
    }
    if has("ko") || has("ko_multi") {
        benefit += 3000;
    }
    if has("return_to_hand") || has("return_to_hand_multi") {
        benefit += 2500;
    }
    if has("power_pump") {
        benefit += 1500;
    }
    if has("give_keyword") {
        benefit += 2000;
    }
    let pl = &state.players[owner];
    if pl.life.len() <= 1 {
        benefit += 1000;
    }
    if pl.hand.len() <= 2 {
        if discard_n > 0 {
            cost_value += 2000;
        }
        if has("draw") || has("search") {
            benefit += 1500;
        }
    }
    if co.contains_key("trash_self") && ccost <= 3 && cpower <= 4000 {
        cost_value -= 1500;
    }
    benefit > cost_value
}

/// end_of_turn cost を支払う (effects.py:11285 `_pay_end_of_turn_cost`)。 cascade を伴う分岐
/// (pay_don の on_self_don_returned_to_deck / ko_self_with_filter の KO時) は Err で bail。
fn pay_end_of_turn_cost(
    state: &mut GameState,
    owner: usize,
    src: Slot,
    cost: &Value,
    eff_idx: usize,
    when: &str,
) -> Result<(), String> {
    let co = cost.as_object().cloned().unwrap_or_default();
    let geti = |k: &str| co.get(k).and_then(|x| x.as_i64()).unwrap_or(0) as i32;
    // trash_self / return_self_to_hand: source を場から除去 (付与ドンはレストへ)。
    let mut src_slot = src;
    if co.contains_key("trash_self") || co.contains_key("return_self_to_hand") {
        let to_hand = co.contains_key("return_self_to_hand") && !co.contains_key("trash_self");
        match src_slot {
            Slot::Char(i) if i < state.players[owner].characters.len() => {
            let ip = state.players[owner].characters.remove(i);
                let don = ip.attached_dons;
                if to_hand {
                    state.players[owner].hand.push(ip.card);
                } else {
                    state.players[owner].trash.push(ip.card);
                }
                state.players[owner].don_rested += don;
                src_slot = Slot::Detached;
            }
            Slot::Stage(i) if !to_hand && i < state.players[owner].stages.len() => {
                let ip = state.players[owner].stages.remove(i);
                let don = ip.attached_dons;
                state.players[owner].trash.push(ip.card);
                state.players[owner].don_rested += don;
                src_slot = Slot::Detached;
            }
            _ => {}
        }
    }
    // pay_don: active → rested の順でドンデッキへ。 戻した枚数>0 なら on_self_don_returned_to_deck。
    let pay_don = geti("pay_don");
    if pay_don > 0 {
        let pl = &mut state.players[owner];
        let taken = pay_don.min(pl.don_active);
        pl.don_active -= taken;
        pl.don_remaining_in_deck += taken;
        let more = (pay_don - taken).min(pl.don_rested);
        pl.don_rested -= more;
        pl.don_remaining_in_deck += more;
        if taken + more > 0 {
            state.last_returned_don_count = taken + more;
            if me_board_has_when(state, owner, "on_self_don_returned_to_deck") {
                // Python は enqueue → _maybe_resolve (解決中は後回し)。 inline 発火は順序が変わる。
                enqueue_field_when(state, owner, "on_self_don_returned_to_deck");
                maybe_resolve(state)?;
            }
        }
    }
    let rest_don = geti("rest_self_don");
    if rest_don > 0 {
        let pl = &mut state.players[owner];
        let actual = rest_don.min(pl.don_active);
        pl.don_active -= actual;
        pl.don_rested += actual;
    }
    if co.contains_key("rest_self") {
        if let Some(ip) = src_ip_mut(&mut state.players[owner], src_slot) {
            ip.rested = true;
        }
    }
    let discard_n = geti("discard_hand");
    for _ in 0..discard_n.min(state.players[owner].hand.len() as i32) {
        let pl = &mut state.players[owner];
        let Some(i) = worst_hand_idx(&pl.hand, &pl.known_hand_card_ids) else { break };
        let c = pl.hand.remove(i);
        pl.trash.push(c);
    }
    if let Some(rsc) = co.get("return_self_chara_to_hand") {
        let (filt, need) = if rsc.is_object() {
            (rsc.get("filter").cloned(), rsc.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize)
        } else {
            (None, 1)
        };
        let mut returned = 0usize;
        let mut i = 0usize;
        while i < state.players[owner].characters.len() && returned < need {
            if matches_filter_ip(&state.players[owner].characters[i], filt.as_ref()) {
            let ip = state.players[owner].characters.remove(i);
                let don = ip.attached_dons;
                state.players[owner].hand.push(ip.card);
                state.players[owner].don_rested += don;
                returned += 1;
            } else {
                i += 1;
            }
        }
    }
    if let Some(ksf) = co.get("ko_self_with_filter").cloned() {
        // ⚠ Python は `trigger_on_ko` / `trigger_on_self_chara_ko` = **enqueue + 即ドレイン**
        //   (走査中なので resolving=false → 既に積んだカードイベントごと解決される)。 Rust の
        //   on_ko は inline 発火でキューを持たないため同順を再現できない → 明示 bail。
        //   overlay 全走査で **end_of_turn cost に ko_self_with_filter を持つカードは 0 枚**
        //   (該当は pay_don の OP09-068 / OP16-073 のみ) なので実質デッドコード。
        if (0..state.players[owner].characters.len())
            .any(|i| matches_filter_ip(&state.players[owner].characters[i], Some(&ksf)))
        {
            return Err("end_of_turn cost ko_self_with_filter: KO時の解決順 未追従 = bail".into());
        }
        // Python は最初の 1 体のみ KO し、 KO時トリガーを発火する。
        if let Some(i) = (0..state.players[owner].characters.len())
            .find(|&i| matches_filter_ip(&state.players[owner].characters[i], Some(&ksf)))
        {
            let vcid = state.players[owner].characters[i].card.card_id.clone();
            note_ko_victim_negated(state, owner, i);
            let ip = state.players[owner].characters.remove(i);
            let don = ip.attached_dons;
            let _ko_vic = ip.card.clone();
                let _ko_vtop = ip.truly_original_power(); // KO 時点の元々のパワー (公式 4-9-2-1) // KO victim 文脈 (victim_truly_original_power_ge / victim_feature_in 用)
            state.players[owner].trash.push(ip.card);
            state.players[owner].don_rested += don;
            // Python (_pay_end_of_turn_cost) は trigger_on_ko を呼ぶので
            // chara_ko_taken_this_turn が増える (= 全 KO 経路の共通フック)。
            state.last_chara_ko_victim_card = Some(_ko_vic);
                state.rust_ko_victim_truly_original_power = Some(_ko_vtop); // Python は payload で victim を運ぶ (2026-08-11)
            fire_on_ko(state, owner, &vcid, false)?;
            fire_field_when(state, owner, "on_self_chara_ko")?;
            state.last_chara_ko_victim_card = None;
        }
    }
    // once_per_turn の canonical mirror (Python は _end_of_turn_used_N 動的属性 + mark_event_once)。
    if co.contains_key("once_per_turn") {
        if let Some(ip) = src_ip_mut(&mut state.players[owner], src_slot) {
            ip.mark_event_once(when, eff_idx as i64);
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
            // ⚠ 実キーは on_ 無しの "opp_event_or_trigger_fired" (Python の綴り違いを修正済)。
            | "opp_event_or_trigger_fired" | "on_opp_event_or_trigger_fired"
            // 「相手がイベントを発動した時」 (= イベント発動のみ、 ライフ【トリガー】では発火せず、
            //  cardqa_op_11 = OP11-012 フランキー / OP06-044 ギオン 等)。 event-play 経路のみ enqueue。
            | "opp_event_played"
            | "on_self_chara_leave_by_self_effect" | "on_self_rested"
            // field-when で once_per_turn を持つが mirror 漏れだった when (2026-08-10)
            | "on_self_chara_rested_by_self_effect" | "on_opp_blocker_use"
            | "on_self_chara_leave_by_opp_effect" | "on_opp_chara_returned_to_hand_by_self_effect"
            | "opp_attack_on_chara"
            | "on_self_trigger_fired" | "opp_trigger_fired" | "on_life_zero" | "on_play" | "on_block"
            // end_of_turn / opp_end_of_turn は _pay_end_of_turn_cost が mark_event_once で
            // canonical mirror する (2026-08-02)。 これで Rust も「ターン1回」を追跡できる。
            | "end_of_turn" | "opp_end_of_turn"
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
        // ⚠ 「効果無効」 の gate はここ (cost 支払い前) で見ない。 Python (_enqueue_opp_attack_with_cost)
        //   は cost 支払い自体には無効化チェックを一切行わず、 無効化ゲートは enqueue 後の
        //   _execute_event (= do 発火の直前) でのみ効く (effects.py:270)。 = 効果無効でも cost
        //   (discard_hand/once_per_turn マーク 等) は先に消費される (2026-08-07、 OP11-041 ナミの
        //   opp_attack が negate されても discard_hand コストだけ先に払われていた MISMATCH で発覚)。
        //   → 発火フェーズ (下) で do 実行の直前にチェックする。
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
                // Python (opp_attack 経路) も同様に entry index で gate する (値は見ない)。
                if !o.is_null()
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
        // 発動元が 「効果無効」 なら 【相手のアタック時】/【ブロック時】 は発動しない
        // (effects.py:_execute_event の gate、 270行目)。 cost 支払い後・do 発火の直前でのみ効く
        // (上の cost 支払いフェーズでは見ない、 このループ冒頭に移設した理由はそこの comment 参照)。
        if src_effect_negated(state, defender_idx, slot, "on_attack") {
            continue;
        }
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
        // ⚠ **昇順** に処理する。 Python は場の並び順 (leader→chars 昇順) にコストを払うので
        //   trash への到着順も昇順。 降順 remove は index shift を避けられるが **トラッシュの順が
        //   逆になる** = digest 不一致 (ST22-002 が 2 体並ぶと露見、 2026-08-04 掃引 MISMATCH)。
        //   昇順のまま、 除去済み枚数ぶん index を詰めて shift を吸収する。
        let mut shift = 0usize;
        for (ci, _) in trash_self_fires.iter() {
            let i = ci.saturating_sub(shift);
            if i < state.players[defender_idx].characters.len() {
                let removed = state.players[defender_idx].characters.remove(i);
                let don = removed.attached_dons;
                state.players[defender_idx].trash.push(removed.card);
                state.players[defender_idx].don_rested += don;
                shift += 1;
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
    // 「相手がイベントを発動した時」 (OP11-012 フランキー 等) は event-play 経路のみ。
    // opp_event_or_trigger_fired の直前に撃つ (Python: trigger_opp_event_played → …_or_trigger_fired)。
    fire_field_when(state, opp, "opp_event_played")?;
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
        // カウンターも event-play 経路 = 「相手がイベントを発動した時」 を撃つ (ライフ【トリガー】は別)。
        fire_field_when(state, attacker_idx, "opp_event_played")?;
        fire_field_when(state, attacker_idx, "opp_event_or_trigger_fired")?;
        fire_field_when(state, defender_idx, "on_self_event_played")?;
    }
    Ok(())
}

/// ステージ登場時の on_play 効果を実行 (game.py:PlayStage → trigger_on_play)。 played_idx = me.stages の末尾。
pub fn execute_stage_on_play(state: &mut GameState, me_idx: usize, played_idx: usize) -> Result<(), String> {
    // ⭐ Python の trigger_on_play は category を問わず last_chara_played_by_field_chara を
    //   立てる (cardqa_op_12 / OP12-081) ので、 STAGE 経路でも同じく反映する。
    state.last_chara_played_by_field_chara = state.rust_play_source_is_field_chara;
    // Python (effects.py:trigger_on_play) は category を問わず on_play を **enqueue** してから
    // _maybe_resolve を呼ぶ (= 解決中ならその場では発火せず後回し)。 以前はここで
    // execute_card_effects を直接呼んでいたため、 STAGE 登場の on_play が (character の
    // execute_on_play と違って) 常に inline 発火していた。 これがネストして呼ばれる経路
    // (= 他 do-list の途中で play_stage_from_hand が呼ばれた場合) では、 外側の do-list の
    // 残りより **先に** 発火してしまい順序がズレる (OP08-098 カルガラの on_attack 内で
    // 「ワイパー on_play → アッパーヤード search→play_stage_from_hand」 が起き、 その
    // アッパーヤード自身の on_play (search_top_n) が本来は on_attack の do-list 完了後まで
    // 後回しになるはずが、 inline 発火して外側の draw/block_self_draw_turn より先にデッキを
    // 消費していた、 2026-08-07 発覚)。 character 版 execute_on_play と同じ enqueue+resolve
    // guard に揃える (on_self/opp_chara_played は CHARACTER 限定、 Python も同様に stage では
    // 発火しない)。
    let card_id = state.players[me_idx].stages[played_idx].card.card_id.clone();
    if !state.players[me_idx].opp_on_play_disabled_through_opp_turn {
        enqueue_trigger(state, "on_play", me_idx, &card_id, Slot::Stage(played_idx));
    }
    maybe_resolve(state)
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
    let (cost, dos, eff_owned): (Option<Value>, Vec<Value>, Value) = {
        let Some(ov) = overlay() else { return Ok(()) };
        let Some(effs) = ov.get(card_id) else { return Ok(()) };
        let Some(eff) = effs.get(effect_index) else { return Err("effect_index 範囲外".into()) };
        (
            eff.get("cost").cloned(),
            eff.get("do").and_then(|v| v.as_array()).cloned().unwrap_or_default(),
            eff.clone(),
        )
    };
    // trash_self でこの起動源が場から除去されたか (= act_used マークを skip する為)。
    let mut source_gone = false;
    // ⭐ 発動コストの支払いで誘発した効果は **本体の解決後** に発動する
    //    (公式 8-4-1-3〜8-4-1-5 + cardqa_op_14 / OP14-080)。 Python は
    //    `_cost_trigger_buffer` に退避して本体 enqueue の後でキューへ流す。 Rust は
    //    「反応集合を支払い時に snapshot して、 do-list の後に発火」 で同じ順序を作る
    //    (= Python の 「enqueue 時にカード単位でスナップショット」 と等価)。
    let mut deferred: Vec<DeferredCostTrigger> = Vec::new();
    // cost 支払い。 未対応 cost 種別 or cascade を起こす cost は bail (黙って間違えない)。
    if let Some(c) = &cost {
        if let Some(o) = c.as_object() {
            for k in o.keys() {
                if !matches!(k.as_str(), "rest_self" | "pay_don" | "rest_self_don" | "once_per_turn" | "rest_own_card" | "ko_self_with_filter" | "trash_self" | "trash_to_deck" | "discard_hand_or_trash_filtered_chara" | "discard_hand" | "return_self_to_hand" | "discard_hand_with_filter" | "reveal_hand_with_filter" | "rest_self_target_name" | "rest_self_target" | "life_to_hand") {
                    note_unknown_key("activate_cost", k);
                    return Err(format!("activate_main cost 未対応: {k} ({card_id})"));
                }
            }
        }
        // pay_don は on_self_don_returned_to_deck cascade を起こす。 発火できるようになったので
        // ここでは bail しない (下の支払い後に fire する)。
        let pay_don = c.get("pay_don").and_then(|v| v.as_i64()).unwrap_or(0) as i32;

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
        // life_to_hand N: ライフの上から N 枚を手札へ (= 発動コスト、 Python と同順で rest_self の前)。
        // 公式 OP01-013 サンジ 「自分のライフ1枚を手札に加えることができる：」 (2026-08-11 新設)。
        let life_cost_n = c.get("life_to_hand").and_then(|v| v.as_i64()).unwrap_or(0);
        if life_cost_n > 0 {
            let mut moved = 0;
            for _ in 0..life_cost_n {
                if state.players[me_idx].life.is_empty() {
                    break;
                }
                let lc = state.players[me_idx].life.remove(0);
                state.players[me_idx].hand.push(lc);
                moved += 1;
            }
            if moved > 0 {
                // 「自分のライフが手札に加わった時」 (Python fire_self_life_to_hand と同経路)。
                fire_self_life_to_hand(state, me_idx)?;
            }
        }
        if c.get("rest_self").and_then(|v| v.as_bool()).unwrap_or(false) {
            // ⭐ **発動コストでレストになった場合も 「レストになった時」 は発動する**
            //   (公式 cardqa_op_07 / OP07-031 バルトロメオ → 「はい、 できます」)。
            //   Python は `_fire_rested_triggers` を コスト支払い中に呼び、 _cost_trigger_buffer
            //   経由で **本体の後** に解決する。 Rust の起動メインは DeferredCostTrigger で
            //   同順を作っているが 「レスト由来」 はまだ載せていないので、 反応カードが場に
            //   あれば bail する (= 黙って乖離しない)。
            let src_rested_before = get_ip(&state.players[me_idx], src).rested;
            if !src_rested_before {
                let scid = get_ip(&state.players[me_idx], src).card.card_id.clone();
                if card_has_when(&scid, "on_self_rested")
                    || me_board_has_when(state, me_idx, "on_self_chara_rested_by_self_effect")
                {
                    return Err("起動メイン rest_self コスト由来の レスト時トリガー 未対応".into());
                }
            }
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
            // 「ドンをドンデッキに戻した時」 (EB02-035 / P-077)。
            // Python は enqueue → _maybe_resolve (解決中は後回し)。 inline 発火は順序が変わる。
            if taken + more > 0 {
                state.last_returned_don_count = taken + more;
                if me_board_has_when(state, me_idx, "on_self_don_returned_to_deck") {
                    // コスト由来 = 本体解決後に発火 (反応集合は今の盤面で snapshot)。
                    let toks = snapshot_field_toks(state, me_idx);
                    deferred.push(DeferredCostTrigger::FieldWhen {
                        owner: me_idx,
                        when: "on_self_don_returned_to_deck".to_string(),
                        toks,
                    });
                }
            }
        }
        // rest_self_target_name / rest_self_target: 自場の同名アクティブ 1 枚をレスト
        // (effects.py:8929 と対。 専用 primitive が無いのでここで直接処理する)。
        for key in ["rest_self_target_name", "rest_self_target"] {
            if let Some(spec) = c.get(key) {
                let want = spec.get("name").and_then(|v| v.as_str())
                    .or_else(|| spec.as_str()).unwrap_or("").to_string();
                let mep = &mut state.players[me_idx];
                // Python は characters → stages の順に走査して最初の 1 枚をレスト
                let mut done = false;
                for x in mep.characters.iter_mut() {
                    if x.card.name == want && !x.rested { x.rested = true; done = true; break; }
                }
                if !done {
                    for x in mep.stages.iter_mut() {
                        if x.card.name == want && !x.rested { x.rested = true; break; }
                    }
                }
            }
        }
        let rest_don = c.get("rest_self_don").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
        if rest_don > 0 {
            let me = &mut state.players[me_idx];
            let n = rest_don.min(me.don_active);
            me.don_active -= n;
            me.don_rested += n;
        }
        // discard_hand_with_filter cost (effects.py:13524)。 hand 順に filter 一致を count 枚 trash。
        // ⚠ payability は can_pay_activate_cost で判定済。 filter は {"filter":{..}} か直書きの両形。
        if let Some(dfs) = c.get("discard_hand_with_filter").cloned() {
            if dfs.is_object() {
                let d_filt = match dfs.get("filter") {
                    Some(f) => f.clone(),
                    None => {
                        let mut o = dfs.as_object().unwrap().clone();
                        o.remove("count");
                        Value::Object(o)
                    }
                };
                let d_count = dfs.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
                let me = &mut state.players[me_idx];
                let old_hand = std::mem::take(&mut me.hand);
                let mut discarded = 0usize;
                for card in old_hand {
                    if discarded < d_count && matches_filter(&card, Some(&d_filt)) {
                        me.trash.push(card);
                        discarded += 1;
                    } else {
                        me.hand.push(card);
                    }
                }
            }
        }
        // reveal_hand_with_filter は公開のみ = state 変化なし (payability で確認済)。
        // discard_hand cost: worst_hand_idx で n 枚捨てる (effects.py:13xxx activate_main cost)。
        let dn = c.get("discard_hand").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
        if dn > 0 {
            if (state.players[me_idx].hand.len() as i32) < dn {
                return Ok(()); // 払えない = 発動しない
            }
            for _ in 0..dn {
                let me = &mut state.players[me_idx];
                let Some(i) = worst_hand_idx(&me.hand, &me.known_hand_card_ids) else { break };
                let card = me.hand.remove(i);
                me.trash.push(card);
            }
        }
        // return_self_to_hand cost: 起動源自身を手札へ (付与ドンはレストへ)。 src が場から消える。
        if c.get("return_self_to_hand").and_then(|v| v.as_bool()).unwrap_or(false) {
            let me = &mut state.players[me_idx];
            let removed = match src {
                Slot::Char(i) if i < me.characters.len() => me.characters.remove(i),
                _ => return Err("return_self_to_hand source 不明".into()),
            };
            let don = removed.attached_dons;
            me.hand.push(removed.card);
            me.don_rested += don;
            source_gone = true;
        }
        // discard_hand_or_trash_filtered_chara (effects.py:13566、 OP13-079 イム):
        // 「特徴 X のキャラ か 手札 1 枚 を トラッシュ」 の選択コスト。 AI は **手札優先**
        // (手札 >= n なら worst_hand_idx を n 枚)、 手札不足なら filter 一致キャラを power 昇順で n 体。
        if let Some(cc) = c.get("discard_hand_or_trash_filtered_chara") {
            let n = cc.get("n").and_then(|x| x.as_i64()).unwrap_or(1) as usize;
            let filt = cc.get("filter");
            if state.players[me_idx].hand.len() >= n {
                for _ in 0..n {
                    let me = &mut state.players[me_idx];
                    if me.hand.is_empty() {
                        break;
                    }
                    let Some(i) = worst_hand_idx(&me.hand, &me.known_hand_card_ids) else { break };
                    let card = me.hand.remove(i);
                    me.trash.push(card);
                }
            } else {
                let mut cands: Vec<usize> = (0..state.players[me_idx].characters.len())
                    .filter(|&i| matches_filter_ip(&state.players[me_idx].characters[i], filt))
                    .collect();
                // Python: chara_cands.sort(key=power) = 昇順 (安定 = tie は board 順)
                cands.sort_by_key(|&i| state.players[me_idx].characters[i].power());
                let mut chosen: Vec<usize> = cands.into_iter().take(n).collect();
                chosen.sort_unstable();
                for i in chosen.into_iter().rev() {
                    let me = &mut state.players[me_idx];
                    let removed = me.characters.remove(i);
                    let don = removed.attached_dons;
                    me.trash.push(removed.card);
                    me.don_rested += don;
                }
            }
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
                if !me.leader.rested && matches_filter_ip(&me.leader, ro_filt) {
                    pool.push((true, me.leader.power(), Slot::Leader));
                }
                for i in 0..me.characters.len() {
                    let ch = &me.characters[i];
                    if !ch.rested && matches_filter_ip(&ch, ro_filt) {
                        pool.push((false, ch.power(), Slot::Char(i)));
                    }
                }
                for i in 0..me.stages.len() {
                    let s = &me.stages[i];
                    if !s.rested && matches_filter_ip(&s, ro_filt) {
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
        //   (self-ko なので on_opp_chara_ko は無し)。 未対応 on_ko/cascade は run_on_ko_effects/
        //   fire_field_when_with_toks が bail。
        // ⭐ 公式 (cardqa_op_14 / OP14-080): 【KO時】は **本体 (パワー+1000 等) を解決した後** に
        //    発動する。 記録 (被KO数 / 効果無効 gate / victim 文脈) は KO の瞬間に行い、 do の実行だけ
        //    deferred に回す = Python の 「即 enqueue、 ドレインは本体の後」 と同順。
        if let Some(kf) = c.get("ko_self_with_filter") {
            let me = &mut state.players[me_idx];
            if let Some(i) = me.characters.iter().position(|ch| matches_filter_ip(&ch, Some(kf))) {
                let removed = me.characters.remove(i);
                let vcid = removed.card.card_id.clone();
                let don = removed.attached_dons;
                // 【KO時】 gate 用に move 前に記録 (公式 Q&A: 無効化されたキャラの【KO時】は不発)。
                let neg = removed.granted_keywords.contains("効果無効")
                    || removed.static_granted_keywords.contains("効果無効")
                    || removed.effect_disabled_through_opp_turn;
                let vcard = removed.card.clone();
                me.trash.push(removed.card);
                me.don_rested += don;
                state.ko_victim_effect_negated = neg;
                // victim_* 条件用の文脈 (Python trigger_on_ko:last_chara_ko_victim_card)。
                // deferred な【KO時】/ on_self_chara_ko が読むので本体解決まで保持する
                // (Python も バッファ中は trigger_on_self_chara_ko でクリアしない)。
                state.last_chara_ko_victim_card = Some(vcard);
                if note_ko_and_should_fire(state, me_idx, &vcid, false) {
                    deferred.push(DeferredCostTrigger::OnKo { owner: me_idx, victim_cid: vcid });
                }
                let toks = snapshot_field_toks(state, me_idx);
                deferred.push(DeferredCostTrigger::FieldWhen {
                    owner: me_idx,
                    when: "on_self_chara_ko".to_string(),
                    toks,
                });
            }
        }
    }
    // once_per_turn フラグ (effects.py と同じく **明示指定時のみ**)。 ⚠ source_gone (trash_self)
    // 時は起動源が場から消えている → Python は off-field object に setattr する (digest 不変=trash は
    // CardDef のみ) ので Rust は skip (stale index を触らない)。
    // ⚠ 既定 True (= 【ターン1回】 が無くても一律 1 回) は 2026-08-04 に撤去。 公式は
    //   コストを払える限り何度でも起動できる。
    let once = cost.as_ref().and_then(|c| c.get("once_per_turn")).and_then(|v| v.as_bool()).unwrap_or(false);
    if once && !source_gone {
        get_ip_mut(&mut state.players[me_idx], src).act_used = true;
    }
    // do: cascade guard + prim gating
    if effect_cascade_blocked(&dos, state, me_idx) {
        return Err(format!("activate_main cascade 未対応 ({card_id})"));
    }
    // ⚠ trash_self cost で起動源が場を離れた後は src (位置 index) が無効。 そのまま渡すと
    //   get_ip が index out of bounds で **panic** していた (OP07-109 / OP05-027/028、 全カード掃引で検出)。
    //   Python は self_inplay を object 参照で保持するが、 場を離れた InPlay への変更は digest に現れない
    //   (trash には CardDef しか残らない) ので、 Slot::Detached (= target "self" は 0 対象) と等価。
    let do_src0 = if source_gone { Slot::Detached } else { src };
    // ⚠ Python は起動メイン本体を **enqueue** し、 resolve_triggers の中 (resolving=true) で
    //   実行する。 = do の途中で誘発した別カードの効果は キューに積まれるだけで、 do-list を
    //   終えてから解決される。 Rust も同じ文脈で走らせる (inline drain だと順序が変わる)。
    let prev_resolving = state.rust_resolving;
    state.rust_resolving = true;
    let r = (|| -> Result<(), String> {
        let mut do_src = do_src0;
        // ⚠ Python は cost 支払い **後** に if 句を再評価する (_execute_event:
        //   「cost 既払いなので if 句のみ再評価 (条件変動の可能性に備える)」)。
        //   コスト自体が条件を崩すカードがあるため必須。 例 P-081 クロスギルド:
        //   cost=return_self_to_hand で自分が場を離れ 「青の《クロスギルド》キャラ3枚以上」 が
        //   崩れる → Python は不発、 Rust は支払い前の判定のまま登場させていた (2026-08-03 発覚)。
        // 発動元が 「効果無効」 なら発動しない (effects.py:_execute_event の gate)。
        // ⚠ 不発でも **コストは払い済み** = コスト由来トリガーは発動する (下の deferred へ落ちる)。
        let mut run_do = !src_effect_negated(state, me_idx, do_src, "activate_main");
        if run_do {
            match eval_effect_conditions(&eff_owned, state, me_idx, Some(do_src)) {
                Some(true) => {}
                Some(false) => run_do = false, // 条件が崩れた = 効果は発動しない
                None => return Err("activate_main 条件 unknown (cost 後)".into()),
            }
        }
        if run_do {
            // do の途中で盤面が動いても発動元を見失わないよう、 一意トークンで追跡する
            // (Python の self_inplay object 参照と等価。 場外に出たら Detached)。
            let mut tok = tag_src(state, me_idx, do_src);
            let last = dos.len().saturating_sub(1);
            for (pi_, prim) in dos.iter().enumerate() {
                if !execute_effect(prim, state, me_idx, do_src) {
                    let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("?");
                    find_tagged(state, me_idx, tok);
                    return Err(format!("activate_main primitive 未対応: {k} ({card_id})"));
                }
                // 最終 prim の後は src を参照しないので取り直し不要
                if pi_ < last {
                    do_src = find_tagged(state, me_idx, tok);
                    tok = tag_src(state, me_idx, do_src);
                } else {
                    find_tagged(state, me_idx, tok);
                }
            }
        }
        // ⭐ 発動コスト由来のトリガー (公式 8-4-1-3〜5 / cardqa_op_14): 本体の解決後に発動。
        //    do が積んだ nested トリガーは **さらに後** (= キューに残っている) = Python 同順。
        for d in std::mem::take(&mut deferred) {
            match d {
                DeferredCostTrigger::OnKo { owner, victim_cid } => {
                    run_on_ko_effects(state, owner, &victim_cid)?;
                }
                DeferredCostTrigger::FieldWhen { owner, when, toks } => {
                    fire_field_when_with_toks(state, owner, &when, toks)?;
                }
            }
        }
        Ok(())
    })();
    state.rust_resolving = prev_resolving;
    r?;
    if !prev_resolving {
        maybe_resolve(state)?;
    }
    // コスト由来の victim 文脈は本体解決まで保持していたので、 ここで畳む (Python:
    // fire_activate_main 末尾で last_chara_ko_victim_card = None)。
    state.last_chara_ko_victim_card = None;
    Ok(())
}

/// 発動コストの支払いで誘発したトリガー (= 本体の解決後に発動する)。
/// 公式 8-4-1-3〜8-4-1-5 + cardqa_op_14 (OP14-080)。 反応集合 (toks) は **支払い時** に
/// snapshot する = Python の `_enqueue_field_when` (enqueue 時にカード単位で積む) と等価。
enum DeferredCostTrigger {
    OnKo { owner: usize, victim_cid: String },
    FieldWhen { owner: usize, when: String, toks: Vec<(Option<u64>, String)> },
}

/// do-list 実行中に src が「別のカードを指す / 範囲外になる」ことがある (前の primitive が場を縮めた場合)。
/// Python は self_inplay を **object 参照** で追うので影響を受けないが、 Rust は位置 index なので
/// 黙って別カードへ適用する (= MISMATCH) か panic する。 → 検知して明示 bail する。
/// 例: ST22-005 `[{return_to_hand: other_self_chara}, {untap: self}]` (全カード掃引で panic として検出)。
fn src_shifted(state: &GameState, me_idx: usize, src: Slot, expect: Option<&String>) -> bool {
    let Some(cid) = expect else { return false };
    match src {
        Slot::Detached | Slot::Leader => false,
        s => src_ip(&state.players[me_idx], s).map_or(true, |ip| &ip.card.card_id != cid),
    }
}

/// スモーク用: card_id の effect_index 番目の効果だけを発火する (条件/cost/do を通常経路と同じ順で)。
/// 通常の対戦経路ではないので once_per_turn の canonical mirror 等は触らない (実行可否の測定が目的)。
pub fn execute_one_effect(
    state: &mut GameState,
    me_idx: usize,
    card_id: &str,
    when: &str,
    effect_index: usize,
    src: Slot,
) -> Result<(), String> {
    let Some(ov) = overlay() else { return Err("overlay 未ロード".into()) };
    let Some(effs) = ov.get(card_id) else { return Err("overlay に該当カード無し".into()) };
    let Some(eff) = effs.get(effect_index) else { return Err("effect_index 範囲外".into()) };
    if eff.get("when").and_then(|v| v.as_str()) != Some(when) {
        return Err("when 不一致".into());
    }
    if src_effect_negated(state, me_idx, src, when) {
        return Ok(()); // 発動元が効果無効 = 発動しない (effects.py:_execute_event の gate)
    }
    match eval_effect_conditions(eff, state, me_idx, Some(src)) {
        Some(true) => {}
        Some(false) => return Ok(()), // 条件不成立 = 発動しない (実装漏れではない)
        None => return Err("条件 unknown".into()),
    }
    // ⚠ activate_main の cost は専用機構 (fire_activate_main = can_pay_activate_cost + 支払い) が
    //   扱う。 ここで counter cost 経路に流すと ko_self_with_filter 等が「未対応」に見えてしまう
    //   (= ハーネス由来の偽陽性。 2026-08-02 にスモークで 6 件計上されていた)。 実経路に委譲する。
    if when == "activate_main" {
        let (kind, idx) = match src {
            Slot::Leader => ("leader", 0usize),
            Slot::Char(i) => ("char", i),
            Slot::Stage(i) => ("stage", i),
            Slot::Detached => ("leader", 0usize),
        };
        return fire_activate_main(state, me_idx, card_id, effect_index, kind, idx);
    }
    if let Some(cost) = eff.get("cost") {
        if !cost_is_empty(cost) {
            let only_once = cost.as_object().map_or(false, |o| o.keys().all(|k| k == "once_per_turn"));
            if !only_once {
                match try_pay_counter_cost(state, me_idx, src, cost)? {
                    true => {}
                    false => return Ok(()), // 払えない = 発動しない
                }
            }
        }
    }
    let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { return Ok(()) };
    for prim in dos {
        if !execute_effect(prim, state, me_idx, src) {
            let k = prim.as_object().and_then(|o| o.keys().next()).map(|s| s.as_str()).unwrap_or("?");
            // 実装済 primitive が spec 変種で落ちるケースを特定できるよう spec も返す (char 境界で truncate)
            let spec: String = prim.to_string().chars().take(120).collect();
            return Err(format!("primitive 未対応/再現不能: {k} {spec}"));
        }
    }
    Ok(())
}

/// on_self_hand_discarded を発火する前に「破棄を起こした効果の発動元」の特徴を transient に載せる
/// (Python の trigger_on_self_hand_discarded が last_discard_source_inplay を一時設定するのと対応)。
/// 条件 actor_source_feature_contains がこれを見る。 発火後は必ず None に戻す。
fn fire_hand_discarded_n(state: &mut GameState, me_idx: usize, src: Slot, n: i32) -> Result<(), String> {
    if n <= 0 {
        return Ok(());
    }
    // Python trigger_on_self_hand_discarded (effects.py:13398) は discard_count>0 で
    // canonical flag hand_discarded_by_effect_this_turn=True を立ててから field-when を発火する。
    // 置換コストの discard 経路 (try_replace_ko) は外側でこの flag を立てていなかったため、
    // Python (trigger が flag を立てる) と digest が食い違っていた (OP12-053 / OP13-046 /
    // OP15-003 の replace-cost discard で MISMATCH)。 flag 設定を helper 内に集約して全経路一致。
    state.players[me_idx].hand_discarded_by_effect_this_turn = true;
    // ⭐ InPlay が無い発動元 (= 【トリガー】/イベント) は CardDef 由来の特徴に fallback。
    //   公式 cardqa_op_12 (OP12-057 の【トリガー】手札捨て → OP12-040 クザンが追加ドロー)。
    state.current_discard_source_features = src_ip(&state.players[me_idx], src)
        .map(|ip| ip.card.features.clone())
        .or_else(|| state.current_source_card_features.clone());
    state.current_discard_count = n;
    let r = fire_field_when(state, me_idx, "on_self_hand_discarded");
    state.current_discard_source_features = None;
    state.current_discard_count = 0;
    r
}

fn fire_hand_discarded(state: &mut GameState, me_idx: usize, src: Slot) -> Result<(), String> {
    fire_hand_discarded_n(state, me_idx, src, 1)
}

/// game.py:evaluate_static_effects の移植 (on_attached_don 常在)。
pub fn evaluate_static_effects(state: &mut GameState) {
    // ⚠ 表向きライフ枚数の正規化 (effects.py:evaluate_static_effects 冒頭と同じ、 2026-08-04)。
    //   face_up_life_count は増やす側/読む側は clamp していたが **ライフが減る時に減らして
    //   いなかった** ため、 ライフ 0 なのに表向き 1 という壊れた値が残り、 後でライフが増えると
    //   裏向きの新しいライフを表向きと誤認しうる。 保存則チェック (INV-face-up-life) が検出した
    //   = 両エンジンが同じ間違いをしていて差分では見えなかったクラス。
    //   ⚠ overlay 未 load でも正規化する (Python も early return より前で行う)。
    for p in state.players.iter_mut() {
        let clamped = p.face_up_life_count.clamp(0, p.life.len() as i32);
        if clamped != p.face_up_life_count {
            p.face_up_life_count = clamped;
        }
    }
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
            crate::selfplay::note_fired(&card_id); // 静的効果も「発火」として記録 (計測漏れ防止)
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

/// effects.py:_execute_event の 「効果無効」 ゲート。 発動元が negate_effect/disable_effect で
/// 無効化されていれば 主要 when の効果は発動しない。
/// ⚠ Rust は 「効果無効」 を **付与するだけ** で発動時に見ていなかった。 OP06-083 オーズ
///   (「自分の《スリラーバーク海賊団》1枚をKOできる：このキャラは、 このターン中、 効果が無効に
///   なる」) は 1 回起動すると自分を無効化して以降発動しない = **公式の自己制限** だが、
///   Rust は無限に起動して自陣を KO し続けていた (2026-08-04、 once_per_turn 既定 True の
///   近似を外して初めて露出)。
fn src_effect_negated(state: &GameState, me_idx: usize, src: Slot, when: &str) -> bool {
    // 公式 「効果を無効にする」 に when の区別は無い = 発動する効果は全て抑止 (effects.py:_execute_event)。
    // ⚠ end_of_turn / opp_end_of_turn は 2026-08-08 追加 (cardqa_op_10、 OP10-112 キッド:
    //   ターン終了時まで無効化されたキャラの【自分のターン終了時】はエンドフェイズ内で
    //   まだ無効なため発動しない)。 opp_attack / on_block は 2026-08-04 追加分。
    if !matches!(
        when,
        "on_play" | "on_attack" | "activate_main" | "main" | "counter"
            | "opp_attack" | "on_block" | "end_of_turn" | "opp_end_of_turn"
    ) {
        return false;
    }
    match src_ip(&state.players[me_idx], src) {
        Some(ip) => {
            ip.granted_keywords.contains("効果無効")
                || ip.static_granted_keywords.contains("効果無効")
                || ip.effect_disabled_through_opp_turn
        }
        None => false,
    }
}

/// effects.py:_optional_cost_payable_in_do = `do` の optional_cost_then に書かれたコストが
/// 払えるか (起動メインの列挙用)。 overlay は 「X することができる：Y」 を top-level `cost` では
/// なく do 内の optional_cost_then で表すことが多く、 列挙時に見ないと 「払えないのに legal」 に
/// なる (EB02-009 サウザンド・サニー号がレスト済でも延々と再起動していた、 2026-08-04)。
/// ⚠ 判定できるものだけ見る (未知コストは true = 従来通り列挙)。
fn optional_cost_payable_in_do(state: &GameState, me_idx: usize, ip: &InPlay, eff: &Value) -> bool {
    let me = &state.players[me_idx];
    let Some(dos) = eff.get("do").and_then(|v| v.as_array()) else { return true };
    for prim in dos {
        let Some(oct) = prim.get("optional_cost_then") else { continue };
        let Some(costs) = oct.get("cost").and_then(|v| v.as_array()) else { continue };
        for cs in costs {
            if cs.get("rest_self").and_then(|v| v.as_bool()) == Some(true) && ip.rested {
                return false;
            }
            if cs.get("rest").and_then(|v| v.as_str()) == Some("self") && ip.rested {
                return false;
            }
            if let Some(n) = cs.get("rest_self_don").and_then(|v| v.as_i64()) {
                if (me.don_active as i64) < n {
                    return false;
                }
            }
            if let Some(n) = cs.get("pay_don").and_then(|v| v.as_i64()) {
                if ((me.don_active + me.don_rested) as i64) < n {
                    return false;
                }
            }
            if let Some(n) = cs.get("discard_hand").and_then(|v| v.as_i64()) {
                if (me.hand.len() as i64) < n {
                    return false;
                }
            }
            // 「相手のキャラ1枚に相手の(レストの)ドンN枚を付与できる：」 (OP15-003 アルビダ 等)。
            // ⚠ 公式 (cardqa_op_15): 相手キャラ0枚 / 相手レストドン0 なら **発動できない**。
            //   この key を見ていなかったため 発動でき、 何も起きないまま【ターン1回】だけ消費して
            //   いた (2026-08-11 に Python と同時に是正)。
            if let Some(av) = cs.get("attach_opp_don_to_opp_chara") {
                let opp = &state.players[1 - me_idx];
                let n = if av.is_object() {
                    av.get("count").and_then(|x| x.as_i64()).unwrap_or(1) as i32
                } else {
                    av.as_i64().unwrap_or(1) as i32
                };
                let from_cost = av.get("from_cost_area").and_then(|x| x.as_bool()).unwrap_or(false);
                let avail = opp.don_rested + if from_cost { opp.don_active } else { 0 };
                if opp.characters.is_empty() || avail < n {
                    return false;
                }
            }
            // 資源が尽きたら払えない型 (effects.py:_optional_cost_payable_in_do と同条件)
            if let Some(n) = cs.get("trash_self_hand_random").and_then(|v| v.as_i64()) {
                if (me.hand.len() as i64) < n {
                    return false;
                }
            }
            for k in ["self_hand_to_deck_bottom", "hand_to_deck_bottom"] {
                if let Some(v) = cs.get(k) {
                    let n = v.get("amount").and_then(|x| x.as_i64())
                        .or_else(|| v.as_i64()).unwrap_or(1);
                    if (me.hand.len() as i64) < n {
                        return false;
                    }
                }
            }
            if let Some(v) = cs.get("trash_to_deck") {
                let n = v.get("limit").and_then(|x| x.as_i64())
                    .or_else(|| v.get("count").and_then(|x| x.as_i64()))
                    .or_else(|| v.as_i64()).unwrap_or(1);
                if (me.trash.len() as i64) < n {
                    return false;
                }
            }
            for k in ["life_to_hand", "life_top_or_bottom_to_hand", "mill_self_life_to_trash"] {
                if let Some(v) = cs.get(k) {
                    let n = v.get("amount").and_then(|x| x.as_i64())
                        .or_else(|| v.as_i64()).unwrap_or(1);
                    if (me.life.len() as i64) < n {
                        return false;
                    }
                }
            }
            if (cs.get("flip_life_face_up").is_some() || cs.get("flip_life_face_down").is_some())
                && me.life.is_empty()
            {
                return false;
            }
            if let Some(n) = cs.get("return_self_don_to_deck").and_then(|v| v.as_i64()) {
                if ((me.don_active + me.don_rested) as i64) < n {
                    return false;
                }
            }
        }
    }
    true
}

/// effects.py:_activate_main_is_noop = 起動メインが 「実行しても状態が変わらない」 と静的に
/// 分かるか (探索のループ防止用)。 ⚠ 条件を足すのは 「no-op が確実」 な場合だけ。 迷ったら false。
fn activate_main_is_noop(state: &GameState, me_idx: usize, ip: &InPlay, eff: &Value) -> bool {
    let Some(do_list) = eff.get("do").and_then(|v| v.as_array()) else { return true };
    if do_list.is_empty() {
        return true;
    }
    // 「ドン‼をアクティブにする」 が自己ロック済 → untap_don も block も no-op
    if state.players[me_idx].block_chara_effect_untap_don_until_turn_end
        && ip.card.category == crate::state::Category::Character
        && do_list.iter().all(|p| {
            p.as_object().map_or(false, |o| {
                o.keys().all(|k| k == "untap_don" || k == "block_chara_effect_untap_don_turn")
            })
        })
    {
        return true;
    }
    false
}

/// effects.py:_can_pay_activate_cost = activate_main の cost を支払えるか。
fn can_pay_activate_cost(state: &GameState, me_idx: usize, ip: &InPlay, on_field: bool, cost: &Value) -> bool {
    let me = &state.players[me_idx];
    let Some(o) = cost.as_object() else { return true };
    let gi = |k: &str| o.get(k).and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    let gb = |k: &str| o.get(k).and_then(|v| v.as_bool()).unwrap_or(false);
    // 公式: 「レストにできない」 は レストを要するコストの支払いもできなくする
    // (effects.py:_can_pay_activate_cost と対、 2026-08-04 是正)。
    if gb("rest_self") && (ip.rested || ip.cannot_be_rested_buff || ip.static_cannot_be_rested) {
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
    // 「自分のライフN枚を手札に加えることができる：」 (OP01-013 サンジ)。 ライフ不足なら発動不可
    // (= do に置くと 「ライフ0でもタダ撃ち」 になる。 2026-08-11 に Python と同時に新設)。
    if gi("life_to_hand") > 0 && (me.life.len() as i32) < gi("life_to_hand") {
        return false;
    }
    if gb("return_self_to_hand") && !on_field {
        return false;
    }
    // rest_self_target_name / rest_self_target = 「自分の『X』1枚をレストにできる：」
    // (effects.py:8697)。 自場 (キャラ+ステージ) に 同名のアクティブが 1 枚以上 必要。
    for key in ["rest_self_target_name", "rest_self_target"] {
        if let Some(spec) = o.get(key) {
            let want = spec.get("name").and_then(|v| v.as_str())
                .or_else(|| spec.as_str()).unwrap_or("");
            let found = me.characters.iter().chain(me.stages.iter())
                .any(|x| x.card.name == want && !x.rested);
            if !found {
                return false;
            }
        }
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
        if !me.characters.iter().any(|c| matches_filter_ip(&c, Some(kf))) {
            return false;
        }
    }
    // rest_self_target_name / rest_self_target: name 一致 + アクティブが 1 枚以上必要
    if let Some(rn) = o.get("rest_self_target_name").or_else(|| o.get("rest_self_target")) {
        let name = rn.get("name").and_then(|v| v.as_str()).or_else(|| rn.as_str()).unwrap_or("");
        let ok = me.characters.iter().chain(me.stages.iter())
            .any(|ip| name_matches(&ip.card, name) && !ip.rested);
        if !ok {
            return false;
        }
    }
    // rest_own_card: filter 一致のアクティブな自カード (leader/char/stage) が count 枚以上必要
    if let Some(ro) = o.get("rest_own_card") {
        let n = ro.get("count").and_then(|v| v.as_i64()).unwrap_or(1) as usize;
        let ro_filt = ro.get("filter");
        let pool = std::iter::once(&me.leader).chain(me.characters.iter()).chain(me.stages.iter())
            .filter(|ip| !ip.rested && matches_filter_ip(&ip, ro_filt))
            .count();
        if pool < n {
            return false;
        }
    }
    // once_per_turn ゲート: **明示指定時のみ** 発動済なら払えない (effects.py と一致)。
    // 既定 True の近似は 2026-08-04 撤去 (公式は払える限り何度でも)。
    let once = o.get("once_per_turn").and_then(|v| v.as_bool()).unwrap_or(false);
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
    // 「アタックする際 手札 N 枚を捨てなければアタックできない」(OP08-043) で手札不足の攻撃者は
    // **そもそもアタックできない** ので候補に出さない。 出すと state 不変の手を方策が選び続けて
    // 無限ループする (Python は no-op 早期 return なので候補に残る)。
    let hand_n = me.hand.len() as i32;
    let can_pay_attack_cost = |ip: &InPlay| -> bool {
        ip.attack_cost_discard_hand_n <= 0 || hand_n >= ip.attack_cost_discard_hand_n
    };
    if can_battle {
        // attacker 候補 (kind, idx) と、 速攻:キャラ 専用 (chara_only)
        let mut attackers: Vec<(String, usize)> = vec![];
        let mut chara_only: Vec<usize> = vec![];
        let l = &me.leader;
        if !l.rested
            && can_pay_attack_cost(l)
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
                || !can_pay_attack_cost(ch)
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
                // 発動元が 「効果無効」 なら実行しても何も起きない (effects.py の gate)。
                if src_effect_negated(state, me_idx, slot, "activate_main") {
                    continue;
                }
                // 探索のループ防止 (ルール上の制限ではない、 effects.py:_activate_main_is_noop と同条件)。
                // 【ターン1回】 の無い起動メインは公式上何度でも起動できるが、 効果が完全な no-op に
                // なったものを出し続けると探索が同じ手を無限に選べる。 現状の該当は
                // 「ドン‼アクティブ + 自己ロック」 (EB04-016 トリ / OP10-030 スモーカー) のみ。
                if activate_main_is_noop(state, me_idx, ip, eff) {
                    continue;
                }
                // do 内 optional_cost_then のコストが払えないなら legal ではない
                // (effects.py:_optional_cost_payable_in_do と同条件)。
                if !optional_cost_payable_in_do(state, me_idx, ip, eff) {
                    continue;
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
