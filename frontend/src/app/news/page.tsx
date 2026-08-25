"use client";

import { useEffect, useState } from "react";
import { getNewsFeed, getTickerNews } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AlertTriangle, ExternalLink, Loader2, Newspaper, RefreshCw, Rss } from "lucide-react";

interface Article {
  source?: string;
  source_type?: string;
  title?: string;
  summary?: string;
  url?: string;
  published_at?: string;
}

function ArticleList({ articles, empty }: { articles: Article[]; empty: string }) {
  if (articles.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">{empty}</CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-2">
      {articles.map((article, index) => (
        <Card key={`${article.url || article.title}-${index}`} className="hover:shadow-sm transition-shadow">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <Badge variant="outline" className="text-xs">
                <Rss className="h-2.5 w-2.5 mr-1" /> {article.source || "Source unavailable"}
              </Badge>
              {article.published_at && <span className="text-xs text-muted-foreground">{article.published_at}</span>}
            </div>
            {article.url ? (
              <a
                href={article.url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-sm hover:text-primary transition-colors flex items-start gap-1"
              >
                {article.title || "Untitled article"}
                <ExternalLink className="h-3 w-3 mt-0.5 shrink-0" />
              </a>
            ) : (
              <p className="font-medium text-sm">{article.title || "Untitled article"}</p>
            )}
            {article.summary && <p className="text-xs text-muted-foreground mt-1 line-clamp-3">{article.summary}</p>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default function NewsPage() {
  const [bseArticles, setBseArticles] = useState<Article[]>([]);
  const [contextArticles, setContextArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadNews = async () => {
    setLoading(true);
    setError(null);
    try {
      const [bse, context]: any[] = await Promise.all([
        getTickerNews("BSE", 20),
        getNewsFeed(6),
      ]);
      setBseArticles(bse?.articles || []);
      setContextArticles(context?.articles || []);
    } catch (e: any) {
      setError(e?.message || "Could not load BSE context news.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadNews();
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Newspaper className="h-6 w-6" /> BSE Context
            </h1>
            <Badge variant="outline">NSE:BSE</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Company, exchange, regulatory and broader-market evidence that may affect BSE Ltd.
            Nothing on this page is a separate trade target.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={loadNews} disabled={loading}>
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <RefreshCw className="h-3.5 w-3.5 mr-1" />}
          Refresh
        </Button>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          Context is evidence, not a signal. Trade Brain still requires BSE-specific price geometry and the deterministic gate before showing a valid candidate.
        </span>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {loading ? (
        <div className="py-20 text-center">
          <Loader2 className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
          <p className="text-xs text-muted-foreground mt-2">Fetching BSE-relevant context...</p>
        </div>
      ) : (
        <Tabs defaultValue="bse">
          <TabsList>
            <TabsTrigger value="bse">BSE Ltd ({bseArticles.length})</TabsTrigger>
            <TabsTrigger value="market">Broader Market — Context Only ({contextArticles.length})</TabsTrigger>
          </TabsList>
          <TabsContent value="bse" className="mt-4">
            <ArticleList
              articles={bseArticles}
              empty="No BSE-specific articles were returned by the configured sources. Trade Brain should treat that as missing evidence, not a neutral/bullish signal."
            />
          </TabsContent>
          <TabsContent value="market" className="mt-4">
            <ArticleList
              articles={contextArticles}
              empty="No broader Indian-market context is currently available from the configured sources."
            />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
