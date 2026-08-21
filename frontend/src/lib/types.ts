export interface Quote {
  ticker: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  volume: number;
  high: number;
  low: number;
  open: number;
  prev_close: number;
  market_cap?: number;
  pe_ratio?: number;
  fifty_two_week_high?: number;
  fifty_two_week_low?: number;
}

export interface ChartDataPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MarketStatus {
  session: string;
  is_trading_day: boolean;
  nifty: { price: number; change: number; change_percent: number };
  banknifty: { price: number; change: number; change_percent: number };
}

export interface WatchlistItem {
  ticker: string;
  symbol: string;
  exchange: string;
  name: string;
  price: number | null;
  change: number | null;
  change_percent: number | null;
  added_at: string;
}

export interface AnalysisRequest {
  ticker: string;
  trade_date: string;
  analysts: string[];
  max_debate_rounds: number;
  max_risk_discuss_rounds: number;
}

export interface TradeBrainAdvisory {
  tradebrain_version?: string;
  ticker?: string;
  exchange?: string;
  final_status?: string;
  reason?: string;
  advisory_only?: boolean;
  trade_authorization?: boolean;
  order_execution_allowed?: boolean;
  requires_phase10_final_gate_for_live_use?: boolean;
  ai_candidate?: Record<string, unknown>;
  calendar?: {
    calendar_verified?: boolean;
    session_type?: string;
    reason?: string;
    timing_verified?: boolean;
    is_trading_session?: boolean;
  } | null;
  gate?: {
    action?: string;
    hard_rule_failures?: string[];
    warnings?: string[];
    soft_parameter_registry_applied?: boolean;
    soft_parameter_source?: string;
    soft_parameter_version?: number | null;
  } | null;
  costs?: {
    status?: string;
    total_charges_rupees?: number;
    net_reward_rupees?: number;
    net_risk_rupees?: number;
  } | null;
}

export interface AnalysisResult {
  task_id: string;
  ticker: string;
  trade_date: string;
  signal: string;
  research_label?: string;
  trade_authorization?: boolean;
  order_execution_allowed?: boolean;
  requires_tradebrain_gate?: boolean;
  tradebrain_advisory?: TradeBrainAdvisory | null;
  market_report?: string;
  sentiment_report?: string;
  news_report?: string;
  fundamentals_report?: string;
  investment_plan?: string;
  trader_investment_plan?: string;
  final_trade_decision?: string;
  bull_history?: string;
  bear_history?: string;
  risk_aggressive_history?: string;
  risk_conservative_history?: string;
  risk_neutral_history?: string;
  stats?: Record<string, number>;
  duration_seconds?: number;
  created_at?: string;
}

export interface AnalysisHistoryItem {
  task_id: string;
  ticker: string;
  trade_date: string;
  signal: string;
  duration_seconds: number;
  entry_price?: number;
  exit_price?: number;
  pnl_pct?: number;
  pnl_status?: string;
  created_at: string;
}

export interface ActualTradeExit {
  exit_id: string;
  trade_id: string;
  quantity: number;
  exit_price: number;
  exit_timestamp: string;
  gross_pnl: number;
  estimated_charges: number;
  actual_charges_override?: number | null;
  charges_used: number;
  net_pnl: number;
  broker_order_ref?: string | null;
  notes?: string | null;
}

export interface ActualTrade {
  trade_id: string;
  advisory_task_id?: string | null;
  ticker: string;
  exchange: "NSE" | "BSE";
  mode: "INTRADAY" | "SWING";
  direction: "LONG" | "SHORT";
  original_quantity: number;
  open_quantity: number;
  avg_entry_price: number;
  entry_timestamp: string;
  stop_loss?: number | null;
  take_profit?: number | null;
  broker_order_ref?: string | null;
  status: "OPEN" | "PARTIALLY_CLOSED" | "CLOSED";
  advisory_alignment: string;
  entry_policy_violation: boolean;
  violation_reasons: string[];
  realized_gross_pnl: number;
  estimated_or_actual_charges: number;
  realized_net_pnl: number;
  notes?: string | null;
  observation_kind: "ACTUAL_MANUAL_TRADE";
  manual_tracking_only: boolean;
  order_execution_enabled: false;
  exits?: ActualTradeExit[];
}

export interface ActualTradeMark {
  trade_id: string;
  status: string;
  ticker?: string;
  mode?: string;
  direction?: string;
  current_price: number;
  source: string;
  open_quantity: number;
  unrealized_gross_pnl: number;
  estimated_open_charges_if_closed_now?: number;
  estimated_open_net_pnl_if_closed_now: number;
  realized_net_pnl: number;
  combined_realized_plus_estimated_open_net_pnl: number;
  charges_estimated?: boolean;
  order_execution_allowed: false;
}

export interface BacktestTrade {
  trade_date: string;
  ticker: string;
  signal: string;
  entry_price: number;
  exit_price: number;
  pnl_pct: number;
  pnl_amount: number;
  cumulative_pnl: number;
  portfolio_value: number;
  duration_seconds: number;
}

export interface BacktestResult {
  backtest_id: string;
  ticker: string;
  initial_capital: number;
  final_portfolio_value: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  total_pnl: number;
  status: string;
  trades: BacktestTrade[];
}

export interface BacktestWSEvent {
  type: "trade" | "status" | "complete" | "error";
  message?: string;
  total_dates?: number;
  trade_date?: string;
  signal?: string;
  entry_price?: number;
  exit_price?: number;
  pnl_pct?: number;
  pnl_amount?: number;
  cumulative_pnl?: number;
  portfolio_value?: number;
  total_trades?: number;
  winning_trades?: number;
  losing_trades?: number;
  win_rate?: number;
  total_return_pct?: number;
  max_drawdown_pct?: number;
  total_pnl?: number;
}

export interface WSEvent {
  type: "report" | "debate" | "risk_debate" | "signal" | "agent_status" | "complete" | "error" | "stats" | "heartbeat";
  section?: string;
  content?: string;
  side?: string;
  agent?: string;
  status?: string;
  decision?: string;
  research_label?: string;
  ticker?: string;
  message?: string;
  duration_seconds?: number;
  llm_calls?: number;
  tool_calls?: number;
  tokens_in?: number;
  tokens_out?: number;
  total_tokens?: number;
  cost_usd?: number;
  cost_inr?: number;
  per_model?: Record<string, { input: number; output: number }>;
  trade_authorization?: boolean;
  requires_tradebrain_gate?: boolean;
  tradebrain_advisory?: TradeBrainAdvisory | null;
  chunk?: number;
  last_activity?: string;
  stats?: Record<string, number>;
}

export type Signal =
  | "LONG_CANDIDATE"
  | "SHORT_CANDIDATE"
  | "EXIT_CANDIDATE"
  | "WAIT"
  | "NO_TRADE"
  // Historical/upstream compatibility only:
  | "STRONG BUY"
  | "BUY"
  | "HOLD"
  | "SELL"
  | "SHORT"
  | "OVERWEIGHT"
  | "UNDERWEIGHT";
