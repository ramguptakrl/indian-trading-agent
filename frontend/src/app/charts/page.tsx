"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { getChartData } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { HelpSection } from "@/components/HelpSection";
import { chartsHelp } from "@/lib/help-content";
import { Database, RefreshCw } from "lucide-react";

const BSE_TICKER = "BSE";

const views = [
  { label: "5D · 5m", period: "5d", interval: "5m" },
  { label: "1M · Daily", period: "1mo", interval: "1d" },
  { label: "3M · Daily", period: "3mo", interval: "1d" },
  { label: "6M · Daily", period: "6mo", interval: "1d" },
  { label: "1Y · Daily", period: "1y", interval: "1d" },
  { label: "2Y · Daily", period: "2y", interval: "1d" },
];

export default function ChartsPage() {
  const [viewIndex, setViewIndex] = useState(2);
  const [data, setData] = useState<any[]>([]);
  const [meta, setMeta] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<any>(null);
  const disposed = useRef(false);
  const view = views[viewIndex];

  const loadChart = useCallback(async () => {
    setLoading(true);
    try {
      const result: any = await getChartData(BSE_TICKER, view.period, view.interval);
      setData(result.data || []);
      setMeta(result || null);
    } catch {
      setData([]);
      setMeta(null);
    } finally {
      setLoading(false);
    }
  }, [view.period, view.interval]);

  useEffect(() => {
    loadChart();
  }, [loadChart]);

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return;

    disposed.current = false;
    if (chartInstance.current) {
      try { chartInstance.current.remove(); } catch {}
      chartInstance.current = null;
    }

    let chart: any = null;

    (async () => {
      const lc = await import("lightweight-charts");
      if (disposed.current || !chartRef.current) return;

      chart = lc.createChart(chartRef.current, {
        layout: {
          background: { type: lc.ColorType.Solid, color: "transparent" },
          textColor: "#333",
        },
        grid: {
          vertLines: { color: "rgba(0,0,0,0.06)" },
          horzLines: { color: "rgba(0,0,0,0.06)" },
        },
        width: chartRef.current.clientWidth,
        height: 500,
        crosshair: { mode: 0 },
        timeScale: { borderColor: "rgba(0,0,0,0.1)" },
        rightPriceScale: { borderColor: "rgba(0,0,0,0.1)" },
      });

      if (disposed.current) {
        try { chart.remove(); } catch {}
        return;
      }

      const candleSeries = chart.addSeries(lc.CandlestickSeries, {
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderDownColor: "#ef4444",
        borderUpColor: "#22c55e",
        wickDownColor: "#ef4444",
        wickUpColor: "#22c55e",
      });

      candleSeries.setData(
        data.map((d: any) => ({
          time: d.time,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        }))
      );

      const volumeSeries = chart.addSeries(lc.HistogramSeries, {
        color: "#3b82f680",
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });

      chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      volumeSeries.setData(
        data.map((d: any) => ({
          time: d.time,
          value: d.volume,
          color: d.close >= d.open ? "#22c55e40" : "#ef444440",
        }))
      );

      chart.timeScale().fitContent();
      chartInstance.current = chart;
    })();

    const handleResize = () => {
      if (chartInstance.current && chartRef.current) {
        try { chartInstance.current.applyOptions({ width: chartRef.current.clientWidth }); } catch {}
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      disposed.current = true;
      window.removeEventListener("resize", handleResize);
      if (chartInstance.current) {
        try { chartInstance.current.remove(); } catch {}
        chartInstance.current = null;
      }
      if (chart && chart !== chartInstance.current) {
        try { chart.remove(); } catch {}
      }
    };
  }, [data]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold">BSE Price & Structure</h1>
            <Badge variant="outline">NSE:BSE</Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            Audited BSE Ltd price path. No generic ticker selection is available on this Trade Brain branch.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={loadChart} disabled={loading}>
          <RefreshCw className={`mr-1 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        {views.map((item, index) => (
          <Button
            key={item.label}
            variant={viewIndex === index ? "default" : "outline"}
            size="sm"
            onClick={() => setViewIndex(index)}
          >
            {item.label}
          </Button>
        ))}
      </div>

      <Card>
        <CardContent className="p-4">
          <div
            ref={chartRef}
            className="w-full"
            style={{ minHeight: 500, display: data.length > 0 ? "block" : "none" }}
          />
          {data.length === 0 && (
            <div className="h-[500px] flex items-center justify-center text-muted-foreground">
              {loading ? "Loading audited BSE price data..." : "No BSE chart data available for this view."}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border p-3 text-xs text-muted-foreground">
        <Database className="h-4 w-4" />
        <span>Source:</span>
        <Badge variant="outline">{meta?.price_source || "unavailable"}</Badge>
        {meta?.fallback_used && <Badge variant="outline" className="border-amber-300 text-amber-700">FALLBACK</Badge>}
        {meta?.fallback_reason && <span>{meta.fallback_reason}</span>}
      </div>

      <p className="text-xs text-muted-foreground">
        Charts powered by{" "}
        <a
          href="https://www.tradingview.com/lightweight-charts/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline hover:text-foreground"
        >
          TradingView Lightweight Charts™
        </a>
      </p>

      <HelpSection title="How to Read BSE Price Structure" items={chartsHelp} />
    </div>
  );
}
