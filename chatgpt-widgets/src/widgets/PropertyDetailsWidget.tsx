/**
 * PropertyDetailsWidget - Displays full property details.
 *
 * Tool: discovery.property.get
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { useToolOutput, useTheme, useSendMessage, useCallTool } from '../utils/bridge';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';

interface PropertyImage {
  id: number;
  url: string;
  caption?: string;
}

interface Amenity {
  id: number;
  name: string;
  icon?: string;
}

interface PropertyDetails {
  id: number;
  title: string;
  description?: string;
  locality?: string;
  city?: string;
  state?: string;
  pincode?: string;
  full_address?: string;
  latitude?: number;
  longitude?: number;
  base_price?: number;
  monthly_rent?: number;
  bedrooms?: number;
  bathrooms?: number;
  area_sqft?: number;
  property_type?: string;
  purpose?: string;
  main_image_url?: string;
  images?: PropertyImage[];
  amenities?: Amenity[];
  is_available?: boolean;
  furnished_status?: string;
  floor_number?: number;
  total_floors?: number;
  facing?: string;
  age_years?: number;
  user_liked?: boolean;
  owner_name?: string;
  owner_phone?: string;
}

interface PropertyDetailsOutput {
  property?: PropertyDetails;
  error?: boolean;
  code?: string;
  message?: string;
}

function formatPrice(price?: number, purpose?: string): string {
  if (!price) return 'Price on request';
  const formatted = price >= 10000000
    ? `₹${(price / 10000000).toFixed(2)} Cr`
    : price >= 100000
      ? `₹${(price / 100000).toFixed(2)} L`
      : `₹${price.toLocaleString('en-IN')}`;
  return purpose === 'rent' ? `${formatted}/month` : formatted;
}

function PropertyDetailsWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<PropertyDetailsOutput>();
  const sendMessage = useSendMessage();
  const callTool = useCallTool();
  const [currentImageIndex, setCurrentImageIndex] = React.useState(0);
  const [isLiked, setIsLiked] = React.useState(false);

  React.useEffect(() => {
    if (data?.property?.user_liked) {
      setIsLiked(true);
    }
  }, [data?.property?.user_liked]);

  if (!data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
        Loading property details...
      </div>
    );
  }

  if (data.error) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.error }}>
        <h3 style={{ marginBottom: 8 }}>
          {data.code === 'NOT_FOUND' ? 'Property Not Found' : 'Error'}
        </h3>
        <p>{data.message || 'Failed to load property details'}</p>
      </div>
    );
  }

  const property = data.property!;
  const images = property.images || (property.main_image_url ? [{ id: 0, url: property.main_image_url }] : []);
  const price = property.purpose === 'rent' ? property.monthly_rent : property.base_price;

  const handleScheduleVisit = () => {
    sendMessage(`I'd like to schedule a visit for property ${property.id}: ${property.title}`);
  };

  const handleLike = async () => {
    await callTool('discovery.swipe', { property_id: property.id, is_liked: true });
    setIsLiked(true);
  };

  const handleShare = () => {
    sendMessage(`Share property ${property.id}: ${property.title}`);
  };

  const handlePrevImage = () => {
    setCurrentImageIndex((prev) => (prev > 0 ? prev - 1 : images.length - 1));
  };

  const handleNextImage = () => {
    setCurrentImageIndex((prev) => (prev < images.length - 1 ? prev + 1 : 0));
  };

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
    }}>
      {/* Image Gallery */}
      {images.length > 0 && (
        <div style={{ position: 'relative', width: '100%', paddingTop: '56.25%', backgroundColor: colors.backgroundSecondary }}>
          <img
            src={images[currentImageIndex].url}
            alt={images[currentImageIndex].caption || property.title}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              objectFit: 'cover',
            }}
          />
          {images.length > 1 && (
            <>
              <button
                onClick={handlePrevImage}
                style={{
                  position: 'absolute',
                  left: 12,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  backgroundColor: 'rgba(28, 26, 22, 0.70)',
                  color: '#F2EDE0',
                  border: 'none',
                  borderRadius: '50%',
                  width: 40,
                  height: 40,
                  fontSize: 20,
                  cursor: 'pointer',
                }}
              >
                ‹
              </button>
              <button
                onClick={handleNextImage}
                style={{
                  position: 'absolute',
                  right: 12,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  backgroundColor: 'rgba(28, 26, 22, 0.70)',
                  color: '#F2EDE0',
                  border: 'none',
                  borderRadius: '50%',
                  width: 40,
                  height: 40,
                  fontSize: 20,
                  cursor: 'pointer',
                }}
              >
                ›
              </button>
              <div style={{
                position: 'absolute',
                bottom: 12,
                left: '50%',
                transform: 'translateX(-50%)',
                display: 'flex',
                gap: 6,
              }}>
                {images.map((_, idx) => (
                  <div
                    key={idx}
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      backgroundColor: idx === currentImageIndex ? '#F2EDE0' : 'rgba(242, 237, 224, 0.50)',
                    }}
                  />
                ))}
              </div>
            </>
          )}
          {/* Badges */}
          <div style={{ position: 'absolute', top: 12, left: 12, display: 'flex', gap: 8 }}>
            <span style={{
              backgroundColor: 'rgba(28, 26, 22, 0.85)',
              color: '#F2EDE0',
              padding: '6px 12px',
              borderRadius: 6,
              fontSize: 12,
              fontWeight: 500,
              textTransform: 'uppercase',
            }}>
              {property.purpose === 'rent' ? 'For Rent' : property.purpose === 'short_stay' ? 'Short Stay' : 'For Sale'}
            </span>
            {property.is_available === false && (
              <span style={{
                backgroundColor: colors.error,
                color: '#F2EDE0',
                padding: '6px 12px',
                borderRadius: 6,
                fontSize: 12,
                fontWeight: 500,
              }}>
                Unavailable
              </span>
            )}
          </div>
        </div>
      )}

      {/* Content */}
      <div style={{ padding: 16 }}>
        {/* Title and Price */}
        <div style={{ marginBottom: 16 }}>
          <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 4 }}>{property.title}</h1>
          <p style={{ fontSize: 14, color: colors.textSecondary, marginBottom: 8 }}>
            {[property.locality, property.city, property.state].filter(Boolean).join(', ')}
          </p>
          <p style={{ fontSize: 28, fontWeight: 700, color: colors.primary }}>
            {formatPrice(price, property.purpose)}
          </p>
        </div>

        {/* Quick Specs */}
        <Card padding="md" style={{ marginBottom: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, textAlign: 'center' }}>
            {property.bedrooms !== undefined && (
              <div>
                <div style={{ fontSize: 20, fontWeight: 600 }}>{property.bedrooms}</div>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>Bedrooms</div>
              </div>
            )}
            {property.bathrooms !== undefined && (
              <div>
                <div style={{ fontSize: 20, fontWeight: 600 }}>{property.bathrooms}</div>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>Bathrooms</div>
              </div>
            )}
            {property.area_sqft !== undefined && (
              <div>
                <div style={{ fontSize: 20, fontWeight: 600 }}>{property.area_sqft.toLocaleString()}</div>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>Sq Ft</div>
              </div>
            )}
            {property.property_type && (
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, textTransform: 'capitalize' }}>{property.property_type}</div>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>Type</div>
              </div>
            )}
          </div>
        </Card>

        {/* Description */}
        {property.description && (
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Description</h3>
            <p style={{ fontSize: 14, color: colors.textSecondary, lineHeight: 1.6 }}>
              {property.description}
            </p>
          </div>
        )}

        {/* Property Details */}
        <Card padding="md" style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Property Details</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
            {property.furnished_status && (
              <div>
                <span style={{ color: colors.textSecondary, fontSize: 13 }}>Furnished Status:</span>
                <span style={{ marginLeft: 8, fontSize: 14, textTransform: 'capitalize' }}>{property.furnished_status}</span>
              </div>
            )}
            {property.floor_number !== undefined && (
              <div>
                <span style={{ color: colors.textSecondary, fontSize: 13 }}>Floor:</span>
                <span style={{ marginLeft: 8, fontSize: 14 }}>
                  {property.floor_number} of {property.total_floors || '?'}
                </span>
              </div>
            )}
            {property.facing && (
              <div>
                <span style={{ color: colors.textSecondary, fontSize: 13 }}>Facing:</span>
                <span style={{ marginLeft: 8, fontSize: 14, textTransform: 'capitalize' }}>{property.facing}</span>
              </div>
            )}
            {property.age_years !== undefined && (
              <div>
                <span style={{ color: colors.textSecondary, fontSize: 13 }}>Age:</span>
                <span style={{ marginLeft: 8, fontSize: 14 }}>{property.age_years} years</span>
              </div>
            )}
          </div>
        </Card>

        {/* Amenities */}
        {property.amenities && property.amenities.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Amenities</h3>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {property.amenities.map((amenity) => (
                <span
                  key={amenity.id}
                  style={{
                    backgroundColor: colors.backgroundSecondary,
                    padding: '8px 12px',
                    borderRadius: 20,
                    fontSize: 13,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  {amenity.icon && <span>{amenity.icon}</span>}
                  {amenity.name}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
          <Button
            onClick={handleScheduleVisit}
            size="lg"
            style={{ flex: 1 }}
          >
            Schedule Visit
          </Button>
          <Button
            onClick={handleLike}
            variant="secondary"
            size="lg"
            disabled={isLiked}
            style={{ minWidth: 56 }}
          >
            {isLiked ? '♥' : '♡'}
          </Button>
        </div>
      </div>
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<PropertyDetailsWidget />);
