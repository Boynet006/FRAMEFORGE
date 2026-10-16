"use client";

import { useCallback, useSyncExternalStore } from "react";

// Per-browser UI preferences (mode, last opened project). Kept in localStorage; every access is
// guarded because storage can be blocked (private windows, embedded previews) and the UI must
// still work with the defaults.

const EVENT = "frameforge-storage";
// Fallback when localStorage throws: values last for this page load only.
const memory = new Map<string, string | null>();

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return memory.get(key) ?? null;
  }
}

function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(EVENT, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(EVENT, cb);
  };
}

/** A string remembered in localStorage. `null` clears it. Server render and hydration use `fallback`. */
export function useStoredString<T extends string>(key: string, fallback: T | null) {
  const value = useSyncExternalStore(
    subscribe,
    () => (read(key) as T | null) ?? fallback,
    () => fallback,
  );
  const set = useCallback(
    (next: T | null) => {
      memory.set(key, next);
      try {
        if (next === null) window.localStorage.removeItem(key);
        else window.localStorage.setItem(key, next);
      } catch {
        // storage unavailable: the value just isn't remembered
      }
      window.dispatchEvent(new Event(EVENT));
    },
    [key],
  );
  return [value, set] as const;
}

export type UiMode = "simple" | "advanced";
