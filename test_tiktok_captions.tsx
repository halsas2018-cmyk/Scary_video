import React from "react";
import { TikTokCaptions } from "./src/TikTokCaptions";

// Test data matching the format from timestamps.json
const testWords = [
  { word: "Almost", start: 0.151, end: 0.391 },
  { word: "60%", start: 0.611, end: 1.191 },
  { word: "of", start: 1.291, end: 1.371 },
  { word: "AI", start: 1.511, end: 1.771 },
  { word: "coding", start: 1.811, end: 2.052 },
  { word: "assistance", start: 2.092, end: 2.492 },
  { word: "stumble", start: 2.532, end: 2.852 },
  { word: "on", start: 3.012, end: 3.072 },
  { word: "a", start: 3.112, end: 3.132 },
  { word: "single", start: 3.212, end: 3.492 },
  { word: "version", start: 3.532, end: 3.832 },
  { word: "rule", start: 3.872, end: 4.092 },
  { word: "in", start: 4.252, end: 4.332 },
  { word: "Rust", start: 4.392, end: 4.612 },
  { word: "Cargo", start: 4.652, end: 4.952 },
  { word: "package", start: 4.992, end: 5.272 },
  { word: "manager.", start: 5.312, end: 5.652 }
];

export const TestTikTokCaptions = () => {
  return (
    <div style={{ padding: 20 }}>
      <h2>TikTok Captions Test</h2>
      <TikTokCaptions words={testWords} />
    </div>
  );
};