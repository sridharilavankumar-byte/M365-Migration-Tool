import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import TopBar from "@/components/layout/TopBar";
import { Panel, DataLabel, StatusBadge } from "@/components/shared/Primitives";
import { useProject } from "@/context/ProjectContext";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import {
  Envelope, Cloud, HardDrives, UsersFour, ChatCircleDots,
  IdentificationBadge, AddressBook, CalendarBlank, Folder,
  MagnifyingGlass, Play, ArrowsClockwise, ArrowRight,
} from "@phosphor-icons/react";

const SERVICE_CONFIG = {
  exchange: {
    name: "Exchange Mailboxes",
    icon: Envelope,
    description: "Discover and migrate user mailboxes, including inbox, sent items, folders, rules and permissions.",
    columns: [
      { key: "display_name", label: "Display Name" },
      { key: "primary_smtp", label: "Primary SMTP", mono: true },
      { key: "mailbox_size_gb", label: "Size (GB)", mono: true, right: true },
      { key: "item_count", label: "Items", mono: true, right: true, format: (v) => (v ?? 0).toLocaleString() },
    ],
  },
  sharepoint: {
    name: "SharePoint Sites",
    icon: Cloud,
    description: "Migrate site collections including lists, libraries, permissions and web parts.",
    columns: [
      { key: "display_name", label: "Site Name" },
      { key: "url", label: "URL", mono: true },
      { key: "storage_gb", label: "Storage (GB)", mono: true, right: true },
      { key: "template", label: "Template" },
    ],
  },
  onedrive: {
    name: "OneDrive for Business",
    icon: HardDrives,
    description: "Move personal file libraries including folder structures, versions and sharing permissions.",
    columns: [
      { key: "display_name", label: "OneDrive" },
      { key: "owner", label: "Owner", mono: true },
      { key: "storage_gb", label: "Storage (GB)", mono: true, right: true },
      { key: "file_count", label: "Files", mono: true, right: true, format: (v) => (v ?? 0).toLocaleString() },
    ],
  },
  distribution_lists: {
    name: "Distribution Lists",
    icon: UsersFour,
    description: "Recreate distribution lists with membership, delivery restrictions and delegation settings.",
    columns: [
      { key: "display_name", label: "DL Name" },
      { key: "primary_smtp", label: "Primary SMTP", mono: true },
      { key: "member_count", label: "Members", mono: true, right: true },
    ],
  },
  teams: {
    name: "Microsoft Teams",
    icon: ChatCircleDots,
    description: "Migrate teams with channels, tabs, apps, members and chat history.",
    columns: [
      { key: "display_name", label: "Team" },
      { key: "member_count", label: "Members", mono: true, right: true },
      { key: "channel_count", label: "Channels", mono: true, right: true },
      { key: "visibility", label: "Visibility" },
    ],
  },
  groups: {
    name: "Microsoft 365 Groups",
    icon: IdentificationBadge,
    description: "Move unified groups with associated mailbox, calendar, files and members.",
    columns: [
      { key: "display_name", label: "Group" },
      { key: "primary_smtp", label: "Primary SMTP", mono: true },
      { key: "member_count", label: "Members", mono: true, right: true },
      { key: "group_type", label: "Type" },
    ],
  },
  contacts: {
    name: "Contacts",
    icon: AddressBook,
    description: "Migrate shared and personal contacts including all custom fields.",
    columns: [
      { key: "display_name", label: "Contact" },
      { key: "email", label: "Email", mono: true },
      { key: "company", label: "Company" },
    ],
  },
  calendars: {
    name: "Calendars",
    icon: CalendarBlank,
    description: "Move calendars including recurring events, attendees, categories and delegations.",
    columns: [
      { key: "display_name", label: "Calendar" },
      { key: "owner", label: "Owner", mono: true },
      { key: "event_count", label: "Events", mono: true, right: true, format: (v) => (v ?? 0).toLocaleString() },
    ],
  },
  public_folders: {
    name: "Public Folders",
    icon: Folder,
    description: "Migrate public folder hierarchies including permissions and mail-enabled folders.",
    columns: [
      { key: "display_name", label: "Path", mono: true },
      { key: "item_count", label: "Items", mono: true, right: true, format: (v) => (v ?? 0).toLocaleString() },
      { key: "size_gb", label: "Size (GB)", mono: true, right: true },
    ],
  },
};

export default function ServiceModule() {
  const { serviceType } = useParams();
  const cfg = SERVICE_CONFIG[serviceType];
  const { current } = useProject();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [q, setQ] = useState("");
  const [starting, setStarting] = useState(false);
  const [mode, setMode] = useState("full");
  const [concurrency, setConcurrency] = useState(3);
  const [runMode, setRunMode] = useState(null);  // "live" | "simulated"
  const [checkpoint, setCheckpoint] = useState(null);
  const [memberModal, setMemberModal] = useState(null);
  const [hideSynced, setHideSynced] = useState(false);
  const nav = useNavigate();

  const requestIdRef = useRef(0);
  useEffect(() => { requestIdRef.current += 1; setItems([]); setSelected(new Set()); setRunMode(null); setCheckpoint(null); }, [serviceType, current?.id]);

  const openMembers = async (itemId, itemName) => {
    if (!current) return;
    setMemberModal({ itemId, itemName, members: [], loading: true });
    try {
      const { data } = await api.get(`/services/${serviceType}/${itemId}/members`, { params: { project_id: current.id } });
      setMemberModal({ itemId, itemName, members: data.members, loading: false });
    } catch (err) {
      setMemberModal({ itemId, itemName, members: [], loading: false, error: true });
    }
  };

  const loadCheckpoint = async () => {
    if (!current) return;
    try {
      const { data } = await api.get(`/projects/${current.id}/services/${serviceType}/checkpoint`);
      setCheckpoint(data);
    } catch {}
  };
  useEffect(() => { loadCheckpoint(); }, [serviceType, current?.id]);

  const resetCheckpoint = async () => {
    if (!current) return;
    if (!confirm("Reset the delta checkpoint for this service?")) return;
    await api.delete(`/projects/${current.id}/services/${serviceType}/checkpoint`);
    toast.success("Checkpoint cleared");
    await loadCheckpoint();
    await discover();
  };

  const discover = async () => {
    if (!current) { toast.error("Select a project first"); return; }
    const myRequestId = requestIdRef.current;
    setLoading(true);
    try {
      const { data } = await api.get(`/services/${serviceType}/discover`, { params: { project_id: current.id } });
      if (requestIdRef.current !== myRequestId) return;
      setItems(data.items);
      setRunMode(data.mode);
      toast.success(`[${(data.mode || "sim").toUpperCase()}] Discovered ${data.total} ${cfg.name.toLowerCase()}`);
      await loadCheckpoint();
    } catch (err) {
      if (requestIdRef.current === myRequestId) toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally { if (requestIdRef.current === myRequestId) setLoading(false); }
  };

  const filtered = useMemo(() => {
    let list = items;
    if (hideSynced) list = list.filter((it) => it.checkpoint_status !== "success");
    if (q.trim()) {
      const s = q.toLowerCase();
      list = list.filter((it) => JSON.stringify(it).toLowerCase().includes(s));
    }
    return list;
  }, [items, q, hideSynced]);

  const toggle = (id) => {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  };
  const toggleAll = () => {
    if (selected.size === filtered.length) setSelected(new Set());
    else setSelected(new Set(filtered.map((it) => it.id)));
  };

  const startMigration = async () => {
    if (!current) return;
    if (selected.size === 0) { toast.error("Select at least one item"); return; }
    setStarting(true);
    try {
      const { data } = await api.post("/jobs", {
        project_id: current.id,
        service_type: serviceType,
        item_ids: Array.from(selected),
        mode,
        concurrency,
      });
      toast.success(`Migration started — ${data.total} items`);
      nav(`/app/jobs/${data.id}`);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally { setStarting(false); }
  };

  if (!cfg) return <div className="p-8 text-zinc-400">Unknown service.</div>;
  const Icon = cfg.icon;

  return (
    <>
      <TopBar
        title={cfg.name}
        subtitle={cfg.description}
        right={
          <div className="flex items-center gap-2">
            <button
              onClick={discover}
              disabled={loading || !current}
              data-testid="discover-btn"
              className="text-xs font-mono uppercase tracking-[0.1em] px-4 py-2 border border-white/20 hover:bg-white/5 flex items-center gap-2 disabled:opacity-40"
            >
              <MagnifyingGlass size={14} />
              {loading ? "discovering…" : "discover"}
            </button>
            <button
              onClick={startMigration}
              disabled={starting || selected.size === 0 || !current}
              data-testid="start-migration-btn"
              className="text-xs font-mono uppercase tracking-[0.1em] px-4 py-2 bg-[#00e5ff] hover:bg-[#00b3cc] text-black flex items-center gap-2 disabled:opacity-40"
            >
              <Play size={14} weight="fill" />
              migrate ({selected.size})
            </button>
          </div>
        }
      />
      <div className="p-6 space-y-4">
        {!current && (
          <Panel className="p-6">
            <div className="text-sm text-zinc-400">
              No active project. <Link to="/app/projects" className="text-[#00e5ff] hover:underline">Select or create one →</Link>
            </div>
          </Panel>
        )}

        {current && (
          <Panel className="p-4">
            <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr_auto_auto_auto] gap-4 items-center">
              <div>
                <DataLabel>source</DataLabel>
                <div className="text-sm font-mono text-white mt-1 truncate">{current.source_tenant.domain}</div>
              </div>
              <ArrowRight size={14} className="text-[#00e5ff] hidden md:block" />
              <div>
                <DataLabel>destination</DataLabel>
                <div className="text-sm font-mono text-white mt-1 truncate">{current.destination_tenant.domain}</div>
              </div>
              <div>
                <DataLabel>mode</DataLabel>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                  data-testid="migration-mode"
                  className="mt-1 bg-[#050505] border border-white/10 px-2 py-1 text-xs font-mono focus:border-[#00e5ff] focus:outline-none"
                >
                  <option value="full">full</option>
                  <option value="incremental">incremental</option>
                  <option value="delta">delta</option>
                </select>
              </div>
              <div>
                <DataLabel>concurrency</DataLabel>
                <select
                  value={concurrency}
                  onChange={(e) => setConcurrency(parseInt(e.target.value, 10))}
                  data-testid="migration-concurrency"
                  className="mt-1 bg-[#050505] border border-white/10 px-2 py-1 text-xs font-mono focus:border-[#00e5ff] focus:outline-none"
                >
                  {[1, 2, 3, 5, 8, 10].map((n) => <option key={n} value={n}>{n}× parallel</option>)}
                </select>
              </div>
              <div>
                <DataLabel>engine</DataLabel>
                <div className="flex items-center gap-2 mt-1">
                  <Icon size={16} className="text-[#00e5ff]" />
                  <span className="text-sm">{cfg.name}</span>
                  {runMode && (
                    <span className={`text-[10px] font-mono uppercase tracking-[0.1em] px-1.5 py-0.5 border ${runMode === "live" ? "border-[#00ff66]/40 text-[#00ff66] bg-[#00ff66]/10" : "border-white/20 text-zinc-400"}`}>
                      {runMode}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </Panel>
        )}

        {current && checkpoint && (
          <Panel className="p-3">
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-6">
                <div>
                  <DataLabel>last sync</DataLabel>
                  <div className="font-mono text-xs text-white mt-1">
                    {checkpoint.last_sync_at ? new Date(checkpoint.last_sync_at).toISOString().replace("T", " ").slice(0, 19) : "never"}
                  </div>
                </div>
                <div>
                  <DataLabel>checkpoint</DataLabel>
                  <div className="font-mono text-xs mt-1">
                    <span className="text-[#00ff66]">{checkpoint.stats.success}</span>
                    <span className="text-zinc-500"> ok · </span>
                    <span className="text-[#ff3b30]">{checkpoint.stats.failed}</span>
                    <span className="text-zinc-500"> err · </span>
                    <span className="text-zinc-300">{checkpoint.stats.total_known}</span>
                    <span className="text-zinc-500"> tracked</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-2 text-xs font-mono text-zinc-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={hideSynced}
                    onChange={(e) => setHideSynced(e.target.checked)}
                    data-testid="hide-synced-toggle"
                    className="accent-[#00e5ff]"
                  />
                  hide already-synced
                </label>
                <button
                  onClick={resetCheckpoint}
                  data-testid="reset-checkpoint-btn"
                  className="text-[10px] font-mono px-2 py-1 border border-white/20 hover:bg-white/5 uppercase tracking-[0.1em]"
                >
                  reset checkpoint
                </button>
              </div>
            </div>
          </Panel>
        )}

        <Panel className="p-0">
          <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">
                {filtered.length} of {items.length} · {selected.size} selected
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="filter…"
                data-testid="filter-input"
                className="bg-[#050505] border border-white/10 px-3 py-1.5 text-xs font-mono focus:border-[#00e5ff] focus:outline-none w-56"
              />
              <button
                onClick={toggleAll}
                data-testid="toggle-all"
                className="text-[10px] font-mono uppercase tracking-[0.1em] px-3 py-1.5 border border-white/20 hover:bg-white/5"
              >
                {selected.size === filtered.length && filtered.length > 0 ? "deselect all" : "select all"}
              </button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-[#0a0a0a]">
                  <th className="w-10 text-left px-4 py-2"></th>
                  {cfg.columns.map((c) => (
                    <th key={c.key} className={`text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 px-4 py-2 ${c.right ? "text-right" : "text-left"}`}>
                      {c.label}
                    </th>
                  ))}
                  <th className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 px-4 py-2 text-left">Sync</th>
                  <th className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 px-4 py-2 text-left">Destination</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={cfg.columns.length + 3} className="text-center py-10 font-mono text-xs text-zinc-500 cursor-blink">scanning source tenant</td></tr>
                )}
                {!loading && items.length === 0 && (
                  <tr><td colSpan={cfg.columns.length + 3} className="text-center py-10">
                    <div className="text-sm text-zinc-500">No items discovered yet.</div>
                    <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-600 mt-1">click discover to scan the source tenant</div>
                  </td></tr>
                )}
                {filtered.map((it) => (
                  <tr key={it.id} className="border-b border-white/5 row-hover">
                    <td className="px-4 py-2.5">
                      <input
                        type="checkbox"
                        checked={selected.has(it.id)}
                        onChange={() => toggle(it.id)}
                        data-testid={`row-check-${it.id}`}
                        className="accent-[#00e5ff]"
                      />
                    </td>
                    {cfg.columns.map((c) => (
                      <td key={c.key} className={`px-4 py-2.5 ${c.mono ? "font-mono text-xs" : "text-sm"} ${c.right ? "text-right" : "text-left"} text-zinc-200`}>
                        {c.key === "member_count" && (serviceType === "groups" || serviceType === "distribution_lists") ? (
                          <button
                            type="button"
                            onClick={() => openMembers(it.id, it.display_name)}
                            data-testid={`view-members-${it.id}`}
                            className="underline decoration-dotted hover:text-[#00e5ff]"
                          >
                            {it[c.key]}
                          </button>
                        ) : (
                          c.format ? c.format(it[c.key]) : it[c.key]
                        )}
                      </td>
                    ))}
                    <td className="px-4 py-2.5">
                      <span className={
                        it.checkpoint_status === "success" ? "text-[10px] font-mono text-[#00ff66] border border-[#00ff66]/30 bg-[#00ff66]/10 px-1.5 py-0.5" :
                        it.checkpoint_status === "failed" ? "text-[10px] font-mono text-[#ff3b30] border border-[#ff3b30]/30 bg-[#ff3b30]/10 px-1.5 py-0.5" :
                        "text-[10px] font-mono text-zinc-500 border border-white/10 px-1.5 py-0.5"
                      }>
                        {it.checkpoint_status || "never"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-500">→ {current?.destination_tenant.domain || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {memberModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-6" onClick={() => setMemberModal(null)}>
          <div className="bg-[#0a0a0a] border border-white/10 max-w-lg w-full max-h-[70vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
              <div className="text-sm font-mono text-white">{memberModal.itemName} - Members</div>
              <button type="button" onClick={() => setMemberModal(null)} className="text-zinc-500 hover:text-white text-xs">close</button>
            </div>
            <div className="overflow-y-auto p-4 space-y-2">
              {memberModal.loading ? (
                <div className="text-xs text-zinc-500 font-mono">loading...</div>
              ) : memberModal.error ? (
                <div className="text-xs text-[#ff3b30] font-mono">failed to load members</div>
              ) : memberModal.members.length === 0 ? (
                <div className="text-xs text-zinc-500 font-mono">no members found</div>
              ) : (
                memberModal.members.map((m) => (
                  <div key={m.id} className="text-xs font-mono text-zinc-200 border-b border-white/5 pb-2">
                    <div className="text-white">{m.display_name}</div>
                    <div className="text-zinc-500">{m.email}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
