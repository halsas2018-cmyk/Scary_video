import { Config } from "@remotion/cli/config";

/**
 * Use ANGLE software WebGL for headless rendering.
 *
 * Without a GPU on this machine, Chromium's default headless WebGL2
 * backend can't create a context within Remotion's 28s `delayRender`
 * window, causing <ThreeCanvas> to time out during full video renders.
 *
 * Setting `ChromiumOpenGlRenderer = "angle"` enables the SwiftShader
 * software WebGL implementation, which is slow but works on any CPU.
 *
 * If you ever run this on a machine with a real GPU, change this to
 * `"desktop"` (or remove the call entirely) for much faster renders.
 */
Config.setChromiumOpenGlRenderer("angle");

/**
 * Increase the per-frame delayRender timeout from the default 28s to 2 minutes.
 *
 * Software WebGL (SwiftShader) on CPU is significantly slower than hardware
 * WebGL. The first frame in particular can take a while to compile shaders
 * and upload geometry. 28s is not enough margin for a 203-cube scene on CPU.
 *
 * 2 minutes (120_000 ms) is plenty for any frame in this project.
 *
 * If you ever switch to hardware WebGL (Config.setChromiumOpenGlRenderer("desktop")
 * on a machine with a GPU), you can lower this back to 28_000.
 */
Config.setDelayRenderTimeoutInMilliseconds(120_000);

/**
 * Horizon 0.5: tell webpack to silently drop Node built-ins from the
 * browser bundle instead of erroring on them.
 *
 * Background: the 0.5 hash helper (`scripts/lastRenderHash.mjs`) lives
 * outside `src/` so webpack never walks it. But there is a residual
 * risk that a future file added to `src/lib/` accidentally imports
 * `node:fs` / `node:crypto` / `node:path`, which would crash the
 * `still` renderer with "Module not found: Error: Can't resolve 'fs'".
 *
 * In Remotion 4.0.516, the API for modifying the webpack config is
 * `Config.overrideWebpackConfig((current) => nextConfig)`. The callback
 * receives Remotion's current webpack config and returns the merged
 * result. We use this to add a `resolve.fallback` map that tells
 * webpack: "when you see an import of `fs` (or any of the other Node
 * built-ins we know are bogus in a browser context), replace it with
 * `false`" — which webpack's resolver understands as "this module
 * does not exist in the browser bundle; don't try to follow it".
 *
 * The smoke script (`scripts/render-smoke.sh`) and the
 * `lastRenderHash.mjs` helper run OUTSIDE the webpack bundle, so
 * this alias does NOT affect their ability to use `node:fs`.
 */
Config.overrideWebpackConfig((current) => {
  return {
    ...current,
    resolve: {
      ...(current.resolve ?? {}),
      fallback: {
        ...(current.resolve?.fallback ?? {}),
        fs: false,
        path: false,
        crypto: false,
        os: false,
        util: false,
        stream: false,
        buffer: false,
        url: false,
        child_process: false,
      },
    },
  };
});
Config.setPublicLicenseKey('free-license');
Config.setLogLevel('verbose');
