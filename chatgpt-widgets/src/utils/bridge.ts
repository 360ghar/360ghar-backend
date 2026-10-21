/**
 * Unified bridge for MCP App hosts (Claude, VS Code, MCPJam, Cursor, etc.)
 * and ChatGPT/OpenAI hosts.
 *
 * Runtime detection: if `window.openai` is present at module load → OpenAI host.
 * Otherwise, if running inside an iframe → MCP Apps host (lightweight JSON-RPC
 * over postMessage, with no heavy SDK dependency).
 *
 * The exported hooks have identical signatures regardless of runtime, so all
 * widgets work without any per-widget changes.
 */

import { useCallback, useSyncExternalStore } from 'react';
import type { ToolName } from '../generated/tool-names';
import type { OpenAiApi, OpenAiGlobals } from '../types/openai';

// ---------------------------------------------------------------------------
// Runtime detection (synchronous, runs once at module load)
// ---------------------------------------------------------------------------

type HostType = 'openai' | 'mcp-apps' | 'standalone';

function detectHost(): HostType {
  if (typeof window === 'undefined') return 'standalone';
  if (window.openai) return 'openai';
  if (window.parent !== window) return 'mcp-apps';
  return 'standalone';
}

const HOST: HostType = detectHost();

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// ---------------------------------------------------------------------------
// Reactive store (shared by both paths)
// ---------------------------------------------------------------------------

interface BridgeStore {
  toolInput: Record<string, unknown> | null;
  toolOutput: Record<string, unknown> | null;
  toolMeta: Record<string, unknown> | null;
  theme: 'light' | 'dark';
  widgetState: Record<string, unknown> | null;
}

let store: BridgeStore = {
  toolInput: null,
  toolOutput: null,
  toolMeta: null,
  theme:
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-color-scheme: dark)')?.matches
      ? 'dark'
      : 'light',
  widgetState: null,
};

/**
 * Widgets read their fields off the top level of `structuredContent`.
 *
 * Not every tool ships them there: the `app/mcp/user/*` and admin tools return an
 * `MCPResponse` envelope, `{ok: true, data: {...}}`, while the `app/mcp/chatgpt/*` tools
 * return the payload flat. Unwrapping here rather than in each widget means every widget
 * accepts either shape, on every host, and a new tool cannot silently render an empty
 * widget by picking the envelope. An error envelope (`ok: false`) is left alone, since
 * widgets read its `error` and `message` keys.
 */
function unwrapToolOutput(raw: unknown): Record<string, unknown> | null {
  if (!isRecord(raw)) return null;
  if (raw.ok === true && isRecord(raw.data)) {
    return raw.data;
  }
  return raw;
}

const listeners = new Set<() => void>();
function emitChange() { listeners.forEach((fn) => fn()); }
function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
function getStore() { return store; }

// ---------------------------------------------------------------------------
// Lightweight MCP Apps postMessage bridge (JSON-RPC 2.0)
// ---------------------------------------------------------------------------

let _nextId = 1;
const _pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
let _mcpReady = false;
let _mcpReadyPromise: Promise<void> | null = null;
let _mcpReadyResolve: (() => void) | null = null;

/** Send a JSON-RPC request to the host and await the response. */
function mcpRequest(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const id = _nextId++;
    _pending.set(id, { resolve, reject });
    window.parent.postMessage({
      jsonrpc: '2.0',
      id,
      method,
      params,
    }, '*');
    // Timeout after 30 s
    setTimeout(() => {
      if (_pending.has(id)) {
        _pending.delete(id);
        reject(new Error(`MCP request "${method}" timed out`));
      }
    }, 30_000);
  });
}

/** Send a JSON-RPC notification (no response expected). */
function mcpNotify(method: string, params: Record<string, unknown> = {}): void {
  window.parent.postMessage({
    jsonrpc: '2.0',
    method,
    params,
  }, '*');
}

/** Handle incoming JSON-RPC messages from the host. */
function handleMcpMessage(event: MessageEvent): void {
  const data: unknown = event.data;
  if (!isRecord(data) || data.jsonrpc !== '2.0') return;

  // Response to a request we sent
  if (typeof data.id === 'number' && _pending.has(data.id) && typeof data.method !== 'string') {
    const pending = _pending.get(data.id)!;
    _pending.delete(data.id);
    if (isRecord(data.error)) {
      pending.reject(new Error(typeof data.error.message === 'string' ? data.error.message : 'MCP error'));
    } else {
      pending.resolve(data.result);
    }
    return;
  }

  const method = typeof data.method === 'string' ? data.method : null;
  if (method === null) return;
  const params = isRecord(data.params) ? data.params : {};

  // Incoming notification from host
  switch (method) {
    case 'ui/notifications/tool-result': {
      store = {
        ...store,
        toolOutput: unwrapToolOutput(params.structuredContent),
        toolMeta: isRecord(params._meta) ? params._meta : null,
      };
      emitChange();
      break;
    }
    case 'ui/notifications/tool-input': {
      // The arguments of the call that produced this widget. Load More and refresh resend them.
      store = { ...store, toolInput: isRecord(params.arguments) ? params.arguments : null };
      emitChange();
      break;
    }
    case 'ui/notifications/host-context-changed': {
      if (params.theme) {
        store = { ...store, theme: params.theme === 'dark' ? 'dark' : 'light' };
        emitChange();
      }
      break;
    }
    case 'ui/notifications/tool-cancelled': {
      // Optionally surface this. For now just log.
      console.warn('[360Ghar] Tool cancelled:', params.reason);
      break;
    }
  }

  // Incoming request from host (we need to respond)
  if (data.id != null && method === 'ui/resource-teardown') {
    // Acknowledge teardown
    window.parent.postMessage({
      jsonrpc: '2.0',
      id: data.id,
      result: {},
    }, '*');
  }
}

/** Perform the MCP Apps initialization handshake. */
async function initMcpApps(): Promise<void> {
  window.addEventListener('message', handleMcpMessage);

  // Send ui/initialize
  const result = await mcpRequest('ui/initialize', {
    protocolVersion: '2026-01-26',
    clientInfo: { name: '360Ghar', version: '1.0.0' },
    capabilities: {},
  });

  // Extract host context
  const ctx = isRecord(result) && isRecord(result.hostContext) ? result.hostContext : null;
  if (ctx?.theme) {
    store = { ...store, theme: ctx.theme === 'dark' ? 'dark' : 'light' };
    emitChange();
  }

  // Send initialized notification
  mcpNotify('ui/notifications/initialized', {});

  // Set up auto-resize via ResizeObserver
  setupAutoResize();

  _mcpReady = true;
  _mcpReadyResolve?.();
}

/** Auto-resize: observe body and report size changes to host. */
function setupAutoResize(): void {
  if (typeof ResizeObserver === 'undefined') return;
  let pending = false;
  const observer = new ResizeObserver(() => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      const w = document.documentElement.scrollWidth;
      const h = document.documentElement.scrollHeight;
      mcpNotify('ui/notifications/size-changed', { width: w, height: h });
    });
  });
  observer.observe(document.documentElement);
  observer.observe(document.body);
}

function waitForMcpReady(): Promise<void> {
  if (_mcpReady) return Promise.resolve();
  if (!_mcpReadyPromise) {
    _mcpReadyPromise = new Promise((resolve) => { _mcpReadyResolve = resolve; });
  }
  return _mcpReadyPromise;
}

// Eagerly start MCP Apps initialization
if (HOST === 'mcp-apps') {
  initMcpApps().catch((err) => {
    console.warn('[360Ghar Bridge] MCP Apps init failed:', err);
  });
}

// ---------------------------------------------------------------------------
// OpenAI helpers
// ---------------------------------------------------------------------------

const SET_GLOBALS_EVENT_TYPE = 'openai:set_globals';

interface SetGlobalsEvent extends Event {
  detail: { globals: Partial<OpenAiGlobals> };
}

function getBridge(): OpenAiApi | null {
  if (typeof window === 'undefined') return null;
  return window.openai ?? null;
}

function readGlobal<K extends keyof OpenAiGlobals>(key: K): OpenAiGlobals[K] {
  const bridge = getBridge();
  if (bridge) return bridge[key];
  if (key === 'widgetState') return null as OpenAiGlobals[K];
  if (key === 'theme') return 'light' as OpenAiGlobals[K];
  if (key === 'toolOutput') return null as OpenAiGlobals[K];
  if (key === 'toolResponseMetadata') return null as OpenAiGlobals[K];
  if (key === 'toolInput') return {} as OpenAiGlobals[K];
  if (key === 'locale') return 'en-US' as OpenAiGlobals[K];
  if (key === 'displayMode') return 'inline' as OpenAiGlobals[K];
  if (key === 'maxHeight') return 720 as OpenAiGlobals[K];
  return null as OpenAiGlobals[K];
}

function useOpenAiGlobal<K extends keyof OpenAiGlobals>(key: K): OpenAiGlobals[K] {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === 'undefined') return () => undefined;
      const handler = (event: Event) => {
        const e = event as SetGlobalsEvent;
        if (e.detail.globals[key] !== undefined) onChange();
      };
      window.addEventListener(SET_GLOBALS_EVENT_TYPE, handler);
      return () => window.removeEventListener(SET_GLOBALS_EVENT_TYPE, handler);
    },
    () => readGlobal(key),
    () => readGlobal(key),
  );
}

// ---------------------------------------------------------------------------
// Unified hooks
// ---------------------------------------------------------------------------

/**
 * Get the structured tool output data.
 */
export function useToolOutput<T = Record<string, unknown>>(): T | null {
  if (HOST === 'openai') {
    return unwrapToolOutput(useOpenAiGlobal('toolOutput')) as T | null;
  }
  const read = () => getStore().toolOutput as T | null;
  return useSyncExternalStore(subscribe, read, read);
}

const NO_INPUT: Record<string, unknown> = {};

/**
 * Get the arguments of the tool call that produced this widget. A cursor is bound to the
 * filters of its call, so Load More and refresh resend these arguments with the new cursor.
 */
export function useToolInput(): Record<string, unknown> {
  if (HOST === 'openai') {
    return useOpenAiGlobal('toolInput') ?? NO_INPUT;
  }
  const read = () => getStore().toolInput ?? NO_INPUT;
  return useSyncExternalStore(subscribe, read, read);
}

/**
 * Get tool metadata (widget-only data passed via `_meta`).
 */
export function useToolMeta<T = Record<string, unknown>>(): T | null {
  if (HOST === 'openai') {
    return useOpenAiGlobal('toolResponseMetadata') as T | null;
  }
  const read = () => getStore().toolMeta as T | null;
  return useSyncExternalStore(subscribe, read, read);
}

/**
 * Get and set widget state. The state lives in memory (MCP Apps hosts) or in the host
 * (OpenAI). Nothing is written to browser storage: it would hold one account's data with no
 * schema version, no account scope and no purge on sign-out.
 */
export function useWidgetState<T extends object>(): [T | null, (state: T) => void] {
  if (HOST === 'openai') {
    const state = useOpenAiGlobal('widgetState') as T | null;
    const setState = useCallback((newState: T) => {
      getBridge()?.setWidgetState(newState as Record<string, unknown>);
    }, []);
    return [state, setState];
  }

  const read = () => getStore().widgetState as T | null;
  const state = useSyncExternalStore(subscribe, read, read);
  const setState = useCallback((newState: T) => {
    store = { ...store, widgetState: newState as Record<string, unknown> };
    emitChange();
  }, []);
  return [state, setState];
}

/**
 * Get current host theme ('light' or 'dark').
 */
export function useTheme(): 'light' | 'dark' {
  if (HOST === 'openai') {
    const theme = useOpenAiGlobal('theme');
    return theme === 'dark' ? 'dark' : 'light';
  }
  const read = () => getStore().theme;
  return useSyncExternalStore(subscribe, read, read);
}

// ---------------------------------------------------------------------------
// Tool calls
// ---------------------------------------------------------------------------

export type ToolArgs = Record<string, unknown>;

/**
 * A tool result that is an error. Two backend shapes reach the widgets:
 * - the chatgpt tools send `{error: true, code?, message?}` (and `{requires_auth: true}` for a sign-in challenge);
 * - the MCPResponse tools send `{ok: false, error: {code, message, details}, message}`.
 * A call that throws or returns nothing becomes `{error: true, message}` here.
 */
export interface ToolFailure {
  ok?: false;
  error: true | { code?: string; message?: string; details?: unknown };
  code?: string;
  message?: string;
  requires_auth?: boolean;
}

export type ToolResult<T> = T | ToolFailure;

export function isToolFailure(value: unknown): value is ToolFailure {
  if (!isRecord(value)) return false;
  return value.ok === false || Boolean(value.error) || value.requires_auth === true;
}

const FAILURE_MESSAGES: Record<string, string> = {
  NOT_FOUND: 'This item was not found.',
  FORBIDDEN: 'You do not have access to this.',
  INSUFFICIENT_PERMISSIONS: 'You do not have access to this.',
  INVALID_INPUT: 'Some details are not valid.',
  INVALID_DATE: 'The date is not valid.',
  PAST_DATE: 'Choose a date and time in the future.',
  INVALID_STATUS: 'This action does not apply to the current status.',
  INVALID_CURSOR: 'The list changed. Reload it and try again.',
  SWIPE_NOT_ALLOWED: 'This property cannot be saved.',
  INVALID_METHOD: 'Choose a valid payment method.',
};

/** A message for the user. Read from the failure, else from its code, else a generic line. */
export function toolFailureMessage(failure: ToolFailure): string {
  if (failure.requires_auth) return 'Sign in to 360Ghar to continue.';
  const nested = typeof failure.error === 'object' ? failure.error : null;
  const code = failure.code ?? nested?.code;
  return (
    failure.message ??
    nested?.message ??
    (code ? FAILURE_MESSAGES[code] : undefined) ??
    'The request failed. Try again.'
  );
}

/** The text of a tool result's `content`: a string, or a list of `{type: 'text', text}` blocks. */
function contentText(content: unknown, separator: string): string {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content
    .filter((c): c is { type: string; text: string } =>
      isRecord(c) && c.type === 'text' && typeof c.text === 'string')
    .map((c) => c.text)
    .join(separator);
}

/** One MCP CallToolResult. The payload is its structuredContent, else its JSON text content. */
function readCallToolResult(result: unknown): unknown {
  if (!isRecord(result)) return null;
  if (isRecord(result.structuredContent)) return result.structuredContent;

  const text = contentText(result.content, result.isError ? '\n' : '');

  if (result.isError) {
    throw new Error(text || 'Tool call failed');
  }
  try {
    return JSON.parse(text || '{}');
  } catch {
    return null;
  }
}

async function callOne(name: ToolName, args: ToolArgs): Promise<unknown> {
  if (HOST === 'openai') {
    const bridge = getBridge();
    if (!bridge?.callTool) {
      throw new Error(`Tool bridge unavailable. Cannot call "${name}".`);
    }
    const result = await bridge.callTool<unknown>(name, args);
    if (result.structuredContent != null) return result.structuredContent;
    // No structured payload: the host sent an error as text, or nothing. An unknown-tool message
    // is thrown, so useCallTool tries the next name, as it does for a rejected call.
    const message = contentText(result.content, '\n');
    if (isUnknownToolError(message)) throw new Error(message);
    return { error: true, message: message || undefined };
  }

  // MCP Apps: send tools/call request via postMessage
  await waitForMcpReady();
  return readCallToolResult(await mcpRequest('tools/call', { name, arguments: args }));
}

/** The host rejected the name: the tool is not on the MCP server this widget came from. */
function isUnknownToolError(err: unknown): boolean {
  const message = err instanceof Error ? err.message : String(err);
  return /unknown tool|no such tool|tool\b[^.]{0,80}\bnot (found|registered|available)|method not found/i.test(message);
}

/**
 * Call an MCP tool and get its payload back.
 *
 * The result is unwrapped, so a widget reads the same keys for a flat result and for an
 * `{ok, data}` envelope. The call never rejects: a failure comes back as a `ToolFailure`.
 * Test it with `isToolFailure()`.
 *
 * A widget is linked to tools on two servers: `/mcp` (owner, tenant, visits, discovery) and
 * `/mcp-admin` (agent). Pass the names in order to try them. The next name is tried only when
 * the host says the tool is unknown, so the real error of a registered tool is never hidden.
 */
export function useCallTool() {
  return useCallback(async <T = Record<string, unknown>>(
    names: ToolName | readonly ToolName[],
    args: ToolArgs,
  ): Promise<ToolResult<T>> => {
    const candidates = typeof names === 'string' ? [names] : names;
    let firstError: unknown = null;

    for (const name of candidates) {
      try {
        const payload = unwrapToolOutput(await callOne(name, args));
        if (payload === null) {
          return { error: true, message: 'The tool returned no data.' };
        }
        return payload as ToolResult<T>;
      } catch (err) {
        if (!isUnknownToolError(err)) {
          return { error: true, message: err instanceof Error ? err.message : 'The request failed.' };
        }
        firstError ??= err;
      }
    }

    return {
      error: true,
      message: firstError instanceof Error ? firstError.message : 'No tool is available for this action.',
    };
  }, []);
}

/**
 * Send a follow-up message to the chat.
 */
export function useSendMessage() {
  return useCallback(async (prompt: string) => {
    if (HOST === 'openai') {
      getBridge()?.sendFollowUpMessage?.({ prompt });
      return;
    }
    // MCP Apps: send ui/message request
    try {
      await waitForMcpReady();
      await mcpRequest('ui/message', {
        role: 'user',
        content: [{ type: 'text', text: prompt }],
      });
    } catch (err) {
      console.warn('[360Ghar Bridge] sendMessage failed:', err);
    }
  }, []);
}

/**
 * Request the widget to close.
 */
export function useRequestClose() {
  return useCallback(() => {
    if (HOST === 'openai') {
      getBridge()?.requestClose?.();
    }
    // MCP Apps: no direct close equivalent
  }, []);
}

/**
 * Request a display mode change (inline, fullscreen, PiP).
 */
export function useRequestDisplayMode() {
  return useCallback(async (mode: 'inline' | 'fullscreen' | 'pip') => {
    if (HOST === 'openai') {
      await getBridge()?.requestDisplayMode?.({ mode });
      return;
    }
    // MCP Apps: no direct equivalent yet
    console.warn('[360Ghar Bridge] requestDisplayMode not available on this host');
  }, []);
}

/**
 * Open an external link (with optional return support on OpenAI hosts).
 */
export function useOpenExternal() {
  return useCallback((href: string) => {
    if (HOST === 'openai') {
      getBridge()?.openExternal?.({ href });
      return;
    }
    // Fallback: open in new tab
    window.open(href, '_blank', 'noopener,noreferrer');
  }, []);
}
