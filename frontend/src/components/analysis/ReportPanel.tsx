"use client";

import { useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import ReactMarkdown from "react-markdown";

interface Props {
  reports: Record<string, string>;
}

const reportTabs = [
  { key: "market_report", label: "Market" },
  { key: "sentiment_report", label: "Social" },
  { key: "news_report", label: "News" },
  { key: "fundamentals_report", label: "Fundamentals" },
  { key: "investment_plan", label: "Research Manager" },
  { key: "trader_investment_plan", label: "Trader" },
  { key: "final_trade_decision", label: "Final Decision" },
];

export function ReportPanel({ reports }: Props) {
  const availableTabs = reportTabs.filter((t) => reports[t.key]);
  const latestTab = availableTabs[availableTabs.length - 1]?.key || "";
  const [value, setValue] = useState(latestTab);

  useEffect(() => {
    if (!value || !availableTabs.some((t) => t.key === value)) {
      setValue(latestTab);
    } else if (latestTab && latestTab !== value) {
      setValue(latestTab);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestTab]);

  if (availableTabs.length === 0) {
    return (
      <Card className="h-40 flex items-center justify-center">
        <p className="text-sm text-muted-foreground">No report is available yet.</p>
      </Card>
    );
  }

  return (
    <Tabs value={value || latestTab} onValueChange={setValue}>
      <TabsList className="w-full flex-wrap h-auto gap-1 bg-muted/50 p-1">
        {availableTabs.map((tab) => (
          <TabsTrigger key={tab.key} value={tab.key} className="text-xs">
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {availableTabs.map((tab) => (
        <TabsContent key={tab.key} value={tab.key}>
          <Card>
            <CardContent className="p-4">
              <ScrollArea className="h-[280px]">
                <div className="prose prose-sm dark:prose-invert max-w-none pr-3">
                  <ReactMarkdown>{reports[tab.key] || ""}</ReactMarkdown>
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>
      ))}
    </Tabs>
  );
}
