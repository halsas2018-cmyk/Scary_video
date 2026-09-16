import React, { createContext, useContext, useMemo } from "react";
import {
  Easing,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
} from "remotion";

export type SceneTransitionContextValue = {
  isIdle: boolean;
  entranceProgress: number; // 0 -> 1 during entrance
  exitProgress: number; // 0 -> 1 during exit
  idleProgress: number; // 0 -> 1 during idle hold
  overallProgress: number; // 0 -> 1 across the whole beat
};

/**
 * Default context — when a component is rendered outside a SceneTransition
 * (e.g. a *Test composition in Studio), it gets identity values so it still
 * works in isolation.
 */
const defaultContextValue: SceneTransitionContextValue = {
  isIdle: true,
  entranceProgress: 1,
  exitProgress: 0,
  idleProgress: 0,
  overallProgress: 1,
};

const SceneTransitionContext = createContext<SceneTransitionContextValue>(
  defaultContextValue,
);

export const useSceneTransition = (): SceneTransitionContextValue =>
  useContext(SceneTransitionContext);

/**
 * Phase budgets (in % of the beat's duration).
 * Tuned for short-form YouTube Shorts (1.5s - 4s beats).
 */
const ENTRANCE_FRACTION = 0.18; // first 18% = entrance animation
const EXIT_FRACTION = 0.18; // last 18% = exit animation
// middle (~64%) is the idle hold, where the beat sits at rest

/**
 * Easing curves.
 * - ENTRANCE_EASING: snappy "out" curve, matches the Remotion best-practice
 *   `Easing.bezier(0.16, 1, 0.3, 1)` (the skill's default).
 * - EXIT_EASING: gentle "in" curve, fades out smoothly.
 */
const ENTRANCE_EASING = Easing.bezier(0.16, 1, 0.3, 1);
const EXIT_EASING = Easing.bezier(0.7, 0, 0.84, 0);

type SceneTransitionProps = {
  children: React.ReactNode;
  /** Override the entrance phase budget (frames). If set, ENTRANCE_FRACTION is ignored. */
  entranceFrames?: number;
  /** Override the exit phase budget (frames). If set, EXIT_FRACTION is ignored. */
  exitFrames?: number;
  /**
   * If set, the exit fade runs across the LAST `crossFadeFrames` frames of the
   * beat instead of the last EXIT_FRACTION (18%). The orchestrator passes the
   * `transitionFrames` value from `computeTransitionFrames()` so the exit
   * fade aligns exactly with the next beat's entrance window — the two beats
   * cross-fade in lockstep instead of double-showing for the first ~18% of
   * the overlap and then snapping.
   *
   * When unset, the 18% default is used (preserves existing `*Test`
   * composition behaviour, keeps the smoke test green).
   */
  crossFadeFrames?: number;
};

/**
 * Wraps a beat's content in entrance / idle / exit animation context.
 *
 * Children can use `useSceneTransition()` to read the four progress values
 * and `interpolate()` against them. The default wrapper behavior is a
 * gentle opacity-driven entrance (fade + slide-up) and exit (fade),
 * with Easing.bezier timing for a snappier feel.
 */
export const SceneTransition: React.FC<SceneTransitionProps> = ({
  children,
  entranceFrames,
  exitFrames,
  crossFadeFrames,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const entranceDuration = entranceFrames ?? Math.round(durationInFrames * ENTRANCE_FRACTION);
  // Exit budget: when a cross-fade window is provided by the orchestrator,
  // the exit fade runs across the LAST `crossFadeFrames` frames of the
  // beat (so it lines up with the next beat's entrance). When no
  // cross-fade is provided, fall back to the 18% default so the last
  // beat (and any *Test composition) still gets a graceful end fade.
  const exitDuration =
    exitFrames ??
    (crossFadeFrames !== undefined && crossFadeFrames > 0
      ? Math.min(crossFadeFrames, durationInFrames)
      : Math.round(durationInFrames * EXIT_FRACTION));
  const exitStart = Math.max(0, durationInFrames - exitDuration);

  const value = useMemo<SceneTransitionContextValue>(() => {
    const entranceProgress = interpolate(
      frame,
      [0, Math.max(1, entranceDuration)],
      [0, 1],
      {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: ENTRANCE_EASING,
      },
    );

    const exitProgress = interpolate(
      frame,
      [exitStart, Math.max(exitStart + 1, durationInFrames)],
      [0, 1],
      {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: EXIT_EASING,
      },
    );

    const idleStart = entranceDuration;
    const idleEnd = exitStart;
    const idleProgress = interpolate(
      frame,
      [idleStart, idleEnd],
      [0, 1],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    );

    const overallProgress = interpolate(
      frame,
      [0, Math.max(1, durationInFrames - 1)],
      [0, 1],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    );

    const isIdle =
      frame >= entranceDuration && frame < exitStart;

    return {
      isIdle,
      entranceProgress,
      exitProgress,
      idleProgress,
      overallProgress,
    };
  }, [frame, durationInFrames, entranceDuration, exitStart]);

  // Default wrapper behavior: a gentle entrance (fade + slide-up) and exit (fade).
  // Children that read useSceneTransition() can layer their own animations on top.
  const opacity = value.entranceProgress * (1 - value.exitProgress);
  const translateY = interpolate(
    value.entranceProgress,
    [0, 1],
    [24, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: ENTRANCE_EASING,
    },
  );

  return (
    <SceneTransitionContext.Provider value={value}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity,
          translate: `0 ${translateY}px`,
          pointerEvents: "none",
        }}
      >
        {children}
      </div>
    </SceneTransitionContext.Provider>
  );
};
