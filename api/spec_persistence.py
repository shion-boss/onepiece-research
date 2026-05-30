# -*- coding: utf-8 -*-
"""spec / deck recipe の 永続 化 layer (= Vercel Blob ↔ local file 透過 wrapper)。

Vercel function は 静的 bundle (= decks/*.target_v1.json) を read-only で 持 つ が、
runtime で の 更新 (= deck 追加、 entries 増加、 bonus 学習) は 永続 化 出来 ない。
Blob にも 同じ JSON を 持 ち、 ensure_spec_loaded で Blob ↔ /tmp/specs に sync。

# データ flow

```
write (= POST /api/decks や bonus 学習 結果):
  save_spec(slug, spec) → Blob put + /tmp/specs write
  save_deck_recipe(slug, recipe) → Blob put

read (= GoalDirectedAI が load_target_spec 経由 で 読 む):
  ensure_spec_loaded(slug) → Blob 取得 → /tmp/specs/<slug>.target_v1.json
  engine が ONEPIECE_SPEC_DIR (= /tmp/specs) を 経由 で 読 む
  cache miss なら bundle fallback
```

# Local dev

BLOB_READ_WRITE_TOKEN env 未設定 = bundle 直接 (= decks/) で 動作。 既 fallback pattern。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


# bundle path (= git で 出 荷)
_BUNDLE_DIR = Path(__file__).resolve().parent.parent / "decks"
# runtime writable path (= Vercel function /tmp は writable)
_RUNTIME_DIR = Path(os.environ.get("ONEPIECE_SPEC_RUNTIME_DIR", "/tmp/specs"))


def get_runtime_dir() -> Path:
    """runtime で spec を 一 時 保 存 する dir (= /tmp/specs 既 定)。"""
    return _RUNTIME_DIR


def get_bundle_dir() -> Path:
    """bundle (= git 出 荷 時 の decks/) dir。"""
    return _BUNDLE_DIR


def _is_blob_configured() -> bool:
    """BLOB_READ_WRITE_TOKEN env が あ れ ば True。"""
    return bool(os.environ.get("BLOB_READ_WRITE_TOKEN"))


def ensure_spec_loaded(deck_slug: str, version: str = "v1") -> Optional[Path]:
    """spec を Blob か bundle か ら 取 得 し て runtime path に sync。

    Returns: spec ファイル path (= engine が 読 む)、 not found なら None。

    優 先 順:
      1. runtime/<slug>.target_v<version>.json 既 存 (= 同 session で 既 読 込)
      2. Blob specs/<slug>.target_v<version>.json (= Vercel persistence)
      3. bundle decks/<slug>.target_v<version>.json (= 静 的 出 荷 時)
    """
    runtime_path = get_runtime_dir() / f"{deck_slug}.target_{version}.json"
    if runtime_path.exists() and runtime_path.stat().st_size > 0:
        return runtime_path

    # Blob 試行
    if _is_blob_configured():
        try:
            from api.blob_storage import list_jsons, get_json

            prefix = f"specs/{deck_slug}.target_{version}"
            blobs = list_jsons(prefix=prefix)
            # add_random_suffix=False で put したら 単 一 file、 直接 マッチ
            for blob in blobs:
                if blob.get("pathname", "").startswith(prefix):
                    data = get_json(blob["url"])
                    runtime_path.parent.mkdir(parents=True, exist_ok=True)
                    runtime_path.write_text(
                        json.dumps(data, ensure_ascii=False), encoding="utf-8"
                    )
                    return runtime_path
        except Exception:
            pass

    # bundle fallback
    bundle_path = get_bundle_dir() / f"{deck_slug}.target_{version}.json"
    if bundle_path.exists():
        return bundle_path

    return None


def save_spec(deck_slug: str, spec: dict, version: str = "v1") -> str:
    """spec を 永続 化。 Blob あり = upload、 なし = bundle に 直接 write。

    Returns: 保 存 先 URL or local path。
    """
    if _is_blob_configured():
        from api.blob_storage import put_json

        pathname = f"specs/{deck_slug}.target_{version}.json"
        url = put_json(pathname, spec, add_random_suffix=False)
        # runtime cache に も 同 期 (= 次 ensure_spec_loaded で 再 fetch 省 略)
        runtime_path = get_runtime_dir() / f"{deck_slug}.target_{version}.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(
            json.dumps(spec, ensure_ascii=False), encoding="utf-8"
        )
        return url

    # local dev = bundle に 直接
    bundle_path = get_bundle_dir() / f"{deck_slug}.target_{version}.json"
    bundle_path.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(bundle_path)


def ensure_deck_recipe_loaded(deck_slug: str) -> Optional[Path]:
    """deck recipe (= decks/<slug>.json) を Blob か bundle か ら 取 得。

    Returns: recipe ファイル path、 not found なら None。
    """
    runtime_path = get_runtime_dir() / f"{deck_slug}.json"
    if runtime_path.exists() and runtime_path.stat().st_size > 0:
        return runtime_path

    if _is_blob_configured():
        try:
            from api.blob_storage import list_jsons, get_json

            prefix = f"deck_recipes/{deck_slug}"
            blobs = list_jsons(prefix=prefix)
            for blob in blobs:
                if blob.get("pathname", "").startswith(prefix):
                    data = get_json(blob["url"])
                    runtime_path.parent.mkdir(parents=True, exist_ok=True)
                    runtime_path.write_text(
                        json.dumps(data, ensure_ascii=False), encoding="utf-8"
                    )
                    return runtime_path
        except Exception:
            pass

    bundle_path = get_bundle_dir() / f"{deck_slug}.json"
    if bundle_path.exists():
        return bundle_path
    return None


def save_deck_recipe(deck_slug: str, recipe: dict) -> str:
    """deck recipe を 永続 化。 Blob あり = upload、 なし = bundle に write。"""
    if _is_blob_configured():
        from api.blob_storage import put_json

        pathname = f"deck_recipes/{deck_slug}.json"
        url = put_json(pathname, recipe, add_random_suffix=False)
        runtime_path = get_runtime_dir() / f"{deck_slug}.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(
            json.dumps(recipe, ensure_ascii=False), encoding="utf-8"
        )
        return url

    bundle_path = get_bundle_dir() / f"{deck_slug}.json"
    bundle_path.write_text(
        json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(bundle_path)


def list_all_deck_slugs() -> list[str]:
    """利 用 可 能 な deck slug 全 列 挙。 Blob + bundle を union。"""
    slugs: set[str] = set()
    bundle = get_bundle_dir()
    if bundle.exists():
        for p in bundle.glob("*.json"):
            name = p.stem
            # _archive や analysis を 除 外
            if name.startswith("_") or ".analysis" in name or ".target_" in name:
                continue
            slugs.add(name)
    if _is_blob_configured():
        try:
            from api.blob_storage import list_jsons

            for blob in list_jsons(prefix="deck_recipes/"):
                pathname = blob.get("pathname", "")
                if pathname.startswith("deck_recipes/") and pathname.endswith(".json"):
                    slug = pathname[len("deck_recipes/"):-len(".json")]
                    if slug and not slug.startswith("_"):
                        slugs.add(slug)
        except Exception:
            pass
    return sorted(slugs)


def get_combined_decks_dir_for_engine() -> Path:
    """engine に 渡 す decks/ dir。 runtime に sync 済 spec が あ れ ば runtime、 な ければ bundle。

    engine の load_target_spec(base_dir=...) で 使う 想 定。 runtime に file が あ れ ば
    そ ち ら 優 先、 な け れ ば bundle path を 返 す。
    """
    runtime = get_runtime_dir()
    if runtime.exists() and any(runtime.iterdir()):
        return runtime
    return get_bundle_dir()
