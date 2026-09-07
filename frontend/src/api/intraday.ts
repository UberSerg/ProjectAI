/** Intraday market status (ephemeral quotes; no candle writes). */

import { apiRequest } from "./client";

export interface IntradayLastRefresh {
  at?: string | null;
  metrics?: Record<string, unknown> | null;
}

export interface IntradayMarketStatus {
  enabled: boolean;
  refresh_minutes: number;
  cache_ttl_seconds: number;
  http_timeout_seconds: number;
  persistence: string;
  writes_market_candles: boolean;
  policy: string;
  last_refresh?: IntradayLastRefresh | null;
  operations?: {
    beat_registered_when_enabled?: boolean;
    task_name?: string;
    lock_key?: string;
  };
}

export function getIntradayStatus(signal?: AbortSignal): Promise<IntradayMarketStatus> {
  return apiRequest("/market/intraday/status", { signal });
}
