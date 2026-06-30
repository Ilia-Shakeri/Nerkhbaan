import React, { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Sparkles, Loader2, RefreshCw } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { useAppContext } from '../context/AppContext';
import { api, getPrices, type PriceAsset } from '../services/api';
import { toast } from 'sonner';

export function ChartAnalysisView() {
  const { language, theme } = useAppContext();
  const isDark = theme === 'dark';

  const [assets, setAssets] = useState<PriceAsset[]>([]);
  const [isLoadingAssets, setIsLoadingAssets] = useState(true);
  const [selectedAsset, setSelectedAsset] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const t = {
    title: { fa: 'تحلیل هوشمند', en: 'Smart Analysis' },
    subtitle: {
      fa: 'یک دارایی را برای دریافت تحلیل بازار انتخاب کنید',
      en: 'Pick an asset to get a market read'
    },
    again: { fa: 'تحلیل دوباره', en: 'Re-analyze' },
    pickAsset: { fa: 'ابتدا یک دارایی انتخاب کنید', en: 'Select an asset first' },
    thinking: { fa: 'در حال بررسی بازار...', en: 'Reading the market...' },
    loadFail: { fa: 'خطا در بارگذاری دارایی‌ها', en: 'Failed to load assets' },
    analyzeFail: { fa: 'تحلیل در دسترس نیست', en: 'Analysis is unavailable' }
  };

  useEffect(() => {
    let cancelled = false;
    getPrices()
      .then((data) => {
        if (!cancelled) setAssets(data?.assets ?? []);
      })
      .catch(() => {
        if (!cancelled) toast.error(t.loadFail[language]);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingAssets(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleAnalyze = async (asset: string) => {
    setSelectedAsset(asset);
    setIsAnalyzing(true);
    setAnalysis('');
    try {
      const result = await api.insights.analyze(asset, language);
      setAnalysis(result.analysis);
    } catch (error) {
      const message = error instanceof Error ? error.message : t.analyzeFail[language];
      toast.error(message);
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <div className="h-full flex flex-col space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className={`text-3xl font-bold ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>
            {t.title[language]}
          </h1>
          <p className={`mt-1 text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
            {t.subtitle[language]}
          </p>
        </div>
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#D4AF37] text-black">
          <Sparkles size={22} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0">
        <Card className={`lg:col-span-1 p-4 overflow-y-auto ${isDark ? 'bg-[#0E0E0E]/60 border-white/5' : 'bg-white/60 border-black/5'}`}>
          {isLoadingAssets ? (
            <div className="flex justify-center py-8">
              <Loader2 size={24} className={`animate-spin ${isDark ? 'text-[#D4AF37]' : 'text-[#9D7A20]'}`} />
            </div>
          ) : (
            <div className="space-y-3">
              {assets.map((asset) => (
                <motion.button
                  key={asset.asset}
                  onClick={() => handleAnalyze(asset.asset)}
                  disabled={isAnalyzing}
                  whileHover={{ scale: 1.02 }}
                  className={`w-full text-start p-3 rounded-xl transition-all disabled:opacity-50 ${
                    selectedAsset === asset.asset
                      ? 'bg-[#D4AF37]/20 border border-[#D4AF37]'
                      : isDark ? 'bg-[#141414] hover:bg-[#1A1A1A]' : 'bg-white hover:bg-gray-50'
                  }`}
                >
                  <div className={`font-semibold text-sm ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>
                    {language === 'fa' ? asset.label_fa : asset.label_en}
                  </div>
                  <div className={`text-xs mt-1 ${asset.trend === 'up' ? 'text-emerald-500' : 'text-red-500'}`}>
                    {asset.change_percent > 0 ? '+' : ''}{asset.change_percent}%
                  </div>
                </motion.button>
              ))}
            </div>
          )}
        </Card>

        <Card className={`lg:col-span-2 flex flex-col p-6 ${isDark ? 'bg-[#0E0E0E]/60 border-white/5' : 'bg-white/60 border-black/5'}`}>
          {isAnalyzing ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-3">
              <Loader2 size={32} className={`animate-spin ${isDark ? 'text-[#D4AF37]' : 'text-[#9D7A20]'}`} />
              <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>{t.thinking[language]}</p>
            </div>
          ) : analysis ? (
            <>
              <div className="flex-1 overflow-y-auto">
                <p className={`whitespace-pre-wrap leading-8 text-sm ${isDark ? 'text-[#E2D3AA]' : 'text-[#4A3913]'}`}>
                  {analysis}
                </p>
              </div>
              {selectedAsset && (
                <div className="pt-4">
                  <Button
                    onClick={() => handleAnalyze(selectedAsset)}
                    className="gap-2 bg-[#D4AF37] text-black"
                  >
                    <RefreshCw size={16} />
                    {t.again[language]}
                  </Button>
                </div>
              )}
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <Sparkles size={48} className={`mx-auto mb-4 ${isDark ? 'text-gray-600' : 'text-gray-400'}`} />
                <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                  {t.pickAsset[language]}
                </p>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
