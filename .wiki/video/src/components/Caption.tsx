import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { palette, smoothSpring, typography } from "../theme";

export type CaptionProps = {
  text: string;
  color?: string;
  size?: number;
  /** Frame delay before the fade-in begins. */
  delay?: number;
  /** Optional max width in px for wrapping long captions. */
  maxWidth?: number;
  /** Text alignment. */
  align?: "left" | "center" | "right";
  weight?: number;
};

/**
 * Reusable animated caption. Fades and rises into place with a smooth spring.
 */
export const Caption: React.FC<CaptionProps> = ({
  text,
  color = palette.ink,
  size = typography.caption,
  delay = 0,
  maxWidth,
  align = "center",
  weight = 600,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame,
    fps,
    delay,
    config: smoothSpring,
  });

  const opacity = interpolate(progress, [0, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(progress, [0, 1], [16, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${translateY}px)`,
        color,
        fontFamily: typography.fontFamily,
        fontSize: size,
        fontWeight: weight,
        lineHeight: 1.35,
        textAlign: align,
        maxWidth,
        margin: align === "center" ? "0 auto" : undefined,
        letterSpacing: "-0.01em",
      }}
    >
      {text}
    </div>
  );
};
