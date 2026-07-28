import { useEffect, useState } from "react";
import TopBar from "@/components/layout/TopBar";
import { Panel } from "@/components/shared/Primitives";
import { api } from "@/lib/api";

export default function LogsPage() {
  const [jobs, setJobs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [logs, setLogs] = useState([]);

  useEffect(() => {
    (async () => {
      const { data } = await api.get("/jobs");
      setJobs(data);
      if (data[0]) setSelected(data[0].id);
    })();
  }, []);

  useEffect(() => {
    if (!selected) return;
    const load = async () => {
      const { data } = await api.get(`/jobs/${selected}/logs`);
      setLogs(data);
    };
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [selected]);

  return (
    <>
      <TopBar title="Audit Logs" subtitle="Immutable audit trail across all migration jobs" />
      <div className="p-6 grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
        <Panel className="p-0">
          <div className="px-4 py-3 border-b border-white/10 text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">jobs</div>
          <div className="max-h-[70vh] overflow-y-auto">
            {jobs.map((j) => (
              <button
                key={j.id}
                onClick={() => setSelected(j.id)}
                data-testid={`log-job-${j.id}`}
                className={`w-full text-left px-4 py-2.5 border-l-2 ${selected === j.id ? "border-[#00e5ff] bg-white/[0.03]" : "border-transparent hover:bg-white/[0.02]"}`}
              >
                <div className="text-xs text-white truncate">{j.service_type} · {j.project_name}</div>
                <div className="text-[10px] font-mono text-zinc-500 mt-0.5">{j.id.slice(-8)} · {j.status}</div>
              </button>
            ))}
            {jobs.length === 0 && <div className="p-4 text-xs font-mono text-zinc-500">no jobs</div>}
          </div>
        </Panel>
        <Panel className="p-0 scanlines">
          <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-[#00e5ff]">audit stream</div>
            <div className="text-[10px] font-mono text-zinc-500">{logs.length} entries</div>
          </div>
          <div className="p-4 font-mono text-[11px] h-[70vh] overflow-y-auto leading-relaxed">
            {logs.length === 0 && <div className="text-zinc-600 cursor-blink">awaiting entries</div>}
            {logs.map((l) => (
              <div key={l.id} className="flex gap-2 border-b border-white/5 py-1">
                <span className="text-zinc-600 shrink-0">{new Date(l.ts).toISOString().replace("T", " ").slice(0, 19)}</span>
                <span className={l.level === "error" ? "text-[#ff3b30]" : l.level === "warn" ? "text-[#ffd600]" : "text-zinc-300"}>[{l.level.toUpperCase()}]</span>
                <span className="text-zinc-300">{l.message}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}
