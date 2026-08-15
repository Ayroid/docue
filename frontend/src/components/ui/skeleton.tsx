import { cn } from '@/lib/utils'

/**
 * Placeholders shown while content is in flight.
 *
 * **A skeleton is a promise about layout, not a spinner.** Every one of these
 * is sized to the thing it stands in for, so the real content lands in the
 * space already reserved for it instead of shoving the page down — which is
 * the whole reason to prefer this over "Loading…". A skeleton that is the
 * wrong height is worse than no skeleton at all: it moves the page twice.
 *
 * **Screen readers are told once, not per box.** A grid of twelve placeholders
 * is one fact — "this is loading" — so the boxes are `aria-hidden` and the
 * container carries a single `role="status"`. Announcing each one would read
 * the same non-word twelve times.
 *
 * The shimmer lives in `styles/components.css` under `.hub-skeleton`, which
 * also drops the animation under `prefers-reduced-motion`.
 */
export function Skeleton({
  className,
  width,
  height,
  rounded = 'md',
}: {
  className?: string
  width?: number | string
  height?: number | string
  rounded?: 'sm' | 'md' | 'lg' | 'pill' | 'none'
}) {
  const radius = {
    none: '',
    sm: 'rounded-[4px]',
    md: 'rounded-[6px]',
    lg: 'rounded-card',
    pill: 'rounded-pill',
  }[rounded]

  return (
    <div
      aria-hidden="true"
      className={cn('hub-skeleton animate-hubshimmer', radius, className)}
      style={{ width, height }}
    />
  )
}

/**
 * The announcing wrapper. Put one of these around a group of `Skeleton`s.
 *
 * `aria-busy` rather than a visually-hidden "Loading" string: the label is on
 * the live region, so a screen reader says it once when the region appears and
 * again when it is replaced by real content.
 */
export function SkeletonGroup({
  children,
  className,
  label = 'Loading',
}: {
  children: React.ReactNode
  className?: string
  label?: string
}) {
  return (
    <div role="status" aria-busy="true" aria-label={label} className={className}>
      {children}
    </div>
  )
}

/* Widths that taper rather than sitting flush, so a block of placeholder lines
   reads as prose instead of as a table. The last line is always shortest — it
   is the one a paragraph actually ends on. */
const LINE_WIDTHS = ['100%', '96%', '88%', '92%', '70%']

/** A run of text lines. `lines` beyond the width list wraps around it. */
export function SkeletonText({
  lines = 3,
  className,
  lineHeight = 10,
  gap = 8,
}: {
  lines?: number
  className?: string
  lineHeight?: number
  gap?: number
}) {
  return (
    <div className={cn('flex flex-col', className)} style={{ gap }}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height={lineHeight}
          rounded="sm"
          /* The final line is short whatever the count, so a two-line block
             still looks like a paragraph rather than two full-width bars. */
          width={i === lines - 1 ? '62%' : LINE_WIDTHS[i % LINE_WIDTHS.length]}
        />
      ))}
    </div>
  )
}

/**
 * A stand-in for one `RealTemplateCard`.
 *
 * Built from the card's own blocks — icon tile and two-line title, the
 * description, the tag row, the meta line, then the action row — inside the
 * same `hub-tcard`, so the two can only drift apart if the card is restructured
 * and this is not. The height follows from the same gaps rather than being
 * pinned to a number that has to be re-measured by hand.
 */
export function TemplateCardSkeleton() {
  return (
    <div className="hub-tcard">
      <div className="flex items-start gap-3">
        <Skeleton width={40} height={40} rounded="md" className="flex-none" />
        {/* No status pill placeholder: the card only shows one for a pending or
            rejected template, which is the rare case, so reserving that corner
            on every skeleton would promise something most cards never fill. */}
        <div className="min-w-0 flex-1">
          <Skeleton height={16} width="88%" className="mb-2" />
          <Skeleton height={16} width="54%" className="mb-2" />
          <Skeleton height={11} width="40%" rounded="sm" />
        </div>
      </div>

      <SkeletonText lines={2} className="min-h-10" />

      <div className="flex items-center gap-1.5 min-h-6">
        {[62, 48, 54].map((w, i) => (
          <Skeleton key={i} width={w} height={20} rounded="pill" />
        ))}
      </div>

      <div className="mt-auto flex items-center justify-between gap-3 border-t border-divider pt-3">
        <Skeleton height={12} width={132} rounded="sm" />
        <Skeleton height={12} width={72} rounded="sm" />
      </div>

      <div className="flex items-center gap-2">
        <Skeleton height={34} rounded="pill" className="flex-1" />
        <Skeleton height={34} rounded="pill" className="flex-1" />
        <Skeleton width={36} height={36} rounded="pill" className="flex-none" />
      </div>
    </div>
  )
}

/** A stand-in for one `.doc-library-row` in the library's left rail. */
export function DocumentRowSkeleton() {
  return (
    <div className="doc-library-row">
      <Skeleton width={32} height={32} rounded="md" className="flex-none" />
      <span className="flex-1 min-w-0 flex flex-col gap-[5px]">
        <Skeleton height={12} width="78%" rounded="sm" />
        <Skeleton height={10} width="56%" rounded="sm" />
        <Skeleton height={9} width="42%" rounded="sm" />
      </span>
    </div>
  )
}

/** A stand-in for one card in the admin approval queue. */
export function ApprovalCardSkeleton() {
  return (
    <div className="relative bg-surface border border-divider rounded-card p-5 flex flex-col gap-4 shadow-elev-sm">
      <Skeleton className="absolute top-4 right-4" width={92} height={20} rounded="pill" />
      <Skeleton width={40} height={40} rounded="md" />
      <div className="min-w-0 flex flex-col gap-2">
        <Skeleton height={16} width="62%" />
        <Skeleton height={12} width="80%" rounded="sm" />
        <Skeleton height={11} width="48%" rounded="sm" />
      </div>
      <div className="flex gap-2">
        <Skeleton width={96} height={32} rounded="pill" />
        <Skeleton width={110} height={32} rounded="pill" />
      </div>
    </div>
  )
}

/**
 * A stand-in for one row in the search/browse results list.
 *
 * Both the ranked-hit card and the browse card are an icon tile, a title with
 * a tag, a filename and a meta line, with actions on the right — close enough
 * that one placeholder serves both rather than guessing which list is coming.
 */
export function ResultRowSkeleton() {
  return (
    <div className="bg-surface border border-divider rounded-card p-5 flex gap-4 items-start shadow-elev-sm">
      <Skeleton width={40} height={40} rounded="md" className="flex-none" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3 mb-2">
          <Skeleton height={16} width="38%" />
          <Skeleton height={20} width={52} rounded="pill" />
        </div>
        <Skeleton height={12} width="52%" rounded="sm" className="mb-3" />
        <div className="flex items-center gap-4">
          <Skeleton height={11} width={72} rounded="sm" />
          <Skeleton height={11} width={128} rounded="sm" />
          <Skeleton height={18} width={44} rounded="pill" />
        </div>
      </div>
      <div className="flex flex-col gap-2 flex-none">
        <Skeleton width={86} height={30} rounded="pill" />
        <Skeleton width={86} height={30} rounded="pill" />
      </div>
    </div>
  )
}

/** `count` result rows under one live region. */
export function ResultListSkeleton({ count = 4, label = 'Loading results' }: { count?: number; label?: string }) {
  return (
    <SkeletonGroup label={label} className="flex flex-col gap-3">
      {Array.from({ length: count }).map((_, i) => (
        <ResultRowSkeleton key={i} />
      ))}
    </SkeletonGroup>
  )
}

/**
 * A stand-in for a rendered document.
 *
 * Shaped like a page — a white sheet, a heading, paragraph runs — rather than
 * one grey slab, because the thing arriving *is* a page and the placeholder
 * should say so. `xlsx` gets a grid instead: a spreadsheet that faded in from
 * a paragraph outline would be a small lie about what is coming.
 */
export function DocumentPreviewSkeleton({
  variant = 'page',
  fileName,
}: {
  variant?: 'page' | 'sheet'
  /** Named in the live region, so a screen reader hears which file is coming
      rather than a bare "Loading". */
  fileName?: string
}) {
  const label = fileName ? `Rendering ${fileName}` : 'Rendering document'

  if (variant === 'sheet') {
    return (
      <SkeletonGroup label={label} className="p-[14px]">
        <div className="flex gap-[6px] mb-[10px]">
          {[68, 54, 60].map((w, i) => (
            <Skeleton key={i} width={w} height={26} rounded="sm" />
          ))}
        </div>
        <div className="flex flex-col gap-[3px]">
          {Array.from({ length: 12 }).map((_, row) => (
            <div key={row} className="flex gap-[3px]">
              {Array.from({ length: 6 }).map((_, col) => (
                <Skeleton
                  key={col}
                  height={row === 0 ? 26 : 22}
                  rounded="none"
                  className={cn('flex-1', row === 0 && 'opacity-90')}
                />
              ))}
            </div>
          ))}
        </div>
      </SkeletonGroup>
    )
  }

  return (
    <SkeletonGroup label={label} className="p-[14px]">
      {/* The sheet itself is a real white surface with a border, not a
          skeleton: the page arrives at that size and in that place, so drawing
          it for real is what stops the shift when the render lands. */}
      <div className="bg-[color:var(--md-surface-container-lowest)] border border-divider rounded-[6px] p-8 shadow-elev-sm">
        <Skeleton height={20} width="52%" className="mb-5" />
        <SkeletonText lines={5} className="mb-6" />
        <SkeletonText lines={4} className="mb-6" />
        <Skeleton height={14} width="34%" className="mb-3" />
        <SkeletonText lines={3} />
      </div>
    </SkeletonGroup>
  )
}
