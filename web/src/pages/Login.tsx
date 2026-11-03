import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Button, ErrorNote, Field, Input } from "../components/ui";
import { Brand } from "../components/Layout";

export default function Login() {
  const { user, login } = useAuth();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const next = sp.get("next") || "/";

  if (user) return <Navigate to={next} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      nav(next.startsWith("/") && !next.startsWith("/login") ? next : "/", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-[1fr_520px]">
      <div className="hidden lg:flex flex-col justify-between p-10 bg-accent text-white">
        <div className="flex items-center gap-2">
          <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="6" fill="#fff" />
            <path d="M9 10h14M16 10v13M11 16h6" stroke="#1E4F8A" strokeWidth="2.6" strokeLinecap="round" />
          </svg>
          <span className="text-lg font-semibold">TwoB</span>
        </div>
        <div className="max-w-md">
          <p className="text-[28px] leading-[1.25] font-medium tracking-[-0.015em]">
            Purchase register against GSTR-2B, supplier by supplier, with a record of every decision.
          </p>
          <MonthWindow />
        </div>
        <p className="text-sm text-white/60">Recommendations are defaults for a CA to review, not filing advice.</p>
      </div>

      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-[340px]">
          <Brand className="lg:hidden mb-8" />
          <h1 className="text-2xl font-semibold tracking-[-0.015em]">Sign in</h1>
          <p className="text-sm text-muted mt-1 mb-6">Use the username your firm's admin gave you.</p>
          <div className="space-y-4">
            <Field label="Username">
              <Input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </Field>
            <Field label="Password">
              <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </Field>
            <ErrorNote error={error} />
            <Button type="submit" variant="primary" className="w-full" busy={busy}>
              Sign in
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** The monthly 11th-20th window, as staff live it. Decorative on the sign-in page only. */
function MonthWindow() {
  const days = Array.from({ length: 10 }, (_, i) => 11 + i);
  return (
    <div className="mt-8">
      <div className="flex gap-1">
        {days.map((d) => (
          <div
            key={d}
            className={
              "w-9 h-11 rounded flex flex-col items-center justify-center text-sm num " +
              (d === 14 || d === 20 ? "bg-white text-accent font-semibold" : "bg-white/10 text-white/80")
            }
          >
            {d}
            {(d === 14 || d === 20) && <span className="text-2xs font-medium">{d === 14 ? "IMS" : "3B"}</span>}
          </div>
        ))}
      </div>
      <p className="mt-2 text-sm text-white/70">IMS actions before the 14th. GSTR-3B by the 20th.</p>
    </div>
  );
}
