import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { Discovery } from '@/pages/Discovery'
import { Results } from '@/pages/Results'
import { TemplateDetail } from '@/pages/TemplateDetail'
import { Generate } from '@/pages/Generate'
import { Review } from '@/pages/Review'
import { GeneratedDocument } from '@/pages/GeneratedDocument'
import { MyDocuments } from '@/pages/MyDocuments'
import { Admin } from '@/pages/Admin'
import { Analytics } from '@/pages/Analytics'
import { Upload } from '@/pages/Upload'
import { Welcome } from '@/pages/Welcome'

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Discovery />} />
        <Route path="/search" element={<Results />} />
        <Route path="/templates/:id" element={<TemplateDetail />} />
        <Route path="/templates/:id/generate" element={<Generate />} />
        <Route path="/generate/:sessionId/review" element={<Review />} />
        <Route path="/documents" element={<MyDocuments />} />
        <Route path="/documents/:id" element={<GeneratedDocument />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/welcome" element={<Welcome />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
