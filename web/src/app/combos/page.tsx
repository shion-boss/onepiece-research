"use client";

import { useEffect, useRef, useState } from "react";
import { fetchCard, fetchCards, fetchCombos } from "@/lib/api";
import type { Card, ComboCard, ComboResult } from "@/lib/types";
import { CardImage } from "@/components/CardImage";
import { CardDetailModal } from "@/components/CardDetailModal";
import { PageHeader } from "@/components/ui/PageHeader";
import { PageShell } from "@/components/ui/PageShell";
import { Badge } from "@/components/ui/Badge";

type Tone = "neutral" | "brand" | "accent" | "success" | "warning" | "danger";

const GROUP_TONE: Record<string, Tone> = {
  enabler: "danger",
  accelerant: "brand",
  tribal: "success",
  amplifier: "accent",
};

// お試し用の入口 (= ペル等、 議論で出た例)
const EXAMPLES = [
  { card_id: "OP04-013", label: "ペル (5c)" },
  { card_id: "OP14-112", label: "ボア・ハンコック" },
  { card_id: "OP09-118", label: "ロジャー" },
];

function ScoreBar({ score, max }: { score: number; max: number }) {
  const pct = Math.max(6, Math.min(100, (score / Math.max(1, max)) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
      <div
        className="h-full rounded-full"
        style={{
          width: `${pct}%`,
          background:
            "linear-gradient(90deg, var(--brand) 0%, var(--accent) 100%)",
        }}
      />
    </div>
  );
}

function ComboCardRow({
  card,
  max,
  onOpen,
}: {
  card: ComboCard;
  max: number;
  onOpen: (cardId: string) => void;
}) {
  return (
    <li className="flex gap-3 rounded-lg border border-zinc-200 p-2.5 dark:border-zinc-800">
      <button
        type="button"
        onClick={() => onOpen(card.card_id)}
        className="w-16 shrink-0 self-start transition hover:opacity-80"
        title="カード詳細を開く"
      >
        <CardImage cardId={card.card_id} alt={card.name} className="w-full rounded" />
      </button>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onOpen(card.card_id)}
            className="truncate text-sm font-medium text-zinc-900 hover:underline dark:text-zinc-100"
          >
            {card.name}
          </button>
          <span className="shrink-0 font-mono text-xs text-zinc-400">
            {card.card_id}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
          <Badge tone="neutral">{card.category}</Badge>
          <span>コスト{card.cost}</span>
          {card.power > 0 && <span>P{card.power}</span>}
          {card.color.map((c) => (
            <span key={c}>{c}</span>
          ))}
        </div>
        {card.text && (
          <p className="whitespace-pre-wrap rounded border border-zinc-100 bg-zinc-50 px-2 py-1.5 text-xs leading-relaxed text-zinc-700 dark:border-zinc-800 dark:bg-zinc-800/40 dark:text-zinc-300">
            {card.text}
          </p>
        )}
        <p className="text-xs leading-relaxed text-amber-700 dark:text-amber-300">
          <span className="font-semibold">コンボ: </span>
          {card.reason}
        </p>
        <div className="flex items-center gap-2 pt-0.5">
          <span className="shrink-0 font-mono text-xs font-semibold text-zinc-500 dark:text-zinc-400">
            {card.score.toFixed(1)}
          </span>
          <ScoreBar score={card.score} max={max} />
        </div>
      </div>
    </li>
  );
}

export default function CombosPage() {
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<Card[]>([]);
  const [anchor, setAnchor] = useState<Card | null>(null);
  const [result, setResult] = useState<ComboResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalCard, setModalCard] = useState<Card | null>(null);
  const reqId = useRef(0);

  async function openCard(cardId: string) {
    try {
      setModalCard(await fetchCard(cardId));
    } catch {
      /* 詳細取得失敗は無視 (= inline の効果文は既に表示済) */
    }
  }

  // 名前検索 (= debounce)
  useEffect(() => {
    const q = query.trim();
    if (q.length < 1) {
      setCandidates([]);
      return;
    }
    const id = ++reqId.current;
    const t = setTimeout(async () => {
      try {
        const cards = await fetchCards({ name_contains: q, limit: 24 });
        if (id === reqId.current) setCandidates(cards);
      } catch {
        if (id === reqId.current) setCandidates([]);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  async function selectAnchor(card: Card) {
    setAnchor(card);
    setCandidates([]);
    setQuery("");
    setResult(null);
    setError(null);
    setLoading(true);
    try {
      const res = await fetchCombos(card.card_id, 8);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function selectById(cardId: string) {
    // card_id 直指定 (= お試しチップ): combos の anchor 情報で anchor を確定
    setCandidates([]);
    setQuery("");
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetchCombos(cardId, 8);
      setResult(res);
      setAnchor({
        card_id: res.anchor.card_id,
        name: res.anchor.name,
        category: res.anchor.category as Card["category"],
        color: res.anchor.color,
        cost: res.anchor.cost,
        life: 0,
        power: res.anchor.power,
        counter: 0,
        attribute: "",
        block_icon: 0,
        features: res.anchor.features,
        text: "",
        trigger: "",
        rarity: "",
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <PageShell>
      <PageHeader
        title="コンボ探索"
        description="カードを指定すると、相性の良いカードを「型」ごとにランク付きで提示します (= 静的 finder)。"
        meta={
          <span>
            recall でなく ranking が本質。 強さの裏取り (= シミュレーション) は別レイヤー。
          </span>
        }
      />

      {/* 検索 + 入口 */}
      <div className="space-y-3">
        <div className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="カード名で検索 (例: ペル)"
            className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
          {candidates.length > 0 && (
            <ul className="absolute z-10 mt-1 max-h-80 w-full overflow-auto rounded-lg border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
              {candidates.map((c) => (
                <li key={c.card_id}>
                  <button
                    type="button"
                    onClick={() => selectAnchor(c)}
                    className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  >
                    <div className="w-8 shrink-0">
                      <CardImage cardId={c.card_id} alt={c.name} className="w-full rounded" />
                    </div>
                    <span className="flex-1 truncate text-sm text-zinc-900 dark:text-zinc-100">
                      {c.name}
                    </span>
                    <span className="font-mono text-xs text-zinc-400">{c.card_id}</span>
                    <span className="text-xs text-zinc-500">c{c.cost}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
          <span>お試し:</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.card_id}
              type="button"
              onClick={() => selectById(ex.card_id)}
              className="rounded-full border border-zinc-300 px-2.5 py-1 hover:border-zinc-500 dark:border-zinc-700 dark:hover:border-zinc-500"
            >
              {ex.label}
            </button>
          ))}
        </div>
      </div>

      {/* anchor */}
      {anchor && (
        <div className="flex items-center gap-4 rounded-lg border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-900/40">
          <div className="w-16 shrink-0">
            <CardImage cardId={anchor.card_id} alt={anchor.name} className="w-full rounded" />
          </div>
          <div className="space-y-1">
            <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
              {anchor.name}
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
              <span className="font-mono">{anchor.card_id}</span>
              <span>コスト{anchor.cost}</span>
              {anchor.features.map((f) => (
                <Badge key={f} tone="neutral">
                  {f}
                </Badge>
              ))}
            </div>
            {result?.anchor.text && (
              <p className="max-w-2xl whitespace-pre-wrap rounded border border-zinc-200 bg-white px-2 py-1.5 text-xs leading-relaxed text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
                {result.anchor.text}
              </p>
            )}
            {result && result.hooks.length > 0 && (
              <ul className="space-y-0.5 pt-1 text-xs text-zinc-600 dark:text-zinc-300">
                {result.hooks.map((h, i) => (
                  <li key={i}>・{h}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {loading && (
        <div className="py-10 text-center text-sm text-zinc-500">探索中…</div>
      )}
      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          取得失敗: {error}
        </div>
      )}

      {/* 結果: 型別グループ */}
      {result &&
        !loading &&
        result.groups.map((g) => {
          const max = g.cards[0]?.score ?? 1;
          return (
            <section key={g.key} className="space-y-2">
              <div className="flex items-center gap-2">
                <Badge tone={GROUP_TONE[g.key] ?? "neutral"}>{g.label}</Badge>
                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                  {g.cards.length} 件
                </span>
              </div>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                {g.description}
              </p>
              <ul className="grid items-start gap-2 md:grid-cols-2">
                {g.cards.map((c) => (
                  <ComboCardRow
                    key={c.card_id}
                    card={c}
                    max={max}
                    onOpen={openCard}
                  />
                ))}
              </ul>
            </section>
          );
        })}

      {result && !loading && result.groups.length === 0 && (
        <div className="py-10 text-center text-sm text-zinc-500">
          このカードでは明確なコンボ候補が見つかりませんでした。
        </div>
      )}

      <CardDetailModal card={modalCard} onClose={() => setModalCard(null)} />
    </PageShell>
  );
}
