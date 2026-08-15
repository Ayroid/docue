import { cn } from '@/lib/utils'

export interface SegmentedOption<T extends string> {
  value: T
  label: string
}

/**
 * The `.seg` control. Kept as real radio inputs — the design system styles the
 * selected state with `:has(input:checked)`, and radios give keyboard and
 * screen-reader behaviour that a div-with-onClick would have to reimplement.
 */
export function Segmented<T extends string>({
  name,
  value,
  options,
  onChange,
  className,
}: {
  name: string
  value: T
  options: readonly SegmentedOption<T>[]
  onChange: (value: T) => void
  className?: string
}) {
  return (
    <div className={cn('seg', className)} role="radiogroup">
      {options.map((opt) => (
        <label key={opt.value} className="seg-opt">
          <input
            type="radio"
            name={name}
            checked={value === opt.value}
            onChange={() => onChange(opt.value)}
          />
          {opt.label}
        </label>
      ))}
    </div>
  )
}
