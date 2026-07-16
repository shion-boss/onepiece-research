"use client";

import { useEffect, useState } from "react";
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
  // savedFilters は localStorage 永続 = hydration まで空。 絞り込み URL を直接開いた時に
  // 未 hydration で「未保存」と誤判定して余分な基底タブを作らないよう、 hydration を待つ。
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setHydrated(useSavedFilters.persist.hasHydrated());
    return useSavedFilters.persist.onFinishHydration(() => setHydrated(true));
  }, []);

  const filterQuery =
    path === "/cards" ? normalizeFilterQuery(new URLSearchParams(search.toString())) : "";
  // 保存済みの絞り込みだけ専用タブにする。 未保存 (アドホック) の絞り込みは基底 /cards
  // タブのまま (= 絞り込むたびに新規タブが増えないように)。
  const savedFilter = filterQuery
    ? savedFilters.find((f) => f.query === filterQuery)
    : undefined;
  const tabId = savedFilter ? `/cards?${filterQuery}` : path;
  // 絞り込みタブは「カード[絞り込み名]」で表記 (= カードタブの派生と分かる)。
  const filterName = savedFilter?.name ?? null;
  // ページが登録したタブ名 (= デッキ詳細のデッキ名等) があればそれを優先。
  const override = useWorkspace((s) => s.tabTitleOverrides[tabId]);
  const title = override ?? (filterName ? `カード[${filterName}]` : tabTitleFor(tabId));

  useEffect(() => {
    setActiveTabId(tabId);
    // ルート "/" は「タブ無し = ようこそ/空状態」なのでタブ化しない。
    if (path === "/") return;
    // 絞り込み URL は hydration 前だと保存済みか判定できない → タブ確定を待つ
    // (= 直接開いた保存絞り込みで基底タブと保存タブが二重に出るのを防ぐ)。
    if (path === "/cards" && filterQuery && !hydrated) return;
    // effect 実行時点の最新 override を読む (= ページの SetTabTitle が先に set 済みなら
    // その名前でタブを開く = slug で開いてしまう race を防ぐ)。
    const latest = useWorkspace.getState().tabTitleOverrides[tabId];
    openTab({ id: tabId, title: latest ?? title });
  }, [tabId, title, path, filterQuery, hydrated, openTab, setActiveTabId]);

  return null;
}
