"""game corpus dump — methodology-independent raw game data persistence.

[[feedback_corpus_methodology]] / [[feedback_adversarial_entry_mining]] 由来 (= 2026-05-29 設計)。

設計 原則:
- raw observations を per-turn / per-action で 気前 良く dump (= card_id 込み)
- **両 side の decision を 等価 に 記録** (= adversarial entry mining 対応、 ai_class タグ 付き)
- methodology 変更 で 過去 game が 無駄 にならない (= 軸 追加 / target 追加 を 後 から 適用 可)

V1 scope (= 今 実装):
- per-game: deck info, ai versions, seed, winner, turns, reason
- per-turn: state_features (= 両 side の life/hand/don/field の card_id 込み 詳細)
- per-action: action repr + active player の ai_class

V2 scope (= 後 で 拡張):
- per-decision: candidate_actions + base_eval + bonus + chosen
- engine_state_snapshot (= picklable state、 counterfactual rollout 用)

出力 = JSON file per game: db/game_corpus/round_N/game_<seed>_<idx>.json
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ===========================================================================
# state snapshot (= 軸 設計 を 縛らない rich dump)
# ===========================================================================


def snapshot_player(p: Any, idx: int) -> dict:
    """Player の 全 状態 を dict 化。 card_id 込み で **気前 良く** dump。

    軸 追加 (= opp_pressure / opp_lethal_proximity 等) を 後 から できる ように、
    raw 数値 + card_id list を 同時 に 入れる。

    **oracle 方針** (= 2026-05-29、 [[feedback_corpus_methodology]] 拡張):
    学習 時 corpus は 隠匿 情報 (= 手札 全部、 life 中身) も 公開 する (= AlphaStar / Pluribus 路線)。
    推論 時 は 公開 情報 のみ で belief 推定 する 設計 (= 既存 hand_estimator)。
    つまり:
      - "hand_card_ids" = oracle (= 学習 用 ground truth)
      - "known_hand_card_ids" = 公開 履歴 のみ (= 推論 時 入力)
      - "life_card_ids" = oracle (= 学習 用)、 推論 時 は count + scry 既知 のみ 使う
    """
    return {
        "idx": idx,
        "name": p.name,
        "leader": {
            "card_id": p.leader.card.card_id,
            "power": p.leader.power,
            "rested": p.leader.rested,
            "attached_dons": p.leader.attached_dons,
        },
        "life_count": len(p.life),
        "life_card_ids": [c.card_id for c in p.life],  # oracle (= 学習 用)
        "hand_count": len(p.hand),
        "hand_card_ids": [c.card_id for c in p.hand],  # oracle (= 学習 用)
        "known_hand_card_ids": list(p.known_hand_card_ids),  # 公開 履歴 (= 推論 時 入力)
        "deck_top5_card_ids": [c.card_id for c in p.deck[:5]],  # oracle (= 「次 何 引く か」 軸 用)
        # マリガン 履歴 (= 公開 情報、 belief 推定 軸 用)
        "did_mulligan": bool(getattr(p, "did_mulligan", False)),
        "deck_count": len(p.deck),
        "trash_count": len(p.trash),
        "trash_card_ids": [c.card_id for c in p.trash],
        "don_active": p.don_active,
        "don_rested": p.don_rested,
        "don_remaining_in_deck": p.don_remaining_in_deck,
        "field_count": len(p.characters),
        "field": [
            {
                "card_id": ip.card.card_id,
                "card_name": ip.card.name,
                "cost": ip.card.cost,
                "power": ip.power,
                "rested": ip.rested,
                "attached_dons": ip.attached_dons,
                "summoning_sickness": ip.summoning_sickness,
                "is_blocker_now": bool(getattr(ip, "is_blocker_now", False)),
                "is_rush_now": bool(getattr(ip, "is_rush_now", False)),
                "granted_keywords": list(getattr(ip, "granted_keywords", set())),
            }
            for ip in p.characters
        ],
        "stages": [
            {"card_id": ip.card.card_id, "card_name": ip.card.name}
            for ip in p.stages
        ],
        # 派生 量 (= 軸 bucket 化 高速 化、 raw からも 再 計算 可 だが cache)
        "field_total_power": sum(ip.power for ip in p.characters),
        "field_active_count": sum(1 for ip in p.characters if not ip.rested),
        "field_rested_count": sum(1 for ip in p.characters if ip.rested),
        # ターン 跨ぎ buff / debuff フラグ (= 軸 設計 で 「効果 残り 影響」 を 入れる 用)
        "block_chara_play_until_turn_end": bool(getattr(p, "block_chara_play_until_turn_end", False)),
        "block_self_draw_until_turn_end": bool(getattr(p, "block_self_draw_until_turn_end", False)),
        "prevent_self_life_to_hand_until_turn_end": bool(
            getattr(p, "prevent_self_life_to_hand_until_turn_end", False)
        ),
    }


def snapshot_state(state: Any) -> dict:
    """GameState の dump。 active_player + phase + both players + 直近 effect 履歴。"""
    return {
        "turn_number": state.turn_number,
        "active_player": state.turn_player_idx,
        "phase": str(state.phase),
        "players": [snapshot_player(p, idx) for idx, p in enumerate(state.players)],
        # 直近 effect events (= 「opp が 前 turn で X 効果 発動」 系 軸 用)。
        # state._effect_events に 試合 開始 から の 全 log が 蓄積 されて る。
        # corpus dump 時 は 末尾 20 件 を 抜き出す (= 直近 文脈 で 充分、 全 dump は 容量 過大)。
        "recent_effect_events": list(getattr(state, "_effect_events", []) or [])[-20:],
        # turn 全体 の 通算 effect 数 (= 「opp は この 試合 で 既に X 回 効果 発動」 軸 用)
        "total_effect_events_count": len(getattr(state, "_effect_events", []) or []),
    }


# ===========================================================================
# action snapshot (= adversarial entry mining 用、 action の identity を 残す)
# ===========================================================================


def snapshot_action(action: Any, state: Any = None) -> dict:
    """Action の dump。 kind + dataclass field 全て + (state 渡せば) hand_idx → card_id 解決。

    state を 渡すと PlayCharacter/PlayEvent/PlayStage の hand_idx を card_id に 変換 して
    "card_id" key で 同 dump (= 学習 時 に PlayCharacter どの card か 区別 可能)。

    AttachDonToCharacter / ActivateMain / Attack* の *_iid も InPlay → card_id 解決。
    """
    d: dict[str, Any] = {"kind": action.__class__.__name__}
    # 実際 の Action dataclass field を 列挙 (= engine/game.py の class 定義 と 一致)
    for attr in (
        "hand_idx",
        "sacrifice_iid",
        "target_iid",
        "attacker_iid",
        "blocker_iid",
        "counter_card_idxs",
        "counter_event_idxs",
        "source_iid",
        "effect_index",
        "n",
    ):
        val = getattr(action, attr, None)
        if val is not None and not callable(val):
            if isinstance(val, tuple):
                val = list(val)
            d[attr] = val

    # card_id 解決 (= state 渡された 場合 のみ、 学習 で 「どの card か」 区別 用)
    if state is not None:
        try:
            active_p = state.players[state.turn_player_idx]
            opp_p = state.players[1 - state.turn_player_idx]
            # PlayCharacter / PlayEvent / PlayStage: hand_idx → card_id
            hand_idx = getattr(action, "hand_idx", None)
            if hand_idx is not None and 0 <= hand_idx < len(active_p.hand):
                d["card_id"] = active_p.hand[hand_idx].card.card_id
            # attacker_iid → card_id (= 自陣)
            attacker_iid = getattr(action, "attacker_iid", None)
            if attacker_iid is not None:
                if active_p.leader.instance_id == attacker_iid:
                    d["attacker_card_id"] = active_p.leader.card.card_id
                else:
                    for ip in active_p.characters:
                        if ip.instance_id == attacker_iid:
                            d["attacker_card_id"] = ip.card.card_id
                            break
            # target_iid / sacrifice_iid → card_id (= 相手 場 or 自陣 場)
            for iid_attr, label in (("target_iid", "target_card_id"),
                                     ("sacrifice_iid", "sacrifice_card_id")):
                iid = getattr(action, iid_attr, None)
                if iid is None:
                    continue
                # 自陣 + 相手 場 両方 search
                for p in (active_p, opp_p):
                    if p.leader.instance_id == iid:
                        d[label] = p.leader.card.card_id
                        break
                    found = False
                    for ip in p.characters:
                        if ip.instance_id == iid:
                            d[label] = ip.card.card_id
                            found = True
                            break
                    if found:
                        break
            # source_iid (ActivateMain) → card_id
            source_iid = getattr(action, "source_iid", None)
            if source_iid is not None:
                if active_p.leader.instance_id == source_iid:
                    d["source_card_id"] = active_p.leader.card.card_id
                else:
                    for ip in active_p.characters:
                        if ip.instance_id == source_iid:
                            d["source_card_id"] = ip.card.card_id
                            break
        except Exception:
            pass  # 解決 失敗 は silent (= corpus 主目的 = 軸 dump、 card_id は + α)

    return d


# ===========================================================================
# corpus builder (= 1 試合 単位 で 構築 → finalize → JSON 出力)
# ===========================================================================


@dataclass
class GameCorpusBuilder:
    """1 試合 分 の corpus を 蓄積 して JSON dict を 返す。

    使い方:
        corpus = GameCorpusBuilder(deck_a_slug, deck_b_slug, seed, first_player,
                                    ai_a_class, ai_b_class, spec_versions)
        # 各 action 前 に:
        corpus.record_action(state_before, action, ai_class_active_player)
        # game 終了 後:
        corpus.finalize(winner_for_deck_a, turns, reason)
        json.dump(corpus.to_dict(), open(path, "w"), ensure_ascii=False)
    """

    deck_a_slug: str
    deck_b_slug: str
    seed: int
    first_player: int  # 0 = deck_a 先攻、 1 = deck_b 先攻
    ai_a_class: str
    ai_b_class: str
    spec_versions: dict = field(default_factory=dict)
    behavior_policy: str = "default"  # "default" / "uniform_priority" / "epsilon_greedy" 等
    actions: list[dict] = field(default_factory=list)
    result: Optional[dict] = None

    def record_action_with_snap(
        self, state_before_snap: dict, action: Any, ai_class: str,
        state: Any = None,
    ) -> None:
        """事前 snapshot 済 state + 選択 action を 記録 (= harness 高速 path)。

        state_before_snap は snapshot_state(state) を play_one_action 前 に 呼んだ 結果。
        state を 渡せば action snapshot に hand_idx → card_id 解決 が 入る。
        """
        self.actions.append({
            "turn_number": state_before_snap.get("turn_number", -1),
            "active_player": state_before_snap.get("active_player", -1),
            "phase": state_before_snap.get("phase", ""),
            "ai_class": ai_class,
            "state_before": state_before_snap,
            "action": snapshot_action(action, state=state),
        })

    def record_action(self, state: Any, action: Any, ai_class: str) -> None:
        """action 適用 **前** の state + 選択 された action を 記録 (= 簡易 path)。"""
        self.record_action_with_snap(snapshot_state(state), action, ai_class)

    def finalize(self, winner_for_deck_a: int, turns: int, reason: str = "") -> None:
        """game 終了 時 に 呼ぶ。 winner_for_deck_a = 0 (= deck_a 勝ち) / 1 (= deck_b) / -1 (= draw)。"""
        self.result = {
            "winner_for_deck_a": winner_for_deck_a,
            "turns": turns,
            "reason": reason,
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "deck_a_slug": self.deck_a_slug,
            "deck_b_slug": self.deck_b_slug,
            "seed": self.seed,
            "first_player": self.first_player,
            "ai_versions": {
                "a": {"class": self.ai_a_class},
                "b": {"class": self.ai_b_class},
            },
            "spec_versions": self.spec_versions,
            "behavior_policy": self.behavior_policy,
            "actions": self.actions,
            "result": self.result,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )


# ===========================================================================
# convenience: corpus 読み込み (= mining / 学習 script で 使う)
# ===========================================================================


def load_corpus_dir(corpus_dir: Path) -> list[dict]:
    """corpus dir 内 の 全 game JSON を ロード。"""
    games = []
    for p in sorted(corpus_dir.glob("game_*.json")):
        games.append(json.loads(p.read_text(encoding="utf-8")))
    return games


def iter_corpus_actions(corpus_dir: Path):
    """各 game の 各 action を flatten で iterate (= mining 高速 化)。

    yields: (game_meta, action_record)
    """
    for p in sorted(corpus_dir.glob("game_*.json")):
        game = json.loads(p.read_text(encoding="utf-8"))
        meta = {k: v for k, v in game.items() if k != "actions"}
        for a in game.get("actions", []):
            yield meta, a
