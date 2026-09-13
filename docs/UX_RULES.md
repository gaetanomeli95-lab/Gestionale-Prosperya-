# UX_RULES — PROSPERYA CRM

Interaction and presentation rules for the CRM. These are requirements, not suggestions — PRs that violate them should not merge.

## 1. Density-first

This is a professional tool used all day, not a marketing page.

- Default text 14px, dense tables 13px; default table row 40px, dense variant 32px.
- Prefer one dense, well-organized screen over three sparse ones. Pagination beat "breathing room".
- Max one primary (petrol) action per view. Secondary actions are quiet (secondary/ghost buttons, overflow menus).
- White space comes from structure (sections, alignment), not padding inflation.

## 2. Record page anatomy

Every entity page (company, contact, lead, opportunity, funding application, practice) follows the same skeleton:

```
┌─ HEADER ────────────────────────────────────────────────┐
│ Identity (Playfair title) + status chip + entity type   │
│ Owner avatar/name · key dates · primary action(s)       │
│ Alert strip — active warnings/deadlines (always shown)  │
├─ TAB BAR ─────────── or ── SECTION STACK ───────────────┤
│ Overview · Timeline · Documents · Tasks · Related       │
│ Sections: identity → business data → relations → admin  │
└──────────────────────────────────────────────────────────┘
```

- **Header** carries identity + status + owner + alerts; never more than two rows tall.
- **Alert strip** surfaces warnings-engine flags and approaching deadlines — it renders even when the rest of the page is in view mode.
- **Timeline** merges `notes` + `activity_events` in reverse-chronological order.
- Sections are collapsible; collapse state persists per user.

## 3. The golden rule: never make the user retype known data

- Converting a lead → company + contact + opportunity pre-fills every captured field.
- Creating an opportunity from a company page pre-fills company, primary contact, service line, owner.
- Creating a task/note/document from a record pre-binds `entity_type`/`entity_id` invisibly.
- If the system knows it, the field is pre-filled; if the user must confirm, it's a pre-selected suggestion, not a blank input.
- Autocomplete on all entity references; create-on-the-fly allowed only where the entity is genuinely new.

## 4. Forms

- One column by default; two columns only for genuinely parallel short fields (first/last name).
- Required fields marked `*`; optional fields are the exception and may be grouped under "Additional".
- Validation on submit; inline field errors from `error.details.fields` (`ARCHITECTURE.md` §5); first invalid field receives focus.
- Unsaved-changes guard on navigation. Save is explicit (Ctrl+S works) — no autosave in Phase 0/1 except notes drafts.
- Dates: `dd/mm/yyyy` display, ISO on the wire; date pickers accept typed input.

## 5. Status language

| Semantic | Meaning | Token |
|---|---|---|
| success | won, done, active, eligible | `--pys-success-600` |
| warning | due soon, at risk, stale, draft | `--pys-warning-600` |
| danger | overdue, lost, error, rejected | `--pys-danger-600` |
| info | open, neutral, informational | `--pys-info-600` |

- Status chips are always **label + color**, never color alone.
- Same word = same chip across every list and record (e.g. an opportunity "won" and a task "done" both read in the success language but keep their own labels).
- Pipeline stages show name + count; won/lost stages keep semantic coloring.

## 6. Deadline prominence

- Anything with `due_at` within 7 days appears: in the record alert strip, in the deadlines board, and (Phase 2) in calendar.
- Overdue items are danger-colored and sort to top — always, in every list that shows them.
- Due dates display as absolute date + relative hint ("12/06/2025 · in 3 g."), never relative alone.
- A deadline without an owner is itself a warning (assignee shown, or "non assegnata" flagged).

## 7. States

| State | Standard |
|---|---|
| Loading | Skeleton rows matching final layout; no full-page spinners after first load |
| Empty | Every empty list states *why* it's empty + the single next action ("Nessuna opportunità — Crea opportunità"). Never a bare blank table |
| Error | Semantic alert with the envelope `message`, a retry action, and the error `code` in small print for support |
| Forbidden | Dedicated 403 state explaining required role — not a generic error |
| Deleted/conflict | `409 VERSION_CONFLICT` → non-destructive banner: "Modificato da altro utente — ricarica" with reload action |

## 8. Keyboard & accessibility (WCAG 2.1 AA)

- Full keyboard operability: every action reachable by Tab; visible `--pys-focus-ring` on every interactive element.
- Global: `/` focuses search, `Ctrl+S` saves forms, `Esc` closes modals/menus, `g then <key>` navigates (g c → companies) — Phase 2+.
- Contrast ≥ 4.5:1 text / 3:1 UI chrome (all brand tokens verified in `BRAND_SYSTEM.md`).
- No information by color alone; icons always paired with text or `aria-label`.
- Tables use semantic `<table>` with `scope`; lists announce counts; live region announces background saves/errors.
- Touch targets ≥ 32px even in dense mode.

## 9. Anti-patterns

- Wizard dialogs for routine creation (create is one form, not five steps).
- Modals stacked on modals; modal for anything but confirm/short-create.
- Toast as the only confirmation of a destructive action — destructive = explicit confirm dialog.
- Auto-refresh that reorders lists under the user's cursor (use "N nuovi — aggiorna" pill).
- Icons without labels in primary navigation.
- Relative-only dates, truncated-only names (tooltip or expand required).
- "Are you sure?" text without naming the object — always "Elimina *Acme S.r.l.*?".
- Disabled buttons with no explanation — tooltip or inline hint stating the unmet condition.
