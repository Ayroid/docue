import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from '@/store/AuthProvider'
import { RedirectIfSignedIn, RequireAdmin, RequireAuth } from '@/components/RouteGuards'
import { AppShell } from '@/components/layout/AppShell'
import { Landing } from '@/pages/Landing'
import { Login } from '@/pages/Login'
import { Register } from '@/pages/Register'
import { VerifyEmail } from '@/pages/VerifyEmail'
import { ForgotPassword } from '@/pages/ForgotPassword'
import { ResetPassword } from '@/pages/ResetPassword'
import { Discovery } from '@/pages/Discovery'
import { DocumentLibrary } from '@/pages/DocumentLibrary'
import { DocumentViewer } from '@/pages/DocumentViewer'
import { Results } from '@/pages/Results'
import { UpdateTemplate } from '@/pages/UpdateTemplate'
import { TemplateDetail } from '@/pages/TemplateDetail'
import { Generate } from '@/pages/Generate'
import { Review } from '@/pages/Review'
import { GeneratedDocument } from '@/pages/GeneratedDocument'
import { MyDocuments } from '@/pages/MyDocuments'
import { Admin } from '@/pages/Admin'
import { Analytics } from '@/pages/Analytics'
import { Upload } from '@/pages/Upload'

export function App() {
  const { signedIn, loading } = useAuth()

  return (
    <Routes>
      {/* The marketing page redirects a signed-in visitor, but only once the
          session check has finished — otherwise a refresh on `/` flashes the
          landing page at someone who is already signed in. */}
      <Route
        path="/"
        element={!loading && signedIn ? <Navigate to="/discovery" replace /> : <Landing />}
      />

      <Route
        path="/login"
        element={
          <RedirectIfSignedIn>
            <Login />
          </RedirectIfSignedIn>
        }
      />
      <Route
        path="/register"
        element={
          <RedirectIfSignedIn>
            <Register />
          </RedirectIfSignedIn>
        }
      />
      {/* Verification and reset are deliberately *not* wrapped in
          `RedirectIfSignedIn`: verifying signs you in, and this route is what
          renders the moment that happens. Bouncing on `signedIn` would tear the
          screen down mid-submit. */}
      <Route path="/verify-email" element={<VerifyEmail />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />

      {/* Outside AppShell on purpose: this is opened in a new tab, where it
          wants the full window width. It is inside the session gate now that
          the token survives a reload — the backend refuses an unapproved
          template to anyone but its owner and the admins, so an anonymous
          viewer tab could not render one anyway. */}
      <Route
        path="/viewer/:id"
        element={
          <RequireAuth>
            <DocumentViewer />
          </RequireAuth>
        }
      />

      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/discovery" element={<Discovery />} />
        {/* `/documents` is My-documents; the template library reads from the
            backend, so it gets its own path off the Discovery branch. */}
        <Route path="/library" element={<DocumentLibrary />} />
        <Route path="/search" element={<Results />} />
        <Route path="/templates/:id" element={<TemplateDetail />} />
        <Route path="/templates/:id/update" element={<UpdateTemplate />} />
        <Route path="/templates/:id/generate" element={<Generate />} />
        <Route path="/generate/:sessionId/review" element={<Review />} />
        <Route path="/documents" element={<MyDocuments />} />
        <Route path="/documents/:id" element={<GeneratedDocument />} />
        <Route
          path="/admin"
          element={
            <RequireAdmin>
              <Admin />
            </RequireAdmin>
          }
        />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/upload" element={<Upload />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
