import React, { useMemo } from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { createTikTokStyleCaptions, type Caption } from "@remotion/captions";

interface TikTokCaptionsProps {
  words: { word: string; start: number; end: number }[];
}

export const TikTokCaptions: React.FC<TikTokCaptionsProps> = ({
  words,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Convert word objects to Caption format expected by remotion/captions
  // Leading space allows createTikTokStyleCaptions() to paginate correctly on word boundaries
  const captions: Caption[] = useMemo(() => {
    return words.map((w, index) => ({
      text: (index > 0 ? " " : "") + w.word,
      startMs: Math.max(0, w.start * 1000), // Ensure non-negative
      endMs: Math.max(w.start * 1000, w.end * 1000), // Ensure proper order
      timestampMs: w.start * 1000,
      confidence: 1.0,
    }));
  }, [words]);

  // Create TikTok-style caption pages
  // Lower values = faster word-by-word progression
  const SWITCH_CAPTIONS_EVERY_MS = 800; // Optimized for sync

  const result = useMemo(() => {
    if (captions.length === 0) {
      return { pages: [] };
    }
    return createTikTokStyleCaptions({
      captions,
      combineTokensWithinMilliseconds: SWITCH_CAPTIONS_EVERY_MS,
    });
  }, [captions]);

  const pages = result.pages;

  // Find the current page based on time
  const currentPage = useMemo(() => {
    if (pages.length === 0) {
      return null;
    }

    const currentTimeMs = (frame / fps) * 1000;

    // Do not show captions before the first word is spoken
    if (currentTimeMs < pages[0].startMs) {
      return null;
    }

    // Find the page that currently contains the playback time
    for (let i = 0; i < pages.length; i++) {
      const page = pages[i];
      const nextPage = pages[i + 1];

      if (nextPage !== undefined) {
        if (currentTimeMs >= page.startMs && currentTimeMs < nextPage.startMs) {
          return page;
        }
      } else {
        // Last page: display until the last token finishes (with a small 500ms buffer)
        const lastToken = page.tokens[page.tokens.length - 1];
        const pageEndMs = lastToken
          ? lastToken.toMs + 500
          : page.startMs + (page.durationMs || 1000);
        if (currentTimeMs >= page.startMs && currentTimeMs <= pageEndMs) {
          return page;
        }
      }
    }

    return null;
  }, [pages, frame, fps]);

  if (!currentPage || !currentPage.tokens || currentPage.tokens.length === 0) {
    return null;
  }

  // Highlight color - TikTok style
  const HIGHLIGHT_COLOR = "#FF006E"; // TikTok pink/red
  const REGULAR_COLOR = "white";
  const currentTimeMs = (frame / fps) * 1000;

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        paddingTop: "30%",
        padding: "0 20px",
      }}
    >
      <div
        style={{
          fontSize: 56,
          fontWeight: 700,
          lineHeight: 1.2,
          textAlign: "center",
          color: REGULAR_COLOR,
          whiteSpace: "pre-wrap", // Changed from "pre" for better wrapping
          wordBreak: "break-word", // Allow word breaking
          backgroundColor: "rgba(0, 0, 0, 0.7)",
          padding: "12px 24px",
          borderRadius: 20,
          backdropFilter: "blur(10px)",
          maxWidth: "90%",
          overflow: "hidden",
        }}
      >
        {currentPage.tokens.map((token, tokenIndex) => {
          // Check if this token is currently being spoken (fromMs and toMs are absolute timestamps)
          const isActive =
            currentTimeMs >= token.fromMs && currentTimeMs < token.toMs;

          return (
            <span
              key={`${token.fromMs}-${tokenIndex}`}
              style={{
                color: isActive ? HIGHLIGHT_COLOR : REGULAR_COLOR,
                fontWeight: isActive ? 800 : 700,
              }}
            >
              {token.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};