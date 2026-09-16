/**
 * Sound effect URLs and defaults used by the orchestrator and the
 * per-beat caption wrapper.
 *
 * The whoosh is a free SFX from the Remotion CDN
 * (https://remotion.media/whoosh.wav), as listed in the project's
 * `.agents/skills/remotion-markup/sfx.md` skill. It plays at the
 * start of every <TransitionSeries.Transition> as a UI feedback
 * sound for the cross-fade.
 *
 * The mouse-click is a short SFX from the same CDN
 * (https://remotion.media/mouse-click.wav). It plays at the start of
 * every visible caption word inside <BeatKineticCaptions> to give the
 * typing a tactile, mechanical feel.
 *
 * The ambient track is a local file in /public (sfx-ambient.mp3) that
 * loops for the entire composition underneath the narration. Volume
 * fades in over the first second and then sits at AMBIENT_SFX_VOLUME
 * (0.15) so it doesn't compete with the narration, the whoosh, or the
 * typing clicks. Per `.agents/skills/remotion-markup/audio.md` best
 * practices for ambient sound: use `loop` + `loopVolumeCurveBehavior=
 * "extend"` so the volume callback sees a continuously incrementing
 * frame count across loops.
 *
 * Centralized here so the URLs and volumes can be tweaked in one
 * place and reused if other parts of the project ever need
 * transition / typing / ambient sounds.
 *
 * Note on 1.4 audio plan log: this file used to also export
 * `writeAudioPlanLog` (Horizon 1.4), which wrote a JSON line to
 * `out/audio-mounts.log` describing the audio plan for each render.
 * The smoke test asserted on that file. The audio plan log was the
 * replacement for the cancelled Horizon 0.4 (per-mount console.log
 * lines that never fire during a `still` render).
 *
 * As of commit that drops 1.4 (see ROADMAP.md), we no longer
 * emit the audio plan log. The orchestration works fine without
 * it — the audio streams (narration, ambient, per-transition
 * whoosh, per-word click) all mount correctly because they live
 * in the React tree, not in a side-channel log. The smoke test
 * dropped its audio-plan assertion in the same change.
 *
 * The previous `writeAudioPlanLog` / `AudioPlanLog` / `WhooshSlot`
 * exports are gone. If you want observability of the audio mix
 * later, write a per-mount <AudioMountLog> component that fires
 * on the real `npx remotion render` path (not `still`) and reads
 * from the orchestrator's state via context. That's a future
 * horizon, not a current one.
 */

import { staticFile } from "remotion";

export const TRANSITION_SFX_URL = staticFile("sfx/whoosh.wav");

/** Volume of the transition SFX (0..1). 0.5 = comfortable default. */
export const TRANSITION_SFX_VOLUME = 0.5;

export const TYPING_SFX_URL = staticFile("sfx/mouse-click.wav");

/** Volume of the typing-click SFX (0..1). 0.15 = quiet; doesn't fight the narration. */
export const TYPING_SFX_VOLUME = 0.15;

/**
 * Ambient SFX — local file in /public. Looped under the narration.
 * Volume is a callback that fades in over the first second and then
 * holds at AMBIENT_SFX_VOLUME so the ambience is felt but not heard
 * loudly.
 */
export const AMBIENT_SFX_URL = "sfx-ambient.mp3";

/**
 * Steady-state ambient volume (0..1). 0.15 = quiet bed under the
 * narration, whoosh, and typing clicks. Per audio.md best practices.
 */
export const AMBIENT_SFX_VOLUME = 0.15;

/**
 * Frames over which the ambient SFX fades in from 0 to
 * AMBIENT_SFX_VOLUME. At 30 fps, 30 frames = 1 second.
 */
export const AMBIENT_SFX_FADE_IN_FRAMES = 30;

/**
 * Duration of a single typing-click <Sequence>. 4 frames (~133ms at
 * 30fps) is the smallest stable window for mediabunny's MP4 muxer —
 * 1-frame variants throw `Cannot write to a closing writable stream`
 * during chunk flush. Used by BeatKineticCaptions to size each
 * per-word click.
 */
export const TYPING_CLICK_HOLD_FRAMES = 4;
