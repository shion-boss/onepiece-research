import type { Banlist } from "./types";

export type BanKind = "forbidden" | "restricted" | "pair";

export type BanPartner = { name: string; card_id: string };

export type BanInfo = {
  kind: BanKind;
  // pair の場合の 相方カード (= 複数ペアに属する場合は連結)。 card_id が明記されていれば
  // 番号縛り、 空なら名前縛り。
  partners?: BanPartner[];
};

/** ペア相方の表示: card_id があれば「名前 (番号)」、 名前縛りなら「名前」。 */
export function formatBanPartner(p: BanPartner): string {
  return p.card_id ? `${p.name} (${p.card_id})` : p.name;
}

/** ペア相方の一覧を「・」区切りで整形。 */
export function formatBanPartners(partners: BanPartner[] | undefined): string {
  return (partners ?? []).map(formatBanPartner).join("・");
}

/**
 * パラレル / 別アート (= OP06-047_r1, OP06-047_p1 等) を base card_id に正規化する。
 * 禁止は印刷バリエーション横断で適用されるので suffix を除いて突合する。
 * base id ("OP06-047" / "ST10-001" / "P-114") は "_" を含まない。
 */
export function baseCardId(cardId: string): string {
  const i = cardId.indexOf("_");
  return i === -1 ? cardId : cardId.slice(0, i);
}

/** card_id (パラレル含む) から BanInfo を引く。 */
export function banInfoFor(
  banStatus: Record<string, BanInfo>,
  cardId: string,
): BanInfo | undefined {
  return banStatus[cardId] ?? banStatus[baseCardId(cardId)];
}

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
  const ref: BanPartner = { name: partner.name, card_id: partner.card_id ?? "" };
  const existing = out[card.card_id];
  if (existing && existing.kind !== "pair") return; // forbidden/restricted 優先
  if (existing && existing.kind === "pair") {
    if (!existing.partners?.some((p) => p.card_id === ref.card_id && p.name === ref.name)) {
      existing.partners = [...(existing.partners ?? []), ref];
    }
    return;
  }
  out[card.card_id] = { kind: "pair", partners: [ref] };
}
