"use client";

import { useEffect, useState } from "react";
import type { Card, CardCategory } from "@/lib/types";
import { fetchCards } from "@/lib/api";
import { CardImage } from "@/components/CardImage";
import { useDeckBuilderStore } from "@/stores/deckBuilder";

const CATEGORIES: CardCategory[] = ["CHARACTER", "EVENT", "STAGE"];

// パックの新しさ order を card_id から導出 (= series_id の並び ST<OP<EB<PRB と同じ)。
// series_id は Card に無いので prefix + 弾番号で近似。 大きいほど新しい弾。
const _PACK_RANK: Record<string, number> = { ST: 0, P: 500, OP: 1000, EB: 2000, PRB: 3000 };
function packSortKey(cardId: string): number {
  const m = /^([A-Za-z]+)(\d+)?-/.exec(cardId);
  const prefix = (m?.[1] ?? "").toUpperCase();
  const packNum = m?.[2] ? parseInt(m[2], 10) : 0;
  return (_PACK_RANK[prefix] ?? 0) + packNum;
}

type SortKey = "pack_new" | "pack_old" | "cost_asc" | "cost_desc" | "power_desc";
const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "pack_new", label: "パック新しい順" },
  { key: "pack_old", label: "パック古い順" },
  { key: "cost_asc", label: "コスト昇順" },
  { key: "cost_desc", label: "コスト降順" },
  { key: "power_desc", label: "パワー高い順" },
];
function sortCards(cards: Card[], by: SortKey): Card[] {
  const arr = [...cards];
  const byCardId = (a: Card, b: Card) => a.card_id.localeCompare(b.card_id);
  switch (by) {
    case "pack_new":
      return arr.sort((a, b) => packSortKey(b.card_id) - packSortKey(a.card_id) || byCardId(a, b));
    case "pack_old":
      return arr.sort((a, b) => packSortKey(a.card_id) - packSortKey(b.card_id) || byCardId(a, b));
    case "cost_asc":
      return arr.sort((a, b) => a.cost - b.cost || byCardId(a, b));
    case "cost_desc":
      return arr.sort((a, b) => b.cost - a.cost || byCardId(a, b));
    case "power_desc":
      return arr.sort((a, b) => (b.power || 0) - (a.power || 0) || byCardId(a, b));
    default:
      return arr;
  }
}

type ContextMenuState = { card: Card; x: number; y: number };

export function CardSearchPane({
  leaderColors,
  onAdd,
  countOf,
  onMarkCore,
  coreCardIds,
  fillHeight = false,
  onHover,
}: {
  leaderColors: string[];
  onAdd: (card: Card) => void;
  countOf: (cardId: string) => number;
  onMarkCore?: (card: Card) => void;
  coreCardIds?: Set<string>;
  // true = 親の高さいっぱいに広がり、 カードグリッドが内部スクロール (= /decks/new の
  // 分割パネル用)。 false (既定) = グリッドを max-h-[60vh] で内部スクロール (= 従来)。
  fillHeight?: boolean;
  // カードをホバー/フォーカスした時に呼ぶ (= 右の拡大プレビュー用)。 グリッドを離れると null。
  onHover?: (card: Card | null) => void;
}) {
  const regulation = useDeckBuilderStore((s) => s.regulation);
  const [cards, setCards] = useState<Card[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterColor, setFilterColor] = useState<string>("");
  const [category, setCategory] = useState<CardCategory | "">("");
  const [costGe, setCostGe] = useState("");
  const [costLe, setCostLe] = useState("");
  const [name, setName] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("pack_new");  // 既定 = パック新しい順
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    const escClose = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("click", close);
    window.addEventListener("keydown", escClose);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("keydown", escClose);
    };
  }, [contextMenu]);

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
      block_icon_ge: regulation === "standard" ? 2 : undefined,
      // 1 色 最大 ~813 枚。 「パック新しい順」 が truncate で新弾を落とさないよう全件取得
      // (= CardImage は lazy 読込なのでタイル数が多くても軽い)。
      limit: 1000,
    })
      .then((all) => {
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
  }, [leaderColors, filterColor, category, costGe, costLe, name, regulation]);

  if (leaderColors.length === 0) {
    return (
      <div className="rounded-[var(--radius)] border border-[color:var(--border-1)] p-6 text-sm text-[color:var(--text-muted)]">
        リーダーを選ぶとカードが表示されます
      </div>
    );
  }

  return (
    <div className={fillHeight ? "flex min-h-0 flex-1 flex-col gap-3" : "space-y-3"}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {leaderColors.length > 1 ? (
            <>
              <button
                type="button"
                onClick={() => setFilterColor("")}
                aria-pressed={!filterColor}
                className={`rounded-[var(--radius-sm)] px-2 py-1 text-xs ${
                  !filterColor
                    ? "bg-[color:var(--brand)] text-white"
                    : "bg-[color:var(--surface-2)] text-[color:var(--text-default)] hover:bg-[var(--list-hover)]"
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
                  className={`rounded-[var(--radius-sm)] px-2 py-1 text-xs ${
                    filterColor === c
                      ? "bg-[color:var(--brand)] text-white"
                      : "bg-[color:var(--surface-2)] text-[color:var(--text-default)] hover:bg-[var(--list-hover)]"
                  }`}
                >
                  {c}
                </button>
              ))}
            </>
          ) : (
            <span className="rounded-[var(--radius-sm)] bg-[color:var(--surface-2)] px-2 py-1 text-xs text-[color:var(--text-default)]">
              {leaderColors[0]}
            </span>
          )}
        </div>

        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as CardCategory | "")}
          className="rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1 text-sm text-[color:var(--text-default)] outline-none focus:border-[color:var(--brand)]"
        >
          <option value="">all categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>

        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortKey)}
          aria-label="並び替え"
          title="並び替え"
          className="rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1 text-sm text-[color:var(--text-default)] outline-none focus:border-[color:var(--brand)]"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-1 text-xs text-[color:var(--text-muted)]">
          cost
          <input
            type="number"
            value={costGe}
            onChange={(e) => setCostGe(e.target.value)}
            placeholder="ge"
            className="w-12 rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-1 py-0.5 text-[color:var(--text-default)] outline-none placeholder:text-[color:var(--text-muted)] focus:border-[color:var(--brand)]"
          />
          〜
          <input
            type="number"
            value={costLe}
            onChange={(e) => setCostLe(e.target.value)}
            placeholder="le"
            className="w-12 rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-1 py-0.5 text-[color:var(--text-default)] outline-none placeholder:text-[color:var(--text-muted)] focus:border-[color:var(--brand)]"
          />
        </label>

        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="カード名"
          className="rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1 text-sm text-[color:var(--text-default)] outline-none placeholder:text-[color:var(--text-muted)] focus:border-[color:var(--brand)]"
        />

        <span className="text-xs text-[color:var(--text-muted)]">
          {loading ? "読み込み中…" : `${cards.length} 件`}
        </span>
        <span
          className="rounded-[var(--radius-sm)] px-1.5 py-0.5 text-xs font-bold"
          style={
            regulation === "standard"
              ? { background: "var(--brand-soft)", color: "var(--brand-strong)" }
              : { background: "var(--surface-3)", color: "var(--text-default)" }
          }
        >
          {regulation === "standard" ? "STD" : "EX"}
        </span>
      </div>

      {error && (
        <div className="rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-2 text-xs text-[color:var(--danger)]">
          {error}
        </div>
      )}

      {onMarkCore && (
        <p className="text-xs text-[color:var(--text-muted)]">
          右クリック or Ctrl+クリックでコアカードに指定 / 解除
        </p>
      )}

      <div
        onMouseLeave={() => onHover?.(null)}
        className={`grid grid-cols-3 gap-2 overflow-auto log-scroll sm:grid-cols-4 md:grid-cols-5 ${
          fillHeight ? "min-h-0 flex-1" : "max-h-[60vh]"
        }`}
      >
        {sortCards(cards, sortBy).map((c) => {
          const used = countOf(c.card_id);
          const disabled = used >= 4;
          const isCore = coreCardIds?.has(c.card_id) ?? false;
          return (
            <button
              key={c.card_id}
              type="button"
              onMouseEnter={() => onHover?.(c)}
              onFocus={() => onHover?.(c)}
              onClick={(e) => {
                if ((e.ctrlKey || e.metaKey) && onMarkCore) {
                  e.preventDefault();
                  onMarkCore(c);
                  return;
                }
                onAdd(c);
              }}
              onContextMenu={(e) => {
                e.preventDefault();
                setContextMenu({ card: c, x: e.clientX, y: e.clientY });
              }}
              disabled={disabled && !onMarkCore}
              title={c.text || c.name}
              className={`group relative flex flex-col gap-1 rounded-[var(--radius-sm)] border p-1 text-left transition ${
                isCore
                  ? "border-[color:var(--warning)]"
                  : "border-[color:var(--border-1)] hover:border-[color:var(--brand)] disabled:opacity-40"
              } ${disabled && !isCore ? "opacity-40" : ""}`}
            >
              <CardImage
                cardId={c.card_id}
                alt={c.name}
                className="aspect-[5/7] w-full rounded-[var(--radius-sm)] object-cover"
              />
              <div className="flex items-center justify-between text-xs">
                <span className="truncate text-[color:var(--text-default)]">{c.name}</span>
                <span className="shrink-0 text-[color:var(--text-muted)]">{c.cost}</span>
              </div>
              {used > 0 && (
                <span className="absolute right-1 top-1 rounded-[var(--radius-sm)] bg-black/80 px-1 text-xs font-mono text-white">
                  ×{used}
                </span>
              )}
              {isCore && (
                <span className="absolute left-1 top-1 text-[color:var(--warning)]" title="コアカード">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-label="コアカード">
                    <path d="M12 2l2.9 6.3 6.9.7-5.1 4.7 1.4 6.8L12 17.8 5.9 21.2l1.4-6.8L2.2 9.7l6.9-.7z" />
                  </svg>
                </span>
              )}
            </button>
          );
        })}
      </div>

      {contextMenu && (
        <div
          className="fixed z-50 min-w-[148px] overflow-hidden rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] py-1 shadow-sm"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            disabled={countOf(contextMenu.card.card_id) >= 4}
            className="w-full px-3 py-1.5 text-left text-sm text-[color:var(--text-default)] hover:bg-[var(--list-hover)] disabled:opacity-40"
            onClick={() => {
              onAdd(contextMenu.card);
              setContextMenu(null);
            }}
          >
            デッキに追加
          </button>
          {onMarkCore && (
            <button
              type="button"
              className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-sm text-[color:var(--text-default)] hover:bg-[var(--list-hover)]"
              onClick={() => {
                onMarkCore(contextMenu.card);
                setContextMenu(null);
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" className="shrink-0 text-[color:var(--warning)]" aria-hidden>
                <path d="M12 2l2.9 6.3 6.9.7-5.1 4.7 1.4 6.8L12 17.8 5.9 21.2l1.4-6.8L2.2 9.7l6.9-.7z" />
              </svg>
              {coreCardIds?.has(contextMenu.card.card_id) ? "コアを解除" : "コアに指定"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
