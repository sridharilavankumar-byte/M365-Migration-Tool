import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider } from "@/context/AuthContext";
import LoginPage from "@/pages/LoginPage";
import AppShell from "@/pages/AppShell";
import Dashboard from "@/pages/Dashboard";
import ProjectsPage from "@/pages/ProjectsPage";
import ServiceModule from "@/pages/ServiceModule";
import JobsPage from "@/pages/JobsPage";
import JobDetail from "@/pages/JobDetail";
import LogsPage from "@/pages/LogsPage";
import SettingsPage from "@/pages/SettingsPage";
import SchedulesPage from "@/pages/SchedulesPage";
import ReportsPage from "@/pages/ReportsPage";

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Navigate to="/app/dashboard" replace />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/app" element={<AppShell />}>
              <Route index element={<Navigate to="/app/dashboard" replace />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="projects" element={<ProjectsPage />} />
              <Route path="services/:serviceType" element={<ServiceModule />} />
              <Route path="jobs" element={<JobsPage />} />
              <Route path="jobs/:jobId" element={<JobDetail />} />
              <Route path="schedules" element={<SchedulesPage />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="logs" element={<LogsPage />} />
              <Route path="settings" element={<SettingsPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/app/dashboard" replace />} />
          </Routes>
        </BrowserRouter>
        <Toaster
          theme="dark"
          position="bottom-right"
          toastOptions={{
            style: {
              background: "#0a0a0a",
              border: "1px solid rgba(255,255,255,0.15)",
              borderRadius: "0",
              color: "#fff",
              fontFamily: "IBM Plex Mono, monospace",
              fontSize: "12px",
            },
          }}
        />
      </AuthProvider>
    </div>
  );
}

export default App;
