/**
 * PropertySearchWidget - Displays search results in a grid layout.
 *
 * Tools: discovery_search, discovery_recommendations, discovery_shortlist
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import type { PropertyRow, PropertySearchOutput } from '../api/wire';
import {
  isToolFailure,
  toolFailureMessage,
  useCallTool,
  useSendMessage,
  useTheme,
  useToolInput,
  useToolOutput,
} from '../utils/bridge';
import { formatFilterValue } from '../utils/format';
import { pageArgs, readPage, usePagedRows, type PagedView } from '../utils/paging';
import { themeColors } from '../utils/theme';
import { PropertyCard } from '../components/property/PropertyCard';
import { FullError, InlineError, LoadMore, LoadingNote, LoginRequired } from '../components/common/Notices';

/** discovery_search sends `items`. discovery_recommendations and discovery_shortlist send `properties`. */
function readSearch(payload: PropertySearchOutput): PagedView<PropertyRow> | null {
  const rows = payload.items ?? payload.properties;
  return rows ? { rows, page: readPage(payload) } : null;
}

function PropertySearchWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<PropertySearchOutput>();
  const toolInput = useToolInput();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { rows: properties, page, append } = usePagedRows(data, readSearch);

  if (!data) {
    return <LoadingNote text="Loading..." />;
  }

  if (data.requires_auth) {
    return <LoginRequired message="Please log in to view your shortlist." />;
  }

  if (data.error) {
    return <FullError message={data.message || 'An error occurred'} />;
  }

  const { total, filters_applied } = data;
  // Only discovery_shortlist sends `properties` with a cursor. Its cursor is not bound to a search.
  const isShortlist = data.properties != null;

  const handleLoadMore = async () => {
    if (loading || !page.has_more || !page.next_cursor) return;
    setLoading(true);
    setError(null);

    // The cursor is bound to the filters of the call that made it. Resend that call's
    // arguments (the model's input), or the applied filters when the host sent no input.
    const limit = data.limit ? { limit: data.limit } : {};
    const result = isShortlist
      ? await callTool<PropertySearchOutput>('discovery_shortlist', { cursor: page.next_cursor, ...limit })
      : await callTool<PropertySearchOutput>(
          'discovery_search',
          Object.keys(toolInput).length > 0
            ? pageArgs(toolInput, page.next_cursor)
            : { ...filters_applied, cursor: page.next_cursor, ...limit },
        );

    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else {
      append(result);
    }
    setLoading(false);
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
          {typeof total === 'number'
            ? `${total} ${total === 1 ? 'Property' : 'Properties'} Found`
            : `${properties.length} ${properties.length === 1 ? 'Property' : 'Properties'} Shown`}
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
                {key}: {formatFilterValue(value)}
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
          <InlineError message={error} />
          <LoadMore hasMore={page.has_more && page.next_cursor !== null} loading={loading} onClick={handleLoadMore} />
        </>
      )}
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<PropertySearchWidget />);
