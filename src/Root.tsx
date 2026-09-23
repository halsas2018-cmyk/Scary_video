import React from "react";
import { Composition } from "remotion";
import { ShortsComposition, ShortsCompositionMetadata } from "./ShortsComposition";
import { LongFormComposition, LongFormCompositionMetadata } from "./LongFormComposition";

/**
 * Root component for the Remotion video pipeline.
 *
 * In Studio mode, props.json should be loaded from public/remotion_props.json
 * Make sure your pipeline generates this file!
 */
export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Main Shorts Composition — 9:16 vertical video */}
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
          timing: [],
          narrationSrc: "project_assets/narration.mp3",
        }}
      />

      {/* Long-form Composition — 16:9 landscape video */}
      <Composition
        id="LongFormComposition"
        component={LongFormComposition}
        durationInFrames={5400}
        fps={30}
        width={1920}
        height={1080}
        calculateMetadata={LongFormCompositionMetadata}
        defaultProps={{
          shots: [],
          words: [],
          timing: [],
          narrationSrc: "project_assets/narration.mp3",
        }}
      />
    </>
  );
};

export { ShortsComposition, ShortsCompositionMetadata };
export { LongFormComposition, LongFormCompositionMetadata };