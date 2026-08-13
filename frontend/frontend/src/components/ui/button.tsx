import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

/**
 * shadcn/ui Button, with the design system's own `.btn` classes as the variant
 * source rather than a parallel Tailwind recipe. One definition of what a
 * primary button looks like keeps the rendered result identical to the
 * prototype, and re-themes for free when the tokens change.
 */
const buttonVariants = cva('btn', {
  variants: {
    variant: {
      primary: 'btn-primary',
      secondary: 'btn-secondary',
      ghost: 'btn-ghost',
      bare: '',
    },
    size: {
      default: '',
      sm: 'text-[13px] px-[14px] py-[7px]',
      xs: 'text-[12.5px] px-[13px] py-[6px]',
      lg: 'text-[16px] px-[26px] py-[12px]',
      icon: 'btn-icon',
    },
    block: { true: 'btn-block', false: '' },
  },
  defaultVariants: { variant: 'bare', size: 'default', block: false },
})

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, block, asChild = false, type = 'button', ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp
        ref={ref}
        type={asChild ? undefined : type}
        className={cn(buttonVariants({ variant, size, block }), className)}
        {...props}
      />
    )
  },
)
Button.displayName = 'Button'

export { buttonVariants }
