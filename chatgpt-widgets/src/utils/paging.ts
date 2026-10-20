/**
 * Cursor paging for the list widgets.
 *
 * Every list tool returns a CursorPage: rows, `next_cursor` and `has_more`. A widget
 * keeps its rows in `usePagedRows`. Load More and refresh call the tool and pass the
 * RETURNED payload to `append` or `replace`. Nothing waits for the host to push a new
 * tool output: the bridge does not write `callTool` results into the output store.
 */

import React from 'react';
import type { ToolArgs } from './bridge';

export interface PageInfo {
  next_cursor: string | null;
  has_more: boolean;
}

export interface PagedView<Row> {
  rows: Row[];
  page: PageInfo;
}

const NO_PAGE: PageInfo = { next_cursor: null, has_more: false };
const NO_ROWS: never[] = [];

/** `next_cursor` and `has_more` of a payload. A page with a cursor and no flag still has more. */
export function readPage(payload: { next_cursor?: string | null; has_more?: boolean | null }): PageInfo {
  const cursor = payload.next_cursor ?? null;
  return { next_cursor: cursor, has_more: (payload.has_more ?? cursor !== null) && cursor !== null };
}

/** Rows of `next` appended to `current`. A row with a known id replaces the old row in place. */
export function mergeRows<Row extends { id: number }>(current: Row[], next: Row[]): Row[] {
  const merged = new Map<number, Row>(current.map((row) => [row.id, row]));
  for (const row of next) merged.set(row.id, row);
  return Array.from(merged.values());
}

/**
 * Rows and page state of a list widget.
 *
 * `output` is the tool output from the host. `read` extracts rows and page info from a
 * payload, or returns null when the payload has no list. `read` must be a module-level
 * function. A new host output replaces the rows; `append` and `replace` apply to the output
 * that is current when they run.
 */
export function usePagedRows<P extends object, Row extends { id: number }>(
  output: P | null,
  read: (payload: P) => PagedView<Row> | null,
) {
  const base = React.useMemo(() => (output ? read(output) : null), [output, read]);
  const [local, setLocal] = React.useState<{ source: P | null; view: PagedView<Row> } | null>(null);

  const view = local && local.source === output ? local.view : base;

  const append = React.useCallback(
    (payload: P) => {
      const next = read(payload);
      if (!next) return;
      setLocal((prev) => {
        const current = prev && prev.source === output ? prev.view : base;
        return {
          source: output,
          view: { rows: mergeRows(current?.rows ?? [], next.rows), page: next.page },
        };
      });
    },
    [output, base, read],
  );

  const replace = React.useCallback(
    (payload: P) => {
      const next = read(payload);
      if (next) setLocal({ source: output, view: next });
    },
    [output, read],
  );

  return {
    rows: view?.rows ?? NO_ROWS,
    page: view?.page ?? NO_PAGE,
    hasList: view !== null,
    append,
    replace,
  };
}

/** The arguments of the original call with a new cursor, or the first page when `cursor` is omitted. */
export function pageArgs(input: ToolArgs, cursor?: string): ToolArgs {
  const { cursor: _old, ...rest } = input;
  return cursor === undefined ? rest : { ...rest, cursor };
}
