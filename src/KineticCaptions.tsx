import React, { useEffect, useMemo, useState } from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
  Interactive,
} from "remotion";
import { useBeatContext } from "./beats/beatContext";

interface Word {
  word: string;
  start: number;
  end: number;
}

interface KineticCaptionsProps {
  /**
   * Optional. Only used when there is NO <BeatContext.Provider> above
   * this component (i.e. *Test compositions with no wrapper). In the
   * real composition, the per-beat wrapper provides the context and
   * the visualizer ignores this prop.
   *
   * Defaults to KINETIC_CAPTION_ENABLED_BEAT_TYPES (the production
   * caption gate — the same set the orchestrator mounts for).
   */
  captionEnabledTypes?: Set<string>;
  /**
   * Optional. Only used in *Test compositions with no provider.
   * Ignored when the context is present.
   */
  beats?: Array<{ type: string; startFrame: number; durationInFrames: number }>;
  /** Optional. Only used when no context. */
  words?: Word[];
}

// ============================================
// CONFIGURATION — clean line captions at bottom
// ============================================
const CONFIG = {
  // Typography
  fontSize: 56,
  fontWeight: 700 as React.CSSProperties["fontWeight"],
  fontFamily: "system-ui, sans-serif",
  lineHeight: 1.3,
  wordGap: 12,

  // Animation
  transitionFrames: 3,
  transitionEasing: Easing.bezier(0.16, 1, 0.3, 1),

  // Highlight style for current word
  highlightColor: "#e86c00",
  highlightBgColor: "rgba(232, 108, 0, 0.12)",
  highlightPadding: "4px 8px",
  highlightBorderRadius: 8,

  // Card style for current word
  cardBgColor: "rgba(255, 255, 255, 0.95)",
  cardBorderColor: "#e86c00",
  cardBorderWidth: 2,
  cardBorderRadius: 12,
  cardPadding: "6px 12px",
  cardShadow: "0 4px 12px rgba(0, 0, 0, 0.15)",

  // Fade for past words
  pastWordOpacity: 0.6,
  pastWordColor: "#4a4a4a",

  // Layout - moved up to 1/3 of screen height
  bottomMargin: "33vh",
  maxWidth: "90%",
  paddingHorizontal: 80,

  // Colors
  textColor: "#1a1a1a",
  inactiveTextColor: "#4a4a4a",
} as const;

/**
 * Single source of truth for which beat types show kinetic captions.
 * Must stay in sync with `CAPTION_VISIBLE_BEAT_TYPES` in
 * src/beats/renderBeat.tsx.
 */
const KINETIC_CAPTION_ENABLED_BEAT_TYPES = new Set<string>([
  "map_3d",
  "chart_line",
  "chart_comparison_3d",
  "chart_counter",
  "progress_meter",
  "timeline",
  "process_flow",
]);

export const KineticCaptions: React.FC<KineticCaptionsProps> = ({
  captionEnabledTypes,
  beats,
  words: dynamicWords,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  // Safely get beat context - default to showing captions if no context
  let beatContext: ReturnType<typeof useBeatContext> | null = null;
  try {
    beatContext = useBeatContext();
  } catch (e) {
    // No BeatContext provider - default to showing captions
    beatContext = null;
  }

  const currentBeatType: string | null = beatContext?.currentBeatType ?? null;
  const beatStartFrame: number | null = beatContext?.beatStartFrame ?? null;
  const beatDurationInFrames: number | null =
    beatContext?.beatDurationInFrames ?? null;

  // If a beat type is provided by the orchestrator, gate captions to the
  // beat types the orchestrator considers data-vis. If no context (e.g. a
  // *Test composition with no provider), use the caller-supplied
  // `captionEnabledTypes` set so test compositions can still preview.
  const effectiveEnabledTypes = currentBeatType
    ? KINETIC_CAPTION_ENABLED_BEAT_TYPES
    : (captionEnabledTypes ?? KINETIC_CAPTION_ENABLED_BEAT_TYPES);

  const shouldShowCaptions = currentBeatType
    ? effectiveEnabledTypes.has(currentBeatType)
    : true;

  // ============================================
  // WORD RESOLUTION (the actual fix)
  // ============================================
  // 1. Prefer the per-beat words from the orchestrator's context
  //    (BeatKineticCaptions slices the full list to the current beat).
  // 2. Fall back to the prop if no context.
  // 3. If we have a beatStartFrame, convert each word's global
  //    `w.start` (seconds) to a LOCAL frame number so the captions
  //    line up with the per-beat <Sequence> that the orchestrator
  //    wraps us in. This is the root-cause fix: previously the
  //    `currentWordIndex` lookup compared `frame` (local, 0..duration)
  //    against `w.start * fps` (global, 0..totalDuration), so it
  //    almost never matched and the highlight stayed stuck on word 0.
  const contextWords: Word[] = beatContext?.currentWords ?? [];

  const allWords: Word[] = useMemo(() => {
    const src = (contextWords && contextWords.length > 0)
      ? contextWords
      : (dynamicWords ?? []);
    if (!src || src.length === 0) return [];

    // If we have a beat context, slice to the beat's window AND
    // rebase `start`/`end` to LOCAL frames. The renderer reads
    // `w.start` as a frame number; after rebasing, frame 0 is the
    // first word spoken inside this beat.
    if (beatStartFrame != null) {
      const startSec = beatStartFrame / fps;
      const endSec = beatStartFrame + (beatDurationInFrames ?? 0) / fps;
      return src
        .filter((w) => w.start >= startSec - 0.01 && w.start < endSec)
        .map((w) => ({
          word: w.word,
          start: Math.max(0, Math.round(w.start * fps) - beatStartFrame),
          end: Math.max(0, Math.round(w.end * fps) - beatStartFrame),
        }));
    }
    // No beat context — treat prop words as local frames already
    // (e.g. the *Test composition pre-slices them).
    return src;
  }, [contextWords, dynamicWords, beatStartFrame, beatDurationInFrames, fps]);

  // Hold words in state so an async-loaded prop update re-renders
  // captions. (When the orchestrator's first render sees an empty
  // `dynamicWords` and then the fetch resolves, we want to update.)
  const [resolvedWords, setResolvedWords] = useState<Word[]>([]);
  useEffect(() => {
    if (allWords.length > 0) setResolvedWords(allWords);
  }, [allWords]);
  const effectiveWords = allWords.length > 0 ? allWords : resolvedWords;

  if (!shouldShowCaptions || effectiveWords.length === 0) {
    return null;
  }

  // Find the currently spoken word index. With the rebasing above,
  // `frame` (local) and `w.start` (local) are now in the same unit,
  // so the lookup is correct.
  const currentWordIndex = effectiveWords.findIndex((w, i) => {
    const wordStartFrame = w.start;
    const nextWord = effectiveWords[i + 1];
    const nextWordStartFrame = nextWord ? nextWord.start : w.end;
    return frame >= wordStartFrame && frame < nextWordStartFrame;
  });

  // If we never found a match (frame is outside the spoken range, e.g.
  // the beat is still pre-roll, or this beat has no words), don't
  // render anything.
  if (currentWordIndex === -1) {
    return null;
  }

  // Only show 5 words at a time: current word + 2 before + 2 after
  const windowSize = 5;
  const halfWindow = Math.floor(windowSize / 2);
  const endIndex = Math.min(
    effectiveWords.length - 1,
    currentWordIndex + halfWindow,
  );

  // Adjust start if we're near the end
  const adjustedStart = Math.max(0, endIndex - windowSize + 1);
  const visibleWordIndices: number[] = [];
  for (let i = adjustedStart; i <= endIndex; i++) {
    visibleWordIndices.push(i);
  }

  // For each visible word, compute its visibility progress
  const wordStates = visibleWordIndices.map((i) => {
    const w = effectiveWords[i];
    const wordStartFrame = w.start;
    const wordEndFrame = w.end;
    const nextWord = effectiveWords[i + 1];
    const nextWordStartFrame = nextWord ? nextWord.start : wordEndFrame;
    const fadeInFrames = CONFIG.transitionFrames;

    let progress = 0;
    let isCurrent = false;
    let currentProgress = 0;

    if (frame < wordStartFrame) {
      progress = 0;
    } else if (frame < wordStartFrame + fadeInFrames) {
      progress = interpolate(frame, [wordStartFrame, wordStartFrame + fadeInFrames], [0, 1], {
        easing: CONFIG.transitionEasing,
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    } else if (frame < nextWordStartFrame) {
      progress = 1;
    } else {
      progress = 1; // Stay visible after spoken
    }

    // Current word highlight
    if (i === currentWordIndex) {
      isCurrent = true;
      if (frame < wordStartFrame + fadeInFrames) {
        currentProgress = interpolate(frame, [wordStartFrame, wordStartFrame + fadeInFrames], [0, 1], {
          easing: CONFIG.transitionEasing,
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
      } else if (frame < nextWordStartFrame - fadeInFrames) {
        currentProgress = 1;
      } else {
        currentProgress = interpolate(frame, [nextWordStartFrame - fadeInFrames, nextWordStartFrame], [1, 0], {
          easing: CONFIG.transitionEasing,
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
      }
    }

    return {
      word: w,
      progress,
      isCurrent,
      currentProgress,
      index: i,
    };
  });

  return (
    <AbsoluteFill
      style={{
        width,
        height,
        backgroundColor: "transparent",
        overflow: "hidden",
        pointerEvents: "none",
      }}
    >
      <Interactive.Div
        name="KineticCaptions"
        style={{
          position: "absolute",
          bottom: CONFIG.bottomMargin,
          left: CONFIG.paddingHorizontal,
          right: CONFIG.paddingHorizontal,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          gap: CONFIG.wordGap,
          maxWidth: CONFIG.maxWidth,
          pointerEvents: "none",
        }}
      >
        {wordStates.map(({ word: w, progress, isCurrent, currentProgress, index }) => {
          const isPast = index < currentWordIndex;
          const isFuture = index > currentWordIndex;

          // Word entrance animation
          const entranceProgress = interpolate(progress, [0, 1], [0, 1], {
            easing: Easing.bezier(0.34, 1.56, 0.64, 1), // subtle bounce
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });

          const scale = interpolate(entranceProgress, [0, 1], [0.8, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const opacity = isFuture ? 0 : progress;
          const yOffset = interpolate(entranceProgress, [0, 1], [20, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });

          // Current word highlight pulse
          const highlightPulse = isCurrent ? 1 + 0.05 * Math.sin(frame * 0.15) : 1;

          // Styles based on state
          const baseStyles: React.CSSProperties = {
            display: "inline-block",
            fontSize: CONFIG.fontSize,
            fontWeight: CONFIG.fontWeight,
            fontFamily: CONFIG.fontFamily,
            lineHeight: CONFIG.lineHeight,
            whiteSpace: "nowrap",
            opacity,
            scale,
            translate: `${yOffset}px 0px`,
            transformOrigin: "center bottom",
          };

          let wordStyles: React.CSSProperties = { ...baseStyles };

          if (isCurrent) {
            wordStyles = {
              ...wordStyles,
              color: CONFIG.highlightColor,
              backgroundColor: CONFIG.highlightBgColor,
              padding: CONFIG.highlightPadding,
              borderRadius: CONFIG.highlightBorderRadius,
              fontWeight: 800,
              boxShadow: `0 2px 12px rgba(232, 108, 0, ${0.2 * currentProgress})`,
            };
          } else if (isPast) {
            wordStyles = {
              ...wordStyles,
              color: CONFIG.pastWordColor,
              opacity: CONFIG.pastWordOpacity * progress,
            };
          } else {
            wordStyles = {
              ...wordStyles,
              color: CONFIG.textColor,
            };
          }

          // Wrap current word in a card
          if (isCurrent) {
            return (
              <div
                key={`${w.start}-${w.word}-${index}`}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  backgroundColor: CONFIG.cardBgColor,
                  border: `${CONFIG.cardBorderWidth}px solid ${CONFIG.cardBorderColor}`,
                  borderRadius: CONFIG.cardBorderRadius,
                  padding: CONFIG.cardPadding,
                  boxShadow: CONFIG.cardShadow,
                  transform: `scale(${highlightPulse})`,
                }}
              >
                <span style={wordStyles}>{w.word}</span>
              </div>
            );
          }

          return (
            <span
              key={`${w.start}-${w.word}-${index}`}
              style={wordStyles}
            >
              {w.word}
            </span>
          );
        })}
      </Interactive.Div>
    </AbsoluteFill>
  );
};
