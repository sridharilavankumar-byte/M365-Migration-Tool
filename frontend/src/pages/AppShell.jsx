import { Outlet, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { ProjectProvider } from "@/context/ProjectContext";
import Sidebar from "@/components/layout/Sidebar";

export default function AppShell() {
  const { user, checking } = useAuth();
  const loc = useLocation();

  if (checking) {
    return (
      <div className="min-h-screen bg-[#050505] flex items-center justify-center">
        <div className="font-mono text-xs text-zinc-500 cursor-blink">initializing session</div>
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  }

  return (
    <ProjectProvider>
      <div className="min-h-screen flex bg-[#050505] text-white">
        <Sidebar />
        <main className="flex-1 min-w-0 flex flex-col">
          <Outlet />
        </main>
      </div>
    </ProjectProvider>
  );
}
