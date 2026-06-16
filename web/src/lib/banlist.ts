import type { Banlist } from "./types";

export type BanKind = "forbidden" | "restricted" | "pair";

export type BanInfo = {
  kind: BanKind;
  // pair の場合の 相方カード名 (= 複数ペアに属する場合は連結)
  partners?: string[];
};

/**
 * card_id → BanInfo の lookup を作る。 強さは forbidden > restricted > pair。
 * forbidden/restricted は単体で禁止/制限、 pair は 相方との同時採用のみ不可。
 */
export function buildBanStatus(banlist: Banlist | null): Record<string, BanInfo> {
  const out: Record<string, BanInfo> = {};
  if (!banlist) return out;
  for (const c of banlist.restricted ?? []) {
    out[c.card_id] = { kind: "restricted" };
  }
  // forbidden は restricted を上書き (= より強い制限)
  for (const c of banlist.forbidden ?? []) {
    out[c.card_id] = { kind: "forbidden" };
  }
  // pair は forbidden/restricted が無いカードにのみ付ける
  for (const p of banlist.forbidden_pairs ?? []) {
    addPair(out, p.a, p.b);
    addPair(out, p.b, p.a);
  }
  return out;
}

function addPair(
  out: Record<string, BanInfo>,
  card: { card_id: string; name: string },
  partner: { card_id: string; name: string },
) {
  const existing = out[card.card_id];
  if (existing && existing.kind !== "pair") return; // forbidden/restricted 優先
  if (existing && existing.kind === "pair") {
    if (!existing.partners?.includes(partner.name)) {
      existing.partners = [...(existing.partners ?? []), partner.name];
    }
    return;
  }
  out[card.card_id] = { kind: "pair", partners: [partner.name] };
}
