import React, { useState } from 'react';
import { useAppContext } from '../../contexts/AppContext';
import { Card, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Switch } from '../components/ui/Switch';
import { Bell, Edit2, Trash2, Plus } from 'lucide-react';

const initialAlerts = [
  { id: 1, assetKey: 'asset.gold', target: '۳,۵۰۰,۰۰۰ تومان', condition: 'بیشتر از', active: true },
  { id: 2, assetKey: 'asset.usd', target: '۵۹,۰۰۰ تومان', condition: 'کمتر از', active: false },
  { id: 3, assetKey: 'asset.btc', target: '+۵٪ تغییر روزانه', condition: 'نوسان', active: true },
];

export const Alerts = () => {
  const { t } = useAppContext();
  const [alerts, setAlerts] = useState(initialAlerts);

  const toggleAlert = (id: number) => {
    setAlerts(alerts.map(a => a.id === id ? { ...a, active: !a.active } : a));
  };

  const deleteAlert = (id: number) => {
    setAlerts(alerts.filter(a => a.id !== id));
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-1">
            {t('alerts.title')}
          </h1>
          <p className="text-sm text-gray-500">مدیریت هشدارهای قیمتی شخصی شما</p>
        </div>
        <Button className="gap-2">
          <Plus className="w-5 h-5" />
          {t('alerts.create')}
        </Button>
      </div>

      <div className="space-y-4">
        {alerts.length === 0 ? (
          <div className="text-center py-12 border border-dashed border-gray-300 dark:border-[#2A2A2A] rounded-xl">
            <Bell className="mx-auto h-12 w-12 text-gray-400 mb-3" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-1">هیچ هشداری یافت نشد</h3>
            <p className="text-gray-500">برای شروع یک هشدار جدید تنظیم کنید.</p>
          </div>
        ) : (
          alerts.map(alert => (
            <Card key={alert.id} className="transition-all hover:border-gray-300 dark:hover:border-[#3A3A3A]">
              <CardContent className="flex items-center justify-between p-5 sm:p-6">
                <div className="flex items-center gap-4 sm:gap-6">
                  <div className={`p-3 rounded-full ${alert.active ? 'bg-[#10B981]/10 text-[#10B981]' : 'bg-gray-100 text-gray-400 dark:bg-[#1C1C1C] dark:text-gray-500'}`}>
                    <Bell className="w-6 h-6" />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
                      {t(alert.assetKey)}
                    </h3>
                    <div className="flex items-center gap-3 text-sm">
                      <Badge variant="outline" className="text-gray-600 dark:text-gray-300">
                        {alert.condition} {alert.target}
                      </Badge>
                      <span className="text-gray-400">
                        {alert.active ? 'فعال' : 'غیرفعال'}
                      </span>
                    </div>
                  </div>
                </div>
                
                <div className="flex items-center gap-4 sm:gap-6">
                  <Switch 
                    checked={alert.active} 
                    onCheckedChange={() => toggleAlert(alert.id)}
                  />
                  
                  <div className="flex items-center gap-2 border-r pr-4 rtl:border-l rtl:border-r-0 rtl:pl-4 rtl:pr-0 border-gray-200 dark:border-[#2A2A2A]">
                    <Button variant="ghost" size="sm" className="w-9 h-9 p-0 text-gray-500 hover:text-gray-900 dark:hover:text-white">
                      <Edit2 className="w-4 h-4" />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => deleteAlert(alert.id)} className="w-9 h-9 p-0 text-gray-500 hover:text-red-500 hover:bg-red-500/10">
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  );
};
