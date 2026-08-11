//! Rust standalone setup_game (pre-mulligan 決定的コア)。
//!
//! Python game.py:setup_game の deterministic 部 (= _make_player[deck shuffle] → _place_life_and_draw)
//! を bit-match で再現。 mulligan (AI 判定) と game_start ステージ登場 (イム等、 稀) は R4/後段に委ね、
//! ここでは do_mulligan_and_finalize=False 相当の pre-mulligan 状態を構築する (= 差分検証可能)。
//!
//! 入力 deck JSON = {leader: CardDef, main: [CardDef], don_deck_size: int}。 rng は getstate keys。

use crate::rng::PyRandom;
use crate::state::{CardDef, GameState, InPlay, Phase, Player};
use serde_json::Value;

/// deck JSON から Player を構築し、 deck を Python 同一列で shuffle (_make_player 相当)。
fn make_player(deck: &Value, name: &str, rng: &mut PyRandom) -> Result<Player, String> {
    let leader_card: CardDef = serde_json::from_value(
        deck.get("leader").cloned().ok_or("deck.leader 無し")?,
    )
    .map_err(|e| format!("leader deserialize: {e}"))?;
    let main: Vec<CardDef> = serde_json::from_value(
        deck.get("main").cloned().ok_or("deck.main 無し")?,
    )
    .map_err(|e| format!("main deserialize: {e}"))?;
    let dds = deck.get("don_deck_size").and_then(|v| v.as_i64()).unwrap_or(10) as i32;
    // InPlay.of(leader, rested=false, sickness=false)
    let leader = InPlay::of(leader_card, false);
    let mut p = Player {
        name: name.to_string(),
        leader,
        deck: main,
        don_remaining_in_deck: dds,
        // Python Player dataclass の非 0 default (Rust Default=0 と差異があるもの)。
        block_chara_play_cost_ge_threshold: -1,
        ..Default::default()
    };
    // Python: p.shuffle_deck(rng) = rng.shuffle(self.deck)。 index 置換を deck に適用。
    let n = p.deck.len();
    let perm = rng.shuffle_perm(n);
    let old = std::mem::take(&mut p.deck);
    p.deck = perm.iter().map(|&j| old[j].clone()).collect();
    Ok(p)
}

/// pre-mulligan 状態を構築 (setup_game の do_mulligan_and_finalize=False 相当、 _recompute_static 前)。
/// rng 消費順 = shuffle(deck1) → shuffle(deck2) (first_player は明示前提 = randrange(2) 消費なし)。
pub fn setup_pre_mulligan(
    deck1: &Value,
    deck2: &Value,
    rng_state: &[u64],
    first_player: usize,
) -> Result<GameState, String> {
    let mut rng = PyRandom::from_state(rng_state).ok_or("rng_state 不正 (625 要素必須)")?;
    // Python: p1=_make_player(deck1) → p2=_make_player(deck2) の順で shuffle 消費。
    let p1 = make_player(deck1, "P0", &mut rng)?;
    let p2 = make_player(deck2, "P1", &mut rng)?;
    let mut players = if first_player == 0 {
        vec![p1, p2]
    } else {
        vec![p2, p1]
    };
    // Python: 並べ替え後に index で name を再設定 (players[0]=P0, [1]=P1)。
    players[0].name = "P0".to_string();
    players[1].name = "P1".to_string();
    let mut st = GameState {
        players,
        turn_player_idx: 0,
        turn_number: 1,
        phase: Phase::Refresh,
        // game_start ステージ登場が deck shuffle で rng を使うので、 ここで載せておく
        // (以後の rng 依存 effect もこれを継続使用する)。
        rng: Some(rng),
        ..Default::default()
    };
    // リーダーの【ゲーム開始時】ステージ登場 (game.py:_apply_game_start_stage_summons、 OP13-079 イム)。
    // 公式 FAQ: 先攻後攻決定後・最初の手札を準備する **前** = ライフ配置/ドローより先。 rng も
    // ここで shuffle を消費するので順序を守らないと以降の全ドローがズレる。
    apply_game_start_stage_summons(&mut st);
    // _place_life_and_draw: 各 player の deck 上から leader.life 枚を life へ、 その後 5 枚 draw。
    for p in st.players.iter_mut() {
        let life_n = p.leader.card.life;
        for _ in 0..life_n {
            if !p.deck.is_empty() {
                let c = p.deck.remove(0);
                p.life.push(c);
                p.life_face_up.push(false);  // 既定は裏向き
            }
        }
    }
    for p in st.players.iter_mut() {
        // Python p.draw(5): 手札 5 枚 + cards_drawn_count += 実ドロー数 (life 配置は draw 経由でない=不加算)。
        let mut drawn = 0;
        for _ in 0..5 {
            if !p.deck.is_empty() {
                let c = p.deck.remove(0);
                p.hand.push(c);
                drawn += 1;
            }
        }
        p.cards_drawn_count += drawn;
    }
    Ok(st)
}

/// リーダーの【ゲーム開始時】ステージ登場 (game.py:229 _apply_game_start_stage_summons)。
/// 対応 primitive = summon_stage_from_deck_with_feature。 AI 経路 = 該当ステージのうち **最高コスト**
/// (tie は deck 内で先に現れる方 = Python max の first-max 準拠) を 1 枚登場 → deck を shuffle。
/// 該当 0 枚なら何もしない (shuffle も無し = Python と同じ)。
fn apply_game_start_stage_summons(st: &mut GameState) {
    let Some(ov) = crate::effects::overlay() else { return };
    for pidx in 0..st.players.len() {
        let lid = st.players[pidx].leader.card.card_id.clone();
        let Some(effs) = ov.get(&lid) else { continue };
        // 対象 primitive の feature を先に集める (borrow 分離)
        let feats: Vec<String> = effs
            .iter()
            .filter(|e| e.get("when").and_then(|v| v.as_str()) == Some("game_start"))
            .filter_map(|e| e.get("do").and_then(|v| v.as_array()))
            .flatten()
            .filter_map(|prim| {
                prim.get("summon_stage_from_deck_with_feature")
                    .map(|v| v.as_str().unwrap_or("").to_string())
            })
            .filter(|f| !f.is_empty())
            .collect();
        for feat in feats {
            let p = &mut st.players[pidx];
            let qualifying: Vec<usize> = (0..p.deck.len())
                .filter(|&i| {
                    p.deck[i].category == crate::state::Category::Stage
                        && p.deck[i].features.iter().any(|f| *f == feat)
                })
                .collect();
            if qualifying.is_empty() {
                continue;
            }
            // Python max(key=cost) は tie で **最初** の要素を返す
            let mut best = qualifying[0];
            for &i in qualifying.iter().skip(1) {
                if p.deck[i].cost > p.deck[best].cost {
                    best = i;
                }
            }
            let card = p.deck.remove(best);
            p.stages.push(crate::state::InPlay::of(card, false));
            // p.shuffle_deck(rng) (公式: search 後はシャッフル)
            let n = p.deck.len();
            let perm = st.rng_mut().shuffle_perm(n);
            let old = std::mem::take(&mut st.players[pidx].deck);
            st.players[pidx].deck = perm.iter().map(|&j| old[j].clone()).collect();
        }
    }
}

/// マリガン判定 (game.py:_should_mulligan の 3 段)。 tier1 = deck の mulligan_keep_card_ids に
/// 手札が 1 枚でも該当すれば keep、 tier2 = imitation prior で優先度 0.5 以上の card_id 集合
/// (mulligan_prior_card_ids、 Python 側で db/imitation_patterns.json から算出して渡す) に該当なら keep、
/// tier3 = コスト 3 以下の CHARACTER が 0 枚なら引き直し。
fn should_mulligan(p: &crate::state::Player, keep: &[String], prior: &[String]) -> bool {
    if !keep.is_empty() {
        return !p.hand.iter().any(|c| keep.contains(&c.card_id));
    }
    if !prior.is_empty() && p.hand.iter().any(|c| prior.contains(&c.card_id)) {
        return false;
    }
    !p.hand
        .iter()
        .any(|c| c.category == crate::state::Category::Character && c.cost <= 3)
}

fn id_list(deck: &Value, key: &str) -> Vec<String> {
    deck.get(key)
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
        .unwrap_or_default()
}

/// マリガンを適用 (game.py:182 / finalize_setup_after_mulligan)。 players[0] → players[1] の順に
/// 判定し、 引き直しなら hand を deck へ戻して shuffle → 5 枚 draw (= Python の rng 消費順と同一)。
/// deck1/deck2 は setup に渡したものと同じ Value (mulligan_keep_card_ids / mulligan_prior_card_ids を読む)。
/// first_player で players と deck の対応が入れ替わることに注意 (players[0] は first_player 側)。
pub fn apply_mulligan(st: &mut GameState, deck1: &Value, deck2: &Value, first_player: usize) {
    // Python finalize_setup_after_mulligan は最後に _recompute_static (= ownership flags 更新を含む)
    // を呼ぶ。 Rust ネイティブ setup では誰も owner_idx を立てないので (-1 のまま) ここで揃える。
    crate::rules::update_ownership_flags(st);
    // players[0] = first_player==0 ? deck1 : deck2
    let decks: [&Value; 2] = if first_player == 0 { [deck1, deck2] } else { [deck2, deck1] };
    for i in 0..2 {
        let keep = id_list(decks[i], "mulligan_keep_card_ids");
        let prior = id_list(decks[i], "mulligan_prior_card_ids");
        if !should_mulligan(&st.players[i], &keep, &prior) {
            st.players[i].did_mulligan = false;
            continue;
        }
        // Python: deck.extend(hand) → hand=[] → shuffle_deck(rng) → draw(5)
        let hand = std::mem::take(&mut st.players[i].hand);
        st.players[i].deck.extend(hand);
        let n = st.players[i].deck.len();
        let perm = st.rng_mut().shuffle_perm(n);
        let old = std::mem::take(&mut st.players[i].deck);
        st.players[i].deck = perm.iter().map(|&j| old[j].clone()).collect();
        let mut drawn = 0;
        for _ in 0..5 {
            if st.players[i].deck.is_empty() {
                break;
            }
            let c = st.players[i].deck.remove(0);
            st.players[i].hand.push(c);
            drawn += 1;
        }
        st.players[i].cards_drawn_count += drawn;
        st.players[i].did_mulligan = true;
    }
}
