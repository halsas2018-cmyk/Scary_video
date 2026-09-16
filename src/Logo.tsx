import React from "react";
import { staticFile } from "remotion";

/* ------------------------------------------------------------------ */
/*  The Signal Feed — logo                                            */
/*                                                                     */
/*  Concept: a single circle (the "scope" or "lens") with a row of   */
/*  dots on its left being funneled through the circle and emerging   */
/*  as a single sharp dot on the right. Reads as "filtering noise    */
/*  into one clean signal."                                           */
/*                                                                     */
/*  Why this is unique:                                                */
/*    - Not a waveform (overused by podcast / voice / music apps)     */
/*    - Not a brain / robot / chip (every AI logo)                     */
/*    - One shape, one accent color, readable at 32px                  */
/*    - The wordmark "the signal feed" is in Space Grotesk 700, the   */
/*      same font the videos already use                              */
/*                                                                     */
/*  Variants:                                                          */
/*    - Logo            → animated React component (mounted in video) */
/*    - StaticLogo      → reads public/signal-feed-logo.svg            */
/* ------------------------------------------------------------------ */

const INK = "#1a1a1a";
const ACCENT = "#e86c00";

export type LogoProps = {
  top?: number;
  left?: number;
  /** Pixel height of the rendered logo. Width is auto from 4:1. */
  height?: number;
  /** Opacity 0..1. Default 1. */
  opacity?: number;
};

/* viewBox is 4:1 (matches the public/signal-feed-logo.svg export). */
const VB_W = 400;
const VB_H = 100;

/* Geometry — a single circle in the center, three noise dots left,
   one signal dot right. All on the same horizontal axis. */
const CIRCLE_CX = 200;
const CIRCLE_CY = 40;
const CIRCLE_R = 18;

const NOISE_DOTS = [
  { x: 60, y: 40, r: 4 },
  { x: 105, y: 28, r: 3 },
  { x: 105, y: 52, r: 3 },
  { x: 145, y: 36, r: 3.5 },
  { x: 145, y: 48, r: 2.5 },
];

const SIGNAL_DOT = { x: 340, y: 40, r: 6 };

/* Connector line from circle's right edge to signal dot — the "feed" */
const LINE_X1 = CIRCLE_CX + CIRCLE_R;
const LINE_X2 = SIGNAL_DOT.x - SIGNAL_DOT.r;
const LINE_Y = CIRCLE_CY;

export const Logo: React.FC<LogoProps> = ({
  top = 56,
  left = 56,
  height = 80,
  opacity = 1,
}) => {
  const width = height * 4; // 4:1 aspect

  return (
    <div
      role="img"
      aria-label="The Signal Feed"
      style={{
        position: "absolute",
        top,
        left,
        width,
        height,
        opacity,
        pointerEvents: "none",
      }}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        width={width}
        height={height}
        preserveAspectRatio="xMidYMid meet"
        style={{ display: "block" }}
      >
        {/* Noise dots — smaller, lighter (the "input") */}
        <g fill={INK} opacity="0.55">
          {NOISE_DOTS.map((d, i) => (
            <circle key={i} cx={d.x} cy={d.y} r={d.r} />
          ))}
        </g>

        {/* The circle (lens / scope) — bold outline only */}
        <circle
          cx={CIRCLE_CX}
          cy={CIRCLE_CY}
          r={CIRCLE_R}
          fill="none"
          stroke={INK}
          strokeWidth={4}
        />

        {/* Connector line — the "feed" leaving the lens as one clean signal */}
        <line
          x1={LINE_X1}
          y1={LINE_Y}
          x2={LINE_X2}
          y2={LINE_Y}
          stroke={INK}
          strokeWidth={2.5}
          strokeLinecap="round"
        />

        {/* The signal dot — orange accent, the "one clear thing" */}
        <circle cx={SIGNAL_DOT.x} cy={SIGNAL_DOT.y} r={SIGNAL_DOT.r} fill={ACCENT} />

        {/* Wordmark — same Space Grotesk 700 the videos use */}
        <text
          x={200}
          y={88}
          textAnchor="middle"
          fontFamily="'Space Grotesk', system-ui, sans-serif"
          fontWeight={700}
          fontSize={20}
          letterSpacing={2}
          fill={INK}
        >
          the signal feed
        </text>
      </svg>
    </div>
  );
};

/**
 * Static-fallback logo. Reads public/signal-feed-logo.svg via Remotion's
 * staticFile resolver — used by tests / favicon-size renders.
 */
export const StaticLogo: React.FC<LogoProps> = ({
  top = 56,
  left = 56,
  height = 80,
  opacity = 1,
}) => {
  const width = height * 4;
  return (
    <div
      style={{
        position: "absolute",
        top,
        left,
        width,
        height,
        opacity,
        pointerEvents: "none",
      }}
    >
      <img
        src={staticFile("signal-feed-logo.svg")}
        alt="The Signal Feed"
        style={{ width, height, display: "block" }}
      />
    </div>
  );
};

export default Logo;
