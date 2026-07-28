import { useEffect, useState } from "react";
import TopBar from "@/components/layout/TopBar";
import { Panel, DataLabel, StatusBadge } from "@/components/shared/Primitives";
import { useProject } from "@/context/ProjectContext";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Plus, X, Play, Trash, Clock } from "@phosphor-icons/react";
import { useNavigate } from "react-router-dom";

const SERVICES = [
  "exchange", "sharepoint", "onedrive", "distribution_lists",
  "teams", "groups", "contacts", "calendars", "public_folders",
];

const CRON_PRESETS = [
  { label: "Every 5 minutes",  cron: "*/5 * * * *" },
  { label: "Hourly",           cron: "0 * * * *" },
  { label: "Daily at 02:00",   cron: "0 2 * * *" },
  { label: "Weekly Sun 02:00", cron: "0 2 * * 0" },
  { label: "Monthly 1st 03:00", cron: "0 3 1 * *" },
];

export default function SchedulesPage() {
  const { projects, current } = useProject();
  const [schedules, setSchedules] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({
    project_id: current?.id || "",
    service_type: "exchange",
    item_ids: [],
    mode: "full",
    concurrency: 3,
    trigger_type: "cron",
    cron: "0 2 * * *",
    run_at: "",
  });
  const nav = useNavigate();

  const load = async () => {
    const { data } = await api.get("/schedules");
    setSchedules(data);
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!showModal) return;
    if (!form.project_id || !form.service_type) return;
    (async () => {
      try {
        const { data } = await api.get(`/services/${form.service_type}/discover`, { params: { project_id: form.project_id } });
        setItems(data.items);
      } catch (err) {
        toast.error(formatApiErrorDetail(err.response?.data?.detail));
      }
    })();
  }, [showModal, form.project_id, form.service_type]);

  const submit = async (e) => {
    e.preventDefault();
    if (form.item_ids.length === 0) return toast.error("Select at least one item");
    if (form.trigger_type === "one_shot" && !form.run_at) return toast.error("Pick a run time");
    setBusy(true);
    try {
      const body = { ...form };
      if (form.trigger_type === "one_shot" && form.run_at) {
        body.run_at = new Date(form.run_at).toISOString();
        delete body.cron;
      } else {
        delete body.run_at;
      }
      const { data } = await api.post("/schedules", body);
      toast.success(`Schedule created — next run ${new Date(data.next_run_at).toISOString().slice(0, 19).replace("T", " ")}`);
      setShowModal(false);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally { setBusy(false); }
  };

  const toggle = async (id) => {
    const { data } = await api.put(`/schedules/${id}/toggle`);
    toast.success(data.enabled ? "Enabled" : "Disabled");
    await load();
  };
  const del = async (id) => {
    if (!confirm("Delete this schedule?")) return;
    await api.delete(`/schedules/${id}`);
    toast.success("Deleted");
    await load();
  };
  const runNow = async (id) => {
    const { data } = await api.post(`/schedules/${id}/run-now`);
    toast.success("Dispatched");
    if (data.job_id) nav(`/app/jobs/${data.job_id}`);
  };

  const toggleItem = (id) => {
    const set = new Set(form.item_ids);
    set.has(id) ? set.delete(id) : set.add(id);
    setForm({ ...form, item_ids: Array.from(set) });
  };

  return (
    <>
      <TopBar
        title="Scheduled Migrations"
        subtitle="Cron and one-shot triggers"
        right={
          <button
            data-testid="new-schedule-btn"
            onClick={() => { setForm({ ...form, project_id: current?.id || (projects[0]?.id ?? "") }); setShowModal(true); }}
            className="bg-[#00e5ff] hover:bg-[#00b3cc] text-black text-xs font-mono uppercase tracking-[0.1em] px-4 py-2 flex items-center gap-2"
          >
            <Plus size={14} weight="bold" /> New Schedule
          </button>
        }
      />
      <div className="p-6">
        <Panel className="p-0">
          <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">{schedules.length} schedules</div>
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 bg-[#00ff66] pulse-dot" />
              <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">scheduler online · tick 15s</span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-[#0a0a0a]">
                  {["Project", "Service", "Mode", "Trigger", "Next Run", "Last Job", "Status", ""].map((h) => (
                    <th key={h} className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 px-4 py-2 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {schedules.length === 0 && (
                  <tr><td colSpan={8} className="text-center py-10 text-sm text-zinc-500 font-mono">no schedules yet</td></tr>
                )}
                {schedules.map((s) => (
                  <tr key={s.id} className="border-b border-white/5 row-hover" data-testid={`schedule-row-${s.id}`}>
                    <td className="px-4 py-2.5 text-zinc-200">{s.project_name}</td>
                    <td className="px-4 py-2.5 font-mono text-xs">{s.service_type}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-400">{s.mode}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-300">
                      {s.trigger_type === "cron" ? <>cron · <span className="text-[#00e5ff]">{s.cron}</span></> : <>one-shot</>}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-[11px] text-zinc-400">
                      {s.next_run_at ? new Date(s.next_run_at).toISOString().replace("T", " ").slice(0, 19) : "—"}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-[11px] text-zinc-400">
                      {s.last_job_id
                        ? <a href={`/app/jobs/${s.last_job_id}`} className="text-[#00e5ff] hover:underline">{s.last_job_id.slice(-8)}</a>
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5"><StatusBadge status={s.enabled ? "running" : "canceled"} /></td>
                    <td className="px-4 py-2.5 flex gap-1">
                      <button onClick={() => runNow(s.id)} data-testid={`run-now-${s.id}`} className="text-[10px] font-mono px-2 py-1 border border-white/20 hover:bg-white/5 flex items-center gap-1">
                        <Play size={11} weight="fill" /> run
                      </button>
                      <button onClick={() => toggle(s.id)} data-testid={`toggle-${s.id}`} className="text-[10px] font-mono px-2 py-1 border border-white/20 hover:bg-white/5">
                        {s.enabled ? "pause" : "enable"}
                      </button>
                      <button onClick={() => del(s.id)} data-testid={`del-${s.id}`} className="text-[10px] font-mono px-2 py-1 border border-[#ff3b30]/30 text-[#ff3b30] hover:bg-[#ff3b30]/10">
                        <Trash size={11} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <form onSubmit={submit} className="bg-[#0a0a0a] border border-white/15 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#00e5ff]">new schedule</div>
                <div className="font-display text-2xl tracking-tighter mt-1 flex items-center gap-2">
                  <Clock size={20} /> Schedule Migration
                </div>
              </div>
              <button type="button" onClick={() => setShowModal(false)} className="p-2 hover:bg-white/5">
                <X size={16} />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <DataLabel className="mb-1">project</DataLabel>
                  <select
                    value={form.project_id}
                    onChange={(e) => setForm({ ...form, project_id: e.target.value })}
                    data-testid="sched-project"
                    className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none"
                  >
                    {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </div>
                <div>
                  <DataLabel className="mb-1">service</DataLabel>
                  <select
                    value={form.service_type}
                    onChange={(e) => setForm({ ...form, service_type: e.target.value, item_ids: [] })}
                    data-testid="sched-service"
                    className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none"
                  >
                    {SERVICES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <DataLabel className="mb-1">mode</DataLabel>
                  <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })} className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none">
                    <option value="full">full</option>
                    <option value="incremental">incremental</option>
                    <option value="delta">delta</option>
                  </select>
                </div>
                <div>
                  <DataLabel className="mb-1">concurrency</DataLabel>
                  <select value={form.concurrency} onChange={(e) => setForm({ ...form, concurrency: parseInt(e.target.value, 10) })} className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none">
                    {[1, 2, 3, 5, 8, 10].map((n) => <option key={n} value={n}>{n}×</option>)}
                  </select>
                </div>
              </div>

              <div className="border border-white/10 p-4 space-y-3">
                <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-[#00e5ff]">trigger</div>
                <div className="flex gap-2">
                  {["cron", "one_shot"].map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setForm({ ...form, trigger_type: t })}
                      data-testid={`trigger-${t}`}
                      className={`text-xs font-mono px-3 py-1.5 border ${form.trigger_type === t ? "border-[#00e5ff] text-[#00e5ff] bg-[#00e5ff]/10" : "border-white/20 text-white"}`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
                {form.trigger_type === "cron" ? (
                  <>
                    <div>
                      <DataLabel className="mb-1">cron expression</DataLabel>
                      <input
                        value={form.cron}
                        onChange={(e) => setForm({ ...form, cron: e.target.value })}
                        data-testid="sched-cron"
                        className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none"
                        placeholder="0 2 * * *"
                      />
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {CRON_PRESETS.map((p) => (
                        <button key={p.cron} type="button" onClick={() => setForm({ ...form, cron: p.cron })}
                          className="text-[10px] font-mono px-2 py-1 border border-white/10 hover:border-white/30">
                          {p.label} <span className="text-zinc-500">({p.cron})</span>
                        </button>
                      ))}
                    </div>
                  </>
                ) : (
                  <div>
                    <DataLabel className="mb-1">run at (local time)</DataLabel>
                    <input
                      type="datetime-local"
                      value={form.run_at}
                      onChange={(e) => setForm({ ...form, run_at: e.target.value })}
                      data-testid="sched-run-at"
                      className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none"
                    />
                  </div>
                )}
              </div>

              <div className="border border-white/10">
                <div className="px-4 py-2 border-b border-white/10 flex items-center justify-between">
                  <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">
                    {form.item_ids.length} of {items.length} selected
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      if (form.item_ids.length === items.length) setForm({ ...form, item_ids: [] });
                      else setForm({ ...form, item_ids: items.map((it) => it.id) });
                    }}
                    className="text-[10px] font-mono px-2 py-1 border border-white/20 hover:bg-white/5"
                  >
                    {form.item_ids.length === items.length && items.length > 0 ? "clear" : "select all"}
                  </button>
                </div>
                <div className="max-h-56 overflow-y-auto text-sm">
                  {items.length === 0 && <div className="p-4 text-xs font-mono text-zinc-500">discover…</div>}
                  {items.map((it) => (
                    <label key={it.id} className="flex items-center gap-3 px-4 py-1.5 hover:bg-white/[0.02] cursor-pointer">
                      <input
                        type="checkbox"
                        checked={form.item_ids.includes(it.id)}
                        onChange={() => toggleItem(it.id)}
                        className="accent-[#00e5ff]"
                      />
                      <span className="text-xs text-zinc-200 truncate">{it.display_name}</span>
                      <span className="text-[10px] font-mono text-zinc-500 ml-auto">{it.id}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <div className="px-6 py-4 border-t border-white/10 flex justify-end gap-3">
              <button type="button" onClick={() => setShowModal(false)} className="text-xs font-mono px-4 py-2 border border-white/20 hover:bg-white/5">cancel</button>
              <button type="submit" disabled={busy} className="text-xs font-mono px-4 py-2 bg-[#00e5ff] hover:bg-[#00b3cc] text-black disabled:opacity-50" data-testid="submit-schedule">
                {busy ? "creating…" : "create schedule"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
