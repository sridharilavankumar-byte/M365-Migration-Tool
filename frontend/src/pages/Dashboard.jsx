import { useEffect, useState } from "react";
import TopBar from "@/components/layout/TopBar";
import { api } from "@/lib/api";
import { Panel, DataLabel, StatusBadge, ProgressLine } from "@/components/shared/Primitives";
import { useProject } from "@/context/ProjectContext";
import { Link, useNavigate } from "react-router-dom";
import { Envelope, Cloud, HardDrives, UsersFour, ChatCircleDots, IdentificationBadge, AddressBook, CalendarBlank, Folder } from "@phosphor-icons/react";

const SERVICE_META = {
  exchange: { name: "Exchange", icon: Envelope },
  sharepoint: { name: "SharePoint", icon: Cloud },
  onedrive: { name: "OneDrive", icon: HardDrives },
  distribution_lists: { name: "Distribution Lists", icon: UsersFour },
  teams: { name: "Teams", icon: ChatCircleDots },
  groups: { name: "M365 Groups", icon: IdentificationBadge },
  contacts: { name: "Contacts", icon: AddressBook },
  calendars: { name: "Calendars", icon: CalendarBlank },
  public_folders: { name: "Public Folders", icon: Folder },
};

export default function Dashboard() {
  const { current, projects } = useProject();
  const [stats, setStats] = useState(null);
  const nav = useNavigate();

  const load = async () => {
    const { data } = await api.get("/dashboard/stats");
    setStats(data);
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  const metrics = [
    { label: "projects", value: stats?.total_projects ?? "—", accent: false },
    { label: "active jobs", value: stats?.running_jobs ?? "—", accent: true },
    { label: "items migrated", value: (stats?.items_success ?? 0).toLocaleString(), accent: false },
    { label: "items failed", value: (stats?.items_failed ?? 0).toLocaleString(), accent: false, danger: (stats?.items_failed ?? 0) > 0 },
  ];

  return (
    <>
      <TopBar title="Command Center" subtitle="Real-time migration telemetry" />
      <div className="p-6 space-y-4">
        {projects.length === 0 && (
          <Panel className="p-8 text-center">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-[#00e5ff]">no projects</div>
            <div className="font-display text-2xl tracking-tighter mt-2">Create your first migration project</div>
            <p className="text-sm text-zinc-500 mt-2">Configure a source tenant and destination tenant to begin.</p>
            <Link
              to="/app/projects"
              data-testid="cta-create-project"
              className="inline-block mt-6 bg-[#00e5ff] hover:bg-[#00b3cc] text-black text-sm px-5 py-2.5"
            >
              → Create Project
            </Link>
          </Panel>
        )}

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {metrics.map((m) => (
            <Panel key={m.label} className="p-5">
              <DataLabel>{m.label}</DataLabel>
              <div className={`font-display text-4xl tracking-tighter mt-2 ${m.accent ? "text-[#00e5ff]" : m.danger ? "text-[#ff3b30]" : "text-white"}`}>
                {m.value}
              </div>
              <div className="mt-3">
                <ProgressLine value={m.accent ? 60 : 0} active={m.accent} />
              </div>
            </Panel>
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Panel className="lg:col-span-2 p-0">
            <div className="px-5 py-3 border-b border-white/10 flex items-center justify-between">
              <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">recent jobs</div>
              <Link to="/app/jobs" className="text-[10px] font-mono uppercase tracking-[0.15em] text-[#00e5ff] hover:text-white" data-testid="link-all-jobs">
                view all →
              </Link>
            </div>
            <div className="divide-y divide-white/5">
              {(stats?.recent_jobs || []).length === 0 && (
                <div className="p-6 text-center text-sm text-zinc-500 font-mono">no jobs yet</div>
              )}
              {(stats?.recent_jobs || []).map((j) => {
                const meta = SERVICE_META[j.service_type] || { name: j.service_type, icon: Envelope };
                const Icon = meta.icon;
                return (
                  <button
                    key={j.id}
                    onClick={() => nav(`/app/jobs/${j.id}`)}
                    data-testid={`recent-job-${j.id}`}
                    className="w-full text-left px-5 py-3 hover:bg-white/[0.02] flex items-center gap-4"
                  >
                    <Icon size={18} className="text-zinc-400" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-white truncate">{meta.name} · {j.project_name}</div>
                      <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 mt-0.5">
                        {j.completed_count}/{j.total} · {j.success_count} ok · {j.fail_count} err
                      </div>
                    </div>
                    <div className="w-40">
                      <ProgressLine value={j.progress || 0} active={j.status === "running"} />
                    </div>
                    <StatusBadge status={j.status} />
                  </button>
                );
              })}
            </div>
          </Panel>

          <Panel className="p-0 scanlines">
            <div className="px-5 py-3 border-b border-white/10 flex items-center justify-between">
              <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">service telemetry</div>
              <span className="w-1.5 h-1.5 bg-[#00ff66] pulse-dot" />
            </div>
            <div className="p-5 space-y-3">
              {Object.entries(SERVICE_META).map(([key, meta]) => {
                const rec = (stats?.by_service || []).find((s) => s._id === key);
                const success = rec?.success || 0;
                const failed = rec?.failed || 0;
                const total = success + failed;
                const pct = total > 0 ? Math.round((success / total) * 100) : 0;
                const Icon = meta.icon;
                return (
                  <div key={key} className="flex items-center gap-3">
                    <Icon size={14} className="text-zinc-400 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-zinc-300 truncate">{meta.name}</div>
                      <div className="text-[10px] font-mono text-zinc-500 mt-0.5">
                        {success} ok · {failed} err
                      </div>
                    </div>
                    <div className="text-[10px] font-mono text-zinc-400 w-8 text-right">{pct}%</div>
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
