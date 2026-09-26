import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { FileText, PlugZap, Send } from "lucide-react";
import { api } from "../api/client";
import type { CompanyListItem, Invoice, Page, ProviderStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import {
  Badge, Callout, Dot, EmptyState, ErrorBanner, Field, Modal, PageHeader, Pagination, Section, Skeleton, Stat,
  StatusBadge, statusLabel, statusTone, toast,
} from "../components/ui";
import { dateIt, dateTimeIt, eur } from "../lib/format";

const ENV_LABEL: Record<string, string> = { sandbox: "Sandbox", production: "Produzione", test: "Test" };

/** Human SdI status (codes stay English in the API). */
const SDI_LABEL: Record<string, string> = {
  pending: "In attesa", queued: "In coda", sent: "Inviata", submitted: "Inviata", delivered: "Consegnata",
  accepted: "Accettata", rejected: "Scartata", not_delivered: "Mancata consegna", delivery_failed: "Mancata consegna",
  unknown: "Sconosciuto", received: "Ricevuta", error: "Errore",
};

function ProviderPanel() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";

  const { data, isLoading } = useQuery({
    queryKey: ["billing-provider"],
    queryFn: () => api.get<ProviderStatus>("/billing/provider"),
    enabled: isAdmin,
    retry: false,
  });
  const test = useMutation({
    mutationFn: () => api.post<ProviderStatus>("/billing/provider/test"),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["billing-provider"] }); toast("Connessione verificata"); },
  });
  const configureStub = useMutation({
    mutationFn: () =>
      api.put("/billing/provider", {
        provider_key: "stub-sandbox",
        api_version: "v1",
        environment: "sandbox",
        config: { endpoint: "https://stub.local/api" },
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["billing-provider"] }); toast("Provider di test configurato"); },
  });

  if (!isAdmin) return null;

  const health = data?.configured ? (data.health_status ?? data.provider!.last_health_status ?? "unknown") : null;

  return (
    <Section
      title="Canale di trasmissione"
      actions={data?.configured ? (
        <button className="btn btn--ghost btn--sm" onClick={() => test.mutate()} disabled={test.isPending}>
          <PlugZap size={12} /> {test.isPending ? "Verifica…" : "Testa connessione"}
        </button>
      ) : undefined}
    >
      {isLoading && <Skeleton rows={2} />}
      {!isLoading && (!data || !data.configured) ? (
        <Callout
          tone="warning"
          title="Nessun provider configurato"
          action={data && data.available_providers.some((p) => p.key === "stub-sandbox") ? (
            <button className="btn btn--ghost btn--sm" onClick={() => configureStub.mutate()} disabled={configureStub.isPending}>
              Configura provider di test
            </button>
          ) : undefined}
        >
          Senza un canale attivo le fatture restano in bozza e non raggiungono lo SdI.
        </Callout>
      ) : data?.configured ? (
        <div className="cluster cluster--between">
          <div className="cluster">
            <Dot tone={statusTone(health)} title={health ?? undefined}>{statusLabel(health)}</Dot>
            <span className="strong">{data.provider!.provider_key}</span>
            <Badge tone="neutral" dot={false}>API {data.provider!.api_version}</Badge>
            <Badge tone={data.provider!.environment === "production" ? "primary" : "accent"} dot={false}>
              {ENV_LABEL[data.provider!.environment] ?? data.provider!.environment}
            </Badge>
            {!data.provider!.credentials_configured && <Badge tone="warning">Credenziali mancanti</Badge>}
          </div>
          <span className="text-xs muted">
            {data.provider!.last_health_check_at
              ? `ultima verifica ${dateTimeIt(data.provider!.last_health_check_at)}`
              : "mai verificato"}
          </span>
        </div>
      ) : null}
      {data && data.available_providers.length > 0 && (
        <details className="mt-3">
          <summary className="eyebrow eyebrow--muted">Provider disponibili ({data.available_providers.length})</summary>
          <div className="cluster mt-1">
            {data.available_providers.map((p) => (
              <Badge key={p.key} tone={data.provider?.provider_key === p.key ? "primary" : "neutral"} dot={false}>
                {p.key} · {p.api_version}
              </Badge>
            ))}
          </div>
        </details>
      )}
      {test.data?.health_detail && <div className="mt-3"><Callout tone="neutral">{test.data.health_detail}</Callout></div>}
      {test.error && <div className="mt-3"><ErrorBanner error={test.error} /></div>}
      {configureStub.error && <div className="mt-3"><ErrorBanner error={configureStub.error} /></div>}
    </Section>
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
    onSuccess: () => { setCreating(false); invalidate(); toast("Bozza creata"); },
  });
  const act = useMutation({
    mutationFn: ({ id, op }: { id: string; op: string }) =>
      api.post(`/billing/invoices/${id}/${op}`, op === "finalize" ? {} : undefined),
    onSuccess: (_r, v) => { invalidate(); toast(v.op === "finalize" ? "Fattura finalizzata" : "Fattura messa in coda di invio"); },
  });
  const dispatch = useMutation({
    mutationFn: () => api.post("/billing/jobs/dispatch"),
    onSuccess: (r) => { invalidate(); toast(`Coda elaborata: ${(r as { processed?: number })?.processed ?? 0} trasmissioni`); },
  });
  const reconcile = useMutation({
    mutationFn: (id: string) => api.post(`/billing/invoices/${id}/reconcile`),
    onSuccess: () => { invalidate(); toast("Stato riconciliato con il provider"); },
  });

  const canSubmit = ["admin", "management"].includes(useAuth().user?.role ?? "");
  const companyName = (id: string) => companies?.items.find((c) => c.id === id)?.legal_name;

  return (
    <>
      <PageHeader
        hero
        eyebrow="Finanza e fisco"
        title="Fatturazione"
        question="Cosa devo emettere, cosa è in trasmissione, cosa è andato storto?"
        actions={
          <>
            <button className="btn btn--ghost" onClick={() => dispatch.mutate()} disabled={dispatch.isPending}>
              <Send size={14} /> {dispatch.isPending ? "Elaborazione…" : "Esegui coda trasmissioni"}
            </button>
            <button className="btn btn--primary" onClick={() => setCreating(true)}>+ Nuova fattura</button>
          </>
        }
      />

      {overview ? (
        <div className="stat-grid">
          <Stat hero icon={<FileText size={14} />} label="Da inviare" value={overview.to_send}
                hint="pronte, in attesa di trasmissione" />
          <Stat label="In attesa SdI" value={overview.awaiting_sdi} hint="trasmesse, esito non ancora ricevuto" />
          <Stat label="Consegnate" value={overview.delivered} hint="esito positivo dal Sistema di Interscambio" tone={overview.delivered ? "success" : undefined} />
          <Stat label="Scartate" value={overview.rejected} hint="richiedono correzione e reinvio" tone={overview.rejected ? "danger" : undefined} />
          <Stat label="Da verificare" value={overview.requires_attention} hint="trasmissione incerta o da riconciliare" tone={overview.requires_attention ? "warn" : undefined} />
        </div>
      ) : <Skeleton kind="stats" rows={5} />}

      <div className="stack">
        <ProviderPanel />

        {error && <ErrorBanner error={error} />}
        {act.error && <ErrorBanner error={act.error} />}
        {reconcile.error && <ErrorBanner error={reconcile.error} />}
        {dispatch.error && <ErrorBanner error={dispatch.error} />}

        <Section
          title="Fatture"
          actions={data && <span className="text-xs muted">{data.total} in archivio</span>}
          flush
          footer={data && data.total > data.page_size ? <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} /> : undefined}
        >
          {isLoading ? <Skeleton kind="table" rows={6} /> : !data || data.items.length === 0 ? (
            <EmptyState title="Nessuna fattura" icon={<FileText size={20} strokeWidth={1.8} />}
                        action={<button className="btn btn--primary btn--sm" onClick={() => setCreating(true)}>Crea la prima bozza</button>}>
              Le bozze si finalizzano con numero e data, poi si trasmettono allo SdI dal canale configurato.
            </EmptyState>
          ) : (
            <table className="table table--flush table--static">
              <thead>
                <tr>
                  <th>Fattura</th><th>Data</th><th className="th--num">Totale</th>
                  <th>Stato</th><th>Esito SdI</th><th className="right">Azione</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((i) => {
                  const problem = ["rejected", "delivery_failed", "transmission_unknown", "requires_reconciliation"].includes(i.status);
                  return (
                    <tr key={i.id}>
                      <td>
                        <div className="table__primary num">
                          {i.number ? `${i.series}${i.number}/${i.fiscal_year}` : <span className="muted">Bozza senza numero</span>}
                        </div>
                        <div className="table__sub">
                          {companyName(i.company_id) ?? (i.provider_key ? `via ${i.provider_key}` : "in attesa di canale")}
                          {i.notes ? ` · ${i.notes}` : ""}
                        </div>
                      </td>
                      <td className="num nowrap">{dateIt(i.issue_date)}</td>
                      <td className="td--num strong">{eur(i.total_amount)}</td>
                      <td><StatusBadge status={i.status} /></td>
                      <td>
                        {i.sdi_status
                          ? <Dot tone={problem ? "danger" : statusTone(i.sdi_status)} title={i.sdi_status}>{SDI_LABEL[i.sdi_status] ?? statusLabel(i.sdi_status)}</Dot>
                          : <span className="muted">—</span>}
                      </td>
                      <td className="right nowrap">
                        {i.status === "draft" && canSubmit && (
                          <button className="btn btn--ghost btn--sm" onClick={() => act.mutate({ id: i.id, op: "finalize" })} disabled={act.isPending}>
                            Finalizza
                          </button>
                        )}
                        {["ready_to_send", "rejected", "delivery_failed"].includes(i.status) && canSubmit && (
                          <button className="btn btn--accent btn--sm" onClick={() => act.mutate({ id: i.id, op: "send" })} disabled={act.isPending}>
                            {i.status === "ready_to_send" ? "Invia" : "Reinvia"}
                          </button>
                        )}
                        {["transmission_unknown", "requires_reconciliation"].includes(i.status) && canSubmit && (
                          <button className="btn btn--ghost btn--sm" onClick={() => reconcile.mutate(i.id)} disabled={reconcile.isPending}>
                            Riconcilia
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Section>
      </div>

      {creating && (
        <Modal title="Nuova fattura" subtitle="Nasce come bozza: numero e data arrivano con la finalizzazione." onClose={() => setCreating(false)}>
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
              <Field label="Cliente *" htmlFor="cliente" span2>
                <select id="cliente" className="select" name="company_id" required>
                  <option value="">— seleziona —</option>
                  {companies?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
                </select>
              </Field>
              <Field label="Descrizione prestazione *" htmlFor="descrizione-prestazione" span2>
                <input id="descrizione-prestazione" className="input" name="description" required />
              </Field>
              <Field label="Quantità" htmlFor="quantita">
                <input id="quantita" className="input input--num" name="quantity" type="number" step="0.01" defaultValue={1} min="0.01" />
              </Field>
              <Field label="Prezzo unitario €" htmlFor="prezzo-unitario">
                <input id="prezzo-unitario" className="input input--num" name="unit_price" type="number" step="0.01" min="0" required />
              </Field>
              <Field label="Aliquota IVA %" htmlFor="aliquota-iva">
                <input id="aliquota-iva" className="input input--num" name="vat_rate" type="number" step="0.01" defaultValue={22} min="0" />
              </Field>
              <Field label="Note" htmlFor="note">
                <input id="note" className="input" name="notes" />
              </Field>
            </div>
            <div className="cluster cluster--end mt-3">
              <button type="button" className="btn btn--ghost" onClick={() => setCreating(false)}>Annulla</button>
              <button type="submit" className="btn btn--primary" disabled={create.isPending}>Crea bozza</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
