import React from 'react';
import { cn } from '../../../lib/utils';

interface SwitchProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'onChange'> {
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

export const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  ({ className, checked, defaultChecked = false, onCheckedChange, ...props }, ref) => {
    const [internalChecked, setInternalChecked] = React.useState(defaultChecked);
    const isChecked = checked ?? internalChecked;

    const toggle = () => {
      const nextChecked = !isChecked;
      if (checked === undefined) {
        setInternalChecked(nextChecked);
      }
      onCheckedChange?.(nextChecked);
    };

    return (
      <button
        ref={ref}
        type="button"
        role="switch"
        aria-checked={isChecked}
        onClick={toggle}
        className={cn(
          "peer relative inline-flex h-11 w-12 shrink-0 cursor-pointer items-center justify-center rounded-full transition-transform active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#D4AF37] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        {...props}
      >
        <span
          className={cn(
            "pointer-events-none flex h-6 w-11 items-center rounded-full p-0.5 transition-colors",
            isChecked ? "bg-[#10B981]" : "bg-gray-300 dark:bg-white/15",
          )}
        >
          <span
            className={cn(
              "block h-5 w-5 rounded-full bg-white shadow-md transition-transform duration-200",
              isChecked ? "translate-x-5 rtl:-translate-x-5" : "translate-x-0",
            )}
          />
        </span>
      </button>
    );
  }
);
Switch.displayName = "Switch";
