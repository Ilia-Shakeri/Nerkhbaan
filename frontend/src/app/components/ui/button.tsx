import React from 'react';
import { cn } from '../../../lib/utils';
// @ts-ignore
import { motion, HTMLMotionProps } from 'motion/react';

export const buttonVariants = (props?: { variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger', size?: 'sm' | 'md' | 'lg' | 'icon', className?: string }) => {
  const variant = props?.variant || 'primary';
  const size = props?.size || 'md';
  const variants: Record<string, string> = {
    primary: 'bg-[#D4AF37] text-[#0A0A0A] hover:bg-[#C29D29] font-medium shadow-[0_4px_14px_0_rgba(212,175,55,0.39)]',
    secondary: 'bg-[#0B1F3A] text-white hover:bg-[#0B1F3A]/90 dark:bg-white/10 dark:text-white dark:hover:bg-white/15',
    outline: 'border border-gray-200 bg-transparent hover:bg-gray-100 text-gray-900 dark:border-white/10 dark:text-gray-100 dark:hover:bg-white/5',
    ghost: 'bg-transparent hover:bg-gray-100 text-gray-700 dark:text-gray-300 dark:hover:bg-white/10',
    danger: 'bg-[#EF4444] text-white hover:bg-red-600 shadow-[0_4px_14px_0_rgba(239,68,68,0.39)]',
  };

  const sizes: Record<string, string> = {
    sm: 'h-8 px-3 text-xs rounded-lg',
    md: 'h-10 px-4 py-2 text-sm rounded-xl',
    lg: 'h-12 px-8 text-base rounded-2xl',
    icon: 'h-10 w-10 flex items-center justify-center rounded-xl',
  };

  return cn(
    "inline-flex items-center justify-center whitespace-nowrap transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 active:scale-[0.98]",
    variants[variant],
    sizes[size],
    props?.className
  );
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg' | 'icon';
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', ...props }, ref) => {
    
    return (
      <button
        ref={ref}
        className={buttonVariants({ variant, size, className })}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";
