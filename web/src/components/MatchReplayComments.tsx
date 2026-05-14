"use client";

/**
 * MatchReplay の log にアノテーションを付けるための副コンポーネント群。
 *
 * 方針:
 * - 完全自由記述 (= category dropdown なし、 自由テキストのみ)
 * - **サーバ永続** (= POST /api/spectate/comments → db/spectate_comments.json)
 *   localStorage ではなく FastAPI を通すので、 Claude が直接 JSON を読める。
 *   user が「コメント確認して」 と言ったらすぐ AI 改善ループに入れる。
 * - replay key は deck_a + deck_b + first_player + winner + turns + snapshots.length で deterministic
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReplayResponse, StateSnapshot } from "@/lib/types";
import {
  addSpectateComment,
  agreeSpectateComment,
  deleteSpectateComment,
  listSpectateComments,
  unagreeSpectateComment,
  type SpectateCommentOut,
} from "@/lib/api";

// ============================================================================
// nickname (= 友達共有時の「誰が言ったか」 識別子)
// ============================================================================
// localStorage に保存して全 spectate ページで共有。 ブラウザ単位のシンプル identity。

const NICKNAME_KEY = "optcg-spectate-nickname";

export function useNickname(): [string, (n: string) => void] {
  const [nickname, setNicknameState] = useState<string>("");
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(NICKNAME_KEY) ?? "";
    setNicknameState(stored);
  }, []);
  const setNickname = useCallback((n: string) => {
    const trimmed = n.trim();
    setNicknameState(trimmed);
    if (typeof window !== "undefined") {
      try {
        if (trimmed) {
          window.localStorage.setItem(NICKNAME_KEY, trimmed);
        } else {
          window.localStorage.removeItem(NICKNAME_KEY);
        }
      } catch {
        /* quota など */
      }
    }
  }, []);
  return [nickname, setNickname];
}

// ============================================================================
// replay key
// ============================================================================

export function buildReplayKey(replay: ReplayResponse): string {
  return [
    replay.deck_a_name,
    replay.deck_b_name,
    String(replay.first_player),
    String(replay.winner),
    String(replay.turns),
    String(replay.snapshots.length),
  ].join("__");
}

// 表示用 LogComment (= サーバ output から必要分のみ)
export type LogComment = {
  id: string;
  text: string;
  created_at: string;
  author: string | null;
  agreed_by: string[];
};

// ============================================================================
// useLogComments hook (server-backed)
// ============================================================================

export function useLogComments(replay: ReplayResponse, nickname: string) {
  const replayKey = useMemo(() => buildReplayKey(replay), [replay]);
  // snapshot_idx (string) -> LogComment[]
  const [byIdx, setByIdx] = useState<Record<string, LogComment[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // replay 切替 / 初回ロード時にサーバから取得
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listSpectateComments(replayKey)
      .then((rows) => {
        if (cancelled) return;
        const map: Record<string, LogComment[]> = {};
        for (const r of rows) {
          const key = String(r.snapshot_idx);
          if (!map[key]) map[key] = [];
          map[key].push({
            id: r.id,
            text: r.text,
            created_at: r.created_at,
            author: r.author ?? null,
            agreed_by: r.agreed_by ?? [],
          });
        }
        setByIdx(map);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [replayKey]);

  const addComment = useCallback(
    async (snapIdx: number, text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      const snap = replay.snapshots[snapIdx];
      try {
        const created = await addSpectateComment({
          replay_key: replayKey,
          deck_a: replay.deck_a_name,
          deck_b: replay.deck_b_name,
          first_player: replay.first_player,
          winner: replay.winner,
          turns: replay.turns,
          snapshot_idx: snapIdx,
          snapshot_log: snap?.log ?? "",
          snapshot_turn: snap?.turn ?? null,
          text: trimmed,
          author: nickname || null,
        });
        setByIdx((prev) => {
          const key = String(snapIdx);
          const arr = prev[key] ? [...prev[key]] : [];
          arr.push({
            id: created.id,
            text: created.text,
            created_at: created.created_at,
            author: created.author ?? null,
            agreed_by: created.agreed_by ?? [],
          });
          return { ...prev, [key]: arr };
        });
      } catch (e) {
        setError(String(e));
      }
    },
    [replay, replayKey, nickname],
  );

  const deleteComment = useCallback(
    async (snapIdx: number, commentIdx: number) => {
      const key = String(snapIdx);
      const arr = byIdx[key];
      if (!arr || !arr[commentIdx]) return;
      const target = arr[commentIdx];
      try {
        await deleteSpectateComment(target.id);
        setByIdx((prev) => {
          const cur = prev[key];
          if (!cur) return prev;
          const filtered = cur.filter((_, i) => i !== commentIdx);
          const next = { ...prev };
          if (filtered.length === 0) delete next[key];
          else next[key] = filtered;
          return next;
        });
      } catch (e) {
        setError(String(e));
      }
    },
    [byIdx],
  );

  // toggleAgree: 同じ nickname の click で agree ↔ unagree を切替。
  // 友達共有時、 「同じ意見だ」 を 1 click で表明できる。
  const toggleAgree = useCallback(
    async (snapIdx: number, commentIdx: number) => {
      if (!nickname) {
        setError("nickname を設定してから 👍 してください");
        return;
      }
      const key = String(snapIdx);
      const arr = byIdx[key];
      if (!arr || !arr[commentIdx]) return;
      const target = arr[commentIdx];
      const has = target.agreed_by.includes(nickname);
      try {
        if (has) {
          await unagreeSpectateComment(target.id, nickname);
          setByIdx((prev) => {
            const cur = prev[key];
            if (!cur) return prev;
            const next = [...cur];
            next[commentIdx] = {
              ...target,
              agreed_by: target.agreed_by.filter((a) => a !== nickname),
            };
            return { ...prev, [key]: next };
          });
        } else {
          const updated = await agreeSpectateComment(target.id, nickname);
          setByIdx((prev) => {
            const cur = prev[key];
            if (!cur) return prev;
            const next = [...cur];
            next[commentIdx] = {
              ...target,
              agreed_by: updated.agreed_by ?? [],
            };
            return { ...prev, [key]: next };
          });
        }
      } catch (e) {
        setError(String(e));
      }
    },
    [byIdx, nickname],
  );

  const getComments = useCallback(
    (snapIdx: number): LogComment[] => byIdx[String(snapIdx)] ?? [],
    [byIdx],
  );

  const totalCount = useMemo(
    () => Object.values(byIdx).reduce((acc, arr) => acc + arr.length, 0),
    [byIdx],
  );

  return {
    byIdx,
    addComment,
    deleteComment,
    toggleAgree,
    getComments,
    totalCount,
    loading,
    error,
    nickname,
  };
}

// ============================================================================
// コンテキストバッジ検出 (= snapshot.log + players state から)
// ============================================================================

export type LogBadge = {
  label: string; // 短い表示テキスト (例: "rested target")
  tone: "warn" | "info" | "danger";
  title: string; // tooltip 用の長い説明
};

/**
 * snapshot 1 つを見て、 検出できるバッジ群を返す。 client-side のヒューリスティック判定。
 *
 * 現在の検出:
 * - **rested target ⚠️**: log に "attach don to <name>" があり、 直前 snapshot で
 *   target が rested 状態 (= 攻撃済) かつ次以降で attack されない場合
 * - **leader DON when rested ⚠️**: attach don to leader, leader が rested
 * - **wasted DON**: END phase で don_active > 0 かつ未使用
 * - **low-power attack**: attack の attacker power < target power (= 確定 KO 失敗 / カウンター必要)
 *
 * 完璧ではない (engine の action_evals.context があればもっと精密) が、 観戦者の気付き
 * 補助には十分。 後で精密化可能。
 */
export function detectBadges(
  snap: StateSnapshot,
  snapIdx: number,
  allSnapshots: StateSnapshot[],
): LogBadge[] {
  const badges: LogBadge[] = [];
  const log = snap.log || "";

  // パターン 1: attach don to <chara name>
  // log 例: "T3 P0: attach don to ロロノア・ゾロ x1 (P=6000)"
  const attachCharaMatch = log.match(/attach don to (.+?) x\d+/);
  const isAttachToLeader = /attach don to leader/.test(log);

  if (attachCharaMatch && !isAttachToLeader) {
    const charaName = attachCharaMatch[1].trim();
    // turn_player の場の同名キャラ全部を取得。 同名複数 (= dup) があり、 1 つでも
    // active なら user の意図した target は active 側の可能性が高い (= log には iid 無し
    // → 名前から特定不可)。 そのため: 全 同名キャラが rested の時だけ badge を出す
    // (= false positive を抑える、 観戦コメント #7 由来の修正)。
    const me = snap.players[snap.turn_player_idx];
    if (me && me.characters) {
      const targets = me.characters.filter((c) => c.name === charaName);
      if (targets.length > 0) {
        const allRested = targets.every((c) => c.rested);
        const allSickness = targets.every(
          (c) => c.summoning_sickness && !c.rested,
        );
        if (allRested) {
          badges.push({
            label: "rested target",
            tone: "warn",
            title: `${charaName} は ${targets.length === 1 ? "" : `${targets.length} 体すべて`}rested (= 攻撃済 or sickness)。 このターン中に追加 attack できないため、 attached DON は次ターンまで活用されない (機会損失の可能性)。`,
          });
        }
        if (allSickness) {
          badges.push({
            label: "sickness target",
            tone: "warn",
            title: `${charaName} は ${targets.length === 1 ? "" : `${targets.length} 体すべて`}summoning sickness 中。 Rush キーワード等がなければこのターン attack できない (= attach DON は次ターン以降の効果)。`,
          });
        }
      }
    }
  }

  // パターン 2: attach don to leader, leader rested
  if (isAttachToLeader) {
    const me = snap.players[snap.turn_player_idx];
    if (me && me.leader && me.leader.rested) {
      badges.push({
        label: "rested leader",
        tone: "warn",
        title:
          "リーダーが既に rested (= 攻撃済)。 attached DON はこのターン中の attack に使えない。",
      });
    }
  }

  // パターン 3: END phase で don_active > 0 (= 未使用 DON)
  // log 例: "T3 P0: end phase" + phase=END
  if (snap.phase === "END") {
    const me = snap.players[snap.turn_player_idx];
    if (me && (me.don_active ?? 0) > 0) {
      badges.push({
        label: `${me.don_active} unused DON`,
        tone: "info",
        title: `MAIN フェイズ終了時に DON が ${me.don_active} 残っている。 attach / カードプレイ / イベント等に使う余地があった可能性。`,
      });
    }
  }

  // パターン 4: low-power attack
  // engine 実装の log 書式: "atk: <attacker_name>(P=<atk>) -> <target_name>(P=<def>)"
  // counter 加算後は: "  counter +<n> → <target>(P=<new_def>)"
  // ここでは初期の atk: 行のみを判定 (= 攻撃宣言時点のパワー比較)
  const attackMatch = log.match(/atk:.+?\(P=(\d+)\)\s*->.+?\(P=(\d+)\)/);
  if (attackMatch) {
    const atkP = Number(attackMatch[1]);
    const tgtP = Number(attackMatch[2]);
    if (atkP < tgtP) {
      badges.push({
        label: "low-power attack",
        tone: "danger",
        title: `attacker power (${atkP}) < target power (${tgtP})。 カウンター無しでは KO 不可、 DON 不足なら空振り。`,
      });
    } else if (atkP === tgtP) {
      badges.push({
        label: "equal power",
        tone: "info",
        title: `attacker = target power (${atkP})。 カウンター 1 枚で防がれる可能性大。`,
      });
    }
  }

  return badges;
}

// ============================================================================
// コメント編集モーダル
// ============================================================================

export function LogCommentModal({
  snapIdx,
  snap,
  existing,
  nickname,
  onSave,
  onDelete,
  onToggleAgree,
  onClose,
}: {
  snapIdx: number;
  snap: StateSnapshot;
  existing: LogComment[];
  nickname: string;
  onSave: (text: string) => void;
  onDelete: (commentIdx: number) => void;
  onToggleAgree: (commentIdx: number) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (text.trim()) {
      onSave(text);
      setText("");
    }
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-lg bg-zinc-900 p-4 text-sm text-zinc-100 shadow-2xl ring-1 ring-zinc-700"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-wide text-zinc-400">
              コメント — step {snapIdx + 1} (T{snap.turn})
            </div>
            <div className="mt-0.5 font-mono text-[11px] text-amber-200/80">
              {snap.log || "(empty log)"}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
            aria-label="閉じる"
          >
            ✕
          </button>
        </div>

        {existing.length > 0 ? (
          <ul className="mb-3 max-h-40 space-y-1 overflow-y-auto rounded border border-zinc-800 bg-zinc-950 p-2 text-[12px]">
            {existing.map((c, i) => (
              <li
                key={i}
                className="flex items-start justify-between gap-2 border-b border-zinc-800/60 pb-1 last:border-b-0 last:pb-0"
              >
                <div className="flex-1">
                  <div className="whitespace-pre-wrap break-words text-zinc-100">
                    {c.text}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-zinc-500">
                    <span>{new Date(c.created_at).toLocaleString()}</span>
                    {c.author ? (
                      <span className="rounded bg-zinc-800 px-1 text-zinc-300">
                        by {c.author}
                      </span>
                    ) : (
                      <span className="text-zinc-600">(anonymous)</span>
                    )}
                    {c.agreed_by.length > 0 ? (
                      <span
                        title={`同意: ${c.agreed_by.join(", ")}`}
                        className="rounded bg-amber-900/60 px-1 text-amber-200"
                      >
                        👍 {c.agreed_by.length}
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-0.5">
                  <button
                    type="button"
                    onClick={() => onToggleAgree(i)}
                    disabled={!nickname}
                    title={
                      nickname
                        ? c.agreed_by.includes(nickname)
                          ? "同意を取り消す"
                          : `「${nickname}」 で同意`
                        : "nickname 未設定 (= 右上で設定)"
                    }
                    className={`rounded px-1.5 py-0.5 text-[10px] transition ${
                      nickname && c.agreed_by.includes(nickname)
                        ? "bg-amber-500 text-amber-950"
                        : nickname
                          ? "border border-amber-200/40 text-amber-200 hover:bg-amber-900/40"
                          : "border border-zinc-700 text-zinc-600 cursor-not-allowed"
                    }`}
                  >
                    👍 同意
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(i)}
                    className="rounded px-1.5 py-0.5 text-[10px] text-rose-300 hover:bg-rose-950 hover:text-rose-100"
                    title="削除"
                  >
                    削除
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : null}

        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="自由記述コメント (Ctrl+Enter で保存)"
            rows={3}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                handleSubmit(e);
              }
            }}
            className="w-full rounded border border-zinc-700 bg-zinc-950 p-2 font-sans text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-amber-500 focus:outline-none"
          />
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-800"
            >
              閉じる
            </button>
            <button
              type="submit"
              disabled={!text.trim()}
              className="rounded bg-amber-500 px-3 py-1 text-xs font-medium text-amber-950 hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              追加
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ============================================================================
// バッジ表示子コンポーネント
// ============================================================================

export function BadgeRow({ badges }: { badges: LogBadge[] }) {
  if (badges.length === 0) return null;
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {badges.map((b, i) => (
        <span
          key={i}
          title={b.title}
          className={`inline-block rounded px-1 py-0 text-[9px] font-medium ${
            b.tone === "warn"
              ? "bg-amber-300/90 text-amber-950"
              : b.tone === "danger"
                ? "bg-rose-400/90 text-rose-950"
                : "bg-sky-300/80 text-sky-950"
          }`}
        >
          {b.tone === "warn" ? "⚠ " : b.tone === "danger" ? "✕ " : "ⓘ "}
          {b.label}
        </span>
      ))}
    </span>
  );
}

// ============================================================================
// NicknameInput (= 友達共有時の自分の名前入力)
// ============================================================================

export function NicknameInput({
  nickname,
  onChange,
}: {
  nickname: string;
  onChange: (n: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(nickname);
  useEffect(() => {
    setDraft(nickname);
  }, [nickname]);

  function commit() {
    onChange(draft);
    setEditing(false);
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="rounded border border-amber-200/40 px-2 py-0.5 text-[11px] text-amber-100/80 hover:bg-amber-900/30"
        title="クリックで nickname を変更"
      >
        {nickname ? `👤 ${nickname}` : "👤 nickname を設定"}
      </button>
    );
  }
  return (
    <span className="flex items-center gap-1">
      <input
        type="text"
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          else if (e.key === "Escape") {
            setDraft(nickname);
            setEditing(false);
          }
        }}
        onBlur={commit}
        placeholder="nickname"
        maxLength={32}
        className="w-32 rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-950 placeholder:text-amber-700/60 focus:outline-none"
      />
    </span>
  );
}
