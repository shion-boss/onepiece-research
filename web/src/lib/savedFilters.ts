// ユーザーが名前を付けて保存するカード絞り込み条件 (localStorage 永続)。
// 条件は /cards の URL クエリ文字列 (color/category/cost/name/feature/set/regulation) で表す。
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type SavedFilter = { id: string; name: string; query: string };

// 保存対象の URL クエリキー (= CardFilterBar が操作するもの)。
export const SAVED_FILTER_KEYS = [
  "color",
  "category",
  "cost_le",
  "cost_ge",
  "name_contains",
  "feature",
  "set",
  "regulation",
] as const;

// searchParams から保存対象キーのみを抜き、 正規化した (キー昇順の) クエリ文字列にする。
export function normalizeFilterQuery(params: URLSearchParams): string {
  const out = new URLSearchParams();
  for (const k of [...SAVED_FILTER_KEYS].sort()) {
    const v = params.get(k);
    if (v) out.set(k, v);
  }
  return out.toString();
}

interface SavedFilterState {
  filters: SavedFilter[];
  add: (name: string, query: string) => void;
  remove: (id: string) => void;
  rename: (id: string, name: string) => void;
}

export const useSavedFilters = create<SavedFilterState>()(
  persist(
    (set) => ({
      filters: [],
      add: (name, query) =>
        set((s) => ({
          filters: [
            ...s.filters,
            { id: crypto.randomUUID(), name: name.trim(), query },
          ],
        })),
      remove: (id) => set((s) => ({ filters: s.filters.filter((f) => f.id !== id) })),
      rename: (id, name) =>
        set((s) => ({
          filters: s.filters.map((f) => (f.id === id ? { ...f, name: name.trim() } : f)),
        })),
    }),
    { name: "optcg-saved-card-filters" },
  ),
);
