export function StatusBadge({ status }) {
  const styles = {
    running: "border-[#00e5ff]/40 text-[#00e5ff] bg-[#00e5ff]/10",
    queued: "border-[#ffd600]/40 text-[#ffd600] bg-[#ffd600]/10",
    paused: "border-[#ffd600]/40 text-[#ffd600] bg-[#ffd600]/10",
    completed: "border-[#00ff66]/40 text-[#00ff66] bg-[#00ff66]/10",
    success: "border-[#00ff66]/40 text-[#00ff66] bg-[#00ff66]/10",
    failed: "border-[#ff3b30]/40 text-[#ff3b30] bg-[#ff3b30]/10",
    canceled: "border-white/20 text-zinc-400 bg-white/5",
    pending: "border-white/15 text-zinc-500 bg-white/[0.02]",
  };
  const cls = styles[status] || styles.pending;
  return (
    <span className={`inline-flex items-center gap-1.5 border ${cls} rounded-none px-2 py-0.5 text-[10px] font-mono uppercase tracking-[0.1em]`}>
      {status === "running" && <span className="w-1 h-1 bg-current pulse-dot" />}
      {status}
    </span>
  );
}

export function ProgressLine({ value = 0, active = false }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div className="w-full h-[2px] bg-white/5 relative overflow-hidden">
      <div
        className={`h-full ${active ? "bg-[#00e5ff] progress-glow" : "bg-white/40"}`}
        style={{ width: `${clamped}%`, transition: "width 400ms ease" }}
      />
      {active && (
        <div className="absolute inset-0 tracing-beam pointer-events-none" />
      )}
    </div>
  );
}

export function DataLabel({ children, className = "" }) {
  return (
    <div className={`text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 ${className}`}>
      {children}
    </div>
  );
}

export function Panel({ children, className = "", ...rest }) {
  return (
    <div className={`bg-[#121212] border border-white/10 rounded-none ${className}`} {...rest}>
      {children}
    </div>
  );
}
