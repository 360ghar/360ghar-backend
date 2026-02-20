/**
 * Reusable Button component.
 */

import React from 'react';
import { useThemeColors } from '../../utils/theme';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  children,
  disabled,
  style,
  ...props
}: ButtonProps) {
  const colors = useThemeColors();

  const baseStyles: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: '10px',
    fontWeight: 600,
    letterSpacing: '0.01em',
    transition: 'transform 0.12s ease, background-color 0.12s ease, border-color 0.12s ease',
    border: 'none',
    cursor: disabled || loading ? 'not-allowed' : 'pointer',
    opacity: disabled || loading ? 0.6 : 1,
    boxShadow: disabled || loading ? 'none' : colors.shadow,
  };

  const sizeStyles: Record<string, React.CSSProperties> = {
    sm: { padding: '6px 12px', fontSize: '13px' },
    md: { padding: '10px 16px', fontSize: '14px' },
    lg: { padding: '13px 22px', fontSize: '15px' },
  };

  const variantStyles: Record<string, React.CSSProperties> = {
    primary: {
      backgroundColor: colors.primary,
      color: '#3D3829',
    },
    secondary: {
      backgroundColor: colors.surfaceTint,
      color: colors.text,
      border: `1px solid ${colors.border}`,
    },
    ghost: {
      backgroundColor: 'transparent',
      color: colors.primary,
    },
  };

  return (
    <button
      disabled={disabled || loading}
      style={{
        ...baseStyles,
        ...sizeStyles[size],
        ...variantStyles[variant],
        ...style,
      }}
      {...props}
    >
      {loading ? 'Loading...' : children}
    </button>
  );
}
