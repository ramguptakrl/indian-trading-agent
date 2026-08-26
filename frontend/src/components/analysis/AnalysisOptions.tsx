"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronUp, Settings2 } from "lucide-react";

interface Props {
  analysts: string[];
  onAnalystsChange: (analysts: string[]) => void;
  depth: number;
  onDepthChange: (depth: number) => void;
  language: string;
  onLanguageChange: (lang: string) => void;
  disabled?: boolean;
}

const availableAnalysts = [
  { value: "market", label: "Price & Structure", description: "BSE trend, levels, volume, volatility" },
  { value: "news", label: "BSE Context", description: "Company, exchange, regulatory and market context" },
  { value: "fundamentals", label: "Fundamentals", description: "BSE business and financial evidence" },
  {
    value: "social",
    label: "Social (experimental)",
    description: "Optional public-sentiment evidence; not part of the default BSE team",
  },
];

const depthOptions = [
  { value: 1, label: "Shallow", description: "1 debate round · recommended · lowest model usage" },
  { value: 2, label: "Medium", description: "2 debate rounds · roughly doubles debate calls" },
  { value: 3, label: "Deep", description: "3 debate rounds · benchmark mode · highest quota use" },
];

const languages = [
  { value: "English", label: "English" },
  { value: "Hindi", label: "हिन्दी (Hindi)" },
];

export function AnalysisOptions({
  analysts,
  onAnalystsChange,
  depth,
  onDepthChange,
  language,
  onLanguageChange,
  disabled,
}: Props) {
  const [expanded, setExpanded] = useState(false);

  const toggleAnalyst = (val: string) => {
    if (analysts.includes(val)) {
      if (analysts.length > 1) onAnalystsChange(analysts.filter((a) => a !== val));
    } else {
      onAnalystsChange([...analysts, val]);
    }
  };

  return (
    <Card>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 text-left hover:bg-accent/30 transition-colors rounded-t-lg"
        disabled={disabled}
      >
        <div className="flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-sm">Customize BSE Research</span>
          <Badge variant="outline" className="text-xs">
            {analysts.length} agents · Depth {depth} · {language}
          </Badge>
          {depth === 1 && <Badge variant="secondary" className="text-[10px]">RECOMMENDED</Badge>}
        </div>
        {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>

      {expanded && (
        <CardContent className="space-y-4 pt-0">
          <div>
            <label className="text-xs font-medium mb-2 block">BSE research agents</label>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {availableAnalysts.map((a) => {
                const active = analysts.includes(a.value);
                return (
                  <button
                    key={a.value}
                    type="button"
                    onClick={() => toggleAnalyst(a.value)}
                    disabled={disabled}
                    className={`p-2 rounded-lg border text-left transition-colors ${
                      active
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-primary/30 opacity-60"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium">{a.label}</span>
                      <input
                        type="checkbox"
                        checked={active}
                        readOnly
                        className="h-3 w-3 pointer-events-none"
                      />
                    </div>
                    <p className="text-[10px] text-muted-foreground">{a.description}</p>
                  </button>
                );
              })}
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">
              More agents use more provider requests. Social sentiment stays optional until evidence proves it adds value for BSE Ltd.
            </p>
          </div>

          <div>
            <label className="text-xs font-medium mb-2 block">Research depth</label>
            <div className="grid grid-cols-3 gap-2">
              {depthOptions.map((d) => (
                <button
                  key={d.value}
                  type="button"
                  onClick={() => onDepthChange(d.value)}
                  disabled={disabled}
                  className={`p-3 rounded-lg border text-left transition-colors ${
                    depth === d.value
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/30"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{d.label}</span>
                    {d.value === 1 && <Badge variant="secondary" className="text-[9px]">NORMAL USE</Badge>}
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-1">{d.description}</p>
                </button>
              ))}
            </div>
            {depth > 1 ? (
              <p className="text-[10px] text-amber-700 mt-2">
                Higher depth repeats both investment and risk debates for each horizon. On free API tiers this can consume quota quickly; use Shallow for normal live analysis.
              </p>
            ) : (
              <p className="text-[10px] text-muted-foreground mt-1">
                Shallow still runs the full analyst → Bull/Bear → Research Manager → Trader → Risk → Portfolio Manager chain; it only limits repeated debate rounds.
              </p>
            )}
          </div>

          <div>
            <label className="text-xs font-medium mb-2 block">Report Language</label>
            <div className="flex gap-2">
              {languages.map((l) => (
                <button
                  key={l.value}
                  type="button"
                  onClick={() => onLanguageChange(l.value)}
                  disabled={disabled}
                  className={`px-3 py-1.5 rounded-md border text-sm transition-colors ${
                    language === l.value
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/30"
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">
              Internal debates stay in English; user-facing reports use the selected language.
            </p>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
