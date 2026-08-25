"use client";

import { useEffect, useState } from "react";
import { MarketOverview } from "@/components/dashboard/MarketOverview";
import { Watchlist } from "@/components/dashboard/Watchlist";
import { RecentAnalyses } from "@/components/dashboard/RecentAnalyses";
import { TodayPicks } from "@/components/dashboard/TodayPicks";
import { WorkflowGuide } from "@/components/dashboard/WorkflowGuide";
import { QuickActions } from "@/components/dashboard/QuickActions";
import { SectorHeatmap } from "@/components/dashboard/SectorHeatmap";
import { FIIDIIBanner } from "@/components/dashboard/FIIDIIBanner";
import { CalendarBanner } from "@/components/dashboard/CalendarBanner";
import { ConcentrationWidget } from "@/components/dashboard/ConcentrationWidget";
import { DailyVerdict } from "@/components/dashboard/DailyVerdict";
import { RegimeBadge } from "@/components/dashboard/RegimeBadge";
import { getIndiaMarketDayContext, getIndiaMarketGreeting } from "@/lib/market-time";

export default function DashboardPage() {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const greeting = now ? getIndiaMarketGreeting(now) : "Trade Brain";
  const dayContext = now
    ? getIndiaMarketDayContext(now)
    : "Indian market context is calculated in Asia/Kolkata (IST).";

  return (
    <div className="p-6 space-y-5 max-w-7xl">
      {/* Greeting and market-session context are always based on IST, never host time. */}
      <div>
        <h1 className="text-2xl font-bold">{greeting}</h1>
        <p className="text-sm text-muted-foreground mt-1">{dayContext}</p>
      </div>

      {/* Market Status Bar */}
      <MarketOverview />

      {/* Market Regime Badge — shows current regime (Bull/Bear/Sideways/High-Vol)
          so traders know which conditional signal weights to expect */}
      <RegimeBadge />

      {/* === HEADLINE DECISION CARD ===
          Synthesizes all filters into one TRADE / SELECTIVE / STAND DOWN verdict */}
      <DailyVerdict />

      {/* FII/DII Flow Banner */}
      <FIIDIIBanner />

      {/* Calendar / Events Banner */}
      <CalendarBanner />

      {/* Sector Concentration Widget — auto-hides if no open positions */}
      <ConcentrationWidget />

      {/* Today's Top Picks — auto-loaded */}
      <TodayPicks universe="nifty100" />

      {/* Sector Heatmap */}
      <SectorHeatmap />

      {/* Workflow Guide */}
      <WorkflowGuide />

      {/* Watchlist + Recent Analyses side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Watchlist />
        <RecentAnalyses />
      </div>

      {/* Quick Actions */}
      <QuickActions />
    </div>
  );
}
