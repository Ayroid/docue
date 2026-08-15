# Docue frontend — functional specification

Written so the UI can be rebuilt on a new theme without losing behaviour.
Everything below is what the app **does**; nothing here is a styling
requirement except the section explicitly marked as one.

Stack: React 18 + TypeScript, Vite 6, react-router-dom 6, Tailwind 3 over CSS
custom properties, Radix primitives (`@radix-ui/react-dialog`, `react-slot`).
Source root `src`.

---

## 1. Routes

| Path | Page | Shell | Auth gate |
|---|---|---|---|
| `/` | Landing | none | redirects to `/discovery` when signed in |
| `/login` | Login | none | redirects to `/discovery` when signed in |
| `/viewer/:id` | DocumentViewer | **none** | **none — deliberate** |
| `/discovery` | Discovery | AppShell | none |
| `/library` | DocumentLibrary | AppShell | none |
| `/search?q=` | Results | AppShell | none |
| `/templates/:id` | TemplateDetail | AppShell | none |
| `/templates/:id/generate` | Generate | AppShell | none |
| `/generate/:sessionId/review` | Review | AppShell | none |
| `/documents` | MyDocuments | AppShell | none |
| `/documents/:id` | GeneratedDocument | AppShell | none |
| `/admin` | Admin | AppShell | none |
| `/analytics` | Analytics | AppShell | none |
| `/upload` | Upload | AppShell | none |
| `*` | → `/` | — | — |

`:id` on template routes is a **backend UUID**. `:sessionId`/`:id` on the
generate and generated-document routes are client-side ids (`s1`, `gs1`).

---

## 2. What is real and what is a demo

This distinction is load-bearing — keep it visible in the new UI.

**Real** (reads/writes the backend): Results, DocumentLibrary, DocumentViewer,
TemplateDetail, Upload, Admin. (Discovery is a search box only — it touches no
data at all.)

**Demo** (scripted, no service behind it): Generate → Review →
GeneratedDocument, and MyDocuments once the walkthrough has been used. Every
one of these screens carries a `DemoBadge` and a sentence saying the output
isn't stored. Fixtures live in `src/data/demo.ts`, imported by nothing else.

**Empty by design**: Analytics — nothing is instrumented, so it shows an empty
state rather than invented charts.

---

## 3. Backend API

Base URL is the **relative** `/api/v1`, proxied to `http://localhost:8000` by
Vite (`server.proxy` and `preview.proxy`). Keep it relative — an absolute URL
makes every call cross-origin and the server only allows a few fixed ports.

`src/services/templates.ts`:

| Function | Call | Returns |
|---|---|---|
| `listTemplates()` | `GET /templates` | `TemplateOut[]` (unpaginated) |
| `getTemplate(id)` | `GET /templates/{id}` | `TemplateOut` |
| `downloadTemplateFile(id)` | `GET /templates/{id}/download` | `ArrayBuffer` (raw file bytes) |
| `uploadTemplate(file)` | `POST /templates` (multipart `file`) | `UploadAccepted \| TemplateOut` |
| `uploadedTemplateId(result)` | — | the template id from either upload shape |

```ts
interface TemplateOut {
  id: string; title: string; original_filename: string
  format: 'docx' | 'xlsx' | 'pptx'
  status: string; current_version_id: string
  created_at: string; updated_at: string
  current_version: {
    id: string; version_number: number; storage_bucket: string
    storage_key: string; size_bytes: number; mime_type: string
    file_hash: string; upload_status: string; created_at: string
  } | null
}
interface UploadAccepted { template_id: string; version_id: string; job_id: string; status: string }
```

Errors throw `TemplateApiError { status, message }` with user-safe messages
(`status: 0` means the server was unreachable). Upload answers **202** with a
job id on the current API and **201** with a full record on older builds —
`uploadedTemplateId` reads whichever is present.

The backend also exposes `GET /templates/{id}/regions` and
`/templates/{id}/ingestion/{job_id}` (region detection). **The frontend does
not use them yet** — that is the hook for making generation real.

---

## 4. Global state — `src/store/HubProvider.tsx`

In-memory only; nothing persists across a reload or a new tab.

- `loggedIn`, `login()`, `logout()` — no real auth; Login accepts anything.
- `role` — fixed `'Admin'`; gates the Admin nav item only.
- `sidebarOpen`, `toggleSidebar()`.
- `uploads[]`, `lastUpload`, `addUpload(name, fmt, meta, backendId?)`, `removeUpload(id)` — templates submitted this session.
- `toast`, `fireToast(msg)` — 2.6s auto-dismiss, rendered by AppShell.
- `uploadDialogOpen`, `closeUploadDialog()` — the "sent for approval" dialog.
- Walkthrough only: `documents[]`, `drafts[]`, `sessions{}`, `startSession(templateId)`, `updateSession`, `getSession`, `saveDraft`, `commitSession`.

---

## 5. Pages

### Landing (`/`)
Marketing page, signed out. Sections: hero with an illustrated product mockup,
"How it works" steps, "What's inside" categories, a why panel, closing CTA,
footer. CTAs go to `/login`. Static copy only.

### Login (`/login`)
Email + password + "Forgot password?". Submitting calls `login()` and
navigates to `/discovery`. **No credentials are checked.**

### AppShell (wraps most pages)
- Sidebar: brand (→ `/`), nav items, "Upload template" button, user block with a settings popover containing Log out.
- Nav: Discovery (badge = real template count), My documents, Analytics, Admin (Admin role only, badge = pending uploads). Blank badge while loading, or when a number would be invented.
- Highlighting: `/library`, `/search`, `/templates/*`, `/generate/*` all light up **Discovery**. Uses plain `Link` + an explicit `aria-current` — `NavLink` sets its own `aria-current` after prop spread and silently clobbers it.
- Header: sidebar toggle, avatar.
- Global chrome: toast (bottom right) and the "Sent for approval" dialog.

### Discovery (`/discovery`)
The front door, and nothing else: a full-height hero holding the search box
(Enter → `/search?q=`) and the example query chips. It reads no templates and
has no loading, error or empty state of its own.

Browsing deliberately lives on `/library` instead — that page already carries
the whole library with its own filter, search and live preview, so a card grid
here would only be a second copy of it.

`RealTemplateCard` still exists in `src/components/TemplateCard.tsx` but is
currently rendered by nothing.

### Results (`/search?q=`)
Search box, removable applied-filter chips, a Format sidebar, and a results
table (Document / Size / Version / View). Empty state clears the search.

### DocumentLibrary (`/library`)
Master–detail reader. Left rail: text filter, DOC/XLS/PPT segmented filter,
scrollable list, "N of M documents" count. Right: the selected document
rendered, with Generate / Download / Open detail.
Selection mirrors to `?doc=<uuid>` so it is deep-linkable; an explicit `?doc=`
always beats the filter's top hit so a shared link can't be hijacked by a
stale filter.

### DocumentViewer (`/viewer/:id`) — opened in a new tab
Full-window reader. Sticky header: format chip, title, `filename · size ·
uploaded date`, version tag, **Download**, **Open in Template Hub**. Body: the
document, full width, page scrolls. Sets `document.title` to the filename.
States: loading / 404 ("no longer in the library") / render failure.

### TemplateDetail (`/templates/:id`)
Back link, title, `FORMAT · vN · uploaded date`. Left: live preview. Right: a
File panel (format, version, status, uploaded timestamp), **Open in full page**,
**Download**. 404s to a not-found empty state.

### Upload (`/upload`)
Two columns, mirroring the viewer. Left rail: file picker (`.docx,.xlsx,.pptx`,
25 MB), Template name, Category chips, Submit. **Everything on the left is
disabled until a valid file is chosen.** Right: the picked file rendered
through the same `DocumentStage` the viewer uses, or a "Nothing to preview yet"
panel.
Submit → `uploadTemplate` → read the record back with `getTemplate` → `addUpload`
→ navigate to `/admin` (which opens the confirmation dialog). Name defaults to
the filename without extension. **Category is collected but never sent — the
API has no field for it.**

### Admin (`/admin`)
Submissions made this session: format chip, name, meta, status pill, and
**View** (new tab) / **Verify** / **Clear**. Verify re-reads `GET /templates/{id}`
and shows a dialog with template id, status, storage key, file hash, size and
upload time — proof the file is really persisted. Empty state otherwise.

### MyDocuments (`/documents`)
Empty state until the walkthrough is used; then Drafts (with Resume) and a
Generated documents table (Document / Template / Created / Status / Open),
both marked as demo output held in this tab only.

### Analytics (`/analytics`)
Empty state — nothing is instrumented.

### Generate (`/templates/:id/generate`) — demo
Two panels. Left: an agent conversation — 4 scripted questions, one at a time,
with extracted-value chips under each answer, a T1/T2/T3 tier selector, a
textarea (Enter sends, Shift+Enter newlines), Send and Save draft. Right: a
live preview that updates per answer, showing each region's value and
provenance (typed / derived / AI-drafted / unchanged). Footer: a progress ring
(`N answers → M of 31 fields`), a preservation guarantee chip, Save draft and
**Review & commit**.
Starts from the real document's title, format and version. `?session=` resumes.

### Review (`/generate/:sessionId/review`) — demo
Field-by-field table with provenance tags and confidence, declined changes,
"Preserved on commit", QA checks, **Create document** (→ `/documents/:id`) and
Back to edit.

### GeneratedDocument (`/documents/:id`) — demo
Header with status, a skeleton document preview, "Generated from", a version
timeline, Download (toast only) and Generate another.

---

## 6. Document rendering — the part to port carefully

`src/features/document-preview/`. This is the app's real value and the most
fragile area.

- **`DocumentPreview`** — props `{ format, fileName, loadBytes, className?, surfaceClassName? }`. Loads bytes, clears the container, dispatches to a renderer inside try/catch, and shows loading / ready / error. Errors log the real cause to `console.error` but show a generic "Preview unavailable — download the file to view it." Never surface library error text.
- **`DocumentStage`** — the header bar + full-bleed render used by both the viewer and Upload. `format === 'xlsx'` gets a **white** backdrop (a sheet fills its window); docx/pptx get a neutral one (a page on a desk).
- **`docx.ts`** — docx-preview with `ignoreLastRenderedPageBreak: false`, `useBase64URL: true`, `experimental: true`.
- **`xlsx.ts`** — ExcelJS → a hand-built table with merges, bold and fills, plus a sheet-tab strip.
- **`pptx.ts`** — pptx-preview, then scaled to fit.
- **`fitToWidth.ts`** — scales a fixed-width page (A4 is 794px at 96dpi) down to the available width and sizes a wrapper to the *scaled* footprint.

**Rules that must survive a reskin:**

1. `loadBytes` **must** be wrapped in `useCallback` keyed on the id. A fresh function identity re-fires the effect in a loop.
2. The render container needs the **`doc-render-root`** class. Without it the app's `body` typography (font, 15px, line-height 1.55) inherits into the document and a Word file renders in the app's typeface at the app's size. The rule lives outside `@layer base` so it isn't demoted under Tailwind preflight.
3. Renderers are **lazy `import()`ed** — keep that or ~2.3 MB of parsers lands in the main bundle.
4. `key={id}` on the preview when the document can change, so the previous render tears down.
5. Anything measuring the surface must cope with it being `display: none` until the render resolves — everything measures 0 while hidden.
6. Cell/text content is written with `textContent`, **never `innerHTML`** — it is untrusted file content.

---

## 7. Shared components

`components/ui/`: `Button` (variants primary/secondary/ghost/bare, sizes
xs/sm/default/lg/icon, `block`, `asChild` via Radix Slot), `Input`, `Textarea`,
`Field`, `Tag` (accent/accent2/neutral/outline), `FilterTag` (selected +
disabled), `Segmented`, `Table`, `TableCard`, `Panel`, `SectionLabel`,
`Dialog`.

`components/common.tsx`: `FormatChip` (DOC/XLS/PPT disc, sizes 30–40),
`CHIP_BY_FORMAT` (`docx→DOC`, `xlsx→XLS`, `pptx→PPT`), `Avatar`, `DemoBadge`,
`PreviewLines`, `EmptyState`, `PageHeading`, `PageBody`.

`lib/utils.ts`: `cn`, `formatBytes`, `extOf`, `initialsOf`, `hash`.

---

## 8. Theming (the only styling section)

Colour, type, radius, shadow and spacing all resolve through CSS custom
properties in `src/styles/tokens.css`; `tailwind.config.ts` maps Tailwind names
onto them. A new theme can be dropped in by replacing token values.

Tokens: `--color-bg`, `--color-surface`, `--color-text`, `--color-divider`,
`--color-accent{,-100..-900}`, `--color-accent-2{,-100..-900}`,
`--color-neutral-100..900`, `--font-heading`, `--font-body`,
`--font-heading-weight`, `--radius-{sm,md,lg,control,tag,card}`,
`--shadow-{sm,md,lg}`, `--space-1..8`.

Component classes in `styles/components.css`: `.btn*`, `.input`, `.field`,
`.tag*`, `.seg*`, `.table`, `.card*`, `.dialog*`, `.hub-nav`, `.hub-tcard`,
`.hub-results`, `.hub-mydocs`, `.elev-*`, `.pill*`, plus the preview-specific
`.doc-render-root`, `.document-preview-surface`, `.doc-library-*` and
`.xlsx-preview-*`.

**Keep regardless of theme:** `.doc-render-root` (see §6.2) and the
`.xlsx-preview-*` white-sheet rules — those are document-fidelity, not brand.

---

## 9. Traps worth knowing before you rewrite

1. `/viewer/:id` must stay outside AppShell **and** outside the auth gate — `loggedIn` is in-memory, so a new tab is always signed out and a gate would bounce every View link to the landing page.
2. Sidebar highlighting must use `Link` + explicit `aria-current`, not `NavLink`.
3. The Templates tab badge counts real templates. Don't reintroduce a hardcoded total.
4. Real templates have **no** category, owner, usage count or version history — the API doesn't record them. Don't design UI that needs those fields without adding them to the API first.
5. `GET /templates` is unpaginated; every list renders every row.
6. Upload's category picker is decorative until the API accepts one.
7. 3 of 5 real `.xlsx` files currently fail to render — ExcelJS rejects workbooks containing a sheet named `History`. Swapping the xlsx renderer (`@js-preview/excel`) is the outstanding fix.
