"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { HumanMatchPlay } from "@/components/HumanMatchPlay";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type Step = {
  turn: number;
  state: Record<string, unknown>;
  ideal_summary: string;
  ideal_actions: string[];
  reasoning: string;
};
type Course = {
  course_id: string;
  title: string;
  source: string;
  matchup_note: string;
  my_deck: string;
  opp_deck: string;
  steps: Step[];
};

export default function TrainingPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [si, setSi] = useState(0);
  const [showAnswer, setShowAnswer] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/api/training/courses`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setCourses(d.courses ?? []))
      .catch(() => setErr("コースの読み込みに失敗しました (API 未起動の可能性)"));
  }, []);

  if (err || !courses.length) {
    return (
      <main className="flex w-full flex-1 items-center justify-center p-8 text-sm text-[var(--text-muted)]">
        {err ?? "読み込み中..."}
      </main>
    );
  }

  const course = courses[0];
  const step = course.steps[si];
  const isLast = si === course.steps.length - 1;
  const decks = [
    { slug: course.my_deck, name: course.my_deck, kind: "meta" },
    { slug: course.opp_deck, name: course.opp_deck, kind: "meta" },
  ];

  const nextStep = () => {
    setShowAnswer(false);
    if (!isLast) setSi((s) => s + 1);
  };

  return (
    // /play と同じ full-screen 構造 (盤面は h-[100dvh])。 コース情報は絶対配置で盤面の高さを圧迫しない。
    <main className="relative flex w-full flex-1 flex-col">
      <HumanMatchPlay
        key={`${course.course_id}-${si}`}
        decks={decks}
        puzzle={{
          // turn を state に含めて盤面を正しいターン表示にする (= コースと一致)。
          state: { ...step.state, turn: step.turn },
          myDeck: course.my_deck,
          oppDeck: course.opp_deck,
          onTurnDone: () => setShowAnswer(true),
        }}
      />

      {/* 左上 コース情報 + 答えを見る (= 盤面 overlay。 右上は対戦終了/速度なので左上に) */}
      <div className="absolute left-2 top-2 z-40 flex items-center gap-2 rounded-lg border border-white/15 bg-zinc-900/85 px-2.5 py-1 shadow-lg backdrop-blur">
        <span className="text-xs font-semibold text-white">操縦コース</span>
        <span className="text-xs text-zinc-300">{course.title.split(" 操縦")[0]}</span>
        <Badge tone="brand">{step.turn}ターン目</Badge>
        <span className="text-xs text-zinc-400">
          {si + 1}/{course.steps.length}
        </span>
        <button
          onClick={() => setShowAnswer(true)}
          className="rounded border border-amber-400/60 px-2 py-0.5 text-xs font-semibold text-amber-200 hover:bg-amber-900/40"
        >
          答えを見る
        </button>
      </div>

      {/* プロの理想手モーダル */}
      {showAnswer && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[85vh] w-full max-w-lg overflow-auto rounded-[var(--radius)] border border-[var(--border-1)] bg-[var(--surface-1)] p-5 shadow-xl">
            <div className="mb-3 flex items-center gap-2">
              <Badge tone="brand">{step.turn}ターン目</Badge>
              <span className="text-sm font-medium text-[var(--text-strong)]">プロの理想手</span>
            </div>
            <p className="text-sm text-[var(--text-strong)]">{step.ideal_summary}</p>
            {step.ideal_actions?.length > 0 && (
              <ul className="mt-2 ml-4 list-disc text-sm text-[var(--text-muted)]">
                {step.ideal_actions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            )}
            <div className="mt-4">
              <span className="text-xs font-medium text-[var(--text-muted)]">理由</span>
              <p className="mt-1 text-sm text-[var(--text-muted)]">{step.reasoning}</p>
            </div>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                onClick={() => setShowAnswer(false)}
                className="rounded-[var(--radius-sm)] border border-[var(--border-1)] px-3 py-1.5 text-sm text-[var(--text-muted)]"
              >
                この局面をもう一度
              </button>
              {isLast ? (
                <span className="text-sm text-[var(--text-strong)]">コース完了</span>
              ) : (
                <button
                  onClick={nextStep}
                  className="rounded-[var(--radius-sm)] border border-[var(--brand)] bg-[var(--brand)]/10 px-4 py-1.5 text-sm text-[var(--text-strong)]"
                >
                  次のターンへ
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
