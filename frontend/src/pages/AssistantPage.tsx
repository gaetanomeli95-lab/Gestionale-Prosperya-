import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowRight, Calculator, Lightbulb, ScrollText, Send, ShieldAlert,
  ShieldCheck, Sparkles,
} from "lucide-react";
import { api } from "../api/client";
import type { AnswerItemType, ChatResponse, CompanyListItem, Page } from "../api/types";
import { Badge, ErrorBanner, Spinner } from "../components/ui";

const MONTHS = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];
const PROMPTS = [
  "Riepilogo di ricavi e risultato gestionale",
  "Quali costi sono oltre il budget?",
  "Qual è la situazione di cassa?",
  "Rischio tensione di cassa nei prossimi 60 giorni?",
  "Quali crediti sono scaduti?",
  "Quanti movimenti bancari non riconciliati abbiamo?",
  "Simula ricavi aumentano del 10% a costi invariati",
];
const ITEM: Record<AnswerItemType, { label: string; tone: string; icon: typeof Sparkles }> = {
  FACT: { label: "Fatto", tone: "primary", icon: ScrollText },
  CALCULATION: { label: "Calcolo", tone: "accent", icon: Calculator },
  ASSUMPTION: { label: "Ipotesi", tone: "warning", icon: Lightbulb },
  SUGGESTION: { label: "Suggerimento", tone: "info", icon: Sparkles },
  WARNING: { label: "Allerta", tone: "warning", icon: AlertTriangle },
  ACTION_REQUIRED: { label: "Azione richiesta", tone: "danger", icon: ShieldAlert },
};

interface Turn { id: string; question: string; answer: ChatResponse; year: number; month: number }

export default function AssistantPage() {
  const [companyId, setCompanyId] = useState("");
  const [year, setYear] = useState(2026);
  const [month, setMonth] = useState(6);
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  const companies = useQuery({
    queryKey: ["companies", "all"],
    queryFn: () => api.get<Page<CompanyListItem>>("/companies?page=1&page_size=200"),
  });
  const cid = companyId || companies.data?.items[0]?.id || "";
  const company = companies.data?.items.find((c) => c.id === cid);

  const ask = useMutation({
    mutationFn: (q: string) =>
      api.post<ChatResponse>(`/assistant/companies/${cid}/chat`, { message: q, year, through_month: month }),
    onSuccess: (answer, q) => {
      setTurns((t) => [...t, { id: crypto.randomUUID(), question: q, answer, year, month }]);
      setMessage("");
    },
  });

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns.length]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = message.trim();
    if (q && !ask.isPending) ask.mutate(q);
  };

  if (companies.isLoading) return <Spinner />;
  if (companies.error) return <ErrorBanner error={companies.error} />;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>AI CFO</h1>
          <div className="page-head__meta">Fatti, calcoli, ipotesi e suggerimenti — sempre distinti e tracciati.</div>
        </div>
        <div className="toolbar" style={{ margin: 0 }}>
          <select className="select" value={cid} onChange={(e) => { setCompanyId(e.target.value); setTurns([]); }} style={{ maxWidth: 260 }}>
            {companies.data?.items.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
          </select>
          <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 90 }}>
            {[2024, 2025, 2026, 2027].map((y) => <option key={y}>{y}</option>)}
          </select>
          <select className="select" value={month} onChange={(e) => setMonth(Number(e.target.value))} style={{ width: 120 }}>
            {MONTHS.slice(1).map((m, i) => <option key={m} value={i + 1}>Gen–{m}</option>)}
          </select>
        </div>
      </div>

      <div className="ai-banner">
        <ShieldCheck size={18} />
        <div>
          <strong>Modalità deterministica — nessun modello esterno</strong>
          <div>Risposte generate da regole e strumenti autorizzati sui soli dati dell'azienda selezionata. Nessun dato lascia il server.</div>
        </div>
        <Badge tone="accent">DEMO</Badge>
      </div>

      <div className="chat">
        <div className="chat__head">
          <span className="chat__avatar"><Sparkles size={16} /></span>
          <div>
            <strong>Prosperya AI CFO</strong>
            <div className="muted" style={{ fontSize: "0.75rem" }}>{company?.legal_name} · Gen–{MONTHS[month]} {year}</div>
          </div>
        </div>

        <div className="chat__body">
          {turns.length === 0 && (
            <div className="chat__welcome">
              <div className="chat__welcome-eyebrow">Meno rumore, più comprensione</div>
              <h2>Partiamo dai tuoi numeri.</h2>
              <p className="muted">Analizziamo quello che i dati possono dirci — e rendiamo esplicito quello che ancora non sappiamo.</p>
              <div className="prompt-grid">
                {PROMPTS.map((p) => (
                  <button key={p} className="prompt" disabled={ask.isPending || !cid} onClick={() => ask.mutate(p)}>
                    <span>{p}</span><ArrowRight size={14} />
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t) => (
            <article className="turn" key={t.id}>
              <div className="turn__q">
                <div className="turn__q-meta">La tua domanda · {t.year} / Gen–{MONTHS[t.month]}</div>
                {t.question}
              </div>
              <div className="turn__a">
                <div className="turn__a-head">
                  <Sparkles size={14} /> <strong>AI CFO</strong>
                  <span className="muted mono" style={{ fontSize: "0.7rem" }}>{t.answer.provider} · {t.answer.mode}</span>
                </div>
                <ul className="answer-items">
                  {t.answer.items.map((it, i) => {
                    const meta = ITEM[it.type];
                    return (
                      <li key={i} className={`answer-item answer-item--${it.type.toLowerCase()}`}>
                        <Badge tone={meta.tone}>{meta.label}</Badge>
                        <span>{it.text}</span>
                      </li>
                    );
                  })}
                </ul>
                {t.answer.tools_used.length > 0 && (
                  <div className="turn__tools">
                    Strumenti: {t.answer.tools_used.map((x) => <code key={x}>{x}</code>)}
                    {t.answer.evidence.source_ids && <> · {t.answer.evidence.source_ids.length} fonti</>}
                  </div>
                )}
                <details className="turn__limits">
                  <summary>Limiti e provenienza ({t.answer.limitations.length})</summary>
                  <ul>{t.answer.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
                </details>
              </div>
            </article>
          ))}
          {ask.error && <ErrorBanner error={ask.error} />}
          <div ref={endRef} />
        </div>

        <form className="chat__input" onSubmit={submit}>
          <input
            className="input"
            placeholder="Chiedi ricavi, costi, trend, budget, qualità dei dati o uno scenario…"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={!cid}
          />
          <button className="btn btn--primary" disabled={ask.isPending || !message.trim() || !cid}>
            <Send size={14} /> {ask.isPending ? "…" : "Chiedi"}
          </button>
        </form>
      </div>
    </>
  );
}
