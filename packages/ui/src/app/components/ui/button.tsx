import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "./utils"

// Added glassmorphism effects, larger border radius, and smooth hover translations
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-2xl text-sm font-medium transition-all duration-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 backdrop-blur-md border border-white/10 dark:border-white/5 active:scale-95",
  {
    variants: {
      variant: {
        default: "bg-primary/90 text-primary-foreground shadow-lg hover:bg-primary/100 hover:shadow-xl hover:-translate-y-0.5",
        destructive: "bg-destructive/90 text-destructive-foreground shadow-md hover:bg-destructive/100 hover:shadow-lg hover:-translate-y-0.5",
        outline: "border border-input bg-background/50 shadow-sm hover:bg-accent hover:text-accent-foreground",
        secondary: "bg-secondary/80 text-secondary-foreground shadow-md hover:bg-secondary/100 hover:shadow-lg hover:-translate-y-0.5",
        ghost: "hover:bg-accent/50 hover:text-accent-foreground border-transparent",
        link: "text-primary underline-offset-4 hover:underline border-transparent",
        primary: "bg-gradient-to-br from-[#D4AF37]/90 to-[#F3E2AB]/90 dark:from-[#D4AF37]/80 dark:to-[#B5952F]/80 text-black shadow-[0_4px_15px_rgba(212,175,55,0.2)] hover:shadow-[0_6px_20px_rgba(212,175,55,0.3)] hover:-translate-y-0.5",
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