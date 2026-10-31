import { createContext, useContext } from "react";
import type { QueryClient } from "@tanstack/react-query";
import type { Client, Period, User } from "../../api";
import { permissions } from "../../lib/auth";

export type WorkspaceCtx = {
  cid: number;
  p: string;
  client: Client & { periods: Period[] };
  period: Period;
  user: User;
  can: ReturnType<typeof permissions>;
  base: string; // "/clients/4/062026"
};

export const WsContext = createContext<WorkspaceCtx | null>(null);

export function useWs(): WorkspaceCtx {
  const v = useContext(WsContext);
  if (!v) throw new Error("useWs outside workspace");
  return v;
}

/** Everything derived from a period's decisions. */
export function invalidatePeriod(qc: QueryClient, cid: number, p: string, opts: { decisions?: boolean } = {}) {
  qc.invalidateQueries({ queryKey: ["period", cid, p] });
  qc.invalidateQueries({ queryKey: ["suppliers", cid, p] });
  qc.invalidateQueries({ queryKey: ["table4", cid, p] });
  qc.invalidateQueries({ queryKey: ["followups", cid, p] });
  qc.invalidateQueries({ queryKey: ["dashboard"] });
  qc.invalidateQueries({ queryKey: ["client", cid] });
  if (opts.decisions !== false) qc.invalidateQueries({ queryKey: ["decisions", cid, p] });
}
