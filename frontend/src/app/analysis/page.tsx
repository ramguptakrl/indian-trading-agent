"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useAnalysisStore } from "@/lib/store";
import { getIndiaMarketDate } from "@/lib/market-time";
import { DecisionCard } from "@/components/analysis/DecisionCard";
import { AgentProgress } from "@/components/analysis/AgentProgress";
import { ReportPanel } from "@/components/analysis/ReportPanel";
import { DebateView } from "@/components/analysis/DebateView";
import { AnalysisOptions } from "@/components/analysis/AnalysisOptions";
import { StatsCard } from "@/components/analysis/StatsCard";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TickerSearch } from "@/components/TickerSearch";
import { HelpSection } from "@/components/HelpSection";
import { analysisHelp } from "@/lib/help-content";
import { Loader2, Play, RotateCcw, History, Calculator } from "lucide-react";
import { NextStep } from "@/components/NextStep";
import { PositionSizeCalculator } from "@/components/PositionSizeCalculator";

export default function AnalysisPage() {
  return (
    <Suspense fallback={<div className="p-6"><p className="text-muted-foreground">Loading...</p></div>}>
      <AnalysisPageInner />
    </Suspense>
  );
}

function AnalysisPageInner() {
  const searchParams = useSearchParams();
  const defaultTicker = searchParams.get("ticker") || "";
  const analysis = useAnalysisStore();

  const [tickerInput, setTickerInput] = useState(defaultTicker || analysis.ticker || "");
  const [tradeDateInput, setTradeDateInput] = useState(analysis.tradeDate || "");
  const [indiaToday, setIndiaToday] = useState("");
  const [selectedAnalysts, setSelectedAnalysts] = useState<string[]>([
    "market", "social", "news", "fundamentals",
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
    if (!tickerInput.trim() || !tradeDateInput) return;
    analysis.start(tickerInput.trim(), tradeDateInput, {
      analysts: selectedAnalysts,
      max_debate_rounds: depth,
      max_risk_discuss_rounds: depth,
      output_language: language,
    });
  };

  const displayTicker = analysis.ticker || tickerInput;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Run Analysis</h1>
          <p className="text-sm text-muted-foreground">
            Multi-agent research feeding the deterministic Trade Brain advisory gate
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

      <Card className="overflow-visible">
        <CardContent className="p-4 overflow-visible">
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <label className="text-xs text-muted-foreground mb-1 block">Ticker Symbol</label>
              <TickerSearch
                value={tickerInput}
                onChange={setTickerInput}
                placeholder="Search stock (e.g., Infosys, RELIANCE)"
                disabled={analysis.status === "running"}
              />
            </div>
            <div className="w-52">
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
                  Defaults to India market date: {indiaToday}
                </p>
              )}
            </div>
            <Button
              onClick={handleRun}
              disabled={analysis.status === "running" || !tickerInput.trim() || !tradeDateInput}
              className="h-10"
            >
              {analysis.status === "running" ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Analyzing...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-2" />
                  Run Analysis
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
          <CardContent className="p-4 text-red-400">{analysis.error}</CardContent>
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
          ticker={displayTicker}
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
          title="Review or log the outcome"
          description="This analysis is advisory research, not an order. If you independently act on a candidate, you can later log the observed outcome for research and learning."
          href="/history"
          buttonText="Analysis History"
          icon={History}
        />
      )}

      <HelpSection title="How to Use Analysis" items={analysisHelp} />

      <PositionSizeCalculator
        open={calcOpen}
        onClose={() => setCalcOpen(false)}
        ticker={displayTicker}
      />
    </div>
  );
}
