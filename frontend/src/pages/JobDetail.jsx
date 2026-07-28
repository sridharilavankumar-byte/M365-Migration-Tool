import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import TopBar from "@/components/layout/TopBar";
import { Panel, DataLabel, StatusBadge, ProgressLine } from "@/components/shared/Primitives";
import { api, API } from "@/lib/api";
import { toast } from "sonner";
import { Pause, Play, X, ArrowsClockwise, FileCsv, FilePdf } from "@phosphor-icons/react";

export default function JobDetail() {
  const { jobId } = useParams();
  const [job, setJob] = useState(null);
  const [logs, setLogs] = useState([]);
  const [filter, setFilter] = useState("all");
  const logsEndRef = useRef(null);

  const load = async () => {
    const [{ data: j }, { data: l }] = await Promise.all([
      api.get(`/jobs/${jobId}`),
      api.get(`/jobs/${jobId}/logs`),
    ]);
    setJob(j);
    setLogs(l);
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [jobId]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  const doAction = async (action) => {
    try {
      const { data } = await api.post(`/jobs/${jobId}/${action}`);
      if (data.ok) toast.success(`${action} accepted`);
      else toast.error(data.message || `${action} not applicable`);
      load();
    } catch (err) {
      toast.error("action failed");
    }
  };

  if (!job) return <div className="p-8 text-zinc-500 font-mono text-xs cursor-blink">loading job</div>;

  const items = job.items || [];
  const filteredItems = filter === "all" ? items : items.filter((i) => i.status === filter);

  return (
    <>
      <TopBar
        title={`Job · ${job.service_type}`}
        subtitle={`${job.project_name} · ${job.total} items · mode: ${job.mode}`}
        right={
          <div className="flex items-center gap-2">
            {["completed", "canceled"].includes(job.status) && (
              <>
                <a
                  href={`${API}/jobs/${jobId}/report.csv`}
                  target="_blank"
                  rel="noreferrer"
                  data-testid="download-csv"
                  className="text-xs font-mono uppercase tracking-[0.1em] px-3 py-2 border border-white/20 hover:bg-white/5 flex items-center gap-1.5"
                  onClick={async (e) => {
                    e.preventDefault();
                    const t = localStorage.getItem("mm_token");
                    const r = await fetch(`${API}/jobs/${jobId}/report.csv`, { headers: { Authorization: `Bearer ${t}` }, credentials: "include" });
                    const blob = await r.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a"); a.href = url; a.download = `job-${jobId}.csv`; a.click(); URL.revokeObjectURL(url);
                  }}
                >
                  <FileCsv size={13} /> csv
                </a>
                <a
                  href={`${API}/jobs/${jobId}/report.pdf`}
                  data-testid="download-pdf"
                  className="text-xs font-mono uppercase tracking-[0.1em] px-3 py-2 border border-white/20 hover:bg-white/5 flex items-center gap-1.5"
                  onClick={async (e) => {
                    e.preventDefault();
                    const t = localStorage.getItem("mm_token");
                    const r = await fetch(`${API}/jobs/${jobId}/report.pdf`, { headers: { Authorization: `Bearer ${t}` }, credentials: "include" });
                    const blob = await r.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a"); a.href = url; a.download = `job-${jobId}.pdf`; a.click(); URL.revokeObjectURL(url);
                  }}
                >
                  <FilePdf size={13} /> pdf
                </a>
              </>
            )}
            {job.status === "running" && (
              <button onClick={() => doAction("pause")} data-testid="pause-btn" className="text-xs font-mono uppercase tracking-[0.1em] px-3 py-2 border border-white/20 hover:bg-white/5 flex items-center gap-1.5">
                <Pause size={13} weight="fill" /> pause
              </button>
            )}
            {job.status === "paused" && (
              <button onClick={() => doAction("resume")} data-testid="resume-btn" className="text-xs font-mono uppercase tracking-[0.1em] px-3 py-2 border border-white/20 hover:bg-white/5 flex items-center gap-1.5">
                <Play size={13} weight="fill" /> resume
              </button>
            )}
            {["running", "paused", "queued"].includes(job.status) && (
              <button onClick={() => doAction("cancel")} data-testid="cancel-btn" className="text-xs font-mono uppercase tracking-[0.1em] px-3 py-2 border border-[#ff3b30]/40 text-[#ff3b30] hover:bg-[#ff3b30]/10 flex items-center gap-1.5">
                <X size={13} weight="bold" /> cancel
              </button>
            )}
            {job.fail_count > 0 && ["completed", "canceled"].includes(job.status) && (
              <button onClick={() => doAction("retry-failed")} data-testid="retry-btn" className="text-xs font-mono uppercase tracking-[0.1em] px-3 py-2 bg-[#00e5ff] text-black hover:bg-[#00b3cc] flex items-center gap-1.5">
                <ArrowsClockwise size={13} weight="bold" /> retry failed
              </button>
            )}
          </div>
        }
      />
      <div className="p-6 space-y-4">
        <Panel className="p-5">
          <div className="grid grid-cols-2 md:grid-cols-6 gap-6">
            {[
              { l: "status", v: <StatusBadge status={job.status} /> },
              { l: "progress", v: <span className="font-display text-3xl tracking-tighter text-[#00e5ff]">{job.progress}%</span> },
              { l: "completed", v: <span className="font-display text-3xl tracking-tighter">{job.completed_count}/{job.total}</span> },
              { l: "success", v: <span className="font-display text-3xl tracking-tighter text-[#00ff66]">{job.success_count}</span> },
              { l: "failed", v: <span className="font-display text-3xl tracking-tighter text-[#ff3b30]">{job.fail_count}</span> },
              { l: "started", v: <span className="font-mono text-xs text-zinc-300">{job.started_at ? new Date(job.started_at).toISOString().replace("T", " ").slice(0, 19) : "—"}</span> },
            ].map((c) => (
              <div key={c.l}><DataLabel>{c.l}</DataLabel><div className="mt-2">{c.v}</div></div>
            ))}
          </div>
          <div className="mt-5">
            <ProgressLine value={job.progress || 0} active={job.status === "running"} />
          </div>
        </Panel>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          <Panel className="p-0 lg:col-span-3">
            <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
              <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">migration items ({filteredItems.length})</div>
              <div className="flex items-center gap-1">
                {["all", "pending", "success", "failed"].map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    data-testid={`filter-${f}`}
                    className={`text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-1 border ${filter === f ? "border-[#00e5ff] text-[#00e5ff]" : "border-white/10 text-zinc-400"}`}
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>
            <div className="max-h-[520px] overflow-y-auto">
              <table className="w-full text-sm">
                <tbody>
                  {filteredItems.map((it) => (
                    <tr key={it.id} className="border-b border-white/5 row-hover">
                      <td className="px-4 py-2 font-mono text-[11px] text-zinc-500 w-24">{it.id}</td>
                      <td className="px-4 py-2 text-zinc-200 truncate max-w-xs">{it.display_name}</td>
                      <td className="px-4 py-2 w-32"><StatusBadge status={it.status} /></td>
                      <td className="px-4 py-2 font-mono text-[11px] text-[#ff3b30] max-w-md truncate">{it.error || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel className="p-0 lg:col-span-2 scanlines">
            <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between bg-[#0a0a0a]">
              <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-[#00e5ff]">stream :: /var/log/migrate.log</div>
              <span className="w-1.5 h-1.5 bg-[#00ff66] pulse-dot" />
            </div>
            <div className="p-4 h-[520px] overflow-y-auto font-mono text-[11px] leading-relaxed">
              {logs.length === 0 && <div className="text-zinc-600 cursor-blink">awaiting output</div>}
              {logs.map((l) => (
                <div key={l.id} className="flex gap-2">
                  <span className="text-zinc-600 shrink-0">{new Date(l.ts).toISOString().slice(11, 19)}</span>
                  <span className={
                    l.level === "error" ? "text-[#ff3b30]" :
                    l.level === "warn" ? "text-[#ffd600]" : "text-zinc-300"
                  }>
                    [{l.level.toUpperCase()}]
                  </span>
                  <span className="text-zinc-300">{l.message}</span>
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
