# -*- coding: utf-8 -*-
"""観戦コメントのクラスタ化。

`db/spectate_comments.json` に集まる自由記述コメントを、 同一の指摘ごとに
グルーピングして「クラスタ」 として返す。 私 (Claude) が「コメント確認して」
された時にクラスタ単位で対応する → 同じ指摘を重複してハンドリングしない。

設計方針:
- 軽量 / deterministic / 外部依存なし (= embedding model 不要)
- text からのキーワード抽出 + snapshot_log の action_type 抽出で fingerprint 化
- dominant_theme + action_type が一致するコメントを 1 クラスタに集める
- 同一クラスタ内では vote (= agreed_by 重複なし合計) で重み付け

将来 embedding 系に置き換える場合も、 同じ I/F (= list[Comment] → list[Cluster])
を保てば差し替え可能。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# ============================================================================ #
# キーワード辞書 (= テキスト → theme tag への mapping)
# ============================================================================ #
# 順序は意識しない。 set 化される。
_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "animation": ("アニメ", "アニメーション", "演出", "animation"),
    "futility": ("意味", "無駄", "無意味", "いみない", "意味ない", "意味不明",
                 "何の意味", "もったいない"),
    "order": ("順番", "順序", "順", "タイミング"),
    "don": ("ドン", "DON", "don"),
    "attack": ("攻撃", "アタック", "アタッカー"),
    "rest": ("rested", "レスト", "レストし"),
    "effect": ("効果", "エフェクト"),
    "draw": ("ドロー",),
    "leader": ("リーダー", "leader"),
    "cost": ("コスト", "cost"),
    "block": ("ブロック", "ブロッカー"),
    "discard": ("捨て", "discard", "ディスカード"),
    "hand": ("手札", "ハンド", "hand"),
    "life": ("ライフ", "life"),
    "ko": ("KO", "ko", "倒", "撃破"),
    "counter": ("カウンター", "counter"),
    "ui": ("表示", "見える", "見にくい", "見やすい", "UI"),
    "bug": ("バグ", "おかしい", "逆", "違う", "間違"),
}

# dominant theme の優先順 — 上のほうが「主訴」 として強い。
# 例: 「アニメ + ドン」 のテキストでは animation (= 要望) が dominant、
# 「意味ない + ドン」 では futility (= 苦情) が dominant。
_DOMINANT_PRIORITY: tuple[str, ...] = (
    "futility",
    "bug",
    "order",
    "animation",
    "ui",
    # 以下は subject 側だが、 dominant が決まらない時の fallback
    "don",
    "attack",
    "effect",
    "draw",
    "block",
    "rest",
    "cost",
    "discard",
    "ko",
    "counter",
    "hand",
    "leader",
    "life",
)


def extract_themes(text: str) -> set[str]:
    """text から theme tag の集合を抽出。 大文字小文字無視、 部分一致。"""
    if not text:
        return set()
    themes: set[str] = set()
    for tag, kws in _THEME_KEYWORDS.items():
        if any(kw in text for kw in kws):
            themes.add(tag)
    return themes


def dominant_theme(themes: set[str]) -> str:
    """themes 集合から「主訴」 にあたる 1 つを返す。 該当なしなら 'other'。"""
    for t in _DOMINANT_PRIORITY:
        if t in themes:
            return t
    return "other"


# ============================================================================ #
# snapshot_log → action_type 抽出
# ============================================================================ #
# engine の log フォーマット (= push_log) を見て、 どの種類の行動かを判定。
# 一致しなければ "other"。

_ACTION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("attach_don_leader", re.compile(r"attach don to leader")),
    ("attach_don_chara",  re.compile(r"attach don to(?! leader)")),
    ("activate_main",     re.compile(r"起動メイン:")),
    ("activate_main_cost", re.compile(r"起動メインコスト:")),
    ("event",             re.compile(r"\bevent:")),
    ("counter_event",     re.compile(r"counter event:")),
    ("play_chara",        re.compile(r"\bplay:")),
    ("play_stage",        re.compile(r"\bstage:")),
    ("atk",               re.compile(r"\batk:")),
    ("survived",          re.compile(r"\bsurvived\b")),
    ("blocked",           re.compile(r"\bblocked\b")),
    ("blocker",           re.compile(r"blocker:")),
    ("ko",                re.compile(r"\bKO: ")),
    ("hit",               re.compile(r"\bhit: ")),
    ("counter_card",      re.compile(r"counter \+\d+")),
    ("draw_phase",        re.compile(r"\bdraw: ")),
    ("don_phase",         re.compile(r"don phase: ")),
    ("refresh",           re.compile(r"refresh: ")),
    ("effect_generic",    re.compile(r"効果:")),
    ("trigger",           re.compile(r"trigger->")),
    ("turn_start",        re.compile(r"=== turn start|=== extra turn")),
)


def extract_action_type(snapshot_log: str) -> str:
    if not snapshot_log:
        return "other"
    for tag, pat in _ACTION_PATTERNS:
        if pat.search(snapshot_log):
            return tag
    return "other"


# 細分された action_type を category にまとめる。 cluster_key 形成時に category を
# 使うことで、 「attach_don_leader」 と「attach_don_chara」 のような関連事象を
# 同じクラスタに集約できる。
_ACTION_CATEGORY: dict[str, str] = {
    "attach_don_leader": "attach_don",
    "attach_don_chara":  "attach_don",
    "atk":               "atk",
    "event":             "event",
    "counter_event":     "counter",
    "counter_card":      "counter",
    "activate_main":     "activate_main",
    "activate_main_cost": "activate_main",
    "play_chara":        "play",
    "play_stage":        "play",
    "draw_phase":        "phase_transition",
    "don_phase":         "phase_transition",
    "refresh":           "phase_transition",
    "turn_start":        "phase_transition",
    "survived":          "battle_outcome",
    "blocked":           "battle_outcome",
    "blocker":           "battle_outcome",
    "ko":                "battle_outcome",
    "hit":               "battle_outcome",
    "effect_generic":    "effect",
    "trigger":           "effect",
    "other":             "other",
}


def action_category(action_type: str) -> str:
    return _ACTION_CATEGORY.get(action_type, "other")


# 主訴 theme の 一部は action を無視して 粗くまとめる (= 「アニメ欲しい」 は
# どの phase でも 同じ要望なので 1 cluster に集約)。
_THEME_IGNORES_ACTION: frozenset[str] = frozenset({"animation", "ui"})


# ============================================================================ #
# snapshot_log からカード名抽出 (= 「五老星」「ガンマナイフ」 等)
# ============================================================================ #
# 「attach don to <name> x1」「event: <name> (cost ...」「atk: <name>(P=」 等。
# クラスタ化のサブ判別 (= 同じ ATK でも別カードなら別事象) に使うが、 過細分化を
# 避けるためデフォルトでは cluster key から外す (= 出力情報としてのみ保持)。
_CARD_NAME_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"attach don to ([^x]+?) x\d+"),
    re.compile(r"event: (.+?) \(cost"),
    re.compile(r"play: (.+?) \(cost"),
    re.compile(r"stage: (.+?) \(cost"),
    re.compile(r"atk: ([^(]+?)\(P="),
    re.compile(r"KO: (.+?)(?: \(|$)"),
    re.compile(r"起動メイン: (.+?)$"),
)


def extract_card_name(snapshot_log: str) -> str:
    if not snapshot_log:
        return ""
    for pat in _CARD_NAME_PATTERNS:
        m = pat.search(snapshot_log)
        if m:
            return m.group(1).strip()
    return ""


# ============================================================================ #
# クラスタ化本体
# ============================================================================ #


@dataclass
class CommentCluster:
    cluster_key: str           # "futility|attach_don_leader" 等の id
    dominant_theme: str        # 主訴
    action_type: str           # snapshot から抽出した行動種
    representative_text: str   # 最長 / 最も情報量のあるテキスト
    representative_id: str     # 代表コメント id
    count: int                 # 含まれるコメント数
    comments: list[dict] = field(default_factory=list)
    snapshot_indices: list[int] = field(default_factory=list)
    card_names: list[str] = field(default_factory=list)
    agreed_total: int = 0      # クラスタ内 agreed_by の 合計人数 (= 同意の強さ)
    authors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cluster_key": self.cluster_key,
            "dominant_theme": self.dominant_theme,
            "action_type": self.action_type,
            "representative_text": self.representative_text,
            "representative_id": self.representative_id,
            "count": self.count,
            "comments": self.comments,
            "snapshot_indices": self.snapshot_indices,
            "card_names": self.card_names,
            "agreed_total": self.agreed_total,
            "authors": self.authors,
        }


def _cluster_key(dominant: str, action_type: str) -> str:
    """cluster の id を作る。 dominant が animation/ui 等の「ガバ要望系」 なら
    action_type を無視 (= "*")、 そうでなければ action_category を使って細分化。
    """
    if dominant in _THEME_IGNORES_ACTION:
        return f"{dominant}|*"
    cat = action_category(action_type)
    return f"{dominant}|{cat}"


def cluster_comments(comments: Iterable[dict]) -> list[CommentCluster]:
    """comment list を入力に、 クラスタ list を返す。 入力は POST /api/spectate/comments
    の出力形式 (= dict with text / snapshot_log / id / agreed_by / author 等)。

    cluster key = dominant_theme + "|" + action_category (animation/ui は "*")。
    """
    buckets: dict[str, list[dict]] = {}
    for c in comments:
        text = c.get("text", "")
        snap_log = c.get("snapshot_log", "")
        themes = extract_themes(text)
        dom = dominant_theme(themes)
        act = extract_action_type(snap_log)
        key = _cluster_key(dom, act)
        buckets.setdefault(key, []).append(c)

    clusters: list[CommentCluster] = []
    for key, items in buckets.items():
        dom, act = key.split("|", 1)
        # representative = 最長 text (= 情報量が高い)
        rep = max(items, key=lambda c: len(c.get("text", "")))
        # snapshot_indices, card_names は重複排除しつつ順序維持
        snap_indices: list[int] = []
        seen_snap: set[int] = set()
        card_names: list[str] = []
        seen_card: set[str] = set()
        agreed_total = 0
        agreed_set: set[str] = set()
        authors: list[str] = []
        seen_author: set[str] = set()
        for c in items:
            si = c.get("snapshot_idx")
            if isinstance(si, int) and si not in seen_snap:
                snap_indices.append(si)
                seen_snap.add(si)
            cn = extract_card_name(c.get("snapshot_log", ""))
            if cn and cn not in seen_card:
                card_names.append(cn)
                seen_card.add(cn)
            for a in c.get("agreed_by") or []:
                agreed_set.add(a)
            author = c.get("author")
            if author and author not in seen_author:
                authors.append(author)
                seen_author.add(author)
        agreed_total = len(agreed_set)
        clusters.append(
            CommentCluster(
                cluster_key=key,
                dominant_theme=dom,
                action_type=act,
                representative_text=rep.get("text", ""),
                representative_id=rep.get("id", ""),
                count=len(items),
                comments=list(items),
                snapshot_indices=snap_indices,
                card_names=card_names,
                agreed_total=agreed_total,
                authors=authors,
            )
        )
    # 「重要度」 で降順 sort: agreed_total + count × 0.5
    clusters.sort(
        key=lambda cl: (cl.agreed_total + cl.count * 0.5, cl.count),
        reverse=True,
    )
    return clusters


def format_clusters_text(clusters: list[CommentCluster]) -> str:
    """CLI 出力用整形。"""
    if not clusters:
        return "(no comments)\n"
    lines: list[str] = []
    lines.append(f"=== {len(clusters)} clusters ===\n")
    for i, cl in enumerate(clusters, 1):
        agreed = f" (👍 {cl.agreed_total})" if cl.agreed_total else ""
        cards = ", ".join(cl.card_names[:5]) if cl.card_names else ""
        cards_str = f" [cards: {cards}]" if cards else ""
        lines.append(
            f"\n[#{i}] {cl.dominant_theme} / {cl.action_type} "
            f"× {cl.count}{agreed}{cards_str}"
        )
        lines.append(f"     代表: 「{cl.representative_text}」")
        if len(cl.comments) > 1:
            lines.append("     ほか:")
            for c in cl.comments:
                if c.get("id") == cl.representative_id:
                    continue
                lines.append(f"       - 「{c.get('text', '')}」 (snap {c.get('snapshot_idx')})")
        # snapshot 場所
        if cl.snapshot_indices:
            si = ", ".join(str(x) for x in cl.snapshot_indices[:8])
            lines.append(f"     観測 snap: [{si}]")
    return "\n".join(lines) + "\n"
