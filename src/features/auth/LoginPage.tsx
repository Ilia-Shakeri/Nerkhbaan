import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { KeyRound, Lock, Mail, User } from "lucide-react";
import { authApi } from "@/lib/api/auth";
import { useAuthStore } from "@/app/store/authStore";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const setToken = useAuthStore((state) => state.setToken);

  const [isLoginMode, setIsLoginMode] = useState(true);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const registrationEnabled = import.meta.env.VITE_ENABLE_REGISTRATION === "true";
  const requiredInviteCode = import.meta.env.VITE_INVITE_CODE?.trim() ?? "";

  const canRegister = useMemo(() => registrationEnabled, [registrationEnabled]);

  useEffect(() => {
    if (isAuthenticated) {
      navigate("/", { replace: true });
    }
  }, [isAuthenticated, navigate]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      if (isLoginMode) {
        const response = await authApi.signIn({ email: email.trim(), password });
        setToken(response.access_token);
      } else {
        if (!canRegister) {
          setError("Registration is disabled for this private instance.");
          setLoading(false);
          return;
        }

        if (!requiredInviteCode || inviteCode.trim() !== requiredInviteCode) {
          setError("Invalid invite code.");
          setLoading(false);
          return;
        }

        const response = await authApi.signUp({
          full_name: fullName.trim(),
          email: email.trim(),
          password,
          invite_code: inviteCode.trim()
        });

        setToken(response.access_token);
      }

      const destination = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname;
      navigate(destination || "/", { replace: true });
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "Authentication failed.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-grid px-4 py-10">
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] w-full max-w-md items-center">
        <Card className="w-full border-cyan-300/25 bg-slate-950/75 shadow-glass backdrop-blur-xl">
          <CardHeader>
            <p className="text-xs uppercase tracking-[0.25em] text-cyan-300">Private Node</p>
            <CardTitle className="text-2xl text-cyan-100">
              {isLoginMode ? "Secure Login" : "Invite-Only Registration"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-4">
              {!isLoginMode && (
                <label className="block space-y-2">
                  <span className="text-sm text-cyan-100">Full name</span>
                  <div className="relative">
                    <User size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-cyan-300/70" />
                    <Input
                      value={fullName}
                      onChange={(event) => setFullName(event.target.value)}
                      required
                      className="pl-9"
                      placeholder="John Doe"
                    />
                  </div>
                </label>
              )}

              <label className="block space-y-2">
                <span className="text-sm text-cyan-100">Email</span>
                <div className="relative">
                  <Mail size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-cyan-300/70" />
                  <Input
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    type="email"
                    required
                    className="pl-9"
                    placeholder="you@company.com"
                  />
                </div>
              </label>

              <label className="block space-y-2">
                <span className="text-sm text-cyan-100">Password</span>
                <div className="relative">
                  <Lock size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-cyan-300/70" />
                  <Input
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    type="password"
                    required
                    className="pl-9"
                    placeholder="••••••••"
                  />
                </div>
              </label>

              {!isLoginMode && (
                <label className="block space-y-2">
                  <span className="text-sm text-cyan-100">Invite code</span>
                  <div className="relative">
                    <KeyRound size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-cyan-300/70" />
                    <Input
                      value={inviteCode}
                      onChange={(event) => setInviteCode(event.target.value)}
                      required
                      className="pl-9"
                      placeholder="INVITE-XXXX"
                    />
                  </div>
                </label>
              )}

              {error && <p className="rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">{error}</p>}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Please wait..." : isLoginMode ? "Log in" : "Create account"}
              </Button>
            </form>

            <div className="mt-4 flex items-center justify-between text-sm text-cyan-200/80">
              {isLoginMode ? (
                <>
                  <span>No access yet?</span>
                  {canRegister ? (
                    <button type="button" className="text-cyan-300 hover:text-cyan-200" onClick={() => setIsLoginMode(false)}>
                      Use invite
                    </button>
                  ) : (
                    <span className="text-cyan-300/70">Registration locked</span>
                  )}
                </>
              ) : (
                <>
                  <span>Already authenticated?</span>
                  <button type="button" className="text-cyan-300 hover:text-cyan-200" onClick={() => setIsLoginMode(true)}>
                    Back to login
                  </button>
                </>
              )}
            </div>

            <div className="mt-3 text-xs text-cyan-300/70">
              API endpoint is expected at <code>/api</code> on the same domain.
              <Link to="/login" className="ml-2 underline decoration-cyan-500/60 underline-offset-4">
                Refresh auth screen
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
