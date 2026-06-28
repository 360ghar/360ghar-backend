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

/**
 * Scene 3 (18s) — 360 Stays.
 * A booking calendar grid animates in, with check-in/check-out markers
 * highlighting a date range.
 */
export const Stays: React.FC = () => {
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

  const gridProgress = spring({
    frame,
    fps,
    delay: fps * 0.8,
    config: { damping: 200 },
  });
  const gridOpacity = interpolate(gridProgress, [0, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const gridTranslate = interpolate(gridProgress, [0, 1], [30, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Highlight range: check-in (day 4) → check-out (day 10).
  const rangeProgress = interpolate(
    frame,
    [fps * 2, fps * 4],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const exitOpacity = interpolate(
    frame,
    [durationInFrames - fps, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const days = Array.from({ length: 21 }, (_, i) => i);
  const checkIn = 4;
  const checkOut = 10;
  const highlightedEnd = checkIn + Math.round((checkOut - checkIn) * rangeProgress);

  const cellSize = 56;
  const gap = 12;
  const cols = 7;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.sand,
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
          color: palette.ink,
          fontFamily: typography.fontFamily,
          fontSize: typography.title,
          fontWeight: 800,
          letterSpacing: "-0.02em",
        }}
      >
        360 Stays
      </div>

      <div
        style={{
          opacity: gridOpacity,
          transform: `translateY(${gridTranslate}px)`,
          background: palette.white,
          padding: 28,
          borderRadius: 20,
          boxShadow: "0 20px 50px rgba(15, 44, 74, 0.15)",
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${cols}, ${cellSize}px)`,
            gap,
            marginBottom: 12,
          }}
        >
          {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
            <div
              key={i}
              style={{
                width: cellSize,
                height: 24,
                color: palette.muted,
                fontSize: 16,
                fontWeight: 700,
                textAlign: "center",
                fontFamily: typography.fontFamily,
              }}
            >
              {d}
            </div>
          ))}
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${cols}, ${cellSize}px)`,
            gap,
          }}
        >
          {days.map((day) => {
            const inRange = day >= checkIn && day <= highlightedEnd;
            const isCheckIn = day === checkIn;
            const isCheckOut = day === checkOut && rangeProgress >= 1;
            return (
              <div
                key={day}
                style={{
                  width: cellSize,
                  height: cellSize,
                  borderRadius: 12,
                  background: isCheckIn || isCheckOut
                    ? palette.terracotta
                    : inRange
                      ? "rgba(199, 93, 59, 0.18)"
                      : "rgba(15, 44, 74, 0.05)",
                  color: isCheckIn || isCheckOut ? palette.white : palette.ink,
                  fontSize: 22,
                  fontWeight: 600,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: typography.fontFamily,
                  border: isCheckIn || isCheckOut
                    ? `2px solid ${palette.terracotta}`
                    : "none",
                }}
              >
                {day + 1}
              </div>
            );
          })}
        </div>
        <div
          style={{
            marginTop: 20,
            display: "flex",
            gap: 28,
            justifyContent: "center",
            fontFamily: typography.fontFamily,
            fontSize: 20,
            fontWeight: 600,
          }}
        >
          <span style={{ color: palette.terracotta }}>● Check-in</span>
          <span style={{ color: palette.navy }}>● Stay</span>
          <span style={{ color: palette.muted }}>● Check-out</span>
        </div>
      </div>

      <Caption
        text="Short-stay bookings  •  Dynamic pricing  •  Availability checks  •  Guest management"
        color={palette.ink}
        size={typography.caption}
        delay={fps * 3}
        maxWidth={1400}
      />
    </AbsoluteFill>
  );
};
