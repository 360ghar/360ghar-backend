// "Sky & Earth" brand palette for the 360Ghar wiki video.

export const palette = {
  navy: "#0F2C4A",
  sand: "#E8DCC4",
  terracotta: "#C75D3B",
  ink: "#1A1A1A",
  muted: "#5A6B7A",
  white: "#FFFFFF",
} as const;

export type PaletteColor = keyof typeof palette;

// Typography constants. Sizes assume a 1920x1080 composition.
export const typography = {
  fontFamily:
    "'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif",
  title: 96,
  subtitle: 64,
  caption: 44,
  captionSmall: 36,
  body: 28,
  tagline: 40,
} as const;

// Animation timing presets (in frames at 30fps).
export const timing = {
  fast: 10,
  normal: 20,
  slow: 30,
  verySlow: 45,
} as const;

// Common spring configuration for natural motion without bounce.
export const smoothSpring = { damping: 200 } as const;
export const snappySpring = { damping: 20, stiffness: 200 } as const;
