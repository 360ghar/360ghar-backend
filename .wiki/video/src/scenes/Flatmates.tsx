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

type Profile = {
  name: string;
  age: number;
  role: string;
  x: number;
};

const PROFILES: Profile[] = [
  { name: "Aarav", age: 26, role: "Seeker", x: -260 },
  { name: "Diya", age: 24, role: "Poster", x: 260 },
];

/**
 * Scene 4 (18s) — 360 Flatmates.
 * Two profile cards slide in from opposite sides, a match line draws
 * between them, and chat bubbles animate upward.
 */
export const Flatmates: React.FC = () => {
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

  // Cards slide in from the sides.
  const cardEnter = spring({
    frame,
    fps,
    delay: fps * 0.6,
    config: { damping: 18, stiffness: 120 },
  });
  const cardShift = interpolate(cardEnter, [0, 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Match line draws.
  const lineProgress = interpolate(
    frame,
    [fps * 1.8, fps * 3.2],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // "It's a match!" badge.
  const matchBadgeProgress = spring({
    frame,
    fps,
    delay: fps * 3.2,
    config: { damping: 14, stiffness: 200 },
  });
  const matchBadgeScale = interpolate(matchBadgeProgress, [0, 1], [0.3, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Chat bubbles appear in sequence.
  const bubbles = [
    { text: "Hey! Is the room still available?", delay: fps * 4, side: "left" as const },
    { text: "Yes! Want to schedule a visit?", delay: fps * 5, side: "right" as const },
    { text: "Absolutely — Saturday works?", delay: fps * 6, side: "left" as const },
  ];

  const exitOpacity = interpolate(
    frame,
    [durationInFrames - fps, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const cardSize = 320;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.navy,
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
          color: palette.white,
          fontFamily: typography.fontFamily,
          fontSize: typography.title,
          fontWeight: 800,
          letterSpacing: "-0.02em",
        }}
      >
        360 Flatmates
      </div>

      <div
        style={{
          position: "relative",
          width: 900,
          height: cardSize,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {PROFILES.map((p, i) => (
          <div
            key={p.name}
            style={{
              position: "absolute",
              left: "50%",
              transform: `translateX(calc(-50% + ${p.x * cardShift}px))`,
              width: cardSize,
              background: palette.white,
              borderRadius: 24,
              padding: 24,
              textAlign: "center",
              fontFamily: typography.fontFamily,
              boxShadow: "0 20px 50px rgba(0,0,0,0.35)",
            }}
          >
            <div
              style={{
                width: 120,
                height: 120,
                borderRadius: "50%",
                margin: "0 auto 16px",
                background: `linear-gradient(135deg, ${palette.terracotta}, ${palette.muted})`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: palette.white,
                fontSize: 52,
                fontWeight: 800,
              }}
            >
              {p.name[0]}
            </div>
            <div style={{ color: palette.ink, fontSize: 30, fontWeight: 700 }}>
              {p.name}, {p.age}
            </div>
            <div style={{ color: palette.muted, fontSize: 20, marginTop: 4 }}>
              {p.role}
            </div>
          </div>
        ))}

        {/* Match line */}
        <svg
          width={600}
          height={4}
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            overflow: "visible",
          }}
        >
          <line
            x1={-300}
            y1={2}
            x2={300}
            y2={2}
            stroke={palette.terracotta}
            strokeWidth={4}
            strokeDasharray={600}
            strokeDashoffset={600 * (1 - lineProgress)}
          />
        </svg>

        {/* Match badge */}
        <div
          style={{
            position: "absolute",
            top: -36,
            left: "50%",
            transform: `translate(-50%, 0) scale(${matchBadgeScale})`,
            background: palette.terracotta,
            color: palette.white,
            fontFamily: typography.fontFamily,
            fontSize: 28,
            fontWeight: 800,
            padding: "10px 24px",
            borderRadius: 999,
            letterSpacing: "0.04em",
            boxShadow: "0 12px 30px rgba(199, 93, 59, 0.5)",
          }}
        >
          ✦ It's a Match!
        </div>
      </div>

      {/* Chat bubbles */}
      <div
        style={{
          width: 800,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          marginTop: 8,
        }}
      >
        {bubbles.map((b, i) => {
          const p = spring({
            frame,
            fps,
            delay: b.delay,
            config: { damping: 200 },
          });
          const op = interpolate(p, [0, 1], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const ty = interpolate(p, [0, 1], [14, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const isLeft = b.side === "left";
          return (
            <div
              key={i}
              style={{
                opacity: op,
                transform: `translateY(${ty}px)`,
                alignSelf: isLeft ? "flex-start" : "flex-end",
                background: isLeft ? palette.sand : palette.terracotta,
                color: isLeft ? palette.ink : palette.white,
                fontFamily: typography.fontFamily,
                fontSize: 22,
                fontWeight: 500,
                padding: "12px 20px",
                borderRadius: 18,
                borderBottomLeftRadius: isLeft ? 4 : 18,
                borderBottomRightRadius: isLeft ? 18 : 4,
                maxWidth: 460,
              }}
            >
              {b.text}
            </div>
          );
        })}
      </div>

      <Caption
        text="Swipe matching  •  Conversations  •  Moderation  •  SSE real-time"
        color={palette.white}
        size={typography.caption}
        delay={fps * 4.5}
        maxWidth={1400}
      />
    </AbsoluteFill>
  );
};
