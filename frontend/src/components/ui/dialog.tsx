import * as DialogPrimitive from '@radix-ui/react-dialog'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * shadcn/ui Dialog over Radix, styled with the design system's `.dialog`
 * classes. Radix supplies the focus trap, scroll lock and Escape handling the
 * prototype's plain backdrop div did not.
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  children,
  actions,
  className,
  header,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title?: string
  children: ReactNode
  actions?: ReactNode
  className?: string
  header?: ReactNode
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="dialog-backdrop" />
        <DialogPrimitive.Content
          className={cn('dialog fixed left-1/2 top-1/2 z-[51] -translate-x-1/2 -translate-y-1/2', className)}
        >
          {header ?? (
            <DialogPrimitive.Title className="dialog-title">{title}</DialogPrimitive.Title>
          )}
          {children}
          {actions ? <div className="dialog-actions">{actions}</div> : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

export const DialogTitle = DialogPrimitive.Title
