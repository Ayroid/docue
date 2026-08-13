import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const tagVariants = cva('tag', {
  variants: {
    variant: {
      accent: 'tag-accent',
      accent2: 'tag-accent-2',
      neutral: 'tag-neutral',
      outline: 'tag-outline',
      bare: '',
    },
  },
  defaultVariants: { variant: 'neutral' },
})

export interface TagProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof tagVariants> {}

export function Tag({ className, variant, ...props }: TagProps) {
  return <span className={cn(tagVariants({ variant }), className)} {...props} />
}

/**
 * The pill-shaped filter buttons used across Discovery, Results, My documents
 * and Admin. `selected` drives the accent fill the prototype applies inline.
 */
export function FilterTag({
  selected,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { selected?: boolean }) {
  return (
    <button
      type="button"
      className={cn(
        'tag cursor-pointer whitespace-nowrap border font-[inherit] text-[12px] px-[15px] py-[6px]',
        selected
          ? 'bg-accent text-bg border-accent'
          : 'bg-transparent text-ink border-divider',
        className,
      )}
      {...props}
    />
  )
}
