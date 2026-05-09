# -*- coding: utf-8 -*-
"""
FastAPI ラッパー - 既存の engine を HTTP API として公開する。

起動:
    cd onepiece_research
    pip install fastapi uvicorn
    uvicorn api.main:app --reload --port 8000

Next.js 側からは fetch("http://localhost:8000/api/cards") のように叩く。
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, make_deck_from_dict  # noqa: E402
from engine.deckbuilder import build_with_core  # noqa: E402
from engine.harness import run_matchup  # noqa: E402

app = FastAPI(title="One Piece Research API", version="0.2")

# Next.js dev server からのアクセスを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 起動時にカードリポジトリを1回だけロード
_repo: Optional[CardRepository] = None


def get_repo() -> CardRepository:
    global _repo
    if _repo is None:
        _repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    return _repo


# --------------------------------------------------------------------------- #
# レスポンスモデル
# --------------------------------------------------------------------------- #
class CardOut(BaseModel):
    card_id: str
    name: str
    category: str
    color: list[str]
    cost: int
    life: int
    power: int
    counter: int
    attribute: str
    block_icon: int
    features: list[str]
    text: str
    trigger: str
    rarity: str
    image_url: Optional[str] = None


def _to_out(card) -> CardOut:
    # CardDef は image_url を持っていないので空欄
    return CardOut(
        card_id=card.card_id,
        name=card.name,
        category=card.category.value,
        color=list(card.color),
        cost=card.cost,
        life=card.life,
        power=card.power,
        counter=card.counter,
        attribute=card.attribute,
        block_icon=card.block_icon,
        features=list(card.features),
        text=card.text,
        trigger=card.trigger,
        rarity=card.rarity,
    )


# --------------------------------------------------------------------------- #
# エンドポイント: cards
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {"ok": True, "cards": len(get_repo()._by_id)}


# --------------------------------------------------------------------------- #
# エンドポイント: meta matchup matrix (事前計算)
# --------------------------------------------------------------------------- #
_MATRIX_PATH = ROOT / "db" / "matchup_matrix.json"


@app.get("/api/meta/matrix")
def meta_matrix():
    """事前計算された全 N×N 勝率マトリックス。
    `scripts/compute_matchup_matrix.py` で更新する。"""
    if not _MATRIX_PATH.exists():
        raise HTTPException(404, "matchup_matrix.json が無い: scripts/compute_matchup_matrix.py を実行してください")
    return json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# エンドポイント: FAQ search (db/faq/*.json から横断検索)
# --------------------------------------------------------------------------- #
FAQ_DIR = ROOT / "db" / "faq"


class FaqHit(BaseModel):
    source: str          # ファイル名 (e.g. "base.json", "cardqa_op_07.json")
    category: str        # 表示用 (e.g. "基本ルール", "ブースターパック 500年後の未来【OP-07】")
    q: str
    a: str


_faq_cache: Optional[list[dict]] = None


def _load_faq_corpus() -> list[dict]:
    """db/faq/*.json を全部メモリにロードして flat list を返す。"""
    global _faq_cache
    if _faq_cache is not None:
        return _faq_cache
    out: list[dict] = []
    if not FAQ_DIR.exists():
        _faq_cache = out
        return out
    for path in sorted(FAQ_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        category = data.get("category") or data.get("series") or path.stem
        for item in data.get("items", []):
            out.append({
                "source": path.name,
                "category": category,
                "q": item.get("q", ""),
                "a": item.get("a", ""),
            })
    _faq_cache = out
    return out


@app.get("/api/faq/search", response_model=list[FaqHit])
def faq_search(
    q: str = Query("", description="検索クエリ (空白区切り AND マッチ)"),
    source_prefix: Optional[str] = Query(
        None,
        description="ソース絞り込み: 'base'/'keyword_effect'/'keyword'/'detail'/'cardqa_op_07' 等",
    ),
    limit: int = Query(50, ge=1, le=500),
):
    corpus = _load_faq_corpus()
    tokens = [t for t in q.strip().split() if t]

    matches: list[FaqHit] = []
    for item in corpus:
        if source_prefix and not item["source"].startswith(source_prefix):
            continue
        if tokens:
            haystack = item["q"] + "\n" + item["a"]
            if not all(t in haystack for t in tokens):
                continue
        matches.append(FaqHit(**item))
        if len(matches) >= limit:
            break
    return matches


@app.get("/api/faq/by-card/{card_id}", response_model=list[FaqHit])
def faq_by_card(card_id: str, limit: int = Query(30, ge=1, le=200)):
    """指定カードに言及している Q&A を返す。

    マッチ条件:
    - card_id (or base_id) が q/a に明示
    - またはカード名 (cards.json から) が q/a に一致
    - source ファイル名 (cardqa_<弾コード>) が card_id の弾コードに含まれる場合は
      その弾の Q&A はやや甘い検索 (カード名 OR card_id) で返す
    """
    corpus = _load_faq_corpus()
    base = card_id.split("_", 1)[0]

    # カード名取得
    card_name = ""
    try:
        c = get_repo().get(card_id)
        card_name = c.name
    except KeyError:
        pass

    # 弾コード抽出 (例: 'OP15-058' → 'op_15')
    series_match = re.match(r"^([A-Z]+)(\d+)-", base)
    series_slug = ""
    if series_match:
        series_slug = f"cardqa_{series_match.group(1).lower()}_{int(series_match.group(2)):02d}"

    matches: list[FaqHit] = []
    for item in corpus:
        haystack = item["q"] + "\n" + item["a"]
        # 1. card_id 直書き
        if base in haystack or card_id in haystack:
            matches.append(FaqHit(**item))
        # 2. カード名 + 同じ弾の cardqa
        elif card_name and series_slug and item["source"].startswith(series_slug) and card_name in haystack:
            matches.append(FaqHit(**item))
        if len(matches) >= limit:
            break
    return matches


@app.get("/api/faq/sources")
def faq_sources():
    """利用可能な FAQ ソースの一覧 (件数付き)。"""
    out: list[dict] = []
    if not FAQ_DIR.exists():
        return out
    for path in sorted(FAQ_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "source": path.name,
            "category": data.get("category") or data.get("series") or path.stem,
            "count": len(data.get("items", [])),
        })
    return out


@app.get("/api/cards", response_model=list[CardOut])
def list_cards(
    color: Optional[str] = Query(None, description="赤/青/緑/紫/黒/黄"),
    category: Optional[str] = Query(None, description="LEADER/CHARACTER/EVENT/STAGE"),
    feature: Optional[str] = Query(None, description="特徴(部分一致)"),
    cost_le: Optional[int] = Query(None),
    cost_ge: Optional[int] = Query(None),
    name_contains: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
):
    repo = get_repo()
    cards = []
    seen: set[str] = set()
    for cid, card in repo._by_id.items():
        if card.card_id in seen:
            continue
        seen.add(card.card_id)
        if color and color not in card.color:
            continue
        if category and card.category.value != category:
            continue
        if feature and not any(feature in f for f in card.features):
            continue
        if cost_le is not None and card.cost > cost_le:
            continue
        if cost_ge is not None and card.cost < cost_ge:
            continue
        if name_contains and name_contains not in card.name:
            continue
        cards.append(_to_out(card))
        if len(cards) >= limit:
            break
    return cards


@app.get("/api/cards/{card_id}", response_model=CardOut)
def get_card(card_id: str):
    try:
        c = get_repo().get(card_id)
    except KeyError:
        raise HTTPException(404, f"card not found: {card_id}")
    return _to_out(c)


# --------------------------------------------------------------------------- #
# エンドポイント: decks (decks/*.json をディレクトリから読む)
# --------------------------------------------------------------------------- #
DECKS_DIR = ROOT / "decks"


class DeckEntry(BaseModel):
    card_id: str
    count: int


class DeckSpec(BaseModel):
    leader: str
    main: list[DeckEntry]
    name: Optional[str] = None


class DeckSummary(BaseModel):
    slug: str
    name: str
    leader: str
    leader_name: str
    leader_color: list[str]
    main_count: int
    unique: int


def _list_deck_files() -> list[Path]:
    if not DECKS_DIR.exists():
        return []
    return sorted(DECKS_DIR.glob("*.json"))


def _load_deck_json(slug: str) -> dict:
    path = DECKS_DIR / f"{slug}.json"
    if not path.exists():
        raise HTTPException(404, f"deck not found: {slug}")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/decks", response_model=list[DeckSummary])
def list_decks():
    repo = get_repo()
    out: list[DeckSummary] = []
    for path in _list_deck_files():
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        slug = d.get("slug") or path.stem
        leader_id = d.get("leader", "")
        leader_name = ""
        leader_color: list[str] = []
        try:
            leader_card = repo.get(leader_id)
            leader_name = leader_card.name
            leader_color = list(leader_card.color)
        except KeyError:
            pass
        main_count = sum(int(e.get("count", 1)) for e in d.get("main", []))
        unique = len(d.get("main", []))
        out.append(
            DeckSummary(
                slug=slug,
                name=d.get("name", slug),
                leader=leader_id,
                leader_name=leader_name,
                leader_color=leader_color,
                main_count=main_count,
                unique=unique,
            )
        )
    return out


@app.get("/api/decks/{slug}")
def get_deck(slug: str):
    return _load_deck_json(slug)


# --------------------------------------------------------------------------- #
# エンドポイント: デッキ保存 (新規作成 / 上書き)
# --------------------------------------------------------------------------- #
class CreateDeckRequest(BaseModel):
    name: str
    leader: str
    main: list[DeckEntry]
    slug: Optional[str] = None
    overwrite: bool = False


class CreateDeckResponse(BaseModel):
    slug: str
    path: str
    warnings: list[str]


def _slugify(s: str) -> str:
    """name から英数字スラグを生成。日本語は失敗 (空文字)、呼び出し側で fallback。"""
    s = re.sub(r"[^\w-]+", "_", (s or "").strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s


@app.post("/api/decks", response_model=CreateDeckResponse, status_code=201)
def create_deck(req: CreateDeckRequest):
    """ユーザ作成デッキを `decks/<slug>.json` として保存。

    - slug 未指定時は name → ASCII slug → 失敗時は `user_<unix秒>` でフォールバック
    - validate (50枚, 4枚制限, 銀リスト) を必ず通過すること
    - overwrite=False (default) で既存 slug 衝突は 409
    """
    repo = get_repo()
    if not req.leader:
        raise HTTPException(400, "leader is required")
    if not req.main:
        raise HTTPException(400, "main is empty")

    deck_dict = {
        "name": req.name or "(無題)",
        "leader": req.leader,
        "main": [{"card_id": e.card_id, "count": e.count} for e in req.main],
    }
    try:
        deck = make_deck_from_dict(deck_dict, repo)
    except KeyError as e:
        raise HTTPException(400, f"unknown card: {e}")
    except Exception as e:
        raise HTTPException(400, f"deck build failed: {e}")

    errors = deck.validate()
    if errors:
        raise HTTPException(422, {"errors": errors})

    slug = req.slug or _slugify(req.name)
    if not slug:
        slug = f"user_{int(datetime.now(timezone.utc).timestamp())}"

    out_path = DECKS_DIR / f"{slug}.json"
    if out_path.exists() and not req.overwrite:
        raise HTTPException(409, f"slug already exists: {slug}")

    deck_dict["slug"] = slug
    deck_dict["source"] = "user"
    deck_dict["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    DECKS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(deck_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CreateDeckResponse(
        slug=slug, path=str(out_path.relative_to(ROOT)), warnings=[]
    )


class ValidateDeckResponse(BaseModel):
    ok: bool
    errors: list[str]


@app.post("/api/decks/validate", response_model=ValidateDeckResponse)
def validate_deck(req: CreateDeckRequest):
    """保存せず validate だけ実行 (UI のリアルタイム検証用)。"""
    repo = get_repo()
    if not req.leader:
        return ValidateDeckResponse(ok=False, errors=["leader is required"])
    if not req.main:
        return ValidateDeckResponse(ok=False, errors=["main is empty"])
    deck_dict = {
        "name": req.name or "(無題)",
        "leader": req.leader,
        "main": [{"card_id": e.card_id, "count": e.count} for e in req.main],
    }
    try:
        deck = make_deck_from_dict(deck_dict, repo)
    except KeyError as e:
        return ValidateDeckResponse(ok=False, errors=[f"unknown card: {e}"])
    except Exception as e:
        return ValidateDeckResponse(ok=False, errors=[f"deck build failed: {e}"])
    errors = deck.validate()
    return ValidateDeckResponse(ok=not errors, errors=errors)


# --------------------------------------------------------------------------- #
# エンドポイント: コアカード固定型 デッキ自動構築
# --------------------------------------------------------------------------- #
class CoreBuildRequest(BaseModel):
    leader: str                                  # リーダー card_id
    core_cards: list[str] = []                   # 必ず採用するコアカード ID
    core_counts: dict[str, int] = {}             # 個別の枚数指定 {card_id: count}
    name: Optional[str] = None
    seed: int = 0


class CoreBuildResponse(BaseModel):
    name: str
    leader: str
    leader_name: str
    main: list[DeckEntry]
    warnings: list[str]
    effect_density: int                          # main のうち overlay 持ちカード枚数
    counter_total: int                           # main のカウンター値合計


@app.post("/api/decks/build", response_model=CoreBuildResponse)
def build_deck(req: CoreBuildRequest):
    """コアカード固定型のデッキビルダー (Phase 5 の完全版)。"""
    import random as _random
    from collections import Counter as _Counter

    repo = get_repo()
    try:
        deck, warnings = build_with_core(
            leader_id=req.leader,
            core_card_ids=req.core_cards,
            repo=repo,
            core_counts=req.core_counts,
            rng=_random.Random(req.seed),
            name=req.name,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"build failed: {e}")

    issues = deck.validate()
    if issues:
        warnings.append(f"validate: {'; '.join(issues)}")

    # main を DeckEntry に変換 (枚数集計)
    counts = _Counter(c.card_id for c in deck.main)
    main_entries = [
        DeckEntry(card_id=cid, count=n)
        for cid, n in sorted(counts.items())
    ]

    # overlay カバレッジ集計
    from engine.deckbuilder import _load_effect_keys
    effect_keys = _load_effect_keys()
    effect_density = sum(
        n for cid, n in counts.items() if cid in effect_keys
    )
    counter_total = sum(c.counter for c in deck.main)

    return CoreBuildResponse(
        name=deck.name,
        leader=deck.leader.card_id,
        leader_name=deck.leader.name,
        main=main_entries,
        warnings=warnings,
        effect_density=effect_density,
        counter_total=counter_total,
    )


# --------------------------------------------------------------------------- #
# エンドポイント: deck analyze
# --------------------------------------------------------------------------- #
class CountByLabel(BaseModel):
    label: str
    count: int


class CardRef(BaseModel):
    card_id: str
    name: str


class DeckAnalysis(BaseModel):
    slug: str
    name: str
    leader: str
    leader_name: str
    main_count: int
    color_dist: list[CountByLabel]
    cost_curve: list[CountByLabel]
    feature_top: list[CountByLabel]
    counter_dist: list[CountByLabel]
    avg_power: float
    avg_cost: float
    avg_counter: float
    activate_main_cards: list[CardRef]


_OVERLAY_PATH = ROOT / "db" / "card_effects.json"


def _load_overlay_keys_with_kind() -> dict[str, set[str]]:
    """card_id -> {when, ...} の dict を返す (例: {"OP01-013": {"activate_main"}})。"""
    if not _OVERLAY_PATH.exists():
        return {}
    raw = json.loads(_OVERLAY_PATH.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for cid, effects in raw.items():
        if cid.startswith("_") or not isinstance(effects, list):
            continue
        whens = set()
        for eff in effects:
            w = eff.get("when")
            if isinstance(w, str):
                whens.add(w)
        out[cid] = whens
    return out


@app.get("/api/decks/{slug}/analyze", response_model=DeckAnalysis)
def analyze_deck(slug: str):
    d = _load_deck_json(slug)
    repo = get_repo()
    overlay = _load_overlay_keys_with_kind()

    color_count: dict[str, int] = {}
    cost_count: dict[int, int] = {}
    feature_count: dict[str, int] = {}
    counter_count: dict[int, int] = {}
    activate_main: list[CardRef] = []
    seen_activate: set[str] = set()

    total_power = 0
    total_cost = 0
    total_counter = 0
    total_n = 0

    for entry in d.get("main", []):
        cid = entry["card_id"]
        n = int(entry.get("count", 1))
        try:
            card = repo.get(cid)
        except KeyError:
            continue
        for c in card.color:
            color_count[c] = color_count.get(c, 0) + n
        cost_count[card.cost] = cost_count.get(card.cost, 0) + n
        for f in card.features:
            feature_count[f] = feature_count.get(f, 0) + n
        counter_count[card.counter] = counter_count.get(card.counter, 0) + n
        total_power += card.power * n
        total_cost += card.cost * n
        total_counter += card.counter * n
        total_n += n

        if "activate_main" in overlay.get(cid, set()) and cid not in seen_activate:
            activate_main.append(CardRef(card_id=cid, name=card.name))
            seen_activate.add(cid)

    leader_id = d.get("leader", "")
    leader_name = ""
    try:
        leader_name = repo.get(leader_id).name
    except KeyError:
        pass

    return DeckAnalysis(
        slug=slug,
        name=d.get("name", slug),
        leader=leader_id,
        leader_name=leader_name,
        main_count=total_n,
        color_dist=[
            CountByLabel(label=c, count=n)
            for c, n in sorted(color_count.items(), key=lambda x: -x[1])
        ],
        cost_curve=[
            CountByLabel(label=str(cost), count=cost_count.get(cost, 0))
            for cost in range(0, 11)
        ],
        feature_top=[
            CountByLabel(label=f, count=n)
            for f, n in sorted(feature_count.items(), key=lambda x: -x[1])[:10]
        ],
        counter_dist=[
            CountByLabel(label=str(v), count=counter_count.get(v, 0))
            for v in (0, 1000, 2000)
        ],
        avg_power=total_power / total_n if total_n else 0,
        avg_cost=total_cost / total_n if total_n else 0,
        avg_counter=total_counter / total_n if total_n else 0,
        activate_main_cards=activate_main,
    )


# --------------------------------------------------------------------------- #
# エンドポイント: match
# --------------------------------------------------------------------------- #
class MatchRequest(BaseModel):
    deck_a: Optional[DeckSpec] = None
    deck_b: Optional[DeckSpec] = None
    deck_a_id: Optional[str] = None  # decks/{slug}.json
    deck_b_id: Optional[str] = None
    n_games: int = 50
    seed: int = 42


class MatchSummary(BaseModel):
    job_id: str
    deck_a_name: str
    deck_b_name: str
    deck_a_winrate: float
    deck_a_wins: int
    deck_b_wins: int
    draws: int
    n_games: int
    avg_turns: float
    median_turns: float
    avg_life_left_winner: float
    deck_a_first_wins: int
    deck_a_second_wins: int


class GameLog(BaseModel):
    """個別試合の結果 + ログ。"""
    index: int
    winner: int                   # 0 (deck_a) / 1 (deck_b) / -1 (draw)
    first_player: int             # 0 (deck_a 先攻) / 1 (deck_b 先攻)
    turns: int
    actions: int
    p0_life_left: int
    p1_life_left: int
    p0_field: int
    p1_field: int
    log: list[str] = []


# ジョブストア (LRU 風、最大 _MAX_JOBS 件)
_MATCH_JOBS: "OrderedDict[str, dict]" = OrderedDict()
_MAX_JOBS = 10

# 対戦履歴 (永続化 jsonl)
_HISTORY_PATH = ROOT / "db" / "match_history.jsonl"


class MatchHistoryEntry(BaseModel):
    timestamp: str               # ISO8601 UTC
    job_id: str
    deck_a_name: str
    deck_b_name: str
    deck_a_id: Optional[str] = None
    deck_b_id: Optional[str] = None
    n_games: int
    seed: int
    deck_a_winrate: float
    deck_a_wins: int
    deck_b_wins: int
    draws: int
    avg_turns: float


def _append_history(entry: MatchHistoryEntry) -> None:
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry.model_dump(), ensure_ascii=False) + "\n")


def _read_history(limit: int = 50) -> list[dict]:
    if not _HISTORY_PATH.exists():
        return []
    lines = _HISTORY_PATH.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict] = []
    # 末尾から limit 件
    for ln in reversed(lines[-(limit * 2):]):
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out


def _resolve_deck(spec: Optional[DeckSpec], slug: Optional[str], side: str) -> dict:
    if spec is not None:
        return {
            "name": spec.name or f"deck_{side}",
            "leader": spec.leader,
            "main": [{"card_id": e.card_id, "count": e.count} for e in spec.main],
        }
    if slug:
        d = _load_deck_json(slug)
        d.setdefault("name", slug)
        return d
    raise HTTPException(400, f"deck_{side} もしくは deck_{side}_id を指定してください")


def _summary_from_report(job_id: str, report) -> MatchSummary:
    return MatchSummary(
        job_id=job_id,
        deck_a_name=report.deck1_name,
        deck_b_name=report.deck2_name,
        deck_a_winrate=report.deck1_winrate,
        deck_a_wins=report.deck1_wins,
        deck_b_wins=report.deck2_wins,
        draws=report.draws,
        n_games=report.n_games,
        avg_turns=report.avg_turns,
        median_turns=report.median_turns,
        avg_life_left_winner=report.avg_life_left_winner,
        deck_a_first_wins=report.deck1_first_wins,
        deck_a_second_wins=report.deck1_second_wins,
    )


@app.post("/api/match", response_model=MatchSummary)
def run_match(req: MatchRequest):
    repo = get_repo()

    deck_a_dict = _resolve_deck(req.deck_a, req.deck_a_id, "a")
    deck_b_dict = _resolve_deck(req.deck_b, req.deck_b_id, "b")

    try:
        deck_a = make_deck_from_dict(deck_a_dict, repo)
        deck_b = make_deck_from_dict(deck_b_dict, repo)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"deck build failed: {e}")

    a_issues = deck_a.validate()
    b_issues = deck_b.validate()
    if a_issues or b_issues:
        raise HTTPException(
            400,
            f"deck validation failed: a={a_issues}, b={b_issues}",
        )

    report = run_matchup(
        deck_a, deck_b,
        n_games=req.n_games,
        seed=req.seed,
        keep_logs=True,
    )

    job_id = uuid.uuid4().hex[:12]
    _MATCH_JOBS[job_id] = {"report": report}
    while len(_MATCH_JOBS) > _MAX_JOBS:
        _MATCH_JOBS.popitem(last=False)

    # 永続履歴に追記
    _append_history(MatchHistoryEntry(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        job_id=job_id,
        deck_a_name=report.deck1_name,
        deck_b_name=report.deck2_name,
        deck_a_id=req.deck_a_id,
        deck_b_id=req.deck_b_id,
        n_games=req.n_games,
        seed=req.seed,
        deck_a_winrate=report.deck1_winrate,
        deck_a_wins=report.deck1_wins,
        deck_b_wins=report.deck2_wins,
        draws=report.draws,
        avg_turns=report.avg_turns,
    ))

    return _summary_from_report(job_id, report)


@app.get("/api/match/history", response_model=list[MatchHistoryEntry])
def match_history(
    deck_id: Optional[str] = Query(None, description="このデッキ slug が a か b に含まれるエントリだけに絞る"),
    limit: int = Query(50, ge=1, le=500),
):
    rows = _read_history(limit=limit * 3 if deck_id else limit)
    if deck_id:
        rows = [r for r in rows if r.get("deck_a_id") == deck_id or r.get("deck_b_id") == deck_id]
    return rows[:limit]


@app.get("/api/match/{job_id}", response_model=MatchSummary)
def get_match_summary(job_id: str):
    job = _MATCH_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"match job not found: {job_id}")
    return _summary_from_report(job_id, job["report"])


@app.get("/api/match/{job_id}/games", response_model=list[GameLog])
def list_match_games(job_id: str):
    job = _MATCH_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"match job not found: {job_id}")
    return [
        GameLog(
            index=i,
            winner=g.winner,
            first_player=g.first_player,
            turns=g.turns,
            actions=g.actions,
            p0_life_left=g.p0_life_left,
            p1_life_left=g.p1_life_left,
            p0_field=g.p0_field,
            p1_field=g.p1_field,
            log=[],  # 概要では log は省く
        )
        for i, g in enumerate(job["report"].games)
    ]


@app.get("/api/match/{job_id}/games/{game_index}", response_model=GameLog)
def get_match_game(job_id: str, game_index: int):
    job = _MATCH_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"match job not found: {job_id}")
    games = job["report"].games
    if game_index < 0 or game_index >= len(games):
        raise HTTPException(404, f"game index out of range: {game_index}")
    g = games[game_index]
    return GameLog(
        index=game_index,
        winner=g.winner,
        first_player=g.first_player,
        turns=g.turns,
        actions=g.actions,
        p0_life_left=g.p0_life_left,
        p1_life_left=g.p1_life_left,
        p0_field=g.p0_field,
        p1_field=g.p1_field,
        log=list(g.log),
    )
