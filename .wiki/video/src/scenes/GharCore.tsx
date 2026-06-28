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
import { PropertyCard } from "../components/PropertyCard";

/**
 * Scene 2 (18s) — 360 Ghar Core.
 * Three property cards swipe across, a map pin drops onto a stylized map,
 * and a caption highlights the core capabilities.
 */
export const GharCore: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  // Title spring.
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
  const titleTranslate = interpolate(titleProgress, [0, 1], [24, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Cards drift left-to-right to imply a swipe gesture.
  const swipeShift = interpolate(
    frame,
    [fps * 1.5, fps * 4.5],
    [120, -120],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Map pin drops.
  const pinProgress = spring({
    frame,
    fps,
    delay: fps * 2.5,
    config: { damping: 12, stiffness: 120 },
  });
  const pinY = interpolate(pinProgress, [0, 1], [-80, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const pinScale = interpolate(pinProgress, [0, 1], [0.4, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Pulse ring on the pin.
  const ringScale = interpolate(frame % (fps * 2), [0, fps * 2], [0.4, 2.2], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const ringOpacity = interpolate(frame % (fps * 2), [0, fps * 2], [0.7, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Exit fade.
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
      <div
        style={{
          opacity: titleOpacity,
          transform: `translateY(${titleTranslate}px)`,
          color: palette.white,
          fontFamily: typography.fontFamily,
          fontSize: typography.title,
          fontWeight: 800,
          letterSpacing: "-0.02em",
        }}
      >
        360 Ghar Core
      </div>

      <div
        style={{
          display: "flex",
          gap: 40,
          transform: `translateX(${swipeShift}px)`,
        }}
      >
        <PropertyCard
          title="3BHK Apartment"
          location="Koramangala, Bengaluru"
          price="₹1.4 Cr"
          tag="For Sale"
          delay={fps * 1}
          background={palette.white}
          width={320}
        />
        <PropertyCard
          title="2BHK Villa"
          location="Whitefield, Bengaluru"
          price="₹85,000/mo"
          tag="For Rent"
          delay={fps * 1.4}
          width={320}
        />
        <PropertyCard
          title="Studio Loft"
          location="Indiranagar, Bengaluru"
          price="₹45,000/mo"
          tag="Short Stay"
          delay={fps * 1.8}
          width={320}
        />
      </div>

      {/* Map with dropping pin */}
      <div
        style={{
          position: "relative",
          width: 540,
          height: 180,
          borderRadius: 16,
          background: `linear-gradient(135deg, ${palette.muted} 0%, ${palette.navy} 100%)`,
          border: `2px solid ${palette.terracotta}`,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 24,
            left: 24,
            color: palette.sand,
            fontSize: 18,
            fontWeight: 600,
            opacity: 0.7,
          }}
        >
          🗺  Bengaluru
        </div>
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: "58%",
            transform: `translate(-50%, ${pinY}px) scale(${pinScale})`,
          }}
        >
          <div
            style={{
              position: "absolute",
              left: "50%",
              top: "50%",
              width: 80,
              height: 80,
              marginLeft: -40,
              marginTop: -40,
              borderRadius: "50%",
              border: `3px solid ${palette.terracotta}`,
              transform: `scale(${ringScale})`,
              opacity: ringOpacity,
            }}
          />
          <div
            style={{
              fontSize: 56,
              color: palette.terracotta,
              filter: "drop-shadow(0 6px 8px rgba(0,0,0,0.4))",
            }}
          >
            📍
          </div>
        </div>
      </div>

      <Caption
        text="Swipe-based discovery  •  Geospatial search  •  Agent coordination  •  Visit scheduling"
        color={palette.white}
        size={typography.caption}
        delay={fps * 3.2}
        maxWidth={1400}
      />
    </AbsoluteFill>
  );
};
