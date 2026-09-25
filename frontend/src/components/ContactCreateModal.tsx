import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, type FormEvent } from "react";
import { api } from "../api/client";
import type { Contact } from "../api/types";
import { ErrorBanner, Modal } from "./ui";

interface Props {
  onClose: () => void;
  /** When set, the contact is created already linked to this company. */
  companyId?: string;
  onCreated?: (contact: Contact) => void;
}

/**
 * Single contact-creation form, reused by the global Contacts page and the
 * company detail tab. One contact domain, one API (`POST /contacts`).
 */
export function ContactCreateModal({ onClose, companyId, onCreated }: Props) {
  const qc = useQueryClient();
  const uid = useId();
  const id = (k: string) => `${uid}-${k}`;

  const create = useMutation({
    mutationFn: (d: Record<string, unknown>) => api.post<Contact>("/contacts", d),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["contacts"] });
      onCreated?.(c);
      onClose();
    },
  });

  return (
    <Modal title="Nuovo contatto" onClose={onClose} footer={null}>
      <form
        aria-label="Nuovo contatto"
        onSubmit={(e: FormEvent<HTMLFormElement>) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          const v = (k: string) => String(f.get(k) ?? "").trim() || undefined;
          create.mutate({
            first_name: v("first_name") ?? "",
            last_name: v("last_name") ?? "",
            email: v("email"),
            phone: v("phone"),
            role_title: v("role_title"),
            ...(companyId
              ? { company_id: companyId, relationship_role: v("relationship_role"),
                  is_primary: f.get("is_primary") === "on" }
              : {}),
          });
        }}
      >
        {create.error && <ErrorBanner error={create.error} />}
        <div className="form-grid">
          <div className="field"><label className="field__label" htmlFor={id("fn")}>Nome *</label>
            <input id={id("fn")} className="input" name="first_name" required autoFocus /></div>
          <div className="field"><label className="field__label" htmlFor={id("ln")}>Cognome *</label>
            <input id={id("ln")} className="input" name="last_name" required /></div>
          <div className="field"><label className="field__label" htmlFor={id("em")}>Email</label>
            <input id={id("em")} className="input" name="email" type="email" autoComplete="off" /></div>
          <div className="field"><label className="field__label" htmlFor={id("ph")}>Telefono</label>
            <input id={id("ph")} className="input" name="phone" type="tel" /></div>
          <div className={companyId ? "field" : "field span-2"}>
            <label className="field__label" htmlFor={id("rt")}>Ruolo</label>
            <input id={id("rt")} className="input" name="role_title" placeholder="es. Amministratore" /></div>
          {companyId && (
            <>
              <div className="field"><label className="field__label" htmlFor={id("rr")}>Ruolo nell'azienda</label>
                <input id={id("rr")} className="input" name="relationship_role" placeholder="es. Decision maker" /></div>
              <div className="field span-2">
                <label className="field__label" htmlFor={id("pr")} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input id={id("pr")} type="checkbox" name="is_primary" /> Referente principale
                </label>
              </div>
            </>
          )}
        </div>
        <div className="modal__foot" style={{ margin: "16px -20px -16px", padding: "12px 0 0" }}>
          <button type="button" className="btn btn--ghost" onClick={onClose}>Annulla</button>
          <button type="submit" className="btn btn--primary" disabled={create.isPending}>
            {create.isPending ? "Salvataggio…" : "Crea"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
