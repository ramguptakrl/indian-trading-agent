"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getAnalysisResult } from "@/lib/api";
import { DecisionCard } from "@/components/analysis/DecisionCard";
import { ReportPanel } from "@/components/analysis/ReportPanel";
import { DebateView } from "@/components/analysis/DebateView";
import { ActualTradeDialog } from "@/components/trades/ActualTradeDialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { BriefcaseBusiness, LockKeyhole } from "lucide-react";
import type { AnalysisResult } from "@/lib/types";

function inferHorizon(result: AnalysisResult) {
  const explicit = String((result as any).requested_trade_mode || "").toUpperCase();
  if (explicit === "INTRADAY" || explicit === "SWING") return explicit;
  const task = String(result.task_id || "");
  if (task.startsWith("sw-")) return "SWING";
  if (task.startsWith("id-")) return "INTRADAY";
  return null;
}

export default function AnalysisDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [tradeDialog, setTradeDialog] = useState(false);

  useEffect(() => {
    if (params.id) {
      getAnalysisResult(params.id as string)
        .then((data: any) => setResult(data))
        .catch(() => setResult(null))
        .finally(() => setLoading(false));
    }
  }, [params.id]);

  if (loading) {
    return <div className="p-6"><p className="text-muted-foreground">Loading analysis...</p></div>;
  }

  if (!result || !result.signal) {
    return <div className="p-6"><p className="text-muted-foreground">Analysis not found or still in progress.</p></div>;
  }

  const reports: Record<string, string> = {};
  if (result.market_report) reports.market_report = result.market_report;
  if (result.sentiment_report) reports.sentiment_report = result.sentiment_report;
  if (result.news_report) reports.news_report = result.news_report;
  if (result.fundamentals_report) reports.fundamentals_report = result.fundamentals_report;
  if (result.investment_plan) reports.investment_plan = result.investment_plan;
  if (result.trader_investment_plan) reports.trader_investment_plan = result.trader_investment_plan;
  if (result.final_trade_decision) reports.final_trade_decision = result.final_trade_decision;

  const researchLabel = result.research_label || result.signal;
  const horizon = inferHorizon(result);
  const canRecordEntry = researchLabel === "LONG_CANDIDATE" || researchLabel === "SHORT_CANDIDATE";
  const exchange = result.tradebrain_advisory?.exchange === "BSE" ? "BSE" : "NSE";
  const persistedAdvisoryTaskId = result.tradebrain_advisory ? result.task_id : undefined;
  const hasDebate = Boolean(
    result.bull_history || result.bear_history || result.risk_aggressive_history ||
    result.risk_conservative_history || result.risk_neutral_history
  );

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold">BSE Analysis Result</h1>
            {horizon && <Badge variant="outline">{horizon === "SWING" ? "SWING · MTF" : "INTRADAY"}</Badge>}
            <Badge variant="outline">{result.trade_date}</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">BSE Ltd · NSE:BSE · advisory research only</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => router.push("/trades")}>
          <BriefcaseBusiness className="h-4 w-4 mr-2" /> Actual Trades
        </Button>
      </div>

      <DecisionCard
        signal={researchLabel}
        ticker={result.ticker}
        duration={result.duration_seconds}
        advisory={result.tradebrain_advisory}
      />

      {canRecordEntry && (
        <div className="rounded-lg border border-blue-200 bg-blue-50/40 p-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex gap-2 text-sm">
            <LockKeyhole className="h-4 w-4 mt-0.5 text-blue-700 shrink-0" />
            <div>
              <div className="font-medium">Only log a trade you actually executed yourself.</div>
              <div className="text-xs text-muted-foreground mt-0.5">This button records a fill; it never sends an order to Zerodha.</div>
            </div>
          </div>
          <Button size="sm" onClick={() => setTradeDialog(true)}>I TOOK THIS TRADE</Button>
        </div>
      )}

      <details className="rounded-lg border bg-muted/10">
        <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium">
          View evidence & agent reasoning
        </summary>
        <div className="border-t p-4 space-y-4">
          <div className="text-[10px] text-muted-foreground font-mono">Task: {result.task_id}</div>
          <ReportPanel reports={reports} />
          {hasDebate && (
            <DebateView
              bull={result.bull_history || ""}
              bear={result.bear_history || ""}
              riskAggressive={result.risk_aggressive_history}
              riskConservative={result.risk_conservative_history}
              riskNeutral={result.risk_neutral_history}
            />
          )}
        </div>
      </details>

      <ActualTradeDialog
        open={tradeDialog}
        onClose={() => setTradeDialog(false)}
        onSaved={() => router.push("/trades")}
        advisoryTaskId={persistedAdvisoryTaskId}
        ticker={result.ticker}
        exchange={exchange}
        researchLabel={researchLabel}
        advisory={result.tradebrain_advisory}
      />
    </div>
  );
}
