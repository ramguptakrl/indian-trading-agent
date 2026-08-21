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
  const canRecordEntry = researchLabel === "LONG_CANDIDATE" || researchLabel === "SHORT_CANDIDATE";
  const exchange = result.tradebrain_advisory?.exchange === "BSE" ? "BSE" : "NSE";
  const persistedAdvisoryTaskId = result.tradebrain_advisory ? result.task_id : undefined;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{result.ticker} Analysis</h1>
          <p className="text-sm text-muted-foreground">
            Date: {result.trade_date} | Task: {result.task_id} | Advisory research only
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => router.push("/trades")}>
            <BriefcaseBusiness className="h-4 w-4 mr-2" /> Actual Trades
          </Button>
          {canRecordEntry && (
            <Button onClick={() => setTradeDialog(true)}>
              <BriefcaseBusiness className="h-4 w-4 mr-2" /> I TOOK THIS TRADE
            </Button>
          )}
        </div>
      </div>

      <DecisionCard
        signal={researchLabel}
        ticker={result.ticker}
        duration={result.duration_seconds}
        advisory={result.tradebrain_advisory}
      />

      {canRecordEntry && (
        <div className="rounded-lg border border-blue-200 bg-blue-50/40 p-3 flex items-start justify-between gap-4">
          <div className="flex gap-2 text-sm">
            <LockKeyhole className="h-4 w-4 mt-0.5 text-blue-700 flex-shrink-0" />
            <div>
              <div className="font-medium">Did you execute this yourself?</div>
              <div className="text-xs text-muted-foreground mt-0.5">
                Record your actual fill so Trade Brain can track the real position separately from replay/paper evidence. This does not send an order to Zerodha.
              </div>
            </div>
          </div>
          <Badge variant="outline" className="whitespace-nowrap">ACTUAL_MANUAL_TRADE</Badge>
        </div>
      )}

      <ReportPanel reports={reports} />

      <DebateView
        bull={result.bull_history || ""}
        bear={result.bear_history || ""}
        riskAggressive={result.risk_aggressive_history}
        riskConservative={result.risk_conservative_history}
        riskNeutral={result.risk_neutral_history}
      />

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
