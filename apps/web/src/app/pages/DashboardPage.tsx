import { useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { fetchPrices, type PriceAsset } from "@/lib/api/prices";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function DashboardPage() {
  const [assets, setAssets] = useState<PriceAsset[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    const run = async () => {
      try {
        const response = await fetchPrices();
        if (mounted) {
          setAssets(response.assets);
        }
      } catch {
        if (mounted) {
          setAssets([]);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    void run();
    const interval = window.setInterval(() => void run(), 30000);

    return () => {
      mounted = false;
      window.clearInterval(interval);
    };
  }, []);

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-2xl font-semibold text-cyan-100">Market Dashboard</h2>
        <p className="text-sm text-cyan-300/75">Live values from your private backend node.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {loading && <p className="text-sm text-cyan-200/70">Loading prices...</p>}
        {!loading && assets.length === 0 && <p className="text-sm text-cyan-200/70">No data available.</p>}
        {assets.map((asset) => (
          <Card key={asset.asset} className="border-cyan-300/20 bg-slate-900/65 backdrop-blur">
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-cyan-100">
                <span>{asset.label_en}</span>
                <span className="text-xs text-cyan-300/70">{asset.asset.toUpperCase()}</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-semibold text-cyan-100">
                {asset.price_usd ? `$${asset.price_usd.toLocaleString("en-US")}` : "--"}
              </div>
              <div className="mt-2 flex items-center gap-1 text-sm text-cyan-300">
                {asset.trend === "up" ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                <span>{asset.change_percent.toFixed(2)}%</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
