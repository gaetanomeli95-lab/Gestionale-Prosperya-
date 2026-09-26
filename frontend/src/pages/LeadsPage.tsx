import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRightLeft, Sparkles, Zap } from "lucide-react";
import { api } from "../api/client";
import type { Lead, Page, ServiceLine } from "../api/types";
import {
  EmptyState, ErrorBanner, Field, Modal, NA, PageHeader, Pagination, Section, Segmented, Skeleton,
  Stat, StatusBadge, toast,
} from "../components/ui";
import { dateIt, eur } from "../lib/format";

type LeadFilter = "" | "new" | "contacted" | "qualified" | "unqualified" | "converted";

const FILTERS: { value: LeadFilter; label: string }[] = [
  { value: "", label: "Tutti" },
  { value: "new", label: "Nuovi" },
  { value: "contacted", label: "Contattati" },
  { value: "qualified", label: "Qualificati" },
  { value: "unqualified", label: "Non qualificati" },
  { value: "converted", label: "Convertiti" },
];

const SOURCE_LABEL: Record<string, string> = {
  website: "Sito web", referral: "Passaparola", social: "Social", event: "Evento",
  partner: "Partner", outreach: "Attività commerciale", other: "Altro",
};

export default function LeadsPage() {
  const [status, setStatus] = useState<LeadFilter>("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const uid = useId();
  const fid = (k: string) => `${uid}-${k}`;

  const { data, isLoading, error } = useQuery({
    queryKey: ["leads", status, page],
    queryFn: () =>
      api.get<Page<Lead>>(`/leads?page=${page}&page_size=25${status ? `&status=${status}` : ""}`),
  });
  const { data: serviceLines } = useQuery({
    queryKey: ["service-lines"],
    queryFn: () => api.get<ServiceLine[]>("/service-lines"),
  });

  const create = useMutation({
    mutationFn: (d: Record<string, unknown>) => api.post("/leads", d),
    onSuccess: () => { setCreating(false); qc.invalidateQueries({ queryKey: ["leads"] }); toast("Lead creato"); },
  });
  const convert = useMutation({
    mutationFn: (id: string) =>
      api.post<{ company_id: string }>(`/leads/${id}/convert`, { create_opportunity: true }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["companies"] });
      toast("Lead convertito: azienda e opportunità create");
      navigate(`/companies/${r.company_id}`);
    },
  });

  const items = data?.items ?? [];
  const toWork = items.filter((l) => l.status === "new" || l.status === "contacted").length;
  const readyToConvert = items.filter((l) => l.status === "qualified").length;
  const potential = items
    .filter((l) => l.status !== "converted" && l.status !== "unqualified")
    .reduce((s, l) => s + (l.estimated_value_eur ?? 0), 0);

  return (
    <>
      <PageHeader
        eyebrow="CRM"
        title="Lead"
        question="Quali contatti in ingresso vanno qualificati o convertiti adesso?"
        actions={
          <button className="btn btn--primary" onClick={() => setCreating(true)}>
            <Zap size={15} /> Nuovo lead
          </button>
        }
      />

      {isLoading && !data ? <Skeleton kind="stats" rows={3} /> : data && (
        <div className="stat-grid">
          <Stat hero icon={<Zap size={14} />} label="Lead in vista"
                value={<span className="num">{data.total}</span>}
                hint={status ? `filtro: ${FILTERS.find((f) => f.value === status)?.label}` : "tutti gli stati"} />
          <Stat icon={<Sparkles size={14} />} label="Da lavorare"
                value={<span className="num">{toWork}</span>}
                hint="nuovi o contattati in questa pagina"
                tone={toWork > 0 ? "warn" : undefined} />
          <Stat icon={<ArrowRightLeft size={14} />} label="Pronti a convertire"
                value={<span className="num">{readyToConvert}</span>}
                hint={<>qualificati · potenziale <span className="money">{eur(potential)}</span></>}
                tone={readyToConvert > 0 ? "success" : undefined} />
        </div>
      )}

      {convert.error && <ErrorBanner error={convert.error} />}

      <Section
        title="Coda lead"
        flush
        actions={
          <Segmented
            ariaLabel="Filtra per stato"
            options={FILTERS}
            value={status}
            onChange={(v) => { setStatus(v); setPage(1); }}
          />
        }
        footer={data && data.total > 0 ? "Convertire un lead crea l'azienda e apre la prima opportunità in pipeline." : undefined}
      >
        {error && <div className="card__pad"><ErrorBanner error={error} /></div>}
        {isLoading ? (
          <div className="card__pad"><Skeleton kind="table" rows={6} /></div>
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title={status ? "Nessun lead in questo stato" : "Nessun lead in ingresso"}
            action={
              status
                ? <button className="btn btn--ghost btn--sm" onClick={() => setStatus("")}>Mostra tutti</button>
                : <button className="btn btn--primary btn--sm" onClick={() => setCreating(true)}><Zap size={14} /> Nuovo lead</button>
            }
          >
            {status
              ? "Cambia filtro oppure registra un nuovo contatto in ingresso."
              : "Registra qui ogni richiesta che arriva dal sito, da un partner o da un evento: da qui nasce la pipeline."}
          </EmptyState>
        ) : (
          <table className="table table--flush table--static">
            <thead>
              <tr>
                <th>Azienda</th>
                <th>Persona</th>
                <th>Interesse</th>
                <th className="th--num">Valore stimato</th>
                <th>Stato</th>
                <th className="right">Prossimo passo</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((l) => (
                <tr key={l.id}>
                  <td>
                    <div className="table__primary">{l.company_name}</div>
                    <div className="table__sub">{SOURCE_LABEL[l.source] ?? l.source} · {dateIt(l.created_at)}</div>
                  </td>
                  <td>
                    {l.contact_name ? <div className="table__primary">{l.contact_name}</div> : <NA title="Persona non indicata" />}
                    <div className="table__sub">
                      {l.email ? <a href={`mailto:${l.email}`}>{l.email}</a> : l.phone ? <a href={`tel:${l.phone}`}>{l.phone}</a> : "Nessun recapito"}
                    </div>
                  </td>
                  <td>{l.interest ?? <NA title="Interesse non indicato" />}</td>
                  <td className="td--num money">
                    {l.estimated_value_eur == null ? <NA title="Valore non stimato" /> : eur(l.estimated_value_eur)}
                  </td>
                  <td><StatusBadge status={l.status} /></td>
                  <td className="right">
                    {l.status === "converted" ? (
                      l.converted_company_id ? (
                        <button className="btn btn--ghost btn--sm" onClick={() => navigate(`/companies/${l.converted_company_id}`)}>
                          Apri azienda
                        </button>
                      ) : <span className="muted text-xs">Convertito</span>
                    ) : (
                      <button className="btn btn--accent btn--sm"
                              disabled={convert.isPending}
                              onClick={() => convert.mutate(l.id)}>
                        <ArrowRightLeft size={13} /> Converti
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      {data && <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}

      {creating && (
        <Modal
          title="Nuovo lead"
          subtitle="Un contatto in ingresso da qualificare. Serve solo il nome dell'azienda; il resto si completa dopo."
          onClose={() => setCreating(false)}
          footer={
            <>
              <button type="button" className="btn btn--ghost" onClick={() => setCreating(false)}>Annulla</button>
              <button type="submit" form={fid("form")} className="btn btn--primary" disabled={create.isPending}>
                {create.isPending ? "Salvataggio…" : "Crea lead"}
              </button>
            </>
          }
        >
          <form id={fid("form")} onSubmit={(e: FormEvent<HTMLFormElement>) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            create.mutate({
              company_name: String(f.get("company_name") ?? ""),
              contact_name: String(f.get("contact_name") ?? "") || undefined,
              email: String(f.get("email") ?? "") || undefined,
              phone: String(f.get("phone") ?? "") || undefined,
              source: String(f.get("source") ?? "other"),
              interest: String(f.get("interest") ?? "") || undefined,
              service_line_id: String(f.get("service_line_id") ?? "") || undefined,
            });
          }}>
            {create.error && <ErrorBanner error={create.error} />}
            <div className="form-section">
              <div className="form-section__title">Chi</div>
              <div className="form-grid">
                <Field label="Azienda *" htmlFor="azienda" span2>
                  <input id="azienda" className="input" name="company_name" required autoFocus />
                </Field>
                <Field label="Persona di riferimento" htmlFor="persona-di-riferimento">
                  <input id="persona-di-riferimento" className="input" name="contact_name" />
                </Field>
                <Field label="Email" htmlFor="email">
                  <input id="email" className="input" name="email" type="email" />
                </Field>
                <Field label="Telefono" htmlFor="telefono">
                  <input id="telefono" className="input" name="phone" />
                </Field>
                <Field label="Fonte" htmlFor="fonte" hint="Da dove è arrivata la richiesta">
                  <select id="fonte" className="select" name="source">
                    <option value="website">Sito web</option>
                    <option value="referral">Passaparola</option>
                    <option value="social">Social</option>
                    <option value="event">Evento</option>
                    <option value="partner">Partner</option>
                    <option value="outreach">Attività commerciale</option>
                    <option value="other">Altro</option>
                  </select>
                </Field>
              </div>
            </div>
            <div className="form-section">
              <div className="form-section__title">Cosa cerca</div>
              <div className="form-grid">
                <Field label="Interesse / servizio" htmlFor="interesse-servizio" span2>
                  <input id="interesse-servizio" className="input" name="interest" placeholder="Es. finanza agevolata, startup…" />
                </Field>
                <Field label="Linea di servizio" htmlFor="linea-di-servizio" span2>
                  <select id="linea-di-servizio" className="select" name="service_line_id">
                    <option value="">—</option>
                    {serviceLines?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </Field>
              </div>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
