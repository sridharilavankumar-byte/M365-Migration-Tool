import { NavLink, useLocation } from "react-router-dom";
import {
  ChartLineUp, Envelope, Cloud, HardDrives, UsersFour,
  ChatCircleDots, IdentificationBadge, AddressBook, CalendarBlank,
  Folder, Stack, GearSix, Terminal, GitBranch, Clock,
} from "@phosphor-icons/react";

const NAV_ITEMS = [
  { to: "/app/dashboard", label: "Dashboard", icon: ChartLineUp, testid: "nav-dashboard" },
  { to: "/app/projects", label: "Projects", icon: GitBranch, testid: "nav-projects" },
  { section: "Migration Services" },
  { to: "/app/services/exchange", label: "Exchange Mailboxes", icon: Envelope, testid: "nav-exchange" },
  { to: "/app/services/sharepoint", label: "SharePoint Sites", icon: Cloud, testid: "nav-sharepoint" },
  { to: "/app/services/onedrive", label: "OneDrive", icon: HardDrives, testid: "nav-onedrive" },
  { to: "/app/services/distribution_lists", label: "Distribution Lists", icon: UsersFour, testid: "nav-dl" },
  { to: "/app/services/teams", label: "Microsoft Teams", icon: ChatCircleDots, testid: "nav-teams" },
  { to: "/app/services/groups", label: "M365 Groups", icon: IdentificationBadge, testid: "nav-groups" },
  { to: "/app/services/contacts", label: "Contacts", icon: AddressBook, testid: "nav-contacts" },
  { to: "/app/services/calendars", label: "Calendars", icon: CalendarBlank, testid: "nav-calendars" },
  { to: "/app/services/public_folders", label: "Public Folders", icon: Folder, testid: "nav-pf" },
  { section: "Operations" },
  { to: "/app/jobs", label: "Job Queue", icon: Stack, testid: "nav-jobs" },
  { to: "/app/schedules", label: "Schedules", icon: Clock, testid: "nav-schedules" },
  { to: "/app/logs", label: "Audit Logs", icon: Terminal, testid: "nav-logs" },
  { to: "/app/settings", label: "Settings", icon: GearSix, testid: "nav-settings" },
];

export default function Sidebar() {
  const loc = useLocation();
  return (
    <aside className="w-64 shrink-0 bg-[#0a0a0a] border-r border-white/10 flex flex-col min-h-screen">
      <div className="px-5 py-5 border-b border-white/10">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-[#00e5ff] flex items-center justify-center text-black font-bold font-mono text-sm">M</div>
          <div>
            <div className="font-display text-white text-base leading-none tracking-tight">MigrateSuite</div>
            <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-500 mt-1">m365 tenant ops</div>
          </div>
        </div>
      </div>
      <nav className="flex-1 py-4 overflow-y-auto">
        {NAV_ITEMS.map((item, idx) => {
          if (item.section) {
            return (
              <div key={idx} className="px-5 pt-5 pb-2 text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-600">
                {item.section}
              </div>
            );
          }
          const Icon = item.icon;
          const active = loc.pathname.startsWith(item.to);
          return (
            <NavLink
              key={item.to}
              to={item.to}
              data-testid={item.testid}
              className={`flex items-center gap-3 px-5 py-2 text-sm border-l-2 transition-colors ${
                active
                  ? "border-[#00e5ff] text-white bg-white/[0.03]"
                  : "border-transparent text-zinc-400 hover:text-white hover:bg-white/[0.02]"
              }`}
            >
              <Icon size={16} weight={active ? "fill" : "regular"} />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>
      <div className="px-5 py-4 border-t border-white/10">
        <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-zinc-600 mb-1">System</div>
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-[#00ff66] pulse-dot" />
          <span className="text-xs font-mono text-zinc-400">operational</span>
        </div>
      </div>
    </aside>
  );
}
