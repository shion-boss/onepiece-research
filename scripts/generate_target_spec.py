#!/usr/bin/env python3
"""Plan H Phase H-1 (= 2026-05-19): Claude API で deck の target spec を 生成。

1 self_deck × 16 opp_leader matchup × 10 turn × 3 condition = 480 entry を Claude が 書く。
prompt caching で cost 10x 削減 (= prefix 共通化)。

# 使い方

```bash
# pilot: 1 deck で 試行
export ANTHROPIC_API_KEY=sk-...
.venv/bin/python scripts/generate_target_spec.py --deck cardrush_1456

# dry run (= prompt 出力 だけ、 API call せず)
.venv/bin/python scripts/generate_target_spec.py --deck cardrush_1456 --dry-run

# resume (= 既存 出力 を 読んで 未完成 matchup のみ 続行)
.venv/bin/python scripts/generate_target_spec.py --deck cardrush_1456 --resume

# 軽量 mode (= 1 opp_leader のみ、 デバッグ用)
.venv/bin/python scripts/generate_target_spec.py --deck cardrush_1456 --only-opp tcgportal_coby
```

# 設計

- self_deck の 全 60 枚 effect + analysis + card_roles + filtered_cardqa は **cache prefix**
- per-matchup section (= opp_deck + matchup_cell) のみ uncached
- 各 matchup の output: 30 entry (= 10 turn × 3 condition)
- 16 matchup を 順次 処理、 incremental save (= 1 matchup ごと file 書き戻し)

# 出力

`decks/<slug>.target_v1.json`
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.target_dsl import DSL_SPEC  # noqa: E402

DECKS_DIR = REPO_ROOT / "decks"
DB_DIR = REPO_ROOT / "db"
CARDS_JSON = DB_DIR / "cards.json"
CARD_EFFECTS_JSON = DB_DIR / "card_effects.json"
CARD_ROLES_JSON = DB_DIR / "card_roles.json"
MATCHUP_MATRIX_JSON = DB_DIR / "matchup_matrix.json"
BANLIST_JSON = DB_DIR / "banlist" / "master.json"
FILTERED_CARDQA_DIR = DB_DIR / "filtered_cardqa"
ARCHIVE_DIR = DECKS_DIR / "_archive" / "cardrush_raw"


# ---------------------------------------------------------------------------
# data load
# ---------------------------------------------------------------------------


def load_deck(deck_slug: str) -> dict:
    """deck JSON を 読み込み。"""
    path = DECKS_DIR / f"{deck_slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"deck not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_deck_analysis(deck_slug: str) -> Optional[dict]:
    """deck analysis JSON を 読み込み。 なければ None。"""
    path = DECKS_DIR / f"{deck_slug}.analysis.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_cards_lookup() -> dict[str, dict]:
    """cards.json → card_id lookup dict。"""
    cards = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    return {c["card_id"]: c for c in cards if c.get("card_id")}


def load_card_effects_lookup() -> dict:
    """card_effects.json をそのまま 返す。"""
    return json.loads(CARD_EFFECTS_JSON.read_text(encoding="utf-8"))


def load_card_roles_lookup() -> dict:
    """card_roles.json をそのまま 返す。"""
    return json.loads(CARD_ROLES_JSON.read_text(encoding="utf-8"))


def load_matchup_cell(self_slug: str, opp_slug: str) -> Optional[dict]:
    """matchup_matrix.json から (self, opp) cell を 取得。"""
    m = json.loads(MATCHUP_MATRIX_JSON.read_text(encoding="utf-8"))
    for row_entry in m.get("matrix", []):
        if row_entry.get("deck_a") != self_slug:
            continue
        for cell in row_entry.get("row", []):
            if cell.get("deck_b") == opp_slug:
                return cell
    return None


def list_all_opp_decks() -> list[dict]:
    """meta pool 16 deck の一覧 を 返す (= decks/*.json で archive 以外)。"""
    decks: list[dict] = []
    for p in sorted(DECKS_DIR.glob("*.json")):
        if "_archive" in str(p) or p.name.endswith(".analysis.json") or p.name.endswith(".target_v1.json"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            decks.append({
                "slug": d.get("slug", p.stem),
                "name": d.get("name", ""),
                "leader": d.get("leader", ""),
                "leader_name": d.get("leader_name", ""),
            })
        except Exception:
            continue
    return decks


# ---------------------------------------------------------------------------
# prompt building
# ---------------------------------------------------------------------------


def _format_card_brief(cid: str, cards: dict, effects: dict, roles: dict) -> str:
    """1 枚 カード を Claude 用 brief format に。"""
    c = cards.get(cid, {})
    if not c:
        return f"- {cid}: (unknown card)"
    role = roles.get(cid, {})
    primary = role.get("primary_role", "")
    tags = role.get("tags", [])
    role_tag = primary
    if tags:
        role_tag = f"{primary} +{','.join(tags)}" if primary else f"+{','.join(tags)}"
    eff_list = effects.get(cid, [])
    if isinstance(eff_list, dict):
        eff_list = eff_list.get("effects", [])
    eff_texts = [e.get("_text") or "" for e in eff_list if isinstance(e, dict) and e.get("_text")]
    eff_summary = " | ".join(eff_texts) if eff_texts else "(no effect)"
    name = c.get("name", "")
    cost = c.get("cost", "")
    power = c.get("power", "")
    counter = c.get("counter", "")
    feat = c.get("features", "")
    return (
        f"- {cid} {name} cost={cost} power={power} counter={counter} feat={feat} role={role_tag}\n"
        f"  effect: {eff_summary}"
    )


def build_deck_brief(deck: dict, cards: dict, effects: dict, roles: dict) -> str:
    """deck 全 60 枚 を brief format で 連結。"""
    lines = [
        f"deck_slug: {deck.get('slug')}",
        f"name: {deck.get('name')}",
        f"leader_id: {deck.get('leader')} ({deck.get('leader_name')})",
        f"score: {deck.get('score')} / tournament: {deck.get('tournament_name')}",
        "",
        "## leader",
        _format_card_brief(deck.get("leader", ""), cards, effects, roles),
        "",
        "## main 60 cards",
    ]
    for entry in deck.get("main", []):
        cid = entry.get("card_id")
        count = entry.get("count", 0)
        lines.append(f"[x{count}]")
        lines.append(_format_card_brief(cid, cards, effects, roles))
    return "\n".join(lines)


def build_opp_brief(opp_deck: dict, cards: dict, effects: dict, roles: dict, max_main: int = 12) -> str:
    """opp deck の brief。 main は keys cards (上位 N) のみ。"""
    lines = [
        f"opp_deck_slug: {opp_deck.get('slug')}",
        f"name: {opp_deck.get('name')}",
        f"leader_id: {opp_deck.get('leader')} ({opp_deck.get('leader_name')})",
        "",
        "## leader",
        _format_card_brief(opp_deck.get("leader", ""), cards, effects, roles),
        "",
        f"## main (top {max_main} by count)",
    ]
    main = opp_deck.get("main", [])
    sorted_main = sorted(main, key=lambda e: -e.get("count", 0))[:max_main]
    for entry in sorted_main:
        cid = entry.get("card_id")
        count = entry.get("count", 0)
        lines.append(f"[x{count}]")
        lines.append(_format_card_brief(cid, cards, effects, roles))
    return "\n".join(lines)


def build_filtered_cardqa(deck_slug: str) -> str:
    """db/filtered_cardqa/<slug>.jsonl を 読み込み Claude 用 text に。"""
    path = FILTERED_CARDQA_DIR / f"{deck_slug}.jsonl"
    if not path.exists():
        return "(no filtered_cardqa)"
    lines = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
            except Exception:
                continue
            hits = ",".join(item.get("card_name_hits", []))
            lines.append(f"- [{item.get('series_slug')}] {hits}: Q: {item.get('q', '')[:120]} → A: {item.get('a', '')[:120]}")
    return "\n".join(lines) if lines else "(empty)"


def build_archive_winners(self_leader_id: str, max_n: int = 3) -> str:
    """cardrush_raw の関連 優勝 レシピ (= 同 leader_id) を 抜粋。"""
    if not ARCHIVE_DIR.exists():
        return "(no archive)"
    matches = []
    for p in ARCHIVE_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("leader") == self_leader_id and d.get("score") in ("優勝", "準優勝"):
            matches.append(d)
        if len(matches) >= max_n:
            break
    if not matches:
        return f"(no tournament winners for {self_leader_id})"
    lines = []
    for d in matches:
        lines.append(f"- [{d.get('score')}] {d.get('tournament_name')} {d.get('tournament_date')}")
        main = d.get("main", [])
        top_cards = sorted(main, key=lambda e: -e.get("count", 0))[:8]
        lines.append("  top cards: " + ", ".join(f"{e.get('card_id')}x{e.get('count')}" for e in top_cards))
    return "\n".join(lines)


def build_cache_prefix(
    self_deck: dict,
    self_analysis: Optional[dict],
    cards: dict,
    effects: dict,
    roles: dict,
) -> str:
    """共通 cache prefix を build (= 全 16 matchup で 共有 される 部分)。"""
    self_slug = self_deck.get("slug", "")
    self_leader = self_deck.get("leader", "")

    parts = [
        "# Plan H Target Spec Writer",
        "",
        "あなたは ワンピース カードゲーム の 専門 deck analyst で、 AI 用 「ターン目標 駆動 戦略 spec」 を 書く 仕事 を します。",
        "",
        "## Output Format",
        "後で 指定 する matchup に 対して、 10 turn × 3 condition = 30 entry を JSON で 出力。",
        "",
        "## DSL Specification",
        DSL_SPEC,
        "",
        "## Self Deck (= あなたが 戦略 を 書く 対象 deck)",
        build_deck_brief(self_deck, cards, effects, roles),
        "",
        "## Self Deck Analysis",
        json.dumps(self_analysis, ensure_ascii=False, indent=2) if self_analysis else "(no analysis)",
        "",
        "## Related Filtered Cardqa (= 公式 Q&A)",
        build_filtered_cardqa(self_slug),
        "",
        "## Related Tournament Winners (= 同 leader 優勝レシピ)",
        build_archive_winners(self_leader),
    ]
    return "\n".join(parts)


def build_matchup_user_prompt(
    opp_deck: dict,
    cards: dict,
    effects: dict,
    roles: dict,
    matchup_cell: Optional[dict],
) -> str:
    """per-matchup の uncached prompt 部分。"""
    parts = [
        f"# Matchup: vs {opp_deck.get('leader_name')} ({opp_deck.get('slug')})",
        "",
        "## Opponent Deck",
        build_opp_brief(opp_deck, cards, effects, roles),
        "",
        "## Matchup Result (= 現 AI で の 勝率 cell)",
    ]
    if matchup_cell:
        winrate = matchup_cell.get("winrate")
        wins = matchup_cell.get("wins", 0)
        losses = matchup_cell.get("losses", 0)
        draws = matchup_cell.get("draws", 0)
        parts.append(f"winrate: {winrate} ({wins}W-{losses}L-{draws}D)")
    else:
        parts.append("(no matchup data)")

    parts.extend([
        "",
        "## あなたへの 依頼",
        "",
        f"上記 self_deck で vs {opp_deck.get('leader_name')} を 戦う 際 の 「ターン目標 spec」 を 書いて ください。",
        "",
        "**必須**: turn 1, 2, 3, ..., 10 の 各 turn × self_condition (= advantage/even/behind) の 3 種類 = 30 entry を 出力。",
        "",
        "各 entry には priority 1-3 の targets (= 「ターン終了時に こうあったらいい」 盤面) を 設定。",
        "**self_condition は start-of-turn の 状況** (= 「behind なら 守備寄り 目標、 advantage なら 攻撃寄り 目標」)。",
        "",
        "**重要 ルール**:",
        "1. primitive は DSL spec の 一覧 のみ 使用 (= 自由 key 不可)",
        "2. bonus は 500-2000 範囲",
        "3. priority 1 が 最優先 達成目標、 2/3 は fallback chain",
        "4. description で 日本語 戦略意図 を 簡潔に (= 1-2 文)",
        "5. opp_leader_id は 必ず opp_deck の leader_id を 設定",
        "6. self_condition は 'advantage' / 'even' / 'behind' のみ (= literal)",
        "",
        "**出力 形式** (= JSON、 余計な コメント なし):",
        "```json",
        "{",
        '  "matchup": {',
        '    "self_leader": "<self_leader_id>",',
        '    "opp_leader": "<opp_leader_id>",',
        '    "opp_deck_slug": "<opp_slug>"',
        "  },",
        '  "entries": [',
        '    {',
        '      "turn": 1, "opp_leader_id": "...", "opp_deck_slug": "...",',
        '      "self_condition": "even",',
        '      "targets": [',
        '        {"priority": 1, "if": {...}, "bonus": 1000, "description": "..."},',
        '        {"priority": 2, "if": {...}, "bonus": 500, "description": "..."}',
        "      ]",
        "    },",
        "    ... (× 30 entry)",
        "  ]",
        "}",
        "```",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------


def call_claude(cache_prefix: str, matchup_prompt: str, model: str = "claude-opus-4-7") -> str:
    """Claude API を 呼んで matchup の target spec text を 取得。"""
    import anthropic

    client = anthropic.Anthropic()

    system_msg = [
        {
            "type": "text",
            "text": "You are an expert One Piece TCG deck analyst writing AI strategy specifications. Always respond with valid JSON in the requested format.",
        },
    ]

    user_content = [
        {
            "type": "text",
            "text": cache_prefix,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": matchup_prompt,
        },
    ]

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system_msg,
        messages=[{"role": "user", "content": user_content}],
    )

    # text block 抽出
    text_parts = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
    return "\n".join(text_parts)


def extract_json(text: str) -> Optional[dict]:
    """Claude output から ```json ... ``` を 抜き出して parse。"""
    import re
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        # fallback: 全体が JSON か
        m = re.search(r"(\{.*\})", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def generate_target_spec(
    deck_slug: str,
    only_opp: Optional[str] = None,
    dry_run: bool = False,
    resume: bool = False,
    model: str = "claude-opus-4-7",
) -> Path:
    """1 deck の target spec を 生成。"""
    self_deck = load_deck(deck_slug)
    self_analysis = load_deck_analysis(deck_slug)
    cards = load_cards_lookup()
    effects = load_card_effects_lookup()
    roles = load_card_roles_lookup()

    cache_prefix = build_cache_prefix(self_deck, self_analysis, cards, effects, roles)

    out_path = DECKS_DIR / f"{deck_slug}.target_v1.json"
    existing: dict = {}
    if resume and out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    spec = existing if resume else {
        "deck_slug": deck_slug,
        "leader_id": self_deck.get("leader"),
        "archetype": (self_analysis or {}).get("archetype", ""),
        "generated_by": "Plan H generate_target_spec.py",
        "model": model,
        "entries": [],
    }
    done_matchups = set()
    if resume:
        for e in spec.get("entries", []):
            done_matchups.add(e.get("opp_leader_id"))

    opp_decks = list_all_opp_decks()
    if only_opp:
        opp_decks = [d for d in opp_decks if d["slug"] == only_opp]
        if not opp_decks:
            raise ValueError(f"opp_deck '{only_opp}' not found")

    print(f"self_deck: {deck_slug}", file=sys.stderr)
    print(f"opp_decks: {[d['slug'] for d in opp_decks]}", file=sys.stderr)
    print(f"cache_prefix size: ~{len(cache_prefix)} chars", file=sys.stderr)

    for i, opp_deck_meta in enumerate(opp_decks):
        opp_slug = opp_deck_meta["slug"]
        opp_leader_id = opp_deck_meta["leader"]
        if resume and opp_leader_id in done_matchups:
            print(f"  [{i+1}/{len(opp_decks)}] skip {opp_slug} (= already done)", file=sys.stderr)
            continue

        opp_deck = load_deck(opp_slug)
        matchup_cell = load_matchup_cell(deck_slug, opp_slug)
        matchup_prompt = build_matchup_user_prompt(opp_deck, cards, effects, roles, matchup_cell)

        print(f"  [{i+1}/{len(opp_decks)}] {opp_slug} (matchup_prompt ~{len(matchup_prompt)} chars)", file=sys.stderr)

        if dry_run:
            # dry run: prompt 出力 だけ
            dry_path = DECKS_DIR / f"{deck_slug}.target_v1.dry.{opp_slug}.txt"
            dry_path.write_text(
                cache_prefix + "\n\n=== MATCHUP PROMPT ===\n\n" + matchup_prompt,
                encoding="utf-8",
            )
            print(f"    dry → {dry_path.name}", file=sys.stderr)
            continue

        # call Claude API
        try:
            start = time.time()
            text = call_claude(cache_prefix, matchup_prompt, model=model)
            elapsed = time.time() - start
            print(f"    api ok ({elapsed:.1f}s, ~{len(text)} chars)", file=sys.stderr)
        except Exception as e:
            print(f"    api ERROR: {e}", file=sys.stderr)
            continue

        # parse JSON
        result = extract_json(text)
        if not result or "entries" not in result:
            print(f"    parse ERROR (no entries)", file=sys.stderr)
            # 失敗 raw を 保存
            raw_path = DECKS_DIR / f"{deck_slug}.target_v1.raw.{opp_slug}.txt"
            raw_path.write_text(text, encoding="utf-8")
            continue

        # entries に opp_leader_id / opp_deck_slug を 設定 (= Claude が 抜けても 補完)
        for e in result["entries"]:
            e.setdefault("opp_leader_id", opp_leader_id)
            e.setdefault("opp_deck_slug", opp_slug)

        spec["entries"].extend(result["entries"])
        # incremental save (= 1 matchup ごと file 書き戻し)
        out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    saved: {len(result['entries'])} entries", file=sys.stderr)

    print(f"\ntotal entries: {len(spec.get('entries', []))}", file=sys.stderr)
    print(f"output: {out_path}", file=sys.stderr)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True, help="self deck slug")
    ap.add_argument("--only-opp", default=None, help="特定 opp_deck slug のみ (= debug)")
    ap.add_argument("--dry-run", action="store_true", help="prompt 出力 だけ、 API call せず")
    ap.add_argument("--resume", action="store_true", help="既存 出力 を 読んで 未完成 のみ")
    ap.add_argument("--model", default="claude-opus-4-7")
    args = ap.parse_args()

    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY env not set (= use --dry-run for testing)", file=sys.stderr)
        sys.exit(1)

    generate_target_spec(
        deck_slug=args.deck,
        only_opp=args.only_opp,
        dry_run=args.dry_run,
        resume=args.resume,
        model=args.model,
    )


if __name__ == "__main__":
    main()
