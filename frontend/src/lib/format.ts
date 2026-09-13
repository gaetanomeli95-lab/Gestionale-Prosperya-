export const eur = (v: number | null | undefined) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(v);

export const dateIt = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("it-IT") : "—";

export const dateTimeIt = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" })
    : "—";
