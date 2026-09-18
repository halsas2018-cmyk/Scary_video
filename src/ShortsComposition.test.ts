import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";
import { calculateShotTimingRanges, ShotAsset } from "./ShortsComposition";

describe("ShortsComposition visual timeline", () => {
  const sampleShots: ShotAsset[] = [
    {
      sentence: "Sentence one here.",
      search_term: "test",
      media_type: "video",
      visual: "Visual 1",
      duration_seconds: 3.0,
    },
    {
      sentence: "Sentence two starts now.",
      search_term: "test",
      media_type: "video",
      visual: "Visual 2",
      duration_seconds: 4.0,
    },
  ];

  const sampleWords = [
    { word: "Sentence", start: 0.5, end: 1.0 },
    { word: "one", start: 1.1, end: 1.5 },
    { word: "here.", start: 1.6, end: 2.0 },
    // Inter-sentence pause: 2.0s to 3.5s (1.5s pause)
    { word: "Sentence", start: 3.5, end: 4.0 },
    { word: "two", start: 4.1, end: 4.5 },
    { word: "starts", start: 4.6, end: 5.0 },
    { word: "now.", start: 5.1, end: 5.8 },
  ];

  it("accurately derives sentence start and end from words, including pauses", () => {
    const ranges = calculateShotTimingRanges(sampleShots, sampleWords, 30);
    expect(ranges).toHaveLength(2);
    expect(ranges[0].startSec).toBe(0.5);
    expect(ranges[0].endSec).toBe(2.0);
    expect(ranges[1].startSec).toBe(3.5);
    expect(ranges[1].endSec).toBe(5.8);
  });

  it("uses explicit shot timing fields when provided", () => {
    const explicitShots: ShotAsset[] = [
      {
        ...sampleShots[0],
        start: 0.2,
        end: 3.0,
      },
      {
        ...sampleShots[1],
        start: 4.5,
        end: 9.0,
      },
    ];
    const ranges = calculateShotTimingRanges(explicitShots, [], 30);
    expect(ranges).toHaveLength(2);
    expect(ranges[0].startSec).toBe(0.2);
    expect(ranges[0].endSec).toBe(3.0);
    expect(ranges[1].startSec).toBe(4.5);
    expect(ranges[1].endSec).toBe(9.0);
  });

  it("accurately uses timing array from timing.json when explicit shot timings are not set", () => {
    const timing = [
      { start: 0.171, end: 4.092 },
      { start: 4.492, end: 9.414 },
    ];
    const ranges = calculateShotTimingRanges(sampleShots, [], 30, timing);
    expect(ranges).toHaveLength(2);
    expect(ranges[0].startSec).toBe(0.171);
    expect(ranges[0].endSec).toBe(4.092);
    expect(ranges[1].startSec).toBe(4.492);
    expect(ranges[1].endSec).toBe(9.414);
  });

  it("handles fallback to cumulative durations when no words or explicit timing", () => {
    const ranges = calculateShotTimingRanges(sampleShots, [], 30);
    expect(ranges).toHaveLength(2);
    expect(ranges[0].startSec).toBe(0);
    expect(ranges[0].endSec).toBe(3.0);
    expect(ranges[1].startSec).toBe(3.0);
    expect(ranges[1].endSec).toBe(7.0);
  });

  it("ensures zero black gaps across production remotion_props.json", () => {
    const propsPath = path.resolve(__dirname, "../public/remotion_props.json");
    const raw = fs.readFileSync(propsPath, "utf-8");
    const data = JSON.parse(raw);
    const fps = 30;

    const ranges = calculateShotTimingRanges(data.shots, data.words, fps);
    expect(ranges).toHaveLength(data.shots.length);

    const lastWordEnd = data.words[data.words.length - 1].end;
    const compositionDuration = Math.ceil(lastWordEnd * fps);

    const OVERLAP_FRAMES = 2;
    const nominalCutFrames = data.shots.map((_: ShotAsset, idx: number) => {
      if (idx === 0) return 0;
      return Math.round(ranges[idx].startSec * fps);
    });

    for (let i = 1; i < nominalCutFrames.length; i++) {
      if (nominalCutFrames[i] <= nominalCutFrames[i - 1]) {
        nominalCutFrames[i] = nominalCutFrames[i - 1] + 1;
      }
    }

    const nominalEndFrames = data.shots.map((_: ShotAsset, idx: number) => {
      if (idx < data.shots.length - 1) {
        return nominalCutFrames[idx + 1];
      }
      const lastSentenceEndFrame = Math.ceil(ranges[idx].endSec * fps);
      return Math.max(
        nominalCutFrames[idx] + 30,
        compositionDuration || 0,
        lastSentenceEndFrame
      );
    });

    const sequencedShots = data.shots.map((shot: ShotAsset, idx: number) => {
      const nominalStart = nominalCutFrames[idx];
      const nominalEnd = nominalEndFrames[idx];
      const startFrame = idx === 0 ? 0 : Math.max(0, nominalStart - OVERLAP_FRAMES);
      const durationInFrames = Math.max(30, nominalEnd - startFrame);
      return {
        ...shot,
        startFrame,
        durationInFrames,
      };
    });

    // Verify every single frame from 0 to compositionDuration - 1 has at least one active shot
    for (let f = 0; f < compositionDuration; f++) {
      const active = sequencedShots.filter(
        (s: { startFrame: number; durationInFrames: number }) =>
          f >= s.startFrame && f < s.startFrame + s.durationInFrames
      );
      expect(active.length).toBeGreaterThanOrEqual(1);
    }

    // Verify final shot covers up to compositionDuration
    const lastShot = sequencedShots[sequencedShots.length - 1];
    expect(lastShot.startFrame + lastShot.durationInFrames).toBeGreaterThanOrEqual(compositionDuration);

    // Verify final 60 frames (1900 to 1959) are covered by the final shot
    for (let f = compositionDuration - 60; f < compositionDuration; f++) {
      expect(f).toBeGreaterThanOrEqual(lastShot.startFrame);
      expect(f).toBeLessThan(lastShot.startFrame + lastShot.durationInFrames);
    }
  });
});
