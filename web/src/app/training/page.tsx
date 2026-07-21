"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/ui/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
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
  const [ci, setCi] = useState(0);
  const [si, setSi] = useState(0);
  const [showAnswer, setShowAnswer] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/api/training/courses`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setCourses(d.courses ?? []))
      .catch(() => setErr("コースの読み込みに失敗しました (API 未起動の可能性)"));
  }, []);

  if (err) {
    return (
      <PageShell>
        <PageHeader title="操縦コース" />
        <p className="text-sm text-[var(--text-muted)]">{err}</p>
      </PageShell>
    );
  }
  if (!courses.length) {
    return (
      <PageShell>
        <PageHeader title="操縦コース" />
        <p className="text-sm text-[var(--text-muted)]">読み込み中...</p>
      </PageShell>
    );
  }

  const course = courses[ci];
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
  const restart = () => setShowAnswer(false);

  return (
    <PageShell>
      <PageHeader
        title="操縦コース"
        description="プロの盤面で1ターンの理想操縦を実際に打って学ぶ (pros02 進行記事より)"
        meta={<span className="text-xs text-[var(--text-muted)]">{course.source}</span>}
      />

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-[var(--text-strong)]">{course.title}</span>
        <Badge tone="brand">{step.turn}ターン目</Badge>
        <span className="text-xs text-[var(--text-muted)]">
          ステップ {si + 1} / {course.steps.length}
        </span>
        <button
          onClick={() => setShowAnswer(true)}
          className="ml-auto rounded-[var(--radius-sm)] border border-[var(--border-1)] px-3 py-1.5 text-xs text-[var(--text-muted)]"
        >
          答えを見る / 降参
        </button>
      </div>
      <p className="text-xs text-[var(--text-muted)]">{course.matchup_note}</p>

      {/* 本物の対戦盤面で puzzle 局面を操作。 ターン終了で onTurnDone → モーダル */}
      <HumanMatchPlay
        key={`${course.course_id}-${si}`}
        decks={decks}
        puzzle={{
          state: step.state,
          myDeck: course.my_deck,
          oppDeck: course.opp_deck,
          onTurnDone: () => setShowAnswer(true),
        }}
      />

      {/* プロの理想手モーダル */}
      {showAnswer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
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
                onClick={restart}
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
    </PageShell>
  );
}
