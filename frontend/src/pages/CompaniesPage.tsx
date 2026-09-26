import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { api, ApiError } from "../api/client";
import type { CompanyListItem, Page, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import {
  EmptyState, ErrorBanner, Modal, PageHeader, Pagination, Spinner, StatusBadge, statusLabel,
} from "../components/ui";

const schema = z.object({
  legal_name: z.string().min(1, "La ragione sociale è obbligatoria"),
  vat_number: z.string().optional(),
  tax_code: z.string().optional(),
  legal_form: z.string().optional(),
  ateco_code: z.string().optional(),
  email: z.string().email("Email non valida").optional().or(z.literal("")),
  pec: z.string().email("PEC non valida").optional().or(z.literal("")),
  phone: z.string().optional(),
  city: z.string().optional(),
  region: z.string().optional(),
  country: z.string().optional(),
  owner_id: z.string().optional(),
});
type FormData = z.infer<typeof schema>;

function CreateCompanyModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [dupWarning, setDupWarning] = useState<string | null>(null);
  const { user } = useAuth();

  const { data: users } = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<Page<User>>("/users?page_size=200"),
  });

  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  const create = useMutation({
    mutationFn: (data: FormData & { confirm_duplicate?: boolean }) =>
      api.post<{ id: string }>("/companies", {
        ...data,
        owner_id: data.owner_id || user?.id || null,
        email: data.email || null,
        pec: data.pec || null,
      }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["companies"] });
      onClose();
      navigate(`/companies/${c.id}`);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "duplicate_company") {
        const matches = (e.details.matches as { legal_name: string }[] | undefined) ?? [];
        setDupWarning(
          `Esiste già un'azienda con questo identificativo: ${matches.map((m) => m.legal_name).join(", ")}. ` +
          `Se è davvero un'azienda diversa, conferma comunque.`,
        );
      } else {
        setDupWarning(e instanceof Error ? e.message : "Errore imprevisto");
      }
    },
  });

  const onSubmit = (data: FormData) =>
    create.mutate(dupWarning ? { ...data, confirm_duplicate: true } : data);

  return (
    <Modal
      title="Nuova azienda"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn--ghost" onClick={onClose}>Annulla</button>
          <button className="btn btn--primary" onClick={handleSubmit(onSubmit)} disabled={create.isPending}>
            {create.isPending ? "Salvataggio…" : dupWarning ? "Conferma comunque" : "Crea azienda"}
          </button>
        </>
      }
    >
      {dupWarning && <div className="alert alert--warning">{dupWarning}</div>}
      <div className="form-grid">
        <div className="field span-2">
          <label className="field__label" htmlFor="ragione-sociale">Ragione sociale *</label>
          <input id="ragione-sociale" className="input" {...register("legal_name")} />
          {errors.legal_name && <div className="field__error" role="alert">{errors.legal_name.message}</div>}
        </div>
        <div className="field">
          <label className="field__label" htmlFor="partita-iva">Partita IVA</label>
          <input id="partita-iva" className="input" {...register("vat_number")} placeholder="IT…" />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="codice-fiscale">Codice fiscale</label>
          <input id="codice-fiscale" className="input" {...register("tax_code")} />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="forma-giuridica">Forma giuridica</label>
          <input id="forma-giuridica" className="input" {...register("legal_form")} placeholder="S.r.l." />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="codice-ateco">Codice ATECO</label>
          <input id="codice-ateco" className="input" {...register("ateco_code")} />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="email">Email</label>
          <input id="email" className="input" {...register("email")} />
          {errors.email && <div className="field__error" role="alert">{errors.email.message}</div>}
        </div>
        <div className="field">
          <label className="field__label" htmlFor="pec">PEC</label>
          <input id="pec" className="input" {...register("pec")} />
          {errors.pec && <div className="field__error" role="alert">{errors.pec.message}</div>}
        </div>
        <div className="field">
          <label className="field__label" htmlFor="telefono">Telefono</label>
          <input id="telefono" className="input" {...register("phone")} />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="citta">Città</label>
          <input id="citta" className="input" {...register("city")} />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="regione">Regione</label>
          <input id="regione" className="input" {...register("region")} />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="paese">Paese</label>
          <input id="paese" className="input" {...register("country")} defaultValue="Italia" />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="responsabile">Responsabile</label>
          <select id="responsabile" className="select" {...register("owner_id")}>
            <option value="">— assegna a me —</option>
            {users?.items.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
          </select>
        </div>
      </div>
    </Modal>
  );
}

export default function CompaniesPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  const { data, isLoading, error } = useQuery({
    queryKey: ["companies", q, status, page],
    queryFn: () =>
      api.get<Page<CompanyListItem>>(
        `/companies?page=${page}&page_size=25${q ? `&q=${encodeURIComponent(q)}` : ""}${status ? `&status=${status}` : ""}`,
      ),
  });

  return (
    <>
      <PageHeader
        eyebrow="Clienti"
        title="Aziende"
        question={data ? <><span>{`${data.total} anagrafiche`}</span> · apri il dossier per vedere cosa sta succedendo con ogni cliente.</> : "…"}
        actions={<button className="btn btn--primary" onClick={() => setCreating(true)}>+ Nuova azienda</button>}
      />

      <div className="toolbar">
        <input className="input" aria-label="Cerca per nome, P.IVA, città…" placeholder="Cerca per nome, P.IVA, città…"
               value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <select className="select" style={{ maxWidth: 180 }} value={status}
                onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">Tutti gli stati</option>
          <option value="prospect">Prospect</option>
          <option value="customer">Cliente</option>
          <option value="former">Ex cliente</option>
        </select>
      </div>

      {error && <ErrorBanner error={error} />}
      {isLoading ? (
        <Spinner />
      ) : !data || data.items.length === 0 ? (
        <EmptyState>Nessuna azienda trovata.</EmptyState>
      ) : (
        <div className="card card__pad" style={{ paddingTop: 4, paddingBottom: 4 }}>
          <table className="table table--flush">
            <thead>
              <tr>
                <th>Ragione sociale</th><th>P.IVA</th><th>Luogo</th>
                <th>Stato</th><th>Dimensione</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id} onClick={() => navigate(`/companies/${c.id}`)}>
                  <td><span className="table__primary">{c.legal_name}</span></td>
                  <td className="num">{c.vat_number ?? "—"}</td>
                  <td>{[c.city, c.region].filter(Boolean).join(", ") || "—"}</td>
                  <td><StatusBadge status={c.status} /></td>
                  <td className="muted">{c.size_band && c.size_band !== "unknown" ? statusLabel(c.size_band === "medium" ? "medium_size" : c.size_band) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
      {creating && <CreateCompanyModal onClose={() => setCreating(false)} />}
    </>
  );
}
