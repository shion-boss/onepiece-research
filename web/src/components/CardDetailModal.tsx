"use client";

import type { Card } from "@/lib/types";
import type { BanInfo } from "@/lib/banlist";
import { CardImage } from "./CardImage";
import { ColorChip } from "./ColorChip";

// 規制 (禁止/制限/ペア) + スタンダード使用可否 の補足説明を組み立てる。
function restrictionNotes(card: Card, ban?: BanInfo): { title: string; desc: string; tone: "danger" | "warning" }[] {
  const notes: { title: string; desc: string; tone: "danger" | "warning" }[] = [];
  if (ban?.kind === "forbidden") {
    notes.push({ title: "禁止カード", desc: "禁止リストに指定されています。デッキに採用できません。", tone: "danger" });
  } else if (ban?.kind === "restricted") {
    notes.push({ title: "制限カード", desc: "制限リストに指定されています。採用できる枚数に制限があります。", tone: "warning" });
  } else if (ban?.kind === "pair") {
    const partners = ban.partners?.join("・") ?? "特定のカード";
    notes.push({ title: "ペア制限", desc: `${partners} と同じデッキに同時採用できません（どちらか一方のみ）。`, tone: "warning" });
  }
  // block①〜②未満 = スタンダードレギュレーション使用不可 (block_icon は 1〜5、 CardTile の判定に合わせる)
  if (card.block_icon >= 1 && card.block_icon < 2) {
    notes.push({ title: "スタンダード使用不可", desc: "現行スタンダードレギュレーション（block② 以降）では使用できません。", tone: "danger" });
  }
  return notes;
}

export function CardDetailModal({
  card,
  onClose,
  ban,
}: {
  card: Card | null;
  onClose: () => void;
  ban?: BanInfo;
}) {
  if (!card) return null;
  const notes = restrictionNotes(card, ban);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="grid max-h-[92vh] w-full max-w-5xl gap-8 overflow-auto rounded-[var(--radius-lg)] border border-[color:var(--border-2)] bg-[color:var(--surface-1)] p-7 sm:grid-cols-[auto_1fr]"
        onClick={(e) => e.stopPropagation()}
      >
        <CardImage
          cardId={card.card_id}
          alt={card.name}
          className="aspect-[5/7] w-72 rounded object-cover lg:w-80"
          loading="eager"
        />
        <div className="space-y-4">
          <div className="flex items-start justify-between gap-2">
            <div className="space-y-0.5">
              <h2 className="text-2xl font-semibold text-[color:var(--text-strong)]">{card.name}</h2>
              <div
                className="select-all font-mono text-sm text-[color:var(--text-muted)]"
                title="カード番号 (クリックで選択 → 検索に使える)"
              >
                {card.card_id}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 text-[color:var(--text-muted)] hover:text-[color:var(--text-strong)]"
              aria-label="close"
            >
              ✕
            </button>
          </div>
          <div className="flex flex-wrap gap-1">
            {card.color.map((c) => (
              <ColorChip key={c} color={c} />
            ))}
            <span className="rounded-[var(--radius-sm)] bg-[color:var(--surface-3)] px-2 text-xs text-[color:var(--text-default)]">
              {card.category}
            </span>
            <span className="rounded-[var(--radius-sm)] bg-[color:var(--surface-3)] px-2 text-xs text-[color:var(--text-default)]">
              {card.rarity}
            </span>
          </div>
          {notes.length > 0 && (
            <div className="space-y-2">
              {notes.map((n) => {
                const color = n.tone === "danger" ? "var(--danger)" : "var(--warning)";
                return (
                  <div
                    key={n.title}
                    className="rounded-[var(--radius)] border-l-2 p-3"
                    style={{ borderColor: color, background: "color-mix(in srgb, " + color + " 10%, transparent)" }}
                  >
                    <div className="text-sm font-semibold" style={{ color }}>
                      {n.title}
                    </div>
                    <p className="mt-0.5 text-xs text-[color:var(--text-default)]">{n.desc}</p>
                  </div>
                );
              })}
            </div>
          )}
          <dl className="grid grid-cols-3 gap-2 text-sm">
            <Stat label="cost" value={card.cost} />
            <Stat label="power" value={card.power} />
            <Stat label="counter" value={card.counter} />
            <Stat label="life" value={card.life} />
            <Stat label="block" value={card.block_icon} />
            <Stat label="attr" value={card.attribute || "-"} />
          </dl>
          {card.features.length > 0 && (
            <div>
              <div className="text-xs text-[color:var(--text-muted)]">特徴</div>
              <div className="text-sm text-[color:var(--text-default)]">{card.features.join(" / ")}</div>
            </div>
          )}
          {card.text && (
            <div>
              <div className="text-xs text-[color:var(--text-muted)]">テキスト</div>
              <p className="whitespace-pre-wrap text-base leading-relaxed text-[color:var(--text-default)]">
                {card.text}
              </p>
            </div>
          )}
          {card.trigger && (
            <div>
              <div className="text-xs text-[color:var(--text-muted)]">トリガー</div>
              <p className="whitespace-pre-wrap text-base leading-relaxed text-[color:var(--text-default)]">
                {card.trigger}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-xs text-[color:var(--text-muted)]">{label}</dt>
      <dd className="font-mono text-[color:var(--text-default)]">{value}</dd>
    </div>
  );
}
