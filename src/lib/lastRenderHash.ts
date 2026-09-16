/* ------------------------------------------------------------------ */
/*  Last-render composition hash (Horizon 0.5).                        */
/*                                                                     */
/*  A small, dependency-free helper that:                             */
/*   1. Computes a SHA-256 over the canonical input bytes             */
/*      (`public/beats.json` + `public/timestamps.json`).             */
/*   2. Reads / writes the hash to `out/last-render.json` so the      */
/*      smoke test can skip duplicate renders.                        */
/*                                                                     */
/*  Why only beats + words (not audio files):                         */
/*   - The visible output is fully determined by beats + words.        */
/*     Changing the narration or ambient SFX doesn't change a pixel.  */
/*   - mtime+size of MP3s is not a useful content hash (ffmpeg /      */
/*     TTS re-exports produce different mtimes for identical bytes).  */
/*   - If you ever ship a true audio-affecting change (e.g. a new     */
/*     whoosh SFX mapping in `sceneSfx.ts`), bump the version string  */
/*     below and old caches will be invalidated automatically.         */
/*                                                                     */
/*  Canonical input is the two file bodies joined by a single LF,     */
/*  which is what the smoke script also computes (so the script and   */
/*  any future caller agree on the same digest).                      */
/*                                                                     */
/*  IMPORTANT: this file uses dynamic `require("node:…")` instead of  */
/*  top-level `import "node:…"` for fs/crypto/path. Remotion's         */
/*  bundler is webpack-based and resolves top-level `import` of any    */
/*  `node:*` module by failing with "Module not found: fs" because    */
/*  the file ends up in the project bundle graph (webpack walks       */
/*  `src/lib/*.ts` even if the file is never imported by a            */
/*  composition). Dynamic `require()` cannot be statically followed   */
/*  by webpack, so the Node-only modules are only pulled in by the     */
/*  bash smoke script's `node -e "require('./src/lib/lastRenderHash')"`*/
/*  invocation — never by the actual render.                           */
/* ------------------------------------------------------------------ */

/**
 * Bumped when the cache key definition changes. Old cache files
 * (which don't contain this version) are invalidated on read.
 * Current value: 1 (initial — beats + words only).
 */
export const LAST_RENDER_HASH_VERSION = 1;

const HASH_FILENAME = "last-render.json";

/**
 * Compute the SHA-256 hex digest of the canonical input pair.
 *
 * @param beatsJson  Raw bytes of `public/beats.json` (a UTF-8 string is fine).
 * @param wordsJson  Raw bytes of `public/timestamps.json`.
 * @returns 64-char lowercase hex digest, prefixed with `v<version>:`
 *          so future schema changes are backwards-incompatible by design.
 */
export const computeLastRenderHash = (
  beatsJson: string | Buffer,
  wordsJson: string | Buffer,
): string => {
  // Lazy require: never seen by webpack's static analysis, only
  // loaded when the smoke script's `node -e` actually calls this
  // function at runtime.
  const { createHash } = require("node:crypto") as typeof import("node:crypto");
  const h = createHash("sha256");
  h.update(beatsJson);
  h.update(0x0a); // LF separator, matches the bash `cat` invocation
  h.update(wordsJson);
  return `v${LAST_RENDER_HASH_VERSION}:${h.digest("hex")}`;
};

/**
 * Shape of `out/last-render.json`. Keep it tiny so the file is
 * trivial to inspect by hand and `jq`.
 */
export type LastRenderRecord = {
  /** Schema version of the cache key (mirrors `LAST_RENDER_HASH_VERSION`). */
  version: number;
  /** The hash returned by `computeLastRenderHash`, prefixed with `v<n>:`. */
  hash: string;
  /** ISO timestamp of the last successful render. */
  renderedAt: string;
  /** Duration in frames, copied from the smoke test for human inspection. */
  durationInFrames?: number;
  /** Story id (optional). Set by the smoke script from `out/story_id` or args. */
  storyId?: string;
};

const isLastRenderRecord = (v: unknown): v is LastRenderRecord => {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  return (
    typeof r.version === "number" &&
    typeof r.hash === "string" &&
    typeof r.renderedAt === "string"
  );
};

/**
 * Read the cached last-render record from `<outDir>/last-render.json`.
 * Returns `null` if the file is missing, unreadable, malformed, or
 * was written with a stale schema version. The caller should treat
 * `null` as "no usable cache" and proceed with the render.
 */
export const readLastRenderHash = (outDir: string): LastRenderRecord | null => {
  // Lazy require: see note at the top of the file.
  const { readFileSync, existsSync } = require("node:fs") as typeof import("node:fs");
  const { resolve } = require("node:path") as typeof import("node:path");
  const file = resolve(outDir, HASH_FILENAME);
  if (!existsSync(file)) return null;
  let raw: string;
  try {
    raw = readFileSync(file, "utf8");
  } catch {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isLastRenderRecord(parsed)) return null;
  if (parsed.version !== LAST_RENDER_HASH_VERSION) return null;
  return parsed;
};

/**
 * Write the last-render record. Creates `<outDir>/` if it doesn't
 * exist. Throws on I/O failure so the smoke script can surface the
 * error in CI — a silently-failed cache write is worse than no cache.
 */
export const writeLastRenderHash = (
  outDir: string,
  hash: string,
  extras: Pick<LastRenderRecord, "durationInFrames" | "storyId"> = {},
): void => {
  // Lazy require: see note at the top of the file.
  const { writeFileSync, mkdirSync } = require("node:fs") as typeof import("node:fs");
  const { resolve } = require("node:path") as typeof import("node:path");
  mkdirSync(outDir, { recursive: true });
  const file = resolve(outDir, HASH_FILENAME);
  const record: LastRenderRecord = {
    version: LAST_RENDER_HASH_VERSION,
    hash,
    renderedAt: new Date().toISOString(),
    ...(extras.durationInFrames !== undefined
      ? { durationInFrames: extras.durationInFrames }
      : {}),
    ...(extras.storyId !== undefined ? { storyId: extras.storyId } : {}),
  };
  writeFileSync(file, JSON.stringify(record, null, 2) + "\n", "utf8");
};

/** Resolve `<projectRoot>/out/last-render.json` (the canonical cache file). */
export const defaultLastRenderFile = (projectRoot: string): string => {
  // Lazy require: see note at the top of the file.
  const { join } = require("node:path") as typeof import("node:path");
  return join(projectRoot, "out", HASH_FILENAME);
};
