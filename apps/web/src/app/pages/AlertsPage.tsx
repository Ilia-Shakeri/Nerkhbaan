import { Card, CardContent, CardHeader, CardTitle } from '@nerkhbaan/ui/app/components/ui/card';

export function AlertsPage() {
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold text-cyan-100">Alerts</h2>
      <Card className="border-cyan-300/20 bg-slate-900/65 backdrop-blur">
        <CardHeader>
          <CardTitle className="text-cyan-100">Push Notification Pipeline</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-cyan-200/80">
          Web push scaffolding is active. Connect your backend to `/api/push/subscribe` to enable mobile and desktop notifications.
        </CardContent>
      </Card>
    </section>
  );
}
