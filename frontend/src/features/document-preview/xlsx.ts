import type { Worksheet } from 'exceljs'

/** 1-based column letters ("A", "Z", "AA", ...) to a 1-based index. */
function colLetterToIndex(letters: string): number {
  let n = 0
  for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64)
  return n
}

function parseCellAddress(addr: string): { row: number; col: number } {
  const m = /^([A-Z]+)(\d+)$/.exec(addr)
  if (!m) return { row: 1, col: 1 }
  return { row: Number(m[2]), col: colLetterToIndex(m[1]) }
}

function parseMergeRange(range: string): { r1: number; c1: number; r2: number; c2: number } {
  const [a, b] = range.split(':')
  const p1 = parseCellAddress(a)
  const p2 = b ? parseCellAddress(b) : p1
  return { r1: p1.row, c1: p1.col, r2: p2.row, c2: p2.col }
}

/** ExcelJS reports fill colors as 8-digit ARGB hex; CSS wants #RRGGBB. */
function argbToCss(argb: string | undefined): string | null {
  if (!argb || argb.length !== 8) return null
  return `#${argb.slice(2)}`
}

function buildSheetTable(worksheet: Worksheet): HTMLTableElement {
  const merges = (worksheet.model.merges ?? []).map(parseMergeRange)
  const covered = new Set<string>()
  const spanAt = new Map<string, { rowSpan: number; colSpan: number }>()

  for (const m of merges) {
    spanAt.set(`${m.r1}:${m.c1}`, { rowSpan: m.r2 - m.r1 + 1, colSpan: m.c2 - m.c1 + 1 })
    for (let r = m.r1; r <= m.r2; r++) {
      for (let c = m.c1; c <= m.c2; c++) {
        if (r === m.r1 && c === m.c1) continue
        covered.add(`${r}:${c}`)
      }
    }
  }

  const table = document.createElement('table')
  table.className = 'xlsx-preview-table'
  const rowCount = Math.max(worksheet.rowCount, worksheet.actualRowCount)
  const colCount = Math.max(worksheet.columnCount, worksheet.actualColumnCount)

  for (let r = 1; r <= rowCount; r++) {
    const tr = document.createElement('tr')
    const row = worksheet.getRow(r)
    for (let c = 1; c <= colCount; c++) {
      const key = `${r}:${c}`
      if (covered.has(key)) continue

      const cell = row.getCell(c)
      const td = document.createElement('td')
      const span = spanAt.get(key)
      if (span) {
        if (span.rowSpan > 1) td.rowSpan = span.rowSpan
        if (span.colSpan > 1) td.colSpan = span.colSpan
      }
      // textContent, never innerHTML — cell values are untrusted file content.
      td.textContent = cell.text
      if (cell.font?.bold) td.style.fontWeight = '600'
      const fill = cell.fill
      const bg = fill && fill.type === 'pattern' ? argbToCss(fill.fgColor?.argb) : null
      if (bg) td.style.backgroundColor = bg
      tr.appendChild(td)
    }
    table.appendChild(tr)
  }
  return table
}

export async function renderXlsx(container: HTMLElement, buf: ArrayBuffer) {
  const ExcelJS = await import('exceljs')
  const workbook = new ExcelJS.Workbook()
  await workbook.xlsx.load(buf)

  const tabs = document.createElement('div')
  tabs.className = 'xlsx-preview-tabs'
  const body = document.createElement('div')
  body.className = 'xlsx-preview-body'

  const showSheet = (name: string) => {
    body.innerHTML = ''
    const worksheet = workbook.getWorksheet(name)
    if (worksheet) body.appendChild(buildSheetTable(worksheet))
    tabs.querySelectorAll('button').forEach((btn) => {
      btn.classList.toggle('active', btn.textContent === name)
    })
  }

  workbook.worksheets.forEach((ws) => {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.textContent = ws.name
    btn.onclick = () => showSheet(ws.name)
    tabs.appendChild(btn)
  })

  container.appendChild(tabs)
  container.appendChild(body)
  if (workbook.worksheets[0]) showSheet(workbook.worksheets[0].name)
}
