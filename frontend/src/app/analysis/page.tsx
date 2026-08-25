"use client";

import { useEffect, useState } from "react";
import { useAnalysisStore } from "@/lib/store";
import { getIndiaMarketDate } from "@/lib/market-time";
import { DecisionCard } from "@/components/analysis/DecisionCard";
import { AgentProgress } from "@/components/analysis/AgentProgress";
import { ReportPanel } from "@/components/analysis/ReportPanel";
import { DebateView } from "@/components/analysis/DebateView";
import { AnalysisOptions } from "@/components/analysis/AnalysisOptions";
import { StatsCard } from "@/components/analysis/StatsCard";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { HelpSection } from "@/components/HelpSection";
import { analysisHelp } from "@/lib/help-content";
import { Loader2, Play, RotateCcw, History, Calculator, Building2 } from "lucide-react";
import { NextStep } from "@/components/NextStep";
import { PositionSizeCalculator } from "@/components/PositionSizeCalculator";

const BSE_TICKER = "BSE";

export default function AnalysisPage() {
  const analysis = useAnalysisStore();
  const [tradeDateInput, setTradeDateInput] = useState(analysis.tradeDate || "");
  const [indiaToday, setIndiaToday] = useState("");
  const [selectedAnalysts, setSelectedAnalysts] = useState<string[]>([
    "market", "news", "fundamentals",
  ]);
  const [depth, setDepth] = useState(1);
  const [language, setLanguage] = useState("English");
  const [calcOpen, setCalcOpen] = useState(false);

  useEffect(() => {
    const refreshIndiaDate = () => {
      const istDate = getIndiaMarketDate();
      setIndiaToday(istDate);
      setTradeDateInput((current) => current || analysis.tradeDate || istDate);
    };

    refreshIndiaDate();
    const timer = window.setInterval(refreshIndiaDate, 60_000);
    return () => window.clearInterval(timer);
  }, [analysis.tradeDate]);

  const handleRun = () => {
    if (!tradeDateInput) return;
    analysis.start(BSE_TICKER, tradeDateInput, {
      analysts: selectedAnalysts,
      max_debate_rounds: depth,
      max_risk_discuss_rounds: depth,
      output_language: language,
    });
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold">BSE Ltd Analysis</h1>
            <Badge variant="outline">NSE:BSE</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            BSE-specific multi-agent research feeding the deterministic Trade Brain advisory gate.
            Broader market inputs are context only.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setCalcOpen(true)}>
            <Calculator className="h-3 w-3 mr-2" />
            Position Calc
          </Button>
          {analysis.status !== "idle" && (
            <Button variant="outline" size="sm" onClick={analysis.reset}>
              <RotateCcw className="h-3 w-3 mr-2" />
              New Analysis
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex gap-4 items-end">
            <div className="flex-1 rounded-lg border bg-muted/20 px-4 py-3">
              <div className="flex items-center gap-3">
                <Building2 className="h-5 w-5 text-green-600" />
                <div>
                  <p className="text-xs text-muted-foreground">Fixed Trade Brain instrument</p>
                  <p className="font-semibold">BSE Ltd · NSE:BSE</p>
                  <p className="text-[11px] text-muted-foreground">ISIN INE118H01025 · only tradable target on this branch</p>
                </div>
              </div>
            </div>

            <div className="w-56">
              <label className="text-xs text-muted-foreground mb-1 block">
                Analysis Date <span className="font-semibold text-foreground">(India / IST)</span>
              </label>
              <Input
                type="date"
                value={tradeDateInput}
                max={indiaToday || undefined}
                onChange={(e) => setTradeDateInput(e.target.value)}
                disabled={analysis.status === "running"}
              />
              {indiaToday && (
                <p className="mt-1 text-[10px] text-muted-foreground">
                  India market date: {indiaToday}
                </p>
              )}
            </div>

            <Button
              onClick={handleRun}
              disabled={analysis.status === "running" || !tradeDateInput}
              className="h-10"
            >
              {analysis.status === "running" ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Analyzing BSE...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-2" />
                  Analyze BSE
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      <AnalysisOptions
        analysts={selectedAnalysts}
        onAnalystsChange={setSelectedAnalysts}
        depth={depth}
        onDepthChange={setDepth}
        language={language}
        onLanguageChange={setLanguage}
        disabled={analysis.status === "running"}
      />

      {analysis.error && (
        <Card className="border-red-500/30 bg-red-500/5">
          <CardContent className="p-4 text-red-700">{analysis.error}</CardContent>
        </Card>
      )}

      {analysis.status === "running" && analysis.heartbeat && (
        <Card className="border-blue-200 bg-blue-50/50">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 text-sm">
              <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
              <span className="text-xs text-muted-foreground">Live:</span>
              <span className="text-blue-700 font-mono text-xs truncate flex-1">{analysis.heartbeat}</span>
              {analysis.lastUpdateAt > 0 && (
                <span className="text-xs text-muted-foreground">
                  {Math.floor((Date.now() - analysis.lastUpdateAt) / 1000)}s ago
                </span>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {analysis.signal && (
        <DecisionCard
          signal={analysis.signal}
          ticker={BSE_TICKER}
          duration={analysis.duration}
          advisory={analysis.tradebrainAdvisory}
        />
      )}

      {analysis.stats && analysis.status === "completed" && (
        <StatsCard stats={analysis.stats} duration={analysis.duration} />
      )}

      {(analysis.status === "running" || analysis.status === "completed") && (
        <div className="grid grid-cols-4 gap-6">
          <div className="col-span-1">
            <AgentProgress reports={analysis.reports} signal={analysis.signal} status={analysis.status} />
          </div>
          <div className="col-span-3 space-y-4">
            <ReportPanel reports={analysis.reports} />
            <DebateView
              bull={analysis.debates.bull}
              bear={analysis.debates.bear}
              riskAggressive={analysis.riskDebates.aggressive}
              riskConservative={analysis.riskDebates.conservative}
              riskNeutral={analysis.riskDebates.neutral}
            />
          </div>
        </div>
      )}

      {analysis.status === "completed" && analysis.signal && (
        <NextStep
          title="Review BSE evidence or log an outcome"
          description="This result is advisory research, not an order. If you independently act on it, record the real fill in Actual Trades after executing externally."
          href="/history"
          buttonText="BSE Analysis Outcomes"
          icon={History}
        />
      )}

      <HelpSection title="How BSE Analysis Works" items={analysisHelp} />

      <PositionSizeCalculator
        open={calcOpen}
        onClose={() => setCalcOpen(false)}
        ticker={BSE_TICKER}
      />
    </div>
  );
}
