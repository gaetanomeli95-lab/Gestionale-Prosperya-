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
import ControllingPage from "./pages/ControllingPage";
import CockpitPage from "./pages/CockpitPage";
import ContactsPage from "./pages/ContactsPage";
import DashboardPage from "./pages/DashboardPage";
import DocumentsPage from "./pages/DocumentsPage";
import FiscalPage from "./pages/FiscalPage";
import FundingPage from "./pages/FundingPage";
import HubPage from "./pages/HubPage";
import LeadsPage from "./pages/LeadsPage";
import LoginPage from "./pages/LoginPage";
import ManagementPage from "./pages/ManagementPage";
import PipelinePage from "./pages/PipelinePage";
import PracticesPage from "./pages/PracticesPage";
import SettingsPage from "./pages/SettingsPage";
import SetupPage from "./pages/SetupPage";
import TasksPage from "./pages/TasksPage";
import TreasuryPage from "./pages/TreasuryPage";

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
          <Route path="/practices" element={<PracticesPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/billing" element={<BillingPage />} />
          <Route path="/management" element={<ManagementPage />} />
          <Route path="/treasury" element={<TreasuryPage />} />
          <Route path="/fiscal" element={<FiscalPage />} />
          <Route path="/controlling" element={<ControllingPage />} />
          <Route path="/funding" element={<FundingPage />} />
          <Route path="/hub" element={<HubPage />} />
          <Route path="/cockpit/:companyId" element={<CockpitPage />} />
          <Route path="/assistant" element={<AssistantPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
