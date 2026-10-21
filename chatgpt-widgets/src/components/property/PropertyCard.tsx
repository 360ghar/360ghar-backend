/**
 * PropertyCard component for displaying property in a list.
 */

import React from 'react';
import type { PropertyRow } from '../../api/wire';
import { isToolFailure, toolFailureMessage, useCallTool, useSendMessage } from '../../utils/bridge';
import { formatLocation, formatPropertyPrice, purposeLabel } from '../../utils/property';
import { useThemeColors } from '../../utils/theme';
import { Card } from '../common/Card';

interface PropertyCardProps {
  property: PropertyRow;
  showActions?: boolean;
}

export function PropertyCard({ property, showActions = true }: PropertyCardProps) {
  const colors = useThemeColors();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [liked, setLiked] = React.useState(false);
  const [liking, setLiking] = React.useState(false);
  const [likeError, setLikeError] = React.useState<string | null>(null);

  const handleViewDetails = () => {
    sendMessage(`Show me details for property ${property.id}`);
  };

  const handleLike = async () => {
    if (liked || liking) return;
    setLiking(true);
    setLikeError(null);
    const result = await callTool('discovery_swipe', { property_id: property.id, is_liked: true });
    if (isToolFailure(result)) {
      setLikeError(toolFailureMessage(result));
    } else {
      setLiked(true);
    }
    setLiking(false);
  };

  const badge = purposeLabel(property.purpose);

  return (
    <Card padding="none" style={{ overflow: 'hidden', borderRadius: 16 }}>
      {/* Image */}
      <div style={{ position: 'relative', paddingTop: '58%', backgroundColor: colors.surfaceTint }}>
        {property.main_image_url && (
          <img
            src={property.main_image_url}
            alt={property.title}
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
        {/* Purpose badge */}
        {badge && (
          <span
            style={{
              position: 'absolute',
              top: 10,
              left: 10,
              backgroundColor: 'rgba(28, 26, 22, 0.85)',
              color: '#F2EDE0',
              padding: '4px 10px',
              borderRadius: 999,
              fontSize: 11,
              letterSpacing: '0.03em',
              textTransform: 'uppercase',
              fontWeight: 600,
            }}
          >
            {badge}
          </span>
        )}
      </div>

      {/* Content */}
      <div style={{ padding: 14 }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4, color: colors.text }}>
          {property.title}
        </h3>
        <p style={{ fontSize: 14, color: colors.textSecondary, marginBottom: 8 }}>
          {formatLocation(property)}
        </p>

        {/* Specs */}
        <div style={{ display: 'flex', gap: 12, fontSize: 13, color: colors.textSecondary, marginBottom: 8 }}>
          {property.bedrooms ? <span>{property.bedrooms} BHK</span> : null}
          {property.bathrooms ? <span>{property.bathrooms} Bath</span> : null}
          {property.area_sqft ? <span>{property.area_sqft.toLocaleString()} sq ft</span> : null}
        </div>

        {/* Price */}
        <p style={{ fontSize: 19, fontWeight: 700, color: colors.primary, marginBottom: 12 }}>
          {formatPropertyPrice(property)}
        </p>

        {/* Actions */}
        {showActions && (
          <>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={handleViewDetails}
                style={{
                  flex: 1,
                  padding: '9px 12px',
                  backgroundColor: colors.primary,
                  color: '#3D3829',
                  border: 'none',
                  borderRadius: 8,
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                View Details
              </button>
              <button
                onClick={handleLike}
                disabled={liked || liking}
                style={{
                  padding: '8px 11px',
                  backgroundColor: colors.surfaceTint,
                  color: colors.primary,
                  border: `1px solid ${colors.border}`,
                  borderRadius: 8,
                  fontSize: 18,
                  cursor: liked || liking ? 'default' : 'pointer',
                }}
                title={liked ? 'Saved to shortlist' : 'Save to shortlist'}
              >
                {liked ? '♥' : '♡'}
              </button>
            </div>
            {likeError && (
              <p role="alert" style={{ fontSize: 12, color: colors.error, marginTop: 8 }}>
                {likeError}
              </p>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
