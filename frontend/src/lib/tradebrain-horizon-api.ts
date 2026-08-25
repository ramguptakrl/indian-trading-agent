const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type TradeBrainHorizon = "INTRADAY" | "SWING";

export interface HorizonRunRequest {
  ticker: "BSE";
  trade_date: string;
  analysts?: string[];
  max_debate_rounds?: number;
  max_risk_discuss_rounds?: number;
  output_language?: string;
}

export interface HorizonRunResponse {
  pair_id: string;
  ticker: "BSE";
  trade_date: string;
  tasks: Record<TradeBrainHorizon, string>;
  independent_graph_runs: true;
  shared_final_decision: false;
  horizon_substitution_allowed: false;
  swing_funding: "ZERODHA_MTF_ONLY";
  advisory_only: true;
  trade_authorization: false;
  order_execution_allowed: false;
}

export async function runTradeBrainHorizons(data: HorizonRunRequest): Promise<HorizonRunResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/analysis/run-horizons`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  } catch {
    throw new Error(`Cannot connect to Trade Brain backend at ${API_BASE}. Is it running?`);
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload?.detail) detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
    } catch {}
    throw new Error(`Horizon analysis API error: ${detail}`);
  }

  return response.json();
}

export function connectTradeBrainHorizonWS(taskId: string, onEvent: (event: any) => void): WebSocket {
  const wsBase = API_BASE.replace("http", "ws");
  const ws = new WebSocket(`${wsBase}/api/analysis/ws/${encodeURIComponent(taskId)}`);
  ws.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data));
    } catch {}
  };
  ws.onerror = () => {
    onEvent({ type: "error", message: "Analysis WebSocket connection failed." });
  };
  return ws;
}
