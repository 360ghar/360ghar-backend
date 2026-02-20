/**
 * Unified bridge for MCP App hosts (Claude, VS Code, MCPJam, Cursor, etc.)
 * and ChatGPT/OpenAI hosts.
 *
 * Runtime detection: if `window.openai` is present at module load → OpenAI host.
 * Otherwise, if running inside an iframe → MCP Apps host (lightweight JSON-RPC
 * over postMessage — no heavy SDK dependency).
 *
 * The exported hooks have identical signatures regardless of runtime, so all
 * widgets work without any per-widget changes.
 */

import { useCallback, useSyncExternalStore } from 'react';
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

// ---------------------------------------------------------------------------
// Reactive store (shared by both paths)
// ---------------------------------------------------------------------------

interface BridgeStore {
  toolOutput: Record<string, unknown> | null;
  toolMeta: Record<string, unknown> | null;
  theme: 'light' | 'dark';
  widgetState: Record<string, unknown> | null;
}

let store: BridgeStore = {
  toolOutput: null,
  toolMeta: null,
  theme:
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-color-scheme: dark)')?.matches
      ? 'dark'
      : 'light',
  widgetState: null,
};

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
const _pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>();
let _mcpReady = false;
let _mcpReadyPromise: Promise<void> | null = null;
let _mcpReadyResolve: (() => void) | null = null;

/** Send a JSON-RPC request to the host and await the response. */
function mcpRequest(method: string, params: Record<string, unknown> = {}): Promise<any> {
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
  const data = event.data;
  if (!data || data.jsonrpc !== '2.0') return;

  // Response to a request we sent
  if (data.id != null && _pending.has(data.id)) {
    const { resolve, reject } = _pending.get(data.id)!;
    _pending.delete(data.id);
    if (data.error) {
      reject(new Error(data.error.message || 'MCP error'));
    } else {
      resolve(data.result);
    }
    return;
  }

  // Incoming notification from host
  if (data.method) {
    switch (data.method) {
      case 'ui/notifications/tool-result': {
        const p = data.params ?? {};
        store = {
          ...store,
          toolOutput: (p.structuredContent ?? null) as Record<string, unknown> | null,
          toolMeta: (p._meta ?? null) as Record<string, unknown> | null,
        };
        emitChange();
        break;
      }
      case 'ui/notifications/tool-input': {
        // Tool arguments — some hosts send this before tool-result
        break;
      }
      case 'ui/notifications/host-context-changed': {
        const p = data.params ?? {};
        if (p.theme) {
          store = { ...store, theme: p.theme === 'dark' ? 'dark' : 'light' };
          emitChange();
        }
        break;
      }
      case 'ui/notifications/tool-cancelled': {
        // Optionally surface this — for now just log
        console.warn('[360Ghar] Tool cancelled:', data.params?.reason);
        break;
      }
    }
  }

  // Incoming request from host (we need to respond)
  if (data.method && data.id != null) {
    switch (data.method) {
      case 'ui/resource-teardown': {
        // Acknowledge teardown
        window.parent.postMessage({
          jsonrpc: '2.0',
          id: data.id,
          result: {},
        }, '*');
        break;
      }
    }
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
  const ctx = result?.hostContext;
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
    return useOpenAiGlobal('toolOutput') as T | null;
  }
  return useSyncExternalStore(subscribe, () => getStore().toolOutput as T | null);
}

/**
 * Get tool metadata (widget-only data passed via `_meta`).
 */
export function useToolMeta<T = Record<string, unknown>>(): T | null {
  if (HOST === 'openai') {
    return useOpenAiGlobal('toolResponseMetadata') as T | null;
  }
  return useSyncExternalStore(subscribe, () => getStore().toolMeta as T | null);
}

/**
 * Get and set widget state.
 */
export function useWidgetState<T extends object>(): [T | null, (state: T) => void] {
  if (HOST === 'openai') {
    const state = useOpenAiGlobal('widgetState') as unknown as T | null;
    const setState = useCallback((newState: T) => {
      getBridge()?.setWidgetState(newState as Record<string, unknown>);
    }, []);
    return [state, setState];
  }

  // MCP Apps: use localStorage for persistence
  const state = useSyncExternalStore(subscribe, () => getStore().widgetState as T | null);
  const setState = useCallback((newState: T) => {
    store = { ...store, widgetState: newState as Record<string, unknown> };
    try { localStorage.setItem('mcp-widget-state', JSON.stringify(newState)); } catch { /* sandboxed */ }
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
  return useSyncExternalStore(subscribe, () => getStore().theme);
}

/**
 * Call an MCP tool and get the structured content back.
 */
export function useCallTool() {
  return useCallback(async <T = any>(
    name: string,
    args: Record<string, unknown>,
  ): Promise<T> => {
    if (HOST === 'openai') {
      const bridge = getBridge();
      if (!bridge?.callTool) {
        throw new Error(`Tool bridge unavailable. Cannot call "${name}".`);
      }
      const result = await bridge.callTool<T>(name, args);
      return result.structuredContent;
    }

    // MCP Apps: send tools/call request via postMessage
    await waitForMcpReady();
    const result = await mcpRequest('tools/call', { name, arguments: args });

    if (result?.isError) {
      const errText = Array.isArray(result.content)
        ? result.content
            .filter((c: any) => c.type === 'text')
            .map((c: any) => c.text)
            .join('\n')
        : 'Tool call failed';
      throw new Error(errText);
    }

    // Prefer structuredContent, fall back to parsing text content
    if (result?.structuredContent) {
      return result.structuredContent as T;
    }
    const textContent = Array.isArray(result?.content)
      ? result.content
          .filter((c: any) => c.type === 'text')
          .map((c: any) => c.text)
          .join('')
      : '';
    try {
      return JSON.parse(textContent || '{}') as T;
    } catch {
      return textContent as unknown as T;
    }
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
