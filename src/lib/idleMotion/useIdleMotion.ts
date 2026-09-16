import { useCurrentFrame } from "remotion";

/**
 * Shared ambient idle motion used by every design-system component.
 *
 * Replaces the three lines every component duplicated:
 *   const bounce = Math.sin(t) * 6;
 *   const tilt   = Math.sin(t * 0.05) * 2;
 *   const glow   = 1 + 0.15 * Math.sin(t * 0.03);
 *
 * Two outputs:
 *   - `transform`: pre-composed CSS string for the common case where
 *     a component wants the idle transform on its main wrapper.
 *   - `translateY` / `rotateX` / `scale`: the three primitives as
 *     numbers, for the rare component that already owns a transform
 *     (slider scroll, ticker scroll, VS badge rotate) and needs to
 *     compose idle on a *parent* of the element that owns the
 *     existing transform.
 *
 * Frequency semantics:
 *   - `bounceFrequency` uses the `Math.sin(frame * f * Math.PI * 2)`
 *     pattern that HeadlineCard / KeyStatement already use, so the
 *     default of 0.08 matches the existing motion exactly.
 *   - `tiltFrequency` and `glowFrequency` use the simpler
 *     `Math.sin(frame * f)` pattern (radians per frame), also matching
 *     the existing 0.05 and 0.03.
 */
export type IdleMotionOptions = {
  /** Composition FPS. Default 30. */
  fps?: number;
  /** Per-primitive toggles. All default true. */
  bounce?: boolean;
  tilt?: boolean;
  glow?: boolean;
  /** Amplitude overrides. */
  bounceAmplitude?: number; // default 6 (px)
  tiltAmplitude?: number;   // default 2 (deg)
  glowAmplitude?: number;   // default 0.15
  /** Frequency overrides. Defaults match HeadlineCard's existing values. */
  bounceFrequency?: number; // default 0.08 (cycles per frame, via * PI * 2)
  tiltFrequency?: number;   // default 0.05 (rad per frame)
  glowFrequency?: number;   // default 0.03 (rad per frame)
};

export type IdleMotion = {
  /** "translateY(Xpx) rotateX(Ydeg) scale(Z)" — spread into `style.transform`. */
  transform: string;
  translateY: number;
  rotateX: number;
  scale: number;
};

export function useIdleMotion(opts: IdleMotionOptions = {}): IdleMotion {
  const frame = useCurrentFrame();
  const {
    bounce: enableBounce = true,
    tilt: enableTilt = true,
    glow: enableGlow = true,
    bounceAmplitude = 6,
    tiltAmplitude = 2,
    glowAmplitude = 0.15,
    bounceFrequency = 0.08,
    tiltFrequency = 0.05,
    glowFrequency = 0.03,
  } = opts;

  const translateY = enableBounce
    ? Math.sin(frame * bounceFrequency * Math.PI * 2) * bounceAmplitude
    : 0;
  const rotateX = enableTilt ? Math.sin(frame * tiltFrequency) * tiltAmplitude : 0;
  const scale = enableGlow ? 1 + glowAmplitude * Math.sin(frame * glowFrequency) : 1;

  const transform = `translateY(${translateY}px) rotateX(${rotateX}deg) scale(${scale})`;

  return { transform, translateY, rotateX, scale };
}
