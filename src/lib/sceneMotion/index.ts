// ============================================================================
// src/lib/sceneMotion/index.ts
// ============================================================================
//
// Barrel re-export for the scene-based motion hooks (sibling of
// `src/lib/idleMotion/index.ts`).
//
// **LEAF FILE — DO NOT re-export from any consumer.** The same
// import-graph rule from CLAUDE.md §4.5 (the `registry` ↔ `renderBeat`
// circular-import rule) applies: this barrel must NOT re-export from
// `src/ChartComparison3D.tsx`, `src/ChartLine.tsx`, `src/Map3D.tsx`,
// or any other consumer. If a future refactor needs a cross-barrel
// re-export, extract the shared helper to its own leaf file instead.
//
// **Hooks exported here (growing over time):**
// - `useChartReveal` — linear draw-in + subtle idle pulse for chart
//   components (Pass 2, ships with `ChartLine`).
// - `useCesiumCamera` — per-frame camera state for the Cesium render
//   loop (Pass 3, ships with `Map3D`).
//
// The barrel only re-exports hooks; it does NOT re-export component
// types, utility helpers, or constants. Components import the hook
// they need directly from this barrel; nothing imports a component
// from this barrel.
// ============================================================================

export { useChartReveal } from "./useChartReveal";
export type { ChartReveal, ChartRevealOptions } from "./useChartReveal";
