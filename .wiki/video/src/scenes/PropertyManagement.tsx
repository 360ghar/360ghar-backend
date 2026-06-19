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

type Stage = {
  label: string;
  icon: string;
};

const STAGES: Stage[] = [
  { label: "Lease", icon: "📄" },
  { label: "Rent", icon: "💳" },
  { label: "Maintenance", icon: "🔧" },
  { label: "Documents", icon: "📁" },
];

/**
 * Scene 5 (18s) — Property Management.
 * A horizontal pipeline of stage cards (Lease → Rent → Maintenance → Documents)
 * lights up left-to-right with a flowing connector.
 */
export const PropertyManagement: React.FC = () => {
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

  // Each stage lights up in sequence.
  const stageStarts = STAGES.map((_, i) => fps * (1 + i * 0.8));
  const connectorProgress = interpolate(
    frame,
    [fps * 1, fps * 5],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // A "data packet" travels along the connector.
  const packetX = interpolate(frame, [fps * 1.2, fps * 5], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const exitOpacity = interpolate(
    frame,
    [durationInFrames - fps, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const cardW = 220;
  const cardH = 240;
  const gap = 60;
  const totalW = STAGES.length * cardW + (STAGES.length - 1) * gap;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.sand,
        opacity: exitOpacity,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 56,
        padding: 60,
      }}
    >
      <div
        style={{
          opacity: titleOpacity,
          color: palette.ink,
          fontFamily: typography.fontFamily,
          fontSize: typography.title,
          fontWeight: 800,
          letterSpacing: "-0.02em",
        }}
      >
        Property Management
      </div>

      <div
        style={{
          position: "relative",
          width: totalW,
          height: cardH,
        }}
      >
        {/* Connector line */}
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: 0,
            right: 0,
            height: 6,
            background: "rgba(15, 44, 74, 0.12)",
            borderRadius: 3,
            transform: "translateY(-50%)",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: 0,
            height: 6,
            width: `${connectorProgress * 100}%`,
            background: palette.terracotta,
            borderRadius: 3,
            transform: "translateY(-50%)",
          }}
        />
        {/* Traveling packet */}
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: `${packetX * 100}%`,
            transform: "translate(-50%, -50%)",
            width: 18,
            height: 18,
            borderRadius: "50%",
            background: palette.navy,
            boxShadow: `0 0 0 6px rgba(15, 44, 74, 0.18)`,
          }}
        />

        {STAGES.map((stage, i) => {
          const start = stageStarts[i];
          const active = frame >= start;
          const p = spring({
            frame,
            fps,
            delay: start,
            config: { damping: 18, stiffness: 140 },
          });
          const scale = interpolate(p, [0, 1], [0.85, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const opacity = interpolate(p, [0, 1], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const left = i * (cardW + gap);
          return (
            <div
              key={stage.label}
              style={{
                position: "absolute",
                left,
                top: 0,
                width: cardW,
                height: cardH,
                opacity,
                transform: `scale(${scale})`,
                background: active ? palette.white : "rgba(255,255,255,0.5)",
                borderRadius: 20,
                border: active
                  ? `2px solid ${palette.terracotta}`
                  : `2px solid rgba(15, 44, 74, 0.1)`,
                boxShadow: active
                  ? "0 20px 50px rgba(15, 44, 74, 0.2)"
                  : "none",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 14,
                fontFamily: typography.fontFamily,
              }}
            >
              <div style={{ fontSize: 64 }}>{stage.icon}</div>
              <div
                style={{
                  color: active ? palette.ink : palette.muted,
                  fontSize: 28,
                  fontWeight: 700,
                }}
              >
                {stage.label}
              </div>
              <div
                style={{
                  width: 12,
                  height: 12,
                  borderRadius: "50%",
                  background: active ? palette.terracotta : "rgba(15,44,74,0.2)",
                }}
              />
            </div>
          );
        })}
      </div>

      <Caption
        text="Lease lifecycle  •  Rent collection  •  Maintenance work orders  •  Financial reports"
        color={palette.ink}
        size={typography.caption}
        delay={fps * 5}
        maxWidth={1500}
      />
    </AbsoluteFill>
  );
};
