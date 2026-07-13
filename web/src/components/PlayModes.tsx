"use client";

import { useEffect, useState, type ReactNode } from "react";
import { HumanMatchPlay } from "./HumanMatchPlay";
import { MatrixSpectate } from "./MatrixSpectate";

type DeckOption = { slug: string; name: string; kind?: string };

// 対戦の入口: 人間 vs AI (自分でプレイ) / AI vs AI (2 デッキを選んで観戦) を切替。
export function PlayModes({
  decks,
  initialDeckA,
}: {
  decks: DeckOption[];
  initialDeckA?: string;
}) {
  const [mode, setMode] = useState<"human" | "ai">("human");
  const [matchActive, setMatchActive] = useState(false);
  useEffect(() => {
    const onChange = (e: Event) =>
      setMatchActive((e as CustomEvent<boolean>).detail === true);
    window.addEventListener("match-state-change", onChange as EventListener);
    return () =>
      window.removeEventListener("match-state-change", onChange as EventListener);
  }, []);

  return (
    <div className="flex w-full flex-1 flex-col">
      {/* モード切替 (対戦中は隠す) */}
      {!matchActive && (
        <div
          className="flex shrink-0 gap-1 border-b p-2"
          style={{ borderColor: "var(--border-1)" }}
        >
          <ModeBtn active={mode === "human"} onClick={() => setMode("human")}>
            人間 vs AI
          </ModeBtn>
          <ModeBtn active={mode === "ai"} onClick={() => setMode("ai")}>
            AI vs AI（観戦）
          </ModeBtn>
        </div>
      )}
      {mode === "human" ? (
        <HumanMatchPlay decks={decks} initialDeckA={initialDeckA} />
      ) : (
        <MatrixSpectate decks={decks} initialDeckA={initialDeckA} />
      )}
    </div>
  );
}

function ModeBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-[var(--radius)] px-3.5 py-1.5 text-sm font-medium transition-colors"
      style={
        active
          ? { background: "var(--brand)", color: "#fff" }
          : { color: "var(--text-muted)" }
      }
    >
      {children}
    </button>
  );
}
