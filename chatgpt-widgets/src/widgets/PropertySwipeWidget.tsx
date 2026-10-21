/**
 * PropertySwipeWidget - Tinder-style swipe interface for property discovery.
 *
 * Tools: discovery_feed (cards), discovery_swipe (like or pass)
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import type { PropertyRow, PropertySwipeOutput } from '../api/wire';
import {
  isToolFailure,
  toolFailureMessage,
  useCallTool,
  useSendMessage,
  useTheme,
  useToolInput,
  useToolOutput,
  useWidgetState,
} from '../utils/bridge';
import { pageArgs, readPage, usePagedRows, type PagedView } from '../utils/paging';
import { formatLocation, formatPropertyPrice, purposeLabel } from '../utils/property';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { FullError, InlineError, LoadingNote } from '../components/common/Notices';

/** The ids the user has swiped. The host keeps this state for the widget instance. */
interface WidgetState {
  swipedIds: number[];
}

/** discovery_feed sends `properties`. */
function readFeed(payload: PropertySwipeOutput): PagedView<PropertyRow> | null {
  const rows = payload.properties ?? payload.items;
  return rows ? { rows, page: readPage(payload) } : null;
}

function PropertySwipeWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<PropertySwipeOutput>();
  const toolInput = useToolInput();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [widgetState, setWidgetState] = useWidgetState<WidgetState>();
  const [isAnimating, setIsAnimating] = React.useState(false);
  const [swipeDirection, setSwipeDirection] = React.useState<'left' | 'right' | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [feedEmpty, setFeedEmpty] = React.useState(false);
  const { rows: deck, append } = usePagedRows(data, readFeed);

  const swipedIds = widgetState?.swipedIds ?? [];

  if (!data) {
    return <LoadingNote text="Loading discovery feed..." />;
  }

  if (data.error) {
    return <FullError message={data.message || 'Failed to load properties'} />;
  }

  const remaining = deck.filter((property) => !swipedIds.includes(property.id));
  const currentProperty: PropertyRow | undefined = remaining[0];
  const position = deck.length - remaining.length + 1;

  const handleSwipe = async (isLiked: boolean) => {
    if (!currentProperty || isAnimating) return;

    setIsAnimating(true);
    setSwipeDirection(isLiked ? 'right' : 'left');
    setError(null);

    // Record the swipe. The card moves on only when the server saved it.
    const result = await callTool('discovery_swipe', {
      property_id: currentProperty.id,
      is_liked: isLiked,
    });

    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
      setIsAnimating(false);
      setSwipeDirection(null);
      return;
    }

    // Short delay for animation
    await new Promise((resolve) => setTimeout(resolve, 300));

    setWidgetState({ swipedIds: [...swipedIds, currentProperty.id] });
    setIsAnimating(false);
    setSwipeDirection(null);
  };

  const handleViewDetails = () => {
    if (currentProperty) {
      sendMessage(`Show me details for property ${currentProperty.id}`);
    }
  };

  const handleLoadMore = async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    setError(null);
    setFeedEmpty(false);

    // The feed has no cursor. The call returns properties the user has not swiped yet.
    const result = await callTool<PropertySwipeOutput>('discovery_feed', pageArgs(toolInput));
    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else {
      const fresh = (readFeed(result)?.rows ?? []).filter(
        (property) => !swipedIds.includes(property.id),
      );
      if (fresh.length === 0) {
        setFeedEmpty(true);
      } else {
        append(result);
      }
    }
    setLoadingMore(false);
  };

  // No card left to show
  if (!currentProperty) {
    return (
      <div style={{
        backgroundColor: colors.background,
        color: colors.text,
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        textAlign: 'center',
      }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>🏠</div>
        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>
          {deck.length === 0 ? 'No properties to show right now' : "You've seen all properties!"}
        </h2>
        <p style={{ fontSize: 14, color: colors.textSecondary, marginBottom: 24 }}>
          {swipedIds.length} properties reviewed
        </p>
        <div style={{ width: '100%', maxWidth: 400 }}>
          <InlineError message={error} />
        </div>
        {feedEmpty && (
          <p style={{ fontSize: 14, color: colors.textSecondary, marginBottom: 16 }}>
            No new properties yet. Try again later.
          </p>
        )}
        <Button onClick={handleLoadMore} size="lg" loading={loadingMore}>
          Load More Properties
        </Button>
      </div>
    );
  }

  const badge = purposeLabel(currentProperty.purpose);

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* Progress */}
      <div style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{
          flex: 1,
          height: 4,
          backgroundColor: colors.backgroundSecondary,
          borderRadius: 2,
          overflow: 'hidden',
        }}>
          <div style={{
            width: `${(position / deck.length) * 100}%`,
            height: '100%',
            backgroundColor: colors.primary,
            transition: 'width 0.3s ease',
          }} />
        </div>
        <span style={{ fontSize: 12, color: colors.textSecondary }}>
          {position} / {deck.length}
        </span>
      </div>

      {/* Card Container */}
      <div style={{
        flex: 1,
        padding: 16,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <div style={{ width: '100%', maxWidth: 400 }}>
          <InlineError message={error} />
        </div>
        <div
          style={{
            width: '100%',
            maxWidth: 400,
            backgroundColor: colors.background,
            borderRadius: 16,
            overflow: 'hidden',
            boxShadow: colors.shadow,
            transform: swipeDirection === 'left'
              ? 'translateX(-100%) rotate(-15deg)'
              : swipeDirection === 'right'
                ? 'translateX(100%) rotate(15deg)'
                : 'none',
            opacity: isAnimating ? 0 : 1,
            transition: 'transform 0.3s ease, opacity 0.3s ease',
          }}
        >
          {/* Image */}
          <div
            onClick={handleViewDetails}
            style={{
              position: 'relative',
              paddingTop: '100%',
              backgroundColor: colors.backgroundSecondary,
              cursor: 'pointer',
            }}
          >
            {currentProperty.main_image_url && (
              <img
                src={currentProperty.main_image_url}
                alt={currentProperty.title}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  objectFit: 'cover',
                }}
              />
            )}
            {/* Swipe indicators */}
            <div style={{
              position: 'absolute',
              top: 20,
              left: 20,
              padding: '8px 16px',
              borderRadius: 8,
              border: `3px solid ${colors.success}`,
              color: colors.success,
              fontWeight: 700,
              fontSize: 24,
              transform: 'rotate(-15deg)',
              opacity: swipeDirection === 'right' ? 1 : 0,
              transition: 'opacity 0.15s ease',
            }}>
              LIKE
            </div>
            <div style={{
              position: 'absolute',
              top: 20,
              right: 20,
              padding: '8px 16px',
              borderRadius: 8,
              border: `3px solid ${colors.error}`,
              color: colors.error,
              fontWeight: 700,
              fontSize: 24,
              transform: 'rotate(15deg)',
              opacity: swipeDirection === 'left' ? 1 : 0,
              transition: 'opacity 0.15s ease',
            }}>
              PASS
            </div>
            {/* Purpose badge */}
            {badge && (
              <span style={{
                position: 'absolute',
                bottom: 12,
                left: 12,
                backgroundColor: 'rgba(28, 26, 22, 0.85)',
                color: '#F2EDE0',
                padding: '6px 10px',
                borderRadius: 6,
                fontSize: 12,
                textTransform: 'uppercase',
              }}>
                {badge}
              </span>
            )}
          </div>

          {/* Content */}
          <div style={{ padding: 16 }}>
            <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>
              {currentProperty.title}
            </h2>
            <p style={{ fontSize: 14, color: colors.textSecondary, marginBottom: 8 }}>
              {formatLocation(currentProperty)}
            </p>

            {/* Specs */}
            <div style={{ display: 'flex', gap: 16, fontSize: 13, color: colors.textSecondary, marginBottom: 12 }}>
              {currentProperty.bedrooms ? <span>{currentProperty.bedrooms} BHK</span> : null}
              {currentProperty.bathrooms ? <span>{currentProperty.bathrooms} Bath</span> : null}
              {currentProperty.area_sqft ? <span>{currentProperty.area_sqft.toLocaleString()} sq ft</span> : null}
            </div>

            {/* Price */}
            <p style={{ fontSize: 22, fontWeight: 700, color: colors.primary }}>
              {formatPropertyPrice(currentProperty)}
            </p>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div style={{
        padding: 24,
        display: 'flex',
        justifyContent: 'center',
        gap: 20,
      }}>
        {/* Pass Button */}
        <button
          onClick={() => handleSwipe(false)}
          disabled={isAnimating}
          aria-label="Pass"
          style={{
            width: 64,
            height: 64,
            borderRadius: '50%',
            border: `2px solid ${colors.error}`,
            backgroundColor: 'transparent',
            color: colors.error,
            fontSize: 28,
            cursor: isAnimating ? 'not-allowed' : 'pointer',
            opacity: isAnimating ? 0.5 : 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'all 0.15s ease',
          }}
        >
          ✕
        </button>

        {/* Details Button */}
        <button
          onClick={handleViewDetails}
          aria-label="Property details"
          style={{
            width: 48,
            height: 48,
            borderRadius: '50%',
            border: `2px solid ${colors.primary}`,
            backgroundColor: 'transparent',
            color: colors.primary,
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            alignSelf: 'center',
          }}
        >
          ℹ
        </button>

        {/* Like Button */}
        <button
          onClick={() => handleSwipe(true)}
          disabled={isAnimating}
          aria-label="Like"
          style={{
            width: 64,
            height: 64,
            borderRadius: '50%',
            border: `2px solid ${colors.success}`,
            backgroundColor: 'transparent',
            color: colors.success,
            fontSize: 28,
            cursor: isAnimating ? 'not-allowed' : 'pointer',
            opacity: isAnimating ? 0.5 : 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'all 0.15s ease',
          }}
        >
          ♥
        </button>
      </div>
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<PropertySwipeWidget />);
