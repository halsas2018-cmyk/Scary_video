import React, { useEffect, useState } from "react";
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

export interface ShotAsset {
  sentence: string;
  search_term: string;
  media_type: "video" | "photo";
  visual: string;
  asset_path?: string; // relative path under public/, e.g. "project_assets/shot_1.mp4"
  duration_seconds: number;
}

type Props = {
  shots: ShotAsset[];
  words: { word: string; start: number; end: number }[];
  narrationSrc: string;
};

/**
 * Load props from remotion_props.json for Studio mode
 */
const loadStudioProps = async (): Promise<Props> => {
  try {
    const response = await fetch(staticFile("remotion_props.json"));
    if (response.ok) {
      const data = await response.json();
      return {
        shots: data.shots || [],
        words: data.words || [],
        narrationSrc: data.narrationSrc || "project_assets/narration.mp3",
      };
    }
  } catch (e) {
    console.warn("Could not load remotion_props.json:", e);
  }
  return {
    shots: [],
    words: [],
    narrationSrc: "project_assets/narration.mp3",
  };
};

// NOTE: declared as a `type` (not `interface`) so it satisfies the
// `Record<string, unknown>` constraint required by Remotion's
// CalculateMetadataFunction / LooseComponentType, matching the pattern
// used by MotionGraphicsVideoProps. An `interface` lacks an implicit index
// signature and triggers a type error at the <Composition> registration.
export type ShortsCompositionProps = {
  shots: ShotAsset[];
  words: { word: string; start: number; end: number }[];
  narrationSrc: string; // e.g. "project_assets/narration.mp3"
};

export const ShortsComposition: React.FC<ShortsCompositionProps> = ({
  shots: initialShots,
  words: initialWords,
  narrationSrc: initialNarrationSrc,
}) => {
  const [props, setProps] = useState<Props>({
    shots: initialShots || [],
    words: initialWords || [],
    narrationSrc: initialNarrationSrc || "project_assets/narration.mp3",
  });

  const { fps } = useVideoConfig();

  // Keep state synchronized if props change (e.g. passed from calculateMetadata or CLI)
  useEffect(() => {
    if (initialShots && initialShots.length > 0) {
      setProps({
        shots: initialShots,
        words: initialWords || [],
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
  }, [initialShots, initialWords, initialNarrationSrc]);

  const shots = props.shots;
  const words = props.words;
  const narrationSrc = props.narrationSrc;

  // OVERLAP_FRAMES: each shot's Sequence starts this many frames before the
  // previous one ends. This ensures the incoming OffthreadVideo has already
  // decoded its first frame when the outgoing Sequence finishes, eliminating
  // the 1-frame black gap caused by OffthreadVideo's decode latency.
  // We extend each shot's durationInFrames by the same amount so the video
  // content timing is preserved; only the Sequence boundary shifts.
  const OVERLAP_FRAMES = 2;

  let currentFrame = 0;
  const sequencedShots = shots.map((shot, idx) => {
    const durationInFrames = Math.max(30, Math.round((shot.duration_seconds || 3.0) * fps));
    // All shots except the first start OVERLAP_FRAMES early to hide the
    // OffthreadVideo decode gap at the transition point.
    const start = idx === 0 ? currentFrame : currentFrame - OVERLAP_FRAMES;
    currentFrame += durationInFrames;
    return {
      ...shot,
      startFrame: start,
      // Extend the Sequence duration to cover the overlap on both sides:
      // +OVERLAP_FRAMES at the start (so it covers the incoming gap),
      // and the last shot doesn't need the tail extension.
      durationInFrames: durationInFrames + (idx === 0 ? 0 : OVERLAP_FRAMES),
    };
  });

  const resolvedNarrationSrc = narrationSrc.startsWith("http")
    ? narrationSrc
    : staticFile(narrationSrc);

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", fontFamily: "sans-serif", overflow: "hidden" }}>
      {/* Media layer with subtle global dark cinematic treatment:
          gentle darkening, contrast boost, slight desaturation, warm sepia tone */}
      <AbsoluteFill style={{ filter: "brightness(0.85) contrast(1.1) saturate(0.85) sepia(0.15)" }}>
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

      {/* Soft vignette overlay — draws focus to center, subtle darkening at edges */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.4) 90%)",
          pointerEvents: "none",
        }}
      />

      {/* Subtle film grain / noise overlay — adds texture without competing with content */}
      <AbsoluteFill
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='1' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
          backgroundSize: "200px 200px",
          opacity: 0.12,
          pointerEvents: "none",
          mixBlendMode: "overlay",
        }}
      />

      {/* Narration Audio */}
      {resolvedNarrationSrc && <Audio src={resolvedNarrationSrc} />}

      {/* Ambient Background Audio – subtle loop at 15% volume */}
      <Audio src={staticFile("sfx-ambient.mp3")} loop volume={0.15} />

      {/* TikTok Captions at Bottom — kept outside the cinematic filter for readability */}
      <AbsoluteFill style={{ justifyContent: "flex-end", paddingBottom: 180, zIndex: 10 }}>
        <TikTokCaptions words={words} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** Derive the composition length from the actual shot plan so a story with
 *  more than 40s of footage (the old hardcoded 1200-frame ceiling) renders
 *  fully instead of blowing up with "frame range not inbetween 0-1199".
 */
export const ShortsCompositionMetadata: CalculateMetadataFunction<ShortsCompositionProps> = async ({
  props,
}) => {
  const fps = 30;
  let activeProps = props;

  // In Studio mode, props.shots is empty by default; load production props from public/remotion_props.json
  if (!activeProps.shots || activeProps.shots.length === 0) {
    const loaded = await loadStudioProps();
    if (loaded.shots && loaded.shots.length > 0) {
      activeProps = loaded;
    }
  }

  const totalFrames = (activeProps.shots || []).reduce((acc, shot) => {
    return acc + Math.max(30, Math.round((shot.duration_seconds || 3.0) * fps));
  }, 0);

  // The sum of shot durations can be shorter than the actual audio because
  // WhisperX sentence timings include inter-sentence pauses/gaps. Extend the
  // composition to cover the full narration timeline using the last real
  // WhisperX word timestamp — never an invented value.
  const words = activeProps.words || [];
  let minNarrationFrames = totalFrames;
  if (words.length > 0) {
    const lastWordEnd = words[words.length - 1].end;
    minNarrationFrames = Math.ceil(lastWordEnd * fps);
  }

  return {
    props: activeProps,
    durationInFrames: Math.max(totalFrames, minNarrationFrames, 30),
    fps,
  };
};