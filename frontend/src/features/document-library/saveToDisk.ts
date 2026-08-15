import { downloadTemplateFile, type TemplateOut } from '@/services/templates'

/**
 * Pulls the real bytes through the backend and hands them to the browser as a
 * download. Separate from the preview path on purpose — preview parses the
 * bytes in-page, this one never looks inside them.
 *
 * Throws whatever `downloadTemplateFile` throws (a `TemplateApiError`), so the
 * caller decides how to surface a failure.
 */
export async function saveTemplateToDisk(template: TemplateOut): Promise<void> {
  const buf = await downloadTemplateFile(template.id)
  const url = URL.createObjectURL(new Blob([buf], { type: template.current_version?.mime_type }))
  const a = document.createElement('a')
  a.href = url
  a.download = template.original_filename
  a.click()
  URL.revokeObjectURL(url)
}
