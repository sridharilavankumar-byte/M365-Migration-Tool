import { useEffect, useState } from "react";
import TopBar from "@/components/layout/TopBar";
import { Panel, DataLabel, StatusBadge } from "@/components/shared/Primitives";
import { useProject } from "@/context/ProjectContext";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Plus, ArrowRight, Trash, PlugsConnected, X, ShieldCheck, Bell } from "@phosphor-icons/react";
import { toast } from "sonner";
import { Link } from "react-router-dom";

const emptyTenant = { tenant_id: "", domain: "", client_id: "", client_secret: "", label: "" };
const emptyNotif = { email_provider: "resend", email_to: "", webhook_url: "" };

export default function ProjectsPage() {
  const { projects, refresh, select, current } = useProject();
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    source_tenant: { ...emptyTenant, label: "Source" },
    destination_tenant: { ...emptyTenant, label: "Destination" },
    notification_settings: { ...emptyNotif },
  });
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(null);
  const [preflight, setPreflight] = useState(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [savedConnections, setSavedConnections] = useState([]);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/tenant-connections");
        setSavedConnections(data);
      } catch {}
    })();
  }, [showModal]);

  const loadConnectionInto = async (key, connectionId) => {
    if (!connectionId) return;
    try {
      const { data } = await api.get(`/tenant-connections/${connectionId}?reveal=true`);
      setForm((prev) => ({
        ...prev,
        [key]: {
          ...prev[key],
          tenant_id: data.tenant_id || "",
          client_id: data.client_id || "",
          client_secret: data.client_secret || "",
          domain: data.domain || prev[key].domain,
          label: data.label || prev[key].label,
        },
      }));
      toast.success(`Loaded '${data.label}' into ${key === "source_tenant" ? "source" : "destination"}`);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { data } = await api.post("/projects", form);
      toast.success(`Project '${data.name}' created`);
      setShowModal(false);
      setForm({
        name: "", description: "",
        source_tenant: { ...emptyTenant, label: "Source" },
        destination_tenant: { ...emptyTenant, label: "Destination" },
        notification_settings: { ...emptyNotif },
      });
      await refresh();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally { setBusy(false); }
  };

  const testConn = async (projectId) => {
    setTesting(projectId);
    try {
      const { data } = await api.post(`/projects/${projectId}/test-connection`);
      const mode = data.source.mode === "live" ? "LIVE" : "SIM";
      toast.success(`[${mode}] Src ${data.source.latency_ms}ms · Dst ${data.destination.latency_ms}ms`);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally { setTesting(null); }
  };

  const runPreflight = async (projectId) => {
    setPreflightBusy(true);
    try {
      const { data } = await api.post(`/projects/${projectId}/preflight`);
      setPreflight(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally { setPreflightBusy(false); }
  };

  const deleteProject = async (id) => {
    if (!confirm("Delete this project and all its jobs?")) return;
    await api.delete(`/projects/${id}`);
    toast.success("Project deleted");
    await refresh();
  };

  return (
    <>
      <TopBar
        title="Migration Projects"
        subtitle="Source ↔ Destination tenant pairings"
        right={
          <button
            data-testid="new-project-btn"
            onClick={() => setShowModal(true)}
            className="bg-[#00e5ff] hover:bg-[#00b3cc] text-black text-xs font-mono uppercase tracking-[0.1em] px-4 py-2 flex items-center gap-2"
          >
            <Plus size={14} weight="bold" /> New Project
          </button>
        }
      />
      <div className="p-6 space-y-4">
        {projects.length === 0 && (
          <Panel className="p-10 text-center">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-[#00e5ff]">empty</div>
            <div className="font-display text-2xl tracking-tighter mt-2">No projects yet</div>
            <p className="text-sm text-zinc-500 mt-2 max-w-md mx-auto">Create a migration project to pair a source Microsoft 365 tenant with a destination tenant.</p>
          </Panel>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {projects.map((p) => (
            <Panel key={p.id} className={`p-5 ${current?.id === p.id ? "border-[#00e5ff]/60" : ""}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">project</div>
                  <div className="font-display text-xl tracking-tight mt-1 truncate">{p.name}</div>
                  <div className="text-xs text-zinc-500 mt-1 line-clamp-2">{p.description || "—"}</div>
                </div>
                <StatusBadge status={p.status} />
              </div>

              <div className="mt-5 border border-white/10 p-3">
                <div className="grid grid-cols-[1fr_auto_1fr] gap-3 items-center">
                  <div className="min-w-0">
                    <DataLabel>source</DataLabel>
                    <div className="text-sm font-mono text-white truncate mt-1">{p.source_tenant.domain || "—"}</div>
                  </div>
                  <ArrowRight size={14} className="text-[#00e5ff]" />
                  <div className="min-w-0">
                    <DataLabel>destination</DataLabel>
                    <div className="text-sm font-mono text-white truncate mt-1">{p.destination_tenant.domain || "—"}</div>
                  </div>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  data-testid={`select-project-${p.id}`}
                  onClick={() => { select(p); toast.success(`Active project: ${p.name}`); }}
                  className={`text-xs font-mono px-3 py-1.5 border ${current?.id === p.id ? "border-[#00e5ff] text-[#00e5ff] bg-[#00e5ff]/10" : "border-white/20 text-white hover:bg-white/5"}`}
                >
                  {current?.id === p.id ? "◆ active" : "activate"}
                </button>
                <button
                  data-testid={`test-conn-${p.id}`}
                  onClick={() => testConn(p.id)}
                  disabled={testing === p.id}
                  className="text-xs font-mono px-3 py-1.5 border border-white/20 text-white hover:bg-white/5 flex items-center gap-1.5 disabled:opacity-50"
                >
                  <PlugsConnected size={13} />
                  {testing === p.id ? "testing…" : "test conn"}
                </button>
                <Link
                  to={`/app/services/exchange`}
                  onClick={() => select(p)}
                  className="text-xs font-mono px-3 py-1.5 border border-white/20 text-white hover:bg-white/5"
                  data-testid={`start-migrate-${p.id}`}
                >
                  → migrate
                </Link>
                <button
                  onClick={() => { select(p); runPreflight(p.id); }}
                  className="text-xs font-mono px-3 py-1.5 border border-white/20 text-white hover:bg-white/5 flex items-center gap-1.5"
                  data-testid={`preflight-${p.id}`}
                >
                  <ShieldCheck size={13} /> preflight
                </button>
                <button
                  onClick={() => deleteProject(p.id)}
                  className="ml-auto text-xs font-mono px-3 py-1.5 border border-[#ff3b30]/30 text-[#ff3b30] hover:bg-[#ff3b30]/10 flex items-center gap-1.5"
                  data-testid={`delete-project-${p.id}`}
                >
                  <Trash size={13} /> delete
                </button>
              </div>

              <div className="mt-4 pt-4 border-t border-white/5 text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-600">
                created :: {new Date(p.created_at).toISOString().replace("T", " ").slice(0, 19)}
              </div>
            </Panel>
          ))}
        </div>
      </div>

      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <form onSubmit={submit} className="bg-[#0a0a0a] border border-white/15 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#00e5ff]">new project</div>
                <div className="font-display text-2xl tracking-tighter mt-1">Configure Tenants</div>
              </div>
              <button type="button" onClick={() => setShowModal(false)} className="p-2 hover:bg-white/5" data-testid="close-modal">
                <X size={16} />
              </button>
            </div>
            <div className="p-6 space-y-5">
              <div>
                <DataLabel className="mb-2">project name</DataLabel>
                <input
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full bg-[#050505] border border-white/10 px-3 py-2.5 text-sm focus:border-[#00e5ff] focus:outline-none"
                  placeholder="Acme Corp → Contoso Migration"
                  data-testid="project-name-input"
                />
              </div>
              <div>
                <DataLabel className="mb-2">description</DataLabel>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  rows={2}
                  className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm focus:border-[#00e5ff] focus:outline-none"
                  placeholder="Q1 migration for the merged entity…"
                />
              </div>
              {["source_tenant", "destination_tenant"].map((key) => (
                <div key={key} className="border border-white/10 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-[#00e5ff]">
                      {key === "source_tenant" ? "source tenant" : "destination tenant"}
                    </div>
                    {savedConnections.length > 0 && (
                      <select
                        onChange={(e) => { loadConnectionInto(key, e.target.value); e.target.value = ""; }}
                        data-testid={`${key}-load-saved`}
                        defaultValue=""
                        className="text-[10px] font-mono bg-[#050505] border border-white/10 px-2 py-1 text-zinc-300 focus:border-[#00e5ff] focus:outline-none"
                      >
                        <option value="">↓ load from saved…</option>
                        {savedConnections.map((c) => (
                          <option key={c.id} value={c.id}>{c.label}</option>
                        ))}
                      </select>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <DataLabel className="mb-1">domain</DataLabel>
                      <input required value={form[key].domain} onChange={(e) => setForm({ ...form, [key]: { ...form[key], domain: e.target.value } })} className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none" placeholder="contoso.onmicrosoft.com" data-testid={`${key}-domain`} />
                    </div>
                    <div>
                      <DataLabel className="mb-1">tenant id</DataLabel>
                      <input value={form[key].tenant_id} onChange={(e) => setForm({ ...form, [key]: { ...form[key], tenant_id: e.target.value } })} className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none" placeholder="00000000-0000-0000-0000-000000000000" />
                    </div>
                    <div>
                      <DataLabel className="mb-1">client id</DataLabel>
                      <input value={form[key].client_id} onChange={(e) => setForm({ ...form, [key]: { ...form[key], client_id: e.target.value } })} className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none" />
                    </div>
                    <div>
                      <DataLabel className="mb-1">client secret</DataLabel>
                      <input type="password" value={form[key].client_secret} onChange={(e) => setForm({ ...form, [key]: { ...form[key], client_secret: e.target.value } })} className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none" />
                    </div>
                  </div>
                </div>
              ))}

              <div className="border border-white/10 p-4">
                <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-[#00e5ff] mb-3 flex items-center gap-2">
                  <Bell size={12} /> notifications on job completion
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <DataLabel className="mb-1">email provider</DataLabel>
                    <select
                      value={form.notification_settings.email_provider}
                      onChange={(e) => setForm({ ...form, notification_settings: { ...form.notification_settings, email_provider: e.target.value } })}
                      data-testid="notif-provider"
                      className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-xs font-mono focus:border-[#00e5ff] focus:outline-none"
                    >
                      <option value="">— none —</option>
                      <option value="resend">resend</option>
                      <option value="sendgrid">sendgrid</option>
                    </select>
                  </div>
                  <div>
                    <DataLabel className="mb-1">email to</DataLabel>
                    <input
                      type="email"
                      value={form.notification_settings.email_to}
                      onChange={(e) => setForm({ ...form, notification_settings: { ...form.notification_settings, email_to: e.target.value } })}
                      className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-xs font-mono focus:border-[#00e5ff] focus:outline-none"
                      placeholder="ops@company.com"
                      data-testid="notif-email"
                    />
                  </div>
                  <div className="col-span-2">
                    <DataLabel className="mb-1">webhook url (optional)</DataLabel>
                    <input
                      value={form.notification_settings.webhook_url}
                      onChange={(e) => setForm({ ...form, notification_settings: { ...form.notification_settings, webhook_url: e.target.value } })}
                      className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-xs font-mono focus:border-[#00e5ff] focus:outline-none"
                      placeholder="https://hooks.example.com/…"
                      data-testid="notif-webhook"
                    />
                  </div>
                </div>
              </div>
            </div>
            <div className="px-6 py-4 border-t border-white/10 flex justify-end gap-3">
              <button type="button" onClick={() => setShowModal(false)} className="text-xs font-mono px-4 py-2 border border-white/20 hover:bg-white/5">cancel</button>
              <button type="submit" disabled={busy} className="text-xs font-mono px-4 py-2 bg-[#00e5ff] hover:bg-[#00b3cc] text-black disabled:opacity-50" data-testid="submit-project-btn">
                {busy ? "creating…" : "create project"}
              </button>
            </div>
          </form>
        </div>
      )}

      {(preflight || preflightBusy) && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <div className="bg-[#0a0a0a] border border-white/15 w-full max-w-2xl">
            <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#00e5ff]">pre-flight</div>
                <div className="font-display text-2xl tracking-tighter mt-1">Destination Readiness</div>
              </div>
              <button onClick={() => setPreflight(null)} className="p-2 hover:bg-white/5" data-testid="close-preflight">
                <X size={16} />
              </button>
            </div>
            <div className="p-6">
              {preflightBusy && !preflight && (
                <div className="font-mono text-xs text-zinc-500 cursor-blink">running pre-flight checks</div>
              )}
              {preflight && (
                <>
                  <div className="flex items-center gap-3 mb-4">
                    <DataLabel>overall</DataLabel>
                    <span className={`text-xs font-mono uppercase tracking-[0.1em] px-2 py-0.5 border ${preflight.overall === "pass" ? "border-[#00ff66]/40 text-[#00ff66] bg-[#00ff66]/10" : "border-[#ff3b30]/40 text-[#ff3b30] bg-[#ff3b30]/10"}`}>
                      {preflight.overall}
                    </span>
                    <span className="ml-auto text-[10px] font-mono text-zinc-500">{new Date(preflight.ran_at).toISOString().slice(0, 19).replace("T", " ")}</span>
                  </div>
                  <div className="border border-white/10 divide-y divide-white/5">
                    {preflight.checks.map((c, i) => (
                      <div key={i} className="px-4 py-3 flex items-center gap-3">
                        <span className={
                          c.status === "pass" ? "w-1.5 h-1.5 bg-[#00ff66]" :
                          c.status === "warn" ? "w-1.5 h-1.5 bg-[#ffd600]" :
                          c.status === "info" ? "w-1.5 h-1.5 bg-[#00e5ff]" :
                          "w-1.5 h-1.5 bg-[#ff3b30]"
                        } />
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-white">{c.name}</div>
                          <div className="text-[11px] font-mono text-zinc-500 mt-0.5 truncate">{c.detail}</div>
                        </div>
                        <span className="text-[10px] font-mono uppercase tracking-[0.1em] text-zinc-400">{c.status}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

    </>
  );
}
