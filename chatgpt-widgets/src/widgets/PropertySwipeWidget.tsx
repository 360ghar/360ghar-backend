/**
 * PropertySwipeWidget - Tinder-style swipe interface for property discovery.
 *
 * Tool: discovery.feed
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { useToolOutput, useTheme, useCallTool, useSendMessage, useWidgetState } from '../utils/bridge';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';

interface Property {
  id: number;
  title: string;
  locality?: string;
  city?: string;
  base_price?: number;
  monthly_rent?: number;
  bedrooms?: number;
  bathrooms?: number;
  area_sqft?: number;
  property_type?: string;
  purpose?: string;
  main_image_url?: string;
}

interface FeedOutput {
  properties: Property[];
  count: number;
  is_personalized?: boolean;
  error?: boolean;
  message?: string;
}

interface WidgetState {
  currentIndex: number;
  swipedIds: number[];
}

function formatPrice(price?: number, purpose?: string): string {
  if (!price) return 'Price on request';
  const formatted = price >= 10000000
    ? `₹${(price / 10000000).toFixed(2)} Cr`
    : price >= 100000
      ? `₹${(price / 100000).toFixed(2)} L`
      : `₹${price.toLocaleString('en-IN')}`;
  return purpose === 'rent' ? `${formatted}/mo` : formatted;
}

function PropertySwipeWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<FeedOutput>();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [widgetState, setWidgetState] = useWidgetState<WidgetState>();
  const [isAnimating, setIsAnimating] = React.useState(false);
  const [swipeDirection, setSwipeDirection] = React.useState<'left' | 'right' | null>(null);

  const currentIndex = widgetState?.currentIndex ?? 0;
  const swipedIds = widgetState?.swipedIds ?? [];

  if (!data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
        Loading discovery feed...
      </div>
    );
  }

  if (data.error) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.error }}>
        {data.message || 'Failed to load properties'}
      </div>
    );
  }

  const properties = data.properties || [];
  const currentProperty = properties[currentIndex];

  const handleSwipe = async (isLiked: boolean) => {
    if (!currentProperty || isAnimating) return;

    setIsAnimating(true);
    setSwipeDirection(isLiked ? 'right' : 'left');

    // Record the swipe
    await callTool('discovery.swipe', {
      property_id: currentProperty.id,
      is_liked: isLiked,
    });

    // Short delay for animation
    await new Promise((resolve) => setTimeout(resolve, 300));

    // Update state
    const newIndex = currentIndex + 1;
    const newSwipedIds = [...swipedIds, currentProperty.id];
    setWidgetState({ currentIndex: newIndex, swipedIds: newSwipedIds });

    setIsAnimating(false);
    setSwipeDirection(null);
  };

  const handleViewDetails = () => {
    if (currentProperty) {
      sendMessage(`Show me details for property ${currentProperty.id}`);
    }
  };

  const handleLoadMore = async () => {
    await callTool('discovery.feed', { limit: 10 });
    setWidgetState({ currentIndex: 0, swipedIds: [] });
  };

  // All properties swiped
  if (currentIndex >= properties.length) {
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
          You've seen all properties!
        </h2>
        <p style={{ fontSize: 14, color: colors.textSecondary, marginBottom: 24 }}>
          {swipedIds.length} properties reviewed
        </p>
        <Button onClick={handleLoadMore} size="lg">
          Load More Properties
        </Button>
      </div>
    );
  }

  const price = currentProperty.purpose === 'rent' ? currentProperty.monthly_rent : currentProperty.base_price;

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
            width: `${((currentIndex + 1) / properties.length) * 100}%`,
            height: '100%',
            backgroundColor: colors.primary,
            transition: 'width 0.3s ease',
          }} />
        </div>
        <span style={{ fontSize: 12, color: colors.textSecondary }}>
          {currentIndex + 1} / {properties.length}
        </span>
      </div>

      {/* Card Container */}
      <div style={{
        flex: 1,
        padding: 16,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
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
              {currentProperty.purpose === 'rent' ? 'For Rent' : 'For Sale'}
            </span>
          </div>

          {/* Content */}
          <div style={{ padding: 16 }}>
            <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>
              {currentProperty.title}
            </h2>
            <p style={{ fontSize: 14, color: colors.textSecondary, marginBottom: 8 }}>
              {[currentProperty.locality, currentProperty.city].filter(Boolean).join(', ')}
            </p>

            {/* Specs */}
            <div style={{ display: 'flex', gap: 16, fontSize: 13, color: colors.textSecondary, marginBottom: 12 }}>
              {currentProperty.bedrooms && <span>{currentProperty.bedrooms} BHK</span>}
              {currentProperty.bathrooms && <span>{currentProperty.bathrooms} Bath</span>}
              {currentProperty.area_sqft && <span>{currentProperty.area_sqft.toLocaleString()} sq ft</span>}
            </div>

            {/* Price */}
            <p style={{ fontSize: 22, fontWeight: 700, color: colors.primary }}>
              {formatPrice(price, currentProperty.purpose)}
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
