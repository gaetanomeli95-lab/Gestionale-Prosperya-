import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight, CalendarClock, Calculator, Download, FilePlus2, FileText, Landmark, Link2,
  Plus, Receipt, ScrollText, ShieldCheck, Upload,
} from "lucide-react";
import { api, apiDownload, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  CompanyListItem, F24Draft, FiscalDeadline, FiscalRuleSetsResponse,
  FiscalSnapshot, Page, Settlement, VatEntry, VatRegister,
} from "../api/types";
import {
  Badge, Callout, EmptyState, ErrorBanner, Field, KV, Modal, NA, PageHeader, Row, Section,
  Skeleton, Stat, StatusBadge, statusLabel, Tabs, Tile, toast, Toolbar,
} from "../components/ui";
import { dateIt, dateTimeIt, money } from "../lib/format";
import { ActionList } from "./HubPage";

const MONTHS = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];
const WRITE_ROLES = ["admin", "management", "consultant", "backoffice", "client_admin", "client_operator"];
const VALIDATE_ROLES = ["admin", "management", "consultant", "client_admin", "client_operator"];

type Tab = "panoramica" | "registro" | "liquidazioni" | "f24" | "scadenze" | "regole";

const TREATMENT_LABEL: Record<string, string> = {
  supported: "supportata",
  unsupported: "non supportata",
  requires_review: "da verificare",
  insufficient_data: "dati insufficienti",
};

/* Italian labels for machine codes shown on screen (codes stay English in the API). */
const OUTCOME_LABEL: Record<string, string> = {
  payable: "da versare",
  carried_forward_debit: "debito riportato (sotto soglia)",
  credit: "a credito",
  zero: "nessun saldo",
};
const SOURCE_LABEL: Record<string, string> = {
  manual: "Manuale", import: "Importazione", invoice: "Fattura", system_derived: "Verifica umana",
};
const RULE_FAMILY_LABEL: Record<string, string> = {
  vat_periodic: "IVA periodica", payment_calendar: "Calendario versamenti", f24_format: "Formato F24",
};
const SECTION_LABEL: Record<string, string> = {
  erario: "Erario", inps: "INPS", regioni: "Regioni", imu: "IMU e altri tributi locali",
};
const USAGE_LABEL: Record<string, string> = {
  vat_monthly: "IVA mensile", vat_quarterly: "IVA trimestrale", vat_quarterly_fourth: "IVA 4° trimestre",
  vat_advance: "Acconto IVA", vat_annual: "IVA annuale",
};
const ORIGIN_LABEL: Record<string, string> = { vat_settlement: "Liquidazione IVA" };
const DEADLINE_KIND_LABEL: Record<string, string> = {
  vat_periodic_payment: "Versamento IVA periodica",
  vat_periodic_payment_recalculated: "Versamento IVA (ricalcolo)",
};
const label = (map: Record<string, string>, code: string | null | undefined) =>
  code ? (map[code] ?? code.replaceAll("_", " ")) : "—";
const freqLabel = (f: string) => (f === "monthly" ? "mensile" : "trimestrale");

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
  if (v == null) return <NA />;
  return <>{suffix ? `${v}${suffix}` : money(v)}</>;
}

function shortId(id: string) {
  return id.slice(0, 8);
}

function nextOpenDeadline(deadlines: FiscalDeadline[]) {
  return deadlines
    .filter((d) => d.due_date && d.status !== "cancelled" && d.status !== "settled")
    .sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1))[0];
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
    onSuccess: (s) => {
      setSelSettlement(s.id); setActionError(null); refresh();
      toast(`Liquidazione ${s.period?.label ?? ""} calcolata (v${s.version})`);
    },
    onError,
  });
  const validateSettlement = useMutation({
    mutationFn: (payload: { note: string; acknowledge_warnings: boolean }) =>
      api.post(`/fiscal/companies/${cid}/settlements/${validateFor!.id}/validate`, payload),
    onSuccess: () => { setValidateFor(null); setActionError(null); refresh(); toast("Liquidazione validata"); },
    onError,
  });
  const confirmEntry = useMutation({
    mutationFn: (payload: { treatment: string; deductible: boolean | null; reason: string }) =>
      api.post(`/fiscal/companies/${cid}/vat-entries/${confirmFor!.id}/confirm`, payload),
    onSuccess: () => { setConfirmFor(null); setActionError(null); refresh(); toast("Trattamento confermato"); },
    onError,
  });
  const createEntry = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post(`/fiscal/companies/${cid}/vat-entries`, payload),
    onSuccess: () => { setShowEntry(false); setActionError(null); refresh(); toast("Voce IVA registrata"); },
    onError,
  });
  const importEntries = useMutation({
    mutationFn: (rowsJson: string) =>
      api.post(`/fiscal/companies/${cid}/vat-entries/import`, { rows: JSON.parse(rowsJson) }),
    onSuccess: () => { setShowImport(false); setActionError(null); refresh(); toast("Voci IVA importate"); },
    onError,
  });
  const linkInvoices = useMutation({
    mutationFn: () => api.post(`/fiscal/companies/${cid}/vat-entries/from-invoices`),
    onSuccess: () => { setActionError(null); refresh(); toast("Voci IVA derivate dalle fatture"); },
    onError,
  });
  const generateF24 = useMutation({
    mutationFn: (settlementId: string) =>
      api.post<F24Draft>(`/fiscal/companies/${cid}/f24/generate`, { settlement_id: settlementId }),
    onSuccess: (d) => { setSelDraft(d.id); setTab("f24"); setActionError(null); refresh(); toast("Bozza F24 generata"); },
    onError,
  });
  const transitionF24 = useMutation({
    mutationFn: (payload: { draftId: string; action: "validate" | "approve"; note?: string }) =>
      api.post(`/fiscal/companies/${cid}/f24/${payload.draftId}/${payload.action}`,
               { note: payload.note }),
    onSuccess: (_d, vars) => {
      setActionError(null); refresh();
      toast(vars.action === "approve" ? "Bozza F24 approvata" : "Bozza F24 validata");
    },
    onError,
  });
  const exportF24 = useMutation({
    mutationFn: (payload: { draftId: string; format: "json" | "csv" }) =>
      apiDownload(`/fiscal/companies/${cid}/f24/${payload.draftId}/export`,
                  { format: payload.format }),
    onSuccess: (_d, vars) => { setActionError(null); refresh(); toast(`Export ${vars.format.toUpperCase()} scaricato`); },
    onError,
  });

  if (companies.isLoading) {
    return (
      <>
        <PageHeader hero eyebrow="Finanza e fisco" title="Fisco · IVA e F24"
                    question="Cosa devo verificare o versare, e quando?" />
        <Skeleton kind="stats" rows={4} />
        <Skeleton kind="table" rows={6} />
      </>
    );
  }
  if (companies.error) return <ErrorBanner error={companies.error} />;
  if (!cid) {
    return (
      <>
        <PageHeader hero eyebrow="Finanza e fisco" title="Fisco · IVA e F24"
                    question="Cosa devo verificare o versare, e quando?" />
        <EmptyState title="Nessuna azienda nel workspace" icon={<Landmark size={20} strokeWidth={1.8} />}
                    action={<Link className="btn btn--primary" to="/companies">Vai alle aziende</Link>}>
          Crea prima un'azienda per usare il workspace fiscale.
        </EmptyState>
      </>
    );
  }

  const snap = snapshot.data;
  const latest = snap?.latest_settlement ?? null;
  const detail = settlement.data ?? (selSettlement === latest?.id ? latest : null);
  const company = companies.data?.items.find((c) => c.id === cid);
  const nextDeadline = snap ? nextOpenDeadline(snap.deadlines) : undefined;

  const toValidate = snap
    ? snap.periods.filter((p) => p.settlement && p.settlement.status !== "validated" && p.settlement.status !== "superseded").length
    : 0;
  const draftsPending = snap
    ? snap.f24_drafts.filter((d) => d.status !== "approved" && d.status !== "exported").length
    : 0;
  const deadlinesToConfirm = snap
    ? snap.deadlines.filter((d) => d.due_date_status === "review_required" && d.status !== "cancelled").length
    : 0;

  const tabs: { key: Tab; label: string; count?: number; tone?: string }[] = snap ? [
    { key: "panoramica", label: "Panoramica" },
    { key: "registro", label: "Registro IVA", count: snap.counters.pending_entries,
      tone: snap.counters.pending_entries > 0 ? "warning" : undefined },
    { key: "liquidazioni", label: "Liquidazioni", count: toValidate || snap.counters.calculated,
      tone: toValidate > 0 ? "warning" : undefined },
    { key: "f24", label: "F24", count: draftsPending || snap.counters.f24_drafts,
      tone: draftsPending > 0 ? "warning" : undefined },
    { key: "scadenze", label: "Scadenze", count: deadlinesToConfirm || snap.counters.open_deadlines,
      tone: deadlinesToConfirm > 0 ? "danger" : undefined },
    { key: "regole", label: "Tracciabilità e regole" },
  ] : [];

  return (
    <>
      <PageHeader
        hero
        eyebrow={`Finanza e fisco · ${company?.legal_name ?? "azienda"} · ${year}`}
        title="Fisco · IVA e F24"
        question="Cosa devo verificare o versare, e quando? Registro IVA, liquidazioni deterministiche, validazione umana, bozze F24 e scadenze: nulla viene calcolato fuori dal motore versionato."
        actions={
          <>
            <select className="select" value={cid} onChange={(e) => setCompany(e.target.value)} aria-label="Azienda">
              {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
            </select>
            <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Anno">
              {[2024, 2025, 2026, 2027].map((y) => <option key={y}>{y}</option>)}
            </select>
            <Link className="btn btn--ghost" to={`/cockpit/${cid}`}>Cockpit</Link>
            <Link className="btn btn--ghost" to="/treasury">Tesoreria</Link>
          </>
        }
      />

      {actionError ? (
        <div className="mb-4">
          <ErrorBanner error={actionError instanceof ApiError ? actionError : new Error("Operazione non riuscita")} />
        </div>
      ) : null}
      {snapshot.isLoading && (
        <>
          <Skeleton kind="stats" rows={4} />
          <Skeleton kind="table" rows={6} />
        </>
      )}
      {snapshot.error && <ErrorBanner error={snapshot.error} />}

      {snap && (
        <>
          <div className="stat-grid">
            <Stat
              hero
              icon={<CalendarClock size={14} />}
              label="Prossimo versamento"
              value={nextDeadline ? <Val v={nextDeadline.amount} /> : <NA title="Nessuna scadenza aperta: non significa zero" />}
              hint={nextDeadline
                ? <>entro il {dateIt(nextDeadline.due_date)} · {label(DEADLINE_KIND_LABEL, nextDeadline.kind)} · {statusLabel(nextDeadline.status)}</>
                : snap.counters.pending_entries > 0
                  ? `nessuna scadenza: prima verifica ${snap.counters.pending_entries} voci IVA`
                  : "nessuna scadenza aperta: calcola una liquidazione"}
              onClick={() => setTab("scadenze")}
            />
            <Stat
              icon={<ShieldCheck size={14} />}
              label="Voci da verificare"
              value={snap.counters.pending_entries}
              hint={snap.counters.pending_entries > 0 ? "bloccano un calcolo affidabile" : "il registro è pulito"}
              tone={snap.counters.pending_entries > 0 ? "warn" : undefined}
              onClick={() => setTab("registro")}
            />
            <Stat
              icon={<Calculator size={14} />}
              label="Posizione IVA netta"
              value={<Val v={latest?.net_position} />}
              hint={latest
                ? <>{latest.period?.label} · v{latest.version} · {statusLabel(latest.status)}</>
                : "nessuna liquidazione nell'anno"}
              tone={latest?.status === "review_required" ? "warn" : undefined}
              onClick={() => { if (latest) setSelSettlement(latest.id); setTab("liquidazioni"); }}
            />
            <Stat
              icon={<Receipt size={14} />}
              label="Bozze F24"
              value={snap.counters.f24_drafts}
              hint={draftsPending > 0
                ? `${draftsPending} in lavorazione · ${snap.counters.open_deadlines} scadenze aperte`
                : `${snap.counters.open_deadlines} scadenze aperte`}
              tone={draftsPending > 0 ? "warn" : undefined}
              onClick={() => setTab("f24")}
            />
          </div>

          <Tabs tabs={tabs} value={tab} onChange={setTab} />

          {tab === "panoramica" && (
            <Panoramica snap={snap} canWrite={canWrite}
                        onCalculate={() => setTab("liquidazioni")}
                        onOpenSettlement={(id) => { setSelSettlement(id); setTab("liquidazioni"); }}
                        onOpenDraft={(id) => { setSelDraft(id); setTab("f24"); }}
                        onOpenRegister={() => setTab("registro")}
                        onConfirm={canWrite ? setConfirmFor : undefined} />
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
                    onOpenSettlement={(id) => { setSelSettlement(id); setTab("liquidazioni"); }}
                    onGoToSettlements={() => setTab("liquidazioni")} />
          )}

          {tab === "scadenze" && <Scadenze deadlines={snap.deadlines} onGoToSettlements={() => setTab("liquidazioni")} />}

          {tab === "regole" && <Regole rules={ruleSets} engineVersion={snap.engine_version}
                                      limitations={snap.limitations}
                                      transmission={snap.transmission} />}

          <details className="mt-4">
            <summary className="eyebrow eyebrow--muted">
              Perimetro e limitazioni dichiarate ({snap.limitations.length + 1})
            </summary>
            <div className="mt-2">
              <Callout tone="neutral" title="Cosa il motore fiscale non fa">
                <ul className="mgmt-issues">
                  {snap.limitations.map((l) => <li key={l}>{l}</li>)}
                  <li>{snap.transmission.note}</li>
                </ul>
                <div className="text-2xs muted mt-2">
                  Motore <span className="mono">{snap.engine_version}</span> ·
                  azienda {company?.legal_name ?? cid} · anno {snap.year} · dati al {dateIt(snap.as_of)}
                </div>
              </Callout>
            </div>
          </details>
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
// Shared pieces
// ---------------------------------------------------------------------------

/** One VAT entry awaiting a human decision, with the reason it matters. */
function PendingEntryRow({ e, onConfirm }: { e: VatEntry; onConfirm?: (e: VatEntry) => void }) {
  return (
    <Row
      tone="warning"
      leading={<FileText size={16} />}
      title={<>{e.document_number ?? <span className="muted">Documento senza numero</span>}{e.counterparty_name ? ` · ${e.counterparty_name}` : ""}</>}
      sub={<>
        {e.direction === "sale" ? "Vendita" : "Acquisto"} · competenza {dateIt(e.competence_date)}
        {" · "}{e.treatment_reason ?? TREATMENT_LABEL[e.treatment] ?? e.treatment}
      </>}
      trailing={<>
        <span className="num strong"><Val v={e.vat_amount} /></span>
        <StatusBadge status={e.treatment} />
        {onConfirm && (
          <button className="btn btn--ghost btn--sm" onClick={() => onConfirm(e)}>Verifica</button>
        )}
      </>}
    />
  );
}

function SeverityCallouts({ warnings }: { warnings: Settlement["warnings"] }) {
  return (
    <div className="stack stack--sm">
      {warnings.map((w) => (
        <Callout key={w.code}
                 tone={w.severity === "critical" ? "danger" : w.severity === "warning" ? "warning" : "info"}
                 title={w.title}>
          {w.message}
        </Callout>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panoramica
// ---------------------------------------------------------------------------

function Panoramica({ snap, canWrite, onCalculate, onOpenSettlement, onOpenDraft, onOpenRegister, onConfirm }: {
  snap: FiscalSnapshot; canWrite: boolean;
  onCalculate: () => void;
  onOpenSettlement: (id: string) => void;
  onOpenDraft: (id: string) => void;
  onOpenRegister: () => void;
  onConfirm?: (e: VatEntry) => void;
}) {
  const latest = snap.latest_settlement;

  return (
    <div className="stack">
      <div className="grid-2-1">
        <Section
          title={<>Operazioni da verificare {snap.counters.pending_entries > 0 && <Badge tone="warning">{snap.counters.pending_entries}</Badge>}</>}
          actions={snap.counters.pending_entries > 0 && (
            <button className="btn btn--ghost btn--sm" onClick={onOpenRegister}>Apri registro <ArrowRight size={12} /></button>
          )}
          footer={snap.counters.pending_entries > 0
            ? "Ogni voce verificata viene sostituita nel calcolo da una nuova voce tracciata: l'originale resta immutabile."
            : undefined}
        >
          {snap.counters.pending_entries === 0 ? (
            <EmptyState title="Nulla da verificare" icon={<ShieldCheck size={20} strokeWidth={1.8} />}>
              Nessuna voce IVA in attesa di verifica umana: il registro è utilizzabile per il calcolo.
            </EmptyState>
          ) : (
            <div className="rows">
              {snap.pending_entries.map((e) => <PendingEntryRow key={e.id} e={e} onConfirm={onConfirm} />)}
            </div>
          )}
        </Section>

        <Section title="Stato del periodo"
                 actions={latest && (
                   <button className="btn btn--ghost btn--sm" onClick={() => onOpenSettlement(latest.id)}>
                     Dettaglio <ArrowRight size={12} />
                   </button>
                 )}>
          {latest ? (
            <KV columns={1} items={[
              { k: "Periodo", v: <span className="cluster">{latest.period?.label} <StatusBadge status={latest.period?.status} /></span> },
              { k: "Liquidazione", v: <span className="cluster">versione {latest.version} <StatusBadge status={latest.status} /></span> },
              { k: "Validazione", v: latest.status === "validated"
                  ? <>validata il {dateTimeIt(latest.validated_at)} da operatore</>
                  : <span className="muted">non validata — richiede conferma umana</span> },
              { k: "Versamento dovuto", v: <span className="num strong"><Val v={latest.payable_amount} /></span> },
              { k: "Voci IVA contate", v: <span className="num">{latest.source_count} fonti · {latest.unsupported_count} escluse</span> },
              { k: "F24 collegato", v: latest.f24_draft_id
                  ? <a role="button" tabIndex={0} onClick={() => onOpenDraft(latest.f24_draft_id!)}
                       onKeyDown={(e) => e.key === "Enter" && onOpenDraft(latest.f24_draft_id!)}>
                      Apri la bozza F24 <ArrowRight size={11} /></a>
                  : <span className="muted">nessuna bozza</span> },
              { k: "Impatto sulla cassa", v: latest.deadline?.open_item_id
                  ? <Link to="/treasury">Partita aperta in tesoreria <ArrowRight size={11} /></Link>
                  : <span className="muted">nessuna partita: impatto cassa solo dopo la validazione</span> },
            ]} />
          ) : (
            <EmptyState title="Posizione IVA non calcolabile" icon={<Calculator size={20} strokeWidth={1.8} />}
                        action={canWrite && <button className="btn btn--primary btn--sm" onClick={onCalculate}>Calcola un periodo</button>}>
              Nessuna liquidazione per l'anno selezionato: con i dati presenti la posizione IVA non è calcolabile — non è pari a zero.
            </EmptyState>
          )}
        </Section>
      </div>

      <Section title="Segnali del motore fiscale">
        <ActionList actions={snap.warnings.map((w) => ({
          ...w, priority: 0, priority_version: "",
          formula: w.formula ?? "", formula_version: w.formula_version ?? snap.engine_version,
          evidence: w.evidence ?? {}, action_required: w.action_required ?? false,
        }))} />
      </Section>

      <Section title={`Contatori anno ${snap.year}`}>
        <div className="grid-auto grid-auto--sm">
          <Tile label="Periodi tracciati" value={snap.counters.periods} />
          <Tile label="Liquidazioni calcolate" value={snap.counters.calculated} />
          <Tile label="Liquidazioni validate" value={snap.counters.validated}
                tone={snap.counters.calculated > snap.counters.validated ? "warn" : undefined}
                hint={snap.counters.calculated > snap.counters.validated ? `${snap.counters.calculated - snap.counters.validated} in attesa` : undefined} />
          <Tile label="Scadenze aperte" value={snap.counters.open_deadlines} />
          <Tile label="Bozze F24" value={snap.counters.f24_drafts} />
        </div>
      </Section>
    </div>
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
    <div className="stack">
      <Toolbar
        end={reg && (
          <span className="text-xs muted">
            {reg.counters.effective} voci efficaci · {reg.counters.sales} attive ·{" "}
            {reg.counters.purchases} passive ·{" "}
            <strong className={reg.counters.requires_review > 0 ? "neg" : undefined}>{reg.counters.requires_review} da verificare</strong>
          </span>
        )}
      >
        <select className="select" value={regMonth} aria-label="Periodo del registro"
                onChange={(e) => setRegMonth(Number(e.target.value) as number | 0)}>
          <option value={0}>Anno {year} intero</option>
          {MONTHS.slice(1).map((m, i) => <option key={m} value={i + 1}>{m} {year}</option>)}
        </select>
        {canWrite && (
          <>
            <button className="btn btn--primary" onClick={onLinkInvoices} disabled={linkPending}>
              <Link2 size={14} /> {linkPending ? "Derivazione…" : "Deriva da fatture"}
            </button>
            <button className="btn btn--ghost" onClick={onNew}><Plus size={14} /> Nuova voce</button>
            <button className="btn btn--ghost" onClick={onImport}><Upload size={14} /> Importa</button>
          </>
        )}
      </Toolbar>

      {register.isLoading && <Section title="Registro IVA"><Skeleton kind="table" rows={6} /></Section>}
      {register.error && <ErrorBanner error={register.error} />}
      {reg && (
        <>
          {reg.pending_review.length > 0 && (
            <Section tone="warning"
                     title={<>Da verificare prima del calcolo <Badge tone="warning">{reg.pending_review.length}</Badge></>}
                     footer="Finché queste voci restano da verificare, la liquidazione le esclude e segnala il rischio.">
              <div className="rows">
                {reg.pending_review.map((e) => (
                  <PendingEntryRow key={e.id} e={e} onConfirm={canWrite ? onConfirm : undefined} />
                ))}
              </div>
            </Section>
          )}

          <Section flush
                   title={<>Registro IVA · {reg.period.label}</>}
                   actions={<span className="text-xs muted nowrap">{dateIt(reg.period.start)} → {dateIt(reg.period.end)}</span>}
                   footer={reg.limitations.length > 0 ? reg.limitations.join(" · ") : undefined}>
            {reg.entries.length === 0 ? (
              <EmptyState title="Nessuna voce IVA nel periodo" icon={<Receipt size={20} strokeWidth={1.8} />}
                          action={canWrite && <button className="btn btn--ghost btn--sm" onClick={onLinkInvoices} disabled={linkPending}>Deriva dalle fatture</button>}>
                Registra una voce, importa un file o deriva le voci dalle fatture emesse e ricevute.
              </EmptyState>
            ) : (
              <table className="table table--flush table--static">
                <thead>
                  <tr>
                    <th>Documento</th><th>Competenza</th><th>Controparte</th>
                    <th className="th--num">Imponibile</th>
                    <th className="th--num">IVA</th>
                    <th>Aliq. / Natura</th><th>Trattamento</th><th>Fonte</th>
                  </tr>
                </thead>
                <tbody>
                  {reg.entries.map((e) => (
                    <tr key={e.id} className={e.superseded ? "muted" : undefined}>
                      <td>
                        <div className="table__primary">{e.document_number ?? <span className="muted">senza numero</span>}</div>
                        <div className="table__sub">
                          {e.direction === "sale" ? "Vendita" : "Acquisto"}
                          {e.invoice_id ? " · da fattura" : ""}
                          {e.superseded ? " · sostituita da verifica" : ""}
                        </div>
                      </td>
                      <td className="num nowrap">{dateIt(e.competence_date)}</td>
                      <td>
                        {e.counterparty_name ?? <span className="muted">—</span>}
                        {e.counterparty_vat && <div className="table__sub num">{e.counterparty_vat}</div>}
                      </td>
                      <td className="td--num"><Val v={e.taxable_amount} /></td>
                      <td className="td--num"><Val v={e.vat_amount} /></td>
                      <td className="num">
                        {e.vat_nature ? `N${e.vat_nature}` : e.vat_rate ? `${e.vat_rate}%` : <NA />}
                        {e.direction === "purchase" && e.deductible === false && (
                          <div className="table__sub">indetraibile</div>
                        )}
                      </td>
                      <td><StatusBadge status={e.treatment} /></td>
                      <td className="text-xs muted">{label(SOURCE_LABEL, e.source)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </>
      )}
    </div>
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
    <div className="stack">
      {canWrite && (
        <Section title="Calcola o ricalcola una liquidazione"
                 footer="Un ricalcolo crea una nuova versione: la precedente resta storicizzata, mai sovrascritta.">
          <div className="cluster">
            <select className="select" value={calcPeriod.frequency} aria-label="Periodicità"
                    onChange={(e) => setCalcPeriod({ period_no: 1, frequency: e.target.value })}>
              <option value="monthly">Mensile</option>
              <option value="quarterly">Trimestrale</option>
            </select>
            <select className="select" value={calcPeriod.period_no} aria-label="Periodo da calcolare"
                    onChange={(e) => setCalcPeriod({ ...calcPeriod, period_no: Number(e.target.value) })}>
              {Array.from({ length: maxPeriod }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {calcPeriod.frequency === "monthly" ? `${MONTHS[n]} ${snap.year}` : `${n}° trimestre ${snap.year}`}
                </option>
              ))}
            </select>
            <button className="btn btn--primary" onClick={onCalculate} disabled={calcPending}>
              <Calculator size={14} /> {calcPending ? "Calcolo…" : "Calcola con il motore"}
            </button>
          </div>
        </Section>
      )}

      <div className="grid-2">
        <Section flush title={`Periodi ${snap.year}`}
                 actions={<span className="text-xs muted">{snap.periods.length} periodi</span>}>
          {snap.periods.length === 0 ? (
            <EmptyState title="Nessun periodo fiscale" icon={<CalendarClock size={20} strokeWidth={1.8} />}>
              I periodi nascono al primo calcolo di una liquidazione.
            </EmptyState>
          ) : (
            <table className="table table--flush">
              <thead>
                <tr><th>Periodo</th><th>Liquidazione</th>
                    <th className="th--num">Posizione netta</th>
                    <th className="th--num">Da versare</th></tr>
              </thead>
              <tbody>
                {snap.periods.map((p) => {
                  const selected = !!p.settlement && detail?.id === p.settlement.id;
                  const open = () => p.settlement && onSelect(p.settlement.id);
                  return (
                    <tr key={p.id} onClick={open}
                        className={selected ? "is-selected" : undefined}
                        tabIndex={p.settlement ? 0 : undefined}
                        onKeyDown={(e) => e.key === "Enter" && open()}
                        aria-label={p.settlement ? `Apri la liquidazione ${p.label}` : undefined}>
                      <td>
                        <div className="table__primary cluster">{p.label} <StatusBadge status={p.status} /></div>
                        <div className="table__sub">
                          {dateIt(p.start_date)} → {dateIt(p.end_date)} · {freqLabel(p.frequency)}
                        </div>
                      </td>
                      <td>
                        {p.settlement
                          ? <>
                              <span className="cluster">v{p.settlement.version} <StatusBadge status={p.settlement.status} /></span>
                              {p.settlement.unsupported_count > 0 && (
                                <div className="table__sub">{p.settlement.unsupported_count} voci escluse</div>
                              )}
                            </>
                          : <span className="muted">non calcolata</span>}
                      </td>
                      <td className="td--num"><Val v={p.settlement?.net_position} /></td>
                      <td className="td--num strong"><Val v={p.settlement?.payable_amount} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Section>

        <Section title="Dettaglio liquidazione"
                 actions={detail && (
                   <span className="text-xs muted nowrap">{detail.period?.label} · versione {detail.version}</span>
                 )}>
          {detailLoading && <Skeleton rows={8} />}
          {detailError ? <ErrorBanner error={detailError} /> : null}
          {!detail && !detailLoading && (
            <EmptyState title="Seleziona una liquidazione" icon={<Calculator size={20} strokeWidth={1.8} />}>
              Scegli un periodo calcolato dalla tabella per vedere importi, segnalazioni e tracciabilità.
            </EmptyState>
          )}
          {detail && <SettlementDetail s={detail} canValidate={canValidate}
                                       onValidate={() => onValidate(detail)}
                                       onGenerateF24={() => onGenerateF24(detail.id)}
                                       genPending={genPending}
                                       onOpenDraft={onOpenDraft}
                                       onOpenRegister={onOpenRegister} />}
        </Section>
      </div>
    </div>
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
  const canGenerate = canValidate && s.status === "validated" && !s.f24_draft_id
    && !!s.payable_amount && Number(s.payable_amount) > 0;
  const canDoValidate = canValidate && s.status !== "validated" && s.status !== "superseded";

  return (
    <div className="stack">
      <div className="grid-auto grid-auto--sm">
        <Tile label="Da versare" value={<Val v={s.payable_amount} />}
              tone={s.payable_amount && Number(s.payable_amount) > 0 ? "warn" : "muted"}
              hint={s.deadline?.due_date ? `entro il ${dateIt(s.deadline.due_date)}` : "scadenza da confermare"} />
        <Tile label="Posizione netta" value={<Val v={s.net_position} />}
              hint={s.outcome ? label(OUTCOME_LABEL, s.outcome) : undefined} />
        <Tile label="Esito" value={<StatusBadge status={s.status} />}
              hint={s.status === "validated"
                ? `validata il ${dateTimeIt(s.validated_at)}`
                : s.status === "superseded" ? "superata da una versione più recente" : "in attesa di validazione umana"} />
      </div>

      <KV columns={2} items={[
        { k: "IVA a debito", v: <span className="num"><Val v={s.debit_total} /></span> },
        { k: "IVA a credito", v: <span className="num"><Val v={s.credit_total} /></span> },
        { k: "Credito periodo precedente", v: <span className="num"><Val v={s.prior_credit} /></span> },
        { k: "Debito precedente sotto soglia", v: <span className="num"><Val v={s.prior_small_debit} /></span> },
        ...(s.interest_amount != null
          ? [{ k: "Interessi trimestrali 1%", v: <span className="num"><Val v={s.interest_amount} /></span> }]
          : []),
        { k: "Riporto a credito", v: <span className="num"><Val v={s.carry_forward_credit} /></span> },
        { k: "Riporto a debito", v: <span className="num"><Val v={s.carry_forward_debit} /></span> },
        { k: "Fonti contate / escluse", v: <span className="num">{s.source_count} / {s.unsupported_count}</span> },
        { k: "Calcolata il", v: <span className="num">{dateTimeIt(s.calculated_at)}</span> },
        ...(s.validation_note ? [{ k: "Nota di validazione", v: <>“{s.validation_note}”</> }] : []),
        ...(s.deadline ? [{
          k: "Scadenza",
          v: <>
            <span className="cluster"><StatusBadge status={s.deadline.status} /> {s.deadline.due_date ? dateIt(s.deadline.due_date) : "data da confermare"}</span>
            {s.deadline.deferral_reason && <div className="text-xs muted">{s.deadline.deferral_reason}</div>}
          </>,
        }] : []),
        { k: "F24", v: s.f24_draft_id
            ? <a role="button" tabIndex={0} onClick={() => onOpenDraft(s.f24_draft_id!)}
                 onKeyDown={(e) => e.key === "Enter" && onOpenDraft(s.f24_draft_id!)}>Apri la bozza F24 <ArrowRight size={11} /></a>
            : <span className="muted">nessuna bozza</span> },
      ]} />

      {s.warnings.length > 0 && (
        <div>
          <div className="eyebrow eyebrow--muted mb-3">Segnalazioni del motore</div>
          <SeverityCallouts warnings={s.warnings} />
        </div>
      )}

      {(canDoValidate || canGenerate || s.period) && (
        <div className="cluster">
          {canDoValidate && (
            <button className="btn btn--primary" onClick={onValidate}>
              <FilePlus2 size={14} /> Valida (atto umano)
            </button>
          )}
          {canGenerate && (
            <button className="btn btn--primary" onClick={onGenerateF24} disabled={genPending}>
              <Receipt size={14} /> {genPending ? "Generazione…" : "Genera bozza F24"}
            </button>
          )}
          {s.period && (
            <button className="btn btn--ghost" onClick={() => onOpenRegister({ period_no: s.period!.period_no })}>
              Registro del periodo
            </button>
          )}
        </div>
      )}
      {critical.length > 0 && canDoValidate && (
        <Callout tone="warning">
          La validazione con segnalazioni critiche richiede una nota di motivazione.
        </Callout>
      )}

      <details>
        <summary className="eyebrow eyebrow--muted">
          Tracciabilità completa — fonti, regole e passaggi di calcolo
        </summary>
        <TraceView s={s} />
      </details>
    </div>
  );
}

function TraceView({ s }: { s: Settlement }) {
  const t = s.trace;
  const srcTable = (rows: NonNullable<typeof t.debit_sources>, title: string) => (
    <div>
      <div className="eyebrow eyebrow--muted mb-3">{title}</div>
      {rows.length === 0 ? (
        <div className="text-xs muted">Nessuna fonte.</div>
      ) : (
        <table className="table table--dense table--static">
          <thead>
            <tr><th>Documento</th><th>Competenza</th><th>Controparte</th>
                <th className="th--num">IVA</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="table__primary">{r.document_number ?? <span className="muted">senza numero</span>}</td>
                <td className="num nowrap">{dateIt(r.competence_date)}</td>
                <td>{r.counterparty_name ?? <span className="muted">—</span>}</td>
                <td className="td--num"><Val v={r.vat_amount} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );

  return (
    <div className="stack mt-3">
      <KV columns={2} items={[
        { k: "Formula", v: <span className="mono">{t.formula_version} · motore {t.engine_version}</span> },
        ...(t.rule_set ? [{
          k: "Rule set IVA",
          v: <>
            <span className="cluster"><span className="mono">{t.rule_set.code} v{t.rule_set.version}</span> <StatusBadge status={t.rule_set.status} /></span>
            <div className="text-xs muted">
              {t.rule_set.source.authority} — {t.rule_set.source.title}
              {t.rule_set.source.legal_reference ? ` · ${t.rule_set.source.legal_reference}` : ""}
              {" · "}vigente dal {dateIt(t.rule_set.effective_from)}
            </div>
          </>,
        }] : []),
        ...(t.calendar_rule_set ? [{
          k: "Rule set calendario",
          v: <span className="mono">{t.calendar_rule_set.code} v{t.calendar_rule_set.version}</span>,
        }] : []),
        ...(t.prior_source ? [{
          k: "Riporto da",
          v: <>liquidazione {t.prior_source.period} v{t.prior_source.version} ({statusLabel(t.prior_source.status)})</>,
        }] : []),
        ...(t.due_date ? [{
          k: "Scadenza statutaria",
          v: <span className="cluster">
            <span className="num">{dateIt(t.due_date.statutory)} → {t.due_date.resolved ? dateIt(t.due_date.resolved) : "da confermare"}</span>
            <StatusBadge status={t.due_date.status} />
          </span>,
        }] : []),
      ]} />

      {t.formula_steps && t.formula_steps.length > 0 && (
        <div>
          <div className="eyebrow eyebrow--muted mb-3">Passaggi di calcolo</div>
          <ol className="mgmt-issues">
            {t.formula_steps.map((step, i) => <li key={i}>{step}</li>)}
          </ol>
        </div>
      )}
      {t.applied_rules && t.applied_rules.length > 0 && (
        <div>
          <div className="eyebrow eyebrow--muted mb-3">Regole applicate</div>
          <ul className="mgmt-issues">
            {t.applied_rules.map((r) => <li key={r} className="mono">{r}</li>)}
          </ul>
        </div>
      )}
      {t.due_date?.applied_rules?.length ? (
        <div>
          <div className="eyebrow eyebrow--muted mb-3">Regole di differimento applicate</div>
          <ul className="mgmt-issues">
            {t.due_date.applied_rules.map((r) => <li key={r} className="mono">{r}</li>)}
          </ul>
        </div>
      ) : null}

      {srcTable(t.debit_sources ?? [], "IVA a debito — voci che compongono il totale")}
      {srcTable(t.credit_sources ?? [], "IVA a credito — voci che compongono il totale")}

      {(t.excluded_sources?.length ?? 0) > 0 && (
        <div>
          <div className="eyebrow eyebrow--muted mb-3">Voci escluse dal calcolo</div>
          <table className="table table--dense table--static">
            <thead>
              <tr><th>Voce</th><th>Trattamento</th><th>Motivo</th>
                  <th className="th--num">IVA</th></tr>
            </thead>
            <tbody>
              {t.excluded_sources!.map((r) => (
                <tr key={r.id}>
                  <td className="table__primary">{r.document_number ?? <span className="muted">senza numero</span>}</td>
                  <td><StatusBadge status={r.treatment ?? ""} /></td>
                  <td className="text-xs muted">{r.reason ?? "—"}</td>
                  <td className="td--num"><Val v={r.vat_amount} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {t.unsupported_cases && t.unsupported_cases.length > 0 && (
        <Callout tone="neutral" title="Casi fuori perimetro dichiarati dal rule set">
          {t.unsupported_cases.join("; ")}.
        </Callout>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// F24
// ---------------------------------------------------------------------------

function F24Tab({ snap, draft, draftLoading, selDraft, onSelect, canValidate,
                  onTransition, transPending, onExport, exportPending, onOpenSettlement, onGoToSettlements }: {
  snap: FiscalSnapshot; draft: F24Draft | null; draftLoading: boolean;
  selDraft: string | null; onSelect: (id: string) => void;
  canValidate: boolean;
  onTransition: (draftId: string, action: "validate" | "approve") => void;
  transPending: boolean;
  onExport: (draftId: string, format: "json" | "csv") => void;
  exportPending: boolean;
  onOpenSettlement: (id: string) => void;
  onGoToSettlements: () => void;
}) {
  const settlementLabel = (id: string | null) => {
    if (!id) return null;
    return snap.periods.find((p) => p.settlement?.id === id)?.label ?? null;
  };

  return (
    <div className="grid-2">
      <Section flush title="Bozze F24"
               footer={<>{snap.transmission.note} Gli export JSON/CSV sono documenti interni di lavoro, non tracciati telematici.</>}>
        {snap.f24_drafts.length === 0 ? (
          <EmptyState title="Nessuna bozza F24" icon={<Receipt size={20} strokeWidth={1.8} />}
                      action={<button className="btn btn--ghost btn--sm" onClick={onGoToSettlements}>Vai alle liquidazioni</button>}>
            Una bozza si genera solo da una liquidazione validata con un importo a debito.
          </EmptyState>
        ) : (
          <table className="table table--flush">
            <thead>
              <tr><th>Bozza</th><th>Stato</th>
                  <th className="th--num">Saldo</th><th className="th--num">Scadenza</th></tr>
            </thead>
            <tbody>
              {snap.f24_drafts.map((d) => (
                <tr key={d.id} onClick={() => onSelect(d.id)} tabIndex={0}
                    onKeyDown={(e) => e.key === "Enter" && onSelect(d.id)}
                    className={selDraft === d.id ? "is-selected" : undefined}
                    aria-label={`Apri la bozza F24 ${shortId(d.id)}`}>
                  <td>
                    <div className="table__primary">{settlementLabel(d.settlement_id) ?? "Bozza F24"}</div>
                    <div className="table__sub">{label(DEADLINE_KIND_LABEL, "vat_periodic_payment")}</div>
                  </td>
                  <td><StatusBadge status={d.status} /></td>
                  <td className="td--num strong"><Val v={d.balance} /></td>
                  <td className="td--num nowrap">{d.due_date ? dateIt(d.due_date) : <NA />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Dettaglio bozza"
               actions={draft && <StatusBadge status={draft.status} />}>
        {draftLoading && <Skeleton rows={8} />}
        {!draft && !draftLoading && (
          <EmptyState title="Seleziona una bozza" icon={<Receipt size={20} strokeWidth={1.8} />}>
            Scegli una bozza dalla tabella per vedere righe, provenienza e azioni disponibili.
          </EmptyState>
        )}
        {draft && (
          <div className="stack">
            <div className="grid-auto grid-auto--sm">
              <Tile label="Saldo" value={<Val v={draft.balance} />}
                    tone={draft.balance && Number(draft.balance) > 0 ? "warn" : "muted"}
                    hint={draft.due_date ? `versamento entro il ${dateIt(draft.due_date)}` : "scadenza non disponibile"} />
              <Tile label="Totale debiti" value={<Val v={draft.total_debit} />} />
              <Tile label="Totale crediti" value={<Val v={draft.total_credit} />} />
            </div>

            <KV columns={2} items={[
              { k: "Liquidazione origine", v: draft.settlement_id
                  ? <a role="button" tabIndex={0} onClick={() => onOpenSettlement(draft.settlement_id!)}
                       onKeyDown={(e) => e.key === "Enter" && onOpenSettlement(draft.settlement_id!)}>
                      {settlementLabel(draft.settlement_id) ?? "Apri la liquidazione"} <ArrowRight size={11} /></a>
                  : <span className="muted">—</span> },
              { k: "Scadenza collegata", v: draft.deadline_id ? "sì, registrata" : <span className="muted">nessuna</span> },
              { k: "Validata", v: <span className="num">{dateTimeIt(draft.validated_at)}</span> },
              { k: "Approvata", v: <span className="num">{dateTimeIt(draft.approved_at)}</span> },
              { k: "Esportata", v: draft.exported_at
                  ? <>
                      {dateTimeIt(draft.exported_at)} · formato {draft.export_format?.toUpperCase()}
                      <div className="text-xs muted mono">impronta {draft.export_fingerprint?.slice(0, 16)}…</div>
                    </>
                  : <span className="muted">mai esportata</span> },
            ]} />

            {draft.taxpayer && Object.keys(draft.taxpayer).length > 0 && (
              <details>
                <summary className="eyebrow eyebrow--muted">Contribuente (istantanea al momento della generazione)</summary>
                <div className="mt-3">
                  <KV columns={2} items={Object.entries(draft.taxpayer).map(([k, v]) => ({
                    k: k.replaceAll("_", " "), v: <span className="num">{String(v ?? "—")}</span>,
                  }))} />
                </div>
              </details>
            )}

            <div>
              <div className="eyebrow eyebrow--muted mb-3">Righe F24</div>
              <table className="table table--dense table--static">
                <thead>
                  <tr><th>Sezione</th><th>Codice tributo</th><th>Anno / periodo rif.</th>
                      <th className="th--num">Debito</th>
                      <th className="th--num">Credito</th></tr>
                </thead>
                <tbody>
                  {draft.lines.map((l) => (
                    <tr key={l.id}>
                      <td>{label(SECTION_LABEL, l.section)}</td>
                      <td>
                        <div className="table__primary mono">{l.tax_code}</div>
                        <div className="table__sub">{l.tax_code_description}</div>
                      </td>
                      <td className="num">
                        {l.reference_year ?? "—"}{l.reference_period ? ` / ${l.reference_period}` : ""}
                      </td>
                      <td className="td--num"><Val v={l.debit_amount} /></td>
                      <td className="td--num"><Val v={l.credit_amount} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {draft.lines.map((l) => (
              <details key={`prov-${l.id}`}>
                <summary className="eyebrow eyebrow--muted">Provenienza riga {l.tax_code}</summary>
                <div className="mt-3">
                  <KV columns={1} items={[
                    { k: "Origine", v: label(ORIGIN_LABEL, l.origin_kind) },
                    { k: "Liquidazione", v: l.origin_settlement_id
                        ? (settlementLabel(l.origin_settlement_id) ?? "liquidazione collegata")
                        : <span className="muted">—</span> },
                    { k: "Riferimento norma", v: l.rule_reference ?? <span className="muted">—</span> },
                    { k: "Spiegazione", v: l.explanation ?? <span className="muted">—</span> },
                  ]} />
                </div>
              </details>
            ))}

            {(canValidate && (draft.status === "validation_required" || draft.status === "validated"))
              || draft.status === "approved" || draft.status === "exported" ? (
              <div className="cluster">
                {canValidate && draft.status === "validation_required" && (
                  <button className="btn btn--primary" disabled={transPending}
                          onClick={() => onTransition(draft.id, "validate")}>
                    <ShieldCheck size={14} /> Valida bozza
                  </button>
                )}
                {canValidate && draft.status === "validated" && (
                  <button className="btn btn--primary" disabled={transPending}
                          onClick={() => onTransition(draft.id, "approve")}>
                    <ShieldCheck size={14} /> Approva
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
            ) : null}
            <Callout tone="info" title="Export interno, non telematico">
              Nessun tracciato Entratel/CBI è implementato e nessun F24 viene trasmesso da questa piattaforma.
            </Callout>
          </div>
        )}
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scadenze
// ---------------------------------------------------------------------------

function Scadenze({ deadlines, onGoToSettlements }: { deadlines: FiscalDeadline[]; onGoToSettlements: () => void }) {
  const toConfirm = deadlines.filter((d) => d.due_date_status === "review_required" && d.status !== "cancelled");

  return (
    <div className="stack">
      {toConfirm.length > 0 && (
        <Callout tone="warning" title={`${toConfirm.length} ${toConfirm.length === 1 ? "scadenza con data da confermare" : "scadenze con data da confermare"}`}>
          Il calendario dei versamenti non ha potuto risolvere la data: verifica il differimento prima di programmare il pagamento.
        </Callout>
      )}
      <Section flush title="Scadenze fiscali"
               actions={<span className="text-xs muted">{deadlines.length} {deadlines.length === 1 ? "scadenza" : "scadenze"}</span>}
               footer="Le scadenze coprono le festività nazionali; le festività locali del santo patrono non sono modellate. Una scadenza validata genera esattamente una partita aperta in tesoreria.">
        {deadlines.length === 0 ? (
          <EmptyState title="Nessuna scadenza registrata" icon={<CalendarClock size={20} strokeWidth={1.8} />}
                      action={<button className="btn btn--ghost btn--sm" onClick={onGoToSettlements}>Vai alle liquidazioni</button>}>
            Le scadenze nascono dalla liquidazione: calcola e valida un periodo per generarle.
          </EmptyState>
        ) : (
          <table className="table table--flush table--static">
            <thead>
              <tr>
                <th>Adempimento</th><th>Scadenza</th><th>Differimento</th>
                <th className="th--num">Importo</th><th>Stato</th><th>Tesoreria</th>
              </tr>
            </thead>
            <tbody>
              {deadlines.map((d) => (
                <tr key={d.id}>
                  <td>
                    <div className="table__primary">{label(DEADLINE_KIND_LABEL, d.kind)}</div>
                    {d.notes && <div className="table__sub">{d.notes}</div>}
                  </td>
                  <td className="nowrap">
                    <div className="table__primary num">
                      {d.due_date ? dateIt(d.due_date) : <span className="na">da confermare</span>}
                    </div>
                    <div className="table__sub num">
                      statutaria {d.statutory_date ? dateIt(d.statutory_date) : "—"}
                      {d.due_date_status === "review_required" && <> · <Badge tone="warning">data da confermare</Badge></>}
                    </div>
                  </td>
                  <td className="text-xs muted">{d.deferral_reason ?? "—"}</td>
                  <td className="td--num strong"><Val v={d.amount} /></td>
                  <td><StatusBadge status={d.status} /></td>
                  <td>
                    {d.open_item_id
                      ? <Link to="/treasury" className="text-xs nowrap">Partita aperta <ArrowRight size={11} /></Link>
                      : <span className="muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
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
  if (rules.isLoading) {
    return (
      <div className="stack">
        <Section title="Rule set vigenti"><Skeleton rows={5} /></Section>
        <Section title="Codici tributo F24 caricati"><Skeleton kind="table" rows={5} /></Section>
      </div>
    );
  }
  if (rules.error) return <ErrorBanner error={rules.error} />;
  const data = rules.data!;
  return (
    <div className="stack">
      <Section title="Rule set vigenti — fonte autorevole e versione"
               actions={<span className="text-xs muted">motore <span className="mono">{engineVersion}</span></span>}>
        {data.rule_sets.length === 0 ? (
          <EmptyState title="Nessun rule set caricato" icon={<ScrollText size={20} strokeWidth={1.8} />}>
            Sincronizzare le regole verificate prima di calcolare.
          </EmptyState>
        ) : (
          <div className="rows">
            {data.rule_sets.map((r) => (
              <Row key={r.id}
                   leading={<ScrollText size={16} />}
                   title={<span className="cluster">
                     <span className="mono">{r.code}</span>
                     <Badge tone="info">{label(RULE_FAMILY_LABEL, r.rule_family)}</Badge>
                     <StatusBadge status={r.status} />
                   </span>}
                   sub={<>
                     <div>
                       {r.source.authority} — {r.source.title}
                       {r.source.legal_reference ? ` · ${r.source.legal_reference}` : ""}
                     </div>
                     <div className="text-2xs">
                       pubblicata {r.source.published_at ? dateIt(r.source.published_at) : "n.d."} ·
                       rilevata {dateIt(r.source.retrieved_at)} ·{" "}
                       <a href={r.source.url} target="_blank" rel="noreferrer">fonte</a> ·
                       impronta <span className="mono">{r.source.fingerprint.slice(0, 20)}…</span>
                     </div>
                     {(r.payload.supported_cases?.length || r.payload.unsupported_cases?.length) ? (
                       <details className="mt-2">
                         <summary className="text-2xs">Casi supportati e non supportati</summary>
                         <div className="mt-2 stack stack--sm">
                           {r.payload.supported_cases?.length ? (
                             <div><strong>Supportato:</strong> {r.payload.supported_cases!.join("; ")}</div>
                           ) : null}
                           {r.payload.unsupported_cases?.length ? (
                             <div><strong>Non supportato:</strong> {r.payload.unsupported_cases!.join("; ")}</div>
                           ) : null}
                         </div>
                       </details>
                     ) : null}
                   </>}
                   trailing={<span className="text-xs muted num nowrap">
                     v{r.version} · {dateIt(r.effective_from)} → {r.effective_to ? dateIt(r.effective_to) : "in vigore"}
                   </span>} />
            ))}
          </div>
        )}
      </Section>

      <Section flush title="Codici tributo F24 caricati"
               footer={<>Motore <span className="mono">{engineVersion}</span> · {transmission.note}</>}>
        {data.tax_codes.length === 0 ? (
          <EmptyState title="Nessun codice tributo">I codici tributo arrivano con il rule set Formato F24.</EmptyState>
        ) : (
          <table className="table table--flush table--static">
            <thead>
              <tr><th>Codice</th><th>Sezione</th><th>Uso</th>
                  <th>Validità</th><th>Periodo di riferimento</th></tr>
            </thead>
            <tbody>
              {data.tax_codes.map((c) => (
                <tr key={c.id}>
                  <td>
                    <div className="table__primary mono">{c.code}</div>
                    <div className="table__sub">{c.description ?? "—"}</div>
                  </td>
                  <td>{label(SECTION_LABEL, c.section)}</td>
                  <td className="text-xs muted">{label(USAGE_LABEL, c.usage)}</td>
                  <td className="num nowrap text-xs">
                    {dateIt(c.valid_from)} → {c.valid_to ? dateIt(c.valid_to) : "in vigore"}
                  </td>
                  <td>{c.requires_reference_period ? "richiesto" : "non richiesto"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <details>
        <summary className="eyebrow eyebrow--muted">Catena di provenienza e limitazioni</summary>
        <div className="mt-2">
          <Callout tone="neutral" title="Come nasce ogni numero">
            <ul className="mgmt-issues">
              <li>Fonte autorevole → rule set versionato → motore deterministico → traccia → validazione umana → spiegazione AI (sola lettura).</li>
              <li>Ogni liquidazione registra: rule set, versione formula, voci IVA contate ed escluse, passaggi e regole applicate, data di scadenza statutaria e risolta.</li>
              <li>Ogni riga F24 riporta la liquidazione di origine e il riferimento normativo del codice tributo.</li>
              <li>Una scadenza validata genera esattamente una partita aperta in tesoreria.</li>
            </ul>
            {limitations.length > 0 && (
              <ul className="mgmt-issues mt-2">
                {limitations.map((l) => <li key={l}>{l}</li>)}
              </ul>
            )}
          </Callout>
        </div>
      </details>
    </div>
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
    <Modal title="Nuova voce IVA"
           subtitle="La voce è immutabile: una correzione si registra come nuova voce."
           onClose={onClose}
           footer={
             <>
               <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
               <button className="btn btn--primary" disabled={pending || !form.competence_date || !form.taxable_amount}
                       onClick={save}>{pending ? "Registrazione…" : "Registra"}</button>
             </>
           }>
      <div className="form-section">
        <div className="form-section__title">Operazione</div>
        <div className="form-grid">
          <Field label="Direzione" htmlFor="ve-direction">
            <select id="ve-direction" className="select" value={form.direction} onChange={(e) => set("direction", e.target.value)}>
              <option value="sale">Vendita (IVA a debito)</option>
              <option value="purchase">Acquisto (IVA a credito)</option>
            </select>
          </Field>
          <Field label="Data di competenza" htmlFor="ve-competence">
            <input id="ve-competence" className="input" type="date" value={form.competence_date}
                   onChange={(e) => set("competence_date", e.target.value)} />
          </Field>
          <Field label="Imponibile" htmlFor="ve-taxable" hint="Decimale con punto, es. 1000.00">
            <input id="ve-taxable" className="input" value={form.taxable_amount} placeholder="1000.00" inputMode="decimal"
                   onChange={(e) => set("taxable_amount", e.target.value)} />
          </Field>
          <Field label="IVA" htmlFor="ve-vat" hint="Se assente la voce sarà classificata come da verificare, mai come zero">
            <input id="ve-vat" className="input" value={form.vat_amount} placeholder="220.00" inputMode="decimal"
                   onChange={(e) => set("vat_amount", e.target.value)} />
          </Field>
          <Field label="Aliquota %" htmlFor="ve-rate">
            <input id="ve-rate" className="input" value={form.vat_rate} inputMode="decimal"
                   onChange={(e) => set("vat_rate", e.target.value)} />
          </Field>
          <Field label="Natura" htmlFor="ve-nature" hint="Es. N1, N4 — in alternativa all'aliquota">
            <input id="ve-nature" className="input" value={form.vat_nature}
                   onChange={(e) => set("vat_nature", e.target.value)} />
          </Field>
          {form.direction === "purchase" && (
            <Field label="Detraibile" htmlFor="ve-deductible">
              <select id="ve-deductible" className="select" value={form.deductible} onChange={(e) => set("deductible", e.target.value)}>
                <option value="yes">Sì</option>
                <option value="no">No</option>
              </select>
            </Field>
          )}
        </div>
      </div>
      <div className="form-section">
        <div className="form-section__title">Documento e controparte</div>
        <div className="form-grid">
          <Field label="N. documento" htmlFor="ve-docno">
            <input id="ve-docno" className="input" value={form.document_number}
                   onChange={(e) => set("document_number", e.target.value)} />
          </Field>
          <Field label="Data documento" htmlFor="ve-docdate">
            <input id="ve-docdate" className="input" type="date" value={form.document_date}
                   onChange={(e) => set("document_date", e.target.value)} />
          </Field>
          <Field label="Controparte" htmlFor="ve-cp">
            <input id="ve-cp" className="input" value={form.counterparty_name}
                   onChange={(e) => set("counterparty_name", e.target.value)} />
          </Field>
          <Field label="P.IVA controparte" htmlFor="ve-cpvat">
            <input id="ve-cpvat" className="input" value={form.counterparty_vat}
                   onChange={(e) => set("counterparty_vat", e.target.value)} />
          </Field>
          <Field label="Note" htmlFor="ve-notes" span2>
            <input id="ve-notes" className="input" value={form.notes} onChange={(e) => set("notes", e.target.value)} />
          </Field>
        </div>
      </div>
    </Modal>
  );
}

function ImportModal({ onClose, onSave, pending }: {
  onClose: () => void; onSave: (json: string) => void; pending: boolean;
}) {
  const [json, setJson] = useState(ENTRY_TEMPLATE);
  return (
    <Modal title="Importa voci IVA"
           subtitle="Importazione idempotente: reimportare lo stesso file non duplica le voci."
           onClose={onClose}
           footer={
             <>
               <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
               <button className="btn btn--primary" disabled={pending} onClick={() => onSave(json)}>
                 <Upload size={14} /> {pending ? "Importazione…" : "Importa"}
               </button>
             </>
           }>
      <Field label="Righe da importare (JSON)" htmlFor="vi-json"
             hint={<>Ogni riga richiede <code>source_ref</code>. Un <code>source_ref</code> esistente con contenuto diverso viene rifiutato: registrare una rettifica, non modificare lo storico.</>}>
        <textarea id="vi-json" className="textarea w-full mono" rows={12} value={json} spellCheck={false}
                  onChange={(e) => setJson(e.target.value)} />
      </Field>
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
    <Modal title={`Valida liquidazione ${s.period?.label ?? ""} v${s.version}`}
           subtitle="Atto umano permissionato: crea la scadenza e la partita di tesoreria, esattamente una volta. L'AI non può eseguirlo."
           onClose={onClose}
           footer={
             <>
               <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
               <button className="btn btn--primary" disabled={!canSubmit || (critical.length > 0 && (!ack || !note.trim()))}
                       onClick={() => onSave({ note, acknowledge_warnings: ack })}>
                 <FilePlus2 size={14} /> {canSubmit ? "Valida" : "Validazione…"}
               </button>
             </>
           }>
      <div className="stack">
        <div className="grid-auto grid-auto--sm">
          <Tile label="Da versare" value={<Val v={s.payable_amount} />}
                tone={s.payable_amount && Number(s.payable_amount) > 0 ? "warn" : "muted"} />
          <Tile label="Posizione netta" value={<Val v={s.net_position} />} />
          <Tile label="Scadenza" value={s.deadline?.due_date ? dateIt(s.deadline.due_date) : <span className="na">da confermare</span>} />
        </div>

        {s.warnings.length > 0 && <SeverityCallouts warnings={s.warnings} />}

        {critical.length > 0 && (
          <label className="check">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            Dichiaro di aver verificato le segnalazioni critiche e di assumermene la responsabilità.
          </label>
        )}

        <Field label={critical.length > 0 ? "Nota di validazione (obbligatoria)" : "Nota di validazione"} htmlFor="vs-note"
               hint={critical.length > 0 ? "Motiva la validazione nonostante le segnalazioni critiche." : "Facoltativa: resta nella traccia della liquidazione."}>
          <textarea id="vs-note" className="textarea w-full" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
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
    <Modal title={`Verifica voce ${entry.document_number ?? shortId(entry.id)}`}
           subtitle="La conferma non modifica la voce originale: registra una nuova voce derivata che la sostituisce nel calcolo."
           onClose={onClose}
           footer={
             <>
               <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
               <button className="btn btn--primary" disabled={pending}
                       onClick={() => onSave({
                         treatment,
                         deductible: deductible === "keep" ? null : deductible === "yes",
                         reason,
                       })}><ShieldCheck size={14} /> {pending ? "Conferma…" : "Conferma trattamento"}</button>
             </>
           }>
      <div className="stack">
        <KV columns={2} items={[
          { k: "Competenza", v: <span className="num">{dateIt(entry.competence_date)}</span> },
          { k: "Controparte", v: entry.counterparty_name ?? <span className="muted">—</span> },
          { k: "Imponibile / IVA", v: <span className="num"><Val v={entry.taxable_amount} /> / <Val v={entry.vat_amount} /></span> },
          { k: "Direzione", v: entry.direction === "sale" ? "Vendita" : "Acquisto" },
          { k: "Motivo attuale", v: entry.treatment_reason ?? <span className="muted">—</span> },
        ]} />

        <div className="form-section">
          <div className="form-section__title">Decisione</div>
          <div className="form-grid">
            <Field label="Trattamento" htmlFor="vc-treatment">
              <select id="vc-treatment" className="select" value={treatment} onChange={(e) => setTreatment(e.target.value)}>
                <option value="supported">Utilizzabile nel calcolo</option>
                <option value="unsupported">Non utilizzabile (esclusa)</option>
              </select>
            </Field>
            {entry.direction === "purchase" && (
              <Field label="Detraibilità" htmlFor="vc-deductible">
                <select id="vc-deductible" className="select" value={deductible} onChange={(e) => setDeductible(e.target.value)}>
                  <option value="keep">Invariata</option>
                  <option value="yes">Detraibile</option>
                  <option value="no">Indetraibile</option>
                </select>
              </Field>
            )}
            <Field label="Motivazione" htmlFor="vc-reason" span2 hint="Resta nella traccia della voce derivata.">
              <textarea id="vc-reason" className="textarea w-full" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </div>
        </div>
      </div>
    </Modal>
  );
}
