/**
 * ImageWithFallback - Image component with error handling and fallback.
 *
 * Displays a placeholder when the image fails to load.
 */

import React, { useState, CSSProperties } from 'react';
import { useTheme } from '../../utils/bridge';
import { themeColors } from '../../utils/theme';

interface ImageWithFallbackProps {
  src: string | null | undefined;
  alt: string;
  style?: CSSProperties;
  fallbackIcon?: string;
  className?: string;
}

export function ImageWithFallback({
  src,
  alt,
  style,
  fallbackIcon = '🏠',
  className,
}: ImageWithFallbackProps) {
  const theme = useTheme();
  const colors = themeColors[theme];
  const [hasError, setHasError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const handleError = () => {
    setHasError(true);
    setIsLoading(false);
  };

  const handleLoad = () => {
    setIsLoading(false);
  };

  // Show fallback if no src or error occurred
  if (!src || hasError) {
    return (
      <div
        className={className}
        style={{
          ...style,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: colors.backgroundSecondary,
          color: colors.textSecondary,
        }}
        role="img"
        aria-label={alt}
      >
        <span style={{ fontSize: '2rem' }}>{fallbackIcon}</span>
      </div>
    );
  }

  return (
    <>
      {isLoading && (
        <div
          className={className}
          style={{
            ...style,
            position: 'absolute',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: colors.backgroundSecondary,
          }}
        >
          <span
            style={{
              width: 24,
              height: 24,
              border: `2px solid ${colors.border}`,
              borderTopColor: colors.primary,
              borderRadius: '50%',
              animation: 'spin 1s linear infinite',
            }}
          />
        </div>
      )}
      <img
        src={src}
        alt={alt}
        className={className}
        style={{
          ...style,
          opacity: isLoading ? 0 : 1,
          transition: 'opacity 0.2s ease-in-out',
        }}
        onError={handleError}
        onLoad={handleLoad}
      />
    </>
  );
}
