import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, getTenantId, getToken } from "../api/client";
import type {
  CompanyListItem, DocumentItem, DocumentType, Page,
} from "../api/types";
import {
  Card, EmptyState, ErrorBanner, Spinner, StatusBadge,
} from "../components/ui";
import { dateIt } from "../lib/format";

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
        <select className="select" style={{ maxWidth: 260 }} value={companyId}
                onChange={(e) => setCompanyId(e.target.value)}>
          <option value="">Azienda…</option>
          {companies.data?.items.map((c) => (
            <option key={c.id} value={c.id}>{c.legal_name}</option>
          ))}
        </select>
        <input className="input" placeholder="Titolo documento…" value={title}
               onChange={(e) => setTitle(e.target.value)} />
        <select className="select" style={{ maxWidth: 200 }} value={typeCode}
                onChange={(e) => setTypeCode(e.target.value)}>
          {types.data?.types.map((t) => (
            <option key={t.code} value={t.code}>{t.label}</option>
          )) ?? <option value="altro">Altro</option>}
        </select>
        <input ref={fileRef} type="file" className="input"
               style={{ maxWidth: 240 }} />
        <button className="btn btn--primary"
                disabled={!companyId || upload.isPending}
                onClick={() => upload.mutate()}>
          Carica
        </button>
        <select className="select" style={{ maxWidth: 160, marginLeft: "auto" }}
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
    </>
  );
}
