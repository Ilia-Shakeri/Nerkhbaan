import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function SettingsPage() {
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold text-cyan-100">Settings</h2>
      <Card className="border-cyan-300/20 bg-slate-900/65 backdrop-blur">
        <CardHeader>
          <CardTitle className="text-cyan-100">Instance Security</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-cyan-200/80">
          <p>- JWT token is attached on every request through Axios interceptors.</p>
          <p>- Any 401 response clears the session and forces navigation back to `/login`.</p>
          <p>- Registration can stay disabled or be unlocked with invite code only.</p>
        </CardContent>
      </Card>
    </section>
  );
}
