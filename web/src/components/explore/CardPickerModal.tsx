"use client";

import { useEffect, useState } from "react";
import { fetchCards } from "@/lib/api";
import type { Card, CardCategory } from "@/lib/types";
import { CardImage } from "@/components/CardImage";

export function CardPickerModal({
  title,
  category,
  selected,
  onAdd,
  onRemove,
  onClose,
}: {
  title: string;
  category?: CardCategory; // 指定すれば LEADER などにフィルタ
  selected: Card[];
  onAdd: (card: Card) => void;
  onRemove: (cardId: string) => void;
  onClose: () => void;
}) {
  const [cards, setCards] = useState<Card[]>([]);
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const list = await fetchCards({
          category,
          name_contains: name || undefined,
          color: color || undefined,
          limit: 200,
        });
        if (!cancelled) setCards(list);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [category, name, color]);

  const selectedIds = new Set(selected.map((c) => c.card_id));

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-label={title}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg bg-white shadow-xl dark:bg-zinc-900">
        <div className="flex items-center justify-between border-b border-zinc-200 p-4 dark:border-zinc-800">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-3 py-1 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            閉じる
          </button>
        </div>

        <div className="flex flex-wrap gap-2 border-b border-zinc-200 p-4 dark:border-zinc-800">
          <input
            type="text"
            placeholder="名前で検索"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="flex-1 min-w-[180px] rounded border border-zinc-300 px-3 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-800"
          />
          <select
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="rounded border border-zinc-300 px-3 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-800"
          >
            <option value="">全色</option>
            <option value="赤">赤</option>
            <option value="青">青</option>
            <option value="黄">黄</option>
            <option value="緑">緑</option>
            <option value="紫">紫</option>
            <option value="黒">黒</option>
          </select>
        </div>

        {selected.length > 0 && (
          <div className="border-b border-zinc-200 p-3 dark:border-zinc-800">
            <div className="mb-2 text-xs font-medium text-zinc-500">
              選択中 ({selected.length} 件)
            </div>
            <div className="flex flex-wrap gap-2">
              {selected.map((c) => (
                <button
                  key={c.card_id}
                  type="button"
                  onClick={() => onRemove(c.card_id)}
                  className="flex items-center gap-2 rounded bg-blue-100 px-2 py-1 text-xs hover:bg-blue-200 dark:bg-blue-900 dark:hover:bg-blue-800"
                  title="クリックで削除"
                >
                  <span>{c.name}</span>
                  <span className="text-zinc-500">×</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4">
          {loading ? (
            <div className="text-sm text-zinc-500">読み込み中…</div>
          ) : cards.length === 0 ? (
            <div className="text-sm text-zinc-500">該当カードなし</div>
          ) : (
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 md:grid-cols-7 lg:grid-cols-8">
              {cards.map((card) => {
                const isSelected = selectedIds.has(card.card_id);
                return (
                  <button
                    key={card.card_id}
                    type="button"
                    onClick={() => {
                      if (isSelected) onRemove(card.card_id);
                      else onAdd(card);
                    }}
                    className={`relative overflow-hidden rounded border-2 transition ${
                      isSelected
                        ? "border-blue-500 ring-2 ring-blue-300"
                        : "border-transparent hover:border-zinc-400"
                    }`}
                    title={`${card.name} (${card.card_id})`}
                  >
                    <div className="aspect-[5/7] bg-zinc-100 dark:bg-zinc-800">
                      <CardImage
                        cardId={card.card_id}
                        alt={card.name}
                        className="h-full w-full object-cover"
                      />
                    </div>
                    {isSelected && (
                      <div className="absolute right-1 top-1 rounded-full bg-blue-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                        ✓
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
