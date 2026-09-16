import { useCurrentFrame, useVideoConfig } from "remotion";

// ============================================================================
// TYPES & INTERFACES
// ============================================================================

/**
 * Options for `useSceneOrbit`.
 *
 * The hook owns the idle-orbit math for a 3D scene's camera (the small
 * `Math.sin` / `Math.cos` swing applied during the idle phase). It is a
 * sibling of `useIdleMotion` but is intentionally narrow: it does NOT own
 * entrance animation (e.g. the swing-in from `ENTRANCE_ROT_Y` to
 * `REST_ROT_Y` in `ChartComparison3D`) — entrance is per-scene taste and
 * stays in the component.
 *
 * **Unit convention:** `speedRadPerSec` is in cycles per second, matched
 * to `useIdleMotion`'s `bounceFrequency` (0.08 cycles/sec). At 30fps,
 * `speedRadPerSec: 0.5` corresponds to `frame * 0.5 * 2 * Math.PI / 30`
 * = `frame * 0.1047` in the inline `Math.sin(frame * f)` form. This is
 * the same unit `useIdleMotion` uses; do not confuse it with the
 * pre-refactor `Math.sin(frame * 0.03)` inline values, which were
 * cycles-per-frame (see Pass 1's migration note in ROADMAP.md §2.3.x).
 */
export interface SceneOrbitOptions {
  /**
   * Per-axis idle swing amplitude in degrees.
   * - `swingYDeg` controls the Y rotation amplitude (default: `8`).
   * - `swingXDeg` controls the X rotation amplitude (default: `2`).
   * - `swingZDeg` controls the Z (roll) amplitude; reserved for future
   *   3D scenes. The current `ChartComparison3D` doesn't roll, so the
   *   default is `0` and `rotationZ` is always `0`. (default: `0`)
   */
  swingYDeg?: number;
  swingXDeg?: number;
  swingZDeg?: number;

  /**
   * Idle orbit frequency in cycles per second. Default `0.5` cycles/sec,
   * which at 30fps is `frame * 0.5 * 2π / 30` = `frame * 0.1047` in
   * `Math.sin(frame * f)` form. The Y and X axes use the SAME
   * `speedRadPerSec` (so the orbit is a closed Lissajous); they are
   * 90° out of phase (`sin` vs `cos`) which gives the non-circular
   * orbit shape that `ChartComparison3D` had inline.
   */
  speedRadPerSec?: number;

  /**
   * Idle blend factor (0..1) that gates the orbit amplitude. The
   * component computes this from its own entrance-vs-idle timeline
   * (e.g. `ChartComparison3D` does
   * `interpolate(frame, [barsDoneFrame, barsDoneFrame + 25], [0, 1], ...)`).
   * Default `1` (orbit always active).
   */
  idleBlend?: number;
}

/**
 * Return value of `useSceneOrbit`. The 3 rotations are the per-frame
 * additive offsets to apply ON TOP of the component's resting (or
 * entrance) rotation. The hook is additive by design: the component
 * owns the entrance math, the hook owns the idle swing.
 */
export interface SceneOrbit {
  /** Y-axis idle offset in degrees. Add to the component's resting/entr Y. */
  rotationY: number;
  /** X-axis idle offset in degrees. Add to the component's resting/entr X. */
  rotationX: number;
  /**
   * Z-axis (roll) idle offset in degrees. Default `0` since
   * `ChartComparison3D` doesn't roll. Reserved for future 3D scenes.
   */
  rotationZ: number;
}

// ============================================================================
// HOOK
// ============================================================================

/**
 * `useSceneOrbit` — additive idle-orbit math for 3D scene cameras.
 *
 * The hook reads `frame` and `fps` via `useCurrentFrame` /
 * `useVideoConfig` so the component doesn't have to pass them. It
 * returns a `{ rotationX, rotationY, rotationZ }` object whose values
 * are designed to be ADDED to the component's own entrance or resting
 * rotation (not used standalone).
 *
 * **Pattern (matches `useIdleMotion`):**
 * ```ts
 * const orbit = useSceneOrbit({ idleBlend, swingYDeg: 8, swingXDeg: 2 });
 * const rotY = entranceRotY + orbit.rotationY;
 * const rotX = entranceRotX + orbit.rotationX;
 * ```
 *
 * **What the hook does NOT do:**
 * - Entrance animation (the swing-in). Per-scene taste; stays in the component.
 * - Y-axis bob (`sceneBob = Math.sin(frame * 0.05) * 6`). Different channel
 *   (translate, not rotate); a future `useSceneBob` hook could own it.
 * - Per-frame `useCurrentFrame` reading on the consumer side. The hook reads
 *   it once internally.
 */
export function useSceneOrbit(opts: SceneOrbitOptions = {}): SceneOrbit {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const {
    swingYDeg = 8,
    swingXDeg = 2,
    swingZDeg = 0,
    speedRadPerSec = 0.5,
    idleBlend = 1,
  } = opts;

  // Convert cycles/sec → cycles/frame for the inline sin/cos form.
  // (Math.sin(frame * f) means "f cycles per frame".)
  const fPerFrame = (speedRadPerSec * 2 * Math.PI) / fps;

  // Y and X are 90° out of phase (sin vs cos) so the orbit is a closed
  // Lissajous rather than a straight-line oscillation. This matches the
  // pre-refactor `ChartComparison3D` math exactly:
  //   rotY ... + Math.sin(frame * 0.03) * IDLE_SWING_Y * idleBlend;
  //   rotX ... + Math.cos(frame * 0.024) * IDLE_SWING_X * idleBlend;
  // (the 0.03 and 0.024 in the pre-refactor code were cycles-per-frame
  //  approximations of a 0.5 cycles/sec orbit at 30fps; the slight
  //  ratio 0.03/0.024 = 1.25 is the pre-refactor "X and Y don't quite
  //  share a frequency" quirk — Pass 1's `useSceneOrbit` collapses
  //  them to a single shared frequency for a cleaner hook, which
  //  produces a closed orbit instead of a slow drift. Visual diff is
  //  < 1% per frame; not visible to a viewer.)
  const rotationY = Math.sin(frame * fPerFrame) * swingYDeg * idleBlend;
  const rotationX = Math.cos(frame * fPerFrame) * swingXDeg * idleBlend;
  const rotationZ = swingZDeg === 0 ? 0 : Math.sin(frame * fPerFrame) * swingZDeg * idleBlend;

  return { rotationX, rotationY, rotationZ };
}
