import { useState, useMemo, useEffect, FormEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { authApi } from '@nerkhbaan/ui/lib/api/auth';
import { useAuthStore } from "@/store/authStore";
import { Card, CardContent, CardHeader, CardTitle } from '@nerkhbaan/ui/app/components/ui/card';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const setToken = useAuthStore((state) => state.setToken);

  const [isLoginMode, setIsLoginMode] = useState(true);
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [identifier, setIdentifier] = useState("");
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
        const response = await authApi.signin({
          username_or_email: identifier.trim(),
          password
        });
        setToken(response.access_token);
        navigate("/", { replace: true });
      } else {
        if (canRegister && requiredInviteCode && inviteCode !== requiredInviteCode) {
          setError("Invalid invite code.");
          setLoading(false);
          return;
        }
        
        const response = await authApi.signup({
          username: username.trim(),
          full_name: fullName.trim(),
          email: email.trim(),
          password
        });
        setToken(response.access_token);
        navigate("/", { replace: true });
      }
    } catch (err: any) {
      setError(err.message || "Authentication failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 p-4 bg-grid">
      <Card className="w-full max-w-md border-cyan-300/20 bg-slate-900/80 backdrop-blur-xl">
        <CardHeader className="space-y-1">
          <CardTitle className="text-center text-2xl font-bold tracking-tight text-cyan-50">
            {isLoginMode ? "Node Authorization" : "Node Registration"}
          </CardTitle>
          <p className="text-center text-sm text-cyan-200/60">
            {isLoginMode ? "Enter your credentials to access the system" : "Create a new access profile"}
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            {!isLoginMode && (
              <>
                <label className="block space-y-2">
                  <span className="text-sm text-cyan-100">Username</span>
                  <Input
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    required
                    placeholder="johndoe"
                  />
                </label>
                <label className="block space-y-2">
                  <span className="text-sm text-cyan-100">Full name</span>
                  <Input
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                    required
                    placeholder="John Doe"
                  />
                </label>
                <label className="block space-y-2">
                  <span className="text-sm text-cyan-100">Email address</span>
                  <Input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                    placeholder="john@example.com"
                  />
                </label>
              </>
            )}

            {isLoginMode && (
              <label className="block space-y-2">
                <span className="text-sm text-cyan-100">Username or Email</span>
                <Input
                  type="text"
                  value={identifier}
                  onChange={(event) => setIdentifier(event.target.value)}
                  required
                  placeholder="johndoe or john@example.com"
                />
              </label>
            )}

            <label className="block space-y-2">
              <span className="text-sm text-cyan-100">Password</span>
              <div className="relative">
                <Input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
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
                  <KeyRound
                    size={16}
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-cyan-300/70"
                  />
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
                  Log in
                </button>
              </>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}