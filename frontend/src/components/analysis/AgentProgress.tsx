"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle2, Loader2, Circle } from "lucide-react";

interface Agent {
  name: string;
  status: "pending" | "running" | "completed";
}

const sharedAgents: Agent[] = [
  { name: "Market Analyst", status: "pending" },
  { name: "Social Analyst", status: "pending" },
  { name: "News Analyst", status: "pending" },
  { name: "Fundamentals Analyst", status: "pending" },
];

const sharedAgentKey: Record<string, string> = {
  "Market Analyst": "market",
  "Social Analyst": "social",
  "News Analyst": "news",
  "Fundamentals Analyst": "fundamentals",
};

const decisionAgents: Agent[] = [
  { name: "Bull Researcher", status: "pending" },
  { name: "Bear Researcher", status: "pending" },
  { name: "Research Manager", status: "pending" },
  { name: "Trader", status: "pending" },
  { name: "Risk Debate", status: "pending" },
  { name: "Portfolio Manager", status: "pending" },
];

const defaultAgents = [...sharedAgents, ...decisionAgents];

interface Props {
  reports: Record<string, string>;
  signal: string | null;
  status: string;
  pipeline?: "full" | "shared" | "decision";
  selectedAnalysts?: string[];
}

export function AgentProgress({
  reports,
  signal: _signal,
  status,
  pipeline = "full",
  selectedAnalysts,
}: Props) {
  const visibleSharedAgents = selectedAnalysts?.length
    ? sharedAgents.filter((agent) => selectedAnalysts.includes(sharedAgentKey[agent.name]))
    : sharedAgents;
  const baseAgents = pipeline === "shared"
    ? visibleSharedAgents
    : pipeline === "decision"
      ? decisionAgents
      : defaultAgents;

  const reportMap: Record<string, string> = {
    "Market Analyst": "market_report",
    "Social Analyst": "sentiment_report",
    "News Analyst": "news_report",
    "Fundamentals Analyst": "fundamentals_report",
    "Research Manager": "investment_plan",
    "Trader": "trader_investment_plan",
    "Portfolio Manager": "final_trade_decision",
    "Bull Researcher": "bull_history",
    "Bear Researcher": "bear_history",
    "Risk Debate": "risk_aggressive_history",
  };

  const agentStatuses = baseAgents.map((agent) => {
    if (status === "completed") return "completed" as const;
    if (status !== "running") return "pending" as const;

    const reportKey = reportMap[agent.name];
    if (reportKey && reports[reportKey]) return "completed" as const;
    if (agent.name === "Risk Debate" && reports["risk_conservative_history"]) {
      return "completed" as const;
    }
    return "pending" as const;
  });

  let foundRunning = false;
  const agents = baseAgents.map((agent, i) => {
    let agentStatus: "pending" | "running" | "completed" = agentStatuses[i];
    if (status === "running" && agentStatus === "pending" && !foundRunning) {
      agentStatus = "running";
      foundRunning = true;
    }
    return { ...agent, status: agentStatus };
  });

  const statusIcon = (s: string) => {
    switch (s) {
      case "completed": return <CheckCircle2 className="h-4 w-4 text-green-400" />;
      case "running": return <Loader2 className="h-4 w-4 text-blue-400 animate-spin" />;
      default: return <Circle className="h-4 w-4 text-muted-foreground/30" />;
    }
  };

  const title = pipeline === "shared"
    ? "Shared Analyst Pipeline"
    : pipeline === "decision"
      ? "Horizon Decision Pipeline"
      : "Agent Pipeline";

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="pt-0 space-y-2">
        {agents.map((agent) => (
          <div key={agent.name} className="flex items-center gap-2">
            {statusIcon(agent.status)}
            <span className={`text-sm ${
              agent.status === "completed" ? "text-foreground" :
              agent.status === "running" ? "text-blue-400 font-medium" :
              "text-muted-foreground"
            }`}>
              {agent.name}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
