/**
 * PropertyCard component for displaying property in a list.
 */

import React from 'react';
import { useThemeColors } from '../../utils/theme';
import { useCallTool, useSendMessage } from '../../utils/bridge';
import { Card } from '../common/Card';
import { ImageWithFallback } from '../common/ImageWithFallback';

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

interface PropertyCardProps {
  property: Property;
  showActions?: boolean;
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

export function PropertyCard({ property, showActions = true }: PropertyCardProps) {
  const colors = useThemeColors();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();

  const handleViewDetails = () => {
    sendMessage(`Show me details for property ${property.id}`);
  };

  const handleScheduleVisit = () => {
    sendMessage(`I'd like to schedule a visit for property ${property.id}`);
  };

  const handleLike = async () => {
    await callTool('discovery.swipe', { property_id: property.id, is_liked: true });
  };

  const price = property.purpose === 'rent' ? property.monthly_rent : property.base_price;

  return (
    <Card padding="none" style={{ overflow: 'hidden' }}>
      {/* Image */}
      <div style={{ position: 'relative', paddingTop: '56.25%', backgroundColor: colors.backgroundSecondary }}>
        <ImageWithFallback
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
        {/* Purpose badge */}
        <span
          style={{
            position: 'absolute',
            top: 8,
            left: 8,
            backgroundColor: 'rgba(0,0,0,0.7)',
            color: '#fff',
            padding: '4px 8px',
            borderRadius: 4,
            fontSize: 12,
            textTransform: 'uppercase',
          }}
        >
          {property.purpose || 'For Sale'}
        </span>
      </div>

      {/* Content */}
      <div style={{ padding: 12 }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4, color: colors.text }}>
          {property.title}
        </h3>
        <p style={{ fontSize: 14, color: colors.textSecondary, marginBottom: 8 }}>
          {[property.locality, property.city].filter(Boolean).join(', ')}
        </p>

        {/* Specs */}
        <div style={{ display: 'flex', gap: 12, fontSize: 13, color: colors.textSecondary, marginBottom: 8 }}>
          {property.bedrooms && <span>{property.bedrooms} BHK</span>}
          {property.bathrooms && <span>{property.bathrooms} Bath</span>}
          {property.area_sqft && <span>{property.area_sqft.toLocaleString()} sq ft</span>}
        </div>

        {/* Price */}
        <p style={{ fontSize: 18, fontWeight: 700, color: colors.primary, marginBottom: 12 }}>
          {formatPrice(price, property.purpose)}
        </p>

        {/* Actions */}
        {showActions && (
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleViewDetails}
              style={{
                flex: 1,
                padding: '8px 12px',
                backgroundColor: colors.primary,
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                fontSize: 14,
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              View Details
            </button>
            <button
              onClick={handleLike}
              style={{
                padding: '8px 12px',
                backgroundColor: 'transparent',
                color: colors.error,
                border: `1px solid ${colors.border}`,
                borderRadius: 6,
                fontSize: 18,
                cursor: 'pointer',
              }}
              title="Save to shortlist"
            >
              ♡
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}
