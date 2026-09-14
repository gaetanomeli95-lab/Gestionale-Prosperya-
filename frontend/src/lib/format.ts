export const eur = (v: number | null | undefined) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(v);

/** Format a backend decimal string (e.g. "12345.67") for display only.
 *  Never use the parsed number for financial calculations. */
export const money = (v: string | null | undefined) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(Number(v));

export const dateIt = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("it-IT") : "—";

export const dateTimeIt = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" })
    : "—";
