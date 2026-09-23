import React, { useEffect, useMemo, useState } from "react";
import {
  AbsoluteFill,
  Audio,
  CalculateMetadataFunction,
  OffthreadVideo,
  Img,
  Sequence,
  useVideoConfig,
  staticFile,
} from "remotion";
import { TikTokCaptions } from "./TikTokCaptions";
import {
  calculateShotTimingRanges,
  ShortsCompositionProps,
} from "./ShortsComposition";

/**
 * Load props from remotion_props.json for Studio mode.
 * Duplicated locally because ShortsComposition's loadStudioProps is not exported.
 */
const loadStudioProps = async (): Promise<ShortsCompositionProps> => {
  try {
    const response = await fetch(staticFile("remotion_props.json"));
    if (response.ok) {
      const data = await response.json();
      let timing = data.timing || [];
      if (!timing || timing.length === 0) {
        try {
          const timingRes = await fetch(staticFile("timing.json"));
          if (timingRes.ok) {
            timing = await timingRes.json();
          }
        } catch {
          // optional fallback
        }
      }
      return {
        shots: data.shots || [],
        words: data.words || [],
        timing: timing,
        narrationSrc: data.narrationSrc || "project_assets/narration.mp3",
      };
    }
  } catch (e) {
    console.warn("Could not load remotion_props.json:", e);
  }
  return {
    shots: [],
    words: [],
    timing: [],
    narrationSrc: "project_assets/narration.mp3",
  };
};

/**
 * Props for LongFormComposition — reuses the same data contract as
 * ShortsComposition (shots, words, timing, narrationSrc).
 * All visual/sizing/layout differences are handled inside this component.
 */
export type LongFormCompositionProps = ShortsCompositionProps;

export const LongFormComposition: React.FC<LongFormCompositionProps> = ({
  shots: initialShots,
  words: initialWords,
  timing: initialTiming,
  narrationSrc: initialNarrationSrc,
}) => {
  const [props, setProps] = useState<ShortsCompositionProps>({
    shots: initialShots || [],
    words: initialWords || [],
    timing: initialTiming || [],
    narrationSrc: initialNarrationSrc || "project_assets/narration.mp3",
  });

  const { fps, durationInFrames: compositionDuration } = useVideoConfig();

  // Keep state synchronized if props change
  useEffect(() => {
    if (initialShots && initialShots.length > 0) {
      setProps({
        shots: initialShots,
        words: initialWords || [],
        timing: initialTiming || [],
        narrationSrc: initialNarrationSrc || "project_assets/narration.mp3",
      });
      return;
    }
    // Fallback: try to load props.json for Studio mode if not populated
    loadStudioProps().then((loaded) => {
      if (loaded.shots.length > 0) {
        setProps(loaded);
      }
    });
  }, [initialShots, initialWords, initialTiming, initialNarrationSrc]);

  const shots = props.shots;
  const words = props.words;
  const timing = props.timing;
  const narrationSrc = props.narrationSrc;

  const timingRanges = useMemo(() => {
    return calculateShotTimingRanges(shots, words, fps, timing);
  }, [shots, words, fps, timing]);

  // OVERLAP_FRAMES: each shot's Sequence starts this many frames before the
  // previous one ends. This ensures the incoming OffthreadVideo has already
  // decoded its first frame when the outgoing Sequence finishes, eliminating
  // the 1-frame black gap caused by OffthreadVideo's decode latency.
  const OVERLAP_FRAMES = 2;

  // Shot placement follows actual sentence start/end timings, including inter-sentence pauses
  const nominalCutFrames: number[] = useMemo(() => {
    if (shots.length === 0) return [];
    const cuts = shots.map((_, idx) => {
      if (idx === 0) return 0;
      return Math.round(timingRanges[idx].startSec * fps);
    });
    for (let i = 1; i < cuts.length; i++) {
      if (cuts[i] <= cuts[i - 1]) {
        cuts[i] = cuts[i - 1] + 1;
      }
    }
    return cuts;
  }, [shots, timingRanges, fps]);

  const nominalEndFrames: number[] = useMemo(() => {
    if (shots.length === 0) return [];
    return shots.map((_, idx) => {
      if (idx < shots.length - 1) {
        return nominalCutFrames[idx + 1];
      }
      const lastSentenceEndFrame = Math.ceil(timingRanges[idx].endSec * fps);
      return Math.max(
        nominalCutFrames[idx] + 30,
        compositionDuration || 0,
        lastSentenceEndFrame
      );
    });
  }, [shots, nominalCutFrames, timingRanges, compositionDuration, fps]);

  const sequencedShots = useMemo(() => {
    return shots.map((shot, idx) => {
      const nominalStart = nominalCutFrames[idx];
      const nominalEnd = nominalEndFrames[idx];

      const startFrame = idx === 0 ? 0 : Math.max(0, nominalStart - OVERLAP_FRAMES);
      const durationInFrames = Math.max(30, nominalEnd - startFrame);

      return {
        ...shot,
        startFrame,
        durationInFrames,
      };
    });
  }, [shots, nominalCutFrames, nominalEndFrames]);

  const resolvedNarrationSrc = narrationSrc.startsWith("http")
    ? narrationSrc
    : staticFile(narrationSrc);

  // Landscape 16:9 cinematic treatment — lighter than Shorts' dark filter:
  // subtle darkening, gentle contrast boost, slight desaturation for a
  // natural cinematic feel suitable for longer-form content.
  const LANDSCAPE_FILTER = "brightness(0.92) contrast(1.05) saturate(0.88)";

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", fontFamily: "sans-serif", overflow: "hidden" }}>
      {/* Media layer with light cinematic treatment */}
      <AbsoluteFill style={{ filter: LANDSCAPE_FILTER }}>
        {/* Background Pexels Videos/Photos sequenced per sentence */}
        {sequencedShots.map((shot, idx) => {
          const assetUrl = shot.asset_path ? staticFile(shot.asset_path) : "";
          return (
            <Sequence
              key={idx}
              from={shot.startFrame}
              durationInFrames={shot.durationInFrames}
            >
              <AbsoluteFill style={{ overflow: "hidden" }}>
                {shot.media_type === "video" && assetUrl ? (
                  <OffthreadVideo
                    src={assetUrl}
                    muted={true}
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "cover",
                    }}
                  />
                ) : assetUrl ? (
                  <Img
                    src={assetUrl}
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "cover",
                    }}
                  />
                ) : (
                  <AbsoluteFill
                    style={{
                      background: "linear-gradient(135deg, #1e293b, #0f172a)",
                      display: "flex",
                      justifyContent: "center",
                      alignItems: "center",
                      color: "#fff",
                      fontSize: 32,
                      padding: 40,
                      textAlign: "center",
                    }}
                  >
                    {shot.visual || shot.sentence}
                  </AbsoluteFill>
                )}
              </AbsoluteFill>
            </Sequence>
          );
        })}
      </AbsoluteFill>

      {/* Soft vignette overlay — draws focus to center with subtle edge darkening */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.25) 85%)",
          pointerEvents: "none",
        }}
      />

      {/* Subtle film grain / noise overlay at lower opacity for long-form comfort */}
      <AbsoluteFill
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='1' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
          backgroundSize: "200px 200px",
          opacity: 0.06,
          pointerEvents: "none",
          mixBlendMode: "overlay",
        }}
      />

      {/* Narration Audio */}
      {resolvedNarrationSrc && <Audio src={resolvedNarrationSrc} />}

      {/* Ambient Background Audio — subtle loop at lower volume for long-form comfort */}
      <Audio src={staticFile("sfx-ambient.mp3")} loop volume={0.08} />

      {/* Captions — positioned for 16:9 landscape (closer to bottom edge) */}
      <AbsoluteFill style={{ justifyContent: "flex-end", paddingBottom: 100, zIndex: 10 }}>
        <TikTokCaptions words={words} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/**
 * Derive the composition length from the actual shot plan.
 * Reuses the same duration logic as ShortsCompositionMetadata:
 * total frames from shot durations, extended to cover the full
 * WhisperX narration timeline (last word end timestamp).
 */
export const LongFormCompositionMetadata: CalculateMetadataFunction<LongFormCompositionProps> = async ({
  props: incomingProps,
}) => {
  const fps = 30;
  let activeProps = incomingProps;

  if (!activeProps.shots || activeProps.shots.length === 0) {
    const loaded = await loadStudioProps();
    if (loaded.shots && loaded.shots.length > 0) {
      activeProps = loaded;
    }
  }

  const shots = activeProps.shots || [];
  const words = activeProps.words || [];

  const totalFrames = shots.reduce((acc, shot) => {
    return acc + Math.max(30, Math.round((shot.duration_seconds || 3.0) * fps));
  }, 0);

  let minNarrationFrames = totalFrames;
  if (words.length > 0) {
    const lastWordEnd = words[words.length - 1].end;
    minNarrationFrames = Math.ceil(lastWordEnd * fps);
  }

  let lastShotEndFrames = 0;
  if (shots.length > 0) {
    const ranges = calculateShotTimingRanges(shots, words, fps, activeProps.timing);
    if (ranges.length > 0) {
      const lastTiming = ranges[ranges.length - 1];
      lastShotEndFrames = Math.ceil(lastTiming.endSec * fps);
    }
  }

  return {
    props: activeProps,
    durationInFrames: Math.max(totalFrames, minNarrationFrames, lastShotEndFrames, 30),
    fps,
  };
};
