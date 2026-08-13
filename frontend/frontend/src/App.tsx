import { Navigate, Route, Routes } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import { AppShell } from '@/components/layout/AppShell'
import { Landing } from '@/pages/Landing'
import { Login } from '@/pages/Login'
import { Discovery } from '@/pages/Discovery'
import { DocumentLibrary } from '@/pages/DocumentLibrary'
import { DocumentViewer } from '@/pages/DocumentViewer'
import { Results } from '@/pages/Results'
import { TemplateDetail } from '@/pages/TemplateDetail'
import { Generate } from '@/pages/Generate'
import { Review } from '@/pages/Review'
import { GeneratedDocument } from '@/pages/GeneratedDocument'
import { MyDocuments } from '@/pages/MyDocuments'
import { Admin } from '@/pages/Admin'
import { Analytics } from '@/pages/Analytics'
import { Upload } from '@/pages/Upload'

export function App() {
  const { loggedIn } = useHub()

  return (
    <Routes>
      <Route path="/" element={loggedIn ? <Navigate to="/discovery" replace /> : <Landing />} />
      <Route path="/login" element={loggedIn ? <Navigate to="/discovery" replace /> : <Login />} />
      {/* Outside AppShell and outside the session gate on purpose: this is
          opened in a new tab, where it wants the full window width and where
          `loggedIn` (in-memory only) is always false on arrival. */}
      <Route path="/viewer/:id" element={<DocumentViewer />} />
      <Route element={<AppShell />}>
        <Route path="/discovery" element={<Discovery />} />
        {/* `/documents` is My-documents; the template library reads from the
            backend, so it gets its own path off the Discovery branch. */}
        <Route path="/library" element={<DocumentLibrary />} />
        <Route path="/search" element={<Results />} />
        <Route path="/templates/:id" element={<TemplateDetail />} />
        <Route path="/templates/:id/generate" element={<Generate />} />
        <Route path="/generate/:sessionId/review" element={<Review />} />
        <Route path="/documents" element={<MyDocuments />} />
        <Route path="/documents/:id" element={<GeneratedDocument />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/upload" element={<Upload />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
