/**
 * TypeScript definitions for the ChatGPT window.openai API.
 *
 * This API provides the bridge between your widget and ChatGPT.
 */

export interface OpenAiGlobals {
  /** Arguments passed when the tool was invoked */
  toolInput: Record<string, unknown>;

  /** Structured content from the tool response (visible to model and widget) */
  toolOutput: Record<string, unknown> | null;

  /** Metadata from tool response (only visible to widget) */
  toolResponseMetadata: Record<string, unknown> | null;

  /** Persisted UI state snapshot */
  widgetState: Record<string, unknown> | null;

  /** Current theme (light or dark) */
  theme: 'light' | 'dark';

  /** User's locale (e.g., 'en-US') */
  locale: string;

  /** Current display mode */
  displayMode: 'inline' | 'fullscreen' | 'pip';

  /** Maximum height for the widget in pixels */
  maxHeight: number;
}

export interface OpenAiApi extends OpenAiGlobals {
  /**
   * Store widget state. This is persisted per widget instance.
   * Keep payloads under 4k tokens as they're sent to the model.
   */
  setWidgetState: (state: Record<string, unknown>) => void;

  /**
   * Invoke an MCP tool from the widget.
   * Returns the tool response.
   */
  callTool: <T = unknown>(name: string, args: Record<string, unknown>) => Promise<{
    structuredContent: T;
    content: string;
    _meta?: Record<string, unknown>;
  }>;

  /**
   * Send a message as if the user typed it.
   */
  sendFollowUpMessage: (options: { prompt: string }) => void;

  /**
   * Upload a file and get a file ID.
   */
  uploadFile: (file: File) => Promise<{ fileId: string }>;

  /**
   * Get download URL for an uploaded file.
   */
  getFileDownloadUrl: (options: { fileId: string }) => Promise<{ url: string }>;

  /**
   * Request a different display mode (fullscreen, PiP, etc).
   */
  requestDisplayMode: (options: { mode: 'inline' | 'fullscreen' | 'pip' }) => Promise<void>;

  /**
   * Open an external link.
   */
  openExternal: (options: { href: string }) => void;

  /**
   * Request the widget to close.
   */
  requestClose: () => void;
}

declare global {
  interface Window {
    openai?: OpenAiApi;
  }
}

export {};
