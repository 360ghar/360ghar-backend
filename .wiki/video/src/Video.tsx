import React from "react";
import { Series } from "remotion";
import { Intro } from "./scenes/Intro";
import { GharCore } from "./scenes/GharCore";
import { Stays } from "./scenes/Stays";
import { Flatmates } from "./scenes/Flatmates";
import { PropertyManagement } from "./scenes/PropertyManagement";
import { VirtualTours } from "./scenes/VirtualTours";
import { DataHub } from "./scenes/DataHub";
import { TechStack } from "./scenes/TechStack";

// Scene durations in frames (30fps).
const INTRO = 12 * 30; // 360
const SCENE = 18 * 30; // 540 each
const OUTRO = 30 * 30; // 900 — tech stack + outro gets extra time for the closing wordmark
// Total: 360 + 6 * 540 + 900 = 4500 frames (150s) — fills the composition exactly.

export const Video: React.FC = () => {
  return (
    <Series>
      <Series.Sequence durationInFrames={INTRO}>
        <Intro />
      </Series.Sequence>
      <Series.Sequence durationInFrames={SCENE}>
        <GharCore />
      </Series.Sequence>
      <Series.Sequence durationInFrames={SCENE}>
        <Stays />
      </Series.Sequence>
      <Series.Sequence durationInFrames={SCENE}>
        <Flatmates />
      </Series.Sequence>
      <Series.Sequence durationInFrames={SCENE}>
        <PropertyManagement />
      </Series.Sequence>
      <Series.Sequence durationInFrames={SCENE}>
        <VirtualTours />
      </Series.Sequence>
      <Series.Sequence durationInFrames={SCENE}>
        <DataHub />
      </Series.Sequence>
      <Series.Sequence durationInFrames={OUTRO}>
        <TechStack />
      </Series.Sequence>
    </Series>
  );
};
