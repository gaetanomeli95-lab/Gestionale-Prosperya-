import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, getTenantId, getToken } from "../api/client";
import type {
  CompanyListItem, DocumentItem, DocumentRequirement, DocumentType, Page, Practice,
} from "../api/types";
import {
  Card, EmptyState, ErrorBanner, Spinner, StatusBadge,
} from "../components/ui";
import { dateIt } from "../lib/format";

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
    onSuccess: () => { setLabel(""); invalidate(); },
  });
  const fulfill = useMutation({
    mutationFn: ({ id, documentId }: { id: string; documentId: string }) =>
      api.post(`/documents/requirements/${id}/fulfill`, { document_id: documentId }),
    onSuccess: invalidate,
  });

  const open = (reqs.data?.requirements ?? []).filter((r) => r.status !== "validated");
  const done = (reqs.data?.requirements ?? []).filter((r) => r.status === "validated");

  return (
    <Card className="card__pad" style={{ marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>Requisiti documentali</h3>
      <form className="form-grid" aria-label="Nuovo requisito documentale"
            onSubmit={(e: FormEvent) => { e.preventDefault(); if (label.trim() && typeCode) create.mutate(); }}>
        <div className="field">
          <label className="field__label" htmlFor={`${uid}-type`}>Tipo documento *</label>
          <select id={`${uid}-type`} className="select" required value={typeCode}
                  onChange={(e) => { setTypeCode(e.target.value);
                    if (!label) setLabel(types.find((t) => t.code === e.target.value)?.label ?? ""); }}>
            <option value="">Seleziona…</option>
            {types.map((t) => <option key={t.code} value={t.code}>{t.label}</option>)}
          </select>
        </div>
        <div className="field">
          <label className="field__label" htmlFor={`${uid}-label`}>Descrizione *</label>
          <input id={`${uid}-label`} className="input" required value={label}
                 onChange={(e) => setLabel(e.target.value)} placeholder="es. Visura camerale aggiornata" />
        </div>
        <div className="field">
          <label className="field__label" htmlFor={`${uid}-practice`}>Pratica (opzionale)</label>
          <select id={`${uid}-practice`} className="select" value={practiceId}
                  onChange={(e) => setPracticeId(e.target.value)}>
            <option value="">Nessuna — requisito aziendale</option>
            {practices.data?.practices.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
        </div>
        <div className="field" style={{ display: "flex", gap: 16, alignItems: "end" }}>
          <label className="field__label" htmlFor={`${uid}-mand`} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input id={`${uid}-mand`} type="checkbox" checked={mandatory} onChange={(e) => setMandatory(e.target.checked)} />
            Obbligatorio
          </label>
          <label className="field__label" htmlFor={`${uid}-val`} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input id={`${uid}-val`} type="checkbox" checked={requiresValidation} onChange={(e) => setRequiresValidation(e.target.checked)} />
            Richiede validazione
          </label>
          <button type="submit" className="btn btn--primary" disabled={create.isPending || !label.trim() || !typeCode}>
            Aggiungi requisito
          </button>
        </div>
      </form>
      {create.error && <ErrorBanner error={create.error} />}
      {fulfill.error && <ErrorBanner error={fulfill.error} />}

      {reqs.isLoading ? <Spinner /> : open.length === 0 && done.length === 0 ? (
        <EmptyState>Nessun requisito documentale per questa azienda.</EmptyState>
      ) : (
        <table className="table" style={{ marginTop: 12 }}>
          <thead><tr><th>Requisito</th><th>Pratica</th><th>Stato</th><th>Documento</th></tr></thead>
          <tbody>
            {[...open, ...done].map((r) => {
              const practice = practices.data?.practices.find((p) => p.id === r.practice_id);
              const candidates = documents.filter((d) => d.company_id === companyId
                && (!r.doc_type_code || d.type_code === r.doc_type_code) && d.status !== "archived");
              return (
                <tr key={r.id}>
                  <td>{r.label}{r.mandatory && " *"}<div className="muted" style={{ fontSize: 11 }}>{r.doc_type_code}</div></td>
                  <td>{practice?.title ?? "—"}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td>
                    {r.status === "validated" ? "✓" : candidates.length === 0 ? (
                      <span className="muted">carica un documento di tipo {r.doc_type_code}</span>
                    ) : (
                      <select className="select" aria-label={`Soddisfa ${r.label} con documento`}
                              value="" onChange={(e) => e.target.value && fulfill.mutate({ id: r.id, documentId: e.target.value })}>
                        <option value="">Soddisfa con…</option>
                        {candidates.map((d) => <option key={d.id} value={d.id}>{d.title} ({d.status})</option>)}
                      </select>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
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
    },
  });

  const validate = useMutation({
    mutationFn: ({ id, versionId, result }:
                 { id: string; versionId: string; result: string }) =>
      api.post(`/documents/${id}/versions/${versionId}/validate`, { result }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Documenti</h1>
          <div className="page-head__meta">
            Archivio canonico — versioni immutabili con checksum
          </div>
        </div>
      </div>

      <div className="toolbar">
        <select className="select" aria-label="Azienda" style={{ maxWidth: 260 }} value={companyId}
                onChange={(e) => setCompanyId(e.target.value)}>
          <option value="">Azienda…</option>
          {companies.data?.items.map((c) => (
            <option key={c.id} value={c.id}>{c.legal_name}</option>
          ))}
        </select>
        <input className="input" aria-label="Titolo documento" placeholder="Titolo documento…" value={title}
               onChange={(e) => setTitle(e.target.value)} />
        <select className="select" aria-label="Tipo documento" style={{ maxWidth: 200 }} value={typeCode}
                onChange={(e) => setTypeCode(e.target.value)}>
          {types.data?.types.map((t) => (
            <option key={t.code} value={t.code}>{t.label}</option>
          )) ?? <option value="altro">Altro</option>}
        </select>
        <input ref={fileRef} type="file" aria-label="File da caricare" className="input"
               style={{ maxWidth: 240 }} />
        <button className="btn btn--primary"
                disabled={!companyId || upload.isPending}
                onClick={() => upload.mutate()}>
          Carica
        </button>
        <select className="select" aria-label="Filtra per stato" style={{ maxWidth: 160, marginLeft: "auto" }}
                value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Tutti gli stati</option>
          {["received", "validated", "rejected", "expired", "archived"]
            .map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {upload.error && <ErrorBanner error={upload.error} />}
      {documents.error && <ErrorBanner error={documents.error} />}
      {documents.isLoading ? <Spinner /> :
       !documents.data || documents.data.documents.length === 0 ? (
        <EmptyState>Nessun documento in questa vista.</EmptyState>
      ) : (
        <Card>
          <table className="table">
            <thead>
              <tr>
                <th>Documento</th><th>Azienda</th><th>Tipo</th>
                <th>Stato</th><th>Scadenza</th><th>Caricato</th><th></th>
              </tr>
            </thead>
            <tbody>
              {documents.data.documents.map((d) => {
                const company = companies.data?.items.find(
                  (c) => c.id === d.company_id);
                return (
                  <tr key={d.id}>
                    <td>{d.title}</td>
                    <td>
                      {company ? (
                        <Link to={`/companies/${company.id}`}>
                          {company.legal_name}
                        </Link>
                      ) : "—"}
                    </td>
                    <td className="muted">{d.type_label ?? d.type_code ?? "—"}</td>
                    <td><StatusBadge status={d.status} /></td>
                    <td className="mono">—</td>
                    <td className="mono">{dateIt(d.created_at)}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button className="btn btn--ghost btn--sm"
                              onClick={() => void downloadDocument(d.id)}>
                        Scarica
                      </button>
                      {d.status === "received" && d.current_version_id && (
                        <button className="btn btn--ghost btn--sm"
                                onClick={() => validate.mutate({
                                  id: d.id,
                                  versionId: d.current_version_id!,
                                  result: "validated",
                                })}>
                          Valida
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
      {companyId && (
        <RequirementsPanel companyId={companyId} types={types.data?.types ?? []}
                           documents={documents.data?.documents ?? []} />
      )}
    </>
  );
}
