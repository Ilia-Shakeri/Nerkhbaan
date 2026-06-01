import { apiClient } from "@/lib/api/client";

export type PriceAsset = {
  asset: "gold" | "silver" | "usdt" | "btc";
  label_en: string;
  price_usd: number | null;
  change_percent: number;
  trend: "up" | "down";
};

export type PricesResponse = {
  refreshed_at: string;
  assets: PriceAsset[];
};

export async function fetchPrices() {
  const { data } = await apiClient.get<PricesResponse>("/prices");
  return data;
}
