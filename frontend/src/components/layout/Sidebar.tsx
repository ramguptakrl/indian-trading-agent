"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  Search,
  CandlestickChart,
  History,
  Settings,
  TrendingUp,
  Newspaper,
  Brain,
  BriefcaseBusiness,
} from "lucide-react";

type NavItem = {
  href: string;
  label: string;
  icon: any;
  hint?: string;
};

type NavGroup = {
  title?: string;
  items: NavItem[];
};

// Trade Brain is intentionally a BSE Ltd product. Legacy multi-stock discovery and
// generic strategy surfaces are not part of the BSE runtime navigation. Broader market
// information survives only as context for BSE Ltd decisions.
const navGroups: NavGroup[] = [
  {
    items: [
      { href: "/", label: "BSE Today", icon: Home, hint: "BSE decision workspace" },
    ],
  },
  {
    title: "DECIDE",
    items: [
      { href: "/analysis", label: "BSE Analysis", icon: Search, hint: "INTRADAY / SWING research + levels" },
      { href: "/charts", label: "Price & Structure", icon: CandlestickChart, hint: "Audited BSE price path" },
      { href: "/news", label: "BSE Context", icon: Newspaper, hint: "Market, regulatory & company context" },
    ],
  },
  {
    title: "EVIDENCE",
    items: [
      { href: "/insights", label: "BSE Evidence", icon: Brain, hint: "Replay, study & learning evidence" },
      { href: "/history", label: "Analysis Outcomes", icon: History, hint: "BSE research outcomes" },
    ],
  },
  {
    title: "TRACK",
    items: [
      { href: "/trades", label: "Actual Trades", icon: BriefcaseBusiness, hint: "BSE trades you really took" },
    ],
  },
  {
    items: [
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-full w-64 bg-card border-r border-border flex flex-col z-50">
      <div className="p-6 border-b border-border">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-6 w-6 text-green-500" />
          <div>
            <h1 className="font-bold text-lg">Trade Brain</h1>
            <p className="text-xs text-muted-foreground">BSE LTD · NSE:BSE</p>
            <p className="text-[10px] text-muted-foreground/80 mt-0.5">INTRADAY + SWING</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 p-3 space-y-4 overflow-y-auto">
        {navGroups.map((group, gi) => (
          <div key={gi}>
            {group.title && (
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-3 mb-1.5">
                {group.title}
              </p>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors group ${
                      isActive
                        ? "bg-accent text-accent-foreground font-medium"
                        : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                    }`}
                  >
                    <item.icon className="h-4 w-4 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div>{item.label}</div>
                      {item.hint && !isActive && (
                        <div className="text-[10px] text-muted-foreground/70 group-hover:text-muted-foreground truncate">
                          {item.hint}
                        </div>
                      )}
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="p-4 border-t border-border">
        <div className="text-[10px] text-muted-foreground">
          <p>BSE Ltd is the only trade target</p>
          <p className="mt-0.5">Broader market: context only</p>
          <p className="mt-0.5">Price: Kite-primary · audited fallback</p>
          <p className="mt-0.5">Broker order execution: OFF</p>
        </div>
      </div>
    </aside>
  );
}
