import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { palette, typography } from "../theme";

export type WordmarkProps = {
  /** Pixel size of the "360" digit. Other glyphs scale relative to it. */
  size?: number;
  /** Override the default navy wordmark color (e.g. for dark backgrounds). */
  color?: string;
  /** Show or hide the terracotta accent dot after "360". Defaults to true. */
  showDot?: boolean;
  /** Optional delay (in frames) before the entrance animation begins. */
  delay?: number;
};

/**
 * Reusable "360 GHAR" wordmark.
 * "360" is rendered in `color` (navy by default) followed by a terracotta
 * accent dot, then "GHAR" in the same `color`. The whole mark springs in
 * with a subtle fade for a clean entrance.
 */
export const Wordmark: React.FC<WordmarkProps> = ({
  size = 120,
  color = palette.navy,
  showDot = true,
  delay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame,
    fps,
    delay,
    config: { damping: 200 },
  });

  const opacity = interpolate(progress, [0, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(progress, [0, 1], [24, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const fontFamily = typography.fontFamily;
  const fontWeight = 800;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: size * 0.04,
        opacity,
        transform: `translateY(${translateY}px)`,
        fontFamily,
        fontWeight,
        fontSize: size,
        lineHeight: 1,
        letterSpacing: "-0.02em",
        color,
      }}
    >
      <span>360</span>
      {showDot && (
        <span
          style={{
            color: palette.terracotta,
            fontSize: size * 0.42,
            lineHeight: 1,
            transform: `translateY(-${size * 0.18}px)`,
            display: "inline-block",
          }}
        >
          ●
        </span>
      )}
      <span style={{ marginLeft: size * 0.12 }}>GHAR</span>
    </div>
  );
};
