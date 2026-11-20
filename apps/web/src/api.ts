export interface RecordBase { id: string; version: number; user_id: string }
export type ShoppingRequirement = 'repairability' | 'replaceable_bulb' | 'replaceable_light_module' | 'serviceable_components';
export const shoppingRequirements: Record<ShoppingRequirement, { label: string; goal: string }> = {
  repairability: { label: 'Repairability · verify the stated repair feature', goal: 'Find a repairable desk light.' },
  replaceable_bulb: { label: 'Replaceable bulb', goal: 'Find a desk light with a replaceable bulb.' },
  replaceable_light_module: { label: 'Replaceable light module', goal: 'Find a desk light with a replaceable light module.' },
  serviceable_components: { label: 'Serviceable components', goal: 'Find a desk light with serviceable components.' },
};
export interface Budget { spendable_minor: number; protected_minor: number; bills_minor: number; reservations_minor: number; available_minor: number; currency: string; formula: string }
export interface Bill extends RecordBase { name: string; amount_minor: number; previous_minor: number; due_at: string; source_id: string; provenance: string }
export interface Product extends RecordBase { name: string; category: string; description: string; price_minor: number; tax_minor: number | null; shipping_minor: number | null; stock: number; repairable: boolean; source_id: string; source_version: number; observed_at: string; provenance: string }
export interface Candidate extends Product { eligible: boolean; reasons: string[]; total_minor: number | null }
export interface Task extends RecordBase { skill: string; goal: string; urgency?: string; target_price_minor?: number | null; status: string; created_at: string; session_id: string; run_id: string; checkpoint: { recommendation?: Recommendation; candidates?: Candidate[]; budget?: Budget; checks?: { name: string; due_in_days: number; increase_minor: number }[] }; error?: string }
export interface Terms { product_name: string; quantity: number; unit_price_minor: number; tax_minor: number; shipping_minor: number; total_minor: number; currency: string; quote_version: number; source_id: string; source_version: number; expires_at: string }
export interface Proposal extends RecordBase { terms: Terms; terms_digest: string; status: string; error?: string }
export interface Action extends RecordBase { task_id: string; product_name: string; total_minor: number; quantity: number; status: string }
export interface AuditEvent extends RecordBase { kind: string; timestamp: string; details: Record<string, unknown>; provenance: string; latency_ms: number | null }
export interface TaskDetail { task: Task; proposals: Proposal[]; actions: Action[]; audit: AuditEvent[] }
export interface Integration { name: string; status: string; detail: string; verified: boolean }
export interface Dashboard { user_id: string; mode: string; budget: Budget; bills: Bill[]; tasks: Task[]; actions: Action[]; preferences: { repairable: boolean }; categories: string[]; portfolio: { total_minor: number; observed_at: string; holdings: { id: string; name: string; allocation_pct: number }[] } }
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, { method, headers: { 'Content-Type': 'application/json', 'X-Demo-User': 'demo-user' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The request could not be completed. Check the input and try again.');
  return data as T;
}
export const money = (minor: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(minor / 100);
export const label = (text: string) => text.replaceAll('_', ' ');
export function parseMoney(value: string): number {
  if (!/^\d+(\.\d{1,2})?$/.test(value)) throw new Error('Enter a positive amount with at most two decimal places.');
  const [dollars, cents = ''] = value.split('.');
  return Number(dollars) * 100 + Number(cents.padEnd(2, '0'));
}

export interface Offer { id: string; code: string | null; source_id: string; supporting_text: string; unknowns: string[]; state: string; merchant_id: string }
export interface MerchantQuote { discount_minor: number; baseline_minor: number; total_minor: number; applied_code: string | null; code_validation?: string; promotion: { source_id: string; evidence: string } | null; rejected_offers: { offer_id: string; code: string | null; source_id: string; reasons: string[] }[] }
export interface Candidate { quote: MerchantQuote }
export interface Terms { discount_minor: number; applied_code: string | null; merchant_quote: MerchantQuote }
export interface Action { cart: MerchantQuote; reservation_id: string }
export interface Bill { paid: boolean; status: string; invoice_id?: string; comparison?: { comparable: boolean; previous_minor: number | null; change_minor: number | null; change_percent_bps: number | null; reason: string }; task_id?: string }
export interface Budget { spending_cap_minor: number; remaining_cap_minor: number }
export interface NextAction { id: string; title: string; due_at: string; status: string; bill_id?: string; task_id?: string; source_id: string }
export interface Dashboard { offers: Offer[]; next_actions: NextAction[]; sample_bill: string }
export interface BillDraft { id: string; source_id: string; fields: Record<string, string | number | null>; missing_fields: string[]; status: string }

export interface Dashboard { products: Product[] }

export interface PriceObservation { id: string; observed_at: string; price_minor: number; price_basis: string; provenance: string; source_id: string }
export interface Recommendation { decision: "Buy" | "Wait" | "Skip"; reason: string; product_id?: string; total_minor?: number; basis: string; prediction: null }
export interface Candidate { price_history: PriceObservation[] }
export interface WatchItem { id: string; task_id: string; product_id: string; product_name: string; target_price_minor: number | null; urgency: string; status: string; created_at: string; last_checked_at: string | null; next_check: string; recommendation: Recommendation }
export interface Dashboard { watchlist: WatchItem[] }

export interface EvidencePassage {
  provider?: string; excerpt?: string; chunk_text?: string; source_id?: string;
  content_id?: string; kb_node_id?: string; source_version?: string | number | null;
  version_id?: string | null; provenance?: string;
}
export type VerificationState = 'supported' | 'conflict' | 'unsupported' | 'not_verifiable' | 'pending' | 'error' | 'not_required' | 'demo';
export interface ClaimVerification {
  requirement: string; feature?: string | null; claim?: string | null;
  state: VerificationState; reason: string; check_id?: string | null;
  product_id: string; product_version?: number; evidence_fingerprint?: string;
  sources?: EvidencePassage[]; checked_at?: string; provider?: string; provenance?: string;
}
export interface Candidate { evidence?: EvidencePassage[]; verification?: ClaimVerification; proposal_allowed?: boolean }
export interface Terms { verification?: ClaimVerification }
export interface Action { proposal_id?: string }
