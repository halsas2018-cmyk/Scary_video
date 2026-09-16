import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

// Entry point - calls registerRoot ONCE with the root component
// This file is separate from Root.tsx to avoid Fast Refresh issues
registerRoot(RemotionRoot);
