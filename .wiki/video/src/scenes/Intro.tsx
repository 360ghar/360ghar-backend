import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { palette, typography } from "../theme";
import { Wordmark } from "../components/Wordmark";

/**
 * Scene 1 (12s) — Intro.
 * Fades from a sand background, reveals the "360 GHAR" wordmark,
 * a subtitle, and a tagline. The wordmark lingers, then everything
 * subtly drifts up and fades out as the scene ends.
 */
export const Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  // Background fade-in from sand.
  const bgOpacity = interpolate(frame, [0, fps], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Subtitle + tagline springs.
  const subtitleProgress = spring({
    frame,
    fps,
    delay: fps * 0.9,
    config: { damping: 200 },
  });
  const taglineProgress = spring({
    frame,
    fps,
    delay: fps * 1.5,
    config: { damping: 200 },
  });

  // Exit: lift + fade in the last second.
  const exitStart = durationInFrames - fps;
  const exitOpacity = interpolate(frame, [exitStart, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const exitTranslate = interpolate(frame, [exitStart, durationInFrames], [0, -24], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.sand,
        opacity: bgOpacity * exitOpacity,
        transform: `translateY(${exitTranslate}px)`,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 28,
      }}
    >
      <Wordmark size={160} color={palette.navy} delay={fps * 0.4} />

      <div
        style={{
          opacity: interpolate(subtitleProgress, [0, 1], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          transform: `translateY(${interpolate(subtitleProgress, [0, 1], [16, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })}px)`,
          color: palette.ink,
          fontFamily: typography.fontFamily,
          fontSize: typography.subtitle,
          fontWeight: 600,
          letterSpacing: "-0.01em",
        }}
      >
        Unified real estate platform
      </div>

      <div
        style={{
          opacity: interpolate(taglineProgress, [0, 1], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          transform: `translateY(${interpolate(taglineProgress, [0, 1], [16, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })}px)`,
          color: palette.terracotta,
          fontFamily: typography.fontFamily,
          fontSize: typography.tagline,
          fontWeight: 700,
          letterSpacing: "0.02em",
        }}
      >
        One backend. Six modules.
      </div>
    </AbsoluteFill>
  );
};
