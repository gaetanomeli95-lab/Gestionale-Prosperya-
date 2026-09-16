import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Download, FilePlus2, Link2, Plus, Upload } from "lucide-react";
import { api, apiDownload, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  CompanyListItem, F24Draft, FiscalDeadline, FiscalRuleSetsResponse,
  FiscalSnapshot, Page, Settlement, VatEntry, VatRegister,
} from "../api/types";
import { Badge, Card, EmptyState, ErrorBanner, Modal, Spinner, StatusBadge } from "../components/ui";
import { dateIt, dateTimeIt, money } from "../lib/format";
import { ActionList } from "./HubPage";

const MONTHS = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];
const WRITE_ROLES = ["admin", "management", "consultant", "backoffice", "client_admin", "client_operator"];
const VALIDATE_ROLES = ["admin", "management", "consultant", "client_admin", "client_operator"];

type Tab = "panoramica" | "registro" | "liquidazioni" | "f24" | "scadenze" | "regole";

const TABS: { key: Tab; label: string }[] = [
  { key: "panoramica", label: "Panoramica" },
  { key: "registro", label: "Registro IVA" },
  { key: "liquidazioni", label: "Liquidazioni" },
  { key: "f24", label: "F24" },
  { key: "scadenze", label: "Scadenze" },
  { key: "regole", label: "Tracciabilità e regole" },
];

const TREATMENT_LABEL: Record<string, string> = {
  supported: "supportata",
  unsupported: "non supportata",
  requires_review: "da verificare",
  insufficient_data: "dati insufficienti",
};

const ENTRY_TEMPLATE = JSON.stringify(
  [{
    source_ref: "REG-2026-001", direction: "sale",
    competence_date: "2026-10-15", taxable_amount: "1000.00",
    vat_amount: "220.00", vat_rate: "22",
    document_number: "FT 120/2026", document_date: "2026-10-15",
    counterparty_name: "Cliente Esempio S.r.l.", counterparty_vat: "01234567890",
  }],
  null, 2,
);

/** Decimal string or the explicit "no evidence" marker — never a fake 0. */
function Val({ v, suffix }: { v: string | null | undefined; suffix?: string }) {
  if (v == null) return <span className="tre-null" title="Nessuna evidenza disponibile: non è zero">n.d.</span>;
  return <>{suffix ? `${v}${suffix}` : money(v)}</>;
}

function shortId(id: string) {
  return id.slice(0, 8);
}

export default function FiscalPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [year, setYear] = useState(2026);
  const [tab, setTab] = useState<Tab>("panoramica");
  const [regMonth, setRegMonth] = useState<number | 0>(0);
  const [calcPeriod, setCalcPeriod] = useState({ period_no: 10, frequency: "monthly" });
  const [selSettlement, setSelSettlement] = useState<string | null>(null);
  const [selDraft, setSelDraft] = useState<string | null>(null);
  const [showEntry, setShowEntry] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [validateFor, setValidateFor] = useState<Settlement | null>(null);
  const [confirmFor, setConfirmFor] = useState<VatEntry | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);

  const canWrite = !!user && WRITE_ROLES.includes(user.role);
  const canValidate = !!user && VALIDATE_ROLES.includes(user.role);

  const companies = useQuery({
    queryKey: ["companies", "all"],
    queryFn: () => api.get<Page<CompanyListItem>>("/companies?page=1&page_size=200"),
  });
  const cid = params.get("company") || companies.data?.items[0]?.id || "";
  const setCompany = (id: string) => setParams(id ? { company: id } : {});

  const snapshot = useQuery({
    queryKey: ["fiscal", cid, year],
    queryFn: () => api.get<FiscalSnapshot>(`/fiscal/companies/${cid}/snapshot?year=${year}`),
    enabled: !!cid,
  });
  const register = useQuery({
    queryKey: ["fiscal-register", cid, year, regMonth],
    queryFn: () => api.get<VatRegister>(
      `/fiscal/companies/${cid}/vat-entries?year=${year}` +
      (regMonth ? `&period_no=${regMonth}&frequency=monthly` : "")),
    enabled: !!cid && tab === "registro",
  });
  const settlement = useQuery({
    queryKey: ["fiscal-settlement", cid, selSettlement],
    queryFn: () => api.get<Settlement>(`/fiscal/companies/${cid}/settlements/${selSettlement}`),
    enabled: !!cid && !!selSettlement,
  });
  const draft = useQuery({
    queryKey: ["fiscal-f24", cid, selDraft],
    queryFn: () => api.get<F24Draft>(`/fiscal/companies/${cid}/f24/${selDraft}`),
    enabled: !!cid && !!selDraft,
  });
  const ruleSets = useQuery({
    queryKey: ["fiscal-rules"],
    queryFn: () => api.get<FiscalRuleSetsResponse>("/fiscal/rule-sets"),
    enabled: tab === "regole",
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["fiscal", cid] });
    qc.invalidateQueries({ queryKey: ["fiscal-register", cid] });
    qc.invalidateQueries({ queryKey: ["fiscal-settlement", cid] });
    qc.invalidateQueries({ queryKey: ["fiscal-f24", cid] });
    qc.invalidateQueries({ queryKey: ["hub"] });
    qc.invalidateQueries({ queryKey: ["cockpit"] });
  };
  const onError = (e: unknown) => setActionError(e);

  const calculate = useMutation({
    mutationFn: () => api.post<Settlement>(
      `/fiscal/companies/${cid}/settlements/calculate`,
      { year, period_no: calcPeriod.period_no, frequency: calcPeriod.frequency }),
    onSuccess: (s) => { setSelSettlement(s.id); setActionError(null); refresh(); },
    onError,
  });
  const validateSettlement = useMutation({
    mutationFn: (payload: { note: string; acknowledge_warnings: boolean }) =>
      api.post(`/fiscal/companies/${cid}/settlements/${validateFor!.id}/validate`, payload),
    onSuccess: () => { setValidateFor(null); setActionError(null); refresh(); },
    onError,
  });
  const confirmEntry = useMutation({
    mutationFn: (payload: { treatment: string; deductible: boolean | null; reason: string }) =>
      api.post(`/fiscal/companies/${cid}/vat-entries/${confirmFor!.id}/confirm`, payload),
    onSuccess: () => { setConfirmFor(null); setActionError(null); refresh(); },
    onError,
  });
  const createEntry = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post(`/fiscal/companies/${cid}/vat-entries`, payload),
    onSuccess: () => { setShowEntry(false); setActionError(null); refresh(); },
    onError,
  });
  const importEntries = useMutation({
    mutationFn: (rowsJson: string) =>
      api.post(`/fiscal/companies/${cid}/vat-entries/import`, { rows: JSON.parse(rowsJson) }),
    onSuccess: () => { setShowImport(false); setActionError(null); refresh(); },
    onError,
  });
  const linkInvoices = useMutation({
    mutationFn: () => api.post(`/fiscal/companies/${cid}/vat-entries/from-invoices`),
    onSuccess: () => { setActionError(null); refresh(); },
    onError,
  });
  const generateF24 = useMutation({
    mutationFn: (settlementId: string) =>
      api.post<F24Draft>(`/fiscal/companies/${cid}/f24/generate`, { settlement_id: settlementId }),
    onSuccess: (d) => { setSelDraft(d.id); setTab("f24"); setActionError(null); refresh(); },
    onError,
  });
  const transitionF24 = useMutation({
    mutationFn: (payload: { draftId: string; action: "validate" | "approve"; note?: string }) =>
      api.post(`/fiscal/companies/${cid}/f24/${payload.draftId}/${payload.action}`,
               { note: payload.note }),
    onSuccess: () => { setActionError(null); refresh(); },
    onError,
  });
  const exportF24 = useMutation({
    mutationFn: (payload: { draftId: string; format: "json" | "csv" }) =>
      apiDownload(`/fiscal/companies/${cid}/f24/${payload.draftId}/export`,
                  { format: payload.format }),
    onSuccess: () => { setActionError(null); refresh(); },
    onError,
  });

  if (companies.isLoading) return <Spinner />;
  if (companies.error) return <ErrorBanner error={companies.error} />;
  if (!cid) return <EmptyState>Crea prima un'azienda per usare il workspace fiscale.</EmptyState>;

  const snap = snapshot.data;
  const latest = snap?.latest_settlement ?? null;
  const detail = settlement.data ?? (selSettlement === latest?.id ? latest : null);
  const company = companies.data?.items.find((c) => c.id === cid);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Fisco · IVA e F24</h1>
          <div className="page-head__meta">
            Registro IVA, liquidazioni deterministiche, validazione umana, bozze F24 e scadenze —
            la piattaforma non calcola mai fuori dal motore versionato.
          </div>
        </div>
        <div className="toolbar" style={{ margin: 0 }}>
          <select className="select" value={cid} onChange={(e) => setCompany(e.target.value)} style={{ maxWidth: 260 }}>
            {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
          </select>
          <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 90 }}>
            {[2024, 2025, 2026, 2027].map((y) => <option key={y}>{y}</option>)}
          </select>
          <Link className="btn btn--ghost" to={`/cockpit/${cid}`}>Cockpit</Link>
          <Link className="btn btn--ghost" to="/treasury">Tesoreria</Link>
        </div>
      </div>

      {actionError ? (
        <ErrorBanner error={actionError instanceof ApiError ? actionError : new Error("Operazione non riuscita")} />
      ) : null}
      {snapshot.isLoading && <Spinner />}
      {snapshot.error && <ErrorBanner error={snapshot.error} />}

      {snap && (
        <>
          <div className="tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t.key} role="tab" aria-selected={tab === t.key}
                      className={`tab${tab === t.key ? " tab--active" : ""}`}
                      onClick={() => setTab(t.key)}>
                {t.label}
              </button>
            ))}
          </div>

          {tab === "panoramica" && (
            <Panoramica snap={snap} canWrite={canWrite}
                        onCalculate={() => setTab("liquidazioni")}
                        onOpenSettlement={(id) => { setSelSettlement(id); setTab("liquidazioni"); }}
                        onOpenDraft={(id) => { setSelDraft(id); setTab("f24"); }} />
          )}

          {tab === "registro" && (
            <Registro register={register} canWrite={canWrite} year={year}
                      regMonth={regMonth} setRegMonth={setRegMonth}
                      onNew={() => setShowEntry(true)} onImport={() => setShowImport(true)}
                      onLinkInvoices={() => linkInvoices.mutate()}
                      linkPending={linkInvoices.isPending}
                      onConfirm={setConfirmFor} />
          )}

          {tab === "liquidazioni" && (
            <Liquidazioni snap={snap} detail={detail} detailLoading={settlement.isLoading}
                          detailError={settlement.error}
                          canWrite={canWrite} canValidate={canValidate}
                          calcPeriod={calcPeriod} setCalcPeriod={setCalcPeriod}
                          calcPending={calculate.isPending}
                          onCalculate={() => calculate.mutate()}
                          onSelect={setSelSettlement}
                          onValidate={setValidateFor}
                          onGenerateF24={(id) => generateF24.mutate(id)}
                          genPending={generateF24.isPending}
                          onOpenDraft={(id) => { setSelDraft(id); setTab("f24"); }}
                          onOpenRegister={(p) => { setRegMonth(p.period_no); setTab("registro"); }} />
          )}

          {tab === "f24" && (
            <F24Tab snap={snap} draft={draft.data ?? null} draftLoading={draft.isPending}
                    selDraft={selDraft} onSelect={setSelDraft} canValidate={canValidate}
                    onTransition={(draftId, action) =>
                      transitionF24.mutate({ draftId, action })}
                    transPending={transitionF24.isPending}
                    onExport={(draftId, format) => exportF24.mutate({ draftId, format })}
                    exportPending={exportF24.isPending}
                    onOpenSettlement={(id) => { setSelSettlement(id); setTab("liquidazioni"); }} />
          )}

          {tab === "scadenze" && <Scadenze deadlines={snap.deadlines} />}

          {tab === "regole" && <Regole rules={ruleSets} engineVersion={snap.engine_version}
                                      limitations={snap.limitations}
                                      transmission={snap.transmission} />}

          <Card className="card__pad" style={{ marginTop: 16 }}>
            <div className="card__title">Perimetro e limitazioni dichiarate</div>
            <ul className="mgmt-issues">
              {snap.limitations.map((l) => <li key={l}>{l}</li>)}
              <li>{snap.transmission.note}</li>
            </ul>
            <div className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>
              Motore <span className="mono">{snap.engine_version}</span> ·
              azienda {company?.legal_name ?? cid} · anno {snap.year} · dati al {snap.as_of}
            </div>
          </Card>
        </>
      )}

      {showEntry && (
        <EntryModal onClose={() => setShowEntry(false)}
                    onSave={(p) => createEntry.mutate(p)} pending={createEntry.isPending} />
      )}
      {showImport && (
        <ImportModal onClose={() => setShowImport(false)}
                     onSave={(json) => importEntries.mutate(json)}
                     pending={importEntries.isPending} />
      )}
      {validateFor && (
        <ValidateModal settlement={validateFor} canSubmit={!validateSettlement.isPending}
                       onClose={() => setValidateFor(null)}
                       onSave={(p) => validateSettlement.mutate(p)} />
      )}
      {confirmFor && (
        <ConfirmModal entry={confirmFor} pending={confirmEntry.isPending}
                      onClose={() => setConfirmFor(null)}
                      onSave={(p) => confirmEntry.mutate(p)} />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Panoramica
// ---------------------------------------------------------------------------

function Panoramica({ snap, canWrite, onCalculate, onOpenSettlement, onOpenDraft }: {
  snap: FiscalSnapshot; canWrite: boolean;
  onCalculate: () => void;
  onOpenSettlement: (id: string) => void;
  onOpenDraft: (id: string) => void;
}) {
  const latest = snap.latest_settlement;
  const nextDeadline = snap.deadlines
    .filter((d) => d.due_date && d.status !== "cancelled")
    .sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1))[0];

  return (
    <>
      <ActionList actions={snap.warnings.map((w) => ({
        ...w, priority: 0, priority_version: "",
        formula: w.formula ?? "", formula_version: w.formula_version ?? snap.engine_version,
        evidence: w.evidence ?? {}, action_required: w.action_required ?? false,
      }))} />

      <div className="kpi-grid" style={{ marginTop: 16 }}>
        <Card className="kpi kpi--edge-primary">
          <div className="kpi__label">IVA a debito</div>
          <div className="kpi__value mono"><Val v={latest?.debit_total} /></div>
          <div className="kpi__hint">
            {latest ? `${latest.period?.label ?? ""} · v${latest.version}` : "nessuna liquidazione"}
          </div>
        </Card>
        <Card className="kpi kpi--edge-teal">
          <div className="kpi__label">IVA a credito</div>
          <div className="kpi__value mono"><Val v={latest?.credit_total} /></div>
          <div className="kpi__hint">
            riporto credito <Val v={latest?.prior_credit} />
          </div>
        </Card>
        <Card className={`kpi kpi--edge-warn ${latest?.status === "review_required" ? "kpi--alert" : ""}`}>
          <div className="kpi__label">Posizione netta</div>
          <div className="kpi__value mono"><Val v={latest?.net_position} /></div>
          <div className="kpi__hint">
            {latest ? <StatusBadge status={latest.status} /> : "dati insufficienti"}
            {latest?.unsupported_count ? ` · ${latest.unsupported_count} non utilizzabili` : ""}
          </div>
        </Card>
        <Card className="kpi kpi--edge-accent">
          <div className="kpi__label">Prossima scadenza</div>
          <div className="kpi__value mono" style={{ fontSize: "1.2rem" }}>
            {nextDeadline?.due_date
              ? <>{nextDeadline.due_date} · <Val v={nextDeadline.amount} /></>
              : <span className="tre-null">n.d.</span>}
          </div>
          <div className="kpi__hint">
            {nextDeadline ? <StatusBadge status={nextDeadline.status} /> : "nessuna scadenza aperta"}
          </div>
        </Card>
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <Card className="card__pad">
          <div className="card__title">Stato del periodo</div>
          {latest ? (
            <div className="dl">
              <dt>Periodo</dt>
              <dd>{latest.period?.label} <StatusBadge status={latest.period?.status} /></dd>
              <dt>Liquidazione</dt>
              <dd>
                v{latest.version} <StatusBadge status={latest.status} /> ·{" "}
                <a role="button" tabIndex={0} style={{ cursor: "pointer" }}
                   onClick={() => onOpenSettlement(latest.id)}>dettaglio <ArrowRight size={11} style={{ verticalAlign: -1 }} /></a>
              </dd>
              <dt>Validazione</dt>
              <dd>
                {latest.status === "validated"
                  ? <>validata il {dateTimeIt(latest.validated_at)} da operatore</>
                  : "non validata — richiede conferma umana"}
              </dd>
              <dt>Versamento dovuto</dt>
              <dd className="mono"><Val v={latest.payable_amount} /></dd>
              <dt>Voci IVA contate</dt>
              <dd className="mono">{latest.source_count} fonti · {latest.unsupported_count} escluse</dd>
              <dt>F24 collegato</dt>
              <dd>
                {latest.f24_draft_id
                  ? <a role="button" tabIndex={0} style={{ cursor: "pointer" }}
                       onClick={() => onOpenDraft(latest.f24_draft_id!)}>bozza {shortId(latest.f24_draft_id)}</a>
                  : <span className="muted">nessuna bozza</span>}
              </dd>
              <dt>Impatto sulla cassa</dt>
              <dd>
                {latest.deadline?.open_item_id
                  ? <Link to="/treasury">partita di tesoreria {shortId(latest.deadline.open_item_id)} →</Link>
                  : <span className="muted">nessuna partita: impatto cassa solo dopo la validazione</span>}
              </dd>
            </div>
          ) : (
            <EmptyState>
              Nessuna liquidazione per l'anno selezionato: la posizione IVA non è
              calcolabile con i dati presenti — non è pari a zero.
              {canWrite && <> <a role="button" tabIndex={0} onClick={onCalculate} style={{ cursor: "pointer" }}>Calcola un periodo</a></>}
            </EmptyState>
          )}
        </Card>

        <Card className="card__pad">
          <div className="card__title">Operazioni da verificare</div>
          {snap.counters.pending_entries === 0 ? (
            <EmptyState>Nessuna voce IVA in attesa di verifica umana.</EmptyState>
          ) : (
            <table className="table">
              <thead>
                <tr><th>Documento</th><th>Competenza</th><th>Controparte</th>
                    <th style={{ textAlign: "right" }}>IVA</th><th>Stato</th></tr>
              </thead>
              <tbody>
                {snap.pending_entries.map((e) => (
                  <tr key={e.id} style={{ cursor: "default" }}>
                    <td>{e.document_number ?? "—"}</td>
                    <td className="mono">{e.competence_date}</td>
                    <td>{e.counterparty_name ?? "—"}</td>
                    <td className="mono" style={{ textAlign: "right" }}><Val v={e.vat_amount} /></td>
                    <td><StatusBadge status={e.treatment} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="card__title" style={{ marginTop: 18 }}>Contatori anno {snap.year}</div>
          <div className="dl">
            <dt>Periodi tracciati</dt><dd className="mono">{snap.counters.periods}</dd>
            <dt>Liquidazioni calcolate</dt><dd className="mono">{snap.counters.calculated}</dd>
            <dt>Liquidazioni validate</dt><dd className="mono">{snap.counters.validated}</dd>
            <dt>Scadenze aperte</dt><dd className="mono">{snap.counters.open_deadlines}</dd>
            <dt>Bozze F24</dt><dd className="mono">{snap.counters.f24_drafts}</dd>
          </div>
        </Card>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Registro IVA
// ---------------------------------------------------------------------------

function Registro({ register, canWrite, year, regMonth, setRegMonth, onNew, onImport,
                    onLinkInvoices, linkPending, onConfirm }: {
  register: UseQueryResult<VatRegister>;
  canWrite: boolean; year: number; regMonth: number | 0;
  setRegMonth: (m: number | 0) => void;
  onNew: () => void; onImport: () => void; onLinkInvoices: () => void;
  linkPending: boolean; onConfirm: (e: VatEntry) => void;
}) {
  const reg = register.data;
  return (
    <>
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <select className="select" value={regMonth}
                onChange={(e) => setRegMonth(Number(e.target.value) as number | 0)}
                style={{ width: 170 }}>
          <option value={0}>Anno {year} intero</option>
          {MONTHS.slice(1).map((m, i) => <option key={m} value={i + 1}>{m} {year}</option>)}
        </select>
        {canWrite && (
          <>
            <button className="btn btn--ghost" onClick={onNew}><Plus size={14} /> Nuova voce</button>
            <button className="btn btn--ghost" onClick={onImport}><Upload size={14} /> Importa</button>
            <button className="btn btn--ghost" onClick={onLinkInvoices} disabled={linkPending}>
              <Link2 size={14} /> Deriva da fatture
            </button>
          </>
        )}
        {reg && (
          <span className="muted" style={{ fontSize: "0.78rem", marginLeft: "auto" }}>
            {reg.counters.effective} voci efficaci · {reg.counters.sales} attive ·{" "}
            {reg.counters.purchases} passive ·{" "}
            <strong>{reg.counters.requires_review} da verificare</strong>
          </span>
        )}
      </div>

      {register.isLoading && <Spinner />}
      {register.error && <ErrorBanner error={register.error} />}
      {reg && (
        <>
          {reg.pending_review.length > 0 && (
            <Card className="card__pad" style={{ marginBottom: 16 }}>
              <div className="card__title">
                Da verificare prima del calcolo <Badge tone="warning">{reg.pending_review.length}</Badge>
              </div>
              <table className="table">
                <thead>
                  <tr><th>Documento</th><th>Competenza</th><th>Controparte</th>
                      <th style={{ textAlign: "right" }}>Imponibile</th>
                      <th style={{ textAlign: "right" }}>IVA</th><th>Motivo</th><th></th></tr>
                </thead>
                <tbody>
                  {reg.pending_review.map((e) => (
                    <tr key={e.id} style={{ cursor: "default" }}>
                      <td>{e.document_number ?? "—"}</td>
                      <td className="mono">{e.competence_date}</td>
                      <td>{e.counterparty_name ?? "—"}</td>
                      <td className="mono" style={{ textAlign: "right" }}><Val v={e.taxable_amount} /></td>
                      <td className="mono" style={{ textAlign: "right" }}><Val v={e.vat_amount} /></td>
                      <td className="muted" style={{ fontSize: "0.75rem", maxWidth: 320 }}>
                        {e.treatment_reason ?? TREATMENT_LABEL[e.treatment] ?? e.treatment}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {canWrite && (
                          <button className="btn btn--ghost btn--sm" onClick={() => onConfirm(e)}>
                            Verifica
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          <Card className="card__pad">
            <div className="card__title">
              Registro IVA · {reg.period.label}
              <span className="muted" style={{ fontWeight: 400, marginLeft: 8 }}>
                {reg.period.start} → {reg.period.end}
              </span>
            </div>
            {reg.entries.length === 0 ? (
              <EmptyState>Nessuna voce IVA nel periodo selezionato.</EmptyState>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Competenza</th><th>Direzione</th><th>Documento</th><th>Controparte</th>
                    <th style={{ textAlign: "right" }}>Imponibile</th>
                    <th style={{ textAlign: "right" }}>IVA</th>
                    <th>Aliq./Natura</th><th>Trattamento</th><th>Fonte</th>
                  </tr>
                </thead>
                <tbody>
                  {reg.entries.map((e) => (
                    <tr key={e.id} style={{ cursor: "default", opacity: e.superseded ? 0.45 : 1 }}>
                      <td className="mono">{e.competence_date}</td>
                      <td>{e.direction === "sale" ? "Vendita" : "Acquisto"}</td>
                      <td>
                        {e.document_number ?? "—"}
                        {e.invoice_id && (
                          <div className="muted" style={{ fontSize: "0.7rem" }}>
                            fattura {shortId(e.invoice_id)}
                          </div>
                        )}
                      </td>
                      <td>
                        {e.counterparty_name ?? "—"}
                        {e.counterparty_vat && (
                          <div className="muted" style={{ fontSize: "0.7rem" }}>{e.counterparty_vat}</div>
                        )}
                      </td>
                      <td className="mono" style={{ textAlign: "right" }}><Val v={e.taxable_amount} /></td>
                      <td className="mono" style={{ textAlign: "right" }}><Val v={e.vat_amount} /></td>
                      <td className="mono" style={{ fontSize: "0.78rem" }}>
                        {e.vat_nature ? `N${e.vat_nature}` : e.vat_rate ? `${e.vat_rate}%` : "—"}
                        {e.direction === "purchase" && e.deductible === false && (
                          <div className="muted" style={{ fontSize: "0.7rem" }}>indetraibile</div>
                        )}
                      </td>
                      <td>
                        <StatusBadge status={e.treatment} />
                        {e.superseded && <div className="muted" style={{ fontSize: "0.7rem" }}>sostituita da verifica</div>}
                      </td>
                      <td className="muted mono" style={{ fontSize: "0.7rem" }}>{e.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Liquidazioni
// ---------------------------------------------------------------------------

function Liquidazioni({ snap, detail, detailLoading, detailError, canWrite, canValidate,
                        calcPeriod, setCalcPeriod, calcPending, onCalculate,
                        onSelect, onValidate, onGenerateF24, genPending,
                        onOpenDraft, onOpenRegister }: {
  snap: FiscalSnapshot; detail: Settlement | null; detailLoading: boolean;
  detailError: unknown; canWrite: boolean; canValidate: boolean;
  calcPeriod: { period_no: number; frequency: string };
  setCalcPeriod: (p: { period_no: number; frequency: string }) => void;
  calcPending: boolean; onCalculate: () => void;
  onSelect: (id: string) => void;
  onValidate: (s: Settlement) => void;
  onGenerateF24: (settlementId: string) => void; genPending: boolean;
  onOpenDraft: (id: string) => void;
  onOpenRegister: (p: { period_no: number }) => void;
}) {
  const maxPeriod = calcPeriod.frequency === "monthly" ? 12 : 4;
  return (
    <>
      {canWrite && (
        <Card className="card__pad" style={{ marginBottom: 16 }}>
          <div className="card__title">Calcola / ricalcola liquidazione</div>
          <div className="toolbar">
            <select className="select" value={calcPeriod.frequency}
                    onChange={(e) => setCalcPeriod({ period_no: 1, frequency: e.target.value })}
                    style={{ width: 140 }}>
              <option value="monthly">Mensile</option>
              <option value="quarterly">Trimestrale</option>
            </select>
            <select className="select" value={calcPeriod.period_no}
                    onChange={(e) => setCalcPeriod({ ...calcPeriod, period_no: Number(e.target.value) })}
                    style={{ width: 160 }}>
              {Array.from({ length: maxPeriod }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {calcPeriod.frequency === "monthly" ? `${MONTHS[n]} ${snap.year}` : `${n}° trimestre ${snap.year}`}
                </option>
              ))}
            </select>
            <button className="btn" onClick={onCalculate} disabled={calcPending}>
              {calcPending ? "Calcolo…" : "Calcola con il motore"}
            </button>
            <span className="muted" style={{ fontSize: "0.75rem" }}>
              Un ricalcolo crea una nuova versione: la precedente resta storicizzata, mai sovrascritta.
            </span>
          </div>
        </Card>
      )}

      <div className="grid-2">
        <Card className="card__pad">
          <div className="card__title">Periodi {snap.year}</div>
          {snap.periods.length === 0 ? (
            <EmptyState>
              Nessun periodo fiscale: i periodi nascono al primo calcolo.
            </EmptyState>
          ) : (
            <table className="table">
              <thead>
                <tr><th>Periodo</th><th>Stato periodo</th><th>Liquidazione</th>
                    <th style={{ textAlign: "right" }}>Posizione netta</th>
                    <th style={{ textAlign: "right" }}>Da versare</th></tr>
              </thead>
              <tbody>
                {snap.periods.map((p) => (
                  <tr key={p.id}
                      onClick={() => p.settlement && onSelect(p.settlement.id)}
                      style={{ cursor: p.settlement ? "pointer" : "default" }}>
                    <td>
                      {p.label}
                      <div className="muted" style={{ fontSize: "0.7rem" }}>
                        {p.start_date} → {p.end_date} · {p.frequency === "monthly" ? "mensile" : "trimestrale"}
                      </div>
                    </td>
                    <td><StatusBadge status={p.status} /></td>
                    <td>
                      {p.settlement
                        ? <>v{p.settlement.version} <StatusBadge status={p.settlement.status} />
                           {p.settlement.unsupported_count > 0 && (
                             <div className="muted" style={{ fontSize: "0.7rem" }}>
                               {p.settlement.unsupported_count} voci escluse
                             </div>)}</>
                        : <span className="muted">non calcolata</span>}
                    </td>
                    <td className="mono" style={{ textAlign: "right" }}><Val v={p.settlement?.net_position} /></td>
                    <td className="mono" style={{ textAlign: "right" }}><Val v={p.settlement?.payable_amount} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card className="card__pad">
          <div className="card__title">
            Dettaglio liquidazione
            {detail && (
              <span className="muted" style={{ fontWeight: 400, marginLeft: 8 }}>
                {detail.period?.label} · v{detail.version} · {shortId(detail.id)}
              </span>
            )}
          </div>
          {detailLoading && <Spinner />}
          {detailError ? <ErrorBanner error={detailError} /> : null}
          {!detail && !detailLoading && (
            <EmptyState>Seleziona una liquidazione dalla tabella dei periodi.</EmptyState>
          )}
          {detail && <SettlementDetail s={detail} canValidate={canValidate}
                                       onValidate={() => onValidate(detail)}
                                       onGenerateF24={() => onGenerateF24(detail.id)}
                                       genPending={genPending}
                                       onOpenDraft={onOpenDraft}
                                       onOpenRegister={onOpenRegister} />}
        </Card>
      </div>
    </>
  );
}

function SettlementDetail({ s, canValidate, onValidate, onGenerateF24, genPending,
                            onOpenDraft, onOpenRegister }: {
  s: Settlement; canValidate: boolean; onValidate: () => void;
  onGenerateF24: () => void; genPending: boolean;
  onOpenDraft: (id: string) => void;
  onOpenRegister: (p: { period_no: number }) => void;
}) {
  const critical = s.warnings.filter((w) => w.severity === "critical");
  return (
    <>
      <div className="dl">
        <dt>Esito</dt>
        <dd><StatusBadge status={s.status} /> {s.outcome && <span className="muted">· {s.outcome}</span>}</dd>
        <dt>IVA a debito</dt>
        <dd className="mono"><Val v={s.debit_total} /></dd>
        <dt>IVA a credito</dt>
        <dd className="mono"><Val v={s.credit_total} /></dd>
        <dt>Credito periodo prec.</dt>
        <dd className="mono"><Val v={s.prior_credit} /></dd>
        <dt>Debito prec. sotto soglia</dt>
        <dd className="mono"><Val v={s.prior_small_debit} /></dd>
        {s.interest_amount != null && (
          <>
            <dt>Interessi trimestrali 1%</dt>
            <dd className="mono"><Val v={s.interest_amount} /></dd>
          </>
        )}
        <dt>Posizione netta</dt>
        <dd className="mono"><strong><Val v={s.net_position} /></strong></dd>
        <dt>Da versare</dt>
        <dd className="mono"><strong><Val v={s.payable_amount} /></strong></dd>
        <dt>Riporto a credito</dt>
        <dd className="mono"><Val v={s.carry_forward_credit} /></dd>
        <dt>Riporto a debito</dt>
        <dd className="mono"><Val v={s.carry_forward_debit} /></dd>
        <dt>Fonti / escluse</dt>
        <dd className="mono">{s.source_count} / {s.unsupported_count}</dd>
        <dt>Calcolata</dt>
        <dd className="mono">{dateTimeIt(s.calculated_at)}</dd>
        <dt>Validazione</dt>
        <dd>
          {s.status === "validated"
            ? <>validata il {dateTimeIt(s.validated_at)}{s.validation_note ? ` · "${s.validation_note}"` : ""}</>
            : s.status === "superseded"
              ? <span className="muted">superata da una versione più recente</span>
              : "in attesa di validazione umana"}
        </dd>
        {s.deadline && (
          <>
            <dt>Scadenza</dt>
            <dd>
              <StatusBadge status={s.deadline.status} />{" "}
              {s.deadline.due_date ?? "data da confermare"}
              {s.deadline.deferral_reason && (
                <div className="muted" style={{ fontSize: "0.72rem" }}>{s.deadline.deferral_reason}</div>
              )}
            </dd>
          </>
        )}
        <dt>F24</dt>
        <dd>
          {s.f24_draft_id
            ? <a role="button" tabIndex={0} style={{ cursor: "pointer" }}
                 onClick={() => onOpenDraft(s.f24_draft_id!)}>bozza {shortId(s.f24_draft_id)} →</a>
            : <span className="muted">nessuna bozza</span>}
        </dd>
      </div>

      {s.warnings.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="card__title">Segnalazioni del motore</div>
          <ul className="mgmt-issues">
            {s.warnings.map((w) => (
              <li key={w.code}>
                <Badge tone={w.severity === "critical" ? "danger" : w.severity === "warning" ? "warning" : "info"}>
                  {w.severity}
                </Badge>{" "}
                <strong>{w.title}</strong> — {w.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="toolbar" style={{ marginTop: 14 }}>
        {canValidate && s.status !== "validated" && s.status !== "superseded" && (
          <button className="btn" onClick={onValidate}>
            <FilePlus2 size={14} /> Valida (umano)
          </button>
        )}
        {canValidate && s.status === "validated" && !s.f24_draft_id
          && s.payable_amount && Number(s.payable_amount) > 0 && (
          <button className="btn" onClick={onGenerateF24} disabled={genPending}>
            Genera bozza F24
          </button>
        )}
        {s.period && (
          <button className="btn btn--ghost" onClick={() => onOpenRegister({ period_no: s.period!.period_no })}>
            Registro del periodo
          </button>
        )}
      </div>
      {critical.length > 0 && (
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          La validazione con segnalazioni critiche richiede una nota di motivazione.
        </div>
      )}

      <details style={{ marginTop: 14 }}>
        <summary className="muted" style={{ fontSize: "0.78rem", cursor: "pointer" }}>
          Tracciabilità completa — fonti, regole e passaggi di calcolo
        </summary>
        <TraceView s={s} />
      </details>
    </>
  );
}

function TraceView({ s }: { s: Settlement }) {
  const t = s.trace;
  const srcTable = (rows: NonNullable<typeof t.debit_sources>, title: string) => (
    <>
      <div className="card__title" style={{ marginTop: 14 }}>{title}</div>
      {rows.length === 0 ? (
        <div className="muted" style={{ fontSize: "0.78rem" }}>Nessuna fonte.</div>
      ) : (
        <table className="table">
          <thead>
            <tr><th>Documento</th><th>Competenza</th><th>Controparte</th>
                <th style={{ textAlign: "right" }}>IVA</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ cursor: "default" }}>
                <td>{r.document_number ?? "—"}</td>
                <td className="mono">{r.competence_date}</td>
                <td>{r.counterparty_name ?? "—"}</td>
                <td className="mono" style={{ textAlign: "right" }}><Val v={r.vat_amount} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );

  return (
    <div style={{ marginTop: 10 }}>
      <div className="dl">
        <dt>Formula</dt>
        <dd className="mono">{t.formula_version} · motore {t.engine_version}</dd>
        {t.rule_set && (
          <>
            <dt>Rule set IVA</dt>
            <dd>
              <span className="mono">{t.rule_set.code} v{t.rule_set.version}</span>{" "}
              <StatusBadge status={t.rule_set.status} />
              <div className="muted" style={{ fontSize: "0.72rem" }}>
                {t.rule_set.source.authority} — {t.rule_set.source.title}
                {t.rule_set.source.legal_reference ? ` · ${t.rule_set.source.legal_reference}` : ""}
                {" · "}vigente dal {t.rule_set.effective_from}
              </div>
            </dd>
          </>
        )}
        {t.calendar_rule_set && (
          <>
            <dt>Rule set calendario</dt>
            <dd className="mono">{t.calendar_rule_set.code} v{t.calendar_rule_set.version}</dd>
          </>
        )}
        {t.prior_source && (
          <>
            <dt>Riporto da</dt>
            <dd className="mono">
              liquidazione {t.prior_source.period} v{t.prior_source.version} ({t.prior_source.status})
            </dd>
          </>
        )}
        {t.due_date && (
          <>
            <dt>Scadenza statutaria</dt>
            <dd className="mono">
              {t.due_date.statutory} → {t.due_date.resolved ?? "da confermare"}{" "}
              <StatusBadge status={t.due_date.status} />
            </dd>
          </>
        )}
      </div>
      {t.formula_steps && t.formula_steps.length > 0 && (
        <>
          <div className="card__title" style={{ marginTop: 14 }}>Passaggi di calcolo</div>
          <ol className="mgmt-issues">
            {t.formula_steps.map((step, i) => <li key={i}>{step}</li>)}
          </ol>
        </>
      )}
      {t.applied_rules && t.applied_rules.length > 0 && (
        <>
          <div className="card__title" style={{ marginTop: 14 }}>Regole applicate</div>
          <ul className="mgmt-issues">
            {t.applied_rules.map((r) => <li key={r} className="mono">{r}</li>)}
          </ul>
        </>
      )}
      {t.due_date?.applied_rules?.length ? (
        <>
          <div className="card__title" style={{ marginTop: 14 }}>Regole di differimento applicate</div>
          <ul className="mgmt-issues">
            {t.due_date.applied_rules.map((r) => <li key={r} className="mono">{r}</li>)}
          </ul>
        </>
      ) : null}
      {srcTable(t.debit_sources ?? [], "IVA a debito — voci che compongono il totale")}
      {srcTable(t.credit_sources ?? [], "IVA a credito — voci che compongono il totale")}
      {(t.excluded_sources?.length ?? 0) > 0 && (
        <>
          <div className="card__title" style={{ marginTop: 14 }}>Voci escluse dal calcolo</div>
          <table className="table">
            <thead>
              <tr><th>Voce</th><th>Trattamento</th><th>Motivo</th>
                  <th style={{ textAlign: "right" }}>IVA</th></tr>
            </thead>
            <tbody>
              {t.excluded_sources!.map((r) => (
                <tr key={r.id} style={{ cursor: "default" }}>
                  <td className="mono" style={{ fontSize: "0.72rem" }}>{shortId(r.id)}</td>
                  <td><StatusBadge status={r.treatment ?? ""} /></td>
                  <td className="muted" style={{ fontSize: "0.75rem" }}>{r.reason ?? "—"}</td>
                  <td className="mono" style={{ textAlign: "right" }}><Val v={r.vat_amount} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {t.unsupported_cases && t.unsupported_cases.length > 0 && (
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>
          Casi fuori perimetro dichiarati dal rule set: {t.unsupported_cases.join("; ")}.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// F24
// ---------------------------------------------------------------------------

function F24Tab({ snap, draft, draftLoading, selDraft, onSelect, canValidate,
                  onTransition, transPending, onExport, exportPending, onOpenSettlement }: {
  snap: FiscalSnapshot; draft: F24Draft | null; draftLoading: boolean;
  selDraft: string | null; onSelect: (id: string) => void;
  canValidate: boolean;
  onTransition: (draftId: string, action: "validate" | "approve") => void;
  transPending: boolean;
  onExport: (draftId: string, format: "json" | "csv") => void;
  exportPending: boolean;
  onOpenSettlement: (id: string) => void;
}) {
  return (
    <div className="grid-2">
      <Card className="card__pad">
        <div className="card__title">Bozze F24</div>
        {snap.f24_drafts.length === 0 ? (
          <EmptyState>
            Nessuna bozza: si genera solo da una liquidazione validata con importo a debito
            (tab Liquidazioni).
          </EmptyState>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Bozza</th><th>Stato</th>
                  <th style={{ textAlign: "right" }}>Saldo</th><th>Scadenza</th></tr>
            </thead>
            <tbody>
              {snap.f24_drafts.map((d) => (
                <tr key={d.id} onClick={() => onSelect(d.id)}
                    style={{ fontWeight: selDraft === d.id ? 600 : 400 }}>
                  <td className="mono">{shortId(d.id)}</td>
                  <td><StatusBadge status={d.status} /></td>
                  <td className="mono" style={{ textAlign: "right" }}><Val v={d.balance} /></td>
                  <td className="mono">{d.due_date ?? "n.d."}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>
          {snap.transmission.note} Gli export JSON/CSV sono documenti interni di
          lavoro, non tracciati telematici.
        </div>
      </Card>

      <Card className="card__pad">
        <div className="card__title">
          Dettaglio bozza {draft && <span className="mono muted" style={{ fontWeight: 400 }}>{shortId(draft.id)}</span>}
        </div>
        {draftLoading && <Spinner />}
        {!draft && !draftLoading && (
          <EmptyState>Seleziona una bozza dalla tabella.</EmptyState>
        )}
        {draft && (
          <>
            <div className="dl">
              <dt>Stato</dt><dd><StatusBadge status={draft.status} /></dd>
              <dt>Liquidazione origine</dt>
              <dd>
                {draft.settlement_id
                  ? <a role="button" tabIndex={0} style={{ cursor: "pointer" }}
                       onClick={() => onOpenSettlement(draft.settlement_id!)}>
                      liquidazione {shortId(draft.settlement_id)} →</a>
                  : "—"}
              </dd>
              <dt>Scadenza collegata</dt>
              <dd className="mono">{draft.deadline_id ? shortId(draft.deadline_id) : "—"}</dd>
              <dt>Scadenza versamento</dt><dd className="mono">{draft.due_date ?? "n.d."}</dd>
              <dt>Totale debiti</dt><dd className="mono"><Val v={draft.total_debit} /></dd>
              <dt>Totale crediti</dt><dd className="mono"><Val v={draft.total_credit} /></dd>
              <dt>Saldo</dt><dd className="mono"><strong><Val v={draft.balance} /></strong></dd>
              <dt>Validata</dt><dd className="mono">{dateTimeIt(draft.validated_at)}</dd>
              <dt>Approvata</dt><dd className="mono">{dateTimeIt(draft.approved_at)}</dd>
              <dt>Esportata</dt>
              <dd>
                {draft.exported_at
                  ? <>{dateTimeIt(draft.exported_at)} · formato {draft.export_format} ·
                     fingerprint <span className="mono" style={{ fontSize: "0.7rem" }}>{draft.export_fingerprint?.slice(0, 16)}…</span></>
                  : "mai esportata"}
              </dd>
            </div>

            {draft.taxpayer && Object.keys(draft.taxpayer).length > 0 && (
              <>
                <div className="card__title" style={{ marginTop: 14 }}>Contribuente (snapshot)</div>
                <div className="dl">
                  {Object.entries(draft.taxpayer).map(([k, v]) => (
                    <Fragment key={k}>
                      <dt>{k.replaceAll("_", " ")}</dt>
                      <dd className="mono">{String(v ?? "—")}</dd>
                    </Fragment>
                  ))}
                </div>
              </>
            )}

            <div className="card__title" style={{ marginTop: 14 }}>Righe F24</div>
            <table className="table">
              <thead>
                <tr><th>Sezione</th><th>Codice tributo</th><th>Anno/Periodo rif.</th>
                    <th style={{ textAlign: "right" }}>Debito</th>
                    <th style={{ textAlign: "right" }}>Credito</th></tr>
              </thead>
              <tbody>
                {draft.lines.map((l) => (
                  <tr key={l.id} style={{ cursor: "default" }}>
                    <td>{l.section}</td>
                    <td>
                      <span className="mono">{l.tax_code}</span>
                      <div className="muted" style={{ fontSize: "0.7rem" }}>{l.tax_code_description}</div>
                    </td>
                    <td className="mono">
                      {l.reference_year ?? "—"}{l.reference_period ? `/${l.reference_period}` : ""}
                    </td>
                    <td className="mono" style={{ textAlign: "right" }}><Val v={l.debit_amount} /></td>
                    <td className="mono" style={{ textAlign: "right" }}><Val v={l.credit_amount} /></td>
                  </tr>
                ))}
              </tbody>
            </table>

            {draft.lines.map((l) => (
              <details key={`prov-${l.id}`} style={{ marginTop: 8 }}>
                <summary className="muted" style={{ fontSize: "0.75rem", cursor: "pointer" }}>
                  Provenienza riga {l.tax_code}
                </summary>
                <div className="dl" style={{ marginTop: 6 }}>
                  <dt>Origine</dt><dd className="mono">{l.origin_kind ?? "—"}</dd>
                  <dt>Liquidazione</dt>
                  <dd className="mono">{l.origin_settlement_id ? shortId(l.origin_settlement_id) : "—"}</dd>
                  <dt>Riferimento norma</dt>
                  <dd style={{ fontSize: "0.78rem" }}>{l.rule_reference ?? "—"}</dd>
                  <dt>Spiegazione</dt>
                  <dd style={{ fontSize: "0.78rem" }}>{l.explanation ?? "—"}</dd>
                </div>
              </details>
            ))}

            <div className="toolbar" style={{ marginTop: 14 }}>
              {canValidate && draft.status === "validation_required" && (
                <button className="btn" disabled={transPending}
                        onClick={() => onTransition(draft.id, "validate")}>
                  Valida bozza
                </button>
              )}
              {canValidate && draft.status === "validated" && (
                <button className="btn" disabled={transPending}
                        onClick={() => onTransition(draft.id, "approve")}>
                  Approva
                </button>
              )}
              {(draft.status === "approved" || draft.status === "exported") && (
                <>
                  <button className="btn btn--ghost" disabled={exportPending}
                          onClick={() => onExport(draft.id, "json")}>
                    <Download size={14} /> Export interno JSON
                  </button>
                  <button className="btn btn--ghost" disabled={exportPending}
                          onClick={() => onExport(draft.id, "csv")}>
                    <Download size={14} /> Export interno CSV
                  </button>
                </>
              )}
            </div>
            <div className="alert alert--info" style={{ marginTop: 10, fontSize: "0.75rem" }}>
              Export interno / non telematico: nessun tracciato Entratel/CBI è implementato
              e nessun F24 viene trasmesso da questa piattaforma.
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scadenze
// ---------------------------------------------------------------------------

function Scadenze({ deadlines }: { deadlines: FiscalDeadline[] }) {
  const kind = (k: string) => ({
    vat_periodic_payment: "Versamento IVA periodica",
    vat_periodic_payment_recalculated: "Versamento IVA (ricalcolo)",
  } as Record<string, string>)[k] ?? k;

  return (
    <Card className="card__pad">
      <div className="card__title">Scadenze fiscali</div>
      {deadlines.length === 0 ? (
        <EmptyState>Nessuna scadenza registrata: nascono dalla liquidazione.</EmptyState>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Tipo</th><th>Statutaria</th><th>Scadenza risolta</th><th>Differimento</th>
              <th style={{ textAlign: "right" }}>Importo</th><th>Stato</th><th>Tesoreria</th>
            </tr>
          </thead>
          <tbody>
            {deadlines.map((d) => (
              <tr key={d.id} style={{ cursor: "default" }}>
                <td>
                  {kind(d.kind)}
                  {d.notes && <div className="muted" style={{ fontSize: "0.7rem" }}>{d.notes}</div>}
                </td>
                <td className="mono">{d.statutory_date ?? "—"}</td>
                <td className="mono">
                  {d.due_date ?? <span className="tre-null">da confermare</span>}
                  {d.due_date_status === "review_required" && (
                    <div><Badge tone="warning">data da confermare</Badge></div>
                  )}
                </td>
                <td className="muted" style={{ fontSize: "0.75rem", maxWidth: 220 }}>
                  {d.deferral_reason ?? "—"}
                </td>
                <td className="mono" style={{ textAlign: "right" }}><Val v={d.amount} /></td>
                <td><StatusBadge status={d.status} /></td>
                <td>
                  {d.open_item_id
                    ? <Link to="/treasury" className="mono" style={{ fontSize: "0.75rem" }}>
                        partita {shortId(d.open_item_id)} →</Link>
                    : <span className="muted">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>
        Le scadenze coprono le festività nazionali; le festività locali del santo patrono
        non sono modellate. Una scadenza validata genera esattamente una partita aperta in
        tesoreria.
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Tracciabilità e regole
// ---------------------------------------------------------------------------

function Regole({ rules, engineVersion, limitations, transmission }: {
  rules: UseQueryResult<FiscalRuleSetsResponse>;
  engineVersion: string; limitations: string[];
  transmission: { supported: boolean; note: string };
}) {
  if (rules.isLoading) return <Spinner />;
  if (rules.error) return <ErrorBanner error={rules.error} />;
  const data = rules.data!;
  return (
    <>
      <Card className="card__pad">
        <div className="card__title">Rule set vigenti — fonte autorevole e versione</div>
        {data.rule_sets.length === 0 ? (
          <EmptyState>Nessun rule set caricato: sincronizzare le regole verificate.</EmptyState>
        ) : (
          data.rule_sets.map((r) => (
            <div key={r.id} style={{ padding: "10px 0", borderBottom: "1px solid var(--pys-surface-2)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <span className="mono">{r.code}</span>{" "}
                  <Badge tone="info">{r.rule_family}</Badge>{" "}
                  <StatusBadge status={r.status} />
                </div>
                <span className="mono muted" style={{ fontSize: "0.75rem" }}>
                  v{r.version} · {r.effective_from} → {r.effective_to ?? "in vigore"}
                </span>
              </div>
              <div className="muted" style={{ fontSize: "0.78rem", marginTop: 4 }}>
                {r.source.authority} — {r.source.title}
                {r.source.legal_reference ? ` · ${r.source.legal_reference}` : ""}
              </div>
              <div className="muted mono" style={{ fontSize: "0.7rem" }}>
                fonte {r.source.url} · pubblicata {r.source.published_at ?? "n.d."} ·
                rilevata {dateIt(r.source.retrieved_at)} · fingerprint {r.source.fingerprint.slice(0, 20)}…
              </div>
              {(r.payload.supported_cases?.length || r.payload.unsupported_cases?.length) ? (
                <div style={{ fontSize: "0.75rem", marginTop: 6 }}>
                  {r.payload.supported_cases?.length ? (
                    <div><strong>Supportato:</strong> {r.payload.supported_cases!.join("; ")}</div>
                  ) : null}
                  {r.payload.unsupported_cases?.length ? (
                    <div className="muted"><strong>Non supportato:</strong> {r.payload.unsupported_cases!.join("; ")}</div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))
        )}
      </Card>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Codici tributo F24 caricati</div>
        {data.tax_codes.length === 0 ? (
          <EmptyState>Nessun codice tributo.</EmptyState>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Codice</th><th>Descrizione</th><th>Sezione</th><th>Uso</th>
                  <th>Validità</th><th>Periodo rif.</th></tr>
            </thead>
            <tbody>
              {data.tax_codes.map((c) => (
                <tr key={c.id} style={{ cursor: "default" }}>
                  <td className="mono">{c.code}</td>
                  <td>{c.description ?? "—"}</td>
                  <td>{c.section}</td>
                  <td className="muted" style={{ fontSize: "0.75rem" }}>{c.usage ?? "—"}</td>
                  <td className="mono" style={{ fontSize: "0.75rem" }}>
                    {c.valid_from} → {c.valid_to ?? "in vigore"}
                  </td>
                  <td>{c.requires_reference_period ? "sì" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>
          Motore <span className="mono">{engineVersion}</span> · {transmission.note}
        </div>
      </Card>

      <Card className="card__pad" style={{ marginTop: 16 }}>
        <div className="card__title">Catena di provenienza</div>
        <ul className="mgmt-issues">
          <li>Fonte autorevole → rule set versionato → motore deterministico → traccia → validazione umana → spiegazione AI (sola lettura).</li>
          <li>Ogni liquidazione registra: rule set, versione formula, voci IVA contate ed escluse, passaggi e regole applicate, data di scadenza statutaria e risolta.</li>
          <li>Ogni riga F24 riporta la liquidazione di origine e il riferimento normativo del codice tributo.</li>
          <li>Una scadenza validata genera esattamente una partita aperta in tesoreria (open_item_id).</li>
        </ul>
        <ul className="mgmt-issues" style={{ marginTop: 8 }}>
          {limitations.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------

function EntryModal({ onClose, onSave, pending }: {
  onClose: () => void; onSave: (p: Record<string, unknown>) => void; pending: boolean;
}) {
  const [form, setForm] = useState({
    direction: "sale", competence_date: "", taxable_amount: "", vat_amount: "",
    vat_rate: "22", vat_nature: "", deductible: "yes",
    document_number: "", document_date: "", counterparty_name: "",
    counterparty_vat: "", notes: "",
  });
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const save = () => onSave({
    direction: form.direction,
    competence_date: form.competence_date,
    taxable_amount: form.taxable_amount,
    vat_amount: form.vat_amount || null,
    vat_rate: form.vat_rate || null,
    vat_nature: form.vat_nature || null,
    deductible: form.direction === "purchase" ? form.deductible === "yes" : null,
    document_number: form.document_number || null,
    document_date: form.document_date || null,
    counterparty_name: form.counterparty_name || null,
    counterparty_vat: form.counterparty_vat || null,
    notes: form.notes || null,
  });
  return (
    <Modal title="Nuova voce IVA" onClose={onClose}
           footer={
             <>
               <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
               <button className="btn" disabled={pending || !form.competence_date || !form.taxable_amount}
                       onClick={save}>Registra</button>
             </>
           }>
      <div className="form-grid">
        <label>Direzione
          <select className="select" value={form.direction} onChange={(e) => set("direction", e.target.value)}>
            <option value="sale">Vendita (IVA a debito)</option>
            <option value="purchase">Acquisto (IVA a credito)</option>
          </select>
        </label>
        <label>Data di competenza
          <input className="input" type="date" value={form.competence_date}
                 onChange={(e) => set("competence_date", e.target.value)} />
        </label>
        <label>Imponibile
          <input className="input" value={form.taxable_amount} placeholder="1000.00"
                 onChange={(e) => set("taxable_amount", e.target.value)} />
        </label>
        <label>IVA
          <input className="input" value={form.vat_amount} placeholder="220.00"
                 onChange={(e) => set("vat_amount", e.target.value)} />
        </label>
        <label>Aliquota %
          <input className="input" value={form.vat_rate}
                 onChange={(e) => set("vat_rate", e.target.value)} />
        </label>
        <label>Natura (es. N1, N4)
          <input className="input" value={form.vat_nature}
                 onChange={(e) => set("vat_nature", e.target.value)} />
        </label>
        {form.direction === "purchase" && (
          <label>Detraibile
            <select className="select" value={form.deductible} onChange={(e) => set("deductible", e.target.value)}>
              <option value="yes">Sì</option>
              <option value="no">No</option>
            </select>
          </label>
        )}
        <label>N. documento
          <input className="input" value={form.document_number}
                 onChange={(e) => set("document_number", e.target.value)} />
        </label>
        <label>Data documento
          <input className="input" type="date" value={form.document_date}
                 onChange={(e) => set("document_date", e.target.value)} />
        </label>
        <label>Controparte
          <input className="input" value={form.counterparty_name}
                 onChange={(e) => set("counterparty_name", e.target.value)} />
        </label>
        <label>P.IVA controparte
          <input className="input" value={form.counterparty_vat}
                 onChange={(e) => set("counterparty_vat", e.target.value)} />
        </label>
        <label>Note
          <input className="input" value={form.notes} onChange={(e) => set("notes", e.target.value)} />
        </label>
      </div>
      <div className="muted" style={{ fontSize: "0.75rem", marginTop: 10 }}>
        La voce è immutabile: una correzione si registra come nuova voce. Senza IVA o senza
        aliquota/natura la voce viene classificata come da verificare, mai come zero.
      </div>
    </Modal>
  );
}

function ImportModal({ onClose, onSave, pending }: {
  onClose: () => void; onSave: (json: string) => void; pending: boolean;
}) {
  const [json, setJson] = useState(ENTRY_TEMPLATE);
  return (
    <Modal title="Importa voci IVA (idempotente)" onClose={onClose}
           footer={
             <>
               <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
               <button className="btn" disabled={pending} onClick={() => onSave(json)}>Importa</button>
             </>
           }>
      <textarea className="input" rows={12} value={json} onChange={(e) => setJson(e.target.value)}
                style={{ fontFamily: "monospace", fontSize: "0.75rem" }} />
      <div className="muted" style={{ fontSize: "0.75rem", marginTop: 8 }}>
        Ogni riga richiede <code>source_ref</code>: reimportare lo stesso file non duplica le voci.
        Uno <code>source_ref</code> esistente con contenuto diverso viene rifiutato (registrare una
        rettifica, non modificare lo storico).
      </div>
    </Modal>
  );
}

function ValidateModal({ settlement: s, onClose, onSave, canSubmit }: {
  settlement: Settlement; onClose: () => void;
  onSave: (p: { note: string; acknowledge_warnings: boolean }) => void;
  canSubmit: boolean;
}) {
  const [note, setNote] = useState("");
  const [ack, setAck] = useState(false);
  const critical = s.warnings.filter((w) => w.severity === "critical");
  return (
    <Modal title={`Valida liquidazione ${s.period?.label ?? ""} v${s.version}`} onClose={onClose}
           footer={
             <>
               <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
               <button className="btn" disabled={!canSubmit || (critical.length > 0 && (!ack || !note.trim()))}
                       onClick={() => onSave({ note, acknowledge_warnings: ack })}>
                 Valida
               </button>
             </>
           }>
      <div className="dl" style={{ marginBottom: 10 }}>
        <dt>Da versare</dt><dd className="mono"><strong><Val v={s.payable_amount} /></strong></dd>
        <dt>Posizione netta</dt><dd className="mono"><Val v={s.net_position} /></dd>
        <dt>Scadenza</dt><dd className="mono">{s.deadline?.due_date ?? "da confermare"}</dd>
      </div>
      {s.warnings.length > 0 && (
        <ul className="mgmt-issues" style={{ marginBottom: 10 }}>
          {s.warnings.map((w) => (
            <li key={w.code}><Badge tone={w.severity === "critical" ? "danger" : "warning"}>{w.severity}</Badge> {w.title}</li>
          ))}
        </ul>
      )}
      {critical.length > 0 && (
        <label style={{ display: "flex", gap: 8, fontSize: "0.8rem", marginBottom: 10 }}>
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          Dichiaro di aver verificato le segnalazioni critiche e di assumermene la responsabilità.
        </label>
      )}
      <label>Nota di validazione {critical.length > 0 && "(obbligatoria)"}
        <textarea className="input" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="muted" style={{ fontSize: "0.75rem", marginTop: 10 }}>
        La validazione è un atto umano permissionato: crea la scadenza e la partita di
        tesoreria (esattamente una volta). L'AI non può eseguirla.
      </div>
    </Modal>
  );
}

function ConfirmModal({ entry, onClose, onSave, pending }: {
  entry: VatEntry; onClose: () => void;
  onSave: (p: { treatment: string; deductible: boolean | null; reason: string }) => void;
  pending: boolean;
}) {
  const [treatment, setTreatment] = useState("supported");
  const [deductible, setDeductible] = useState<string>("keep");
  const [reason, setReason] = useState("");
  return (
    <Modal title={`Verifica voce ${entry.document_number ?? shortId(entry.id)}`} onClose={onClose}
           footer={
             <>
               <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
               <button className="btn" disabled={pending}
                       onClick={() => onSave({
                         treatment,
                         deductible: deductible === "keep" ? null : deductible === "yes",
                         reason,
                       })}>Conferma trattamento</button>
             </>
           }>
      <div className="dl" style={{ marginBottom: 10 }}>
        <dt>Competenza</dt><dd className="mono">{entry.competence_date}</dd>
        <dt>Controparte</dt><dd>{entry.counterparty_name ?? "—"}</dd>
        <dt>Imponibile / IVA</dt>
        <dd className="mono"><Val v={entry.taxable_amount} /> / <Val v={entry.vat_amount} /></dd>
        <dt>Motivo attuale</dt>
        <dd style={{ fontSize: "0.8rem" }}>{entry.treatment_reason ?? "—"}</dd>
      </div>
      <div className="form-grid">
        <label>Trattamento
          <select className="select" value={treatment} onChange={(e) => setTreatment(e.target.value)}>
            <option value="supported">Utilizzabile nel calcolo</option>
            <option value="unsupported">Non utilizzabile (esclusa)</option>
          </select>
        </label>
        {entry.direction === "purchase" && (
          <label>Detraibilità
            <select className="select" value={deductible} onChange={(e) => setDeductible(e.target.value)}>
              <option value="keep">Invariata</option>
              <option value="yes">Detraibile</option>
              <option value="no">Indetraibile</option>
            </select>
          </label>
        )}
      </div>
      <label style={{ marginTop: 8, display: "block" }}>Motivazione
        <textarea className="input" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="muted" style={{ fontSize: "0.75rem", marginTop: 10 }}>
        La conferma non modifica la voce originale: registra una nuova voce
        <span className="mono"> system_derived</span> che la sostituisce nel calcolo.
      </div>
    </Modal>
  );
}
