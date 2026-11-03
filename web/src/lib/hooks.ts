import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type User } from "../api";

/** True when the key event comes from a text field, so shortcuts should stand aside. */
export function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t.isContentEditable;
}

/** Single-key shortcuts (no modifiers). Handlers get the event; return false to let it through. */
export function useHotkeys(map: Record<string, (e: KeyboardEvent) => void | boolean>, enabled = true) {
  const ref = useRef(map);
  ref.current = map;
  useEffect(() => {
    if (!enabled) return;
    const h = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isTyping(e)) return;
      if (document.querySelector("[role=dialog][aria-modal=true]")) return;
      const fn = ref.current[e.key];
      if (fn) {
        const r = fn(e);
        if (r !== false) e.preventDefault();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [enabled]);
}

/** Read/write a set of string params in the URL (filters persist across reloads and links). */
export function useUrlState<K extends string>(keys: readonly K[]) {
  const [sp, setSp] = useSearchParams();
  const values = Object.fromEntries(keys.map((k) => [k, sp.get(k) ?? ""])) as Record<K, string>;
  const set = useCallback(
    (patch: Partial<Record<K, string | null>>, opts: { replace?: boolean } = { replace: true }) => {
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch) as [K, string | null | undefined][]) {
            if (v === null || v === undefined || v === "") next.delete(k);
            else next.set(k, v);
          }
          return next;
        },
        { replace: opts.replace ?? true },
      );
    },
    [setSp],
  );
  return [values, set] as const;
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
}

/**
 * Users for assignee pickers. `GET /api/users` is admin-only in the contract, so for other roles we fall
 * back to "me" only (see the contract note in the hand-off).
 */
export function useAssignableUsers(me: User) {
  return useQuery({
    queryKey: ["users", "assignable", me.id],
    queryFn: async () => {
      try {
        return (await api.users()).filter((u) => u.active !== false);
      } catch {
        return [me];
      }
    },
    staleTime: 5 * 60_000,
  });
}
