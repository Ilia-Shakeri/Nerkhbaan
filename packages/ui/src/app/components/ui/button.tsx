import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "./utils"

const buttonVariants = cva(
  "app-button inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold transition-[color,background-color,border-color,box-shadow,transform] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#D4AF37] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 border active:scale-[0.97]",
  {
    variants: {
      variant: {
        default: "border-[#B8942A] bg-[#D4AF37] text-[#151006] shadow-sm hover:bg-[#E2C05A] hover:shadow-md",
        destructive: "border-red-700/40 bg-red-600 text-white shadow-sm hover:bg-red-500 hover:shadow-md",
        outline: "border-[#D4AF37]/35 bg-transparent text-inherit shadow-sm hover:border-[#D4AF37]/60 hover:bg-[#D4AF37]/10",
        secondary: "border-[#D4AF37]/20 bg-[#D4AF37]/10 text-inherit shadow-sm hover:bg-[#D4AF37]/18",
        ghost: "hover:bg-accent/50 hover:text-accent-foreground border-transparent",
        link: "text-primary underline-offset-4 hover:underline border-transparent",
        primary: "border-[#B8942A] bg-[#D4AF37] text-[#151006] shadow-sm hover:bg-[#E2C05A] hover:shadow-md",
      },
      size: {
        default: "h-11 px-6 py-2",
        sm: "h-9 rounded-xl px-4 text-xs",
        lg: "h-12 rounded-2xl px-10 text-base",
        icon: "h-11 w-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
