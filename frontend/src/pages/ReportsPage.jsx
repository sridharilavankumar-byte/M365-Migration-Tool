import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import TopBar from "@/components/layout/TopBar";
import { Panel, StatusBadge } from "@/components/shared/Primitives";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { DownloadSimple, MagnifyingGlass } from "@phosphor-icons/react";
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

const SERVICE_TYPES = ["exchange", "sharepoint", "onedrive", "distribution_lists", "teams", "groups", "contacts", "calendars", "public_folders"];

export default function ReportsPage() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [serviceFilter, setServiceFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [searchEmail, setSearchEmail] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [searching, setSearching] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const params = {};
      if (serviceFilter) params.service_type = serviceFilter;
      if (statusFilter) params.status = statusFilter;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const { data } = await api.get("/jobs", { params });
      setJobs(data);
    } catch (err) {
      toast.error("Failed to load reports");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [serviceFilter, statusFilter, dateFrom, dateTo]);

  const summary = useMemo(() => {
    const totalJobs = jobs.length;
    const totalSuccess = jobs.reduce((s, j) => s + (j.success_count || 0), 0);
    const totalFailed = jobs.reduce((s, j) => s + (j.fail_count || 0), 0);
    const totalItems = totalSuccess + totalFailed;
    const successRate = totalItems > 0 ? Math.round((totalSuccess / totalItems) * 100) : 0;
    const byService = SERVICE_TYPES.map((s) => ({
      service: s,
      jobs: jobs.filter((j) => j.service_type === s).length,
    })).filter((x) => x.jobs > 0);

    const finishedJobs = jobs
      .filter((j) => j.finished_at)
      .slice()
      .sort((a, b) => new Date(a.finished_at) - new Date(b.finished_at));
    const byDay = {};
    finishedJobs.forEach((j) => {
      const day = j.finished_at.slice(0, 10);
      if (!byDay[day]) byDay[day] = { day, success: 0, failed: 0 };
      byDay[day].success += j.success_count || 0;
      byDay[day].failed += j.fail_count || 0;
    });
    const trend = Object.values(byDay).map((d) => {
      const total = d.success + d.failed;
      return { day: d.day.slice(5), rate: total > 0 ? Math.round((d.success / total) * 100) : 0 };
    });

    return { totalJobs, totalSuccess, totalFailed, successRate, byService, trend };
  }, [jobs]);

  const exportCsv = () => {
    if (!jobs.length) return;
    const headers = ["Job ID", "Project", "Service", "Status", "Mode", "Total", "Success", "Failed", "Started", "Finished"];
    const rows = jobs.map((j) => [
      j.id, j.project_name, j.service_type, j.status, j.mode,
      j.total, j.success_count, j.fail_count,
      j.started_at || "", j.finished_at || "",
    ].map((v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`).join(","));
    const csv = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "migration-report.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const exportPdf = async () => {
    try {
      const params = {};
      if (serviceFilter) params.service_type = serviceFilter;
      if (statusFilter) params.status = statusFilter;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const response = await api.get("/reports/export.pdf", { params, responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "migration-report.pdf";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error("Failed to generate PDF");
    }
  };

  const runSearch = async () => {
    if (!searchEmail.trim()) return;
    setSearching(true);
    setSearchResults(null);
    try {
      const { data } = await api.get("/reports/user-history", { params: { email: searchEmail.trim() } });
      setSearchResults(data);
    } catch (err) {
      toast.error("Search failed");
    } finally {
      setSearching(false);
    }
  };

  return (
    <>
      <TopBar
        title="Reports"
        subtitle="Migration history and analytics across all services"
        right={
          <div className="flex items-center gap-2">
            <button
              onClick={exportCsv}
              disabled={!jobs.length}
              data-testid="export-report-csv-btn"
              className="text-xs font-mono uppercase tracking-[0.1em] px-4 py-2 border border-white/20 hover:bg-white/5 flex items-center gap-2 disabled:opacity-40"
            >
              <DownloadSimple size={14} />
              export csv
            </button>
            <button
              onClick={exportPdf}
              disabled={!jobs.length}
              data-testid="export-report-pdf-btn"
              className="text-xs font-mono uppercase tracking-[0.1em] px-4 py-2 border border-white/20 hover:bg-white/5 flex items-center gap-2 disabled:opacity-40"
            >
              <DownloadSimple size={14} />
              export pdf
            </button>
          </div>
        }
      />
      <div className="p-6 space-y-4">
        <div className="grid grid-cols-4 gap-4">
          <Panel className="p-4">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">Total Jobs</div>
            <div className="text-2xl font-mono text-white mt-1">{summary.totalJobs}</div>
          </Panel>
          <Panel className="p-4">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">Items Succeeded</div>
            <div className="text-2xl font-mono text-[#00ff66] mt-1">{summary.totalSuccess}</div>
          </Panel>
          <Panel className="p-4">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">Items Failed</div>
            <div className="text-2xl font-mono text-[#ff3b30] mt-1">{summary.totalFailed}</div>
          </Panel>
          <Panel className="p-4">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">Success Rate</div>
            <div className="text-2xl font-mono text-white mt-1">{summary.successRate}%</div>
          </Panel>
        </div>

        <div className="grid grid-cols-2 gap-4">
          {summary.byService.length > 0 && (
            <Panel className="p-4">
              <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 mb-3">Jobs by Service</div>
              <div style={{ width: "100%", height: 200 }}>
                <ResponsiveContainer>
                  <BarChart data={summary.byService}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="service" tick={{ fill: "#71717a", fontSize: 10 }} />
                    <YAxis tick={{ fill: "#71717a", fontSize: 10 }} allowDecimals={false} />
                    <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid rgba(255,255,255,0.15)" }} />
                    <Bar dataKey="jobs" fill="#00e5ff" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          )}

          {summary.trend.length > 1 && (
            <Panel className="p-4">
              <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 mb-3">Success Rate Over Time</div>
              <div style={{ width: "100%", height: 200 }}>
                <ResponsiveContainer>
                  <LineChart data={summary.trend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="day" tick={{ fill: "#71717a", fontSize: 10 }} />
                    <YAxis tick={{ fill: "#71717a", fontSize: 10 }} domain={[0, 100]} />
                    <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid rgba(255,255,255,0.15)" }} />
                    <Line type="monotone" dataKey="rate" stroke="#00ff66" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          )}
        </div>

        <Panel className="p-4">
          <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 mb-3">Search by Email or Name (across all services)</div>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={searchEmail}
              onChange={(e) => setSearchEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
              placeholder="test.user@maxisit.com"
              data-testid="user-history-input"
              className="flex-1 bg-[#050505] border border-white/10 px-3 py-2 text-sm font-mono focus:border-[#00e5ff] focus:outline-none"
            />
            <button
              onClick={runSearch}
              disabled={searching || !searchEmail.trim()}
              data-testid="user-history-search-btn"
              className="text-xs font-mono uppercase tracking-[0.1em] px-4 py-2 bg-[#00e5ff] hover:bg-[#00b3cc] text-black flex items-center gap-2 disabled:opacity-40"
            >
              <MagnifyingGlass size={14} />
              {searching ? "searching..." : "search"}
            </button>
          </div>

          {searchResults && (
            <div className="mt-4 border-t border-white/10 pt-4">
              <div className="text-xs font-mono text-zinc-500 mb-2">{searchResults.total} match(es) for "{searchResults.query}"</div>
              {searchResults.total === 0 ? (
                <div className="text-xs font-mono text-zinc-500 py-4 text-center">no migration history found for this person</div>
              ) : (
                <div className="space-y-2">
                  {searchResults.matches.map((m, idx) => (
                    <div key={idx} className="text-xs font-mono border-b border-white/5 pb-2 flex items-center justify-between">
                      <div>
                        <span className="text-white">{m.item_display_name}</span>
                        <span className="text-zinc-500"> - {m.service_type} - {m.project_name}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <StatusBadge status={m.item_status} />
                        <Link to={`/app/jobs/${m.job_id}`} className="text-[#00e5ff] hover:underline">view job -&gt;</Link>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Panel>

        <Panel className="p-4">
          <div className="flex items-center gap-3 flex-wrap">
            <select value={serviceFilter} onChange={(e) => setServiceFilter(e.target.value)}
              className="bg-[#050505] border border-white/10 px-3 py-1.5 text-xs font-mono focus:border-[#00e5ff] focus:outline-none">
              <option value="">all services</option>
              {SERVICE_TYPES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-[#050505] border border-white/10 px-3 py-1.5 text-xs font-mono focus:border-[#00e5ff] focus:outline-none">
              <option value="">all statuses</option>
              <option value="completed">completed</option>
              <option value="running">running</option>
              <option value="queued">queued</option>
              <option value="canceled">canceled</option>
            </select>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
              className="bg-[#050505] border border-white/10 px-3 py-1.5 text-xs font-mono focus:border-[#00e5ff] focus:outline-none" />
            <span className="text-zinc-500 text-xs">to</span>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
              className="bg-[#050505] border border-white/10 px-3 py-1.5 text-xs font-mono focus:border-[#00e5ff] focus:outline-none" />
          </div>
        </Panel>

        <Panel className="p-0">
          <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500">{jobs.length} jobs</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-[#0a0a0a]">
                  {["Job ID", "Project", "Service", "Mode", "Success", "Failed", "Status", "Started", ""].map((h) => (
                    <th key={h} className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 px-4 py-2 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={9} className="text-center py-10 text-sm text-zinc-500 font-mono">loading...</td></tr>
                )}
                {!loading && jobs.length === 0 && (
                  <tr><td colSpan={9} className="text-center py-10 text-sm text-zinc-500 font-mono">no jobs match these filters</td></tr>
                )}
                {jobs.map((j) => (
                  <tr key={j.id} className="border-b border-white/5 row-hover">
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-400">{j.id.slice(-8)}</td>
                    <td className="px-4 py-2.5 text-zinc-200">{j.project_name}</td>
                    <td className="px-4 py-2.5 font-mono text-xs">{j.service_type}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-400">{j.mode}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-[#00ff66]">{j.success_count}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-[#ff3b30]">{j.fail_count}</td>
                    <td className="px-4 py-2.5"><StatusBadge status={j.status} /></td>
                    <td className="px-4 py-2.5 font-mono text-[10px] text-zinc-500">{j.started_at ? new Date(j.started_at).toISOString().replace("T", " ").slice(5, 19) : "-"}</td>
                    <td className="px-4 py-2.5"><Link to={`/app/jobs/${j.id}`} className="text-[10px] font-mono text-[#00e5ff] hover:underline">open -&gt;</Link></td>
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