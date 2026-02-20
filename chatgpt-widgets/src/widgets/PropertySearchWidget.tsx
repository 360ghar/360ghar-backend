/**
 * PropertySearchWidget - Displays search results in a grid layout.
 *
 * Tool: discovery.search
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { useToolOutput, useTheme, useCallTool, useSendMessage } from '../utils/bridge';
import { themeColors } from '../utils/theme';
import { PropertyCard } from '../components/property/PropertyCard';

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

interface SearchOutput {
  properties: Property[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  filters_applied?: Record<string, unknown>;
  error?: boolean;
  message?: string;
}

function PropertySearchWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<SearchOutput>();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [loading, setLoading] = React.useState(false);

  if (!data) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: colors.textSecondary }}>
        Loading...
      </div>
    );
  }

  if (data.error) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: colors.error }}>
        {data.message || 'An error occurred'}
      </div>
    );
  }

  const { properties, total, page, total_pages, filters_applied } = data;

  const handleLoadMore = async () => {
    if (loading || page >= total_pages) return;
    setLoading(true);
    try {
      await callTool('discovery.search', {
        ...filters_applied,
        page: page + 1,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleRefineSearch = () => {
    sendMessage('I want to refine my property search');
  };

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      padding: 16,
    }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>
          {total} Properties Found
        </h2>
        {filters_applied && Object.keys(filters_applied).length > 0 && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
            {Object.entries(filters_applied).map(([key, value]) => (
              <span
                key={key}
                style={{
                  backgroundColor: colors.backgroundSecondary,
                  padding: '4px 8px',
                  borderRadius: 4,
                  fontSize: 12,
                  color: colors.textSecondary,
                }}
              >
                {key}: {String(value)}
              </span>
            ))}
            <button
              onClick={handleRefineSearch}
              style={{
                backgroundColor: 'transparent',
                border: `1px solid ${colors.primary}`,
                color: colors.primary,
                padding: '4px 8px',
                borderRadius: 4,
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              Refine Search
            </button>
          </div>
        )}
      </div>

      {/* Results Grid */}
      {properties.length === 0 ? (
        <div style={{
          textAlign: 'center',
          padding: 40,
          color: colors.textSecondary,
          backgroundColor: colors.backgroundSecondary,
          borderRadius: 12,
        }}>
          <p style={{ fontSize: 16, marginBottom: 8 }}>No properties found</p>
          <p style={{ fontSize: 14 }}>Try adjusting your search filters</p>
        </div>
      ) : (
        <>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: 16,
          }}>
            {properties.map((property) => (
              <PropertyCard key={property.id} property={property} />
            ))}
          </div>

          {/* Pagination */}
          {page < total_pages && (
            <div style={{ marginTop: 20, textAlign: 'center' }}>
              <button
                onClick={handleLoadMore}
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
                {loading ? 'Loading...' : `Load More (Page ${page + 1} of ${total_pages})`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<PropertySearchWidget />);
