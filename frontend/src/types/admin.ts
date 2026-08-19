/**
 * frontend/src/types/admin.ts — Centralized TypeScript interfaces for Admin Telemetry & Observability.
 */

export interface OverviewData {
  time_range_hours: number
  total_requests: number
  total_tokens: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_cost_usd: number
  total_cost_vnd: number
  avg_latency_ms: number
  p50_latency_ms: number
  p95_latency_ms: number
  avg_ttft_ms: number
  p50_ttft_ms: number
  p95_ttft_ms: number
  cache_hits: number
  cache_hit_rate_pct: number
  total_errors: number
  error_rate_pct: number
}

export interface TimeseriesPoint {
  timestamp: string
  requests: number
  avg_latency_ms: number
  avg_ttft_ms: number
  total_tokens: number
  cost_usd: number
  cost_vnd: number
  cache_hits: number
}

export interface IntentPoint {
  intent: string
  count: number
  avg_latency_ms: number
  total_tokens: number
  total_cost_vnd: number
}

export interface TopIP {
  client_ip: string
  total_requests: number
  blocked_429: number
  error_requests: number
  total_cost_vnd: number
  last_request: string
}

export interface SessionItem {
  session_id: string
  total_turns: number
  total_tokens: number
  total_cost_vnd: number
  total_cost_usd: number
  first_seen: string
  last_seen: string
  client_ip: string
}

export interface LogItem {
  id: number
  request_id: string
  session_id: string | null
  client_ip: string
  created_at: string
  query_text: string
  intent: string
  decision: string
  model_used: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  cost_vnd: number
  ttft_ms: number
  total_latency_ms: number
  cache_hit: boolean
  cache_type: string
  status_code: number
  error_message: string | null
}

export interface AlertItem {
  id: number
  alert_type: string
  severity: string
  title: string
  message: string
  details: Record<string, unknown>
  email_sent: boolean
  created_at: string
}
