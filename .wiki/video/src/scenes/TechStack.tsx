import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { palette, typography } from "../theme";
import { Caption } from "../components/Caption";
import { Wordmark } from "../components/Wordmark";

type Badge = { label: string; color: string };

const BADGES: Badge[] = [
  { label: "FastAPI", color: palette.terracotta },
  { label: "PostgreSQL + PostGIS", color: palette.navy },
  { label: "Redis", color: palette.terracotta },
  { label: "pgvector", color: palette.navy },
  { label: "Supabase Auth", color: palette.terracotta },
  { label: "MCP", color: palette.navy },
];

/**
 * Scene 8 (18s) — Tech Stack + Outro.
 * Tech badges animate in, then the 360 GHAR wordmark reappears with the
 * repo URL as a closing caption. Navy background, terracotta accents.
 */
export const TechStack: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const titleProgress = spring({
    frame,
    fps,
    delay: fps * 0.2,
    config: { damping: 200 },
  });
  const titleOpacity = interpolate(titleProgress, [0, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Badges section fades out as outro fades in.
  const badgesOut = interpolate(
    frame,
    [fps * 9, fps * 10.5],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const outroIn = interpolate(
    frame,
    [fps * 9.5, fps * 11],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const exitOpacity = interpolate(
    frame,
    [durationInFrames - fps, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.navy,
        opacity: exitOpacity,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 48,
        padding: 60,
      }}
    >
      {/* Tech stack section */}
      <div
        style={{
          opacity: titleOpacity * badgesOut,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 40,
          position: "absolute",
        }}
      >
        <div
          style={{
            color: palette.white,
            fontFamily: typography.fontFamily,
            fontSize: typography.title,
            fontWeight: 800,
            letterSpacing: "-0.02em",
          }}
        >
          Built on a modern stack
        </div>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "center",
            gap: 20,
            maxWidth: 1300,
          }}
        >
          {BADGES.map((b, i) => {
            const p = spring({
              frame,
              fps,
              delay: fps * (0.8 + i * 0.3),
              config: { damping: 18, stiffness: 140 },
            });
            const opacity = interpolate(p, [0, 1], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const scale = interpolate(p, [0, 1], [0.7, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div
                key={b.label}
                style={{
                  opacity,
                  transform: `scale(${scale})`,
                  background: palette.white,
                  color: b.color,
                  fontFamily: typography.fontFamily,
                  fontSize: 30,
                  fontWeight: 800,
                  padding: "14px 28px",
                  borderRadius: 999,
                  border: `2px solid ${b.color}`,
                  boxShadow: "0 12px 30px rgba(0,0,0,0.25)",
                }}
              >
                {b.label}
              </div>
            );
          })}
        </div>

        <Caption
          text="Async-first  •  TypeScript-safe APIs  •  Vector search  •  MCP-native"
          color={palette.white}
          size={typography.captionSmall}
          delay={fps * 4}
          maxWidth={1300}
        />
      </div>

      {/* Outro section */}
      <div
        style={{
          opacity: outroIn,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 32,
        }}
      >
        <Wordmark size={170} color={palette.white} delay={fps * 9.8} />

        <div
          style={{
            color: palette.sand,
            fontFamily: typography.fontFamily,
            fontSize: typography.subtitle,
            fontWeight: 600,
            opacity: interpolate(outroIn, [0, 1], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          One backend. Six modules.
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "14px 28px",
            borderRadius: 999,
            border: `2px solid ${palette.terracotta}`,
            color: palette.white,
            fontFamily: typography.fontFamily,
            fontSize: typography.tagline,
            fontWeight: 700,
            opacity: interpolate(outroIn, [0, 1], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          <span style={{ color: palette.terracotta }}>›</span>
          github.com/360ghar/360ghar-backend
        </div>
      </div>
    </AbsoluteFill>
  );
};
