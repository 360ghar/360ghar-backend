/**
 * OpenAI bridge utilities for ChatGPT widgets.
 *
 * Provides hooks and helpers for interacting with the window.openai API.
 */

import { useSyncExternalStore, useCallback } from 'react';
import type { OpenAiGlobals } from '../types/openai';

const SET_GLOBALS_EVENT_TYPE = 'openai:set_globals';

interface SetGlobalsEvent extends Event {
  detail: {
    globals: Partial<OpenAiGlobals>;
  };
}

/**
 * Check if window.openai API is available.
 * Returns false when running outside of ChatGPT environment.
 */
function isOpenAiAvailable(): boolean {
  return typeof window !== 'undefined' && window.openai !== undefined;
}

/**
 * Get a default value for OpenAI globals when API is not available.
 */
function getDefaultGlobal<K extends keyof OpenAiGlobals>(key: K): OpenAiGlobals[K] {
  const defaults: Partial<OpenAiGlobals> = {
    theme: 'light',
    displayMode: 'inline',
    toolOutput: null,
    toolInput: null,
    toolResponseMetadata: null,
    widgetState: null,
  };
  return defaults[key] as OpenAiGlobals[K];
}

/**
 * Hook to subscribe to a specific window.openai global value.
 * Re-renders when the value changes.
 */
export function useOpenAiGlobal<K extends keyof OpenAiGlobals>(
  key: K
): OpenAiGlobals[K] {
  return useSyncExternalStore(
    (onChange) => {
      const handleSetGlobal = (event: Event) => {
        const e = event as SetGlobalsEvent;
        if (e.detail.globals[key] !== undefined) {
          onChange();
        }
      };
      window.addEventListener(SET_GLOBALS_EVENT_TYPE, handleSetGlobal);
      return () => window.removeEventListener(SET_GLOBALS_EVENT_TYPE, handleSetGlobal);
    },
    () => isOpenAiAvailable() ? window.openai[key] : getDefaultGlobal(key)
  );
}

/**
 * Hook to get the current tool output data.
 */
export function useToolOutput<T = Record<string, unknown>>(): T | null {
  return useOpenAiGlobal('toolOutput') as T | null;
}

/**
 * Hook to get the current tool metadata (widget-only data).
 */
export function useToolMeta<T = Record<string, unknown>>(): T | null {
  return useOpenAiGlobal('toolResponseMetadata') as T | null;
}

/**
 * Hook to get and set widget state.
 */
export function useWidgetState<T extends Record<string, unknown>>(): [
  T | null,
  (state: T) => void
] {
  const state = useOpenAiGlobal('widgetState') as T | null;

  const setState = useCallback((newState: T) => {
    if (isOpenAiAvailable()) {
      window.openai.setWidgetState(newState);
    }
  }, []);

  return [state, setState];
}

/**
 * Hook to get the current theme.
 */
export function useTheme(): 'light' | 'dark' {
  return useOpenAiGlobal('theme');
}

/**
 * MCP error response structure.
 */
export interface MCPError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

/**
 * MCP response structure for tool calls.
 */
export interface MCPToolResponse<T = unknown> {
  ok: boolean;
  data?: T;
  error?: MCPError;
}

/**
 * Error thrown when an MCP tool call fails.
 */
export class MCPToolError extends Error {
  code: string;
  details?: Record<string, unknown>;

  constructor(error: MCPError) {
    super(error.message);
    this.name = 'MCPToolError';
    this.code = error.code;
    this.details = error.details;
  }
}

/**
 * Hook to call an MCP tool.
 * Throws MCPToolError if the tool returns an error response.
 */
export function useCallTool() {
  return useCallback(async <T = unknown>(
    name: string,
    args: Record<string, unknown>
  ): Promise<T> => {
    if (!isOpenAiAvailable()) {
      throw new Error('OpenAI API is not available. This widget must run inside ChatGPT.');
    }
    const result = await window.openai.callTool<MCPToolResponse<T>>(name, args);
    const response = result.structuredContent;

    // Check if the response indicates an error
    if (response && typeof response === 'object' && 'ok' in response) {
      if (!response.ok && response.error) {
        throw new MCPToolError(response.error);
      }
      // Return just the data for successful responses
      return response.data as T;
    }

    // Fallback for tools that don't use MCPResponse format
    return response as T;
  }, []);
}

/**
 * Hook to send a follow-up message.
 */
export function useSendMessage() {
  return useCallback((prompt: string) => {
    if (isOpenAiAvailable()) {
      window.openai.sendFollowUpMessage({ prompt });
    }
  }, []);
}

/**
 * Hook to request close.
 */
export function useRequestClose() {
  return useCallback(() => {
    if (isOpenAiAvailable()) {
      window.openai.requestClose();
    }
  }, []);
}
