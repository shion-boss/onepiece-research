"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/ui/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { CardImage } from "@/components/CardImage";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const Ico = ({ d, className }: { d: string; className?: string }) => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
    <path d={d} />
  </svg>
);
const IcoLeft = (p: { className?: string }) => <Ico d="M15 18l-6-6 6-6" {...p} />;
const IcoRight = (p: { className?: string }) => <Ico d="M9 18l6-6-6-6" {...p} />;
const IcoEye = (p: { className?: string }) => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={p.className} aria-hidden>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

type CardBrief = { card_id: string; name: string; power: number | null; dons?: number };
type Board = {
  my_leader: CardBrief;
  my_chars: CardBrief[];
  opp_leader: CardBrief;
  opp_chars: CardBrief[];
  my_hand: CardBrief[];
  opp_hand_count: number;
  opp_life: number;
  my_don: number;
};
type Step = {
  turn: number;
  board: Board;
  ideal_summary: string;
  ideal_actions: string[];
  reasoning: string;
};
type Course = {
  course_id: string;
  title: string;
  source: string;
  matchup_note: string;
  steps: Step[];
};

function CardMini({ c, small }: { c: CardBrief; small?: boolean }) {
  return (
    <div className="relative shrink-0">
      <CardImage
        cardId={c.card_id}
        alt={c.name}
        remoteFirst
        className={`${small ? "w-12" : "w-16"} aspect-[5/7] rounded-[var(--radius-sm)] border border-[var(--border-1)] object-cover`}
      />
      {c.power != null && (
        <span className="absolute bottom-0 right-0 rounded-tl bg-black/75 px-1 text-[10px] font-medium text-white">
          {c.power}
          {c.dons ? `+${c.dons}` : ""}
        </span>
      )}
    </div>
  );
}

function Row({ label, cards, empty }: { label: string; cards: CardBrief[]; empty: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-14 shrink-0 text-xs text-[var(--text-muted)]">{label}</span>
      {cards.length === 0 ? (
        <span className="text-xs text-[var(--text-muted)]">{empty}</span>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {cards.map((c, i) => (
            <CardMini key={`${c.card_id}-${i}`} c={c} small={label === "手札"} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function TrainingPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [ci, setCi] = useState(0);
  const [si, setSi] = useState(0);
  const [reveal, setReveal] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/api/training/courses`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setCourses(d.courses ?? []))
      .catch(() => setErr("コースの読み込みに失敗しました (API 未起動の可能性)"));
  }, []);

  const goStep = (delta: number, steps: Step[]) => {
    setSi((s) => Math.min(Math.max(s + delta, 0), steps.length - 1));
    setReveal(false);
  };

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
  const b = step.board;

  return (
    <PageShell>
      <PageHeader
        title="操縦コース"
        description="プロの盤面で1ターンの理想操縦を学ぶ (pros02 進行記事より)"
        meta={<span className="text-xs text-[var(--text-muted)]">{course.source}</span>}
      />

      {/* コース選択 */}
      {courses.length > 1 && (
        <div className="flex gap-2">
          {courses.map((c, i) => (
            <button
              key={c.course_id}
              onClick={() => {
                setCi(i);
                setSi(0);
                setReveal(false);
              }}
              className={`rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm ${
                i === ci
                  ? "border-[var(--brand)] bg-[var(--brand)]/10 text-[var(--text-strong)]"
                  : "border-[var(--border-1)] text-[var(--text-muted)]"
              }`}
            >
              {c.title}
            </button>
          ))}
        </div>
      )}

      <div className="rounded-[var(--radius)] border border-[var(--border-1)] bg-[var(--surface-1)] p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-[var(--text-strong)]">{course.title}</span>
            <Badge tone="brand">{step.turn}ターン目</Badge>
          </div>
          <span className="text-xs text-[var(--text-muted)]">
            ステップ {si + 1} / {course.steps.length}
          </span>
        </div>
        <p className="mb-4 text-xs text-[var(--text-muted)]">{course.matchup_note}</p>

        {/* 盤面 */}
        <div className="space-y-4">
          {/* 相手 */}
          <div className="rounded-[var(--radius-sm)] border border-[var(--border-1)] bg-[var(--surface-2,transparent)] p-3">
            <div className="mb-2 flex items-center gap-3 text-xs text-[var(--text-muted)]">
              <span className="font-medium text-[var(--text-strong)]">相手: {b.opp_leader.name}</span>
              <span>ライフ {b.opp_life}</span>
              <span>手札 {b.opp_hand_count}</span>
            </div>
            <div className="flex items-start gap-3">
              <CardMini c={b.opp_leader} />
              <Row label="盤面" cards={b.opp_chars} empty="キャラなし" />
            </div>
          </div>

          {/* 自分 */}
          <div className="rounded-[var(--radius-sm)] border border-[var(--brand)]/40 p-3">
            <div className="mb-2 flex items-center gap-3 text-xs text-[var(--text-muted)]">
              <span className="font-medium text-[var(--text-strong)]">あなた: {b.my_leader.name}</span>
              <span>DON {b.my_don}</span>
            </div>
            <div className="flex items-start gap-3">
              <CardMini c={b.my_leader} />
              <Row label="盤面" cards={b.my_chars} empty="キャラなし" />
            </div>
            <div className="mt-3">
              <Row label="手札" cards={b.my_hand} empty="手札なし" />
            </div>
          </div>
        </div>

        {/* 出題 + 答え */}
        <div className="mt-5 rounded-[var(--radius-sm)] border border-[var(--border-1)] p-3">
          <p className="text-sm text-[var(--text-strong)]">
            この局面での理想的な行動は？ 自分で考えてから答えを見てください。
          </p>
          {!reveal ? (
            <button
              onClick={() => setReveal(true)}
              className="mt-3 inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--brand)] bg-[var(--brand)]/10 px-3 py-1.5 text-sm text-[var(--text-strong)]"
            >
              <IcoEye className="h-4 w-4" /> 答えを見る
            </button>
          ) : (
            <div className="mt-3 space-y-2">
              <div>
                <span className="text-xs font-medium text-[var(--text-muted)]">プロの理想手</span>
                <p className="text-sm text-[var(--text-strong)]">{step.ideal_summary}</p>
              </div>
              {step.ideal_actions?.length > 0 && (
                <ul className="ml-4 list-disc text-sm text-[var(--text-muted)]">
                  {step.ideal_actions.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              )}
              <div>
                <span className="text-xs font-medium text-[var(--text-muted)]">理由</span>
                <p className="text-sm text-[var(--text-muted)]">{step.reasoning}</p>
              </div>
            </div>
          )}
        </div>

        {/* ステップ移動 */}
        <div className="mt-4 flex items-center justify-between">
          <button
            onClick={() => goStep(-1, course.steps)}
            disabled={si === 0}
            className="inline-flex items-center gap-1 rounded-[var(--radius-sm)] border border-[var(--border-1)] px-3 py-1.5 text-sm text-[var(--text-muted)] disabled:opacity-40"
          >
            <IcoLeft className="h-4 w-4" /> 前のターン
          </button>
          <button
            onClick={() => goStep(1, course.steps)}
            disabled={si === course.steps.length - 1}
            className="inline-flex items-center gap-1 rounded-[var(--radius-sm)] border border-[var(--border-1)] px-3 py-1.5 text-sm text-[var(--text-muted)] disabled:opacity-40"
          >
            次のターン <IcoRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </PageShell>
  );
}
