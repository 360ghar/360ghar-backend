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

type Hotspot = { x: number; y: number; label: string };

const HOTSPOTS: Hotspot[] = [
  { x: 32, y: 38, label: "Living Room" },
  { x: 68, y: 30, label: "Kitchen" },
  { x: 50, y: 65, label: "Balcony" },
  { x: 78, y: 70, label: "Bedroom" },
  { x: 22, y: 72, label: "Entrance" },
];

/**
 * Scene 6 (18s) — 360 Virtual Tours.
 * A 360 scene with hotspot pins appearing one-by-one, plus an AI spark
 * animation indicating AI hotspot generation.
 */
export const VirtualTours: React.FC = () => {
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

  const sceneProgress = spring({
    frame,
    fps,
    delay: fps * 0.5,
    config: { damping: 200 },
  });
  const sceneScale = interpolate(sceneProgress, [0, 1], [0.9, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const sceneOpacity = interpolate(sceneProgress, [0, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // AI spark orbiting the scene.
  const sparkAngle = (frame / fps) * 90;
  const sparkRadius = 220;
  const sparkX = Math.cos((sparkAngle * Math.PI) / 180) * sparkRadius;
  const sparkY = Math.sin((sparkAngle * Math.PI) / 180) * sparkRadius * 0.4;
  const sparkOpacity = interpolate(
    frame,
    [fps * 2, fps * 3, fps * 7, fps * 8],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const exitOpacity = interpolate(
    frame,
    [durationInFrames - fps, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const sceneW = 900;
  const sceneH = 420;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.navy,
        opacity: exitOpacity,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 40,
        padding: 60,
      }}
    >
      <div
        style={{
          opacity: titleOpacity,
          color: palette.white,
          fontFamily: typography.fontFamily,
          fontSize: typography.title,
          fontWeight: 800,
          letterSpacing: "-0.02em",
        }}
      >
        360 Virtual Tours
      </div>

      <div
        style={{
          position: "relative",
          width: sceneW,
          height: sceneH,
          opacity: sceneOpacity,
          transform: `scale(${sceneScale})`,
          borderRadius: 24,
          overflow: "hidden",
          background: `linear-gradient(135deg, ${palette.muted} 0%, ${palette.navy} 60%, ${palette.ink} 100%)`,
          border: `2px solid ${palette.terracotta}`,
        }}
      >
        {/* Stylized room interior */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage: `
              linear-gradient(180deg, rgba(232, 220, 196, 0.18) 0%, rgba(15, 44, 74, 0.6) 100%),
              radial-gradient(circle at 30% 40%, rgba(232, 220, 196, 0.3) 0%, transparent 40%),
              radial-gradient(circle at 70% 60%, rgba(199, 93, 59, 0.18) 0%, transparent 45%)
            `,
          }}
        />
        {/* Floor */}
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: "40%",
            background: `linear-gradient(180deg, rgba(26, 26, 26, 0) 0%, rgba(26, 26, 26, 0.5) 100%)`,
          }}
        />

        {/* Hotspots */}
        {HOTSPOTS.map((h, i) => {
          const start = fps * (1.2 + i * 0.55);
          const p = spring({
            frame,
            fps,
            delay: start,
            config: { damping: 12, stiffness: 160 },
          });
          const scale = interpolate(p, [0, 1], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const labelOpacity = interpolate(p, [0.5, 1], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          // Pulse.
          const pulse = interpolate(
            (frame - start + fps * 2) % (fps * 2),
            [0, fps * 2],
            [0.6, 1.6],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          );
          return (
            <div
              key={h.label}
              style={{
                position: "absolute",
                left: `${h.x}%`,
                top: `${h.y}%`,
                transform: `translate(-50%, -50%) scale(${scale})`,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 6,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  width: 36,
                  height: 36,
                  borderRadius: "50%",
                  border: `2px solid ${palette.terracotta}`,
                  transform: `scale(${pulse})`,
                  opacity: labelOpacity * 0.7,
                }}
              />
              <div
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: "50%",
                  background: palette.terracotta,
                  boxShadow: `0 0 0 4px rgba(199, 93, 59, 0.3)`,
                }}
              />
              <div
                style={{
                  opacity: labelOpacity,
                  background: palette.sand,
                  color: palette.ink,
                  fontFamily: typography.fontFamily,
                  fontSize: 16,
                  fontWeight: 700,
                  padding: "4px 10px",
                  borderRadius: 10,
                  whiteSpace: "nowrap",
                }}
              >
                {h.label}
              </div>
            </div>
          );
        })}

        {/* AI spark */}
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: "50%",
            transform: `translate(calc(-50% + ${sparkX}px), calc(-50% + ${sparkY}px))`,
            opacity: sparkOpacity,
            display: "flex",
            alignItems: "center",
            gap: 10,
            background: "rgba(15, 44, 74, 0.85)",
            border: `1px solid ${palette.terracotta}`,
            color: palette.white,
            fontFamily: typography.fontFamily,
            fontSize: 18,
            fontWeight: 700,
            padding: "8px 16px",
            borderRadius: 999,
          }}
        >
          ✦ AI hotspot generation
        </div>
      </div>

      <Caption
        text="360° scenes  •  AI hotspot generation  •  Floor plans  •  Custom domains  •  Analytics"
        color={palette.white}
        size={typography.caption}
        delay={fps * 4}
        maxWidth={1500}
      />
    </AbsoluteFill>
  );
};
