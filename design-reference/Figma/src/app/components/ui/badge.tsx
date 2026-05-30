import * as React from "react"
import { cn } from "../../../lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "positive" | "negative" | "outline"
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const variants = {
    default: "bg-[#2A2A2A] text-gray-100",
    positive: "bg-[#10B981]/10 text-[#10B981] border border-[#10B981]/20",
    negative: "bg-[#EF4444]/10 text-[#EF4444] border border-[#EF4444]/20",
    outline: "text-gray-900 border border-gray-200 dark:text-gray-100 dark:border-[#2A2A2A]",
  }

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-[#D4AF37] focus:ring-offset-2",
        variants[variant],
        className
      )}
      {...props}
    />
  )
}

export { Badge }
