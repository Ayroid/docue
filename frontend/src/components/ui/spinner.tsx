import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * An indeterminate spinner, with room for something at its centre.
 *
 * Reach for a `Skeleton` first: whenever the shape of what is arriving is
 * known, drawing that shape is the better wait, because the content lands in
 * space already reserved for it. This is for work whose result has no layout to
 * promise — a model thinking, a plan being compiled — where the only honest
 * thing to say is "still going".
 *
 * It carries no percentage and no stage, deliberately. Nothing upstream reports
 * either, and a bar that fills on a timer is a claim about progress the page
 * cannot make.
 *
 * The rotation lives in `.hub-spinner` (`styles/components.css`), which also
 * swaps it for a pulse under `prefers-reduced-motion`.
 */
export function Spinner({
  size = 40,
  thickness = 3,
  className,
  children,
  label = 'Working',
}: {
  size?: number
  thickness?: number
  className?: string
  /** Rendered inside the ring — an icon, usually. */
  children?: ReactNode
  /** Announced by screen readers, which get no benefit from the ring itself. */
  label?: string
}) {
  return (
    <div role="status" aria-label={label} className={cn('relative grid place-items-center', className)} style={{ width: size, height: size }}>
      <div className="hub-spinner absolute inset-0" style={{ borderWidth: thickness }} aria-hidden="true" />
      {children ? <div className="relative grid place-items-center">{children}</div> : null}
    </div>
  )
}
