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

type Source = { label: string; icon: string };

const SOURCES: Source[] = [
  { label: "RERA", icon: "🏛" },
  { label: "Bank Auctions", icon: "🏦" },
  { label: "Circle Rates", icon: "💰" },
  { label: "Gazette", icon: "📰" },
  { label: "Jamabandi", icon: "📋" },
  { label: "Zoning", icon: "📐" },
];

/**
 * Scene 7 (18s) — 360 Data Hub.
 * A grid of data source cards lights up, with data streams flowing
 * down into a central dashboard that fills up with metric bars.
 */
export const DataHub: React.FC = () => {
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

  const exitOpacity = interpolate(
    frame,
    [durationInFrames - fps, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const cardW = 200;
  const cardH = 130;
  const gap = 24;
  const cols = 3;

  // Dashboard fill bars.
  const dashFill = interpolate(frame, [fps * 4, fps * 7], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const dashMetrics = [
    { label: "Records", value: 1.2, suffix: "M+" },
    { label: "Scrapers", value: 0.95, suffix: "26" },
    { label: "Alerts", value: 0.7, suffix: "Live" },
  ];

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.sand,
        opacity: exitOpacity,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
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
        360 Data Hub
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 60 }}>
        {/* Source grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${cols}, ${cardW}px)`,
            gap,
          }}
        >
          {SOURCES.map((s, i) => {
            const start = fps * (0.8 + i * 0.3);
            const p = spring({
              frame,
              fps,
              delay: start,
              config: { damping: 18, stiffness: 140 },
            });
            const opacity = interpolate(p, [0, 1], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const scale = interpolate(p, [0, 1], [0.85, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            // Flowing dot indicator.
            const flowActive = frame >= start + fps * 0.5;
            const flowY = interpolate(
              (frame - start) % (fps * 1.2),
              [0, fps * 1.2],
              [0, 60],
              { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
            );
            return (
              <div
                key={s.label}
                style={{
                  width: cardW,
                  height: cardH,
                  opacity,
                  transform: `scale(${scale})`,
                  background: palette.white,
                  borderRadius: 16,
                  border: `1px solid rgba(15, 44, 74, 0.1)`,
                  boxShadow: "0 10px 24px rgba(15, 44, 74, 0.1)",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 8,
                  fontFamily: typography.fontFamily,
                  position: "relative",
                  overflow: "visible",
                }}
              >
                <div style={{ fontSize: 36 }}>{s.icon}</div>
                <div style={{ color: palette.ink, fontSize: 20, fontWeight: 700 }}>
                  {s.label}
                </div>
                {flowActive && (
                  <div
                    style={{
                      position: "absolute",
                      bottom: -8,
                      left: "50%",
                      transform: `translate(-50%, ${flowY}px)`,
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      background: palette.terracotta,
                      opacity: 0.8,
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Flow connector */}
        <svg width={120} height={400} viewBox="0 0 120 400">
          <path
            d="M 0 200 C 40 200, 80 200, 120 200"
            stroke={palette.terracotta}
            strokeWidth={4}
            fill="none"
            strokeDasharray="8 8"
          />
        </svg>

        {/* Dashboard */}
        <div
          style={{
            width: 360,
            background: palette.navy,
            borderRadius: 20,
            padding: 28,
            color: palette.white,
            fontFamily: typography.fontFamily,
            boxShadow: "0 24px 60px rgba(15, 44, 74, 0.3)",
          }}
        >
          <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 20 }}>
            📊 Dashboard
          </div>
          {dashMetrics.map((m) => (
            <div key={m.label} style={{ marginBottom: 20 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 16,
                  marginBottom: 6,
                  color: palette.sand,
                }}
              >
                <span>{m.label}</span>
                <span style={{ fontWeight: 700 }}>{m.suffix}</span>
              </div>
              <div
                style={{
                  height: 10,
                  background: "rgba(255,255,255,0.12)",
                  borderRadius: 5,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${m.value * dashFill * 100}%`,
                    height: "100%",
                    background: palette.terracotta,
                    borderRadius: 5,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <Caption
        text="26 scrapers  •  6 data categories  •  Scheduled aggregation  •  Alerts"
        color={palette.ink}
        size={typography.caption}
        delay={fps * 5}
        maxWidth={1500}
      />
    </AbsoluteFill>
  );
};
