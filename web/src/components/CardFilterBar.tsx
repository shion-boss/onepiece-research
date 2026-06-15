"use client";

import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useCallback, useTransition } from "react";
import type { CardCategory } from "@/lib/types";

const COLORS = ["赤", "青", "緑", "紫", "黒", "黄"] as const;
const CATEGORIES: CardCategory[] = ["LEADER", "CHARACTER", "EVENT", "STAGE"];

export function CardFilterBar() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [isPending, startTransition] = useTransition();

  const update = useCallback(
    (mutate: (p: URLSearchParams) => void) => {
      const next = new URLSearchParams(params.toString());
      mutate(next);
      const qs = next.toString();
      startTransition(() => {
        router.replace(qs ? `${pathname}?${qs}` : pathname);
      });
    },
    [params, pathname, router],
  );

  const color = params.get("color") ?? "";
  const category = params.get("category") ?? "";
  const cost_le = params.get("cost_le") ?? "";
  const cost_ge = params.get("cost_ge") ?? "";
  const name_contains = params.get("name_contains") ?? "";
  const feature = params.get("feature") ?? "";
  const regulation = params.get("regulation") ?? "";

  const setParam = (k: string, v: string) =>
    update((p) => {
      if (v) p.set(k, v);
      else p.delete(k);
    });

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex gap-1" role="group" aria-label="色フィルタ">
        {COLORS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setParam("color", color === c ? "" : c)}
            aria-pressed={color === c}
            className={`rounded px-2 py-1 text-xs ${
              color === c
                ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-100"
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      <select
        value={category}
        onChange={(e) => setParam("category", e.target.value)}
        className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        aria-label="カテゴリ"
      >
        <option value="">全カテゴリ</option>
        {CATEGORIES.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>

      <label className="flex items-center gap-1 text-xs text-zinc-600 dark:text-zinc-400">
        コスト
        <input
          type="number"
          min={0}
          max={10}
          value={cost_ge}
          onChange={(e) => setParam("cost_ge", e.target.value)}
          placeholder="最小"
          className="w-16 rounded border border-zinc-300 bg-white px-2 py-1 text-zinc-900 placeholder:text-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
        〜
        <input
          type="number"
          min={0}
          max={10}
          value={cost_le}
          onChange={(e) => setParam("cost_le", e.target.value)}
          placeholder="最大"
          className="w-16 rounded border border-zinc-300 bg-white px-2 py-1 text-zinc-900 placeholder:text-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
      </label>

      <input
        type="text"
        value={name_contains}
        onChange={(e) => setParam("name_contains", e.target.value)}
        placeholder="カード名"
        className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm text-zinc-900 placeholder:text-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        aria-label="カード名"
      />

      <input
        type="text"
        value={feature}
        onChange={(e) => setParam("feature", e.target.value)}
        placeholder="特徴 (例: 麦わらの一味)"
        className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm text-zinc-900 placeholder:text-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        aria-label="特徴"
      />

      <div className="flex rounded border border-zinc-300 text-xs dark:border-zinc-700 overflow-hidden" role="group" aria-label="レギュレーション">
        <button
          type="button"
          onClick={() => setParam("regulation", "")}
          aria-pressed={regulation === ""}
          className={`px-2 py-1 font-medium transition ${
            regulation === ""
              ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
              : "bg-transparent text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          }`}
        >
          全件
        </button>
        <button
          type="button"
          onClick={() => setParam("regulation", regulation === "standard" ? "" : "standard")}
          aria-pressed={regulation === "standard"}
          className={`px-2 py-1 font-medium transition ${
            regulation === "standard"
              ? "bg-blue-600 text-white"
              : "bg-transparent text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          }`}
        >
          STD
        </button>
      </div>

      {(color || category || cost_le || cost_ge || name_contains || feature || regulation) && (
        <button
          type="button"
          onClick={() => update((p) => {
            for (const k of ["color", "category", "cost_le", "cost_ge", "name_contains", "feature", "regulation"]) {
              p.delete(k);
            }
          })}
          className="rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
        >
          クリア
        </button>
      )}

      {isPending && (
        <span className="text-xs text-zinc-500 dark:text-zinc-400">更新中…</span>
      )}
    </div>
  );
}
