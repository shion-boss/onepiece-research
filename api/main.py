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
from engine.effects import load_effect_overlay  # noqa: E402
from engine.harness import run_matchup  # noqa: E402

app = FastAPI(title="One Piece Research API", version="0.2")


@app.on_event("startup")
def _on_startup():
    """API server 起動時: "running" 状態の研究セッションを auto-resume。

    dev server --reload で thread が消失した場合の復活機構。
    """
    try:
        from engine.research_session import auto_resume_on_startup
        n = auto_resume_on_startup()
        if n > 0:
            print(f"[startup] Resumed {n} research session(s) from DB")
    except Exception as e:
        print(f"[startup] auto_resume failed: {e}")

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
# エンドポイント: banlist
# --------------------------------------------------------------------------- #
_BANLIST_PATH = ROOT / "db" / "banlist" / "master.json"


@app.get("/api/banlist")
def get_banlist():
    """禁止 / 制限 / 禁止ペア + standard_min_block を返す。"""
    if not _BANLIST_PATH.exists():
        raise HTTPException(404, "banlist not found")
    return json.loads(_BANLIST_PATH.read_text(encoding="utf-8"))


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
    block_icon_ge: Optional[int] = Query(None, description="ブロックアイコン下限 (Standard=2)"),
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
        if block_icon_ge is not None and card.block_icon < block_icon_ge:
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


# 全カードの primary_role を card_id → role の compact map で返す。
# board_eval (chara_quality / hand_quality) の TS 側計算用 (R69)。
# 元 db/card_roles.json は 2MB 超だが、 primary_role のみなら ~200KB。
@app.get("/api/cards/roles")
def get_card_roles():
    from engine import card_role as _cr
    db = _cr.load_card_role_db()
    out: dict[str, str] = {}
    for cid, v in db.items():
        if cid.startswith("_"):  # _meta 等のメタキー除外
            continue
        if isinstance(v, dict):
            role = v.get("primary_role")
            if isinstance(role, str):
                out[cid] = role
    return out


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
    regulation: Optional[str] = None


def _list_deck_files() -> list[Path]:
    if not DECKS_DIR.exists():
        return []
    # *.analysis.json は分析メタデータなのでデッキ本体から除外
    return sorted(
        p for p in DECKS_DIR.glob("*.json") if not p.name.endswith(".analysis.json")
    )


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
                regulation=d.get("regulation"),
            )
        )
    return out


@app.get("/api/decks/{slug}")
def get_deck(slug: str):
    return _load_deck_json(slug)


@app.get("/api/decks/{slug}/strategy")
def get_deck_strategy(slug: str):
    """静的デッキ分析 (戦略 / マリガン / 理想ムーブ / 弱点 / キーカード / AI ヒント)。

    `decks/<slug>.analysis.json` があればそれを返す (高速)。
    なければ即時生成して返す (= cache miss でも軽量、 動的対戦不要)。
    """
    from dataclasses import asdict
    from engine.deck_analyzer import analyze_deck

    deck_path = DECKS_DIR / f"{slug}.json"
    if not deck_path.exists():
        raise HTTPException(404, f"deck not found: {slug}")

    cache_path = DECKS_DIR / f"{slug}.analysis.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass  # cache 壊れていれば再生成

    # 即時生成
    repo = get_repo()
    try:
        deck = make_deck_from_dict(json.loads(deck_path.read_text(encoding="utf-8")), repo)
    except Exception as e:
        raise HTTPException(500, f"deck load failed: {e}")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    analysis = analyze_deck(deck, overlay)
    d = asdict(analysis)
    d["top_features"] = [list(t) for t in d.get("top_features", [])]
    return d


# --------------------------------------------------------------------------- #
# エンドポイント: デッキ保存 (新規作成 / 上書き)
# --------------------------------------------------------------------------- #
class CreateDeckRequest(BaseModel):
    name: str
    leader: str
    main: list[DeckEntry]
    slug: Optional[str] = None
    overwrite: bool = False
    regulation: str = "standard"


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
        "regulation": req.regulation,
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


@app.put("/api/decks/{slug}", response_model=CreateDeckResponse)
def update_deck(slug: str, req: CreateDeckRequest):
    """デッキ上書き保存。slug 必須、existing でない場合は 404。validate 必須。"""
    out_path = DECKS_DIR / f"{slug}.json"
    if not out_path.exists():
        raise HTTPException(404, f"deck not found: {slug}")
    repo = get_repo()
    if not req.leader:
        raise HTTPException(400, "leader is required")
    if not req.main:
        raise HTTPException(400, "main is empty")

    deck_dict = {
        "name": req.name or "(無題)",
        "leader": req.leader,
        "main": [{"card_id": e.card_id, "count": e.count} for e in req.main],
        "regulation": req.regulation,
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

    deck_dict["slug"] = slug
    deck_dict["source"] = "user"
    deck_dict["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_path.write_text(
        json.dumps(deck_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CreateDeckResponse(
        slug=slug, path=str(out_path.relative_to(ROOT)), warnings=[]
    )


@app.delete("/api/decks/{slug}", status_code=204)
def delete_deck(slug: str):
    """デッキ削除。cardrush_* (大会上位由来) は保護。"""
    if slug.startswith("cardrush_"):
        raise HTTPException(403, "cardrush_* decks are protected (meta source)")
    out_path = DECKS_DIR / f"{slug}.json"
    if not out_path.exists():
        raise HTTPException(404, f"deck not found: {slug}")
    out_path.unlink()
    return None


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
        "regulation": req.regulation,
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
# エンドポイント: explore counter decks (Phase B.5)
# --------------------------------------------------------------------------- #
class ExploreCounterRequest(BaseModel):
    target_slug: str
    leader_filter: Optional[list[str]] = None
    must_include: Optional[list[str]] = None
    n_candidates: int = 20


class CounterCandidateOut(BaseModel):
    rank: int
    leader: str
    leader_name: str
    archetype: str
    estimated_score: int
    rationale: list[str]
    role_distribution: dict[str, int]
    main: list[DeckEntry]
    regulation_required: str           # "standard" or "extra" (= block-1 含むなら extra)
    extra_only_cards: list[str]        # block-1 のみ (Standard 使用不可) のカード ID list


class ExploreCounterResponse(BaseModel):
    target_slug: str
    target_name: str
    n_generated: int
    candidates: list[CounterCandidateOut]


@app.post("/api/explore/counter-decks", response_model=ExploreCounterResponse)
def explore_counter_decks(req: ExploreCounterRequest):
    """対策デッキ候補を N 件生成 (engine.explorer.generate_counter_candidates ラッパー)。

    target_slug の deck JSON が無ければ 404。 explorer 内部で発生する例外は
    422 (= 候補不足、 リーダー枚挙失敗 等) で返す。
    """
    from collections import Counter as _Counter
    from engine.explorer import generate_counter_candidates

    # target deck をロード
    target_path = DECKS_DIR / f"{req.target_slug}.json"
    if not target_path.exists():
        raise HTTPException(404, f"target deck not found: {req.target_slug}")
    repo = get_repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    try:
        target_deck = make_deck_from_dict(
            json.loads(target_path.read_text(encoding="utf-8")), repo
        )
    except Exception as e:
        raise HTTPException(422, f"target deck load failed: {e}")

    try:
        candidates = generate_counter_candidates(
            target_deck, repo, overlay,
            n_candidates=max(1, min(req.n_candidates, 50)),
            leader_filter=req.leader_filter,
            must_include=req.must_include,
            diversity="archetype",
        )
    except Exception as e:
        raise HTTPException(500, f"explore failed: {e}")

    # Standard 規制 判定用 (= block-1 のみのカードは Extra 必須)
    from engine.deck import _load_max_block_by_base_id, _base_id, _load_banlist
    max_block_map = _load_max_block_by_base_id()
    banlist = _load_banlist() or {}
    standard_min_block = banlist.get("standard_min_block", 2)

    out_candidates: list[CounterCandidateOut] = []
    for rank, cand in enumerate(candidates, 1):
        counts = _Counter(c.card_id for c in cand.deck.main)
        main_entries = [
            DeckEntry(card_id=cid, count=n)
            for cid, n in sorted(counts.items())
        ]
        # 各カードの Standard 使用可否を判定
        extra_only: list[str] = []
        for cid in counts:
            try:
                card = repo.get(cid)
                bid = _base_id(cid)
                max_block = max_block_map.get(bid, card.block_icon)
                if max_block < standard_min_block:
                    extra_only.append(cid)
            except KeyError:
                continue
        regulation_required = "extra" if extra_only else "standard"

        out_candidates.append(CounterCandidateOut(
            rank=rank,
            leader=cand.leader_id,
            leader_name=cand.deck.leader.name,
            archetype=cand.archetype,
            estimated_score=cand.estimated_score,
            rationale=cand.rationale,
            role_distribution=cand.role_distribution,
            main=main_entries,
            regulation_required=regulation_required,
            extra_only_cards=extra_only,
        ))

    return ExploreCounterResponse(
        target_slug=req.target_slug,
        target_name=target_deck.name,
        n_generated=len(out_candidates),
        candidates=out_candidates,
    )


# --------------------------------------------------------------------------- #
# エンドポイント: 研究セッション (Phase R)
# --------------------------------------------------------------------------- #
class ResearchSessionConfig(BaseModel):
    target_slug: str
    leader_filter: Optional[list[str]] = None
    must_include: Optional[list[str]] = None
    target_winrate: float = 0.7
    max_generations: int = 50
    n_games_per_eval: int = 50
    initial_population: int = 20
    mutations_per_top: int = 3
    top_k: int = 5
    seed: int = 42


class ResearchSessionStartResponse(BaseModel):
    session_id: str
    status: str


class ResearchSessionSummary(BaseModel):
    id: str
    target_slug: str
    status: str
    created_at: str
    updated_at: str
    current_generation: int
    best_winrate: Optional[float]
    completion_reason: Optional[str]


class ResearchGenerationHistory(BaseModel):
    generation: int
    n_candidates: int
    best_winrate: Optional[float]
    avg_winrate: Optional[float]


class ResearchSessionDetail(BaseModel):
    id: str
    target_slug: str
    config: dict
    status: str
    created_at: str
    updated_at: str
    current_generation: int
    best_winrate: Optional[float]
    best_deck: Optional[dict]
    completion_reason: Optional[str]
    generation_history: list[ResearchGenerationHistory]


class ResearchCandidate(BaseModel):
    id: int
    generation: int
    candidate_idx: int
    deck: dict
    parent_id: Optional[int]
    mutation_type: Optional[str]
    winrate: Optional[float]
    n_games: Optional[int]
    evaluated_at: Optional[str]


@app.post("/api/research/sessions", response_model=ResearchSessionStartResponse)
def start_research_session(config: ResearchSessionConfig):
    """新規研究セッション起動。 backend で thread spawn → 即時 session_id 返却。"""
    from engine.research_session import start_research

    target_path = DECKS_DIR / f"{config.target_slug}.json"
    if not target_path.exists():
        raise HTTPException(404, f"target deck not found: {config.target_slug}")

    session_id = start_research(
        target_slug=config.target_slug,
        leader_filter=config.leader_filter,
        must_include=config.must_include,
        target_winrate=config.target_winrate,
        max_generations=config.max_generations,
        n_games_per_eval=config.n_games_per_eval,
        initial_population=config.initial_population,
        mutations_per_top=config.mutations_per_top,
        top_k=config.top_k,
        seed=config.seed,
    )
    return ResearchSessionStartResponse(session_id=session_id, status="running")


@app.get("/api/research/sessions", response_model=list[ResearchSessionSummary])
def list_research_sessions(
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, regex="^(running|paused|completed|stopped)$"),
):
    from engine import research_storage
    sessions = research_storage.list_sessions(limit=limit, status=status)
    return [ResearchSessionSummary(**s) for s in sessions]


@app.get("/api/research/sessions/{session_id}", response_model=ResearchSessionDetail)
def get_research_session(session_id: str):
    from engine import research_storage
    s = research_storage.get_session(session_id)
    if s is None:
        raise HTTPException(404, f"session not found: {session_id}")
    history = research_storage.get_generation_history(session_id)
    return ResearchSessionDetail(
        id=s["id"],
        target_slug=s["target_slug"],
        config=s["config"],
        status=s["status"],
        created_at=s["created_at"],
        updated_at=s["updated_at"],
        current_generation=s["current_generation"],
        best_winrate=s["best_winrate"],
        best_deck=s["best_deck"],
        completion_reason=s["completion_reason"],
        generation_history=[ResearchGenerationHistory(**h) for h in history],
    )


@app.post("/api/research/sessions/{session_id}/pause")
def pause_research_session(session_id: str):
    from engine.research_session import pause_session
    if not pause_session(session_id):
        raise HTTPException(404, f"session not found or not active: {session_id}")
    return {"session_id": session_id, "status": "paused"}


@app.post("/api/research/sessions/{session_id}/resume")
def resume_research_session(session_id: str):
    from engine.research_session import resume_session
    if not resume_session(session_id):
        raise HTTPException(404, f"session not resumable: {session_id}")
    return {"session_id": session_id, "status": "running"}


@app.post("/api/research/sessions/{session_id}/stop")
def stop_research_session(session_id: str):
    from engine.research_session import stop_session
    if not stop_session(session_id):
        raise HTTPException(404, f"session not found: {session_id}")
    return {"session_id": session_id, "status": "stopped"}


@app.get("/api/research/sessions/{session_id}/best-deck")
def get_research_best_deck(session_id: str):
    from engine import research_storage
    best = research_storage.get_best_candidate(session_id)
    if best is None:
        raise HTTPException(404, f"no evaluated candidate yet for session: {session_id}")
    return {
        "session_id": session_id,
        "candidate_id": best["id"],
        "generation": best["generation"],
        "winrate": best["winrate"],
        "n_games": best["n_games"],
        "mutation_type": best["mutation_type"],
        "deck": best["deck"],
    }


@app.get("/api/research/sessions/{session_id}/candidates", response_model=list[ResearchCandidate])
def get_research_candidates(
    session_id: str,
    generation: Optional[int] = Query(None, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    from engine import research_storage
    cands = research_storage.get_candidates(
        session_id, generation=generation, only_evaluated=True, limit=limit,
    )
    return [ResearchCandidate(**c) for c in cands]


@app.delete("/api/research/sessions/{session_id}")
def delete_research_session(session_id: str):
    from engine import research_storage
    research_storage.delete_session(session_id)
    return {"session_id": session_id, "deleted": True}


# --------------------------------------------------------------------------- #
# エンドポイント: deck improvement (改善提案)
# --------------------------------------------------------------------------- #
class CardChangeOut(BaseModel):
    card_id: str
    delta: int
    name: str


class ProposalOut(BaseModel):
    proposal_id: str
    proposal_type: str                # "swap" | "count_decrease" | "count_increase"
    changes: list[CardChangeOut]
    reason: str
    impact_estimate: int


class CardStatOut(BaseModel):
    card_id: str
    name: str
    n_in_deck: int
    n_appearances: int
    n_total_plays: int
    winrate_when_played: float


class DeckImprovementsResponse(BaseModel):
    slug: str
    n_matches: int
    deck_winrate_baseline: float
    card_stats: list[CardStatOut]
    proposals: list[ProposalOut]


@app.get("/api/decks/{slug}/improvements", response_model=DeckImprovementsResponse)
def deck_improvements(slug: str):
    """指定デッキの過去対戦ログから改善提案を生成。

    対戦データが無い (= 0 試合) 場合は proposals=[] で返す (= UI 側で「対戦データ無し」 表示)。
    """
    from engine.deck_improver import compute_card_stats, generate_proposals

    deck_path = DECKS_DIR / f"{slug}.json"
    if not deck_path.exists():
        raise HTTPException(404, f"deck not found: {slug}")
    repo = get_repo()
    try:
        deck = make_deck_from_dict(json.loads(deck_path.read_text(encoding="utf-8")), repo)
    except Exception as e:
        raise HTTPException(422, f"deck load failed: {e}")

    stats, n_matches, baseline = compute_card_stats(slug, deck)
    proposals = generate_proposals(stats, deck, repo) if stats else []

    return DeckImprovementsResponse(
        slug=slug,
        n_matches=n_matches,
        deck_winrate_baseline=baseline,
        card_stats=[
            CardStatOut(
                card_id=s.card_id,
                name=s.name,
                n_in_deck=s.n_in_deck,
                n_appearances=s.n_appearances,
                n_total_plays=s.n_total_plays,
                winrate_when_played=s.winrate_when_played,
            )
            for s in stats
        ],
        proposals=[
            ProposalOut(
                proposal_id=p.proposal_id,
                proposal_type=p.proposal_type,
                changes=[CardChangeOut(card_id=c.card_id, delta=c.delta, name=c.name)
                         for c in p.changes],
                reason=p.reason,
                impact_estimate=p.impact_estimate,
            )
            for p in proposals
        ],
    )


class ApplyImprovementRequest(BaseModel):
    changes: list[CardChangeOut]


class ApplyImprovementResponse(BaseModel):
    slug: str
    main: list[DeckEntry]
    warnings: list[str]


@app.post("/api/decks/{slug}/apply-improvement", response_model=ApplyImprovementResponse)
def apply_improvement(slug: str, req: ApplyImprovementRequest):
    """改善提案 changes (= [card_id, delta] list) を適用してデッキを上書き保存。

    検証:
    - 全 delta の合計 = 0 (= main 50 枚を維持)
    - 適用後、 各カード 0〜4 枚
    - DeckList.validate() pass

    失敗時 422。
    """
    from collections import Counter as _Counter

    deck_path = DECKS_DIR / f"{slug}.json"
    if not deck_path.exists():
        raise HTTPException(404, f"deck not found: {slug}")

    deck_dict = json.loads(deck_path.read_text(encoding="utf-8"))

    # 現 main 集計
    counts: dict[str, int] = {}
    for entry in deck_dict.get("main", []):
        counts[entry["card_id"]] = counts.get(entry["card_id"], 0) + entry["count"]

    # delta 適用
    total_delta = 0
    for ch in req.changes:
        cur = counts.get(ch.card_id, 0)
        new = cur + ch.delta
        if new < 0:
            raise HTTPException(
                422,
                f"カード {ch.card_id} の枚数が負になる (現 {cur} + {ch.delta:+d} = {new})",
            )
        if new > 4:
            raise HTTPException(
                422,
                f"カード {ch.card_id} の枚数が 4 を超える (現 {cur} + {ch.delta:+d} = {new})",
            )
        if new == 0:
            counts.pop(ch.card_id, None)
        else:
            counts[ch.card_id] = new
        total_delta += ch.delta

    if total_delta != 0:
        raise HTTPException(
            422, f"changes の delta 合計が 0 でない (= main 枚数が変わる: {total_delta:+d})",
        )

    # 新 main 構築 + validate
    repo = get_repo()
    new_main = [
        DeckEntry(card_id=cid, count=n)
        for cid, n in sorted(counts.items())
    ]
    deck_dict["main"] = [m.model_dump() for m in new_main]
    try:
        deck = make_deck_from_dict(deck_dict, repo)
        issues = deck.validate()
        if issues:
            raise HTTPException(422, {"errors": issues})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"deck rebuild failed: {e}")

    # 上書き保存 + analysis 再生成
    deck_path.write_text(
        json.dumps(deck_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # analysis.json も再生成 (= 統計表示用)
    try:
        from dataclasses import asdict
        from engine.deck_analyzer import analyze_deck
        from engine.effects import load_effect_overlay
        overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
        analysis = analyze_deck(deck, overlay)
        d = asdict(analysis)
        d["top_features"] = [list(t) for t in d.get("top_features", [])]
        analysis_path = DECKS_DIR / f"{slug}.analysis.json"
        analysis_path.write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass  # analysis 再生成失敗は致命的でない

    return ApplyImprovementResponse(slug=slug, main=new_main, warnings=[])


# --------------------------------------------------------------------------- #
# エンドポイント: MCTS 思考ツリー (Phase B.7 戦い方の探索)
# --------------------------------------------------------------------------- #
class McctsGameRequest(BaseModel):
    opponent_slug: str
    seed: int = 42
    n_simulations: int = 30
    max_tree_depth: int = 2


class McctsTurnOut(BaseModel):
    turn: int
    player_idx: int
    action_index: int
    chosen_action_label: str
    root_tree: dict
    greedy_action_label: str = ""
    agree_with_greedy: bool = False
    mcts_confidence: float = 0.0


class McctsGameResponse(BaseModel):
    deck_mcts: str
    deck_opp: str
    seed: int
    n_simulations: int
    winner: Optional[int]
    total_turns: int
    total_actions: int
    mcts_turns: list[McctsTurnOut]


class CandidateDeckSpec(BaseModel):
    leader: str
    main: list[DeckEntry]
    name: Optional[str] = None


class RerankRequest(BaseModel):
    target_slug: str
    candidates: list[CandidateDeckSpec]
    seed: int = 42
    n_simulations: int = 10
    n_games_per_candidate: int = 1


class RerankResultOut(BaseModel):
    leader: str
    name: str
    original_index: int
    mcts_wins: int
    mcts_total: int
    mcts_winrate: float


class RerankResponse(BaseModel):
    target_slug: str
    target_name: str
    n_candidates: int
    n_games_per_candidate: int
    results: list[RerankResultOut]
    elapsed_seconds: float


@app.post("/api/explore/rerank-with-mcts", response_model=RerankResponse)
def rerank_with_mcts(req: RerankRequest):
    """対策候補デッキ list を MCTS で 1 試合ずつ評価 → MCTS 勝率順に rerank (U3)。

    実行時間: candidates 数 × n_simulations × turns で 5〜30 分。 frontend で
    progress 表示推奨。
    """
    import time as _time
    from engine.mcts_replay import play_mcts_game

    target_path = DECKS_DIR / f"{req.target_slug}.json"
    if not target_path.exists():
        raise HTTPException(404, f"target deck not found: {req.target_slug}")
    repo = get_repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    try:
        target_deck = make_deck_from_dict(json.loads(target_path.read_text(encoding="utf-8")), repo)
    except Exception as e:
        raise HTTPException(422, f"target deck load failed: {e}")

    n_sim = max(1, min(req.n_simulations, 30))
    n_games = max(1, min(req.n_games_per_candidate, 5))

    t0 = _time.time()
    results: list[RerankResultOut] = []
    for i, cand_spec in enumerate(req.candidates):
        # candidate を DeckList 化
        try:
            cand_deck = make_deck_from_dict({
                "name": cand_spec.name or f"candidate_{i}",
                "leader": cand_spec.leader,
                "main": [m.model_dump() for m in cand_spec.main],
                "regulation": "standard",
            }, repo)
        except Exception:
            results.append(RerankResultOut(
                leader=cand_spec.leader,
                name=cand_spec.name or f"candidate_{i}",
                original_index=i,
                mcts_wins=0,
                mcts_total=0,
                mcts_winrate=0.0,
            ))
            continue

        wins = 0
        total = 0
        for g in range(n_games):
            try:
                rec = play_mcts_game(
                    cand_deck, target_deck,
                    effects_overlay=overlay,
                    seed=req.seed + g,
                    n_simulations=n_sim,
                    max_tree_depth=1,  # rerank なのでツリー詳細不要
                )
                total += 1
                if rec.winner == 0:  # candidate (= MCTS player) が勝ち
                    wins += 1
            except Exception:
                continue

        winrate = wins / total if total > 0 else 0.0
        results.append(RerankResultOut(
            leader=cand_spec.leader,
            name=cand_spec.name or f"candidate_{i}",
            original_index=i,
            mcts_wins=wins,
            mcts_total=total,
            mcts_winrate=round(winrate, 3),
        ))

    # winrate 降順で rerank
    results.sort(key=lambda r: -r.mcts_winrate)
    return RerankResponse(
        target_slug=req.target_slug,
        target_name=target_deck.name,
        n_candidates=len(req.candidates),
        n_games_per_candidate=n_games,
        results=results,
        elapsed_seconds=round(_time.time() - t0, 2),
    )


class McctsImprovementsRequest(BaseModel):
    opponent_slug: str
    seed: int = 42
    n_simulations: int = 10


class McctsCardStatOut(BaseModel):
    card_id: str
    name: str
    n_in_deck: int
    mcts_plays: int
    greedy_plays: int
    mcts_preference: float       # -1..+1 (MCTS 好み度)


class McctsImprovementsResponse(BaseModel):
    slug: str
    opponent_slug: str
    n_mcts_turns: int
    card_stats: list[McctsCardStatOut]
    proposals: list[ProposalOut]


@app.post("/api/decks/{slug}/improvements/mcts", response_model=McctsImprovementsResponse)
def mcts_improvements(slug: str, req: McctsImprovementsRequest):
    """MCTS 1 試合を走らせ、 MCTS と Greedy のカード選好差分から追加提案を生成 (U2)。

    実行時間: n_simulations=10 で ~30-60 秒。 既存 improvements とは別系統。
    """
    from engine.deck_improver import generate_mcts_proposals

    deck_path = DECKS_DIR / f"{slug}.json"
    opp_path = DECKS_DIR / f"{req.opponent_slug}.json"
    if not deck_path.exists():
        raise HTTPException(404, f"deck not found: {slug}")
    if not opp_path.exists():
        raise HTTPException(404, f"opponent deck not found: {req.opponent_slug}")
    repo = get_repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    try:
        deck = make_deck_from_dict(json.loads(deck_path.read_text(encoding="utf-8")), repo)
        opp_deck = make_deck_from_dict(json.loads(opp_path.read_text(encoding="utf-8")), repo)
    except Exception as e:
        raise HTTPException(422, f"deck load failed: {e}")

    n_sim = max(1, min(req.n_simulations, 50))
    try:
        proposals, card_stats = generate_mcts_proposals(
            deck, opp_deck, repo,
            overlay=overlay,
            n_simulations=n_sim,
            seed=req.seed,
        )
    except Exception as e:
        raise HTTPException(500, f"mcts improvements failed: {e}")

    return McctsImprovementsResponse(
        slug=slug,
        opponent_slug=req.opponent_slug,
        n_mcts_turns=sum(s["mcts_plays"] + s["greedy_plays"] for s in card_stats),
        card_stats=[
            McctsCardStatOut(**s) for s in card_stats
        ],
        proposals=[
            ProposalOut(
                proposal_id=p.proposal_id,
                proposal_type=p.proposal_type,
                changes=[CardChangeOut(card_id=c.card_id, delta=c.delta, name=c.name)
                         for c in p.changes],
                reason=p.reason,
                impact_estimate=p.impact_estimate,
            )
            for p in proposals
        ],
    )


@app.post("/api/decks/{slug}/mcts-game", response_model=McctsGameResponse)
def mcts_game(slug: str, req: McctsGameRequest):
    """MCTSAI で 1 試合実行し、 各 MCTS choose_action のツリーを返す (戦い方の探索)。

    実行時間: n_simulations=30 で 1 試合 ~30-60 秒 + アクション数依存。
    """
    from engine.mcts_replay import play_mcts_game

    deck_a_path = DECKS_DIR / f"{slug}.json"
    deck_b_path = DECKS_DIR / f"{req.opponent_slug}.json"
    if not deck_a_path.exists():
        raise HTTPException(404, f"deck not found: {slug}")
    if not deck_b_path.exists():
        raise HTTPException(404, f"opponent deck not found: {req.opponent_slug}")

    repo = get_repo()
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    try:
        deck_mcts = make_deck_from_dict(json.loads(deck_a_path.read_text(encoding="utf-8")), repo)
        deck_opp = make_deck_from_dict(json.loads(deck_b_path.read_text(encoding="utf-8")), repo)
    except Exception as e:
        raise HTTPException(422, f"deck load failed: {e}")

    n_sim = max(1, min(req.n_simulations, 200))
    depth = max(1, min(req.max_tree_depth, 4))

    try:
        rec = play_mcts_game(
            deck_mcts, deck_opp,
            effects_overlay=overlay,
            seed=req.seed,
            n_simulations=n_sim,
            max_tree_depth=depth,
        )
    except Exception as e:
        raise HTTPException(500, f"mcts game failed: {e}")

    return McctsGameResponse(
        deck_mcts=rec.deck_mcts,
        deck_opp=rec.deck_opp,
        seed=rec.seed,
        n_simulations=rec.n_simulations,
        winner=rec.winner,
        total_turns=rec.total_turns,
        total_actions=rec.total_actions,
        mcts_turns=[
            McctsTurnOut(
                turn=t.turn,
                player_idx=t.player_idx,
                action_index=t.action_index,
                chosen_action_label=t.chosen_action_label,
                root_tree=t.root_tree,
                greedy_action_label=t.greedy_action_label,
                agree_with_greedy=t.agree_with_greedy,
                mcts_confidence=t.mcts_confidence,
            )
            for t in rec.mcts_turns
        ],
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

    # deck.slug を req.deck_a_id / req.deck_b_id から補完
    # (= make_deck_from_dict が dict に slug が無い場合 None を返すため、
    # request の id を fallback で採用。 これがないと record_replays で
    # 試合履歴が deck slug 無しで保存され、 後で improvements 取得時に
    # 該当試合が見つからない)
    if req.deck_a_id and not getattr(deck_a, "slug", None):
        deck_a.slug = req.deck_a_id
    if req.deck_b_id and not getattr(deck_b, "slug", None):
        deck_b.slug = req.deck_b_id

    report = run_matchup(
        deck_a, deck_b,
        n_games=req.n_games,
        seed=req.seed,
        keep_logs=True,
        record_replays=True,        # 改善提案で利用するため必ず replay 保存
        record_snapshots=True,
    )

    job_id = uuid.uuid4().hex[:12]
    _MATCH_JOBS[job_id] = {
        "report": report,
        # リプレイ再実行時に同じ条件で再構築するため、deck/seed/n_games を保持
        "deck_a": deck_a_dict,
        "deck_b": deck_b_dict,
        "seed": req.seed,
        "n_games": req.n_games,
    }
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


# --------------------------------------------------------------------------- #
# エンドポイント: replay (盤面スナップショット付きで対象ゲームを再実行)
# --------------------------------------------------------------------------- #
class CharSnapshot(BaseModel):
    instance_id: int
    card_id: str
    name: str
    rested: bool
    attached_dons: int
    summoning_sickness: bool
    power: int
    base_power: int
    keywords: list[str]


class PlayerSnapshot(BaseModel):
    name: str
    leader: CharSnapshot
    characters: list[CharSnapshot]
    stages: list[CharSnapshot]
    hand: list[str]
    hand_count: int
    life_count: int
    trash: list[str]
    trash_count: int
    deck_count: int
    don_active: int
    don_rested: int
    don_total: int
    don_remaining_in_deck: int


class AttackEvent(BaseModel):
    type: str
    attacker_iid: int
    target_iid: int
    target_kind: str
    atk_power: int
    defender_power: int


class StateSnapshot(BaseModel):
    turn: int
    turn_player_idx: int
    phase: str
    log: str
    game_over: bool
    winner: Optional[int] = None
    event: Optional[AttackEvent] = None
    players: list[PlayerSnapshot]


class ReplayResponse(BaseModel):
    job_id: str
    game_index: int
    deck_a_name: str
    deck_b_name: str
    first_player: int
    winner: int
    turns: int
    snapshots: list[StateSnapshot]


# === 試合後分析 ===
class EvalPointOut(BaseModel):
    snap_idx: int
    turn: int
    phase: str
    score: float
    normalized: float
    log: str


class TurningPointOut(BaseModel):
    snap_idx: int
    turn: int
    delta: float
    side: str  # "self_gain" / "self_loss"
    log: str
    score_before: float
    score_after: float


class GameSummaryOut(BaseModel):
    avg_score: float
    max_lead: float
    max_deficit: float
    final_score: float
    comeback: bool


class GameAnalysisResponse(BaseModel):
    job_id: str
    game_index: int
    me_idx: int
    me_name: str
    opp_name: str
    winner: Optional[int]
    eval_series: list[EvalPointOut]
    turning_points: list[TurningPointOut]
    summary: Optional[GameSummaryOut]


@app.post("/api/match/{job_id}/games/{game_index}/replay", response_model=ReplayResponse)
def replay_match_game(job_id: str, game_index: int):
    """対象ゲームを同じ seed で再実行し、push_log 毎の盤面スナップショットを返す。

    元の対戦時には snapshot を取らない (メモリ節約) ので、開いた試合だけ lazy 再実行する。
    """
    job = _MATCH_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"match job not found: {job_id}")
    if game_index < 0 or game_index >= job["n_games"]:
        raise HTTPException(404, f"game index out of range: {game_index}")

    repo = get_repo()
    try:
        deck_a = make_deck_from_dict(job["deck_a"], repo)
        deck_b = make_deck_from_dict(job["deck_b"], repo)
    except (KeyError, ValueError) as e:
        raise HTTPException(500, f"deck rebuild failed: {e}")

    report = run_matchup(
        deck_a, deck_b,
        n_games=job["n_games"],
        seed=job["seed"],
        record_snapshots=True,
        only_game_index=game_index,
    )
    g = report.games[game_index]
    return ReplayResponse(
        job_id=job_id,
        game_index=game_index,
        deck_a_name=report.deck1_name,
        deck_b_name=report.deck2_name,
        first_player=g.first_player,
        winner=g.winner,
        turns=g.turns,
        snapshots=[StateSnapshot(**s) for s in g.snapshots],
    )


@app.get(
    "/api/match/{job_id}/games/{game_index}/analysis",
    response_model=GameAnalysisResponse,
)
def analyze_match_game(job_id: str, game_index: int):
    """既存 replay snapshot を再利用して試合後分析を返す。

    deck_a 視点 (= me_idx は first_player から逆引きで deck_a が居る側) で
    eval_series + turning_points + summary を計算。
    snapshot が record されていない場合は replay と同じく lazy 再実行する。
    """
    from engine.analyzer import analyze_game

    job = _MATCH_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"match job not found: {job_id}")
    if game_index < 0 or game_index >= job["n_games"]:
        raise HTTPException(404, f"game index out of range: {game_index}")

    repo = get_repo()
    try:
        deck_a = make_deck_from_dict(job["deck_a"], repo)
        deck_b = make_deck_from_dict(job["deck_b"], repo)
    except (KeyError, ValueError) as e:
        raise HTTPException(500, f"deck rebuild failed: {e}")

    report = run_matchup(
        deck_a, deck_b,
        n_games=job["n_games"],
        seed=job["seed"],
        record_snapshots=True,
        only_game_index=game_index,
    )
    g = report.games[game_index]
    snapshots = g.snapshots

    # me_idx (= deck_a 視点 = self) を first_player で決める。
    # MatchReplay の selfIdx と同じ計算: deck_a が後攻 (first_player==1) なら snap.players[1]
    me_idx = g.first_player  # 0 or 1
    me_name = report.deck1_name  # = deck_a name
    opp_name = report.deck2_name

    analysis = analyze_game(
        snapshots, me_idx=me_idx, me_name=me_name, opp_name=opp_name,
    )

    return GameAnalysisResponse(
        job_id=job_id,
        game_index=game_index,
        me_idx=analysis.me_idx,
        me_name=analysis.me_name,
        opp_name=analysis.opp_name,
        winner=analysis.winner,
        eval_series=[
            EvalPointOut(
                snap_idx=p.snap_idx, turn=p.turn, phase=p.phase,
                score=p.score, normalized=p.normalized, log=p.log,
            )
            for p in analysis.eval_series
        ],
        turning_points=[
            TurningPointOut(
                snap_idx=t.snap_idx, turn=t.turn, delta=t.delta,
                side=t.side, log=t.log,
                score_before=t.score_before, score_after=t.score_after,
            )
            for t in analysis.turning_points
        ],
        summary=(
            GameSummaryOut(
                avg_score=analysis.summary.avg_score,
                max_lead=analysis.summary.max_lead,
                max_deficit=analysis.summary.max_deficit,
                final_score=analysis.summary.final_score,
                comeback=analysis.summary.comeback,
            )
            if analysis.summary
            else None
        ),
    )


# --------------------------------------------------------------------------- #
# エンドポイント: note 記事生成 (完全ローカル)
# --------------------------------------------------------------------------- #

class ArticleResponse(BaseModel):
    article: str
    deck_name: str
    model: str


@app.post("/api/decks/{slug}/generate-article")
def generate_deck_article(slug: str):
    """デッキ分析データを元に note.com 向けデッキ概要記事をローカル生成する。
    外部 API 不要。engine/article_generator.py のテンプレートエンジンを使用。
    vs 相手 攻略記事は /api/decks/{slug}/battle-report エンドポイントを使うこと。
    """
    from engine.article_generator import generate_article

    deck_path = DECKS_DIR / f"{slug}.json"
    if not deck_path.exists():
        raise HTTPException(404, f"deck not found: {slug}")

    strategy_data: dict = {}
    cache_path = DECKS_DIR / f"{slug}.analysis.json"
    if cache_path.exists():
        try:
            strategy_data = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not strategy_data:
        try:
            from dataclasses import asdict
            from engine.deck_analyzer import analyze_deck
            repo = get_repo()
            deck = make_deck_from_dict(json.loads(deck_path.read_text(encoding="utf-8")), repo)
            overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
            analysis = analyze_deck(deck, overlay)
            d = asdict(analysis)
            d["top_features"] = [list(t) for t in d.get("top_features", [])]
            strategy_data = d
        except Exception as e:
            raise HTTPException(500, f"strategy load failed: {e}")

    deck_name = strategy_data.get("deck_name", slug)

    matchup_rows: list[dict] = []
    deck_name_map: dict[str, str] = {}
    if _MATRIX_PATH.exists():
        try:
            matrix = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))
            deck_name_map = {d["slug"]: d["name"] for d in matrix.get("decks", [])}
            for row in matrix.get("matrix", []):
                if row.get("deck_a") == slug:
                    matchup_rows = row.get("row", [])
                    break
        except Exception:
            pass

    article = generate_article(strategy_data, matchup_rows, deck_name_map)
    return ArticleResponse(article=article, deck_name=deck_name, model="local")


class BattleReportResponse(BaseModel):
    article: str
    deck_name: str
    opponent_name: str
    n_games: int
    n_wins: int
    n_losses: int


@app.post("/api/decks/{slug}/battle-report", response_model=BattleReportResponse)
def generate_battle_report(
    slug: str,
    opponent_slug: str = Query(..., description="対戦相手デッキの slug"),
    n_games: int = Query(10, ge=3, le=20, description="試合数 (3〜20)"),
    seed: int = Query(42),
):
    """対戦ログを解析して勝ち/負け別の実戦レポートを生成する。"""
    from engine.log_analyzer import parse_game_log, generate_battle_report as _gen_report
    from engine.analyzer import analyze_game

    repo = get_repo()

    deck_path = DECKS_DIR / f"{slug}.json"
    opp_path = DECKS_DIR / f"{opponent_slug}.json"
    if not deck_path.exists():
        raise HTTPException(404, f"deck not found: {slug}")
    if not opp_path.exists():
        raise HTTPException(404, f"opponent deck not found: {opponent_slug}")

    try:
        deck_a = make_deck_from_dict(json.loads(deck_path.read_text(encoding="utf-8")), repo)
        deck_b = make_deck_from_dict(json.loads(opp_path.read_text(encoding="utf-8")), repo)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"deck build failed: {e}")

    report = run_matchup(
        deck_a, deck_b, n_games=n_games, seed=seed, keep_logs=True, record_snapshots=True,
    )

    all_stats = [
        parse_game_log(g.log, g.winner, g.turns, our_idx=0)
        for g in report.games
    ]

    board_analyses = [
        analyze_game(g.snapshots, me_idx=0, me_name=deck_a.name, opp_name=deck_b.name)
        for g in report.games
    ]

    n_wins = sum(1 for s in all_stats if s.won)
    article = _gen_report(all_stats, deck_a.name, deck_b.name, board_analyses=board_analyses)

    return BattleReportResponse(
        article=article,
        deck_name=deck_a.name,
        opponent_name=deck_b.name,
        n_games=n_games,
        n_wins=n_wins,
        n_losses=n_games - n_wins,
    )
