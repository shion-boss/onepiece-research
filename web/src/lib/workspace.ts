// VSCode 風ワークスペース状態: 開いているタブ + アクティビティビュー + サイドバー開閉。
// ルーティングは Next の route ベースのまま、 「開いたページ = タブ」 をクライアント状態で管理する。
import { create } from "zustand";

export type Tab = { id: string; title: string };
export type ActivityView = "grow" | "explorer" | "cards" | "play" | "faq" | "history";

interface WorkspaceState {
  tabs: Tab[];
  activeTabId: string; // 現在アクティブなタブ ID (= pathname、 /cards は絞り込みクエリ込み)
  activeView: ActivityView;
  sidebarOpen: boolean;
  sidebarWidth: number;
  collapsedFolders: string[];
  openTab: (t: Tab) => void;
  closeTab: (id: string) => void;
  setActiveTabId: (id: string) => void;
  setView: (v: ActivityView) => void;
  toggleSidebar: () => void;
  setSidebarOpen: (b: boolean) => void;
  setSidebarWidth: (w: number) => void;
  toggleFolder: (f: string) => void;
}

export const useWorkspace = create<WorkspaceState>((set) => ({
  tabs: [],
  activeTabId: "/",
  activeView: "explorer",
  sidebarOpen: true,
  sidebarWidth: 224,
  collapsedFolders: [],
  openTab: (t) =>
    set((s) =>
      s.tabs.some((x) => x.id === t.id)
        ? { tabs: s.tabs.map((x) => (x.id === t.id ? { ...x, title: t.title } : x)) }
        : { tabs: [...s.tabs, t] },
    ),
  closeTab: (id) => set((s) => ({ tabs: s.tabs.filter((x) => x.id !== id) })),
  setActiveTabId: (id) => set({ activeTabId: id }),
  setView: (v) => set({ activeView: v, sidebarOpen: true }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (b) => set({ sidebarOpen: b }),
  setSidebarWidth: (w) => set({ sidebarWidth: w }),
  toggleFolder: (f) =>
    set((s) => ({
      collapsedFolders: s.collapsedFolders.includes(f)
        ? s.collapsedFolders.filter((x) => x !== f)
        : [...s.collapsedFolders, f],
    })),
}));

// パス → タブ表示名。 未知は末尾セグメント。
export function tabTitleFor(path: string): string {
  const map: Record<string, string> = {
    "/": "ようこそ",
    "/grow": "みんなで育てる",
    "/history": "戦いの歴史",
    "/play": "人間 vs AI",
    "/watch": "AI vs AI 観戦",
    "/winrate": "AI vs AI 勝率",
    "/decks": "マイデッキ",
    "/decks/new": "新規デッキ",
    "/decks/generate": "デッキ生成",
    "/cards": "カード",
    "/faq": "Q&A",
    "/combos": "コンボ探索",
    "/meta": "メタ分析",
    "/research": "研究",
  };
  if (map[path]) return map[path];
  const seg = path.split("/").filter(Boolean);
  if (seg[0] === "decks" && seg[1]) {
    if (seg[2] === "analyze") return `${seg[1]} · 分析`;
    return seg[1];
  }
  return seg[seg.length - 1] ?? path;
}
