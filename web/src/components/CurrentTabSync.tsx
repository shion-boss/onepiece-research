"use client";

import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useWorkspace, tabTitleFor } from "@/lib/workspace";
import { useSavedFilters, normalizeFilterQuery } from "@/lib/savedFilters";

// 現在の URL を workspace のタブに同期する (= useSearchParams を隔離するための小コンポーネント。
// Suspense 境界に包んで使う → ページ本体の SSR を保ちつつ CSR bailout をここに閉じ込める)。
// /cards は絞り込みクエリ込みで別タブにする (= 保存した絞り込みを独立タブで開く)。
export function CurrentTabSync() {
  const path = usePathname() || "/";
  const search = useSearchParams();
  const savedFilters = useSavedFilters((s) => s.filters);
  const openTab = useWorkspace((s) => s.openTab);
  const setActiveTabId = useWorkspace((s) => s.setActiveTabId);

  const filterQuery =
    path === "/cards" ? normalizeFilterQuery(new URLSearchParams(search.toString())) : "";
  const tabId = filterQuery ? `/cards?${filterQuery}` : path;
  // 絞り込みタブは「カード[絞り込み名]」で表記 (= カードタブの派生と分かる)。
  const filterName = tabId.startsWith("/cards?")
    ? savedFilters.find((f) => f.query === tabId.slice("/cards?".length))?.name ?? "絞り込み"
    : null;
  const title = filterName ? `カード[${filterName}]` : tabTitleFor(tabId);

  useEffect(() => {
    setActiveTabId(tabId);
    // ルート "/" は「タブ無し = ようこそ/空状態」なのでタブ化しない。
    if (path === "/") return;
    openTab({ id: tabId, title });
  }, [tabId, title, path, openTab, setActiveTabId]);

  return null;
}
