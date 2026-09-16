import { useCurrentFrame, useVideoConfig } from "remotion";

// ============================================================================
// TYPES & INTERFACES
// ============================================================================

/**
 * Options for `useChartReveal`.
 *
 * The hook owns the chart's two time-based primitives:
 *   - drawProgress: linear 0..1 reveal used for stroke-dashoffset and
 *     point fade-in. drawInFrames is the value the inline code used
 *     for "line is fully drawn" — the hook reads fps from useVideoConfig
 *     so the component doesn't have to pass it.
 *   - idlePulse: subtle 1 ± idleAmp * sin(frame * idleFreq) scale
 *     modulation on the chart element wrapper (NOT on individual data
 *     points, which would distort the data). Defaults idleAmp=0.05,
 *     idleFreq=0.04. To preserve the pre-2.3.x curve 1:1, pass
 *     idleAmp=0.01 and idleFreq=0.05 (as ChartLine does).
 *
 * **Unit convention:** drawInFrames is in frames at the composition's
 * fps. The hook handles the linear ramp internally; the component
 * doesn't have to do any frame math.
 */
export interface ChartRevealOptions {
  /**
   * Frame index at which the line is fully drawn. The component
   * computes this from its entrance timing (e.g.
   * `lineStart + lineDuration` for `ChartLine`).
   */
  drawInFrames: number;
  /**
   * Idle pulse amplitude. Default `0.05` (~5% scale). The pre-2.3.x
   * `ChartLine` inline value was `0.01`, which the component now
   * passes explicitly.
   */
  idleAmp?: number;
  /**
   * Idle pulse frequency in cycles per frame. Default `0.04` (≈1.2
   * cycles/sec at 30fps). The pre-2.3.x `ChartLine` inline value
   * was `0.05`, which the component now passes explicitly.
   */
  idleFreq?: number;
}

/**
 * Return value of `useChartReveal`.
 *
 * - `drawProgress`: linear 0..1 reveal. Use for stroke-dashoffset
 *   (`dashOffset = totalLength * (1 - drawProgress)`) and for
 *   fading in elements as the line draws.
 * - `idlePulse`: 1 ± idleAmp * sin(frame * idleFreq). Apply to the
 *   chart element wrapper's `scale` to get a subtle breathing effect.
 */
export interface ChartReveal {
  /** Linear 0..1 reveal, in [0, drawInFrames]. */
  drawProgress: number;
  /** 1 ± idleAmp * sin(frame * idleFreq). Apply to `scale`. */
  idlePulse: number;
}

// ============================================================================
// HOOK
// ============================================================================

/**
 * `useChartReveal` — Pass 2 of Horizon 2.3.x. Owns the chart's two
 * time-based primitives (linear reveal + idle pulse). Sibling of
 * `useSceneOrbit`. The component still owns entrance / exit /
 * per-point stagger; only the 2 time-based primitives move to the
 * hook.
 */
export function useChartReveal(opts: ChartRevealOptions): ChartReveal {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const { drawInFrames, idleAmp = 0.05, idleFreq = 0.04 } = opts;

  // Linear 0..1 reveal over [0, drawInFrames]. Clamped at both ends
  // so frames beyond drawInFrames return 1, and frames before 0
  // return 0.
  const drawProgress = Math.min(1, Math.max(0, frame / drawInFrames));

  // 1 ± idleAmp * sin(frame * idleFreq). idleFreq is cycles per
  // frame (matches the pre-2.3.x inline form `1 + 0.01 * sin(frame
  // * 0.05)`).
  const idlePulse = 1 + idleAmp * Math.sin(frame * idleFreq);

  // fps is read from useVideoConfig but not used in the math (the
  // values are in cycles/frame, not cycles/sec). We keep the read
  // to make the hook fps-aware by signature and to match the
  // sibling `useSceneOrbit` pattern.
  void fps;

  return { drawProgress, idlePulse };
}
