import { cn } from '@/lib/utils'

/**
 * Material Symbols Outlined — the icon set the design system uses.
 *
 * The font is loaded in `index.html`; a symbol is just its name as the
 * element's text. `filled` switches to the solid cut, which the design uses
 * for the format tiles on cards.
 */
export function Icon({
  name,
  size = 20,
  filled = false,
  className,
}: {
  name: string
  size?: number
  filled?: boolean
  className?: string
}) {
  return (
    <span
      aria-hidden="true"
      className={cn('material-symbols-outlined leading-none select-none', className)}
      style={{
        fontSize: size,
        width: size,
        height: size,
        fontVariationSettings: `'FILL' ${filled ? 1 : 0}, 'wght' 400, 'GRAD' 0, 'opsz' ${size}`,
      }}
    >
      {name}
    </span>
  )
}
