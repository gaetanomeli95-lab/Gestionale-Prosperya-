import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Download, FileCheck2, FileWarning, Files, Upload } from "lucide-react";
import { api, getTenantId, getToken } from "../api/client";
import type {
  CompanyListItem, DocumentItem, DocumentRequirement, DocumentType, Page, Practice,
} from "../api/types";
import {
  Badge, Callout, EmptyState, ErrorBanner, Field, PageHeader, Section, Skeleton, Stat, statusLabel, toast,
} from "../components/ui";
import { dateIt } from "../lib/format";

const DOC_STATUS_LABEL: Record<string, string> = {
  received: "Ricevuto", validated: "Validato", rejected: "Respinto", expired: "Scaduto", archived: "Archiviato",
  missing: "Mancante", requested: "Richiesto",
};

/**
 * Document requirements for the selected company: what is still missing,
 * create a new requirement (optionally bound to a practice), and satisfy one
 * with an uploaded document. Backend keeps practice blockers in sync.
 */
function RequirementsPanel({ companyId, types, documents }: {
  companyId: string; types: DocumentType[]; documents: DocumentItem[];
}) {
  const qc = useQueryClient();
  const uid = useId();
  const [label, setLabel] = useState("");
  const [typeCode, setTypeCode] = useState("");
  const [practiceId, setPracticeId] = useState("");
  const [mandatory, setMandatory] = useState(true);
  const [requiresValidation, setRequiresValidation] = useState(true);

  const reqs = useQuery({
    queryKey: ["requirements", companyId],
    queryFn: () => api.get<{ requirements: DocumentRequirement[] }>(
      `/documents/requirements/list?company_id=${companyId}`),
  });
  const practices = useQuery({
    queryKey: ["practices", companyId, ""],
    queryFn: () => api.get<{ practices: Practice[] }>(`/practices?company_id=${companyId}`),
  });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["requirements"] });
    qc.invalidateQueries({ queryKey: ["practices"] });
    qc.invalidateQueries({ queryKey: ["dossier"] });
  };
  const create = useMutation({
    mutationFn: () => api.post(`/documents/companies/${companyId}/requirements`, {
      doc_type_code: typeCode, label: label.trim(), practice_id: practiceId || null,
      mandatory, requires_validation: requiresValidation,
    }),
    onSuccess: () => { setLabel(""); invalidate(); toast("Requisito aggiunto"); },
  });
  const fulfill = useMutation({
    mutationFn: ({ id, documentId }: { id: string; documentId: string }) =>
      api.post(`/documents/requirements/${id}/fulfill`, { document_id: documentId }),
    onSuccess: () => { invalidate(); toast("Requisito collegato al documento"); },
  });

  const open = (reqs.data?.requirements ?? []).filter((r) => r.status !== "validated");
  const done = (reqs.data?.requirements ?? []).filter((r) => r.status === "validated");

  return (
    <div className="grid-1-2 mt-4">
      <Section title="Nuovo requisito">
        <form className="stack stack--sm" aria-label="Nuovo requisito documentale"
              onSubmit={(e: FormEvent) => { e.preventDefault(); if (label.trim() && typeCode) create.mutate(); }}>
          <Field label="Tipo documento *" htmlFor={`${uid}-type`}>
            <select id={`${uid}-type`} className="select" required value={typeCode}
                    onChange={(e) => { setTypeCode(e.target.value);
                      if (!label) setLabel(types.find((t) => t.code === e.target.value)?.label ?? ""); }}>
              <option value="">Seleziona…</option>
              {types.map((t) => <option key={t.code} value={t.code}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="Descrizione *" htmlFor={`${uid}-label`}>
            <input id={`${uid}-label`} className="input" required value={label}
                   onChange={(e) => setLabel(e.target.value)} placeholder="es. Visura camerale aggiornata" />
          </Field>
          <Field label="Pratica (opzionale)" htmlFor={`${uid}-practice`} hint="Se collegato, il requisito blocca la pratica finché non è soddisfatto.">
            <select id={`${uid}-practice`} className="select" value={practiceId} onChange={(e) => setPracticeId(e.target.value)}>
              <option value="">Nessuna — requisito aziendale</option>
              {practices.data?.practices.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
            </select>
          </Field>
          <div className="cluster">
            <label className="check" htmlFor={`${uid}-mand`}>
              <input id={`${uid}-mand`} type="checkbox" checked={mandatory} onChange={(e) => setMandatory(e.target.checked)} />Obbligatorio
            </label>
            <label className="check" htmlFor={`${uid}-val`}>
              <input id={`${uid}-val`} type="checkbox" checked={requiresValidation} onChange={(e) => setRequiresValidation(e.target.checked)} />Richiede validazione
            </label>
          </div>
          <button type="submit" className="btn btn--primary w-full" disabled={create.isPending || !label.trim() || !typeCode}>
            Aggiungi requisito
          </button>
          {create.error && <ErrorBanner error={create.error} />}
        </form>
      </Section>

      <Section title={<>Requisiti documentali {open.length > 0 && <span className="tab__count tab__count--danger">{open.length} aperti</span>}</>} flush={open.length + done.length > 0}>
        {fulfill.error && <ErrorBanner error={fulfill.error} />}
        {reqs.isLoading ? <Skeleton kind="table" rows={3} /> : open.length === 0 && done.length === 0 ? (
          <EmptyState title="Nessun requisito per questa azienda" icon={<FileCheck2 size={20} strokeWidth={1.8} />}>
            Aggiungi cosa serve (visura, bilancio, DURC…) e collegalo a una pratica: Prosperya seguirà i blocchi.
          </EmptyState>
        ) : (
          <table className="table table--flush table--static">
            <thead><tr><th>Requisito</th><th>Pratica</th><th>Stato</th><th>Documento</th></tr></thead>
            <tbody>
              {[...open, ...done].map((r) => {
                const practice = practices.data?.practices.find((p) => p.id === r.practice_id);
                const candidates = documents.filter((d) => d.company_id === companyId
                  && (!r.doc_type_code || d.type_code === r.doc_type_code) && d.status !== "archived");
                const typeLabel = types.find((t) => t.code === r.doc_type_code)?.label ?? r.doc_type_code;
                return (
                  <tr key={r.id}>
                    <td>
                      <div className="table__primary">{r.label}{r.mandatory && <span className="neg" title="Obbligatorio"> *</span>}</div>
                      <div className="table__sub">{typeLabel}</div>
                    </td>
                    <td>{practice?.title ?? <span className="muted">Aziendale</span>}</td>
                    <td><Badge tone={r.status === "validated" ? "success" : r.status === "received" ? "info" : "danger"} title={r.status}>{DOC_STATUS_LABEL[r.status] ?? statusLabel(r.status)}</Badge></td>
                    <td>
                      {r.status === "validated" ? <span className="pos cluster"><CheckCircle2 size={14} /> Soddisfatto</span> : candidates.length === 0 ? (
                        <span className="muted text-xs">Carica un documento «{typeLabel}»</span>
                      ) : (
                        <select className="select select--sm" aria-label={`Soddisfa ${r.label} con documento`}
                                value="" onChange={(e) => e.target.value && fulfill.mutate({ id: r.id, documentId: e.target.value })}>
                          <option value="">Soddisfa con…</option>
                          {candidates.map((d) => <option key={d.id} value={d.id}>{d.title} · {DOC_STATUS_LABEL[d.status] ?? d.status}</option>)}
                        </select>
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
  );
}

async function downloadDocument(id: string): Promise<void> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const tenantId = getTenantId();
  if (tenantId) headers["X-Tenant-Id"] = tenantId;
  const res = await fetch(`/api/v1/documents/${id}/download`, { headers });
  if (!res.ok) throw new Error("Download non autorizzato o file non trovato.");
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const filename =
    /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? "documento";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function DocumentsPage() {
  const [companyId, setCompanyId] = useState("");
  const [status, setStatus] = useState("");
  const [typeCode, setTypeCode] = useState("altro");
  const [title, setTitle] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();

  const companies = useQuery({
    queryKey: ["companies", "all"],
    queryFn: () => api.get<Page<CompanyListItem>>("/companies?page=1&page_size=200"),
  });
  const types = useQuery({
    queryKey: ["document-types"],
    queryFn: () => api.get<{ types: DocumentType[] }>("/documents/types"),
  });

  const params = new URLSearchParams();
  if (companyId) params.set("company_id", companyId);
  if (status) params.set("status", status);
  const documents = useQuery({
    queryKey: ["documents", companyId, status],
    queryFn: () => api.get<{ documents: DocumentItem[] }>(`/documents?${params}`),
  });

  const upload = useMutation({
    mutationFn: async () => {
      const file = fileRef.current?.files?.[0];
      if (!file || !companyId) throw new Error("File e azienda richiesti.");
      const form = new FormData();
      form.append("file", file);
      if (title.trim()) form.append("title", title.trim());
      form.append("type_code", typeCode);
      const headers: Record<string, string> = {};
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const tenantId = getTenantId();
      if (tenantId) headers["X-Tenant-Id"] = tenantId;
      const res = await fetch(
        `/api/v1/documents/companies/${companyId}/upload`,
        { method: "POST", headers, body: form });
      if (!res.ok) {
        const err = (await res.json().catch(() => null))?.error ?? {};
        throw new Error(err.message ?? "Upload fallito.");
      }
      return res.json();
    },
    onSuccess: () => {
      setTitle("");
      if (fileRef.current) fileRef.current.value = "";
      qc.invalidateQueries({ queryKey: ["documents"] });
      toast("Documento caricato: versione immutabile con checksum");
    },
  });

  const validate = useMutation({
    mutationFn: ({ id, versionId, result }:
                 { id: string; versionId: string; result: string }) =>
      api.post(`/documents/${id}/versions/${versionId}/validate`, { result }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["documents"] }); qc.invalidateQueries({ queryKey: ["requirements"] }); toast("Documento validato"); },
  });

  const docs = documents.data?.documents ?? [];
  const toValidate = docs.filter((d) => d.status === "received").length;
  const expired = docs.filter((d) => d.status === "expired" || d.status === "rejected").length;
  const companyName = companies.data?.items.find((c) => c.id === companyId)?.legal_name;

  return (
    <>
      <PageHeader
        hero
        eyebrow={<>Lavoro{companyName ? ` · ${companyName}` : ""}</>}
        title="Documenti"
        question="Cosa manca, cosa scade, cosa attende validazione? Archivio canonico: versioni immutabili con checksum."
      />

      {documents.isLoading ? <Skeleton kind="stats" rows={3} /> : (
        <div className="stat-grid">
          <Stat hero icon={<FileWarning size={14} />} label="Da validare" value={toValidate} hint="documenti ricevuti in attesa di controllo" />
          <Stat icon={<FileWarning size={14} />} label="Scaduti o respinti" value={expired} tone={expired ? "danger" : undefined} hint="da sostituire con una nuova versione" />
          <Stat icon={<Files size={14} />} label="In archivio" value={docs.length} hint={companyId ? "per l'azienda selezionata" : "in tutte le aziende"} />
        </div>
      )}

      <Section title="Carica un documento">
        <div className="toolbar">
          <select className="select" aria-label="Azienda" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
            <option value="">Azienda…</option>
            {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
          </select>
          <input className="input" aria-label="Titolo documento" placeholder="Titolo documento…" value={title} onChange={(e) => setTitle(e.target.value)} />
          <select className="select" aria-label="Tipo documento" value={typeCode} onChange={(e) => setTypeCode(e.target.value)}>
            {types.data?.types.map((t) => <option key={t.code} value={t.code}>{t.label}</option>) ?? <option value="altro">Altro</option>}
          </select>
          <input ref={fileRef} type="file" aria-label="File da caricare" className="input" />
          <button className="btn btn--primary nowrap" disabled={!companyId || upload.isPending} onClick={() => upload.mutate()}>
            <Upload size={14} /> {upload.isPending ? "Caricamento…" : "Carica"}
          </button>
        </div>
        {!companyId && <Callout tone="neutral">Seleziona un'azienda per caricare documenti e gestire i requisiti documentali.</Callout>}
        {upload.error && <ErrorBanner error={upload.error} />}
      </Section>

      <Section className="mt-4" flush={docs.length > 0}
        title={<>Archivio <span className="tab__count">{docs.length}</span></>}
        actions={
          <select className="select select--sm" aria-label="Filtra per stato" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Tutti gli stati</option>
            {["received", "validated", "rejected", "expired", "archived"].map((s) => <option key={s} value={s}>{DOC_STATUS_LABEL[s]}</option>)}
          </select>
        }>
        {documents.error && <ErrorBanner error={documents.error} />}
        {documents.isLoading ? <Skeleton kind="table" rows={5} /> : docs.length === 0 ? (
          <EmptyState title="Nessun documento in questa vista" icon={<Files size={20} strokeWidth={1.8} />}>
            Carica il primo documento qui sopra oppure cambia i filtri.
          </EmptyState>
        ) : (
          <table className="table table--flush table--static">
            <thead>
              <tr><th>Documento</th><th>Azienda</th><th>Stato</th><th>Caricato</th><th className="right">Azioni</th></tr>
            </thead>
            <tbody>
              {docs.map((d) => {
                const company = companies.data?.items.find((c) => c.id === d.company_id);
                return (
                  <tr key={d.id}>
                    <td>
                      <div className="table__primary">{d.title}</div>
                      <div className="table__sub">{d.type_label ?? d.type_code ?? "—"}</div>
                    </td>
                    <td>{company ? <Link to={`/companies/${company.id}`}>{company.legal_name}</Link> : <span className="muted">—</span>}</td>
                    <td><Badge tone={d.status === "validated" ? "success" : d.status === "received" ? "info" : d.status === "archived" ? "neutral" : "danger"} title={d.status}>{DOC_STATUS_LABEL[d.status] ?? statusLabel(d.status)}</Badge></td>
                    <td className="num">{dateIt(d.created_at)}</td>
                    <td className="right nowrap">
                      <button className="btn btn--ghost btn--sm" onClick={() => void downloadDocument(d.id)}><Download size={12} /> Scarica</button>
                      {d.status === "received" && d.current_version_id && (
                        <button className="btn btn--primary btn--sm" disabled={validate.isPending}
                                onClick={() => validate.mutate({ id: d.id, versionId: d.current_version_id!, result: "validated" })}>
                          <CheckCircle2 size={12} /> Valida
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

      {companyId && (
        <RequirementsPanel companyId={companyId} types={types.data?.types ?? []} documents={docs} />
      )}
    </>
  );
}
