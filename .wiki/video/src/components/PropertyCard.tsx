import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { palette, typography } from "../theme";

export type PropertyCardProps = {
  title: string;
  location: string;
  price: string;
  /** Tag text shown on the card footer, e.g. "For Rent". */
  tag?: string;
  /** Frame delay before the card springs in. */
  delay?: number;
  /** Background color of the card body. */
  background?: string;
  /** Accent color for the price + tag. */
  accent?: string;
  /** Width in px. */
  width?: number;
};

/**
 * Animated property card used by the Ghar Core scene.
 * Springs up with a subtle scale and reveals price + tag in sequence.
 */
export const PropertyCard: React.FC<PropertyCardProps> = ({
  title,
  location,
  price,
  tag,
  delay = 0,
  background = palette.white,
  accent = palette.terracotta,
  width = 360,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({
    frame,
    fps,
    delay,
    config: { damping: 18, stiffness: 120 },
  });

  const scale = interpolate(enter, [0, 1], [0.85, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(enter, [0, 1], [40, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = interpolate(enter, [0, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const tagOpacity = interpolate(enter, [0.6, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const height = width * 0.72;
  const heroHeight = height * 0.56;

  return (
    <div
      style={{
        width,
        opacity,
        transform: `translateY(${translateY}px) scale(${scale})`,
        background,
        borderRadius: 20,
        overflow: "hidden",
        boxShadow: "0 24px 60px rgba(15, 44, 74, 0.22)",
        fontFamily: typography.fontFamily,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          height: heroHeight,
          background: `linear-gradient(135deg, ${palette.navy} 0%, ${palette.muted} 100%)`,
          position: "relative",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 16,
            left: 16,
            color: accent,
            fontSize: 18,
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            opacity: tagOpacity,
          }}
        >
          {tag ?? ""}
        </div>
        <div
          style={{
            position: "absolute",
            bottom: 14,
            right: 16,
            color: palette.white,
            fontSize: 22,
            fontWeight: 700,
          }}
        >
          ◉ 360°
        </div>
      </div>
      <div style={{ padding: 20, flex: 1, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <div>
          <div
            style={{
              color: palette.ink,
              fontSize: 24,
              fontWeight: 700,
              marginBottom: 6,
            }}
          >
            {title}
          </div>
          <div style={{ color: palette.muted, fontSize: 18 }}>{location}</div>
        </div>
        <div
          style={{
            color: accent,
            fontSize: 26,
            fontWeight: 800,
            marginTop: 12,
            opacity: tagOpacity,
          }}
        >
          {price}
        </div>
      </div>
    </div>
  );
};
