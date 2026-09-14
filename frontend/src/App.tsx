import { useQuery } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { useAuth } from "./auth/AuthContext";
import AppShell from "./components/AppShell";
import { Spinner } from "./components/ui";
import AssistantPage from "./pages/AssistantPage";
import BillingPage from "./pages/BillingPage";
import CompaniesPage from "./pages/CompaniesPage";
import CompanyDetailPage from "./pages/CompanyDetailPage";
import ContactsPage from "./pages/ContactsPage";
import DashboardPage from "./pages/DashboardPage";
import LeadsPage from "./pages/LeadsPage";
import LoginPage from "./pages/LoginPage";
import ManagementPage from "./pages/ManagementPage";
import PipelinePage from "./pages/PipelinePage";
import SettingsPage from "./pages/SettingsPage";
import SetupPage from "./pages/SetupPage";
import TasksPage from "./pages/TasksPage";

function useNeedsSetup() {
  const { user } = useAuth();
  return useQuery({
    queryKey: ["setup-status"],
    queryFn: () => api.get<{ needs_setup: boolean }>("/setup/status"),
    enabled: !user,
    staleTime: Infinity,
    retry: 1,
  });
}

function Protected() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to="/login" replace />;
  return <AppShell />;
}

function LoginGate() {
  const { user } = useAuth();
  const setup = useNeedsSetup();
  if (user) return <Navigate to="/" replace />;
  if (setup.isLoading) return <Spinner />;
  if (setup.data?.needs_setup) return <Navigate to="/setup" replace />;
  return <LoginPage />;
}

function SetupGate() {
  const { user } = useAuth();
  const setup = useNeedsSetup();
  if (user) return <Navigate to="/" replace />;
  if (setup.isLoading) return <Spinner />;
  if (setup.data && !setup.data.needs_setup) return <Navigate to="/login" replace />;
  return <SetupPage />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginGate />} />
        <Route path="/setup" element={<SetupGate />} />
        <Route element={<Protected />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/companies" element={<CompaniesPage />} />
          <Route path="/companies/:id" element={<CompanyDetailPage />} />
          <Route path="/contacts" element={<ContactsPage />} />
          <Route path="/leads" element={<LeadsPage />} />
          <Route path="/pipeline" element={<PipelinePage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/billing" element={<BillingPage />} />
          <Route path="/management" element={<ManagementPage />} />
          <Route path="/assistant" element={<AssistantPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
