import React from "react";
import { Composition } from "remotion";
import { Video } from "./Video";

// 150 seconds * 30 fps = 4500 frames.
const DURATION_IN_FRAMES = 4500;
const FPS = 30;
const WIDTH = 1920;
const HEIGHT = 1080;

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Video"
      component={Video}
      durationInFrames={DURATION_IN_FRAMES}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
  );
};
