import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { ArrowRight, CalendarClock, CheckCircle2, FileWarning, FolderKanban, HandCoins, Landmark, Search, Sparkles } from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  CompanyListItem, DeMinimisPosition, FundingAssessment,
  FundingMatch, FundingOverview, FundingPractice, FundingProgramme,
  Page,
} from "../api/types";
import {
  Badge, Callout, EmptyState, ErrorBanner, KV, NA, PageHeader, Progress, Row, Section, Skeleton, Stat, Tabs, Tile, toast,
} from "../components/ui";
import { dateIt, dateTimeIt, money } from "../lib/format";

const WRITE_ROLES = ["admin", "management", "consultant", "backoffice",
                     "client_admin", "client_operator"];

type Tab = "programmi" | "opportunita" | "valutazioni" | "pratiche" | "posizione";

const RESULT_LABEL: Record<string, string> = {
  eligible_on_known_data: "Compatibile sui dati noti",
  potentially_eligible: "Potenzialmente compatibile",
  review_required: "Da verificare",
  insufficient_data: "Dati insufficienti",
  not_eligible: "Non compatibile",
  unsupported: "Non valutabile",
};
const RESULT_TONE: Record<string, string> = {
  eligible_on_known_data: "success", potentially_eligible: "warning",
  review_required: "warning", insufficient_data: "neutral",
  not_eligible: "danger", unsupported: "neutral",
};
const RULE_RESULT_LABEL: Record<string, string> = {
  satisfied: "Soddisfatto", not_satisfied: "Non soddisfatto",
  insufficient_data: "Dato mancante", unsupported: "Non supportato",
  review_required: "Verifica umana",
};
const RULE_TONE = (r: string) => r === "satisfied" ? "success" : r === "not_satisfied" ? "danger" : r === "review_required" ? "warning" : "neutral";
const PRACTICE_STATUS: Record<string, string> = {
  draft: "Bozza", data_collection: "Raccolta dati",
  document_collection: "Raccolta documenti", ready_to_submit: "Pronta",
  submitted: "Presentata", under_review: "In istruttoria",
  integration_requested: "Integrazione richiesta", approved: "Approvata",
  rejected: "Respinta", withdrawn: "Ritirata", closed: "Chiusa",
};
const PRACTICE_TONE = (s: string) => s === "approved" ? "success" : s === "rejected" ? "danger" : ["closed", "withdrawn"].includes(s) ? "neutral" : s === "integration_requested" ? "warning" : "primary";
const DOC_STATUS: Record<string, string> = {
  missing: "Mancante", requested: "Richiesto", received: "Ricevuto",
  validated: "Validato", rejected: "Respinto", not_applicable: "Non applicabile",
};
const ASSESSMENT_STATUS: Record<string, string> = {
  calculated: "Calcolata", review_required: "Da revisionare",
  reviewed: "Revisionata", approved_for_practice: "Approvata per pratica",
  rejected: "Respinta",
};
const PROGRAMME_STATUS: Record<string, string> = { open: "Aperto", closed: "Chiuso", draft: "Bozza", suspended: "Sospeso", upcoming: "In arrivo" };
const WINDOW_KIND: Record<string, string> = { submission: "presentazione", evaluation: "valutazione", disbursement: "erogazione", fixed: "fissa", rolling: "a sportello" };
const DM_STATUS: Record<string, string> = { available: "Capienza disponibile", exhausted: "Capienza esaurita", review_required: "Da verificare", unknown: "Non determinabile", insufficient_data: "Dati insufficienti" };
const DM_TONE = (s: string) => s === "available" ? "success" : s === "exhausted" ? "danger" : s === "review_required" ? "warning" : "neutral";
const yesNo = (v: boolean | null) => v === null ? null : v ? "Sì" : "No";

export default function FundingPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>("programmi");
  const [actionError, setActionError] = useState<unknown>(null);
  const [selectedProgramme, setSelectedProgramme] = useState<string | null>(null);
  const [selectedPractice, setSelectedPractice] = useState<string | null>(null);
  const canWrite = !!user && WRITE_ROLES.includes(user.role);

  const companies = useQuery({
    queryKey: ["companies", "all"],
    queryFn: () => api.get<Page<CompanyListItem>>("/companies?page=1&page_size=200"),
  });
  const cid = params.get("company") || companies.data?.items[0]?.id || "";
  const setCompany = (id: string) => setParams(id ? { company: id } : {});
  const companyName = companies.data?.items.find((c) => c.id === cid)?.legal_name;

  const programmes = useQuery({
    queryKey: ["funding-programmes"],
    queryFn: () => api.get<{ programmes: FundingProgramme[] }>("/funding/programmes"),
  });
  const programmeDetail = useQuery({
    queryKey: ["funding-programme", selectedProgramme],
    queryFn: () => api.get<FundingProgramme>(`/funding/programmes/${selectedProgramme}`),
    enabled: !!selectedProgramme,
  });
  const match = useQuery({
    queryKey: ["funding-match", cid],
    queryFn: () => api.get<FundingMatch>(`/funding/companies/${cid}/match`),
    enabled: !!cid && tab === "opportunita",
  });
  const overview = useQuery({
    queryKey: ["funding-overview", cid],
    queryFn: () => api.get<FundingOverview>(`/funding/companies/${cid}/overview`),
    enabled: !!cid,
  });
  const practiceDetail = useQuery({
    queryKey: ["funding-practice", selectedPractice],
    queryFn: () => api.get<FundingPractice>(`/funding/practices/${selectedPractice}`),
    enabled: !!selectedPractice,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["funding-overview", cid] });
    qc.invalidateQueries({ queryKey: ["funding-match", cid] });
    qc.invalidateQueries({ queryKey: ["funding-practice", selectedPractice] });
    qc.invalidateQueries({ queryKey: ["dossier"] });
    qc.invalidateQueries({ queryKey: ["practices"] });
  };

  const runAssessment = useMutation({
    mutationFn: (versionId: string) =>
      api.post<FundingAssessment>(`/funding/companies/${cid}/assessments`, { version_id: versionId }),
    onSuccess: () => { refresh(); setActionError(null); toast("Valutazione eseguita e salvata"); setTab("valutazioni"); }, onError: setActionError,
  });
  const reviewAssessment = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post(`/funding/assessments/${id}/review`, { action }),
    onSuccess: () => { refresh(); setActionError(null); toast("Valutazione aggiornata"); }, onError: setActionError,
  });
  const openPractice = useMutation({
    mutationFn: ({ versionId, assessmentId }: { versionId: string; assessmentId?: string }) =>
      api.post<FundingPractice>(`/funding/companies/${cid}/practices`, { version_id: versionId, assessment_id: assessmentId }),
    onSuccess: (p) => { refresh(); setActionError(null); setSelectedPractice(p.id); setTab("pratiche"); toast("Pratica aperta: checklist documentale creata"); },
    onError: setActionError,
  });
  const transition = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post(`/funding/practices/${id}/transition`, { action }),
    onSuccess: (_r, v) => { refresh(); setActionError(null); toast(`Pratica: ${PRACTICE_STATUS[v.action] ?? v.action}`); }, onError: setActionError,
  });
  const docUpdate = useMutation({
    mutationFn: ({ practiceId, docId, status }: { practiceId: string; docId: string; status: string }) =>
      api.patch(`/funding/practices/${practiceId}/documents/${docId}`, { status }),
    onSuccess: () => { refresh(); setActionError(null); toast("Checklist aggiornata"); }, onError: setActionError,
  });

  const ov = overview.data;
  const openPractices = (ov?.practices ?? []).filter((p) => !["closed", "withdrawn", "rejected"].includes(p.status));
  const openDeadlines = ov?.deadlines ?? [];
  const toReview = (ov?.assessments ?? []).filter((a) => a.status === "review_required" || a.status === "reviewed").length;
  const dm = ov?.de_minimis;

  return (
    <>
      <PageHeader
        hero
        eyebrow={<>Finanza e fisco{companyName ? ` · ${companyName}` : ""}</>}
        title="Finanza agevolata"
        question="Quale opportunità esiste per questa azienda e cosa manca per coglierla? Fonti ufficiali, valutazione deterministica, nessuna stima automatica."
        actions={
          <select className="select" aria-label="Azienda" value={cid} onChange={(e) => setCompany(e.target.value)}>
            {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
          </select>
        }
      />

      {overview.isLoading ? <Skeleton kind="stats" rows={4} /> : ov && (
        <div className="stat-grid">
          <Stat hero icon={<HandCoins size={14} />} label="Capienza de minimis"
                value={dm?.headroom != null ? money(dm.headroom) : <span className="na">n.d.</span>}
                hint={dm ? DM_STATUS[dm.status] ?? dm.status : undefined} />
          <Stat icon={<FolderKanban size={14} />} label="Pratiche in corso" value={openPractices.length}
                hint={`${ov.practices.length} totali`} onClick={() => setTab("pratiche")} />
          <Stat icon={<Sparkles size={14} />} label="Valutazioni da rivedere" value={toReview}
                hint={`${ov.assessments.length} valutazioni salvate`} tone={toReview ? "warn" : undefined} onClick={() => setTab("valutazioni")} />
          <Stat icon={<CalendarClock size={14} />} label="Scadenze aperte" value={openDeadlines.length}
                hint={openDeadlines[0] ? `prossima ${dateIt(openDeadlines[0].due_at)}` : "nessuna scadenza"} tone={openDeadlines.length ? "warn" : undefined} />
        </div>
      )}

      {actionError != null && <ErrorBanner error={actionError} />}

      <Tabs value={tab} onChange={setTab} tabs={[
        { key: "programmi", label: "Programmi", count: programmes.data?.programmes.length },
        { key: "opportunita", label: "Opportunità" },
        { key: "valutazioni", label: "Valutazioni", count: ov?.assessments.length, tone: toReview ? "warning" : undefined },
        { key: "pratiche", label: "Pratiche", count: ov?.practices.length },
        { key: "posizione", label: "Posizione agevolativa" },
      ]} />

      {tab === "programmi" && (
        <ProgrammesTab programmes={programmes.data?.programmes ?? []} loading={programmes.isLoading}
                       selected={selectedProgramme} onSelect={setSelectedProgramme}
                       detail={programmeDetail.data} detailLoading={programmeDetail.isLoading} />
      )}
      {tab === "opportunita" && (
        <MatchTab match={match.data} loading={match.isLoading} canWrite={canWrite} busy={runAssessment.isPending}
                  onAssess={(vid) => runAssessment.mutate(vid)} />
      )}
      {tab === "valutazioni" && (
        <AssessmentsTab overview={ov} loading={overview.isLoading} canWrite={canWrite}
                        onReview={(id, action) => reviewAssessment.mutate({ id, action })}
                        onOpenPractice={(versionId, assessmentId) => openPractice.mutate({ versionId, assessmentId })}
                        goMatch={() => setTab("opportunita")} />
      )}
      {tab === "pratiche" && (
        <PracticesTab overview={ov} loading={overview.isLoading} canWrite={canWrite}
                      selected={selectedPractice} onSelect={setSelectedPractice}
                      detail={practiceDetail.data} detailLoading={practiceDetail.isLoading}
                      onTransition={(id, action) => transition.mutate({ id, action })}
                      onDocUpdate={(practiceId, docId, status) => docUpdate.mutate({ practiceId, docId, status })}
                      goAssessments={() => setTab("valutazioni")} />
      )}
      {tab === "posizione" && <PositionTab overview={ov} loading={overview.isLoading} />}
    </>
  );
}

// ---------------------------------------------------------------------------
// Programmes
// ---------------------------------------------------------------------------

function ProgrammesTab({ programmes, loading, selected, onSelect, detail, detailLoading }: {
  programmes: FundingProgramme[]; loading: boolean;
  selected: string | null; onSelect: (id: string) => void;
  detail: FundingProgramme | undefined; detailLoading: boolean;
}) {
  if (loading) return <Skeleton kind="table" rows={5} />;
  if (!programmes.length) {
    return (
      <EmptyState title="Nessun programma censito" icon={<Landmark size={20} strokeWidth={1.8} />}>
        Le fonti ufficiali vengono inserite manualmente o via import strutturato.
      </EmptyState>
    );
  }
  return (
    <div className="grid-1-2">
      <Section title={<>Programmi <span className="tab__count">{programmes.length}</span></>} flush>
        <table className="table table--flush">
          <thead><tr><th>Programma</th><th>Stato</th></tr></thead>
          <tbody>
            {programmes.map((p) => (
              <tr key={p.id} onClick={() => onSelect(p.id)} className={p.id === selected ? "is-selected" : undefined}>
                <td>
                  <div className="table__primary">{p.title}</div>
                  <div className="table__sub">{p.authority_name ?? p.code}{p.version_count > 1 ? ` · ${p.version_count} versioni` : ""}</div>
                </td>
                <td><Badge tone={p.status === "open" ? "success" : "neutral"} title={p.status}>{PROGRAMME_STATUS[p.status] ?? p.status}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <ProgrammeDetail detail={detail} loading={detailLoading && !!selected} />
    </div>
  );
}

function ProgrammeDetail({ detail, loading }: { detail: FundingProgramme | undefined; loading: boolean }) {
  if (loading) return <Section title="Scheda programma"><Skeleton rows={6} /></Section>;
  if (!detail) {
    return (
      <Section title="Scheda programma">
        <EmptyState title="Seleziona un programma" icon={<Search size={20} strokeWidth={1.8} />}>Requisiti, benefici, spese ammissibili e documenti richiesti.</EmptyState>
      </Section>
    );
  }
  const v = detail.versions?.[0] ?? detail.current_version;
  return (
    <Section title={<>{detail.code} {v && <Badge tone="neutral" dot={false}>v{v.version_no}</Badge>}</>}
             actions={v && <><Badge tone={v.status === "open" ? "success" : "neutral"}>{PROGRAMME_STATUS[v.status] ?? v.status}</Badge>{v.aid_regime_code && <Badge tone="accent" dot={false}>{v.aid_regime_code}</Badge>}</>}
             footer={v?.source ? <>Fonte: {v.source.title} — {v.source.reference}{v.source.published_on && ` (${dateIt(v.source.published_on)})`}</> : undefined}>
      <h3>{detail.title}</h3>
      {detail.description && <p className="ink-500 text-sm">{detail.description}</p>}
      {v && (
        <div className="stack">
          {v.windows?.length > 0 && (
            <div className="grid-auto grid-auto--sm">
              {v.windows.map((w) => (
                <Tile key={w.id} label={`Finestra ${WINDOW_KIND[w.kind] ?? w.kind}`} icon={<CalendarClock size={12} />}
                      value={w.opens_at ? dateIt(w.opens_at) : <span className="na">apertura n.d.</span>}
                      hint={w.closes_at ? `chiude ${dateTimeIt(w.closes_at)}` : "senza chiusura dichiarata"} />
              ))}
            </div>
          )}
          {v.requirements && v.requirements.length > 0 && (
            <div>
              <div className="card__title">Requisiti</div>
              <div className="rows">
                {v.requirements.map((r) => (
                  <Row key={r.id} title={r.description} sub={r.rule_code} trailing={r.mandatory ? <Badge tone="danger" dot={false}>Obbligatorio</Badge> : <Badge tone="neutral" dot={false}>Facoltativo</Badge>} />
                ))}
              </div>
            </div>
          )}
          {v.benefits && v.benefits.length > 0 && (
            <div>
              <div className="card__title">Benefici</div>
              <div className="rows">
                {v.benefits.map((b) => (
                  <Row key={b.id} leading={<HandCoins size={16} />} title={b.benefit_type}
                       sub={[b.max_aid_intensity && `intensità max ${b.max_aid_intensity}`, b.notes].filter(Boolean).join(" · ") || undefined}
                       trailing={b.max_amount ? <span className="strong num">max {money(b.max_amount)}</span> : undefined} />
                ))}
              </div>
            </div>
          )}
          {v.expense_categories && v.expense_categories.length > 0 && (
            <div>
              <div className="card__title">Spese</div>
              <div className="rows">
                {v.expense_categories.map((e) => (
                  <Row key={e.id} title={e.label} sub={e.conditions ?? undefined}
                       trailing={<Badge tone={e.status === "eligible" ? "success" : e.status === "excluded" ? "danger" : "warning"}>{e.status === "eligible" ? "Ammissibile" : e.status === "excluded" ? "Esclusa" : "Con condizioni"}</Badge>} />
                ))}
              </div>
            </div>
          )}
          {v.document_requirements && v.document_requirements.length > 0 && (
            <div>
              <div className="card__title">Documenti richiesti</div>
              <div className="rows">
                {v.document_requirements.map((d) => (
                  <Row key={d.id} leading={<FileWarning size={16} />} title={d.label} sub={[d.doc_type.replaceAll("_", " "), d.stage].filter(Boolean).join(" · ")}
                       trailing={d.required ? <Badge tone="danger" dot={false}>Obbligatorio</Badge> : undefined} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Match / opportunities
// ---------------------------------------------------------------------------

function MatchTab({ match, loading, canWrite, busy, onAssess }: {
  match: FundingMatch | undefined; loading: boolean; canWrite: boolean; busy: boolean;
  onAssess: (versionId: string) => void;
}) {
  if (loading) return <Skeleton rows={6} />;
  if (!match) return <EmptyState title="Seleziona un'azienda" />;
  const order: [string, string][] = [
    ["eligible_on_known_data", "Compatibili sui dati noti"],
    ["potentially_eligible", "Potenzialmente compatibili"],
    ["review_required", "Da verificare professionalmente"],
    ["insufficient_data", "Dati insufficienti"],
    ["not_eligible", "Non compatibili"],
    ["unsupported", "Non valutabili"],
  ];
  const total = Object.values(match.groups).reduce((s, g) => s + g.length, 0);
  return (
    <div className="stack">
      <Callout tone="info" title={`Pre-screening deterministico su ${total} versioni di programma`}>
        Raggruppato per esito, mai un punteggio. «Dato mancante» è una risposta legittima: l'ammissibilità resta una decisione professionale. Motore <span className="mono">{match.engine_version}</span>.
      </Callout>
      {order.map(([key, label]) => {
        const entries = match.groups[key] ?? [];
        if (!entries.length) return null;
        return (
          <Section key={key} title={<>{label} <span className={`tab__count${key === "eligible_on_known_data" ? "" : key === "not_eligible" ? " tab__count--danger" : key === "insufficient_data" || key === "unsupported" ? "" : " tab__count--warning"}`}>{entries.length}</span></>}>
            <div className="rows">
              {entries.map((e) => {
                const ok = e.results.filter((r) => r.result === "satisfied").length;
                return (
                  <Row key={e.version_id} leading={<Landmark size={16} />}
                       tone={key === "eligible_on_known_data" ? "success" : key === "not_eligible" ? "critical" : key === "insufficient_data" || key === "unsupported" ? undefined : "warning"}
                       title={e.programme_title}
                       sub={<>
                         <span>v{e.version_no} · {PROGRAMME_STATUS[e.status] ?? e.status} · {ok}/{e.results.length} regole soddisfatte</span>
                         <details className="mt-1"><summary className="text-2xs">Perché</summary>
                           <ul className="mgmt-issues mt-1">
                             {e.results.map((r, i) => <li key={i}><Badge tone={RULE_TONE(r.result)} dot={false}>{RULE_RESULT_LABEL[r.result] ?? r.result}</Badge> {r.description}</li>)}
                           </ul>
                         </details>
                       </>}
                       trailing={canWrite ? <button className="btn btn--primary btn--sm" disabled={busy} onClick={() => onAssess(e.version_id)}>Valuta <ArrowRight size={12} /></button> : undefined} />
                );
              })}
            </div>
          </Section>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Assessments
// ---------------------------------------------------------------------------

function AssessmentsTab({ overview, loading, canWrite, onReview, onOpenPractice, goMatch }: {
  overview: FundingOverview | undefined; loading: boolean; canWrite: boolean;
  onReview: (id: string, action: string) => void;
  onOpenPractice: (versionId: string, assessmentId: string) => void;
  goMatch: () => void;
}) {
  if (loading) return <Skeleton rows={6} />;
  const assessments = overview?.assessments ?? [];
  if (!assessments.length) {
    return (
      <EmptyState title="Nessuna valutazione salvata" icon={<Sparkles size={20} strokeWidth={1.8} />}
                  action={<button className="btn btn--primary btn--sm" onClick={goMatch}>Vai alle opportunità</button>}>
        Esegui una valutazione da «Opportunità»: ogni regola lascia evidenza del perché.
      </EmptyState>
    );
  }
  return (
    <div className="stack">
      {assessments.map((a) => {
        const items = a.items ?? [];
        const ok = items.filter((i) => i.result === "satisfied").length;
        return (
          <Section key={a.id}
                   title={<>{a.programme_version ? `Versione ${a.programme_version.version_no}` : "Versione programma"} <Badge tone={RESULT_TONE[a.result] ?? "neutral"}>{RESULT_LABEL[a.result] ?? a.result}</Badge> <Badge tone="neutral" dot={false}>{ASSESSMENT_STATUS[a.status] ?? a.status}</Badge></>}
                   actions={canWrite && (
                     <>
                       {a.status === "review_required" && <button className="btn btn--ghost btn--sm" onClick={() => onReview(a.id, "reviewed")}>Segna revisionata</button>}
                       {a.status === "reviewed" && <button className="btn btn--primary btn--sm" onClick={() => onReview(a.id, "approved_for_practice")}>Approva per pratica</button>}
                       {a.status === "approved_for_practice" && <button className="btn btn--primary btn--sm" onClick={() => onOpenPractice(a.version_id, a.id)}>Apri pratica <ArrowRight size={12} /></button>}
                     </>
                   )}
                   footer={<>{dateTimeIt(a.assessed_at)} · motore <span className="mono">{a.engine_version}</span>{a.reviewed_at && <> · revisionata {dateTimeIt(a.reviewed_at)}</>}</>}>
            {items.length > 0 && <Progress value={ok} max={items.length} tone={ok === items.length ? "success" : "accent"} label={`${ok}/${items.length} regole soddisfatte`} />}
            {a.missing_data.length > 0 && (
              <Callout tone="warning" title={`Dati mancanti (${a.missing_data.length})`}>
                {a.missing_data.map((m) => m.description || m.rule_code).join(" · ")}
              </Callout>
            )}
            {a.unsupported_rules.length > 0 && <Callout tone="neutral" title="Regole non supportate dal motore">{a.unsupported_rules.join(", ")}</Callout>}
            {items.length > 0 && (
              <div className="rows mt-2">
                {items.map((i) => (
                  <Row key={i.id} title={i.description} sub={`${i.rule_code}${i.mandatory ? " · obbligatoria" : ""}`}
                       trailing={<Badge tone={RULE_TONE(i.result)}>{RULE_RESULT_LABEL[i.result] ?? i.result}</Badge>} />
                ))}
              </div>
            )}
          </Section>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Practices
// ---------------------------------------------------------------------------

const NEXT: Record<string, string[]> = {
  draft: ["data_collection", "withdrawn"],
  data_collection: ["document_collection", "withdrawn"],
  document_collection: ["ready_to_submit", "data_collection", "withdrawn"],
  ready_to_submit: ["submitted", "document_collection", "withdrawn"],
  submitted: ["under_review", "withdrawn"],
  under_review: ["integration_requested", "approved", "rejected"],
  integration_requested: ["under_review", "rejected", "withdrawn"],
  approved: ["closed"], rejected: ["closed"], withdrawn: ["closed"],
};

function PracticesTab({ overview, loading, canWrite, selected, onSelect, detail, detailLoading, onTransition, onDocUpdate, goAssessments }: {
  overview: FundingOverview | undefined; loading: boolean; canWrite: boolean;
  selected: string | null; onSelect: (id: string) => void;
  detail: FundingPractice | undefined; detailLoading: boolean;
  onTransition: (id: string, action: string) => void;
  onDocUpdate: (practiceId: string, docId: string, status: string) => void;
  goAssessments: () => void;
}) {
  if (loading) return <Skeleton kind="table" rows={4} />;
  const practices = overview?.practices ?? [];
  if (!practices.length) {
    return (
      <EmptyState title="Nessuna pratica aperta" icon={<FolderKanban size={20} strokeWidth={1.8} />}
                  action={<button className="btn btn--ghost btn--sm" onClick={goAssessments}>Vai alle valutazioni</button>}>
        Approva una valutazione per aprire una pratica: la checklist documentale viene creata automaticamente.
      </EmptyState>
    );
  }
  const docs = detail?.documents ?? [];
  const docsDone = docs.filter((d) => d.status === "validated" || d.status === "not_applicable").length;
  return (
    <div className="grid-1-2">
      <Section title={<>Pratiche <span className="tab__count">{practices.length}</span></>} flush>
        <table className="table table--flush">
          <thead><tr><th>Pratica</th><th>Stato</th></tr></thead>
          <tbody>
            {practices.map((p) => (
              <tr key={p.id} onClick={() => onSelect(p.id)} className={p.id === selected ? "is-selected" : undefined}>
                <td>
                  <div className="table__primary">{p.programme_title ?? "Programma non disponibile"}</div>
                  <div className="table__sub">
                    {[p.programme_code, p.version_no != null ? `v${p.version_no}` : null,
                      p.created_at ? `aperta ${dateIt(p.created_at)}` : null].filter(Boolean).join(" · ")}
                  </div>
                </td>
                <td><Badge tone={PRACTICE_TONE(p.status)} title={p.status}>{PRACTICE_STATUS[p.status] ?? p.status}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      {detailLoading && selected ? <Section title="Pratica"><Skeleton rows={6} /></Section> : !detail ? (
        <Section title="Pratica"><EmptyState title="Seleziona una pratica">Stato, prossimi passi, checklist documenti e scadenze.</EmptyState></Section>
      ) : (
        <Section title={<>{detail.programme_title ?? "Pratica"} <Badge tone={PRACTICE_TONE(detail.status)}>{PRACTICE_STATUS[detail.status] ?? detail.status}</Badge></>}
                 actions={canWrite && (NEXT[detail.status] ?? []).length > 0 && (
                   <div className="cluster">
                     {(NEXT[detail.status] ?? []).map((a) => (
                       <button key={a} className={`btn btn--sm ${["withdrawn", "rejected"].includes(a) ? "btn--danger" : a === "approved" || a === "submitted" ? "btn--primary" : "btn--ghost"}`}
                               onClick={() => onTransition(detail.id, a)}>
                         {PRACTICE_STATUS[a] ?? a}
                       </button>
                     ))}
                   </div>
                 )}>
          {docs.length > 0 && (
            <>
              <div className="card__title">Checklist documenti</div>
              <Progress value={docsDone} max={docs.length} tone={docsDone === docs.length ? "success" : "accent"} label={`${docsDone}/${docs.length} completati`} />
              <div className="rows mt-2">
                {docs.map((d) => (
                  <Row key={d.id} tone={d.status === "missing" && d.required ? "critical" : d.status === "validated" ? "success" : undefined}
                       leading={d.status === "validated" ? <CheckCircle2 size={16} /> : <FileWarning size={16} />}
                       title={<>{d.label}{d.required && <span className="neg" title="Obbligatorio"> *</span>}</>}
                       sub={d.doc_type.replaceAll("_", " ")}
                       trailing={canWrite ? (
                         <select className="select select--sm" value={d.status} aria-label={`Stato documento ${d.label}`}
                                 onChange={(e) => onDocUpdate(detail.id, d.id, e.target.value)}>
                           {Object.entries(DOC_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                         </select>
                       ) : (
                         <Badge tone={d.status === "validated" ? "success" : d.status === "missing" ? "danger" : "neutral"}>{DOC_STATUS[d.status] ?? d.status}</Badge>
                       )} />
                ))}
              </div>
            </>
          )}
          {detail.deadlines && detail.deadlines.length > 0 && (
            <>
              <div className="card__title mt-4">Scadenze</div>
              <div className="rows">
                {detail.deadlines.map((dl) => (
                  <Row key={dl.id} leading={<CalendarClock size={16} />} tone={dl.status === "open" ? "warning" : undefined} title={dl.title}
                       sub={dateTimeIt(dl.due_at)} trailing={<Badge tone={dl.status === "open" ? "warning" : "neutral"}>{dl.status === "open" ? "Aperta" : dl.status === "done" ? "Fatta" : dl.status}</Badge>} />
                ))}
              </div>
            </>
          )}
          {detail.notes && <Callout tone="neutral" title="Note">{detail.notes}</Callout>}
        </Section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Position (profile + aids + de minimis)
// ---------------------------------------------------------------------------

function PositionTab({ overview, loading }: { overview: FundingOverview | undefined; loading: boolean }) {
  if (loading) return <Skeleton rows={8} />;
  if (!overview) return <EmptyState title="Seleziona un'azienda" />;
  const p = overview.profile;
  const dm: DeMinimisPosition = overview.de_minimis;
  const used = dm.aid_total != null && dm.regime ? Number(dm.aid_total) : null;
  const threshold = dm.regime ? Number(dm.regime.threshold) : null;
  return (
    <div className="stack">
      <div className="grid-2">
        <Section title="Profilo agevolativo">
          {!p ? (
            <Callout tone="neutral" title="Profilo non dichiarato">I dati mancanti restano espliciti e bloccano le regole che li richiedono: nessuna assunzione automatica.</Callout>
          ) : (
            <KV columns={2} items={[
              { k: "Costituzione", v: p.incorporated_on ? dateIt(p.incorporated_on) : null },
              { k: "Startup", v: yesNo(p.is_startup) },
              { k: "Startup innovativa", v: yesNo(p.is_innovative_startup) },
              { k: "Quota femminile", v: p.female_ownership_pct != null ? `${p.female_ownership_pct}%` : null },
              { k: "Quota giovanile", v: p.youth_ownership_pct != null ? `${p.youth_ownership_pct}%` : null },
              { k: "Regione progetto", v: p.project_region },
              { k: "Impresa unica verificata", v: yesNo(p.single_undertaking_known) },
              { k: "Storico aiuti completo", v: yesNo(p.aid_history_complete) },
            ]} />
          )}
        </Section>
        <Section title="Posizione de minimis"
                 footer={dm.regime ? <>{dm.regime.code} · {dm.regime.legal_reference} · formula <span className="mono">{dm.regime.formula_version}</span></> : undefined}>
          <div className="cluster mb-3"><Badge tone={DM_TONE(dm.status)}>{DM_STATUS[dm.status] ?? dm.status}</Badge></div>
          {used != null && threshold != null && (
            <Progress value={used} max={threshold} tone={used >= threshold ? "danger" : used / threshold > 0.8 ? "warn" : "success"}
                      label={`${money(dm.aid_total)} su ${money(dm.regime!.threshold)}`} />
          )}
          <div className="grid-auto grid-auto--sm mt-3">
            <Tile label="Soglia" value={dm.regime ? money(dm.regime.threshold) : <NA />} hint={dm.regime ? `su ${dm.regime.period_months} mesi` : undefined} />
            <Tile label="Aiuti nella finestra" value={dm.aid_total != null ? money(dm.aid_total) : <NA />} hint={dm.window_start ? `dal ${dateIt(dm.window_start)}` : undefined} />
            <Tile label="Capienza residua" value={dm.headroom != null ? money(dm.headroom) : <NA />} tone={dm.headroom != null ? (Number(dm.headroom) <= 0 ? "danger" : "success") : undefined} />
          </div>
          {((dm.reasons ?? []).length > 0 || dm.reason) && (
            <Callout tone="warning" title="Attenzione">
              <ul className="mgmt-issues">{[...(dm.reasons ?? []), ...(dm.reason ? [dm.reason] : [])].map((r, i) => <li key={i}>{r}</li>)}</ul>
            </Callout>
          )}
        </Section>
      </div>
      <Section title={<>Storico aiuti dichiarati <span className="tab__count">{overview.aids.length}</span></>} flush={overview.aids.length > 0}>
        {!overview.aids.length ? <EmptyState title="Nessun aiuto dichiarato">Senza storico completo la posizione de minimis resta indeterminata.</EmptyState> : (
          <table className="table table--flush table--static">
            <thead><tr><th>Programma</th><th>Regime</th><th>Concesso</th><th className="th--num">Importo</th><th>Stato</th></tr></thead>
            <tbody>
              {overview.aids.map((a) => (
                <tr key={a.id}>
                  <td><div className="table__primary">{a.programme_label}</div><div className="table__sub">{a.authority ?? ""}{a.reference ? ` · ${a.reference}` : ""}</div></td>
                  <td>{a.regime_code ?? <span className="muted">—</span>}</td>
                  <td className="num">{dateIt(a.granted_on)}</td>
                  <td className="td--num strong">{money(a.amount)}{a.gge_amount && <div className="table__sub">ESL {money(a.gge_amount)}</div>}</td>
                  <td><Badge tone={a.status === "granted" || a.status === "confirmed" ? "success" : "neutral"}>{a.status === "granted" ? "Concesso" : a.status === "confirmed" ? "Confermato" : a.status === "declared" ? "Dichiarato" : a.status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      {overview.limitations.length > 0 && (
        <details>
          <summary className="eyebrow eyebrow--muted">Limiti del modulo ({overview.limitations.length})</summary>
          <Section tone="section" className="mt-2"><ul className="mgmt-issues">{overview.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></Section>
        </details>
      )}
    </div>
  );
}
