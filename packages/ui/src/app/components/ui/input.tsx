import React from 'react';
import { useState } from 'react';
import { cn } from '../../../lib/utils';
import { Eye, EyeOff } from 'lucide-react';

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  passwordToggleLabels?: {
    show: string;
    hide: string;
  };
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, passwordToggleLabels, ...props }, ref) => {
    const [showPassword, setShowPassword] = useState(false);
    const isPasswordField = type === 'password';
    const inputType = isPasswordField && showPassword ? 'text' : type;

    return (
      <div className="relative w-full">
        <input
          type={inputType}
          className={cn(
            "flex h-11 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-gray-500 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gray-950 disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/10 dark:bg-[#121212] dark:text-gray-50 dark:placeholder:text-gray-400 dark:focus-visible:ring-white/20",
            isPasswordField && "pr-14",
            className
          )}
          ref={ref}
          {...props}
        />
        {isPasswordField && (
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute right-1.5 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-xl text-gray-400 transition-colors hover:text-gray-600 active:scale-95 dark:hover:text-gray-300"
            aria-label={showPassword
              ? passwordToggleLabels?.hide ?? 'Hide password'
              : passwordToggleLabels?.show ?? 'Show password'}
            aria-pressed={showPassword}
          >
            {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        )}
      </div>
    )
  }
)
Input.displayName = "Input"
