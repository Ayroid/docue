# Docue — Frontend

React interface for Docue, a document template hub built for the YMSLI
hackathon. Users search a library of templates by meaning, answer a short
interview about the one they picked, and get back a filled document with the
original's formatting intact.

The API it talks to lives alongside it in [`backend/`](../backend). Run both: see
the [root README](../README.md).

---

## Stack

React 18 + TypeScript, Vite 6, react-router-dom 6, Tailwind 3 layered over CSS
custom properties, and Radix primitives for dialogs and radio groups.

Documents are previewed **in the browser** rather than server-rendered:
`docx-preview` for Word, `pptx-preview` for PowerPoint, and `exceljs` for
spreadsheets. That keeps the round trip short and means the preview works on a
file the user has selected but not yet uploaded.

## Running it

```bash
npm install
npm run dev
```

The dev server comes up on `http://localhost:5173`. It expects the backend on
`http://localhost:8000` — Vite proxies `/api/v1` there, configured in
`vite.config.ts`.

Keep the API base URL **relative**. An absolute URL makes every call
cross-origin, and the backend only allows a small fixed set of origins.

| Command | Does |
|---|---|
| `npm run dev` | Dev server with HMR |
| `npm run build` | Type-check, then production build |
| `npm run preview` | Serve the built output |
| `npm run typecheck` | `tsc --noEmit` |

## Layout

```
src/
├── pages/        one file per route
├── features/     feature-scoped logic — generate, search, upload,
│                 ingestion, document-preview, access, notifications
├── components/   shared UI; components/ui holds the primitives
├── services/     one module per backend resource (auth, templates,
│                 search, sessions, documents, versions, access)
├── store/        cross-page state
├── styles/       design tokens as CSS custom properties
└── lib/          helpers
```

Routes are declared in `src/App.tsx` and gated by `RequireAuth`,
`RequireAdmin`, and `RedirectIfSignedIn` from `src/components/RouteGuards.tsx`.

`/viewer/:id` is deliberately **outside** the app shell and **ungated** — it is
the shareable link to a single document, and it renders standalone.

## Auth

The access token is kept in `localStorage` under `docue.token`
(`src/services/auth.ts`). Tokens are valid for 12 hours, and there is no
refresh token — when one expires the user signs in again.

## Design tokens

Colour, type, and spacing live as CSS custom properties in
`src/styles/tokens.css`; Tailwind is configured to consume them rather than
carry its own palette. Change a token there and it propagates everywhere.

## Further reading

`FRONTEND_FUNCTIONAL_SPEC.md` documents the intended behaviour of every screen
independently of styling, so the UI can be re-themed without losing behaviour.
