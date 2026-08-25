"use client";

import { create } from "zustand";
import type { TradeBrainAdvisory } from "@/lib/types";
import {
  connectTradeBrainHorizonWS,
  runTradeBrainHorizons,
  type TradeBrainHorizon,
} from "@/lib/tradebrain-horizon-api";

export interface HorizonAnalysisOptions {
  analysts?: string[];
  max_debate_rounds?: number;
  max_risk_discuss_rounds?: number;
  output_language?: string;
}

export interface HorizonAnalysisStats {
  llm_calls: number;
  tool_calls: number;
  tokens_in: number;
  tokens_out: number;
  total_tokens: number;
  cost_usd: number;
  cost_inr: number;
  per_model?: Record<string, { input: number; output: number }>;
}

export interface HorizonPlanState {
  mode: TradeBrainHorizon;
  taskId: string | null;
  status: "idle" | "running" | "completed" | "error";
  reports: Record<string, string>;
  debates: { bull: string; bear: string };
  riskDebates: { aggressive: string; conservative: string; neutral: string };
  signal: string | null;
  tradebrainAdvisory: TradeBrainAdvisory | null;
  error: string | null;
  duration: number | null;
  heartbeat: string;
  lastUpdateAt: number;
  stats: HorizonAnalysisStats | null;
  ws: WebSocket | null;
}

interface HorizonAnalysisState {
  pairId: string | null;
  ticker: "BSE";
  tradeDate: string;
  status: "idle" | "running" | "completed" | "error";
  error: string | null;
  plans: Record<TradeBrainHorizon, HorizonPlanState>;
  start: (tradeDate: string, options?: HorizonAnalysisOptions) => Promise<void>;
  reset: () => void;
}

function emptyPlan(mode: TradeBrainHorizon): HorizonPlanState {
  return {
    mode,
    taskId: null,
    status: "idle",
    reports: {},
    debates: { bull: "", bear: "" },
    riskDebates: { aggressive: "", conservative: "", neutral: "" },
    signal: null,
    tradebrainAdvisory: null,
    error: null,
    duration: null,
    heartbeat: "",
    lastUpdateAt: 0,
    stats: null,
    ws: null,
  };
}

function normalizeStats(event: any): HorizonAnalysisStats {
  return {
    llm_calls: event?.llm_calls || 0,
    tool_calls: event?.tool_calls || 0,
    tokens_in: event?.tokens_in || 0,
    tokens_out: event?.tokens_out || 0,
    total_tokens: event?.total_tokens || 0,
    cost_usd: event?.cost_usd || 0,
    cost_inr: event?.cost_inr || 0,
    per_model: event?.per_model,
  };
}

export const useHorizonAnalysisStore = create<HorizonAnalysisState>((set, get) => {
  const updatePlan = (
    mode: TradeBrainHorizon,
    updater: (plan: HorizonPlanState) => HorizonPlanState,
  ) => {
    set((state) => {
      const plans = { ...state.plans, [mode]: updater(state.plans[mode]) };
      const terminal = Object.values(plans).every(
        (plan) => plan.status === "completed" || plan.status === "error",
      );
      return {
        plans,
        status: state.status === "idle" ? "idle" : terminal ? "completed" : "running",
      };
    });
  };

  const attachStream = (mode: TradeBrainHorizon, taskId: string) => {
    const ws = connectTradeBrainHorizonWS(taskId, (event: any) => {
      switch (event.type) {
        case "heartbeat":
          updatePlan(mode, (plan) => ({
            ...plan,
            heartbeat: event.last_activity || `Processing chunk #${event.chunk}`,
            lastUpdateAt: Date.now(),
          }));
          break;
        case "report":
          updatePlan(mode, (plan) => ({
            ...plan,
            reports: { ...plan.reports, [event.section!]: event.content! },
            lastUpdateAt: Date.now(),
          }));
          break;
        case "debate":
          updatePlan(mode, (plan) => ({
            ...plan,
            debates: { ...plan.debates, [event.side!]: event.content! },
            lastUpdateAt: Date.now(),
          }));
          break;
        case "risk_debate":
          updatePlan(mode, (plan) => ({
            ...plan,
            riskDebates: { ...plan.riskDebates, [event.side!]: event.content! },
            lastUpdateAt: Date.now(),
          }));
          break;
        case "signal":
          updatePlan(mode, (plan) => ({
            ...plan,
            signal: event.research_label || event.decision || "NO_TRADE",
            tradebrainAdvisory: event.tradebrain_advisory || null,
            lastUpdateAt: Date.now(),
          }));
          break;
        case "stats":
          updatePlan(mode, (plan) => ({
            ...plan,
            stats: normalizeStats(event),
            lastUpdateAt: Date.now(),
          }));
          break;
        case "complete":
          try { ws.close(); } catch {}
          updatePlan(mode, (plan) => ({
            ...plan,
            status: "completed",
            duration: event.duration_seconds ?? null,
            heartbeat: "Complete",
            lastUpdateAt: Date.now(),
            stats: event.stats ? normalizeStats(event.stats) : plan.stats,
            ws: null,
          }));
          break;
        case "error":
          try { ws.close(); } catch {}
          updatePlan(mode, (plan) => ({
            ...plan,
            status: "error",
            error: event.message ?? "Unknown analysis error",
            heartbeat: "Stopped",
            lastUpdateAt: Date.now(),
            ws: null,
          }));
          break;
      }
    });

    updatePlan(mode, (plan) => ({ ...plan, taskId, status: "running", ws }));
  };

  return {
    pairId: null,
    ticker: "BSE",
    tradeDate: "",
    status: "idle",
    error: null,
    plans: {
      INTRADAY: emptyPlan("INTRADAY"),
      SWING: emptyPlan("SWING"),
    },

    start: async (tradeDate: string, options: HorizonAnalysisOptions = {}) => {
      Object.values(get().plans).forEach((plan) => {
        if (plan.ws) {
          try { plan.ws.close(); } catch {}
        }
      });

      set({
        pairId: null,
        ticker: "BSE",
        tradeDate,
        status: "running",
        error: null,
        plans: {
          INTRADAY: { ...emptyPlan("INTRADAY"), status: "running", heartbeat: "Initializing independent INTRADAY pipeline..." },
          SWING: { ...emptyPlan("SWING"), status: "running", heartbeat: "Initializing independent SWING · MTF pipeline..." },
        },
      });

      try {
        const result = await runTradeBrainHorizons({
          ticker: "BSE",
          trade_date: tradeDate,
          analysts: options.analysts,
          max_debate_rounds: options.max_debate_rounds,
          max_risk_discuss_rounds: options.max_risk_discuss_rounds,
          output_language: options.output_language,
        });

        set({ pairId: result.pair_id });
        attachStream("INTRADAY", result.tasks.INTRADAY);
        attachStream("SWING", result.tasks.SWING);
      } catch (error: any) {
        set({
          status: "error",
          error: error?.message || "Unable to start independent horizon analysis.",
          plans: {
            INTRADAY: { ...emptyPlan("INTRADAY"), status: "error", error: error?.message || "Start failed" },
            SWING: { ...emptyPlan("SWING"), status: "error", error: error?.message || "Start failed" },
          },
        });
      }
    },

    reset: () => {
      Object.values(get().plans).forEach((plan) => {
        if (plan.ws) {
          try { plan.ws.close(); } catch {}
        }
      });
      set({
        pairId: null,
        ticker: "BSE",
        tradeDate: "",
        status: "idle",
        error: null,
        plans: {
          INTRADAY: emptyPlan("INTRADAY"),
          SWING: emptyPlan("SWING"),
        },
      });
    },
  };
});
