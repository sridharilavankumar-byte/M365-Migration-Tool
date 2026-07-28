import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import TopBar from "@/components/layout/TopBar";
import { Panel, DataLabel, StatusBadge, ProgressLine } from "@/components/shared/Primitives";
import { api } from "@/lib/api";
import { useProject } from "@/context/ProjectContext";
import { toast } from "sonner";

export default function JobsPage() {
  const [jobs, setJobs] = useState([]);
  const { current } = useProject();

  const load = async () => {
    const { data } = await api.get("/jobs");
    setJobs(data);
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, []);

  return (
    <>
      <TopBar title="Job Queue" subtitle="All migration jobs across projects" />
      <div className="p-6">
        <Panel className="p-0">
          <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">{jobs.length} jobs</div>
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 bg-[#00ff66] pulse-dot" />
              <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">auto-refresh 2s</span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-[#0a0a0a]">
                  {["Job ID", "Project", "Service", "Mode", "Progress", "Success", "Failed", "Status", "Started", ""].map((h) => (
                    <th key={h} className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 px-4 py-2 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {jobs.length === 0 && (
                  <tr><td colSpan={10} className="text-center py-10 text-sm text-zinc-500 font-mono">no jobs yet</td></tr>
                )}
                {jobs.map((j) => (
                  <tr key={j.id} className="border-b border-white/5 row-hover" data-testid={`job-row-${j.id}`}>
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-400">{j.id.slice(-8)}</td>
                    <td className="px-4 py-2.5 text-zinc-200">{j.project_name}</td>
                    <td className="px-4 py-2.5 font-mono text-xs">{j.service_type}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-400">{j.mode}</td>
                    <td className="px-4 py-2.5 w-56">
                      <div className="flex items-center gap-2">
                        <ProgressLine value={j.progress || 0} active={j.status === "running"} />
                        <span className="font-mono text-xs text-zinc-400 w-10 text-right">{j.progress || 0}%</span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-[#00ff66]">{j.success_count}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-[#ff3b30]">{j.fail_count}</td>
                    <td className="px-4 py-2.5"><StatusBadge status={j.status} /></td>
                    <td className="px-4 py-2.5 font-mono text-[10px] text-zinc-500">{j.started_at ? new Date(j.started_at).toISOString().replace("T", " ").slice(5, 19) : "—"}</td>
                    <td className="px-4 py-2.5"><Link to={`/app/jobs/${j.id}`} className="text-[10px] font-mono text-[#00e5ff] hover:underline">open →</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </>
  );
}
