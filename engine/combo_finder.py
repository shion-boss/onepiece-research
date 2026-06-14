# -*- coding: utf-8 -*-
"""コンボ探索 finder (Step 1 = 静的).

指定カード (= anchor) を起点に、 全カードプールから「相性の良いカード」を
種別ごとに抽出し、 **差別化された static score** でランクして返す。

設計 (= 2026-06-14、 docs 議論の実装):
- recall (= 多く見つける) より ranking (= 差をつける) が本質。 フラットな一覧は
  ノイズなので、 (1) 機能で型分類 (2) static score で全件ランク (3) 型ごと top-N + dedup。
- score factor: シナジー強度 (飽和) / コスト効率 / 一貫性 (CHARACTER>EVENT) / デッキ適合
  (= 同特徴・同色)。 「下げ幅最大だが単発・異アーキ」 を自動で下げ、 効率の良い噛み合いを上げる。
- 各候補に **LLM 不要の理由文 (reason)** をテンプレで付与 (= 「なぜ効くか」)。

強さの裏取り (= sim / deck-doctor) は Layer B (別) で、 本 module は構造発見まで。

primitive/effect は db/card_effects.json (overlay) も使えるが、 MVP は公式 text +
構造化フィールド (features/cost/color/category/power) で十分な精度 (= demo 実証済)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


# --------------------------------------------------------------------------- #
# データ構造
# --------------------------------------------------------------------------- #
@dataclass
class ComboCard:
    card_id: str
    name: str
    category: str
    color: list[str]
    cost: int
    power: int
    features: list[str]
    text: str
    score: float
    reason: str


@dataclass
class ComboGroup:
    key: str           # machine key (= "tribal" / "accelerant" / "enabler" / "amplifier")
    label: str         # 表示名
    description: str    # 型の説明 (= なぜこの軸が効くか)
    cards: list[ComboCard] = field(default_factory=list)


@dataclass
class ComboChainStep:
    card_id: str
    name: str
    role: str          # 役割 (= ペイオフ / 下げ役 / 条件成立 ...)
    category: str
    color: list[str]
    cost: int
    text: str


@dataclass
class ComboChain:
    n_cards: int
    score: float
    label: str          # "3枚コンボ" / "4枚コンボ"
    description: str     # どう繋がるか
    steps: list[ComboChainStep]  # anchor → enabler → satisfier ... の順


@dataclass
class ComboResult:
    anchor: ComboCard
    hooks: list[str]            # anchor から検出した噛み所 (= human-readable)
    groups: list[ComboGroup]
    chains: list[ComboChain] = field(default_factory=list)  # 3-4枚 多枚コンボ


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _cost(card) -> int:
    try:
        return int(card.cost)
    except (TypeError, ValueError):
        return 5


def _block_icon(card) -> int:
    try:
        return int(getattr(card, "block_icon", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _category(card) -> str:
    cat = getattr(card, "category", "")
    return getattr(cat, "value", cat) or ""


def _features(card) -> list[str]:
    return [str(f) for f in (getattr(card, "features", None) or [])]


def _colors(card) -> list[str]:
    return [str(c) for c in (getattr(card, "color", None) or [])]


def _text(card) -> str:
    return getattr(card, "text", "") or ""


def _cost_eff(card) -> float:
    """安い = 高得点 (= テンポ)。 0..1。"""
    return max(0.0, (10 - _cost(card)) / 10.0)


def _consistency(card) -> float:
    """場に残り反復するか。 CHARACTER > STAGE > EVENT (= 単発)。"""
    cat = _category(card)
    if cat == "CHARACTER":
        return 1.0
    if cat == "STAGE":
        return 0.6
    return 0.2  # EVENT は単発


def _shared_features(anchor_feats: list[str], card) -> list[str]:
    cf = set(_features(card))
    return [f for f in anchor_feats if f in cf]


def _required_leader_features(text: str) -> set[str]:
    """効果が『リーダーが特徴《X》/『X』を持つ場合』 で要求するリーダー特徴を返す
    (= 名前指定「X」 は対象外。 デッキの色/特徴で両立可否を判定するため)。"""
    return set(re.findall(r"リーダーが(?:特徴)?[『《]([^』》]+)[』》]", text))


def _leader_feature_compatible(text: str, anchor_feats: list[str]) -> bool:
    """効果が要求するリーダー特徴が anchor の特徴と両立するか (= 同じデッキ/リーダーで使えるか)。
    ⚠ 2026-06-14: サッチ(リーダー=白ひげ要求)がアラバスタのペルのチェーンに誤混入していた。"""
    req = _required_leader_features(text)
    if not req:
        return True
    return bool(req & set(anchor_feats))


def _condition_note(text: str) -> tuple[float, str, str]:
    """効果の発動条件 (= in-game setup の要否) を (倍率, 注記, 条件type) で返す。

    構築で自動成立する条件 (= リーダー特徴/色) は減点しない。 試合中に別カードで状態を
    作る必要がある条件は「実質 N 枚コンボ」 なので combo 候補としての価値を割り引く。
    条件type (= leader_power/life/trash) は、 その条件を満たす satisfier を探して
    多枚コンボを組むのに使う ([[combo chains]])。
    ⚠ 2026-06-14 ユーザー指摘: 海ネコ (= 自リーダーがパワー0以下の場合 -3000) が
    無条件の下げ役と同列に評価されていた。 条件で減点 + 多枚コンボ化する。
    """
    # 自リーダーのパワーを下げる必要 = 別カード必須 (= 実質3枚コンボ)
    if re.search(r"リーダー.{0,8}パワー.{0,6}\d+以下", text):
        return 0.4, "要セットアップ: 自リーダーのパワーを下げる別カードが必要 (= 実質3枚コンボ)", "leader_power"
    if re.search(r"(自分の)?ライフ.{0,6}\d+\s*枚?以下", text):
        return 0.7, "条件: 自ライフが一定以下の時のみ", "life"
    if re.search(r"トラッシュ.{0,8}\d+\s*枚以上", text):
        return 0.75, "条件: トラッシュを貯める必要あり", "trash"
    return 1.0, "", ""


# --------------------------------------------------------------------------- #
# anchor の「噛み所 (hooks)」 検出
# --------------------------------------------------------------------------- #
def _detect_ko_power_threshold(text: str) -> Optional[int]:
    """『相手のパワーX以下のキャラ…KO』 系。 → power-down で圏を広げられる anchor。"""
    m = re.search(r"相手の?パワー(\d{3,5})以下.{0,12}(KO|ＫＯ)", text)
    if m:
        return int(m.group(1))
    # 「パワーX以下」 + 同節に KO
    if ("KO" in text or "ＫＯ" in text):
        m2 = re.search(r"パワー(\d{3,5})以下", text)
        if m2:
            return int(m2.group(1))
    return None


def _detect_self_powerdown(text: str) -> Optional[int]:
    """このカード自身が『相手キャラのパワーを下げる』効果か (= enabler matcher と同基準)。
    → KO閾値ペイオフを活かせる下げ役。 返り値 = 下げ幅。"""
    if "相手" not in text:
        return None
    m = re.search(r"パワー[-－](\d{3,5})", text)
    if not m:
        return None
    d = int(m.group(1))
    return d if d >= 1000 else None


def _is_attacker_trigger(text: str) -> bool:
    return "【アタック時】" in text


def _has_on_play(text: str) -> bool:
    return "【登場時】" in text


# --------------------------------------------------------------------------- #
# matcher 群 (= 各軸で候補 + score + reason を生成)
# --------------------------------------------------------------------------- #
def _match_enabler_powerdown(anchor, all_cards, ko_threshold: int) -> list[ComboCard]:
    """anchor の KO 閾値を「相手パワーダウン」 で広げる相棒 (= ペル × 下げ役)。"""
    anchor_feats = _features(anchor)
    anchor_colors = set(_colors(anchor))
    out: list[ComboCard] = []
    for c in all_cards:
        if c.card_id == anchor.card_id:
            continue
        t = _text(c)
        if "相手" not in t:
            continue
        m = re.search(r"パワー[-－](\d{3,5})", t)
        if not m:
            continue
        debuff = int(m.group(1))
        if debuff < 1000:
            continue
        # ① シナジー強度: KO 閾値 + debuff で届く相手 power。 ただし ~7000 到達で飽和
        #    (= overkill は加点しない → 下げ幅最大の単発カードが不当に上位化するのを防ぐ)
        reach = ko_threshold + debuff
        s_mag = min(reach, 7000) / 7000 * 4.0
        s_cost = _cost_eff(c) * 3.0
        s_consist = _consistency(c) * 2.0
        shared = _shared_features(anchor_feats, c)
        s_fit = (1.5 if shared else 0.0) + (0.8 if anchor_colors & set(_colors(c)) else 0.0)
        score = s_mag + s_cost + s_consist + s_fit
        cond_factor, cond_note, _ = _condition_note(t)
        score *= cond_factor
        reach_txt = f"最大{reach}" if reach <= 14000 else "ほぼ全サイズ"
        reason = (
            f"「相手パワー-{debuff}」で、{anchor.name}のKO圏(≤{ko_threshold})を{reach_txt}まで拡張"
            + (f"。同特徴《{shared[0]}》で噛み合う" if shared else "")
            + (f"。⚠ {cond_note}" if cond_note else "")
        )
        out.append(_to_combo(c, score, reason))
    return out


def _match_tribal(anchor, all_cards) -> list[ComboCard]:
    """anchor の特徴を共有する相棒 + その特徴を強化するリーダー。"""
    anchor_feats = _features(anchor)
    if not anchor_feats:
        return []
    anchor_colors = set(_colors(anchor))
    out: list[ComboCard] = []
    for c in all_cards:
        if c.card_id == anchor.card_id:
            continue
        shared = _shared_features(anchor_feats, c)
        if not shared:
            continue
        t = _text(c)
        cat = _category(c)
        is_leader = cat == "LEADER"
        # リーダーが anchor の特徴を参照/強化するか
        buffs_feature = any(f"《{f}》" in t for f in shared) and (
            "パワー+" in t or "登場" in t or "得る" in t or "引く" in t
        )
        s_overlap = min(len(shared), 2) * 1.2
        s_leader = (2.5 if is_leader and any(f"《{f}》" in t for f in shared) else 0.0)
        s_buff = 1.5 if buffs_feature and not is_leader else 0.0
        s_color = 0.6 if anchor_colors & set(_colors(c)) else 0.0
        s_cost = _cost_eff(c) * 1.0
        score = s_overlap + s_leader + s_buff + s_color + s_cost
        if is_leader:
            reason = f"リーダー《{shared[0]}》軸。{anchor.name}の居場所/強化元になる"
        elif buffs_feature:
            reason = f"《{shared[0]}》を参照/強化。{anchor.name}と部族シナジー"
        else:
            reason = f"同特徴《{shared[0]}》。{anchor.name}と並べて部族の数を稼ぐ"
        out.append(_to_combo(c, score, reason))
    return out


def _match_accelerant(anchor, all_cards) -> list[ComboCard]:
    """anchor を『早く/安定して出す』カード: サーチ / コスト軽減 / 踏み倒し登場。"""
    anchor_feats = _features(anchor)
    anchor_cost = _cost(anchor)
    anchor_name = anchor.name
    anchor_colors = set(_colors(anchor))
    out: list[ComboCard] = []
    for c in all_cards:
        if c.card_id == anchor.card_id:
            continue
        t = _text(c)
        kind = None
        reason = ""
        # 名前指定 (最強の確実性)
        named = f"「{anchor_name}」" in t
        # 特徴一致のサーチ/踏み倒し
        feat_hit = next((f for f in anchor_feats if f"《{f}》" in t), None)
        # コスト条件 (= anchor がその範囲に入るか)
        cost_ok = True
        cm = re.search(r"コスト(\d+)以下", t)
        if cm:
            cost_ok = anchor_cost <= int(cm.group(1))
        if ("手札に加える" in t or "公開" in t) and ("デッキ" in t) and (named or feat_hit):
            kind = "search"
            reason = (f"《{feat_hit}》" if feat_hit else f"「{anchor_name}」") + f"をサーチ → {anchor_name}を引ける"
        elif "登場させる" in t and (named or (feat_hit and cost_ok)):
            kind = "cheat"
            reason = (f"「{anchor_name}」" if named else f"《{feat_hit}》(コスト{anchor_cost})") + f"を踏み倒し登場"
        elif ("コスト" in t and ("少なくなる" in t or "減" in t)) and (named or feat_hit):
            kind = "cost"
            reason = (f"「{anchor_name}」" if named else f"《{feat_hit}》") + f"の登場コストを軽減"
        if not kind:
            continue
        s_named = 3.0 if named else 0.0
        s_feat = 1.5 if feat_hit else 0.0
        s_kind = {"search": 1.5, "cheat": 2.0, "cost": 1.2}[kind]
        s_cost = _cost_eff(c) * 1.5
        s_color = 0.6 if anchor_colors & set(_colors(c)) else 0.0
        score = s_named + s_feat + s_kind + s_cost + s_color
        out.append(_to_combo(c, score, reason))
    return out


def _match_amplifier(anchor, all_cards) -> list[ComboCard]:
    """anchor のペイオフを増幅: 攻撃時持ち→【速攻】付与で即発動。"""
    if not _is_attacker_trigger(_text(anchor)):
        return []
    anchor_colors = set(_colors(anchor))
    out: list[ComboCard] = []
    for c in all_cards:
        if c.card_id == anchor.card_id:
            continue
        t = _text(c)
        if "【速攻】" not in t or not ("得る" in t or "付与" in t or "与え" in t):
            continue
        s_color = 1.5 if anchor_colors & set(_colors(c)) else 0.0
        s_cost = _cost_eff(c) * 1.5
        s_consist = _consistency(c) * 1.0
        score = 2.0 + s_color + s_cost + s_consist
        reason = f"【速攻】付与 → {anchor.name}を出したターンに即【アタック時】効果を発動できる"
        out.append(_to_combo(c, score, reason))
    return out


def _match_payoff_for_powerdown(anchor, all_cards, pd_amount: int) -> list[ComboCard]:
    """anchor が相手パワーを下げる → その下げを活かす『パワーX以下KO』ペイオフ (= 双方向)。"""
    anchor_feats = _features(anchor)
    anchor_colors = set(_colors(anchor))
    out: list[ComboCard] = []
    for c in all_cards:
        if c.card_id == anchor.card_id:
            continue
        ko_t = _detect_ko_power_threshold(_text(c))
        if ko_t is None:
            continue
        reach = ko_t + pd_amount
        s_mag = min(reach, 7000) / 7000 * 4.0
        s_cost = _cost_eff(c) * 2.0
        s_consist = _consistency(c) * 2.0
        shared = _shared_features(anchor_feats, c)
        s_fit = (1.5 if shared else 0.0) + (0.8 if anchor_colors & set(_colors(c)) else 0.0)
        score = s_mag + s_cost + s_consist + s_fit
        cond_factor, cond_note, _ = _condition_note(_text(c))
        score *= cond_factor
        reach_txt = f"最大{reach}" if reach <= 14000 else "ほぼ全サイズ"
        reason = (
            f"{c.name}は「パワー{ko_t}以下をKO」。{anchor.name}の-{pd_amount}で{reach_txt}まで"
            "KO圏に入る (= この下げ役を活かすペイオフ)"
            + (f"。⚠ {cond_note}" if cond_note else "")
        )
        out.append(_to_combo(c, score, reason))
    return out


def _to_combo(c, score: float, reason: str) -> ComboCard:
    return ComboCard(
        card_id=c.card_id,
        name=c.name,
        category=_category(c),
        color=_colors(c),
        cost=_cost(c),
        power=int(getattr(c, "power", 0) or 0),
        features=_features(c),
        text=_text(c),
        score=round(score, 2),
        reason=reason,
    )


# --------------------------------------------------------------------------- #
# 多枚コンボ (= 条件成立チェーン: anchor + 条件付enabler + satisfier ...)
# --------------------------------------------------------------------------- #
_SATISFIER_PATTERNS = {
    "leader_power": r"自分の.{0,6}(アクティブの)?リーダー.{0,12}パワー[-－]\d",
    "life": r"自分のライフ.{0,18}(トラッシュ|手札に加え)",
    "trash": r"(自分の)?デッキの上から\d+枚.{0,14}トラッシュ",
}
_CTYPE_LABEL = {
    "leader_power": "自リーダーのパワーを下げる",
    "life": "自ライフを減らす",
    "trash": "トラッシュを貯める",
}


def _satisfiers_of_condition(ctype, all_cards, anchor, anchor_colors, anchor_feats):
    """条件 ctype を試合中に満たすカード (= satisfier) を扱いやすい順で返す。 同色のみ。"""
    pat = _SATISFIER_PATTERNS.get(ctype)
    if not pat:
        return []
    out = []
    for c in all_cards:
        if c.card_id == anchor.card_id:
            continue
        if anchor_colors and not (anchor_colors & set(_colors(c))):
            continue  # deck 成立性: anchor と同色のみ
        ct = _text(c)
        if not re.search(pat, ct):
            continue
        if not _leader_feature_compatible(ct, anchor_feats):
            continue  # 要求リーダー特徴が非互換 (= サッチ@ペル) → satisfier にならない
        shared = _shared_features(anchor_feats, c)
        fit = (1.5 if shared else 0.0) + (0.8 if anchor_colors & set(_colors(c)) else 0.0)
        out.append((c, round(_cost_eff(c) * 2.0 + _consistency(c) + fit, 2)))
    out.sort(key=lambda x: -x[1])
    return out


def _extra_opp_debuff(text: str, anchor_feats: list[str]) -> int:
    """このカードが (互換に) 相手キャラのパワーを下げる量 (= チェーンの reach に合算する)。
    リーダー特徴ゲートが非互換なら 0 (= 発動しないので加算しない)。"""
    if "相手" not in text or not _leader_feature_compatible(text, anchor_feats):
        return 0
    m = re.search(r"相手.{0,30}パワー[-－](\d{3,5})", text) or re.search(r"パワー[-－](\d{3,5})", text)
    return int(m.group(1)) if m else 0


def _chain_step(card, role: str) -> ComboChainStep:
    return ComboChainStep(
        card_id=card.card_id, name=card.name, role=role,
        category=_category(card), color=_colors(card), cost=_cost(card), text=_text(card),
    )


def _build_condition_chains(anchor, all_cards, anchor_colors, anchor_feats, ko_t, max_chains=6):
    """anchor の条件付き power-down enabler を起点に satisfier を足し 3-4 枚コンボを構築。
    ⚠ ユーザー指摘の「海ネコ(条件付下げ役) は自リーダー0が要る = 3枚コンボ」 を明示化する。"""
    if ko_t is None:
        return []
    cond_enablers = []
    for c in all_cards:
        if c.card_id == anchor.card_id:
            continue
        if anchor_colors and not (anchor_colors & set(_colors(c))):
            continue
        t = _text(c)
        if "相手" not in t:
            continue
        if not _leader_feature_compatible(t, anchor_feats):
            continue  # 要求リーダー特徴が非互換 → このデッキで発動しない
        m = re.search(r"パワー[-－](\d{3,5})", t)
        if not m:
            continue
        debuff = int(m.group(1))
        if debuff < 1000:
            continue
        _, _, ctype = _condition_note(t)
        if not ctype:
            continue  # 無条件 enabler は 2 枚コンボ (enabler 群で既出)
        cond_enablers.append((c, debuff, ctype))

    def _en_key(e):
        c, _, _ = e
        sh = 1.5 if _shared_features(anchor_feats, c) else 0.0
        col = 0.8 if anchor_colors & set(_colors(c)) else 0.0
        return -(sh + col + _cost_eff(c))

    cond_enablers.sort(key=_en_key)
    chains, seen = [], set()
    for c, debuff, ctype in cond_enablers[:4]:
        sats = _satisfiers_of_condition(ctype, all_cards, anchor, anchor_colors, anchor_feats)
        if not sats:
            continue
        base_reach = ko_t + debuff
        for sat, sat_score in sats[:2]:
            parts = [c, sat]
            role_sat = f"条件成立: {_CTYPE_LABEL.get(ctype, ctype)}"
            # satisfier が (互換に) 相手パワーも下げるなら reach に合算 (= ユーザー指摘)
            sat_extra = _extra_opp_debuff(_text(sat), anchor_feats)
            if sat_extra:
                role_sat += f" + 下げ-{sat_extra}"
            steps = [
                _chain_step(anchor, "ペイオフ (KO)"),
                _chain_step(c, "下げ役 (条件付)"),
                _chain_step(sat, role_sat),
            ]
            n_cards = 3
            extra_total = sat_extra
            _, _, sctype = _condition_note(_text(sat))
            if sctype and sctype != ctype:
                sats2 = _satisfiers_of_condition(sctype, all_cards, anchor, anchor_colors, anchor_feats)
                if sats2:
                    sat2 = sats2[0][0]
                    parts.append(sat2)
                    extra_total += _extra_opp_debuff(_text(sat2), anchor_feats)
                    steps.append(_chain_step(sat2, f"条件成立: {_CTYPE_LABEL.get(sctype, sctype)}"))
                    n_cards = 4
            sig = tuple(re.sub(r"_(p\d+|r\d+)$", "", s.card_id) for s in steps)
            if sig in seen:
                continue
            seen.add(sig)
            reach = base_reach + extra_total
            reach_factor = min(reach, 7000) / 7000
            cohesion = 1.0 if anchor_feats and all(_shared_features(anchor_feats, p) for p in parts) else 0.0
            penalty = 0.6 if n_cards == 3 else 0.42
            score = round((reach_factor * 4 + sat_score * 0.3 + cohesion * 1.5) * penalty, 2)
            reach_txt = f"最大{reach}" if reach <= 14000 else "ほぼ全サイズ"
            extra_txt = (
                f" さらに{sat.name}も相手-{sat_extra}するので合計-{debuff + extra_total}。"
                if sat_extra else ""
            )
            desc = (
                f"{anchor.name}のKO圏(≤{ko_t})を{c.name}の-{debuff}で広げるが、{c.name}は条件付き → "
                f"{sat.name}で{_CTYPE_LABEL.get(ctype, ctype)}と成立。{extra_txt}{n_cards}枚で{reach_txt}までKO可能。"
            )
            chains.append(ComboChain(
                n_cards=n_cards, score=score, label=f"{n_cards}枚コンボ",
                description=desc, steps=steps,
            ))
    chains.sort(key=lambda ch: -ch.score)
    return chains[:max_chains]


# --------------------------------------------------------------------------- #
# entrypoint
# --------------------------------------------------------------------------- #
def _dedup_parallels(cards: list[ComboCard]) -> list[ComboCard]:
    """パラレル (= OPxx-yyy_p1 等) は base と同一カードなので 1 つに畳む。"""
    seen: set[str] = set()
    out: list[ComboCard] = []
    for c in sorted(cards, key=lambda x: -x.score):
        base = re.sub(r"_(p\d+|r\d+)$", "", c.card_id)
        if base in seen:
            continue
        seen.add(base)
        out.append(c)
    return out


def _filter_offcolor_leaders(
    cards: list[ComboCard], anchor_colors: set[str]
) -> list[ComboCard]:
    """指定カードと違う色のリーダーを除外 (= そのリーダーのデッキに anchor を入れられない)。

    公式構築ルール: カードの全色がリーダーの色に含まれる必要 → leader.colors ⊇ anchor.colors。
    非リーダー候補は 2 色リーダーで共存しうるので除外しない (= リーダーのみ色厳密化)。
    """
    if not anchor_colors:
        return cards
    return [
        c
        for c in cards
        if c.category != "LEADER" or anchor_colors.issubset(set(c.color))
    ]


def find_combos(
    repo, card_id: str, per_group: int = 8, min_block_icon: int = 0
) -> ComboResult:
    """anchor card_id を起点にコンボ候補を型別・ランク付きで返す。

    min_block_icon: レギュレーション制限 (= スタンダードは block_icon>=2、 0 で全カード)。
    候補プールを絞る (= anchor 自体は対象外 = ユーザー指定なのでそのまま)。
    """
    by_id = repo._by_id
    anchor = by_id.get(card_id)
    if anchor is None:
        raise KeyError(f"unknown card_id: {card_id}")
    all_cards = list(by_id.values())
    if min_block_icon > 0:
        all_cards = [c for c in all_cards if _block_icon(c) >= min_block_icon]
    text = _text(anchor)
    anchor_colors = set(_colors(anchor))
    anchor_feats = _features(anchor)

    # 実戦デッキ共起による接地 (= スコア補正 + 専用グループ)。 off-meta anchor は空 (= 静的に委ねる)。
    try:
        from .combo_cooccurrence import cooc_score_map, cooccurring, n_decks
        _boost_map = cooc_score_map(card_id)
        _cooc = cooccurring(card_id, top=per_group * 2)
        _n_decks = n_decks()
    except Exception:
        _boost_map, _cooc, _n_decks = {}, [], 0

    def _legal(cards: list[ComboCard]) -> list[ComboCard]:
        # (1) 指定カードと違う色のリーダーは除外。 (2) 効果が要求するリーダー特徴が anchor と
        # 非互換なカードは除外 (= 同じデッキに入れても効果が発動しない、 例: サッチ@ペル)。
        cards = _filter_offcolor_leaders(cards, anchor_colors)
        cards = [c for c in cards if _leader_feature_compatible(c.text, anchor_feats)]
        return _dedup_parallels(cards)

    def _boosted(cards: list[ComboCard]) -> list[ComboCard]:
        # 実戦で anchor と共起する候補を加点 (= ランクを実戦に接地)。 cap +3。
        for c in cards:
            b = _boost_map.get(c.card_id)
            if b:
                c.score = round(c.score + min(3.0, 0.15 * b), 2)
                if "実戦" not in c.reason:
                    c.reason += "（実戦でも併用例あり）"
        return _legal(cards)

    hooks: list[str] = []
    groups: list[ComboGroup] = []

    # ⓪ 実戦シナジー (= 最も接地、 先頭): 実際に anchor と一緒に採用されているカード
    cooc_cards: list[ComboCard] = []
    for d in _cooc:
        c = by_id.get(d["card_id"])
        if c is None or c.card_id == anchor.card_id:
            continue
        if min_block_icon > 0 and _block_icon(c) < min_block_icon:
            continue
        cooc_cards.append(_to_combo(
            c, d["score"],
            f"実戦 {d['anchor_decks']} デッキ中 {d['cooc']} 個で {anchor.name} と併用 (lift {d['lift']})",
        ))
    cooc_cards = _legal(cooc_cards)
    if cooc_cards:
        hooks.append(f"実戦 {_n_decks} デッキ中、 一緒に採用されている相棒あり (= 接地)")
        groups.append(ComboGroup(
            key="cooccurrence",
            label="実戦シナジー (一緒に使われる)",
            description=f"{anchor.name}が実際に採用されている大会/構築デッキで、 同じデッキに入っているカード。ルールでなく実戦が根拠。",
            cards=cooc_cards[:per_group],
        ))

    # ① 条件成立 enabler (= anchor 固有、 最も価値が高い): KO 閾値 → power-down
    ko_t = _detect_ko_power_threshold(text)
    if ko_t is not None:
        hooks.append(f"KO条件「パワー{ko_t}以下」 → 相手パワーダウンで圏を広げられる")
        cards = _boosted(_match_enabler_powerdown(anchor, all_cards, ko_t))
        if cards:
            groups.append(ComboGroup(
                key="enabler",
                label="条件成立 (KO圏を広げる下げ役)",
                description=f"{anchor.name}はパワー{ko_t}以下しかKOできない。相手のパワーを下げるカードと組むと中大型までKO圏に入る。",
                cards=cards[:per_group],
            ))

    # ①b 双方向: anchor が相手パワーを下げる → その下げを活かす KO ペイオフ
    pd = _detect_self_powerdown(text)
    if pd is not None:
        cards = _boosted(_match_payoff_for_powerdown(anchor, all_cards, pd))
        if cards:
            hooks.append(f"相手パワー-{pd} → 「パワーX以下KO」 のペイオフを活かせる")
            groups.append(ComboGroup(
                key="payoff",
                label="このカードが活かす (KO/除去ペイオフ)",
                description=f"{anchor.name}は相手のパワーを-{pd}できる。これを前提に『パワーX以下KO』を持つカードが、本来届かない中大型を除去できるようになる。",
                cards=cards[:per_group],
            ))

    # ② 加速 accelerant
    cards = _boosted(_match_accelerant(anchor, all_cards))
    if cards:
        hooks.append("サーチ/コスト軽減/踏み倒しで早く・安定して出せる")
        groups.append(ComboGroup(
            key="accelerant",
            label="加速 (早く・安定して出す)",
            description=f"{anchor.name}をサーチ・コスト軽減・踏み倒し登場させ、着地を早め一貫性を上げるカード。",
            cards=cards[:per_group],
        ))

    # ③ 特徴シナジー tribal
    cards = _boosted(_match_tribal(anchor, all_cards))
    if cards:
        af = _features(anchor)
        hooks.append(f"特徴《{af[0]}》の部族シナジー" if af else "特徴シナジー")
        groups.append(ComboGroup(
            key="tribal",
            label="特徴シナジー (部族)",
            description=f"{anchor.name}と特徴を共有する相棒、およびその特徴を強化するリーダー。",
            cards=cards[:per_group],
        ))

    # ④ ペイオフ増幅 amplifier
    if _is_attacker_trigger(text):
        cards = _boosted(_match_amplifier(anchor, all_cards))
        if cards:
            hooks.append("【アタック時】持ち → 【速攻】付与で出したターンに即発動")
            groups.append(ComboGroup(
                key="amplifier",
                label="ペイオフ増幅 (速攻で即起動)",
                description=f"{anchor.name}は【アタック時】効果持ち。【速攻】を与えると出したターンに即発動できる。",
                cards=cards[:per_group],
            ))

    # 多枚コンボ (= 3-4枚 条件成立チェーン)。 条件付き enabler の不足ピースを明示化。
    chains = _build_condition_chains(anchor, all_cards, anchor_colors, _features(anchor), ko_t)
    if chains:
        hooks.append(f"条件付きカードを補う {chains[0].n_cards} 枚コンボあり")

    return ComboResult(
        anchor=_to_combo(anchor, 0.0, ""),
        hooks=hooks,
        groups=groups,
        chains=chains,
    )
