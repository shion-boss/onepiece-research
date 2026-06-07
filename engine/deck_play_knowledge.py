"""デッキプレイ知識: DSL からデッキ内コンボ + 各カードの有効な使い方を導出し、
対戦 AI が実行時に参照する (= 仕様 docs/DECK_PLAY_KNOWLEDGE.md)。

- build_knowledge(deck, overlay) → 知識 dict (= scripts/build_deck_knowledge.py が JSON 化)
- DeckKnowledge: 知識をラップし、 対戦時の候補手スコア調整を提供
    - play_timing_adjustment(card_id, state, me_idx): 各カードの有効な使い方による加点/温存
    - combo_bonus(card_id, state, me_idx): 準備完了コンボの前進への加点

固定プランは作らない (= プライア)。 条件 live 判定は engine の eval_all_conditions で厳密に行う。
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

_DK_DEPLOY: Optional[dict] = None


def deck_knowledge_weight(deck_slug: Optional[str]) -> float:
    """deck別の deck-knowledge 重み W。 解決順: env override > db/deck_knowledge_deploy.json > 0。

    配備 AI は deck_slug から自分の W を引く (= 効くデッキだけ ON、 deploy_results と同型)。
    env ONEPIECE_DECK_KNOWLEDGE_W は A/B 用の global override。"""
    env = os.environ.get("ONEPIECE_DECK_KNOWLEDGE_W")
    if env not in (None, ""):
        try:
            return float(env)
        except ValueError:
            pass
    global _DK_DEPLOY
    if _DK_DEPLOY is None:
        try:
            p = Path(__file__).resolve().parents[1] / "db" / "deck_knowledge_deploy.json"
            _DK_DEPLOY = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except Exception:
            _DK_DEPLOY = {}
    if not deck_slug:
        return 0.0
    try:
        return float(_DK_DEPLOY.get(deck_slug, 0) or 0)
    except (ValueError, TypeError):
        return 0.0

PROD_HAND = {"search_top_n", "search", "reveal_top_play", "reveal_top_then", "draw",
             "draw_per_self_hand_discarded"}
PROD_ATTACH = {"attach_rested_don", "attach_don", "attach_active_don"}
PROD_RAMP = {"add_don", "add_rested_don"}
PROD_LIFE = {"put_top_to_life", "hand_to_self_life"}
PROD_KEYWORD = {"give_keyword", "give_rush", "give_attack_active_chara"}
PROD_TRASH = {"trash_self_hand_random"}
PROD_BOARD = {"play_from_hand", "play_from_trash", "summon_from_deck", "play_self",
              "play_from_hand_named", "play_from_hand_or_trash"}
PROD_COSTRED = {"set_base_cost", "set_base_cost_timed"}
REMOVAL = {"ko", "ko_multi", "ko_all_others", "return_to_hand", "return_to_hand_multi",
           "return_to_deck_bottom", "return_to_deck_bottom_multi", "chara_to_self_life",
           "chara_to_opp_life"}
# 温存判断の対象になる「価値ある条件付き効果」 の value_class
VALUABLE = {"recovery", "removal", "draw", "summon", "pump", "search"}
# 効果が「登場/プレイ時点」 に判定される when (= 出すタイミングが効く)
PLAY_WHEN = {"on_play", "on_attack", "activate_main"}


def _effs(overlay, card) -> list:
    """overlay は raw json dict ({cid: [eff]}) と load_effect_overlay 結果
    ({cid: CardEffectBundle}) の双方を受ける。 後者は .effects が list。"""
    b = overlay.get(card.card_id) if overlay else None
    if b is None:
        return []
    effs = getattr(b, "effects", b)
    return [e for e in (effs or []) if isinstance(e, dict)]


def _do_keys(eff: dict) -> list:
    out = []
    for d in eff.get("do") or []:
        if isinstance(d, dict):
            out += list(d.keys())
    return out


def _flatten_if(iff) -> list:
    out = []
    if isinstance(iff, dict):
        for k, v in iff.items():
            if k in ("or", "and", "not", "any", "all"):
                for s in (v if isinstance(v, list) else [v]):
                    out += _flatten_if(s)
            else:
                out.append((k, v))
    elif isinstance(iff, list):
        for s in iff:
            out += _flatten_if(s)
    return out


def _cost_keys(cost) -> set:
    out: set = set()
    for ci in ([cost] if isinstance(cost, dict) else (cost if isinstance(cost, list) else [])):
        if isinstance(ci, dict):
            out |= set(ci.keys())
    return out


def _value_class(keys: set) -> str:
    if keys & PROD_LIFE:
        return "recovery"
    if keys & REMOVAL:
        return "removal"
    if any(k.startswith("draw") for k in keys):
        return "draw"
    if any(k.startswith("power_pump") or k.startswith("set_base_power") for k in keys):
        return "pump"
    if keys & {"search_top_n", "search", "reveal_top_play", "reveal_top_then"}:
        return "search"
    if keys & PROD_RAMP:
        return "ramp"
    if keys & PROD_ATTACH:
        return "attach_don"
    if keys & {"play_from_hand", "summon_from_deck", "play_from_trash", "play_self"}:
        return "summon"
    if keys & {"give_keyword", "give_rush"}:
        return "keyword"
    if any(k.startswith("reduce_play_cost") for k in keys) or keys & PROD_COSTRED:
        return "cost_reduction"
    return next(iter(keys), "—") if keys else "—"


def _reachable(if_keys: set) -> bool:
    """条件が「将来満たされやすい」 = 温存する価値がある。"""
    return bool(if_keys & {
        "self_life_le", "trash_count_ge", "self_trash_count_ge",
        "self_don_ge", "self_attached_don_ge", "opp_life_ge",
        "self_chara_filtered_count_ge",
    })


def build_knowledge(deck, overlay: dict) -> dict:
    """deck (DeckList) + overlay → 知識 dict。 全カード・全デッキ汎用、 決定論。"""
    fc: dict = defaultdict(int)
    for c in deck.main:
        for f in c.features:
            fc[f] += 1
    main_feature = max(fc, key=fc.get) if fc else None
    deck_features = set(fc)

    summon_features: set = set()
    for c in [deck.leader] + deck.main:
        keys: set = set()
        for e in _effs(overlay, c):
            keys |= set(_do_keys(e))
        if keys & {"play_from_hand", "summon_from_deck", "play_from_hand_named",
                   "play_from_hand_or_trash"}:
            for f in re.findall(r"《([^》]+)》", c.text or ""):
                if f in deck_features:
                    summon_features.add(f)

    def extract(card):
        prod, cons = set(), set()
        summon_feats = re.findall(r"《([^》]+)》", card.text or "")
        for eff in _effs(overlay, card):
            if_pairs = _flatten_if(eff.get("if") or eff.get("cond"))
            if_keys = {k for k, _ in if_pairs}
            cost_keys = _cost_keys(eff.get("cost"))
            keys = _do_keys(eff)
            for k in keys:
                if k in PROD_HAND:
                    prod.add("hand_fuel")
                    for sf in summon_features:
                        prod.add(f"hand:{sf}")
                if k in PROD_ATTACH:
                    prod.add("attach_don")
                if k in PROD_RAMP:
                    prod.add("don")
                if k in PROD_LIFE:
                    prod.add("life+")
                if k in PROD_KEYWORD:
                    prod.add("keyword")
                if k in PROD_TRASH:
                    prod.add("trash+")
                if k in PROD_COSTRED or k.startswith("reduce_play_cost"):
                    prod.add("cost_reduction")
                if k in PROD_BOARD and main_feature:
                    prod.add(f"board:{main_feature}")
            if cost_keys & {"discard_hand", "optional_discard_hand"}:
                cons.add("hand_fuel")
                prod.add("trash+")
            if cost_keys & {"rest_self_don", "pay_don"}:
                cons.add("don")
            if "self_attached_don_ge" in if_keys:
                cons.add("attach_don")
            if "self_don_ge" in if_keys:
                cons.add("don")
            if "self_life_le" in if_keys:
                cons.add("low_life(外的)")
            if {"opp_life_ge", "opp_life_le"} & if_keys:
                cons.add("opp_life(外的)")
            if {"trash_count_ge", "self_trash_count_ge"} & if_keys or "play_from_trash" in keys:
                cons.add("trash+")
            for _k, _v in if_pairs:
                if _k == "self_chara_filtered_count_ge" and isinstance(_v, dict):
                    filt = _v.get("filter", {})
                    tgt = filt.get("name") or filt.get("feature") or filt.get("feature_in")
                    if isinstance(tgt, list):
                        tgt = tgt[0] if tgt else None
                    if tgt:
                        cons.add(f"board:{tgt}")
            if "play_from_hand" in keys and summon_feats:
                for sf in summon_feats:
                    cons.add(f"hand:{sf}")
        if "character" in str(card.category).lower():
            for f in card.features:
                prod.add(f"board:{f}")
            prod.add(f"board:{card.name}")
        return prod, cons

    def usage_profile(card):
        usage = []
        for eff in _effs(overlay, card):
            if_pairs = _flatten_if(eff.get("if") or eff.get("cond"))
            if_keys = {k for k, _ in if_pairs}
            keys = set(_do_keys(eff))
            if not keys:
                continue
            usage.append({
                "when": eff.get("when"),
                "do": sorted(keys),
                "value_class": _value_class(keys),
                "conditional": bool(if_pairs),
                "reachable": _reachable(if_keys),
                "if_raw": eff.get("if") or eff.get("cond") or None,
            })
        return usage

    uniq = {}
    for c in [deck.leader] + deck.main:
        uniq.setdefault(c.card_id, c)
    info = {cid: dict(zip(("prod", "cons"), extract(c))) for cid, c in uniq.items()}

    EXTERNAL = {"low_life(外的)", "opp_life(外的)"}
    edges = []
    for bid, b in info.items():
        for tag in b["cons"]:
            if tag in EXTERNAL:
                continue
            producers = [aid for aid, a in info.items() if aid != bid and tag in a["prod"]]
            if producers:
                edges.append({"tag": tag, "to": bid, "from": producers})

    enables: dict = defaultdict(set)
    enabled_by: dict = defaultdict(set)
    for e in edges:
        enabled_by[e["to"]].update(e["from"])
        for a in e["from"]:
            enables[a].add(e["to"])

    def roles_of(card, usage):
        r = []
        keys = set()
        whens = set()
        for e in _effs(overlay, card):
            keys |= set(_do_keys(e))
            whens.add(e.get("when"))
        if "leader" in str(card.category).lower():
            r.append("leader")
        if getattr(card, "is_blocker", False):
            r.append("blocker")
        if (card.counter or 0) > 0 or "counter" in whens:
            r.append("counter")
        if (card.power or 0) >= 7000 or getattr(card, "is_double_attack", False):
            r.append("finisher")
        if keys & {"search_top_n", "search", "reveal_top_play", "reveal_top_then"}:
            r.append("searcher")
        if keys & PROD_RAMP:
            r.append("ramp")
        if keys & PROD_LIFE:
            r.append("recovery")
        if keys & REMOVAL:
            r.append("removal")
        if any(k.startswith("power_pump") for k in keys):
            r.append("pump")
        return r

    def timing_hint(card, usage, roles):
        strong = [u for u in usage if u["conditional"] and u["value_class"] in VALUABLE]
        if strong:
            u = strong[0]
            tail = "将来満たしやすく温存価値高" if u["reachable"] else "条件成立を待つ"
            return (f"{u['when']}効果は条件付き({u['value_class']})。 条件外なら body のみ → {tail}")
        if "counter" in roles and any(u["when"] == "counter" for u in usage):
            return "カウンターは相手の攻撃時まで温存"
        uncond = [u for u in usage if not u["conditional"] and u["value_class"] not in ("—", "other")]
        if uncond:
            return f"いつでも{uncond[0]['value_class']}を発動できる(即時運用)"
        if "blocker" in roles:
            return "ブロッカー: 守りが要る時(低ライフ/相手打点高)の価値が高い"
        if "finisher" in roles:
            return "フィニッシャー: 打点を通せる盤面/リーサル圏で価値が高い"
        return "効果なし/バニラ: コストカーブ通り"

    cards_out = {}
    for cid, c in uniq.items():
        usage = usage_profile(c)
        roles = roles_of(c, usage)
        if enables.get(cid):
            roles.append("enabler")
        if enabled_by.get(cid):
            roles.append("payoff")
        cards_out[cid] = {
            "name": c.name, "cost": c.cost, "power": c.power, "counter": c.counter,
            "roles": roles,
            "produces": sorted(info[cid]["prod"]),
            "consumes": sorted(info[cid]["cons"]),
            "usage": usage,
            "combo": {"enables": sorted(enables.get(cid, [])),
                      "enabled_by": sorted(enabled_by.get(cid, []))},
            "timing_hint": timing_hint(c, usage, roles),
        }
    return {
        "slug": getattr(deck, "slug", None), "deck_name": getattr(deck, "name", None),
        "main_feature": main_feature, "summon_features": sorted(summon_features),
        "combos": edges, "cards": cards_out,
    }


class _PoolDeck:
    """build_knowledge に渡す軽量 deck shim (= leader + main の CardDef リスト)。"""

    def __init__(self, leader, main, name=None, slug=None):
        self.leader = leader
        self.main = main
        self.name = name
        self.slug = slug


def _gather_pool(player) -> list:
    """player の全ゾーンから CardDef を収集 (= 50枚は保存則で union に揃う)。
    play 候補は hand にあるので、 多少 deck が隠れていても bias 対象は網羅される。"""
    cards = []
    seen = set()
    for z in ("deck", "hand", "characters", "stages", "trash", "life"):
        for item in getattr(player, z, []) or []:
            cd = getattr(item, "card", item)
            cid = getattr(cd, "card_id", None)
            if cid and cid not in seen and getattr(cd, "category", None) is not None:
                seen.add(cid)
                cards.append(cd)
    return cards


def build_knowledge_from_player(player, overlay) -> dict:
    """対戦中の player オブジェクトから知識を build (= deck file 不要、 zone から復元)。"""
    leader = getattr(player.leader, "card", player.leader)
    return build_knowledge(_PoolDeck(leader, _gather_pool(player)), overlay)


# 調整スケール (= board_eval 単位に合わせた控えめな nudge。 探索の最終判断を上書きしない)。
# ⚠ defer は「他に良い手があれば温存、 body が最善なら出す」 の tiebreaker。 大きすぎると
# body が最善でも出さず winrate を下げる (= 検証で確認)。 低ライフで効果が live な場合は
# engine が効果を発火 → board_eval が既に +life を評価するので、 good-timing 加点は小さくてよい。
DEFER_PENALTY = 300      # 条件付き効果が今 dead だが将来満たせる → 温存 (gentle nudge)
GOOD_TIMING_BONUS = 150  # 条件が今 live → 出す好機 (board_eval が主、 これは補強)
COMBO_READY_BONUS = 350  # 準備完了コンボを前進させる


class DeckKnowledge:
    """build_knowledge の dict をラップし、 対戦時の候補手スコア調整を提供。"""

    def __init__(self, knowledge: dict):
        self.k = knowledge or {}
        self.cards = self.k.get("cards", {})

    @classmethod
    def for_deck(cls, deck, overlay: dict) -> "DeckKnowledge":
        return cls(build_knowledge(deck, overlay))

    def _conditions_live(self, if_raw, state, me) -> bool:
        """if_raw が現状態で成立するか (= engine の厳密判定)。"""
        if not if_raw:
            return True
        try:
            from .effects import eval_all_conditions
            return bool(eval_all_conditions({"if": if_raw}, state, me, None))
        except Exception:
            return True  # 判定不能は live 扱い (= 抑制しすぎない)

    def play_timing_adjustment(self, card_id: str, state, me_idx: int) -> float:
        """card_id を「今」 play する事への加点(好機)/減点(温存)。

        各カードの有効な使い方 (= 条件付き効果が live か) で決まる:
          - 価値ある条件付き効果が今 dead + 将来満たせる → 温存 (DEFER_PENALTY)
          - その効果が今 live → 好機 (GOOD_TIMING_BONUS)
        他に良い手が無い時は探索/lookup 側が body 価値で上書きする (= プライア)。
        """
        c = self.cards.get(card_id)
        if not c:
            return 0.0
        me = state.players[me_idx]
        adj = 0.0
        for u in c.get("usage", []):
            if u.get("value_class") not in VALUABLE:
                continue
            if u.get("when") not in PLAY_WHEN:
                continue
            if not u.get("conditional"):
                continue
            live = self._conditions_live(u.get("if_raw"), state, me)
            if live:
                adj += GOOD_TIMING_BONUS
            elif u.get("reachable"):
                adj -= DEFER_PENALTY
        return adj

    def combo_bonus(self, card_id: str, state, me_idx: int) -> float:
        """card_id が「準備完了コンボ」 を前進させるなら加点。

        card が enable する consumer が場/手札に既にいる (= パーツが揃っている) なら、
        この card を出すことでコンボが繋がる → 加点。
        """
        c = self.cards.get(card_id)
        if not c:
            return 0.0
        partners = c.get("combo", {}).get("enables", [])
        if not partners:
            return 0.0
        me = state.players[me_idx]
        present = set()
        for ip in [me.leader] + list(getattr(me, "characters", []) or []):
            present.add(getattr(ip.card, "card_id", None))
        for hc in getattr(me, "hand", []) or []:
            present.add(getattr(hc, "card_id", None))
        if any(p in present for p in partners):
            return COMBO_READY_BONUS
        return 0.0
