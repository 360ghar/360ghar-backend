/**
 * OwnerDashboardWidget - Dashboard for property owners and agents.
 *
 * Tools: owner_properties_list and agent_properties_list (`items` and `stats`),
 * owner_dashboard_overview (`dashboard`), agent_dashboard_overview (`stats`, or `metrics`
 * on the admin server).
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import type { OwnerDashboardOutput, PropertyRow } from '../api/wire';
import {
  isToolFailure,
  toolFailureMessage,
  useCallTool,
  useSendMessage,
  useTheme,
  useToolInput,
  useToolOutput,
} from '../utils/bridge';
import { formatRupeesCompact } from '../utils/format';
import { pageArgs, readPage, usePagedRows, type PagedView } from '../utils/paging';
import { formatLocation, formatPropertyPrice } from '../utils/property';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { FullError, InlineError, LoadMore, LoadingNote, LoginRequired } from '../components/common/Notices';

interface StatTile {
  label: string;
  value: string;
}

/** The four counts the tiles and filter tabs show, and the money tiles beside them. */
interface Summary {
  total: number;
  occupied: number;
  vacant: number;
  money: StatTile[];
}

function readProperties(payload: OwnerDashboardOutput): PagedView<PropertyRow> | null {
  return payload.items ? { rows: payload.items, page: readPage(payload) } : null;
}

/**
 * The numbers for the tiles. Portfolio stats cover every property in scope, not the page.
 * Each producer names them differently: `stats` (property lists, in-app agent dashboard),
 * `dashboard` (owner_dashboard_overview, a DashboardOverview) and `metrics` (admin
 * agent_dashboard_overview). With none of them, the loaded rows are counted.
 */
function summarize(data: OwnerDashboardOutput, rows: PropertyRow[]): Summary {
  const { stats, dashboard, metrics } = data;

  if (stats) {
    const money: StatTile[] = [
      { label: 'Monthly Rent (Expected)', value: formatRupeesCompact(stats.total_monthly_income) },
    ];
    if (stats.open_maintenance_requests != null) {
      money.push({ label: 'Open Maintenance', value: String(stats.open_maintenance_requests) });
    }
    return { total: stats.total_properties, occupied: stats.occupied, vacant: stats.vacant, money };
  }

  if (dashboard) {
    return {
      total: dashboard.total_properties,
      occupied: dashboard.occupied_properties,
      vacant: dashboard.vacant_properties,
      money: [
        { label: 'Collected This Month', value: formatRupeesCompact(dashboard.monthly_revenue_current) },
        { label: 'Outstanding Rent', value: formatRupeesCompact(dashboard.outstanding_rent_total) },
        { label: 'Under Maintenance', value: String(dashboard.under_maintenance_properties) },
      ],
    };
  }

  if (metrics) {
    return {
      total: metrics.total_properties,
      occupied: metrics.active_leases,
      vacant: Math.max(metrics.total_properties - metrics.active_leases, 0),
      money: [
        { label: 'Monthly Rent (Expected)', value: formatRupeesCompact(metrics.monthly_rent_expected) },
        { label: 'Open Maintenance', value: String(metrics.open_maintenance_requests) },
      ],
    };
  }

  // Loaded rows only. Rent counts occupied properties.
  const occupiedRows = rows.filter((p) => p.has_active_lease);
  return {
    total: rows.length,
    occupied: occupiedRows.length,
    vacant: rows.length - occupiedRows.length,
    money: [
      {
        label: 'Monthly Rent (Expected)',
        value: formatRupeesCompact(occupiedRows.reduce((sum, p) => sum + (p.monthly_rent ?? 0), 0)),
      },
    ],
  };
}

function OwnerDashboardWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<OwnerDashboardOutput>();
  const toolInput = useToolInput();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [filter, setFilter] = React.useState<'all' | 'occupied' | 'vacant'>('all');
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { rows: properties, page, hasList, append } = usePagedRows(data, readProperties);

  if (!data) {
    return <LoadingNote text="Loading your properties..." />;
  }

  // Check for auth required
  if (data.requires_auth) {
    return <LoginRequired message="Please log in to view your property dashboard." />;
  }

  if (data.error) {
    return <FullError message={data.message || 'Failed to load properties'} />;
  }

  const summary = summarize(data, properties);

  // Filter properties
  const filteredProperties = properties.filter((p) => {
    if (filter === 'all') return true;
    if (filter === 'occupied') return p.has_active_lease;
    return !p.has_active_lease;
  });

  const handleViewProperty = (propertyId: number) => {
    sendMessage(`Show me details for property ${propertyId}`);
  };

  const handleAddProperty = () => {
    sendMessage('Help me list a new property');
  };

  const handleLoadMore = async () => {
    if (loadingMore || !page.has_more || !page.next_cursor) return;
    setLoadingMore(true);
    setError(null);

    const result = await callTool<OwnerDashboardOutput>(
      ['owner_properties_list', 'agent_properties_list'],
      pageArgs(toolInput, page.next_cursor),
    );
    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else {
      append(result);
    }
    setLoadingMore(false);
  };

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      padding: 16,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ fontSize: 20, fontWeight: 600 }}>My Properties</h2>
        <Button size="sm" onClick={handleAddProperty}>+ Add</Button>
      </div>

      {/* Stats Cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: 12,
        marginBottom: 20,
      }}>
        <Card padding="md">
          <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Total Properties</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{summary.total}</div>
        </Card>
        {summary.money.map((tile, index) => (
          <Card key={tile.label} padding="md">
            <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>{tile.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: index === 0 ? colors.success : colors.text }}>
              {tile.value}
            </div>
          </Card>
        ))}
        <Card
          padding="md"
          onClick={hasList ? () => setFilter('occupied') : undefined}
          style={{ cursor: hasList ? 'pointer' : 'default' }}
        >
          <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Occupied</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: colors.primary }}>{summary.occupied}</div>
        </Card>
        <Card
          padding="md"
          onClick={hasList ? () => setFilter('vacant') : undefined}
          style={{ cursor: hasList ? 'pointer' : 'default' }}
        >
          <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Vacant</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: colors.warning }}>{summary.vacant}</div>
        </Card>
      </div>

      {!hasList ? (
        <div style={{ marginBottom: 20 }}>
          <Button variant="secondary" onClick={() => sendMessage('Show my properties')}>
            Show My Properties
          </Button>
        </div>
      ) : (
        <>
          {/* Filter Tabs */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            {(['all', 'occupied', 'vacant'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  padding: '8px 16px',
                  borderRadius: 20,
                  border: 'none',
                  backgroundColor: filter === f ? colors.primary : colors.backgroundSecondary,
                  color: filter === f ? '#3D3829' : colors.text,
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: 'pointer',
                  textTransform: 'capitalize',
                }}
              >
                {f} ({f === 'all' ? summary.total : f === 'occupied' ? summary.occupied : summary.vacant})
              </button>
            ))}
          </div>

          <InlineError message={error} />

          {/* Property List */}
          {filteredProperties.length === 0 ? (
            <div style={{
              textAlign: 'center',
              padding: 40,
              color: colors.textSecondary,
              backgroundColor: colors.backgroundSecondary,
              borderRadius: 12,
            }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>🏠</div>
              <p style={{ fontSize: 16, marginBottom: 8 }}>
                {filter === 'all' ? "You haven't listed any properties yet." : `No ${filter} properties.`}
              </p>
              {filter === 'all' && (
                <Button onClick={handleAddProperty} style={{ marginTop: 16 }}>
                  List Your First Property
                </Button>
              )}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {filteredProperties.map((property) => (
                <Card
                  key={property.id}
                  padding="none"
                  onClick={() => handleViewProperty(property.id)}
                  style={{ overflow: 'hidden', cursor: 'pointer' }}
                >
                  <div style={{ display: 'flex' }}>
                    {/* Image */}
                    <div style={{
                      width: 100,
                      minHeight: 100,
                      backgroundColor: colors.backgroundSecondary,
                      flexShrink: 0,
                    }}>
                      {property.main_image_url && (
                        <img
                          src={property.main_image_url}
                          alt={property.title}
                          style={{
                            width: '100%',
                            height: '100%',
                            objectFit: 'cover',
                          }}
                        />
                      )}
                    </div>

                    {/* Content */}
                    <div style={{ flex: 1, padding: 12 }}>
                      {/* Status */}
                      <div style={{ marginBottom: 6 }}>
                        <span style={{
                          display: 'inline-block',
                          padding: '2px 8px',
                          borderRadius: 4,
                          fontSize: 11,
                          fontWeight: 500,
                          backgroundColor: property.has_active_lease
                            ? `${colors.success}20`
                            : property.is_available
                              ? `${colors.primary}20`
                              : `${colors.warning}20`,
                          color: property.has_active_lease
                            ? colors.success
                            : property.is_available
                              ? colors.primary
                              : colors.warning,
                        }}>
                          {property.has_active_lease ? 'Occupied' : property.is_available ? 'Available' : 'Unlisted'}
                        </span>
                        {property.tenant_name && (
                          <span style={{ fontSize: 12, color: colors.textSecondary, marginLeft: 8 }}>
                            • {property.tenant_name}
                          </span>
                        )}
                      </div>

                      {/* Title */}
                      <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 2 }}>
                        {property.title}
                      </h3>

                      {/* Location */}
                      <p style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 8 }}>
                        {formatLocation(property)}
                      </p>

                      {/* Specs & Price */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ fontSize: 12, color: colors.textSecondary }}>
                          {property.bedrooms ? `${property.bedrooms} BHK` : null}
                          {property.area_sqft ? ` • ${property.area_sqft.toLocaleString()} sq ft` : null}
                        </div>
                        <div style={{ fontSize: 14, fontWeight: 600, color: colors.primary }}>
                          {formatPropertyPrice(property)}
                        </div>
                      </div>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}

          <LoadMore hasMore={page.has_more && page.next_cursor !== null} loading={loadingMore} onClick={handleLoadMore} />
        </>
      )}

      {/* Quick Actions */}
      <div style={{
        marginTop: 24,
        padding: 16,
        backgroundColor: colors.backgroundSecondary,
        borderRadius: 12,
      }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Quick Actions</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => sendMessage('Show maintenance requests for my properties')}
          >
            Maintenance
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => sendMessage('Show rent collection status for my properties')}
          >
            Rent Status
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => sendMessage('Show my leases')}
          >
            Leases
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => sendMessage('Show property visit requests')}
          >
            Visit Requests
          </Button>
        </div>
      </div>
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<OwnerDashboardWidget />);
