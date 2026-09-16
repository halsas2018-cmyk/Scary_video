import React from "react";

/* ------------------------------------------------------------------ */
/*  textCards — shared visual primitives for the text-on-card family. */
/*                                                                     */
/*  This is a LEAF file under src/lib/ (sibling of idleMotion and     */
/*  sceneMotion). It exports pure presentational primitives that      */
/*  accept their animation state as props — the parent component      */
/*  owns the frame counter and the easing. It must NOT import from    */
/*  any consumer component or orchestrator (CLAUDE.md §0: "Hook        */
/*  barrels are leaf files").                                          */
/*                                                                     */
/*  Used by: HeadlineCard, KeyStatement, PlainText, QuoteCard,        */
/*  Scrollytelling (the 5 text-on-card beat types).                   */
/* ------------------------------------------------------------------ */

/**
 * `<DottedUnderline>` — an animated SVG dotted rule that draws in
 * from left to right. The parent supplies the current progress (0..1)
 * so the animation can be driven by Remotion's frame counter rather
 * than by a CSS keyframe.
 *
 * Used by HeadlineCard (large, full-width, behind the headline) and
 * QuoteCard (small, between quote and attribution).
 */
export const DottedUnderline: React.FC<{
  /** Width of the rule in px. */
  width: number;
  /** Stroke color (defaults to the orange accent). */
  color?: string;
  /** 0..1 — how much of the rule is drawn in. 1 = fully drawn. */
  progress: number;
  /** Stroke width in px (defaults to 4). */
  strokeWidth?: number;
  /** Optional vertical offset from the parent baseline (px). */
  y?: number;
  /** Optional opacity (defaults to 1). */
  opacity?: number;
}> = ({ width, color = "#e86c00", progress, strokeWidth = 4, y = 0, opacity = 1 }) => {
  const clamped = Math.max(0, Math.min(1, progress));
  return (
    <svg
      width={width}
      height={strokeWidth + 4}
      style={{ display: "block", overflow: "visible", opacity }}
    >
      <line
        x1={0}
        y1={y + strokeWidth / 2 + 2}
        x2={width}
        y2={y + strokeWidth / 2 + 2}
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray="2 8"
        pathLength={100}
        strokeDashoffset={100 - clamped * 100}
      />
    </svg>
  );
};

/**
 * `<DropCap>` — wraps a single oversized first letter (rendered in the
 * accent color) with the rest of the word/paragraph flowing around it.
 *
 * Uses CSS float so the body text wraps around the drop cap on the
 * left. The drop cap itself is large (default 3.2× the body font) and
 * uses the accent color, optionally with a gradient.
 *
 * Used by PlainText and Scrollytelling.
 */
export const DropCap: React.FC<{
  /** The first character (single letter, ideally). */
  letter: string;
  /** Size of the drop cap in px (default 120). */
  size?: number;
  /** Color (defaults to orange accent). */
  color?: string;
  /** Optional second color for a linear gradient (defaults to lighter orange). */
  colorEnd?: string;
  /** Body font size in px (so the float math scales). Default 36. */
  bodyFontSize?: number;
  /** Number of lines the drop cap should span (CSS line-height based). Default 3. */
  lineSpan?: number;
  /** Body line height multiplier. Default 1.5. */
  lineHeight?: number;
  /** Right margin between the drop cap and body text (px). Default 16. */
  marginRight?: number;
  /** Font family for the drop cap. Default "Georgia, serif". */
  fontFamily?: string;
  /** Top margin offset (px) so the drop cap aligns with the first line. */
  topOffset?: number;
}> = ({
  letter,
  size = 120,
  color = "#e86c00",
  colorEnd = "#f97316",
  bodyFontSize = 36,
  lineSpan = 3,
  lineHeight = 1.5,
  marginRight = 16,
  fontFamily = "Georgia, serif",
  topOffset = 6,
}) => {
  const height = bodyFontSize * lineHeight * lineSpan;
  return (
    <span
      style={{
        float: "left",
        fontSize: size,
        lineHeight: 0.9,
        fontFamily,
        fontWeight: 700,
        background: `linear-gradient(180deg, ${color}, ${colorEnd})`,
        WebkitBackgroundClip: "text",
        backgroundClip: "text",
        WebkitTextFillColor: "transparent",
        marginRight,
        marginTop: topOffset,
        marginBottom: -bodyFontSize * 0.2,
        height,
        // Align the cap's top with the first body line baseline.
        display: "flex",
        alignItems: "flex-start",
        textShadow: `0 4px 24px ${color}30`,
      }}
    >
      {letter}
    </span>
  );
};

/**
 * `<TimelineRail>` — a vertical accent line on the left of a card with
 * evenly-spaced dots beside it. Dots can be filled in progressively
 * (the parent passes `filledCount` to show the first N dots as solid).
 *
 * Used by Scrollytelling — each word in the body lights up its dot as
 * it appears.
 */
export const TimelineRail: React.FC<{
  /** Total height of the rail in px (matches the body content). */
  height: number;
  /** Number of dots to render. */
  dotCount: number;
  /** 0..dotCount — how many dots are filled in. */
  filledCount: number;
  /** Color of the rail + filled dots (defaults to orange accent). */
  color?: string;
  /** Color of the unfilled dots. Defaults to #d4d4d4. */
  emptyColor?: string;
  /** X offset from the left edge of the parent (px). */
  x?: number;
  /** Dot diameter in px. Default 10. */
  dotSize?: number;
  /** Rail width in px. Default 2. */
  railWidth?: number;
}> = ({
  height,
  dotCount,
  filledCount,
  color = "#e86c00",
  emptyColor = "#d4d4d4",
  x = 24,
  dotSize = 10,
  railWidth = 2,
}) => {
  const dots: React.ReactElement[] = [];
  for (let i = 0; i < dotCount; i++) {
    const y = ((i + 0.5) * height) / dotCount;
    const filled = i < filledCount;
    dots.push(
      <div
        key={i}
        style={{
          position: "absolute",
          left: x - dotSize / 2,
          top: y - dotSize / 2,
          width: dotSize,
          height: dotSize,
          borderRadius: "50%",
          backgroundColor: filled ? color : emptyColor,
          boxShadow: filled ? `0 0 ${dotSize}px ${color}80` : "none",
          transition: "background-color 200ms, box-shadow 200ms",
        }}
      />,
    );
  }
  return (
    <div
      style={{
        position: "absolute",
        left: x - railWidth / 2,
        top: 0,
        width: railWidth,
        height,
        background: `linear-gradient(180deg, ${color}40, ${color}10)`,
        borderRadius: railWidth,
        pointerEvents: "none",
      }}
    >
      {dots}
    </div>
  );
};

/**
 * `<Masthead>` — a small uppercase label at the top of a card, like a
 * newspaper section header ("ARTICLE", "OPINION", "BREAKING"). Renders
 * as a single inline-block with a small accent dot to the left.
 *
 * Used by Scrollytelling.
 */
export const Masthead: React.FC<{
  label: string;
  /** Color of the label and the dot. Defaults to orange accent. */
  color?: string;
  /** Font size in px. Default 18. */
  fontSize?: number;
  /** Font family. Defaults to "Inter, system-ui, sans-serif" so it reads as a small caps label. */
  fontFamily?: string;
  /** Letter spacing in px. Default 4. */
  letterSpacing?: number;
  /** Dot diameter in px. Default 6. */
  dotSize?: number;
  /** Opacity (defaults to 0.85). */
  opacity?: number;
}> = ({
  label,
  color = "#e86c00",
  fontSize = 18,
  fontFamily = "Inter, system-ui, -apple-system, sans-serif",
  letterSpacing = 4,
  dotSize = 6,
  opacity = 0.85,
}) => {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        opacity,
      }}
    >
      <div
        style={{
          width: dotSize,
          height: dotSize,
          borderRadius: "50%",
          backgroundColor: color,
          boxShadow: `0 0 ${dotSize * 1.5}px ${color}80`,
        }}
      />
      <span
        style={{
          fontSize,
          fontFamily,
          fontWeight: 700,
          color,
          letterSpacing,
          textTransform: "uppercase",
        }}
      >
        {label}
      </span>
    </div>
  );
};

/**
 * `<RotatedStamp>` — a small text label rotated -8° in a corner, like
 * a "FEATURED" stamp on a magazine cover. Uses a thin border + accent
 * text in a transparent box.
 *
 * Used by QuoteCard (top-right corner of the card).
 */
export const RotatedStamp: React.FC<{
  label: string;
  /** Color of the border + text. Defaults to orange accent. */
  color?: string;
  /** Rotation in degrees. Default -8. */
  rotation?: number;
  /** Font size in px. Default 16. */
  fontSize?: number;
  /** Opacity. Default 0.5. */
  opacity?: number;
}> = ({ label, color = "#e86c00", rotation = -8, fontSize = 16, opacity = 0.5 }) => {
  return (
    <div
      style={{
        position: "absolute",
        top: 32,
        right: 32,
        transform: `rotate(${rotation}deg)`,
        border: `2px solid ${color}`,
        borderRadius: 4,
        padding: "4px 10px",
        fontSize,
        fontWeight: 800,
        letterSpacing: 2,
        textTransform: "uppercase",
        color,
        opacity,
        fontFamily: "Inter, system-ui, -apple-system, sans-serif",
        pointerEvents: "none",
      }}
    >
      {label}
    </div>
  );
};
