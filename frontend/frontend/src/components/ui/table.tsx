import type { HTMLAttributes, ReactNode, TableHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

/** The surface card every table in the hub sits inside. */
export function TableCard({
  className,
  children,
  scroll = true,
}: {
  className?: string
  children: ReactNode
  scroll?: boolean
}) {
  return (
    <div
      className={cn('bg-surface rounded-card pt-2 px-[18px] pb-[14px]', scroll && 'overflow-x-auto', className)}
    >
      {children}
    </div>
  )
}

export function Table({ className, ...props }: TableHTMLAttributes<HTMLTableElement>) {
  return <table className={cn('table', className)} {...props} />
}

export function SectionLabel({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('text-[10.5px] tracking-[.1em] uppercase opacity-55 mb-3', className)}
      {...props}
    />
  )
}

/** The `background:var(--color-surface)` panel used for every sidebar card. */
export function Panel({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('bg-surface rounded-card p-[18px]', className)} {...props} />
}
