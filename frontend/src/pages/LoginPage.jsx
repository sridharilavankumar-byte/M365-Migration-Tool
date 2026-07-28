import { useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import { ShieldCheck, ArrowRight } from "@phosphor-icons/react";

export default function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("admin@migratetool.com");
  const [password, setPassword] = useState("Admin@12345");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const loc = useLocation();
  const returnTo = loc.state?.from || "/app/dashboard";

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name || email.split("@")[0]);
      nav(returnTo, { replace: true });
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] text-white relative overflow-hidden">
      <div className="absolute inset-0 opacity-20">
        <img
          src="https://images.pexels.com/photos/37730212/pexels-photo-37730212.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940"
          className="w-full h-full object-cover"
          alt=""
        />
      </div>
      <div className="absolute inset-0 grid-lines-bg opacity-40" />
      <div className="absolute inset-0 bg-gradient-to-br from-[#050505] via-[#050505]/70 to-[#050505]" />

      <div className="relative z-10 min-h-screen flex flex-col">
        <div className="px-8 py-5 flex items-center gap-2 border-b border-white/10">
          <div className="w-8 h-8 bg-[#00e5ff] text-black flex items-center justify-center font-mono font-bold text-sm">M</div>
          <div>
            <div className="font-display text-white text-base leading-none tracking-tight">MigrateSuite</div>
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 mt-1">m365 tenant-to-tenant ops</div>
          </div>
        </div>

        <div className="flex-1 flex items-center justify-center px-6 py-12">
          <div className="w-full max-w-5xl grid md:grid-cols-2 gap-0 border border-white/10 bg-[#0a0a0a]/90 backdrop-blur-sm">
            {/* Left: pitch */}
            <div className="p-10 border-r border-white/10 hidden md:flex flex-col justify-between">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#00e5ff]">system.access</div>
                <h1 className="font-display text-4xl lg:text-5xl tracking-tighter mt-4 leading-[1.05]">
                  Migrate every<br />Microsoft 365 service.<br />
                  <span className="text-[#00e5ff]">Zero downtime.</span>
                </h1>
                <p className="text-sm text-zinc-400 mt-6 max-w-sm leading-relaxed">
                  Exchange mailboxes, SharePoint sites, OneDrive, Teams, Groups, Distribution Lists, Contacts, Calendars and Public Folders — each with an isolated migration engine.
                </p>
              </div>
              <div className="mt-10 grid grid-cols-3 gap-4 pt-6 border-t border-white/10">
                {[
                  ["09", "services"],
                  ["24/7", "orchestration"],
                  ["∞", "throughput"],
                ].map(([v, l]) => (
                  <div key={l}>
                    <div className="font-display text-3xl tracking-tighter">{v}</div>
                    <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 mt-1">{l}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right: form */}
            <div className="p-10">
              <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.2em] text-zinc-500">
                <ShieldCheck size={14} className="text-[#00e5ff]" />
                secure operator terminal
              </div>
              <h2 className="font-display text-3xl tracking-tighter mt-3">
                {mode === "login" ? "Sign in" : "Create account"}<span className="text-[#00e5ff] cursor-blink" />
              </h2>
              <p className="text-sm text-zinc-500 mt-2">
                {mode === "login"
                  ? "Access the migration control plane."
                  : "Provision a new operator identity."}
              </p>

              <form onSubmit={submit} className="mt-8 space-y-4">
                {mode === "register" && (
                  <div>
                    <label className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 block mb-2">Name</label>
                    <input
                      data-testid="register-name-input"
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="w-full bg-[#050505] border border-white/10 px-3 py-2.5 text-sm text-white focus:border-[#00e5ff] focus:outline-none"
                      placeholder="Alex Cortex"
                    />
                  </div>
                )}
                <div>
                  <label className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 block mb-2">Email</label>
                  <input
                    data-testid="login-email-input"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-[#050505] border border-white/10 px-3 py-2.5 text-sm text-white focus:border-[#00e5ff] focus:outline-none font-mono"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 block mb-2">Password</label>
                  <input
                    data-testid="login-password-input"
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-[#050505] border border-white/10 px-3 py-2.5 text-sm text-white focus:border-[#00e5ff] focus:outline-none font-mono"
                  />
                </div>

                {error && (
                  <div className="text-xs font-mono text-[#ff3b30] border border-[#ff3b30]/30 bg-[#ff3b30]/5 px-3 py-2" data-testid="login-error">
                    err :: {error}
                  </div>
                )}

                <button
                  data-testid="login-submit-btn"
                  type="submit"
                  disabled={busy}
                  className="w-full bg-[#00e5ff] hover:bg-[#00b3cc] disabled:opacity-50 text-black font-medium text-sm px-4 py-3 flex items-center justify-center gap-2 transition-colors"
                >
                  {busy ? "authenticating…" : mode === "login" ? "Sign In" : "Create Account"}
                  <ArrowRight size={14} weight="bold" />
                </button>

                <div className="text-center pt-2">
                  <button
                    type="button"
                    onClick={() => setMode(mode === "login" ? "register" : "login")}
                    className="text-xs text-zinc-500 hover:text-white font-mono"
                    data-testid="toggle-auth-mode"
                  >
                    {mode === "login" ? "→ register new operator" : "→ sign in existing"}
                  </button>
                </div>
              </form>

              <div className="mt-8 pt-6 border-t border-white/10 text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-600 leading-relaxed">
                admin :: admin@migratetool.com<br />
                token :: Admin@12345
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
