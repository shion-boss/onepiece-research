/**
 * card_roles.json (= primary_role only) のクライアント側キャッシュ。
 *
 * /api/cards/roles から { card_id: primary_role } の compact map を 1 回 fetch、
 * module-level Map にキャッシュ。 boardEval の chara_quality / hand_quality
 * 計算で参照する (= engine/eval.py と同じ role 価値テーブルで重み付け)。
 *
 * 使い方:
 *   const db = useCardRoleDb();          // React hook で fetch 状態管理
 *   const role = getCardRoleSync(cid);   // 既にキャッシュ済の同期 lookup
 */

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

let cache: Map<string, string> | null = null;
let fetchPromise: Promise<Map<string, string>> | null = null;

export async function loadCardRoleDb(): Promise<Map<string, string>> {
  if (cache) return cache;
  if (fetchPromise) return fetchPromise;
  fetchPromise = (async () => {
    const res = await fetch(`${API}/api/cards/roles`);
    if (!res.ok) throw new Error(`role db fetch failed: ${res.status}`);
    const data: Record<string, string> = await res.json();
    cache = new Map(Object.entries(data));
    return cache;
  })();
  return fetchPromise;
}

export function getCardRoleSync(cardId: string): string {
  return cache?.get(cardId) ?? "";
}

/**
 * React hook: role db をロードして Map を返す。
 * 初回 mount で fetch、 完了後 setState で再 render。 未完了は null。
 */
export function useCardRoleDb(): Map<string, string> | null {
  const [db, setDb] = useState<Map<string, string> | null>(cache);
  useEffect(() => {
    if (db) return;
    let cancelled = false;
    loadCardRoleDb()
      .then((m) => {
        if (!cancelled) setDb(m);
      })
      .catch(() => {
        // silent: chara/hand_quality は 0 で graceful degradation
      });
    return () => {
      cancelled = true;
    };
  }, [db]);
  return db;
}
