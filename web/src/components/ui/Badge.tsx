import type { ReactNode } from "react";

type Tone = "neutral" | "brand" | "accent" | "success" | "warning" | "danger";

/**
 * 全 page で 統一 する 小さい label / status badge。
 */
export function Badge({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  const tones: Record<Tone, string> = {
    neutral:
      "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200",
    brand:
      "bg-[color:var(--brand-soft)] text-[color:var(--brand-strong)] border border-[color:var(--brand-soft-border)]",
    accent:
      "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    success:
      "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200",
    warning:
      "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    danger:
      "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
