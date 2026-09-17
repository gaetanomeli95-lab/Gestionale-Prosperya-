import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Landmark } from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  CompanyListItem, DeMinimisPosition, FundingAssessment,
  FundingMatch, FundingOverview, FundingPractice, FundingProgramme,
  Page,
} from "../api/types";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { dateIt, dateTimeIt, money } from "../lib/format";

const WRITE_ROLES = ["admin", "management", "consultant", "backoffice",
                     "client_admin", "client_operator"];

type Tab = "programmi" | "opportunita" | "valutazioni" | "pratiche" | "posizione";

const TABS: { key: Tab; label: string }[] = [
  { key: "programmi", label: "Programmi" },
  { key: "opportunita", label: "Opportunità" },
  { key: "valutazioni", label: "Valutazioni" },
  { key: "pratiche", label: "Pratiche" },
  { key: "posizione", label: "Posizione agevolativa" },
];

const RESULT_LABEL: Record<string, string> = {
  eligible_on_known_data: "Compatibile sui dati noti",
  potentially_eligible: "Potenzialmente compatibile",
  review_required: "Da verificare",
  insufficient_data: "Dati insufficienti",
  not_eligible: "Non compatibile",
  unsupported: "Non valutabile",
};
const RESULT_TONE: Record<string, string> = {
  eligible_on_known_data: "ok", potentially_eligible: "warn",
  review_required: "warn", insufficient_data: "neutral",
  not_eligible: "bad", unsupported: "neutral",
};
const RULE_RESULT_LABEL: Record<string, string> = {
  satisfied: "soddisfatto", not_satisfied: "non soddisfatto",
  insufficient_data: "dato mancante", unsupported: "non supportato",
  review_required: "verifica umana",
};
const PRACTICE_STATUS: Record<string, string> = {
  draft: "Bozza", data_collection: "Raccolta dati",
  document_collection: "Raccolta documenti", ready_to_submit: "Pronta",
  submitted: "Presentata", under_review: "In istruttoria",
  integration_requested: "Integrazione richiesta", approved: "Approvata",
  rejected: "Respinta", withdrawn: "Ritirata", closed: "Chiusa",
};
const DOC_STATUS: Record<string, string> = {
  missing: "mancante", requested: "richiesto", received: "ricevuto",
  validated: "validato", rejected: "respinto", not_applicable: "n/a",
};
const ASSESSMENT_STATUS: Record<string, string> = {
  calculated: "Calcolata", review_required: "Da revisionare",
  reviewed: "Revisionata", approved_for_practice: "Approvata per pratica",
  rejected: "Respinta",
};

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
    enabled: !!cid && (tab === "posizione" || tab === "valutazioni" || tab === "pratiche"),
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
  };

  const runAssessment = useMutation({
    mutationFn: (versionId: string) =>
      api.post<FundingAssessment>(`/funding/companies/${cid}/assessments`,
                                  { version_id: versionId }),
    onSuccess: refresh, onError: setActionError,
  });
  const reviewAssessment = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post(`/funding/assessments/${id}/review`, { action }),
    onSuccess: refresh, onError: setActionError,
  });
  const openPractice = useMutation({
    mutationFn: ({ versionId, assessmentId }: { versionId: string; assessmentId?: string }) =>
      api.post<FundingPractice>(`/funding/companies/${cid}/practices`,
                                { version_id: versionId, assessment_id: assessmentId }),
    onSuccess: (p) => { refresh(); setSelectedPractice(p.id); setTab("pratiche"); },
    onError: setActionError,
  });
  const transition = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post(`/funding/practices/${id}/transition`, { action }),
    onSuccess: refresh, onError: setActionError,
  });
  const docUpdate = useMutation({
    mutationFn: ({ practiceId, docId, status }: { practiceId: string; docId: string; status: string }) =>
      api.patch(`/funding/practices/${practiceId}/documents/${docId}`, { status }),
    onSuccess: refresh, onError: setActionError,
  });

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title"><Landmark size={20} /> Finanza agevolata</h1>
          <p className="page__subtitle">
            Programmi, valutazione deterministica e pratiche — fonti ufficiali,
            nessuna stima automatica.
          </p>
        </div>
        <select className="input" style={{ maxWidth: 320 }} value={cid}
                onChange={(e) => setCompany(e.target.value)}>
          {companies.data?.items.map((c) => (
            <option key={c.id} value={c.id}>{c.legal_name}</option>
          ))}
        </select>
      </header>

      {actionError != null && <ErrorBanner error={actionError} />}

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key}
                  className={`tab${tab === t.key ? " tab--active" : ""}`}
                  onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "programmi" && (
        <ProgrammesTab programmes={programmes.data?.programmes ?? []}
                       loading={programmes.isLoading}
                       selected={selectedProgramme}
                       onSelect={setSelectedProgramme}
                       detail={programmeDetail.data} />
      )}

      {tab === "opportunita" && (
        <MatchTab match={match.data} loading={match.isLoading}
                  canWrite={canWrite}
                  onAssess={(vid) => runAssessment.mutate(vid)} />
      )}

      {tab === "valutazioni" && (
        <AssessmentsTab overview={overview.data} loading={overview.isLoading}
                        canWrite={canWrite}
                        onReview={(id, action) => reviewAssessment.mutate({ id, action })}
                        onOpenPractice={(versionId, assessmentId) =>
                          openPractice.mutate({ versionId, assessmentId })} />
      )}

      {tab === "pratiche" && (
        <PracticesTab overview={overview.data} loading={overview.isLoading}
                      canWrite={canWrite}
                      selected={selectedPractice}
                      onSelect={setSelectedPractice}
                      detail={practiceDetail.data}
                      onTransition={(id, action) => transition.mutate({ id, action })}
                      onDocUpdate={(practiceId, docId, status) =>
                        docUpdate.mutate({ practiceId, docId, status })} />
      )}

      {tab === "posizione" && (
        <PositionTab overview={overview.data} loading={overview.isLoading} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Programmes
// ---------------------------------------------------------------------------

function ProgrammesTab({ programmes, loading, selected, onSelect, detail }: {
  programmes: FundingProgramme[]; loading: boolean;
  selected: string | null; onSelect: (id: string) => void;
  detail: FundingProgramme | undefined;
}) {
  if (loading) return <Spinner />;
  if (!programmes.length) {
    return <EmptyState>Nessun programma censito. Le fonti ufficiali vengono
      inserite manualmente o via import strutturato.</EmptyState>;
  }
  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <Card className="card__pad">
        <table className="table">
          <thead>
            <tr><th>Programma</th><th>Ente</th><th>Stato</th><th>Versioni</th></tr>
          </thead>
          <tbody>
            {programmes.map((p) => (
              <tr key={p.id} onClick={() => onSelect(p.id)}
                  style={{ cursor: "pointer",
                           fontWeight: p.id === selected ? 600 : 400 }}>
                <td>{p.title}<div className="muted">{p.code}</div></td>
                <td>{p.authority_name ?? "—"}</td>
                <td><Badge tone={p.status === "open" ? "ok" : "neutral"}>{p.status}</Badge></td>
                <td>{p.version_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <ProgrammeDetail detail={detail} />
    </div>
  );
}

function ProgrammeDetail({ detail }: { detail: FundingProgramme | undefined }) {
  if (!detail) {
    return <Card className="card__pad"><EmptyState>Seleziona un programma.</EmptyState></Card>;
  }
  const v = detail.versions?.[0] ?? detail.current_version;
  return (
    <Card className="card__pad">
      <h3>{detail.title}</h3>
      <p className="muted">{detail.description}</p>
      {v && (
        <>
          <div className="toolbar" style={{ marginTop: 8 }}>
            <Badge tone="neutral">v{v.version_no}</Badge>
            <Badge tone={v.status === "open" ? "ok" : "neutral"}>{v.status}</Badge>
            {v.aid_regime_code && <Badge tone="warn">{v.aid_regime_code}</Badge>}
          </div>
          {v.source && (
            <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
              Fonte: {v.source.title} — {v.source.reference}
              {v.source.published_on && ` (${dateIt(v.source.published_on)})`}
            </p>
          )}
          {v.windows?.map((w) => (
            <p key={w.id} style={{ fontSize: 13 }}>
              Finestra {w.kind}: {w.opens_at ? `apre ${dateTimeIt(w.opens_at)}` : "apertura n/d"}
              {w.closes_at ? ` — chiude ${dateTimeIt(w.closes_at)}` : ""}
            </p>
          ))}
          {v.requirements && v.requirements.length > 0 && (
            <>
              <h4 style={{ marginTop: 12 }}>Requisiti</h4>
              <ul style={{ fontSize: 13, paddingLeft: 18 }}>
                {v.requirements.map((r) => (
                  <li key={r.id}>{r.description}
                    <span className="muted"> [{r.rule_code}{r.mandatory ? ", obbligatorio" : ""}]</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {v.benefits && v.benefits.length > 0 && (
            <>
              <h4 style={{ marginTop: 12 }}>Benefici</h4>
              <ul style={{ fontSize: 13, paddingLeft: 18 }}>
                {v.benefits.map((b) => (
                  <li key={b.id}>{b.benefit_type}
                    {b.max_aid_intensity && ` — intensità max ${b.max_aid_intensity}`}
                    {b.max_amount && ` — max ${money(b.max_amount)}`}
                    {b.notes && <span className="muted"> {b.notes}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {v.expense_categories && v.expense_categories.length > 0 && (
            <>
              <h4 style={{ marginTop: 12 }}>Spese</h4>
              <ul style={{ fontSize: 13, paddingLeft: 18 }}>
                {v.expense_categories.map((e) => (
                  <li key={e.id}>{e.label} <Badge tone={e.status === "eligible" ? "ok" : e.status === "excluded" ? "bad" : "warn"}>{e.status}</Badge>
                    {e.conditions && <span className="muted"> — {e.conditions}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {v.document_requirements && v.document_requirements.length > 0 && (
            <>
              <h4 style={{ marginTop: 12 }}>Documenti</h4>
              <ul style={{ fontSize: 13, paddingLeft: 18 }}>
                {v.document_requirements.map((d) => (
                  <li key={d.id}>{d.label}
                    <span className="muted"> [{d.doc_type}{d.required ? ", obbligatorio" : ""}{d.stage ? `, ${d.stage}` : ""}]</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Match / opportunities
// ---------------------------------------------------------------------------

function MatchTab({ match, loading, canWrite, onAssess }: {
  match: FundingMatch | undefined; loading: boolean; canWrite: boolean;
  onAssess: (versionId: string) => void;
}) {
  if (loading) return <Spinner />;
  if (!match) return <EmptyState>Seleziona un'azienda.</EmptyState>;
  const order: [string, string][] = [
    ["eligible_on_known_data", "Compatibili sui dati noti"],
    ["potentially_eligible", "Potenzialmente compatibili"],
    ["review_required", "Da verificare professionalmente"],
    ["insufficient_data", "Dati insufficienti"],
    ["not_eligible", "Non compatibili"],
    ["unsupported", "Non valutabili"],
  ];
  return (
    <div>
      <p className="muted" style={{ fontSize: 12 }}>
        Pre-screening deterministico [{match.engine_version}] — raggruppato per
        esito, mai un punteggio. L'eligibilità resta una decisione professionale.
      </p>
      {order.map(([key, label]) => {
        const entries = match.groups[key] ?? [];
        if (!entries.length) return null;
        return (
          <Card className="card__pad" key={key} style={{ marginTop: 12 }}>
            <h4>{label} <Badge tone={RESULT_TONE[key]}>{entries.length}</Badge></h4>
            <table className="table">
              <tbody>
                {entries.map((e) => (
                  <tr key={e.version_id}>
                    <td>{e.programme_title}
                      <div className="muted">v{e.version_no} — {e.status}</div>
                    </td>
                    <td style={{ fontSize: 12 }}>
                      {e.results.map((r, i) => (
                        <div key={i}>
                          <Badge tone={r.result === "satisfied" ? "ok"
                                       : r.result === "not_satisfied" ? "bad"
                                       : r.result === "review_required" ? "warn"
                                       : "neutral"}>
                            {RULE_RESULT_LABEL[r.result] ?? r.result}
                          </Badge>{" "}{r.description}
                        </div>
                      ))}
                    </td>
                    <td>
                      {canWrite && (
                        <button className="btn btn--sm"
                                onClick={() => onAssess(e.version_id)}>
                          Valuta
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Assessments
// ---------------------------------------------------------------------------

function AssessmentsTab({ overview, loading, canWrite, onReview, onOpenPractice }: {
  overview: FundingOverview | undefined; loading: boolean; canWrite: boolean;
  onReview: (id: string, action: string) => void;
  onOpenPractice: (versionId: string, assessmentId: string) => void;
}) {
  if (loading) return <Spinner />;
  const assessments = overview?.assessments ?? [];
  if (!assessments.length) {
    return <EmptyState>Nessuna valutazione persistita. Esegui una valutazione
      dalla tab Opportunità.</EmptyState>;
  }
  return (
    <div>
      {assessments.map((a) => (
        <Card className="card__pad" key={a.id} style={{ marginTop: 12 }}>
          <div className="toolbar">
            <strong>{a.programme_version
              ? `Versione ${a.programme_version.version_no}`
              : a.version_id.slice(0, 8)}</strong>
            <Badge tone={RESULT_TONE[a.result] ?? "neutral"}>
              {RESULT_LABEL[a.result] ?? a.result}
            </Badge>
            <Badge tone="neutral">{ASSESSMENT_STATUS[a.status] ?? a.status}</Badge>
            <span className="muted">{dateTimeIt(a.assessed_at)} — {a.engine_version}</span>
          </div>
          {a.missing_data.length > 0 && (
            <p className="muted" style={{ fontSize: 12 }}>
              Dati mancanti: {a.missing_data.map((m) => m.rule_code).join(", ")}
            </p>
          )}
          {a.unsupported_rules.length > 0 && (
            <p className="muted" style={{ fontSize: 12 }}>
              Regole non supportate: {a.unsupported_rules.join(", ")}
            </p>
          )}
          {a.items && (
            <table className="table" style={{ marginTop: 8 }}>
              <tbody>
                {a.items.map((i) => (
                  <tr key={i.id}>
                    <td style={{ width: 140 }}>
                      <Badge tone={i.result === "satisfied" ? "ok"
                                   : i.result === "not_satisfied" ? "bad"
                                   : i.result === "review_required" ? "warn"
                                   : "neutral"}>
                        {RULE_RESULT_LABEL[i.result] ?? i.result}
                      </Badge>
                    </td>
                    <td>{i.description}
                      <div className="muted" style={{ fontSize: 11 }}>{i.rule_code}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {canWrite && (
            <div className="toolbar" style={{ marginTop: 8 }}>
              {a.status === "review_required" && (
                <button className="btn btn--sm"
                        onClick={() => onReview(a.id, "reviewed")}>
                  Segna revisionata
                </button>
              )}
              {a.status === "reviewed" && (
                <button className="btn btn--sm btn--primary"
                        onClick={() => onReview(a.id, "approved_for_practice")}>
                  Approva per pratica
                </button>
              )}
              {a.status === "approved_for_practice" && (
                <button className="btn btn--sm btn--primary"
                        onClick={() => onOpenPractice(a.version_id, a.id)}>
                  Apri pratica
                </button>
              )}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Practices
// ---------------------------------------------------------------------------

function PracticesTab({ overview, loading, canWrite, selected, onSelect,
                        detail, onTransition, onDocUpdate }: {
  overview: FundingOverview | undefined; loading: boolean; canWrite: boolean;
  selected: string | null; onSelect: (id: string) => void;
  detail: FundingPractice | undefined;
  onTransition: (id: string, action: string) => void;
  onDocUpdate: (practiceId: string, docId: string, status: string) => void;
}) {
  if (loading) return <Spinner />;
  const practices = overview?.practices ?? [];
  if (!practices.length) {
    return <EmptyState>Nessuna pratica aperta. Approva una valutazione per
      aprire una pratica.</EmptyState>;
  }
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
  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <Card className="card__pad">
        <table className="table">
          <thead><tr><th>Pratica</th><th>Stato</th></tr></thead>
          <tbody>
            {practices.map((p) => (
              <tr key={p.id} onClick={() => onSelect(p.id)}
                  style={{ cursor: "pointer",
                           fontWeight: p.id === selected ? 600 : 400 }}>
                <td>{p.programme_title ?? p.version_id.slice(0, 8)}
                  <div className="muted">{p.id.slice(0, 8)}</div>
                </td>
                <td><Badge tone={p.status === "approved" ? "ok"
                                 : p.status === "rejected" ? "bad" : "neutral"}>
                  {PRACTICE_STATUS[p.status] ?? p.status}
                </Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card className="card__pad">
        {!detail ? <EmptyState>Seleziona una pratica.</EmptyState> : (
          <>
            <div className="toolbar">
              <strong>{detail.programme_title ?? "Pratica"}</strong>
              <Badge tone="neutral">{PRACTICE_STATUS[detail.status] ?? detail.status}</Badge>
            </div>
            {canWrite && (NEXT[detail.status] ?? []).length > 0 && (
              <div className="toolbar" style={{ marginTop: 8 }}>
                {(NEXT[detail.status] ?? []).map((a) => (
                  <button key={a} className="btn btn--sm"
                          onClick={() => onTransition(detail.id, a)}>
                    → {PRACTICE_STATUS[a] ?? a}
                  </button>
                ))}
              </div>
            )}
            {detail.documents && detail.documents.length > 0 && (
              <>
                <h4 style={{ marginTop: 12 }}>Checklist documenti</h4>
                <table className="table">
                  <tbody>
                    {detail.documents.map((d) => (
                      <tr key={d.id}>
                        <td>{d.label}{d.required && " *"}
                          <div className="muted" style={{ fontSize: 11 }}>{d.doc_type}</div>
                        </td>
                        <td>
                          {canWrite ? (
                            <select className="input" value={d.status}
                                    style={{ padding: "2px 6px", fontSize: 12 }}
                                    onChange={(e) => onDocUpdate(detail.id, d.id, e.target.value)}>
                              {Object.entries(DOC_STATUS).map(([k, l]) => (
                                <option key={k} value={k}>{l}</option>
                              ))}
                            </select>
                          ) : (
                            <Badge tone={d.status === "validated" ? "ok"
                                         : d.status === "missing" ? "bad" : "neutral"}>
                              {DOC_STATUS[d.status] ?? d.status}
                            </Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            {detail.deadlines && detail.deadlines.length > 0 && (
              <>
                <h4 style={{ marginTop: 12 }}>Scadenze</h4>
                <ul style={{ fontSize: 13, paddingLeft: 18 }}>
                  {detail.deadlines.map((dl) => (
                    <li key={dl.id}>{dl.title} — {dateTimeIt(dl.due_at)}
                      <Badge tone={dl.status === "open" ? "warn" : "neutral"}> {dl.status}</Badge>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Position (profile + aids + de minimis)
// ---------------------------------------------------------------------------

function PositionTab({ overview, loading }: {
  overview: FundingOverview | undefined; loading: boolean;
}) {
  if (loading) return <Spinner />;
  if (!overview) return <EmptyState>Seleziona un'azienda.</EmptyState>;
  const p = overview.profile;
  const dm: DeMinimisPosition = overview.de_minimis;
  return (
    <div>
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card className="card__pad">
          <h4>Profilo agevolativo</h4>
          {!p ? <EmptyState>Profilo non dichiarato.</EmptyState> : (
            <table className="table">
              <tbody>
                <tr><td>Costituzione</td><td>{p.incorporated_on ? dateIt(p.incorporated_on) : "n/d"}</td></tr>
                <tr><td>Startup</td><td>{p.is_startup === null ? "n/d" : p.is_startup ? "sì" : "no"}</td></tr>
                <tr><td>Startup innovativa</td><td>{p.is_innovative_startup === null ? "n/d" : p.is_innovative_startup ? "sì" : "no"}</td></tr>
                <tr><td>Quota femminile</td><td>{p.female_ownership_pct ?? "n/d"}%</td></tr>
                <tr><td>Quota giovanile</td><td>{p.youth_ownership_pct ?? "n/d"}%</td></tr>
                <tr><td>Regione progetto</td><td>{p.project_region ?? "n/d"}</td></tr>
                <tr><td>Impresa unica verificata</td><td>{p.single_undertaking_known === null ? "n/d" : p.single_undertaking_known ? "sì" : "no"}</td></tr>
                <tr><td>Storico aiuti completo</td><td>{p.aid_history_complete === null ? "n/d" : p.aid_history_complete ? "sì" : "no"}</td></tr>
              </tbody>
            </table>
          )}
        </Card>
        <Card className="card__pad">
          <h4>Posizione de minimis</h4>
          <p><Badge tone={dm.status === "available" ? "ok"
                          : dm.status === "review_required" ? "warn" : "neutral"}>
            {dm.status}
          </Badge></p>
          {dm.regime && (
            <p className="muted" style={{ fontSize: 12 }}>
              {dm.regime.code} — soglia {money(dm.regime.threshold)} su
              {" "}{dm.regime.period_months} mesi [{dm.regime.formula_version}]
            </p>
          )}
          {dm.aid_total != null && (
            <p style={{ fontSize: 13 }}>
              Aiuti nella finestra: {money(dm.aid_total)} —
              capienza residua {money(dm.headroom)}
            </p>
          )}
          {(dm.reasons ?? []).map((r, i) => (
            <p key={i} className="muted" style={{ fontSize: 12 }}>⚠ {r}</p>
          ))}
          {dm.reason && <p className="muted" style={{ fontSize: 12 }}>⚠ {dm.reason}</p>}
        </Card>
      </div>
      <Card className="card__pad" style={{ marginTop: 16 }}>
        <h4>Storico aiuti dichiarati</h4>
        {!overview.aids.length ? <EmptyState>Nessun aiuto dichiarato.</EmptyState> : (
          <table className="table">
            <thead>
              <tr><th>Programma</th><th>Regime</th><th>Concesso</th>
                  <th>Importo</th><th>Stato</th></tr>
            </thead>
            <tbody>
              {overview.aids.map((a) => (
                <tr key={a.id}>
                  <td>{a.programme_label}
                    <div className="muted">{a.authority ?? ""}</div>
                  </td>
                  <td>{a.regime_code ?? "—"}</td>
                  <td>{dateIt(a.granted_on)}</td>
                  <td>{money(a.amount)}</td>
                  <td><Badge tone="neutral">{a.status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {overview.limitations.length > 0 && (
        <Card className="card__pad" style={{ marginTop: 16 }}>
          <h4>Limiti del modulo</h4>
          <ul style={{ fontSize: 12, paddingLeft: 18 }}>
            {overview.limitations.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </Card>
      )}
    </div>
  );
}
