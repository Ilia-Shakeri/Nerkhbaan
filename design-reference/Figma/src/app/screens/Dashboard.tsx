import React from 'react';
import { useAppContext } from '../../contexts/AppContext';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { TrendingUp, TrendingDown, BellPlus } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';

const mockData = {
  gold: Array.from({ length: 20 }, (_, i) => ({ value: 3450000 + Math.random() * 50000 })),
  silver: Array.from({ length: 20 }, (_, i) => ({ value: 45000 + Math.random() * 2000 })),
  usd: Array.from({ length: 20 }, (_, i) => ({ value: 59800 + Math.random() * 500 })),
  btc: Array.from({ length: 20 }, (_, i) => ({ value: 64200 + Math.random() * 2000 })),
};

const assets = [
  { id: 'gold', key: 'asset.gold', price: '۳,۴۸۵,۰۰۰ تومان', change: '+۱.۲٪', isUp: true, data: mockData.gold, color: '#D4AF37' },
  { id: 'usd', key: 'asset.usd', price: '۵۹,۹۵۰ تومان', change: '-۰.۵٪', isUp: false, data: mockData.usd, color: '#10B981' },
  { id: 'btc', key: 'asset.btc', price: '$۶۵,۱۲۰', change: '+۳.۴٪', isUp: true, data: mockData.btc, color: '#F7931A' },
  { id: 'silver', key: 'asset.silver', price: '۴۶,۲۰۰ تومان', change: '+0.1٪', isUp: true, data: mockData.silver, color: '#9CA3AF' },
];

export const Dashboard = () => {
  const { t } = useAppContext();

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          {t('nav.dashboard')}
        </h1>
        <p className="text-sm text-gray-500">آخرین بروزرسانی: دقایقی پیش</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {assets.map((asset) => (
          <Card key={asset.id} className="group relative overflow-hidden transition-all duration-300 hover:border-[#D4AF37]/50 hover:shadow-lg dark:hover:shadow-[#D4AF37]/10">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-center">
                <CardTitle className="text-base text-gray-700 dark:text-gray-300">
                  {t(asset.key)}
                </CardTitle>
                <Badge variant={asset.isUp ? 'positive' : 'negative'} className="flex items-center gap-1">
                  {asset.isUp ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                  <span dir="ltr">{asset.change}</span>
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
                {asset.price}
              </div>
              <div className="h-16 w-full -mx-2">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={asset.data}>
                    <YAxis domain={['dataMin', 'dataMax']} hide />
                    <Line 
                      type="monotone" 
                      dataKey="value" 
                      stroke={asset.isUp ? '#10B981' : '#EF4444'} 
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
            <CardFooter className="pt-2 border-t border-gray-100 dark:border-[#2A2A2A]/50">
              <Button variant="ghost" className="w-full text-[#D4AF37] hover:text-[#E2B714] justify-center gap-2">
                <BellPlus className="w-4 h-4" />
                {t('dash.quick_alert')}
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  );
};
