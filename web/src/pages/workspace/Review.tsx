import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ACTIONS,
  api,
  type Action,
  type Decision,
  type DecisionFilter,
  type DecisionSort,
  type DecisionView,
  type FinalChoice,
  type Owner,
  type SupplierRow,
} from "../../api";
import { useAssignableUsers, useDebounced, useHotkeys, useMeta, useUrlState } from "../../lib/hooks";
import { count, cx, fmtDateShort, fmtNum, inr0, inrCompact, plural } from "../../lib/format";
import {
  ACTION_KEY,
  ACTION_SHORT,
  Banner,
  Button,
  Dialog,
  EmptyState,
  ErrorNote,
  Input,
  Kbd,
  Select,
  Skeleton,
  TableSkeleton,
  Tag,
  Textarea,
} from "../../components/ui";
import { IconKeyboard, IconLock, IconSearch, IconX } from "../../components/icons";
import { DecisionDrawer, HistoryChip } from "./DecisionDrawer";
import { decisionsKey, useDecisionActions } from "./decisions";
import { useWs } from "./shared";
import { NotReconciled } from "./Workspace";

const VIEWS: { id: DecisionView; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "all", label: "All" },
  { id: "decided", label: "Decided" },
  { id: "auto", label: "Auto-cleared" },
  { id: "blocked", label: "Blocked credit" },
];
const OWNERS: Owner[] = ["Nobody", "CA", "Client", "Supplier"];
const PAGE = 200;
const ROW_H = 44;

export default function Review() {
  const { period } = useWs();
  if (!period.summary) return <NotReconciled what="Review" />;
  return <ReviewInner />;
}

function ReviewInner() {
  const { cid, p, can, period } = useWs();
  const [url, setUrl] = useUrlState(["view", "supplier", "status", "action", "owner", "assignee", "q", "sort", "d", "sq", "all_suppliers"] as const);
  const view = (VIEWS.some((v) => v.id === url.view) ? url.view : "open") as DecisionView;
  const [qText, setQText] = useState(url.q);
  const q = useDebounced(qText, 300);
  useEffect(() => {
    if (q !== url.q) setUrl({ q });
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const filter: DecisionFilter = useMemo(
    () => ({
      view,
      supplier: url.supplier || undefined,
      status_code: url.status || undefined,
      action: (url.action || undefined) as Action | undefined,
      owner: (url.owner || undefined) as Owner | undefined,
      assignee: url.assignee || undefined,
      q: url.q || undefined,
      sort: (url.sort || undefined) as DecisionSort | undefined,
    }),
    [view, url.supplier, url.status, url.action, url.owner, url.assignee, url.q, url.sort],
  );

  const list = useInfiniteQuery({
    queryKey: decisionsKey(cid, p, filter),
    queryFn: ({ pageParam }) => api.decisions(cid, p, filter, pageParam, PAGE),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined),
    staleTime: 60_000,
  });
  const rows = useMemo(() => list.data?.pages.flatMap((pg) => pg.items) ?? [], [list.data]);
  const total = list.data?.pages[0]?.total ?? 0;

  // ---- focus, selection, drawer
  const [focus, setFocus] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [allMatching, setAllMatching] = useState(false);
  const lastClicked = useRef<number | null>(null);
  const [help, setHelp] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const filterSig = JSON.stringify(filter);
  useEffect(() => {
    setSelected(new Set());
    setAllMatching(false);
    setFocus(0);
    lastClicked.current = null;
  }, [filterSig]);
  useEffect(() => {
    if (focus >= rows.length && rows.length > 0) setFocus(rows.length - 1);
  }, [rows.length, focus]);

  const drawerId = url.d ? Number(url.d) : null;
  const drawerIdx = drawerId !== null ? rows.findIndex((r) => r.id === drawerId) : -1;
  const drawerRow = drawerIdx >= 0 ? rows[drawerIdx] : null;

  const { patch, bulk } = useDecisionActions(cid, p);
  const locked = can.decide;

  const scrollRef = useRef<HTMLDivElement>(null);
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => scrollRef.current, estimateSize: () => ROW_H, overscan: 12 });

  // Load the next page when the user scrolls near the end.
  const vItems = virt.getVirtualItems();
  const lastV = vItems[vItems.length - 1];
  useEffect(() => {
    if (lastV && lastV.index >= rows.length - 30 && list.hasNextPage && !list.isFetchingNextPage) list.fetchNextPage();
  }, [lastV?.index, rows.length, list.hasNextPage, list.isFetchingNextPage]); // eslint-disable-line react-hooks/exhaustive-deps

  const moveFocus = useCallback(
    (to: number) => {
      if (!rows.length) return;
      const i = Math.max(0, Math.min(rows.length - 1, to));
      setFocus(i);
      virt.scrollToIndex(i, { align: "auto" });
      if (drawerId !== null) setUrl({ d: String(rows[i].id) });
    },
    [rows, virt, drawerId, setUrl],
  );

  const selectedIds = useMemo(() => rows.filter((r) => selected.has(r.id)).map((r) => r.id), [rows, selected]);
  const hasSelection = allMatching || selectedIds.length > 0;

  const decide = useCallback(
    (choice: FinalChoice, label: string) => {
      if (locked) return;
      if (allMatching) {
        bulk.mutate({ filter, final: choice, label });
        setSelected(new Set());
        setAllMatching(false);
        return;
      }
      if (selectedIds.length > 0) {
        bulk.mutate({ ids: selectedIds, final: choice, label });
        setSelected(new Set());
        return;
      }
      const r = rows[focus];
      if (!r) return;
      if (choice === "history" && !r.history) return;
      patch.mutate({ id: r.id, final: choice, prev: r });
      if (focus < rows.length - 1) moveFocus(focus + 1);
    },
    [locked, allMatching, selectedIds, rows, focus, bulk, patch, filter, moveFocus],
  );

  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const onCheck = (idx: number, shift: boolean) => {
    const id = rows[idx].id;
    setAllMatching(false);
    if (shift && lastClicked.current !== null) {
      const [a, b] = [Math.min(lastClicked.current, idx), Math.max(lastClicked.current, idx)];
      const turnOn = !selected.has(id);
      setSelected((s) => {
        const n = new Set(s);
        for (let i = a; i <= b; i++) {
          if (turnOn) n.add(rows[i].id);
          else n.delete(rows[i].id);
        }
        return n;
      });
    } else toggle(id);
    lastClicked.current = idx;
    setFocus(idx);
  };

  useHotkeys(
    {
      j: () => moveFocus(focus + 1),
      ArrowDown: () => moveFocus(focus + 1),
      k: () => moveFocus(focus - 1),
      ArrowUp: () => moveFocus(focus - 1),
      a: () => decide("Accept", "Accepted"),
      r: () => decide("Reject", "Rejected"),
      p: () => decide("Pending", "Kept pending"),
      n: () => decide("No IMS action", "Set to No IMS action"),
      u: () => decide("recommended", "Recommendation used"),
      h: () => decide("history", "Same as last month"),
      x: () => {
        if (rows[focus]) onCheck(focus, false);
      },
      Enter: () => {
        if (rows[focus]) setUrl({ d: String(rows[focus].id) });
      },
      Escape: () => {
        if (drawerId !== null) setUrl({ d: null });
        else {
          setSelected(new Set());
          setAllMatching(false);
        }
      },
      "/": () => searchRef.current?.focus(),
      "?": () => setHelp((h) => !h),
      "]": () => stepSupplier(1),
      "[": () => stepSupplier(-1),
    },
    true,
  );

  // Suppliers (left pane)
  const [sqText, setSqText] = useState(url.sq);
  const sq = useDebounced(sqText, 250);
  useEffect(() => {
    if (sq !== url.sq) setUrl({ sq });
  }, [sq]); // eslint-disable-line react-hooks/exhaustive-deps
  const onlyOpen = url.all_suppliers !== "1";
  const suppliers = useQuery({
    queryKey: ["suppliers", cid, p, url.sq, onlyOpen],
    queryFn: () => api.suppliers(cid, p, url.sq || undefined, onlyOpen),
    placeholderData: (prev) => prev,
  });
  const supplierRows = suppliers.data ?? [];
  // Keep showing a supplier that just dropped out of the "only open" list.
  const lastSupplier = useRef<SupplierRow | null>(null);
  const found = supplierRows.find((s) => s.gstin === url.supplier) ?? null;
  if (found) lastSupplier.current = found;
  const currentSupplier = found ?? (url.supplier && lastSupplier.current?.gstin === url.supplier ? lastSupplier.current : null);

  /** The supplier after the current one (for "done, next"). */
  function nextSupplierAfter(gstin: string): string | null {
    const i = supplierRows.findIndex((s) => s.gstin === gstin);
    const rest = supplierRows.slice(i + 1).concat(i >= 0 ? supplierRows.slice(0, i) : []);
    return rest.find((s) => s.open > 0 && s.gstin !== gstin)?.gstin ?? null;
  }
  const finishSupplier = (gstin: string) => {
    const next = nextSupplierAfter(gstin);
    setUrl({ supplier: next, d: null });
  };

  function stepSupplier(delta: number) {
    if (!supplierRows.length) return;
    const i = supplierRows.findIndex((s) => s.gstin === url.supplier);
    const next = i < 0 ? (delta > 0 ? 0 : supplierRows.length - 1) : i + delta;
    if (next < 0) return setUrl({ supplier: null, d: null });
    if (next >= supplierRows.length) return;
    setUrl({ supplier: supplierRows[next].gstin, d: null });
  }

  const itcLoaded = rows.reduce((s, r) => s + (r.itc_at_stake || 0), 0);
  const filtersActive = !!(url.status || url.action || url.owner || url.assignee || url.q);
  const historyCount = period.summary?.history_suggestions ?? 0;
  const historyInView = rows.filter((r) => r.history && r.final === null).length;

  return (
    <div className="flex h-[calc(100vh-128px)] min-h-[520px]">
      <SupplierPane
        rows={supplierRows}
        loading={suppliers.isLoading}
        selected={url.supplier}
        onSelect={(g) => setUrl({ supplier: g, d: null })}
        search={sqText}
        onSearch={setSqText}
        onlyOpen={onlyOpen}
        onOnlyOpen={(v) => setUrl({ all_suppliers: v ? null : "1" })}
        totalOpen={period.summary?.open ?? 0}
      />

      <section className="flex-1 min-w-0 flex flex-col bg-surface">
        {locked && (
          <div className="px-4 pt-3">
            <Banner tone="review" icon={<IconLock />}>
              Read only. {locked}
            </Banner>
          </div>
        )}

        {currentSupplier && (
          <SupplierHeader
            s={currentSupplier}
            rows={rows}
            locked={locked}
            busy={bulk.isPending}
            onClear={() => setUrl({ supplier: null })}
            onAcceptAll={() =>
              bulk.mutate(
                { filter: { view: "open", supplier: currentSupplier.gstin }, final: "recommended", label: `Recommendations used for ${currentSupplier.name}` },
                { onSuccess: () => finishSupplier(currentSupplier.gstin) },
              )
            }
            onHistory={() => bulk.mutate({ filter: { view: "open", supplier: currentSupplier.gstin }, final: "history", label: "Same as last month" })}
            onNext={() => finishSupplier(currentSupplier.gstin)}
          />
        )}

        {/* View tabs and filters */}
        <div className="px-4 pt-3 pb-2 border-b border-rule space-y-2.5">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-1" role="tablist" aria-label="Which decisions">
              {VIEWS.map((v) => (
                <button
                  key={v.id}
                  role="tab"
                  aria-selected={view === v.id}
                  onClick={() => setUrl({ view: v.id === "open" ? null : v.id, d: null })}
                  className={cx(
                    "h-7 px-2.5 rounded-md text-sm",
                    view === v.id ? "bg-ink text-white font-medium" : "text-ink-2 hover:bg-sunken",
                  )}
                >
                  {v.label}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              {historyCount > 0 && !locked && (
                <Button
                  size="sm"
                  variant="quiet"
                  busy={bulk.isPending && bulk.variables?.final === "history"}
                  onClick={() =>
                    bulk.mutate(
                      currentSupplier || filtersActive
                        ? { filter: { ...filter, view: "open" }, final: "history", label: "Last month's decisions applied" }
                        : { filter: { view: "open" }, final: "history", label: "Last month's decisions applied" },
                    )
                  }
                  title="Apply what staff decided last month for the same supplier in the same situation"
                >
                  Apply last month's decisions ({count(currentSupplier || filtersActive ? historyInView : historyCount)})
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setHelp(true)} title="Keyboard shortcuts (?)">
                <IconKeyboard /> Shortcuts
              </Button>
            </div>
          </div>
          <Filters
            url={url}
            setUrl={setUrl}
            qText={qText}
            setQText={setQText}
            searchRef={searchRef}
          />
        </div>

        {/* Count line */}
        <div className="px-4 h-9 flex items-center justify-between gap-3 text-sm border-b border-rule bg-sunken">
          <div>
            {list.isLoading ? (
              <Skeleton className="h-3.5 w-56" />
            ) : (
              <>
                <b className="font-semibold num">{count(total)}</b> {viewNoun(view, total)}
                {total > 0 && (
                  <span className="text-muted">
                    {" "}
                    · {inr0(itcLoaded)} ITC at stake{rows.length < total ? ` in the first ${count(rows.length)}` : ""}
                  </span>
                )}
                {view === "open" && rows.some((r) => r.final !== null) && (
                  <span className="text-ok ml-2">
                    {plural(rows.filter((r) => r.final !== null).length, "decided just now", "decided just now")}
                    <button className="ml-1.5 text-accent hover:underline" onClick={() => list.refetch()}>
                      Clear them from the list
                    </button>
                  </span>
                )}
              </>
            )}
          </div>
          {list.isFetching && !list.isLoading && <span className="text-xs text-muted">Updating…</span>}
        </div>

        {/* Table */}
        <div ref={scrollRef} className="flex-1 overflow-auto relative" tabIndex={-1}>
          {list.isLoading ? (
            <TableSkeleton rows={12} cols={8} />
          ) : list.error ? (
            <div className="p-4">
              <ErrorNote error={list.error} />
            </div>
          ) : rows.length === 0 ? (
            <EmptyRows
              view={view}
              filtered={filtersActive}
              supplier={url.supplier ? (currentSupplier?.name ?? url.supplier) : undefined}
              onNext={url.supplier ? () => finishSupplier(url.supplier) : undefined}
              onReset={() => setUrl({ status: null, action: null, owner: null, assignee: null, q: null })}
            />
          ) : (
            <DecisionTable
              rows={rows}
              virt={virt}
              focus={focus}
              selected={selected}
              allMatching={allMatching}
              locked={locked}
              onFocus={setFocus}
              onCheck={onCheck}
              onOpen={(id) => {
                const i = rows.findIndex((x) => x.id === id);
                if (i >= 0) setFocus(i);
                setUrl({ d: String(id) });
              }}
              onDecide={(r, a) => patch.mutate({ id: r.id, final: r.final === a ? null : a, prev: r })}
              onSelectAllLoaded={(on) => {
                setAllMatching(false);
                setSelected(on ? new Set(rows.map((r) => r.id)) : new Set());
              }}
            />
          )}
        </div>

        {/* Bulk bar */}
        {hasSelection ? (
          <BulkBar
            n={allMatching ? total : selectedIds.length}
            allMatching={allMatching}
            canSelectAll={!allMatching && total > selectedIds.length}
            total={total}
            itc={allMatching ? null : rows.filter((r) => selected.has(r.id)).reduce((s, r) => s + r.itc_at_stake, 0)}
            locked={locked}
            busy={bulk.isPending}
            onSelectAll={() => setAllMatching(true)}
            onDecide={decide}
            onAssign={(uid) => {
              const label = uid === null ? "Unassigned" : "Assigned";
              if (allMatching) bulk.mutate({ filter, assignee_id: uid, label });
              else bulk.mutate({ ids: selectedIds, assignee_id: uid, label });
            }}
            onNote={() => setNoteOpen(true)}
            onClear={() => {
              setSelected(new Set());
              setAllMatching(false);
            }}
          />
        ) : (
          <div className="h-9 px-4 flex items-center gap-4 border-t border-rule text-xs text-muted bg-sunken">
            <span>
              <Kbd>j</Kbd> <Kbd>k</Kbd> move
            </span>
            <span>
              <Kbd>a</Kbd> <Kbd>r</Kbd> <Kbd>p</Kbd> <Kbd>n</Kbd> decide
            </span>
            <span>
              <Kbd>u</Kbd> use recommendation
            </span>
            <span>
              <Kbd>x</Kbd> select, shift-click for a range
            </span>
            <span>
              <Kbd>Enter</Kbd> details
            </span>
            <span>
              <Kbd>[</Kbd> <Kbd>]</Kbd> supplier
            </span>
            <button className="ml-auto text-accent hover:underline" onClick={() => setHelp(true)}>
              All shortcuts
            </button>
          </div>
        )}
      </section>

      {drawerRow && (
        <DecisionDrawer
          decision={drawerRow}
          onClose={() => setUrl({ d: null })}
          position={`${count(drawerIdx + 1)} of ${count(total)}`}
          onPrev={drawerIdx > 0 ? () => moveFocus(drawerIdx - 1) : undefined}
          onNext={drawerIdx < rows.length - 1 ? () => moveFocus(drawerIdx + 1) : undefined}
        />
      )}
      {drawerId !== null && !drawerRow && !list.isLoading && <MissingDrawer id={drawerId} onClose={() => setUrl({ d: null })} />}

      <ShortcutHelp open={help} onClose={() => setHelp(false)} />
      <BulkNoteDialog
        open={noteOpen}
        n={allMatching ? total : selectedIds.length}
        onClose={() => setNoteOpen(false)}
        onSave={(note) => {
          if (allMatching) bulk.mutate({ filter, note, label: "Note added" });
          else bulk.mutate({ ids: selectedIds, note, label: "Note added" });
          setNoteOpen(false);
        }}
      />
    </div>
  );
}

function viewNoun(view: DecisionView, n: number) {
  const s = n === 1;
  switch (view) {
    case "open":
      return "open";
    case "all":
      return s ? "record" : "records";
    case "decided":
      return "decided";
    case "auto":
      return "cleared automatically";
    case "blocked":
      return s ? "possible blocked-credit item" : "possible blocked-credit items";
  }
}

/** A decision linked by ?d= that isn't in the loaded list (e.g. from the Blocked tab). */
function MissingDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { cid, p } = useWs();
  const q = useQuery({ queryKey: ["decision", cid, p, id], queryFn: () => api.decision(cid, p, id) });
  if (!q.data) return null;
  return <DecisionDrawer decision={q.data} onClose={onClose} />;
}

// ---------------------------------------------------------------------------------------------------------

function Filters({
  url,
  setUrl,
  qText,
  setQText,
  searchRef,
}: {
  url: Record<string, string>;
  setUrl: (p: Record<string, string | null>) => void;
  qText: string;
  setQText: (s: string) => void;
  searchRef: React.RefObject<HTMLInputElement>;
}) {
  const meta = useMeta();
  const statuses = meta.data?.statuses ?? {};
  const active = url.status || url.action || url.owner || url.assignee || url.q;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="relative">
        <IconSearch className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" size={14} />
        <Input
          ref={searchRef}
          value={qText}
          onChange={(e) => setQText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") (e.target as HTMLInputElement).blur();
          }}
          placeholder="Search doc no, supplier, reason  ( / )"
          className="h-7 pl-7 w-64 text-sm"
        />
      </div>
      <Select aria-label="Status" value={url.status} onChange={(e) => setUrl({ status: e.target.value })} className="h-7 text-sm w-auto max-w-[220px]">
        <option value="">Any status</option>
        {Object.entries(statuses).map(([code, label]) => (
          <option key={code} value={code}>
            {label}
          </option>
        ))}
      </Select>
      <Select aria-label="Action" value={url.action} onChange={(e) => setUrl({ action: e.target.value })} className="h-7 text-sm w-auto">
        <option value="">Any action</option>
        {ACTIONS.map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </Select>
      <Select aria-label="Who acts" value={url.owner} onChange={(e) => setUrl({ owner: e.target.value })} className="h-7 text-sm w-auto">
        <option value="">Anyone acts</option>
        {OWNERS.map((o) => (
          <option key={o} value={o}>
            {o === "Nobody" ? "Nobody acts" : `${o} acts`}
          </option>
        ))}
      </Select>
      <label className="inline-flex items-center gap-1.5 text-sm text-ink-2 h-7 px-2 rounded-md border border-rule-strong bg-surface cursor-pointer">
        <input type="checkbox" checked={url.assignee === "me"} onChange={(e) => setUrl({ assignee: e.target.checked ? "me" : null })} className="accent-[var(--color-accent)]" />
        Assigned to me
      </label>
      <Select aria-label="Sort" value={url.sort} onChange={(e) => setUrl({ sort: e.target.value })} className="h-7 text-sm w-auto">
        <option value="">Most ITC first</option>
        <option value="supplier">By supplier</option>
        <option value="status">By status</option>
      </Select>
      {active && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setQText("");
            setUrl({ status: null, action: null, owner: null, assignee: null, q: null });
          }}
        >
          <IconX size={12} /> Clear filters
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------

function SupplierPane({
  rows,
  loading,
  selected,
  onSelect,
  search,
  onSearch,
  onlyOpen,
  onOnlyOpen,
  totalOpen,
}: {
  rows: SupplierRow[];
  loading: boolean;
  selected: string;
  onSelect: (g: string | null) => void;
  search: string;
  onSearch: (s: string) => void;
  onlyOpen: boolean;
  onOnlyOpen: (v: boolean) => void;
  totalOpen: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => ref.current, estimateSize: () => 58, overscan: 10 });
  const openSuppliers = rows.filter((r) => r.open > 0).length;
  return (
    <aside className="hidden lg:flex w-[272px] shrink-0 border-r border-rule bg-sunken flex-col">
      <div className="p-3 border-b border-rule space-y-2">
        <div className="relative">
          <IconSearch className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" size={14} />
          <Input value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Find supplier or GSTIN" className="h-7 pl-7 text-sm" />
        </div>
        <div className="flex items-center justify-between text-xs text-muted">
          <span>
            {loading ? "Loading…" : `${count(rows.length)} suppliers${onlyOpen ? " with open items" : ""}`}
          </span>
          <label className="inline-flex items-center gap-1 cursor-pointer">
            <input type="checkbox" checked={onlyOpen} onChange={(e) => onOnlyOpen(e.target.checked)} className="accent-[var(--color-accent)]" />
            Only open
          </label>
        </div>
      </div>
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={cx("text-left px-3 py-2 border-b border-rule", !selected ? "bg-surface shadow-[inset_3px_0_0_var(--color-accent)]" : "hover:bg-surface/70")}
      >
        <div className="flex items-baseline justify-between">
          <span className="font-medium">All suppliers</span>
          <span className="num text-sm">{count(totalOpen)} open</span>
        </div>
        <div className="text-xs text-muted">{openSuppliers > 0 ? `${count(openSuppliers)} suppliers to decide` : "Nothing open"}</div>
      </button>
      <div ref={ref} className="flex-1 overflow-auto">
        {loading ? (
          <div className="p-3 space-y-3">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="p-4 text-sm text-muted">{search ? "No supplier matches." : onlyOpen ? "No supplier has open items." : "No suppliers."}</p>
        ) : (
          <div style={{ height: virt.getTotalSize(), position: "relative" }}>
            {virt.getVirtualItems().map((vi) => {
              const s = rows[vi.index];
              const active = s.gstin === selected;
              return (
                <button
                  key={s.gstin + vi.index}
                  type="button"
                  onClick={() => onSelect(s.gstin)}
                  title={s.statuses}
                  style={{ position: "absolute", top: 0, left: 0, right: 0, height: vi.size, transform: `translateY(${vi.start}px)` }}
                  className={cx(
                    "text-left px-3 py-1.5 border-b border-rule/70",
                    active ? "bg-surface shadow-[inset_3px_0_0_var(--color-accent)]" : "hover:bg-surface/70",
                  )}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={cx("truncate text-sm", active ? "font-semibold" : "font-medium")}>{s.name || s.gstin}</span>
                    <span className={cx("num text-sm shrink-0", s.open > 0 ? "text-ink" : "text-faint")}>{s.open > 0 ? count(s.open) : "✓"}</span>
                  </div>
                  <div className="flex items-center justify-between gap-2 mt-0.5">
                    <span className="flex items-center gap-1 min-w-0">
                      {!s.in_books && <Tag tone="review">never in books</Tag>}
                      <span className="text-xs text-muted truncate">{supplierHint(s)}</span>
                    </span>
                    <span className="num text-xs text-muted shrink-0">{s.itc_open > 0 ? inrCompact(s.itc_open) : ""}</span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}

/** The supplier's suggestion, unless it only repeats the open count; then its main status. */
function supplierHint(s: SupplierRow): string {
  if (!s.suggestion || /^\d+ open\b.*see the decisions/i.test(s.suggestion)) return s.main_status;
  return s.suggestion;
}

function SupplierHeader({
  s,
  rows,
  locked,
  busy,
  onClear,
  onAcceptAll,
  onHistory,
  onNext,
}: {
  s: SupplierRow;
  rows: Decision[];
  locked: string | null;
  busy: boolean;
  onClear: () => void;
  onAcceptAll: () => void;
  onHistory: () => void;
  onNext: () => void;
}) {
  // The most common "last month" decision among this supplier's open rows.
  const hist = useMemo(() => {
    if (s.history_final && s.history_count) return { action: s.history_final, n: s.history_count };
    const m = new Map<Action, number>();
    for (const r of rows) if (r.history && r.final === null && r.supplier_gstin === s.gstin) m.set(r.history.final, (m.get(r.history.final) ?? 0) + 1);
    let best: [Action, number] | null = null;
    for (const e of m) if (!best || e[1] > best[1]) best = e;
    const n = [...m.values()].reduce((a, b) => a + b, 0);
    return best ? { action: best[0], n } : null;
  }, [rows, s.gstin, s.history_final, s.history_count]);
  return (
    <div className="px-4 py-3 border-b border-rule">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-lg font-semibold truncate max-w-[440px]">{s.name || "Unknown supplier"}</h2>
            <span className="code text-sm text-muted">{s.gstin}</span>
            {!s.in_books && <Tag tone="review">never in books</Tag>}
            {s.followup_status && <Tag>{`Follow-up: ${s.followup_status.replace("_", " ")}`}</Tag>}
            <button onClick={onClear} className="text-xs text-accent hover:underline ml-1">
              Show all suppliers
            </button>
          </div>
          <div className="text-sm text-muted mt-1 num">
            {count(s.records_2b)} in 2B · {count(s.entries_books)} in books · {count(s.matched)} matched · ITC 2B {inr0(s.itc_2b)} · books {inr0(s.itc_books)} · to claim {inr0(s.itc_claim)}
          </div>
          {supplierHint(s) && <div className="text-sm text-ink-2 mt-1">{supplierHint(s)}</div>}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {hist && (
            <Button size="sm" variant="secondary" busy={busy} disabledReason={locked} onClick={onHistory} title="Apply last month's decisions for this supplier">
              Same as last month: {ACTION_SHORT[hist.action]} ({count(hist.n)})
            </Button>
          )}
          {s.open > 0 ? (
            <Button size="sm" variant="primary" busy={busy} disabledReason={locked} onClick={onAcceptAll} title="Use TaxMind's recommendation for every open item of this supplier, then go to the next supplier">
              Accept all recommendations ({count(s.open)})
            </Button>
          ) : (
            <Button size="sm" variant="secondary" onClick={onNext}>
              Next supplier
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------

function sumTax(docs: { tax: number }[]) {
  return docs.reduce((s, d) => s + (d.tax || 0), 0);
}
function docNos(docs: { doc_no: string }[]) {
  if (!docs.length) return null;
  const first = docs[0].doc_no || "(no number)";
  return docs.length > 1 ? `${first} +${docs.length - 1}` : first;
}

const COLS = [
  { w: 32 }, // select
  { w: 162, label: "Status" },
  { w: 166, label: "Recommended → final" },
  { w: 54, label: "Conf." },
  { w: 62, label: "Acts" },
  { w: 136, label: "Doc no. books / 2B" },
  { w: 54, label: "Date" },
  { w: 90, label: "Tax 2B ₹", r: true },
  { w: 90, label: "Tax books ₹", r: true },
  { w: 96, label: "ITC to claim ₹", r: true },
  { w: 200, label: "Reason" },
];

function DecisionTable({
  rows,
  virt,
  focus,
  selected,
  allMatching,
  locked,
  onFocus,
  onCheck,
  onOpen,
  onDecide,
  onSelectAllLoaded,
}: {
  rows: Decision[];
  virt: ReturnType<typeof useVirtualizer<HTMLDivElement, Element>>;
  focus: number;
  selected: Set<number>;
  allMatching: boolean;
  locked: string | null;
  onFocus: (i: number) => void;
  onCheck: (i: number, shift: boolean) => void;
  onOpen: (id: number) => void;
  onDecide: (r: Decision, a: Action) => void;
  onSelectAllLoaded: (on: boolean) => void;
}) {
  const items = virt.getVirtualItems();
  const padTop = items.length ? items[0].start : 0;
  const padBottom = items.length ? virt.getTotalSize() - items[items.length - 1].end : 0;
  const allOn = allMatching || (rows.length > 0 && rows.every((r) => selected.has(r.id)));
  const someOn = !allOn && rows.some((r) => selected.has(r.id));
  const totalW = COLS.reduce((s, c) => s + c.w, 0);

  return (
    <table className="tbl" style={{ tableLayout: "fixed", minWidth: totalW }}>
      <colgroup>
        {COLS.map((c, i) => (
          <col key={i} style={{ width: i === COLS.length - 1 ? undefined : c.w, minWidth: c.w }} />
        ))}
      </colgroup>
      <thead>
        <tr>
          <th className="!px-2.5">
            <input
              type="checkbox"
              aria-label="Select all loaded rows"
              checked={allOn}
              ref={(el) => {
                if (el) el.indeterminate = someOn;
              }}
              onChange={(e) => onSelectAllLoaded(e.target.checked)}
              className="accent-[var(--color-accent)]"
            />
          </th>
          {COLS.slice(1).map((c) => (
            <th key={c.label} className={c.r ? "r" : ""}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {padTop > 0 && (
          <tr aria-hidden="true">
            <td colSpan={COLS.length} style={{ height: padTop, padding: 0, border: 0 }} />
          </tr>
        )}
        {items.map((vi) => {
          const r = rows[vi.index];
          const isSel = allMatching || selected.has(r.id);
          const isFocus = vi.index === focus;
          const decided = r.final !== null;
          const t2b = sumTax(r.portal);
          const tb = sumTax(r.books);
          const date = r.books[0]?.doc_date ?? r.portal[0]?.doc_date ?? null;
          return (
            <tr
              key={r.id}
              data-index={vi.index}
              style={{ height: ROW_H }}
              aria-selected={isSel}
              onClick={() => onFocus(vi.index)}
              onDoubleClick={() => onOpen(r.id)}
              className={cx(
                "cursor-default",
                isSel ? "[&>td]:bg-accent-soft" : isFocus ? "[&>td]:bg-[#f3f6fa]" : "hover:[&>td]:bg-[#f8f9fb]",
                isFocus && "[&>td:first-child]:shadow-[inset_3px_0_0_var(--color-accent)]",
              )}
            >
              <td className="!px-2.5">
                <input
                  type="checkbox"
                  aria-label={`Select ${r.supplier_name} ${docNos(r.books) ?? docNos(r.portal) ?? ""}`}
                  checked={isSel}
                  onClick={(e) => {
                    e.stopPropagation();
                    onCheck(vi.index, e.shiftKey);
                  }}
                  onChange={() => {}}
                  className="accent-[var(--color-accent)]"
                />
              </td>
              <td className="overflow-hidden">
                <div className={cx("truncate text-sm", decided ? "text-muted" : "text-ink")} title={r.status}>
                  {r.status}
                </div>
                <div className="flex items-center gap-1 mt-0.5 overflow-hidden">
                  {r.blocked.length > 0 && <Tag tone="review" title={r.blocked.map((b) => `${b.label} (${b.section})`).join("; ")}>17(5)?</Tag>}
                  {r.history && <HistoryChip h={r.history} compact />}
                  {!r.blocked.length && !r.history && <span className="text-2xs text-faint truncate">{r.supplier_name}</span>}
                </div>
              </td>
              <td>
                <div className="flex items-center gap-1.5">
                  <span className="w-[44px] shrink-0 text-xs text-muted truncate" title={`TaxMind recommends ${r.recommended}`}>
                    {ACTION_SHORT[r.recommended]}
                  </span>
                  <span className="text-faint text-xs">→</span>
                  <span className="inline-flex rounded border border-rule-strong overflow-hidden" role="group" aria-label="Final decision">
                    {ACTIONS.map((a) => {
                      const on = r.final === a;
                      const isRec = r.final === null && r.recommended === a;
                      return (
                        <button
                          key={a}
                          type="button"
                          disabled={!!locked}
                          title={locked ?? `${a} (${ACTION_KEY[a]})${on ? " – click again to clear" : ""}`}
                          aria-pressed={on}
                          onClick={(e) => {
                            e.stopPropagation();
                            onFocus(vi.index);
                            onDecide(r, a);
                          }}
                          className={cx(
                            "w-[25px] h-[22px] text-[11px] font-semibold border-l border-rule first:border-l-0 disabled:cursor-not-allowed",
                            on
                              ? a === "Accept"
                                ? "bg-ok text-white"
                                : a === "Reject"
                                  ? "bg-high text-white"
                                  : a === "Pending"
                                    ? "bg-review text-white"
                                    : "bg-ink-2 text-white"
                              : isRec
                                ? "bg-sunken text-ink underline decoration-dotted underline-offset-2"
                                : "bg-surface text-faint hover:text-ink hover:bg-sunken",
                          )}
                        >
                          {ACTION_KEY[a].toUpperCase()}
                        </button>
                      );
                    })}
                  </span>
                </div>
              </td>
              <td className={cx("text-xs", r.confidence === "High" ? "text-ok" : r.confidence === "Low" ? "text-high" : "text-review")}>{r.confidence === "Medium" ? "Med" : r.confidence}</td>
              <td className="text-xs text-ink-2">{r.owner}</td>
              <td className="overflow-hidden">
                <div className="code text-xs truncate" title={r.books.map((d) => d.doc_no).join(", ")}>
                  {docNos(r.books) ?? <span className="text-faint font-sans">not in books</span>}
                </div>
                <div className="code text-xs text-muted truncate" title={r.portal.map((d) => d.doc_no).join(", ")}>
                  {docNos(r.portal) ?? <span className="text-faint font-sans">not in 2B</span>}
                </div>
              </td>
              <td className="text-xs num text-ink-2">{fmtDateShort(date)}</td>
              <td className="r num">{r.portal.length ? fmtNum(t2b) : <span className="text-faint">–</span>}</td>
              <td className={cx("r num", r.portal.length > 0 && r.books.length > 0 && Math.abs(t2b - tb) > 0.5 && "text-review font-medium")}>
                {r.books.length ? fmtNum(tb) : <span className="text-faint">–</span>}
              </td>
              <td className="r num font-medium">{fmtNum(r.itc_to_claim)}</td>
              <td className="overflow-hidden">
                <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(r.id); }} className="w-full text-left text-xs text-ink-2 line-clamp-2 leading-snug hover:text-ink max-h-[2.8em] overflow-hidden" title="Open details (Enter)">
                  {r.reason}
                </button>
              </td>
            </tr>
          );
        })}
        {padBottom > 0 && (
          <tr aria-hidden="true">
            <td colSpan={COLS.length} style={{ height: padBottom, padding: 0, border: 0 }} />
          </tr>
        )}
      </tbody>
    </table>
  );
}

function EmptyRows({ view, filtered, supplier, onReset, onNext }: { view: DecisionView; filtered: boolean; supplier?: string; onReset: () => void; onNext?: () => void }) {
  if (filtered)
    return (
      <EmptyState title="Nothing matches these filters" action={<Button onClick={onReset}>Clear filters</Button>}>
        Try another status or action, or clear the search.
      </EmptyState>
    );
  if (view === "open")
    return (
      <EmptyState
        title={supplier ? `Nothing open for ${supplier}` : "Nothing open. Every decision is made."}
        action={supplier && onNext ? <Button variant="primary" onClick={onNext}>Next supplier with open items</Button> : undefined}
      >
        {supplier ? "Everything for this supplier is decided." : "Submit the month for review from the Close tab."}
      </EmptyState>
    );
  return <EmptyState title="No records in this view" />;
}

// ---------------------------------------------------------------------------------------------------------

function BulkBar({
  n,
  allMatching,
  canSelectAll,
  total,
  itc,
  locked,
  busy,
  onSelectAll,
  onDecide,
  onAssign,
  onNote,
  onClear,
}: {
  n: number;
  allMatching: boolean;
  canSelectAll: boolean;
  total: number;
  itc: number | null;
  locked: string | null;
  busy: boolean;
  onSelectAll: () => void;
  onDecide: (c: FinalChoice, label: string) => void;
  onAssign: (uid: number | null) => void;
  onNote: () => void;
  onClear: () => void;
}) {
  const { user } = useWs();
  const users = useAssignableUsers(user);
  return (
    <div className="border-t border-accent-line bg-accent-soft px-4 py-2 flex items-center gap-2 flex-wrap sticky bottom-0 z-10" role="region" aria-label="Bulk actions">
      <div className="text-sm mr-2">
        <b className="font-semibold num">{count(n)}</b> {allMatching ? "matching this filter" : "selected"}
        {itc !== null && <span className="text-muted"> · {inr0(itc)} ITC</span>}
        {canSelectAll && (
          <button className="ml-2 text-accent font-medium hover:underline" onClick={onSelectAll}>
            Select all {count(total)} matching this filter
          </button>
        )}
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        <Button size="sm" variant="secondary" className="!text-ok" disabledReason={locked} busy={busy} onClick={() => onDecide("Accept", "Accepted")}>
          Accept <Kbd>a</Kbd>
        </Button>
        <Button size="sm" variant="secondary" className="!text-high" disabledReason={locked} onClick={() => onDecide("Reject", "Rejected")}>
          Reject <Kbd>r</Kbd>
        </Button>
        <Button size="sm" variant="secondary" className="!text-review" disabledReason={locked} onClick={() => onDecide("Pending", "Kept pending")}>
          Pending <Kbd>p</Kbd>
        </Button>
        <Button size="sm" variant="secondary" disabledReason={locked} onClick={() => onDecide("No IMS action", "Set to No IMS action")}>
          No IMS action <Kbd>n</Kbd>
        </Button>
        <Button size="sm" variant="primary" disabledReason={locked} onClick={() => onDecide("recommended", "Recommendation used")}>
          Use recommendation <Kbd>u</Kbd>
        </Button>
        <Button size="sm" variant="secondary" disabledReason={locked} onClick={() => onDecide("history", "Same as last month")} title="Apply last month's decision where there is one (h)">
          Same as last month
        </Button>
        <Select
          aria-label="Assign to"
          value=""
          disabled={!!locked}
          onChange={(e) => {
            if (e.target.value === "") return;
            onAssign(e.target.value === "none" ? null : Number(e.target.value));
          }}
          className="h-7 text-sm w-auto"
        >
          <option value="">Assign to…</option>
          {(users.data ?? []).map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
              {u.id === user.id ? " (me)" : ""}
            </option>
          ))}
          <option value="none">Nobody</option>
        </Select>
        <Button size="sm" variant="secondary" disabledReason={locked} onClick={onNote}>
          Add note
        </Button>
        <Button size="sm" variant="ghost" onClick={onClear} title="Clear selection (Esc)">
          Clear
        </Button>
      </div>
    </div>
  );
}

function BulkNoteDialog({ open, n, onClose, onSave }: { open: boolean; n: number; onClose: () => void; onSave: (note: string) => void }) {
  const [note, setNote] = useState("");
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Note on ${plural(n, "record")}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!note.trim()} onClick={() => { onSave(note.trim()); setNote(""); }}>
            Save note
          </Button>
        </>
      }
    >
      <Textarea rows={4} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Client confirmed these were received in July" className="w-full" />
      <p className="text-xs text-muted mt-1.5">Replaces the note on each selected record. Notes go into the close pack.</p>
    </Dialog>
  );
}

function ShortcutHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  const rows: [string[], string][] = [
    [["j", "↓"], "Next row"],
    [["k", "↑"], "Previous row"],
    [["a"], "Accept (selected rows, or the current row)"],
    [["r"], "Reject"],
    [["p"], "Pending"],
    [["n"], "No IMS action"],
    [["u"], "Use TaxMind's recommendation"],
    [["h"], "Same as last month"],
    [["x"], "Select or unselect the current row"],
    [["Shift", "click"], "Select a range of rows"],
    [["Enter"], "Open details"],
    [["Esc"], "Close details, or clear the selection"],
    [["["], "Previous supplier"],
    [["]"], "Next supplier"],
    [["/"], "Search"],
    [["?"], "Show this list"],
  ];
  return (
    <Dialog open={open} onClose={onClose} title="Keyboard shortcuts" width={460}>
      <table className="w-full text-sm">
        <tbody>
          {rows.map(([keys, what]) => (
            <tr key={what} className="border-b border-rule last:border-0">
              <td className="py-1.5 pr-4 whitespace-nowrap">
                {keys.map((k, i) => (
                  <span key={k}>
                    {i > 0 && <span className="text-faint mx-1">{keys[0] === "Shift" ? "+" : "or"}</span>}
                    <Kbd>{k}</Kbd>
                  </span>
                ))}
              </td>
              <td className="py-1.5 text-ink-2">{what}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-muted mt-3">After a decision on the current row, the next row is selected, so you can keep pressing keys.</p>
    </Dialog>
  );
}
