import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { CompanyListItem, Invoice, Page, ProviderStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Card, EmptyState, ErrorBanner, Modal, Pagination, Spinner, StatusBadge } from "../components/ui";
import { dateIt, dateTimeIt, eur } from "../lib/format";

function ProviderPanel() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";

  const { data } = useQuery({
    queryKey: ["billing-provider"],
    queryFn: () => api.get<ProviderStatus>("/billing/provider"),
    enabled: isAdmin,
    retry: false,
  });
  const test = useMutation({
    mutationFn: () => api.post<ProviderStatus>("/billing/provider/test"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["billing-provider"] }),
  });
  const configureStub = useMutation({
    mutationFn: () =>
      api.put("/billing/provider", {
        provider_key: "stub-sandbox",
        api_version: "v1",
        environment: "sandbox",
        config: { endpoint: "https://stub.local/api" },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["billing-provider"] }),
  });

  if (!isAdmin) return null;

  return (
    <Card className="card__pad">
      <div className="card__title">Provider fatturazione elettronica</div>
      {!data || !data.configured ? (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span className="muted">Nessun provider configurato.</span>
          {data && data.available_providers.some((p) => p.key === "stub-sandbox") && (
            <button className="btn btn--ghost btn--sm" onClick={() => configureStub.mutate()}>
              Configura provider di test (sandbox)
            </button>
          )}
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <span><strong>{data.provider!.provider_key}</strong> <span className="muted">api {data.provider!.api_version}</span></span>
          <StatusBadge status={data.health_status ?? data.provider!.last_health_status ?? "unknown"} />
          <span className="muted">Ambiente: {data.provider!.environment}</span>
          {data.provider!.last_health_check_at && (
            <span className="muted">Ultimo check: {dateTimeIt(data.provider!.last_health_check_at)}</span>
          )}
          <button className="btn btn--ghost btn--sm" onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? "Verifica…" : "Testa connessione"}
          </button>
        </div>
      )}
      {test.data?.health_detail && <div className="muted" style={{ marginTop: 8 }}>{test.data.health_detail}</div>}
      {test.error && <ErrorBanner error={test.error} />}
      {configureStub.error && <ErrorBanner error={configureStub.error} />}
    </Card>
  );
}

export default function BillingPage() {
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["invoices", page],
    queryFn: () => api.get<Page<Invoice>>(`/billing/invoices?page=${page}&page_size=25`),
  });
  const { data: overview } = useQuery({
    queryKey: ["billing-overview"],
    queryFn: () => api.get<Record<string, number>>("/billing/overview"),
  });
  const { data: companies } = useQuery({
    queryKey: ["companies", "for-invoice"],
    queryFn: () => api.get<Page<CompanyListItem>>("/companies?page_size=200"),
    enabled: creating,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["invoices"] });
    qc.invalidateQueries({ queryKey: ["billing-overview"] });
  };
  const create = useMutation({
    mutationFn: (d: Record<string, unknown>) => api.post("/billing/invoices", d),
    onSuccess: () => { setCreating(false); invalidate(); },
  });
  const act = useMutation({
    mutationFn: ({ id, op }: { id: string; op: string }) =>
      api.post(`/billing/invoices/${id}/${op}`, op === "finalize" ? {} : undefined),
    onSuccess: invalidate,
  });
  const dispatch = useMutation({
    mutationFn: () => api.post("/billing/jobs/dispatch"),
    onSuccess: invalidate,
  });
  const reconcile = useMutation({
    mutationFn: (id: string) => api.post(`/billing/invoices/${id}/reconcile`),
    onSuccess: invalidate,
  });

  const canSubmit = ["admin", "management"].includes(useAuth().user?.role ?? "");

  return (
    <>
      <div className="page-head">
        <div><h1>Fatturazione</h1><div className="page-head__meta">Fatture attive e trasmissioni SdI</div></div>
        <button className="btn btn--primary" onClick={() => setCreating(true)}>+ Nuova fattura</button>
      </div>

      <ProviderPanel />

      {overview && (
        <div className="kpi-grid">
          <Card className="kpi"><div className="kpi__label">Da inviare</div><div className="kpi__value">{overview.to_send}</div></Card>
          <Card className="kpi"><div className="kpi__label">In attesa SdI</div><div className="kpi__value">{overview.awaiting_sdi}</div></Card>
          <Card className="kpi"><div className="kpi__label">Consegnate</div><div className="kpi__value">{overview.delivered}</div></Card>
          <Card className={`kpi ${overview.rejected ? "kpi--alert" : ""}`}><div className="kpi__label">Scartate</div><div className="kpi__value">{overview.rejected}</div></Card>
          <Card className={`kpi ${overview.requires_attention ? "kpi--warn" : ""}`}><div className="kpi__label">Da verificare</div><div className="kpi__value">{overview.requires_attention}</div></Card>
        </div>
      )}

      {error && <ErrorBanner error={error} />}
      {act.error && <ErrorBanner error={act.error} />}
      {isLoading ? <Spinner /> : !data || data.items.length === 0 ? (
        <EmptyState>Nessuna fattura. Crea la prima bozza.</EmptyState>
      ) : (
        <div className="card">
          <table className="table">
            <thead>
              <tr><th>N°</th><th>Data</th><th>Totale</th><th>Stato interno</th><th>SdI</th><th>Provider</th><th></th></tr>
            </thead>
            <tbody>
              {data.items.map((i) => (
                <tr key={i.id} style={{ cursor: "default" }}>
                  <td className="mono">{i.number ? `${i.series}${i.number}/${i.fiscal_year}` : <span className="muted">bozza</span>}</td>
                  <td>{dateIt(i.issue_date)}</td>
                  <td className="mono">{eur(i.total_amount)}</td>
                  <td><StatusBadge status={i.status} /></td>
                  <td className="muted">{i.sdi_status ?? "—"}</td>
                  <td className="muted">{i.provider_key ?? "—"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {i.status === "draft" && canSubmit && (
                      <button className="btn btn--ghost btn--sm" onClick={() => act.mutate({ id: i.id, op: "finalize" })}>
                        Finalizza
                      </button>
                    )}
                    {["ready_to_send", "rejected", "delivery_failed"].includes(i.status) && canSubmit && (
                      <button className="btn btn--accent btn--sm" onClick={() => act.mutate({ id: i.id, op: "send" })}>
                        {i.status === "ready_to_send" ? "Invia" : "Reinvia"}
                      </button>
                    )}
                    {["transmission_unknown", "requires_reconciliation"].includes(i.status) && canSubmit && (
                      <button className="btn btn--ghost btn--sm" onClick={() => reconcile.mutate(i.id)}>
                        Riconcilia
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}

      <div style={{ marginTop: 12 }}>
        <button className="btn btn--ghost btn--sm" onClick={() => dispatch.mutate()}>
          Esegui coda trasmissioni ({dispatch.data ? `${(dispatch.data as { processed: number }).processed} elaborate` : "…"})
        </button>
      </div>

      {creating && (
        <Modal title="Nuova fattura (bozza)" onClose={() => setCreating(false)} footer={null}>
          <form onSubmit={(e: FormEvent<HTMLFormElement>) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            create.mutate({
              company_id: String(f.get("company_id")),
              notes: String(f.get("notes") ?? "") || undefined,
              lines: [{
                description: String(f.get("description") ?? ""),
                quantity: Number(f.get("quantity") ?? 1),
                unit_price: Number(f.get("unit_price") ?? 0),
                vat_rate: Number(f.get("vat_rate") ?? 22),
              }],
            });
          }}>
            {create.error && <ErrorBanner error={create.error} />}
            <div className="form-grid">
              <div className="field span-2">
                <label className="field__label">Cliente *</label>
                <select className="select" name="company_id" required>
                  <option value="">— seleziona —</option>
                  {companies?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
                </select>
              </div>
              <div className="field span-2"><label className="field__label">Descrizione prestazione *</label>
                <input className="input" name="description" required /></div>
              <div className="field"><label className="field__label">Quantità</label>
                <input className="input" name="quantity" type="number" step="0.01" defaultValue={1} min="0.01" /></div>
              <div className="field"><label className="field__label">Prezzo unitario €</label>
                <input className="input" name="unit_price" type="number" step="0.01" min="0" required /></div>
              <div className="field"><label className="field__label">Aliquota IVA %</label>
                <input className="input" name="vat_rate" type="number" step="0.01" defaultValue={22} min="0" /></div>
              <div className="field"><label className="field__label">Note</label>
                <input className="input" name="notes" /></div>
            </div>
            <div className="modal__foot" style={{ margin: "16px -20px -16px", padding: "12px 0 0" }}>
              <button type="button" className="btn btn--ghost" onClick={() => setCreating(false)}>Annulla</button>
              <button type="submit" className="btn btn--primary" disabled={create.isPending}>Crea bozza</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
