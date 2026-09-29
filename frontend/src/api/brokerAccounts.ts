import { apiRequest } from "./client";

/** Fee profile (builtin Sber or user custom BUY%/SELL%). */
export interface FeeProfile {
  id: number;
  code: string;
  name: string;
  broker_code: string;
  broker_name: string;
  tariff_name: string;
  version: number;
  valid_from?: string | null;
  valid_to?: string | null;
  source_url?: string | null;
  source_note?: string | null;
  is_builtin: boolean;
  read_only: boolean;
  buy_rate_pct?: string | null;
  sell_rate_pct?: string | null;
  rules?: Array<{
    id: number;
    code: string | null;
    side: string | null;
    percentage_rate: string | null;
    instrument_symbol?: string | null;
    explanation?: string | null;
    active: boolean;
  }>;
}

export interface BrokerAccount {
  id: number;
  name: string;
  broker_code: string;
  broker_name: string;
  tariff_name?: string | null;
  fee_profile_id: number;
  base_currency: string;
  active: boolean;
  note?: string | null;
  fee_profile?: FeeProfile;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FeeEstimateResult {
  status: "KNOWN" | "UNKNOWN" | string;
  amount: string | null;
  fee_rule_id: number | null;
  explanation: string;
  commission_source: "NONE" | "MANUAL" | "PROFILE_ESTIMATE" | string;
  broker_account_id: number | null;
  limitation?: string | null;
  matched_rule_code?: string | null;
  exclude_from_turnover?: boolean;
}

export function listFeeProfiles(opts?: { includeRules?: boolean; signal?: AbortSignal }) {
  const q = opts?.includeRules === false ? "?include_rules=false" : "";
  return apiRequest<{ items: FeeProfile[]; count: number }>(`/fee-profiles${q}`, {
    signal: opts?.signal,
  });
}

export function createFeeProfile(
  body: {
    name: string;
    broker_name: string;
    tariff_name?: string;
    broker_code?: string;
    buy_rate_pct: string | number;
    sell_rate_pct: string | number;
  },
  opts?: { signal?: AbortSignal },
) {
  return apiRequest<FeeProfile>("/fee-profiles", {
    method: "POST",
    body,
    signal: opts?.signal,
  });
}

export function patchFeeProfile(
  profileId: number,
  body: {
    name?: string;
    broker_name?: string;
    tariff_name?: string;
    buy_rate_pct?: string | number;
    sell_rate_pct?: string | number;
  },
  opts?: { signal?: AbortSignal },
) {
  return apiRequest<FeeProfile>(`/fee-profiles/${profileId}`, {
    method: "PATCH",
    body,
    signal: opts?.signal,
  });
}

export function listBrokerAccounts(opts?: { activeOnly?: boolean; signal?: AbortSignal }) {
  const q = opts?.activeOnly === false ? "?active_only=false" : "";
  return apiRequest<{ items: BrokerAccount[]; count: number }>(`/broker-accounts${q}`, {
    signal: opts?.signal,
  });
}

export function createBrokerAccount(
  body: { name: string; fee_profile_id: number; note?: string },
  opts?: { signal?: AbortSignal },
) {
  return apiRequest<BrokerAccount>("/broker-accounts", {
    method: "POST",
    body,
    signal: opts?.signal,
  });
}

export function patchBrokerAccount(
  accountId: number,
  body: {
    name?: string;
    fee_profile_id?: number;
    note?: string | null;
    active?: boolean;
  },
  opts?: { signal?: AbortSignal },
) {
  return apiRequest<BrokerAccount>(`/broker-accounts/${accountId}`, {
    method: "PATCH",
    body,
    signal: opts?.signal,
  });
}
