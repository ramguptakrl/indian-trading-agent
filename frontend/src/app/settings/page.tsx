"use client";

import { useEffect, useState } from "react";
import { getConfig } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LLMSettings } from "@/components/settings/LLMSettings";

export default function SettingsPage() {
  const [config, setConfig] = useState<Record<string, any> | null>(null);

  useEffect(() => {
    getConfig().then((data: any) => setConfig(data)).catch(() => {});
  }, []);

  if (!config) {
    return <div className="p-6"><p className="text-muted-foreground">Loading settings...</p></div>;
  }

  const sections = [
    {
      title: "Active AI",
      items: [
        { label: "Provider", value: config.llm_provider, badge: true },
        { label: "Deep model", value: config.deep_think_llm },
        { label: "Quick model", value: config.quick_think_llm },
      ],
    },
    {
      title: "Trade Brain scope",
      items: [
        { label: "Market", value: config.market, badge: true },
        { label: "Exchange", value: config.default_exchange },
        { label: "Target", value: "BSE Ltd · NSE:BSE" },
        { label: "Execution", value: "Advisory only", badge: true },
      ],
    },
  ];

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Configure AI providers locally. API keys are masked and are never displayed back in full.
        </p>
      </div>

      <LLMSettings />

      <Card className="border-blue-200 bg-blue-50/40">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Recommended development setup</CardTitle>
        </CardHeader>
        <CardContent className="text-sm space-y-2">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="rounded-lg border bg-background p-3">
              <div className="text-xs text-muted-foreground">Primary · quick</div>
              <div className="font-semibold font-mono text-xs mt-1">gpt-5.6-luna</div>
              <div className="text-[11px] text-muted-foreground mt-1">Analysts + routine debate work</div>
            </div>
            <div className="rounded-lg border bg-background p-3">
              <div className="text-xs text-muted-foreground">Primary · deep</div>
              <div className="font-semibold font-mono text-xs mt-1">gpt-5.6-terra</div>
              <div className="text-[11px] text-muted-foreground mt-1">Research manager + decision synthesis</div>
            </div>
            <div className="rounded-lg border bg-background p-3">
              <div className="text-xs text-muted-foreground">Independent backup</div>
              <div className="font-semibold font-mono text-xs mt-1">gemini-3.6-flash</div>
              <div className="text-[11px] text-muted-foreground mt-1">Capacity fallback + material verifier</div>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            OpenAI only becomes active after its key is saved/tested and you click <strong>Set as default</strong>.
            A configured Gemini key remains available for retryable provider-capacity fallback; no AI provider can authorize or execute an order.
          </p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {sections.map((section) => (
          <Card key={section.title}>
            <CardHeader className="pb-3">
              <CardTitle className="text-lg">{section.title}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {section.items.map((item) => (
                <div key={item.label} className="flex items-center justify-between gap-4">
                  <span className="text-sm text-muted-foreground">{item.label}</span>
                  {item.badge ? (
                    <Badge variant="outline">{String(item.value)}</Badge>
                  ) : (
                    <span className="text-sm font-medium text-right">{String(item.value)}</span>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>

      <p className="text-[11px] text-muted-foreground">
        Model pricing and provider limits change over time, so Trade Brain does not hard-code guessed per-analysis rupee costs on this screen. Actual completed-run usage is recorded in diagnostics.
      </p>
    </div>
  );
}
