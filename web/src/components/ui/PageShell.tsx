import type { ReactNode } from "react";

/**
 * 全 page で 共通 の outer shell。
 * `<main>` を 提供 + 横幅 / padding を 統一。
 *
 * variant:
 * - "default" (= ~max-w-6xl): 一般 page 用
 * - "wide" (= ~max-w-7xl): grid / table 重視 page (= /cards / /meta)
 * - "narrow" (= ~max-w-3xl): text-heavy / form page (= /faq / /decks/new)
 */
export function PageShell({
  children,
  variant = "default",
}: {
  children: ReactNode;
  variant?: "default" | "wide" | "narrow";
}) {
  const maxW =
    variant === "wide"
      ? "max-w-7xl"
      : variant === "narrow"
      ? "max-w-3xl"
      : "max-w-6xl";
  return (
    <main className={`mx-auto w-full flex-1 ${maxW} space-y-6 px-6 py-8`}>
      {children}
    </main>
  );
}
