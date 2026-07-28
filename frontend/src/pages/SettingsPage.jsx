import { useEffect, useState } from "react";
import TopBar from "@/components/layout/TopBar";
import { Panel, DataLabel } from "@/components/shared/Primitives";
import { useAuth } from "@/context/AuthContext";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash, PlugsConnected, X, Pencil, Key } from "@phosphor-icons/react";

const emptyForm = {
  label: "",
  domain: "",
  tenant_id: "",
  client_id: "",
  client_secret: "",
  notes: "",
};

export default function SettingsPage() {
  const { user } = useAuth();
  const [connections, setConnections] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(null);

  const load = async () => {
    const { data } = await api.get("/tenant-connections");
    setConnections(data);
  };
  useEffect(() => { load(); }, []);

  const openNew = () => { setEditingId(null); setForm(emptyForm); setShowModal(true); };
  const openEdit = async (id) => {
    const { data } = await api.get(`/tenant-connections/${id}`);
    setEditingId(id);
    setForm({
      label: data.label || "",
      domain: data.domain || "",
      tenant_id: data.tenant_id || "",
      client_id: data.client_id || "",
      client_secret: "",  // don't reveal in UI; empty means "keep existing"
      notes: data.notes || "",
    });
    setShowModal(true);
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (editingId) {
        await api.put(`/tenant-connections/${editingId}`, form);
        toast.success("Connection updated");
      } else {
        await api.post("/tenant-connections", form);
        toast.success("Connection saved");
      }
      setShowModal(false);
      setForm(emptyForm);
      setEditingId(null);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally { setBusy(false); }
  };

  const del = async (id) => {
    if (!confirm("Delete this saved connection?")) return;
    await api.delete(`/tenant-connections/${id}`);
    toast.success("Deleted");
    await load();
  };

  const test = async (id) => {
    setTesting(id);
    try {
      const { data } = await api.post(`/tenant-connections/${id}/test`);
      if (data.ok) {
        toast.success(`[${data.mode?.toUpperCase()}] ${data.latency_ms}ms — ${data.message || "OK"}`);
      } else {
        toast.error(data.message || "connection test failed");
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally { setTesting(null); }
  };

  return (
    <>
      <TopBar title="Settings" subtitle="Operator profile, tenant credentials, and system config" />
      <div className="p-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Panel className="p-6">
            <DataLabel>operator profile</DataLabel>
            <div className="mt-4 space-y-3 text-sm">
              <div><span className="text-zinc-500 font-mono text-[10px] uppercase tracking-wider block mb-1">name</span><span className="text-white">{user?.name}</span></div>
              <div><span className="text-zinc-500 font-mono text-[10px] uppercase tracking-wider block mb-1">email</span><span className="text-white font-mono text-xs">{user?.email}</span></div>
              <div><span className="text-zinc-500 font-mono text-[10px] uppercase tracking-wider block mb-1">role</span><span className="text-white font-mono text-xs">{user?.role}</span></div>
            </div>
          </Panel>
          <Panel className="p-6">
            <DataLabel>system</DataLabel>
            <div className="mt-4 space-y-3 text-sm">
              <div><span className="text-zinc-500 font-mono text-[10px] uppercase tracking-wider block mb-1">migration engine</span><span className="text-white font-mono text-xs">MSAL Graph adapter · simulated fallback</span></div>
              <div><span className="text-zinc-500 font-mono text-[10px] uppercase tracking-wider block mb-1">graph auth</span><span className="text-white font-mono text-xs">app-only client credentials</span></div>
              <div><span className="text-zinc-500 font-mono text-[10px] uppercase tracking-wider block mb-1">version</span><span className="text-white font-mono text-xs">1.2.0</span></div>
            </div>
          </Panel>
        </div>

        <Panel className="p-0">
          <div className="px-5 py-3 border-b border-white/10 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Key size={14} className="text-[#00e5ff]" />
              <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">tenant credentials · azure ad app registrations</div>
            </div>
            <button
              onClick={openNew}
              data-testid="new-connection-btn"
              className="text-xs font-mono uppercase tracking-[0.1em] px-3 py-1.5 bg-[#00e5ff] hover:bg-[#00b3cc] text-black flex items-center gap-1.5"
            >
              <Plus size={13} weight="bold" /> Add connection
            </button>
          </div>
          <div className="p-5">
            {connections.length === 0 ? (
              <div className="text-center py-8 text-sm text-zinc-500">
                <div className="font-mono text-[10px] uppercase tracking-[0.15em]">empty</div>
                <div className="mt-2">No saved tenant connections yet.</div>
                <div className="text-xs text-zinc-600 mt-2 max-w-md mx-auto">
                  Add your source and destination Azure AD app registrations here to reuse them across all migration projects.
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {connections.map((c) => (
                  <div key={c.id} className="border border-white/10 p-4" data-testid={`conn-card-${c.id}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm text-white truncate">{c.label}</div>
                        <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 mt-1">{c.domain || "no domain"}</div>
                      </div>
                    </div>
                    <div className="mt-3 space-y-1 text-[11px] font-mono">
                      <div className="flex gap-2"><span className="text-zinc-500 w-20">tenant_id</span><span className="text-zinc-300 truncate">{c.tenant_id || "—"}</span></div>
                      <div className="flex gap-2"><span className="text-zinc-500 w-20">client_id</span><span className="text-zinc-300 truncate">{c.client_id || "—"}</span></div>
                      <div className="flex gap-2"><span className="text-zinc-500 w-20">secret</span><span className="text-zinc-300">{c.client_secret_masked || "—"}</span></div>
                    </div>
                    {c.notes && <div className="mt-2 text-[11px] text-zinc-500 italic line-clamp-2">{c.notes}</div>}
                    <div className="mt-4 flex gap-2">
                      <button
                        onClick={() => test(c.id)}
                        disabled={testing === c.id}
                        data-testid={`test-conn-${c.id}`}
                        className="text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-1 border border-white/20 hover:bg-white/5 flex items-center gap-1 disabled:opacity-40"
                      >
                        <PlugsConnected size={11} />
                        {testing === c.id ? "testing…" : "test"}
                      </button>
                      <button
                        onClick={() => openEdit(c.id)}
                        data-testid={`edit-conn-${c.id}`}
                        className="text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-1 border border-white/20 hover:bg-white/5 flex items-center gap-1"
                      >
                        <Pencil size={11} /> edit
                      </button>
                      <button
                        onClick={() => del(c.id)}
                        data-testid={`del-conn-${c.id}`}
                        className="ml-auto text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-1 border border-[#ff3b30]/30 text-[#ff3b30] hover:bg-[#ff3b30]/10 flex items-center gap-1"
                      >
                        <Trash size={11} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Panel>

        <Panel className="p-6">
          <DataLabel>Required application permissions</DataLabel>
          <div className="mt-3 text-xs text-zinc-400">
            Register an app in each Azure AD tenant and grant admin consent for these Graph <span className="text-[#00e5ff]">application</span> permissions:
          </div>
          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2 font-mono text-[11px]">
            {["User.Read.All", "Mail.ReadWrite", "Sites.FullControl.All", "Files.ReadWrite.All", "Group.ReadWrite.All", "Directory.Read.All", "Team.ReadBasic.All", "TeamMember.ReadWrite.All"].map((s) => (
              <span key={s} className="border border-white/10 px-2 py-1 text-zinc-300">{s}</span>
            ))}
          </div>
          <p className="text-[11px] text-zinc-500 mt-3">
            After saving a connection, use the <span className="text-white">Test</span> button to verify the token acquisition. Green = MSAL got an app-only access token from Microsoft.
          </p>
        </Panel>

        <Panel className="p-6">
          <DataLabel>notification providers</DataLabel>
          <div className="mt-3 text-xs text-zinc-500">
            Configure email + webhook recipients per project (Projects → New Project → Notifications).
            Global API keys must be set in <code className="text-[#00e5ff]">backend/.env</code>:
          </div>
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
            {[
              { name: "Resend", env: "RESEND_API_KEY", detail: "get key at resend.com/api-keys" },
              { name: "SendGrid", env: "SENDGRID_API_KEY", detail: "get key at app.sendgrid.com" },
              { name: "Webhooks", env: "(per project)", detail: "POST job.completed payload to any URL" },
            ].map((p) => (
              <div key={p.name} className="border border-white/10 p-4">
                <div className="text-sm text-white">{p.name}</div>
                <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 mt-2">env :: {p.env}</div>
                <div className="text-[11px] font-mono text-zinc-500 mt-2">{p.detail}</div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <form onSubmit={submit} className="bg-[#0a0a0a] border border-white/15 w-full max-w-xl max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#00e5ff]">{editingId ? "edit" : "new"} connection</div>
                <div className="font-display text-2xl tracking-tighter mt-1 flex items-center gap-2">
                  <Key size={20} /> Azure AD Credentials
                </div>
              </div>
              <button type="button" onClick={() => setShowModal(false)} className="p-2 hover:bg-white/5" data-testid="close-conn-modal">
                <X size={16} />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <DataLabel className="mb-2">label *</DataLabel>
                <input
                  required
                  value={form.label}
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                  data-testid="conn-label"
                  className="w-full bg-[#050505] border border-white/10 px-3 py-2.5 text-sm focus:border-[#00e5ff] focus:outline-none"
                  placeholder="Contoso Source Prod"
                />
              </div>
              <div>
                <DataLabel className="mb-2">primary domain</DataLabel>
                <input
                  value={form.domain}
                  onChange={(e) => setForm({ ...form, domain: e.target.value })}
                  data-testid="conn-domain"
                  className="w-full bg-[#050505] border border-white/10 px-3 py-2.5 text-sm font-mono focus:border-[#00e5ff] focus:outline-none"
                  placeholder="contoso.onmicrosoft.com"
                />
              </div>
              <div className="grid grid-cols-1 gap-3">
                <div>
                  <DataLabel className="mb-1">tenant id *</DataLabel>
                  <input
                    required
                    value={form.tenant_id}
                    onChange={(e) => setForm({ ...form, tenant_id: e.target.value })}
                    data-testid="conn-tenant-id"
                    className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none"
                    placeholder="00000000-0000-0000-0000-000000000000"
                  />
                </div>
                <div>
                  <DataLabel className="mb-1">client id *</DataLabel>
                  <input
                    required
                    value={form.client_id}
                    onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                    data-testid="conn-client-id"
                    className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none"
                    placeholder="00000000-0000-0000-0000-000000000000"
                  />
                </div>
                <div>
                  <DataLabel className="mb-1">client secret {editingId && <span className="text-zinc-600 normal-case">(leave blank to keep existing)</span>}</DataLabel>
                  <input
                    type="password"
                    value={form.client_secret}
                    onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
                    data-testid="conn-client-secret"
                    className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none"
                    placeholder={editingId ? "•••••••• (unchanged)" : "paste value from Azure Portal → Certificates & secrets"}
                  />
                </div>
              </div>
              <div>
                <DataLabel className="mb-1">notes (optional)</DataLabel>
                <textarea
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  rows={2}
                  className="w-full bg-[#050505] border border-white/10 px-3 py-2 text-sm focus:border-[#00e5ff] focus:outline-none"
                  placeholder="e.g. Source for Q1 acquisition · secret rotates 2026-06-01"
                />
              </div>
              <div className="text-[11px] font-mono text-zinc-500 border border-white/10 p-3">
                <span className="text-[#00e5ff]">tip ::</span> the app registration must have admin-consented application permissions for User.Read.All, Mail.ReadWrite, Sites.FullControl.All, Files.ReadWrite.All, Group.ReadWrite.All
              </div>
            </div>
            <div className="px-6 py-4 border-t border-white/10 flex justify-end gap-3">
              <button type="button" onClick={() => setShowModal(false)} className="text-xs font-mono px-4 py-2 border border-white/20 hover:bg-white/5">cancel</button>
              <button type="submit" disabled={busy} className="text-xs font-mono px-4 py-2 bg-[#00e5ff] hover:bg-[#00b3cc] text-black disabled:opacity-50" data-testid="submit-connection">
                {busy ? "saving…" : editingId ? "update" : "save connection"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
