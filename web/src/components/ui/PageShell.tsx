import type { ReactNode } from "react";

/**
 * 全 page で 共通 の outer shell。
 * `<main>` を 提供 + 横幅 / padding を 統一。
 *
 * 設計方針 (= 2026-05-27): 全 page で 横幅 固定 (= max-w-6xl) して 視覚的安定 を 優先。
 * ナビ 移動 で コンテンツ が 横に シフトしない (= 「酔う」 を 防止)。
 * grid / table 多い page (= /cards / /meta) は 内部で 横スクロール や 縦並び 切替 で対応。
 */
export function PageShell({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-6xl flex-1 space-y-6 px-6 py-8">
      {children}
    </main>
  );
}
