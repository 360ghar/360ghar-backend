/**
 * Shared notices: sign-in prompt, inline error, centered note and the Load More button.
 */

import React from 'react';
import { useSendMessage } from '../../utils/bridge';
import { useThemeColors } from '../../utils/theme';
import { Button } from './Button';

/** Shown when a tool answers with `requires_auth`. */
export function LoginRequired({ message }: { message: string }) {
  const colors = useThemeColors();
  const sendMessage = useSendMessage();

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      padding: 24,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center',
    }}>
      <div style={{ fontSize: 48, marginBottom: 16 }}>🔐</div>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>Login Required</h2>
      <p style={{ color: colors.textSecondary, marginBottom: 24 }}>{message}</p>
      <Button onClick={() => sendMessage('Help me log in to 360Ghar')}>
        Log In
      </Button>
    </div>
  );
}

/** A failed action, shown above the control that caused it. */
export function InlineError({ message }: { message: string | null }) {
  const colors = useThemeColors();
  if (!message) return null;

  return (
    <div role="alert" style={{
      padding: 12,
      backgroundColor: `${colors.error}20`,
      borderRadius: 8,
      marginBottom: 16,
      color: colors.error,
      fontSize: 14,
    }}>
      {message}
    </div>
  );
}

/** A load failure that replaces the whole widget. */
export function FullError({ message }: { message: string }) {
  const colors = useThemeColors();
  return (
    <div role="alert" style={{ padding: 40, textAlign: 'center', color: colors.error }}>
      {message}
    </div>
  );
}

export function LoadingNote({ text }: { text: string }) {
  const colors = useThemeColors();
  return (
    <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
      {text}
    </div>
  );
}

/** The Load More control under a cursor-paged list. */
export function LoadMore({
  hasMore,
  loading,
  onClick,
}: {
  hasMore: boolean;
  loading: boolean;
  onClick: () => void;
}) {
  const colors = useThemeColors();
  if (!hasMore) return null;

  return (
    <div style={{ marginTop: 20, textAlign: 'center' }}>
      <button
        onClick={onClick}
        disabled={loading}
        style={{
          padding: '12px 24px',
          backgroundColor: colors.primary,
          color: '#3D3829',
          border: 'none',
          borderRadius: 8,
          fontSize: 14,
          fontWeight: 500,
          cursor: loading ? 'not-allowed' : 'pointer',
          opacity: loading ? 0.6 : 1,
        }}
      >
        {loading ? 'Loading...' : 'Load More'}
      </button>
    </div>
  );
}
