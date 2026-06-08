"""ローカル LLM (Ollama) を相手プレイヤーにする AI。

GreedyAI を継承し、 choose_action を Ollama HTTP API 経由で LLM に委ねる。
盤面と「番号付き合法手」をカード名・効果込みでテキスト化して LLM に渡し、
最善手の番号を 1 つ選ばせる方式 (= 盤面を完璧に理解させる必要がない)。

LLM が落ちた / タイムアウト / 不正応答なら GreedyAI に degrade する
(= super().choose_action、 対戦が止まらない)。 これにより Ollama が
未起動でも対戦自体は成立する (ただしその場合は Greedy で打つ)。

v1 は攻め / 展開 (choose_action) のみ LLM 化。 防御 (choose_defense) は
GreedyAI を継承したまま (= まず動かす)。 防御も LLM 化したくなったら
choose_defense を override する。

env:
  ONEPIECE_LLM_MODEL   使用モデル (既定 "qwen2.5:7b-instruct")
  OLLAMA_HOST          Ollama host (既定 "http://localhost:11434")
  ONEPIECE_LLM_TIMEOUT 1 手の timeout 秒 (既定 60)
  ONEPIECE_LLM_VERBOSE 1 で prompt 要約 / 応答 / fallback を stderr に出す
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Optional

from .ai import GreedyAI
from .core import GameState, Player
from .game import (
    Action,
    ActivateMain,
    AttachDonToCharacter,
    AttachDonToLeader,
    AttackCharacter,
    AttackLeader,
    EndPhase,
    PlayCharacter,
    PlayEvent,
    PlayStage,
    legal_actions,
)


def _short(t: str, limit: int = 80) -> str:
    """効果テキストを 1 行 + 上限文字数に圧縮 (= prompt を膨らませない)。"""
    t = (t or "").replace("\n", " ").strip()
    return t if len(t) <= limit else t[:limit] + "…"


def _cat(c) -> str:
    cat = getattr(c, "category", "")
    return getattr(cat, "value", str(cat))


class LLMPlayerAI(GreedyAI):
    def __init__(
        self,
        rng=None,
        deck_analysis=None,
        model: Optional[str] = None,
        host: Optional[str] = None,
        timeout: Optional[float] = None,
        **_kw,  # deck_slug 等を factory が渡しても無視 (= 互換)
    ):
        super().__init__(rng=rng, deck_analysis=deck_analysis)
        self.model = model or os.environ.get("ONEPIECE_LLM_MODEL", "qwen2.5:7b-instruct")
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.timeout = float(timeout or os.environ.get("ONEPIECE_LLM_TIMEOUT", "60"))
        self.verbose = os.environ.get("ONEPIECE_LLM_VERBOSE") == "1"
        self.spec_version = f"llm:{self.model}"
        # 軽い自己診断用カウンタ (= 何手 LLM が選び、 何手 Greedy に落ちたか)
        self.llm_calls = 0
        self.llm_fallbacks = 0

    # ----------------------------------------------------------------- #
    # choose_action: LLM に番号を選ばせる。 失敗時は GreedyAI に degrade。
    # ----------------------------------------------------------------- #
    def choose_action(self, state: GameState) -> Action:
        actions = legal_actions(state)
        if not actions:
            return EndPhase()
        if len(actions) == 1:
            # 自明手 (= EndPhase のみ等) は LLM を呼ばず即決 (= 速度)
            return actions[0]
        prompt = self._render_action_prompt(state, actions)
        idx = self._ask_llm_index(prompt, n=len(actions))
        if idx is None:
            self.llm_fallbacks += 1
            return super().choose_action(state)
        return actions[idx]

    # ----------------------------------------------------------------- #
    # rendering
    # ----------------------------------------------------------------- #
    def _render_action_prompt(self, state: GameState, actions) -> str:
        me = state.turn_player
        opp = state.opponent
        lines = [
            "あなたはワンピースカードゲーム (OPTCG) を対戦中の上級プレイヤーです。",
            "いまはあなたのメインフェイズ。 盤面を読み、 勝ちに最も近づく 1 手を選びます。",
            "原則: 不利な交換は避ける / リーダー有利時はライフを詰める / "
            "ブロッカーや除去を有効に使う / DON は無駄打ちしない。",
            "",
            self._render_side("【あなた】", me, hidden_hand=False),
            self._render_side("【相手】", opp, hidden_hand=True),
            "",
            "選べる手 (この中から番号で 1 つ選ぶ):",
        ]
        for i, a in enumerate(actions):
            lines.append(f"  {i}: {self._describe_action(a, state)}")
        lines += [
            "",
            "最善手を 1 つ選び、 JSON だけで答えてください。 説明文は不要です。",
            '形式: {"action": <番号>, "why": "<20字以内の理由>"}',
        ]
        return "\n".join(lines)

    def _render_side(self, title: str, p: Player, hidden_hand: bool) -> str:
        ldr = p.leader
        out = [
            title,
            f"  リーダー: {ldr.card.name} Power{ldr.power} / ライフ{len(p.life)}枚 / "
            f"使用可能DON{p.don_active}(レスト{getattr(p, 'don_rested', 0)})",
        ]
        if p.characters:
            out.append("  キャラ場:")
            for c in p.characters:
                tags = ["レスト"] if c.rested else ["アクティブ"]
                if c.is_blocker_now:
                    tags.append("ブロッカー")
                if c.summoning_sickness and not c.rested:
                    tags.append("召喚酔い")
                eff = f" 効果:{_short(c.card.text)}" if c.card.text else ""
                out.append(
                    f"    - iid{c.instance_id} {c.card.name} "
                    f"Power{c.power}/cost{c.card.cost} [{','.join(tags)}]{eff}"
                )
        else:
            out.append("  キャラ場: なし")
        if hidden_hand:
            out.append(f"  手札: {len(p.hand)}枚 (非公開)")
        else:
            out.append("  手札:")
            for i, c in enumerate(p.hand):
                cv = f" counter{c.counter}" if c.counter else ""
                eff = f" 効果:{_short(c.text)}" if c.text else ""
                out.append(
                    f"    - hand[{i}] {c.name} cost{c.cost}/power{c.power}{cv} "
                    f"<{_cat(c)}>{eff}"
                )
        return "\n".join(out)

    def _find_inplay(self, state: GameState, iid):
        for p in state.players:
            for ip in [p.leader, *p.characters, *p.stages]:
                if ip.instance_id == iid:
                    return ip
        return None

    def _describe_action(self, a: Action, state: GameState) -> str:
        me = state.turn_player
        if isinstance(a, PlayCharacter):
            c = me.hand[a.hand_idx]
            sac = getattr(a, "sacrifice_iid", None)
            tail = f" (場のiid{sac}と差し替え)" if sac else ""
            return f"キャラ登場: {c.name} cost{c.cost}/power{c.power}{tail}"
        if isinstance(a, PlayEvent):
            c = me.hand[a.hand_idx]
            return f"イベント発動: {c.name} cost{c.cost} 効果:{_short(c.text, 60)}"
        if isinstance(a, PlayStage):
            c = me.hand[a.hand_idx]
            return f"ステージ設置: {c.name} cost{c.cost}"
        if isinstance(a, AttachDonToLeader):
            n = getattr(a, "n", 1)
            return f"DON+{n} → 自リーダー (パワー+{1000 * n})"
        if isinstance(a, AttachDonToCharacter):
            ip = self._find_inplay(state, a.target_iid)
            nm = ip.card.name if ip else f"iid{a.target_iid}"
            n = getattr(a, "n", 1)
            return f"DON+{n} → 自キャラ {nm} (パワー+{1000 * n})"
        if isinstance(a, AttackLeader):
            ip = self._find_inplay(state, a.attacker_iid)
            nm = ip.card.name if ip else f"iid{a.attacker_iid}"
            pw = ip.power if ip else "?"
            return f"アタック: {nm}(Power{pw}) → 相手リーダー"
        if isinstance(a, AttackCharacter):
            at = self._find_inplay(state, a.attacker_iid)
            tg = self._find_inplay(state, a.target_iid)
            an = at.card.name if at else f"iid{a.attacker_iid}"
            ap = at.power if at else "?"
            tn = tg.card.name if tg else f"iid{a.target_iid}"
            tp = tg.power if tg else "?"
            return f"アタック: {an}(Power{ap}) → 相手キャラ {tn}(Power{tp})"
        if isinstance(a, ActivateMain):
            ip = self._find_inplay(state, a.source_iid)
            nm = ip.card.name if ip else f"iid{a.source_iid}"
            eff = _short(ip.card.text, 60) if ip else ""
            return f"起動メイン: {nm} の効果{a.effect_index} 効果:{eff}"
        if isinstance(a, EndPhase):
            return "ターン終了 (これ以上は動かない)"
        return type(a).__name__

    # ----------------------------------------------------------------- #
    # Ollama call
    # ----------------------------------------------------------------- #
    def _ask_llm_index(self, prompt: str, n: int) -> Optional[int]:
        import requests

        self.llm_calls += 1
        try:
            r = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2, "num_predict": 128},
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            content = r.json().get("message", {}).get("content", "")
        except Exception as e:  # noqa: BLE001 (LLM はベストエフォート)
            if self.verbose:
                print(f"[LLM] call failed -> Greedy fallback: {e}", file=sys.stderr)
            return None
        idx = self._parse_index(content, n)
        if self.verbose:
            print(f"[LLM] {_short(content, 120)} -> idx={idx}", file=sys.stderr)
        return idx

    @staticmethod
    def _parse_index(content: str, n: int) -> Optional[int]:
        if not content:
            return None
        # 1) JSON として {"action": N}
        try:
            obj = json.loads(content)
            if isinstance(obj, dict) and "action" in obj:
                v = int(obj["action"])
                if 0 <= v < n:
                    return v
        except Exception:
            pass
        # 2) "action": N を正規表現で
        m = re.search(r'"action"\s*:\s*(\d+)', content)
        if m:
            v = int(m.group(1))
            if 0 <= v < n:
                return v
        # 3) 最初に出てくる範囲内の整数
        for m in re.finditer(r"\d+", content):
            v = int(m.group(0))
            if 0 <= v < n:
                return v
        return None
