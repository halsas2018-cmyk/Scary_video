import React from "react";
import { Composition } from "remotion";
import { ShortsComposition, ShortsCompositionMetadata } from "./ShortsComposition";

/**
 * Root component for the Remotion video pipeline.
 *
 * In Studio mode, props.json should be loaded from public/remotion_props.json
 * Make sure your pipeline generates this file!
 */
export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Main Shorts Composition */}
      <Composition
        id="ShortsComposition"
        component={ShortsComposition}
        durationInFrames={1200}
        fps={30}
        width={1080}
        height={1920}
        calculateMetadata={ShortsCompositionMetadata}
        defaultProps={{
          shots: [],
          words: [],
          narrationSrc: "project_assets/narration.mp3",
        }}
      />
    </>
  );
};

export { ShortsComposition, ShortsCompositionMetadata };