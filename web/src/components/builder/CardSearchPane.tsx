"use client";

import { useEffect, useState } from "react";
import type { Card, CardCategory } from "@/lib/types";
import { fetchCards } from "@/lib/api";
import { CardImage } from "@/components/CardImage";

const CATEGORIES: CardCategory[] = ["CHARACTER", "EVENT", "STAGE"];

export function CardSearchPane({
  leaderColors,
  onAdd,
  countOf,
}: {
  leaderColors: string[];
  onAdd: (card: Card) => void;
  countOf: (cardId: string) => number;
}) {
  const [cards, setCards] = useState<Card[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterColor, setFilterColor] = useState<string>("");
  const [category, setCategory] = useState<CardCategory | "">("");
  const [costGe, setCostGe] = useState("");
  const [costLe, setCostLe] = useState("");
  const [name, setName] = useState("");

  useEffect(() => {
    if (leaderColors.length === 0) {
      setCards([]);
      return;
    }
    setLoading(true);
    setError(null);
    const color = filterColor || leaderColors[0];
    fetchCards({
      color,
      category: category || undefined,
      cost_ge: costGe ? Number(costGe) : undefined,
      cost_le: costLe ? Number(costLe) : undefined,
      name_contains: name || undefined,
      limit: 200,
    })
      .then((all) => {
        // リーダー色のいずれかに合うものだけ表示。LEADER は除外。
        const colorSet = new Set(leaderColors);
        const filtered = all.filter(
          (c) =>
            c.category !== "LEADER" &&
            c.color.some((cc) => colorSet.has(cc)),
        );
        setCards(filtered);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [leaderColors, filterColor, category, costGe, costLe, name]);

  if (leaderColors.length === 0) {
    return (
      <div className="rounded border border-zinc-200 p-6 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        リーダーを選ぶとカードが表示されます
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {leaderColors.length > 1 ? (
            <>
              <button
                type="button"
                onClick={() => setFilterColor("")}
                aria-pressed={!filterColor}
                className={`rounded px-2 py-1 text-xs ${
                  !filterColor
                    ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                    : "bg-zinc-100 dark:bg-zinc-800"
                }`}
              >
                {leaderColors.join("/")}
              </button>
              {leaderColors.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setFilterColor(c)}
                  aria-pressed={filterColor === c}
                  className={`rounded px-2 py-1 text-xs ${
                    filterColor === c
                      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                      : "bg-zinc-100 dark:bg-zinc-800"
                  }`}
                >
                  {c}
                </button>
              ))}
            </>
          ) : (
            <span className="rounded bg-zinc-100 px-2 py-1 text-xs dark:bg-zinc-800">
              {leaderColors[0]}
            </span>
          )}
        </div>

        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as CardCategory | "")}
          className="rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
        >
          <option value="">all categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-1 text-xs text-zinc-600 dark:text-zinc-400">
          cost
          <input
            type="number"
            value={costGe}
            onChange={(e) => setCostGe(e.target.value)}
            placeholder="ge"
            className="w-12 rounded border border-zinc-300 bg-transparent px-1 py-0.5 dark:border-zinc-700"
          />
          〜
          <input
            type="number"
            value={costLe}
            onChange={(e) => setCostLe(e.target.value)}
            placeholder="le"
            className="w-12 rounded border border-zinc-300 bg-transparent px-1 py-0.5 dark:border-zinc-700"
          />
        </label>

        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="カード名"
          className="rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
        />

        <span className="text-xs text-zinc-500 dark:text-zinc-400">
          {loading ? "読み込み中…" : `${cards.length} 件`}
        </span>
      </div>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          {error}
        </div>
      )}

      <div className="grid max-h-[60vh] grid-cols-3 gap-2 overflow-auto sm:grid-cols-4 md:grid-cols-5">
        {cards.map((c) => {
          const used = countOf(c.card_id);
          const disabled = used >= 4;
          return (
            <button
              key={c.card_id}
              type="button"
              onClick={() => onAdd(c)}
              disabled={disabled}
              title={c.text || c.name}
              className="group relative flex flex-col gap-1 rounded border border-zinc-200 p-1 text-left transition hover:border-zinc-400 disabled:opacity-40 dark:border-zinc-800 dark:hover:border-zinc-500"
            >
              <CardImage
                cardId={c.card_id}
                alt={c.name}
                className="aspect-[5/7] w-full rounded object-cover"
              />
              <div className="flex items-center justify-between text-xs">
                <span className="truncate">{c.name}</span>
                <span className="shrink-0 text-zinc-500">{c.cost}</span>
              </div>
              {used > 0 && (
                <span className="absolute right-1 top-1 rounded bg-zinc-900/80 px-1 text-xs font-mono text-white">
                  ×{used}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
