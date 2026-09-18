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

export interface ShotAsset {
  sentence: string;
  search_term: string;
  media_type: "video" | "photo";
  visual: string;
  asset_path?: string; // relative path under public/, e.g. "project_assets/shot_1.mp4"
  duration_seconds: number;
  start?: number;
  end?: number;
  start_seconds?: number;
  end_seconds?: number;
  startSeconds?: number;
  endSeconds?: number;
  startFrame?: number;
  endFrame?: number;
}

type Props = {
  shots: ShotAsset[];
  words: { word: string; start: number; end: number }[];
  timing?: { start: number; end: number }[];
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

// NOTE: declared as a `type` (not `interface`) so it satisfies the
// `Record<string, unknown>` constraint required by Remotion's
// CalculateMetadataFunction / LooseComponentType, matching the pattern
// used by MotionGraphicsVideoProps. An `interface` lacks an implicit index
// signature and triggers a type error at the <Composition> registration.
export type ShortsCompositionProps = {
  shots: ShotAsset[];
  words: { word: string; start: number; end: number }[];
  timing?: { start: number; end: number }[];
  narrationSrc: string; // e.g. "project_assets/narration.mp3"
};

/**
 * Clean a word for matching against Whisper word timestamps.
 */
const cleanWord = (w: string): string => {
  return w.toLowerCase().replace(/[^a-z0-9]/g, "");
};

/**
 * Derive sentence start and end times (in seconds) for each shot.
 *
 * 1. Uses explicit shot timing fields if present (start / end / start_seconds / etc.).
 * 2. Uses timing array if provided (from timing.json WhisperX sentence timestamps).
 * 3. Otherwise aligns shot sentences against Whisper word-level timestamps.
 * 4. Fallback: cumulative active durations.
 */
export const calculateShotTimingRanges = (
  shots: ShotAsset[],
  words: { word: string; start: number; end: number }[] = [],
  fps = 30,
  timing: { start: number; end: number }[] = []
): { startSec: number; endSec: number }[] => {
  if (shots.length === 0) return [];

  // 1. Check for explicit start on shots
  const hasExplicitTiming = shots.every(
    (s) =>
      s.start !== undefined ||
      s.start_seconds !== undefined ||
      s.startSeconds !== undefined ||
      s.startFrame !== undefined
  );

  if (hasExplicitTiming) {
    return shots.map((s) => {
      const startSec =
        s.start ??
        s.start_seconds ??
        s.startSeconds ??
        (s.startFrame !== undefined ? s.startFrame / fps : 0);
      const endSec =
        s.end ??
        s.end_seconds ??
        s.endSeconds ??
        (s.endFrame !== undefined
          ? s.endFrame / fps
          : startSec + (s.duration_seconds || 3.0));
      return { startSec, endSec };
    });
  }

  // 2. Use timing array from timing.json if available and matching shot count
  if (timing && timing.length === shots.length) {
    return timing.map((t, idx) => {
      const dur = shots[idx]?.duration_seconds || (t.end - t.start);
      return {
        startSec: t.start,
        endSec: t.end ?? (t.start + dur),
      };
    });
  }

  // 3. Align shot sentences with word-level timestamps
  if (words && words.length > 0) {
    let wordIdx = 0;
    let prevEndSec = 0;
    const result: { startSec: number; endSec: number }[] = [];

    for (let i = 0; i < shots.length; i++) {
      const shot = shots[i];
      const sentWords = (shot.sentence || "")
        .split(/\s+/)
        .map(cleanWord)
        .filter(Boolean);

      let shotStart: number | null = null;
      let shotEnd: number | null = null;
      let matched = 0;

      while (wordIdx < words.length && matched < sentWords.length) {
        const w = cleanWord(words[wordIdx].word);
        const target = sentWords[matched];

        if (!w) {
          wordIdx++;
          continue;
        }

        if (w === target || w.startsWith(target) || target.startsWith(w)) {
          if (shotStart === null) shotStart = words[wordIdx].start;
          shotEnd = words[wordIdx].end;
          matched++;
          wordIdx++;
        } else {
          const futureIdx = sentWords.slice(matched).indexOf(w);
          if (futureIdx !== -1) {
            matched += futureIdx;
            if (shotStart === null) shotStart = words[wordIdx].start;
            shotEnd = words[wordIdx].end;
            matched++;
            wordIdx++;
          } else {
            wordIdx++;
          }
        }
      }

      if (shotStart !== null && shotEnd !== null) {
        result.push({ startSec: shotStart, endSec: shotEnd });
        prevEndSec = shotEnd;
      } else {
        const dur = shot.duration_seconds || 3.0;
        result.push({ startSec: prevEndSec, endSec: prevEndSec + dur });
        prevEndSec += dur;
      }
    }

    return result;
  }

  // 3. Fallback: cumulative durations
  let cur = 0;
  return shots.map((shot) => {
    const dur = shot.duration_seconds || 3.0;
    const startSec = cur;
    const endSec = cur + dur;
    cur += dur;
    return { startSec, endSec };
  });
};

export const ShortsComposition: React.FC<ShortsCompositionProps> = ({
  shots: initialShots,
  words: initialWords,
  timing: initialTiming,
  narrationSrc: initialNarrationSrc,
}) => {
  const [props, setProps] = useState<Props>({
    shots: initialShots || [],
    words: initialWords || [],
    timing: initialTiming || [],
    narrationSrc: initialNarrationSrc || "project_assets/narration.mp3",
  });

  const { fps, durationInFrames: compositionDuration } = useVideoConfig();

  // Keep state synchronized if props change (e.g. passed from calculateMetadata or CLI)
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
  // We extend each shot's durationInFrames by the same amount so the video
  // content timing is preserved; only the Sequence boundary shifts.
  const OVERLAP_FRAMES = 2;

  // Shot placement follows actual sentence start/end timings, including inter-sentence pauses:
  // - Shot 0 starts at frame 0 (avoiding any initial black gap before narration begins).
  // - Shot i (i > 0) starts when sentence i begins (Math.round(startSec * fps)).
  // - Shot i extends across the inter-sentence pause until shot i + 1 begins.
  // - The final shot extends to the composition/narration end without black gaps.
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

      // All shots except the first start OVERLAP_FRAMES early to hide the
      // OffthreadVideo decode gap at the transition point.
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

  const shots = activeProps.shots || [];
  const words = activeProps.words || [];

  const totalFrames = shots.reduce((acc, shot) => {
    return acc + Math.max(30, Math.round((shot.duration_seconds || 3.0) * fps));
  }, 0);

  // The sum of shot durations can be shorter than the actual audio because
  // WhisperX sentence timings include inter-sentence pauses/gaps. Extend the
  // composition to cover the full narration timeline using the last real
  // WhisperX word timestamp — never an invented value.
  let minNarrationFrames = totalFrames;
  if (words.length > 0) {
    const lastWordEnd = words[words.length - 1].end;
    minNarrationFrames = Math.ceil(lastWordEnd * fps);
  }

  let lastShotEndFrames = 0;
  if (shots.length > 0) {
    const timingRanges = calculateShotTimingRanges(shots, words, fps, activeProps.timing);
    if (timingRanges.length > 0) {
      const lastTiming = timingRanges[timingRanges.length - 1];
      lastShotEndFrames = Math.ceil(lastTiming.endSec * fps);
    }
  }

  return {
    props: activeProps,
    durationInFrames: Math.max(totalFrames, minNarrationFrames, lastShotEndFrames, 30),
    fps,
  };
};