import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, type FormEvent } from "react";
import { api } from "../api/client";
import type { Contact } from "../api/types";
import { ErrorBanner, Field, Modal, toast } from "./ui";

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
  const formId = id("form");

  const create = useMutation({
    mutationFn: (d: Record<string, unknown>) => api.post<Contact>("/contacts", d),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["contacts"] });
      toast(`Contatto ${c.first_name} ${c.last_name} creato`);
      onCreated?.(c);
      onClose();
    },
  });

  return (
    <Modal
      title="Nuovo contatto"
      subtitle={companyId
        ? "La persona viene collegata subito a questa azienda: potrai inviarle richieste documentali e comunicazioni."
        : "Una persona reale, con recapiti verificabili. Potrai collegarla a un'azienda in un secondo momento."}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose}>Annulla</button>
          <button type="submit" form={formId} className="btn btn--primary" disabled={create.isPending}>
            {create.isPending ? "Salvataggio…" : "Crea"}
          </button>
        </>
      }
    >
      <form
        id={formId}
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

        <div className="form-section">
          <div className="form-section__title">Persona</div>
          <div className="form-grid">
            <Field label="Nome *" htmlFor={id("fn")}>
              <input id={id("fn")} className="input" name="first_name" required autoFocus />
            </Field>
            <Field label="Cognome *" htmlFor={id("ln")}>
              <input id={id("ln")} className="input" name="last_name" required />
            </Field>
            <Field label="Email" htmlFor={id("em")} hint="Usata per le richieste al cliente">
              <input id={id("em")} className="input" name="email" type="email" autoComplete="off" />
            </Field>
            <Field label="Telefono" htmlFor={id("ph")}>
              <input id={id("ph")} className="input" name="phone" type="tel" />
            </Field>
            <Field label="Ruolo" htmlFor={id("rt")} span2={!companyId} hint="Qualifica della persona, es. Amministratore">
              <input id={id("rt")} className="input" name="role_title" placeholder="es. Amministratore" />
            </Field>
          </div>
        </div>

        {companyId && (
          <div className="form-section">
            <div className="form-section__title">Rapporto con l'azienda</div>
            <div className="form-grid">
              <Field label="Ruolo nell'azienda" htmlFor={id("rr")} hint="Cosa decide o firma per questa azienda">
                <input id={id("rr")} className="input" name="relationship_role" placeholder="es. Decision maker" />
              </Field>
              <div className="field">
                <span className="field__label">Referente</span>
                <label className="check" htmlFor={id("pr")}>
                  <input id={id("pr")} type="checkbox" name="is_primary" /> Referente principale
                </label>
                <div className="field__hint">Riceve per primo richieste e comunicazioni.</div>
              </div>
            </div>
          </div>
        )}
      </form>
    </Modal>
  );
}
