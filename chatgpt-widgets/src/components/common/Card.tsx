/**
 * Reusable Card component.
 */

import React from 'react';
import { useThemeColors } from '../../utils/theme';

interface CardProps {
  children: React.ReactNode;
  onClick?: () => void;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  style?: React.CSSProperties;
}

export function Card({ children, onClick, padding = 'md', style }: CardProps) {
  const colors = useThemeColors();

  const paddingMap = {
    none: 0,
    sm: 8,
    md: 16,
    lg: 24,
  };

  return (
    <div
      onClick={onClick}
      style={{
        background: `linear-gradient(180deg, ${colors.backgroundSecondary} 0%, ${colors.background} 100%)`,
        borderRadius: '14px',
        border: `1px solid ${colors.border}`,
        padding: paddingMap[padding],
        cursor: onClick ? 'pointer' : 'default',
        boxShadow: colors.shadow,
        transition: 'transform 120ms ease, box-shadow 120ms ease',
        ...style,
      }}
    >
      {children}
    </div>
  );
}
