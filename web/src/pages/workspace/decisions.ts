import { useCallback, useRef } from "react";
import { useMutation, useQueryClient, type InfiniteData, type QueryClient } from "@tanstack/react-query";
import { api, type Action, type Decision, type DecisionFilter, type FinalChoice, type Page } from "../../api";
import { plural } from "../../lib/format";
import { useToast } from "../../components/ui";
import { invalidatePeriod } from "./shared";

type Pages = InfiniteData<Page<Decision>, number>;

export function decisionsKey(cid: number, p: string, f: DecisionFilter) {
  return ["decisions", cid, p, f] as const;
}

/** Apply `fn` to every cached copy of the decisions it returns a new value for. */
export function patchCachedDecisions(qc: QueryClient, cid: number, p: string, fn: (d: Decision) => Decision | null) {
  qc.setQueriesData<Pages>({ queryKey: ["decisions", cid, p] }, (old) => {
    if (!old || !Array.isArray(old.pages)) return old;
    let changed = false;
    const pages = old.pages.map((pg) => {
      let pgChanged = false;
      const items = pg.items.map((d) => {
        const n = fn(d);
        if (n && n !== d) {
          pgChanged = true;
          return n;
        }
        return d;
      });
      if (!pgChanged) return pg;
      changed = true;
      return { ...pg, items };
    });
    return changed ? { ...old, pages } : old;
  });
  qc.setQueriesData<Decision>({ queryKey: ["decision", cid, p] }, (old) => (old ? (fn(old) ?? old) : old));
}

/** The decision as it will look once `final` is applied (for optimistic updates). */
export function withFinal(d: Decision, choice: FinalChoice): Decision {
  let final: Action | null;
  if (choice === "recommended") final = d.recommended;
  else if (choice === "history") {
    if (!d.history) return d;
    final = d.history.final;
  } else final = choice;
  return { ...d, final, effective: final ?? d.recommended, done: !d.needs_human || final !== null };
}

/** Mutations for decisions: single PATCH (optimistic), bulk by ids (optimistic) or by filter. */
export function useDecisionActions(cid: number, p: string) {
  const qc = useQueryClient();
  const toast = useToast();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Rapid keyboard decisions: refresh the counts once the burst ends.
  const refreshCountsSoon = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => invalidatePeriod(qc, cid, p, { decisions: false }), 700);
  }, [qc, cid, p]);

  const patch = useMutation({
    mutationFn: (v: { id: number; final?: FinalChoice; note?: string; assignee_id?: number | null; prev?: Decision }) => {
      const body: { final?: Action | null | "history"; note?: string; assignee_id?: number | null } = {};
      if (v.final !== undefined) body.final = v.final === "recommended" ? (v.prev?.recommended ?? null) : v.final;
      if (v.note !== undefined) body.note = v.note;
      if (v.assignee_id !== undefined) body.assignee_id = v.assignee_id;
      return api.updateDecision(cid, p, v.id, body);
    },
    onMutate: (v) => {
      const snapshot: Decision[] = [];
      patchCachedDecisions(qc, cid, p, (d) => {
        if (d.id !== v.id) return null;
        snapshot.push(d);
        let n = d;
        if (v.final !== undefined) n = withFinal(n, v.final);
        if (v.note !== undefined) n = { ...n, note: v.note };
        return n;
      });
      return { snapshot: snapshot[0] };
    },
    onError: (e, _v, ctx) => {
      if (ctx?.snapshot) {
        const old = ctx.snapshot;
        patchCachedDecisions(qc, cid, p, (d) => (d.id === old.id ? old : null));
      }
      toast((e as Error).message, "error");
    },
    onSuccess: (server) => {
      patchCachedDecisions(qc, cid, p, (d) => (d.id === server.id ? server : null));
      refreshCountsSoon();
    },
  });

  const bulk = useMutation({
    mutationFn: (v: { ids?: number[]; filter?: DecisionFilter; final?: FinalChoice; note?: string; assignee_id?: number | null; label?: string }) =>
      api.bulk(cid, p, { ids: v.ids, filter: v.filter, final: v.final, note: v.note, assignee_id: v.assignee_id }),
    onMutate: (v) => {
      if (v.ids && v.final !== undefined) {
        const set = new Set(v.ids);
        const fin = v.final;
        patchCachedDecisions(qc, cid, p, (d) => (set.has(d.id) ? withFinal(d, fin) : null));
      }
    },
    onError: (e) => {
      toast((e as Error).message, "error");
      qc.invalidateQueries({ queryKey: ["decisions", cid, p] });
    },
    onSuccess: (r, v) => {
      toast(`${v.label ?? "Updated"}: ${plural(r.updated, "record")}`, "ok");
      invalidatePeriod(qc, cid, p);
    },
  });

  return { patch, bulk };
}
