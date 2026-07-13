// VSCode 風ワークスペース状態: 開いているタブ + アクティビティビュー + サイドバー開閉。
// ルーティングは Next の route ベースのまま、 「開いたページ = タブ」 をクライアント状態で管理する。
import { create } from "zustand";

export type Tab = { id: string; title: string };
export type ActivityView = "explorer" | "cards" | "play" | "faq";

interface WorkspaceState {
  tabs: Tab[];
  activeView: ActivityView;
  sidebarOpen: boolean;
  collapsedFolders: string[];
  openTab: (t: Tab) => void;
  closeTab: (id: string) => void;
  setView: (v: ActivityView) => void;
  toggleSidebar: () => void;
  setSidebarOpen: (b: boolean) => void;
  toggleFolder: (f: string) => void;
}

export const useWorkspace = create<WorkspaceState>((set) => ({
  tabs: [],
  activeView: "explorer",
  sidebarOpen: true,
  collapsedFolders: [],
  openTab: (t) =>
    set((s) =>
      s.tabs.some((x) => x.id === t.id)
        ? { tabs: s.tabs.map((x) => (x.id === t.id ? { ...x, title: t.title } : x)) }
        : { tabs: [...s.tabs, t] },
    ),
  closeTab: (id) => set((s) => ({ tabs: s.tabs.filter((x) => x.id !== id) })),
  setView: (v) => set({ activeView: v, sidebarOpen: true }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (b) => set({ sidebarOpen: b }),
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
    "/play": "対戦",
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
