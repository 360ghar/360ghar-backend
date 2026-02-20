/**
 * Theme utilities for MCP App widgets.
 *
 * Works across ChatGPT (OpenAI), Claude Desktop, VS Code, MCPJam, and other
 * MCP hosts. Falls back to the system `prefers-color-scheme` media query when
 * no host-level theme is available.
 */

import { useTheme } from './bridge';

/**
 * CSS variables for theming.
 */
export interface WidgetThemeColors {
  background: string;
  backgroundSecondary: string;
  text: string;
  textSecondary: string;
  border: string;
  primary: string;
  primaryHover: string;
  success: string;
  error: string;
  warning: string;
  surfaceTint: string;
  shadow: string;
}

export const themeColors: Record<'light' | 'dark', WidgetThemeColors> = {
  light: {
    background: '#FFFEF7',
    backgroundSecondary: '#FFFDF0',
    text: '#3D3829',
    textSecondary: '#7A7464',
    border: '#EDE7D0',
    primary: '#E5D08B',
    primaryHover: '#D9C478',
    success: '#9CAF7C',
    error: '#C99898',
    warning: '#D4B56A',
    surfaceTint: '#FFF8E1',
    shadow: '0 14px 32px rgba(61, 56, 41, 0.10)',
  },
  dark: {
    background: '#1C1A16',
    backgroundSecondary: '#2A2720',
    text: '#F2EDE0',
    textSecondary: '#A9A394',
    border: '#3D3A34',
    primary: '#D9C478',
    primaryHover: '#E5D08B',
    success: '#8FAF6C',
    error: '#C98888',
    warning: '#C9A854',
    surfaceTint: '#2E2B26',
    shadow: '0 16px 38px rgba(0, 0, 0, 0.35)',
  },
};

/**
 * Hook to get theme-aware colors.
 */
export function useThemeColors() {
  const theme = useTheme();
  return themeColors[theme];
}

/**
 * Get CSS styles for the current theme.
 */
export function getThemeStyles(theme: 'light' | 'dark'): React.CSSProperties {
  const colors = themeColors[theme];
  return {
    backgroundColor: colors.background,
    color: colors.text,
    fontFamily: '"Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif',
  };
}
