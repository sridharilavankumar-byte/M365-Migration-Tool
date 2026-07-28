import { useAuth } from "@/context/AuthContext";
import { useNavigate } from "react-router-dom";
import { SignOut, UserCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { useProject } from "@/context/ProjectContext";

export default function TopBar({ title, subtitle, right }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { current } = useProject();
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className="bg-[#050505] border-b border-white/10 h-16 px-6 flex items-center justify-between sticky top-0 z-10">
      <div>
        <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-zinc-500">
          {current ? `project :: ${current.name}` : "no project selected"}
        </div>
        <div className="font-display text-white text-xl leading-none tracking-tight mt-1">{title}</div>
        {subtitle && <div className="text-xs text-zinc-500 mt-1">{subtitle}</div>}
      </div>
      <div className="flex items-center gap-6">
        {right}
        <div className="text-right hidden md:block">
          <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-zinc-500">utc time</div>
          <div className="font-mono text-xs text-zinc-300">{now.toISOString().split("T")[1].slice(0, 8)}</div>
        </div>
        <div className="flex items-center gap-3 pl-6 border-l border-white/10">
          <UserCircle size={22} className="text-zinc-400" />
          <div className="hidden md:block">
            <div className="text-xs text-white leading-none">{user?.name || user?.email}</div>
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 mt-1">{user?.role}</div>
          </div>
          <button
            data-testid="logout-btn"
            onClick={async () => { await logout(); navigate("/login"); }}
            className="ml-2 p-2 border border-white/10 hover:border-white/30 hover:bg-white/5"
            title="Sign out"
          >
            <SignOut size={16} />
          </button>
        </div>
      </div>
    </header>
  );
}
