/**
 * Dynamic cross-fade duration for `<TransitionSeries.Transition>`.
 *
 * The transition frames are computed as a percentage of the SHORTER of
 * the two adjacent beats, then clamped to a min/max so that:
 *   - very short beats still produce a visible cross-fade (>= 4 frames), and
 *   - very long beats don't drag through a long fade (<= 15 frames).
 *
 * Why percentage of the shorter side?
 *   The shorter beat is the bottleneck: you can't cross-fade for more
 *   frames than the shorter side has idle time. Using `min(out, in)`
 *   makes the formula symmetric and works for any beat pair.
 *
 * Why cap at 15 frames?
 *   At 30 fps, 15 frames = 0.5s. A 4-second beat at 15% would yield
 *   ~36 frames (1.2s), which feels sluggish. The cap keeps the
 *   cross-fade snappy regardless of beat length.
 *
 * The orchestrator AND `calculateMetadata` both call this so the
 * rendered timeline and the declared total duration stay in sync.
 */
export const TRANSITION_PCT = 0.15;
export const TRANSITION_MIN_FRAMES = 4;
export const TRANSITION_MAX_FRAMES = 15;

export const computeTransitionFrames = (
  outgoingDurationInFrames: number,
  incomingDurationInFrames: number,
): number => {
  const shorter = Math.min(
    outgoingDurationInFrames,
    incomingDurationInFrames,
  );
  const pctBased = Math.round(TRANSITION_PCT * shorter);
  return Math.max(
    TRANSITION_MIN_FRAMES,
    Math.min(TRANSITION_MAX_FRAMES, pctBased),
  );
};
