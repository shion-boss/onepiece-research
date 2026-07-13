"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useWorkspace, tabTitleFor, type ActivityView } from "@/lib/workspace";
import { AuthControls } from "./AuthControls";
import { StatusBar } from "./StatusBar";
import { fetchDecks } from "@/lib/api";

// ---- icons (VSCode codicon 風の細線 SVG) ----
const svg = (p: ReactNode) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="22" height="22">
    {p}
  </svg>
);
const IconDeck = svg(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M9 20V9" /></>);
const IconCards = svg(<><rect x="3" y="5" width="14" height="16" rx="1.5" /><path d="M7 3h13v15" /></>);
const IconPlay = svg(<path d="M6 4l14 8-14 8z" />);
const chevron = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
    <path d="M9 6l6 6-6 6" />
  </svg>
);

const IconFaq = svg(
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.6 9.2a2.4 2.4 0 1 1 3.3 2.2c-.7.4-1.1.9-1.1 1.8" />
    <path d="M12 16.6h.01" strokeLinecap="round" />
  </>,
);

// 主要ツール (上部) と Q&A (下部) を分ける = VSCode のアクティビティバー流。
const ACTIVITY_MAIN: { view: ActivityView; label: string; icon: ReactNode }[] = [
  { view: "explorer", label: "デッキ", icon: IconDeck },
  { view: "cards", label: "カード", icon: IconCards },
  { view: "play", label: "対戦", icon: IconPlay },
];
const FAQ_ACT: { view: ActivityView; label: string; icon: ReactNode } = {
  view: "faq",
  label: "ルール Q&A",
  icon: IconFaq,
};

type DeckRow = { slug: string; name: string; kind?: string; leader_color?: string[] };

const COLOR_HEX: Record<string, string> = {
  赤: "#f14c4c", 緑: "#4ec9b0", 青: "#3794ff", 紫: "#c586c0", 黒: "#6a6a72", 黄: "#cca700",
};

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const path = usePathname() || "/";
  const router = useRouter();
  const { tabs, openTab, closeTab, activeView, setView, sidebarOpen, toggleSidebar } =
    useWorkspace();
  const [matchActive, setMatchActive] = useState(false);

  useEffect(() => {
    function onChange(e: Event) {
      setMatchActive((e as CustomEvent<boolean>).detail === true);
    }
    window.addEventListener("match-state-change", onChange as EventListener);
    return () =>
      window.removeEventListener("match-state-change", onChange as EventListener);
  }, []);
  useEffect(() => {
    if (!path.startsWith("/play")) setMatchActive(false);
  }, [path]);

  // 現在のルートをタブとして開く (= 遷移した先が自動でタブになる)。
  useEffect(() => {
    openTab({ id: path, title: tabTitleFor(path) });
  }, [path, openTab]);

  // 対戦中 (full-screen board) はシェルの chrome を隠す。
  if (path.startsWith("/play") && matchActive) return <>{children}</>;

  const onCloseTab = (id: string) => {
    const idx = tabs.findIndex((t) => t.id === id);
    closeTab(id);
    if (id === path) {
      const rest = tabs.filter((t) => t.id !== id);
      const next = rest[idx] ?? rest[idx - 1] ?? rest[rest.length - 1];
      router.push(next ? next.id : "/");
    }
  };

  const onActivity = (v: ActivityView) => {
    if (v === activeView && sidebarOpen) toggleSidebar();
    else setView(v);
  };

  const renderAct = (a: { view: ActivityView; label: string; icon: ReactNode }) => {
    const on = a.view === activeView && sidebarOpen;
    return (
      <button
        key={a.view}
        type="button"
        title={a.label}
        onClick={() => onActivity(a.view)}
        className="flex h-11 w-full items-center justify-center border-l-2 transition-colors"
        style={{ color: on ? "#fff" : "var(--text-muted)", borderLeftColor: on ? "#fff" : "transparent" }}
      >
        {a.icon}
      </button>
    );
  };

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1">
        {/* activity bar */}
        <div
          className="flex w-12 shrink-0 flex-col items-center border-r pt-2"
          style={{ background: "var(--activity-bar)", borderColor: "var(--border-1)" }}
        >
          {ACTIVITY_MAIN.map(renderAct)}
          <div className="flex-1" />
          {renderAct(FAQ_ACT)}
        </div>

        {/* sidebar panel */}
        {sidebarOpen && (
          <aside
            className="flex w-56 shrink-0 flex-col border-r"
            style={{ background: "var(--sidebar-bg)", borderColor: "var(--border-1)" }}
          >
            <div className="flex items-center gap-2 border-b px-3 py-3" style={{ borderColor: "var(--border-1)" }}>
              <span
                className="flex h-6 w-6 items-center justify-center rounded text-[10px] font-bold text-white"
                style={{ background: "var(--brand)" }}
                aria-hidden
              >
                OP
              </span>
              <span className="text-[13px] font-semibold text-[color:var(--text-strong)]">OPTCG</span>
            </div>
            <div className="min-h-0 flex-1 overflow-auto log-scroll">
              <SidebarPanel view={activeView} path={path} />
            </div>
            <div className="border-t px-3 py-2.5" style={{ borderColor: "var(--border-1)" }}>
              <AuthControls />
            </div>
          </aside>
        )}

        {/* editor: tabs + content */}
        <main className="flex min-w-0 flex-1 flex-col" style={{ background: "var(--editor-bg)" }}>
          <div
            className="flex h-9 shrink-0 items-stretch overflow-x-auto border-b"
            style={{ background: "var(--sidebar-bg)", borderColor: "var(--border-1)" }}
          >
            {tabs.map((t) => {
              const on = t.id === path;
              return (
                <div
                  key={t.id}
                  className="group flex shrink-0 items-center gap-2 border-r pl-3 pr-2 text-[12px]"
                  style={{
                    borderColor: "var(--border-1)",
                    background: on ? "var(--editor-bg)" : "transparent",
                    color: on ? "var(--text-strong)" : "var(--text-muted)",
                    boxShadow: on ? "inset 0 1px 0 var(--brand)" : undefined,
                  }}
                >
                  <Link href={t.id} className="py-2">
                    {t.title}
                  </Link>
                  <button
                    type="button"
                    aria-label="タブを閉じる"
                    onClick={() => onCloseTab(t.id)}
                    className="flex h-4 w-4 items-center justify-center rounded text-[color:var(--text-muted)] opacity-0 hover:bg-[var(--surface-3)] hover:text-white group-hover:opacity-100"
                  >
                    <svg viewBox="0 0 24 24" width="11" height="11" stroke="currentColor" strokeWidth="2" fill="none">
                      <path d="M6 6l12 12M18 6L6 18" />
                    </svg>
                  </button>
                </div>
              );
            })}
          </div>
          <div className="min-h-0 flex-1 overflow-auto log-scroll">{children}</div>
        </main>
      </div>
      <StatusBar />
    </div>
  );
}

// ---- sidebar panel: activeView 毎に内容を切替 ----
function SidebarPanel({ view, path }: { view: ActivityView; path: string }) {
  if (view === "cards") {
    return (
      <div className="py-2">
        <PanelHeader>カード</PanelHeader>
        <PanelLink href="/cards" active={path === "/cards"}>すべてのカードを開く</PanelLink>
        <div className="px-4 pb-1 pt-3 text-[10px] uppercase tracking-wider text-[color:var(--text-muted)]">色で絞る</div>
        {Object.keys(COLOR_HEX).map((c) => (
          <Link
            key={c}
            href={`/cards?color=${encodeURIComponent(c)}`}
            className="flex items-center gap-2 px-4 py-1.5 text-[13px] text-[color:var(--text-default)] hover:bg-[var(--list-hover)] hover:text-white"
          >
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: COLOR_HEX[c] }} />
            {c}
          </Link>
        ))}
      </div>
    );
  }
  if (view === "play") {
    return (
      <div className="py-2">
        <PanelHeader>対戦</PanelHeader>
        <PanelLink href="/play" active={path === "/play"}>対戦をはじめる</PanelLink>
        <p className="px-4 pt-2 text-[11px] leading-relaxed text-[color:var(--text-muted)]">
          自分の（非公開）デッキを選んで、環境デッキの AI と対戦します。
        </p>
      </div>
    );
  }
  if (view === "faq") {
    return (
      <div className="py-2">
        <PanelHeader>ルール Q&amp;A</PanelHeader>
        <PanelLink href="/faq" active={path === "/faq"}>Q&amp;A を開く</PanelLink>
        <p className="px-4 pt-2 text-[11px] leading-relaxed text-[color:var(--text-muted)]">
          公式ルール・カードの裁定を検索できます。
        </p>
      </div>
    );
  }
  return <ExplorerPanel path={path} />;
}

function ExplorerPanel({ path }: { path: string }) {
  const [decks, setDecks] = useState<DeckRow[] | null>(null);
  useEffect(() => {
    let alive = true;
    fetchDecks()
      .then((d) => alive && setDecks(d as DeckRow[]))
      .catch(() => alive && setDecks([]));
    return () => {
      alive = false;
    };
  }, []);
  const mine = decks?.filter((d) => d.kind === "user") ?? [];
  const meta = decks?.filter((d) => d.kind === "meta") ?? [];
  return (
    <div className="py-2">
      <PanelHeader>エクスプローラー</PanelHeader>
      <Section label="マイデッキ（非公開）" />
      {decks === null && <Muted>読み込み中…</Muted>}
      {decks !== null && mine.length === 0 && <Muted>まだデッキがありません</Muted>}
      {mine.map((d) => (
        <DeckRowLink key={d.slug} deck={d} active={path === `/decks/${d.slug}`} />
      ))}
      <Link
        href="/decks/new"
        className="flex items-center gap-2 px-4 py-1.5 text-[13px] text-[color:var(--brand-strong)] hover:bg-[var(--list-hover)]"
      >
        ＋ 新規デッキ
      </Link>
      <div className="mt-2">
        <Section label="環境デッキ（相手候補）" />
        {meta.map((d) => (
          <DeckRowLink key={d.slug} deck={d} active={path === `/decks/${d.slug}`} meta />
        ))}
      </div>
    </div>
  );
}

function DeckRowLink({ deck, active, meta }: { deck: DeckRow; active: boolean; meta?: boolean }) {
  const color = deck.leader_color?.[0];
  return (
    <Link
      href={`/decks/${deck.slug}`}
      className="flex items-center gap-2 px-4 py-1.5 text-[13px] hover:bg-[var(--list-hover)]"
      style={
        active
          ? { background: "var(--brand-soft)", color: "#fff", boxShadow: "inset 2px 0 0 var(--brand)" }
          : { color: "var(--text-default)" }
      }
    >
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-sm"
        style={{ background: (color && COLOR_HEX[color]) || "#4a4a52" }}
      />
      <span className="flex-1 truncate">{deck.name}</span>
      {meta && <span className="text-[10px] text-[color:var(--text-muted)]">meta</span>}
    </Link>
  );
}

function PanelHeader({ children }: { children: ReactNode }) {
  return (
    <div className="px-4 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-wider text-[color:var(--text-muted)]">
      {children}
    </div>
  );
}
function Section({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-1 px-3 py-1 text-[11px] font-medium text-[color:var(--text-muted)]">
      {chevron}
      {label}
    </div>
  );
}
function PanelLink({ href, active, children }: { href: string; active?: boolean; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="block px-4 py-1.5 text-[13px] hover:bg-[var(--list-hover)] hover:text-white"
      style={active ? { color: "#fff", boxShadow: "inset 2px 0 0 var(--brand)" } : { color: "var(--text-default)" }}
    >
      {children}
    </Link>
  );
}
function Muted({ children }: { children: ReactNode }) {
  return <div className="px-4 py-1.5 text-[12px] text-[color:var(--text-muted)]">{children}</div>;
}
