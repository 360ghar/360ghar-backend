/**
 * OwnerDashboardWidget - Dashboard for property owners.
 *
 * Tool: owner.properties.list
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { useToolOutput, useTheme, useCallTool, useSendMessage } from '../utils/bridge';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';

interface Property {
  id: number;
  title: string;
  locality?: string;
  city?: string;
  base_price?: number;
  monthly_rent?: number;
  property_type?: string;
  purpose?: string;
  main_image_url?: string;
  is_available?: boolean;
  bedrooms?: number;
  bathrooms?: number;
  area_sqft?: number;
  has_active_lease?: boolean;
  tenant_name?: string;
}

interface OwnerDashboardOutput {
  items?: Property[];
  total?: number;
  page?: number;
  limit?: number;
  stats?: {
    total_properties: number;
    occupied: number;
    vacant: number;
    total_monthly_income: number;
  };
  error?: boolean;
  message?: string;
  requires_auth?: boolean;
}

function formatPrice(price?: number): string {
  if (!price) return '₹0';
  if (price >= 10000000) return `₹${(price / 10000000).toFixed(2)} Cr`;
  if (price >= 100000) return `₹${(price / 100000).toFixed(2)} L`;
  return `₹${price.toLocaleString('en-IN')}`;
}

function OwnerDashboardWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<OwnerDashboardOutput>();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [filter, setFilter] = React.useState<'all' | 'occupied' | 'vacant'>('all');

  if (!data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
        Loading your properties...
      </div>
    );
  }

  // Check for auth required
  if (data.requires_auth) {
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
        <p style={{ color: colors.textSecondary, marginBottom: 24 }}>
          Please log in to view your property dashboard.
        </p>
        <Button onClick={() => sendMessage('Help me log in to 360Ghar')}>
          Log In
        </Button>
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

  const properties = data.items || [];
  const stats = data.stats || {
    total_properties: properties.length,
    occupied: properties.filter((p) => p.has_active_lease).length,
    vacant: properties.filter((p) => !p.has_active_lease).length,
    total_monthly_income: properties.reduce((sum, p) => sum + (p.monthly_rent || 0), 0),
  };

  // Filter properties
  const filteredProperties = properties.filter((p) => {
    if (filter === 'all') return true;
    if (filter === 'occupied') return p.has_active_lease;
    if (filter === 'vacant') return !p.has_active_lease;
    return true;
  });

  const handleViewProperty = (propertyId: number) => {
    sendMessage(`Show me details for property ${propertyId}`);
  };

  const handleAddProperty = () => {
    sendMessage('Help me list a new property');
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
          <div style={{ fontSize: 24, fontWeight: 700 }}>{stats.total_properties}</div>
        </Card>
        <Card padding="md">
          <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Monthly Income</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: colors.success }}>
            {formatPrice(stats.total_monthly_income)}
          </div>
        </Card>
        <Card padding="md" onClick={() => setFilter('occupied')} style={{ cursor: 'pointer' }}>
          <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Occupied</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: colors.primary }}>{stats.occupied}</div>
        </Card>
        <Card padding="md" onClick={() => setFilter('vacant')} style={{ cursor: 'pointer' }}>
          <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Vacant</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: colors.warning }}>{stats.vacant}</div>
        </Card>
      </div>

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
            {f} ({f === 'all' ? stats.total_properties : f === 'occupied' ? stats.occupied : stats.vacant})
          </button>
        ))}
      </div>

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
                    {[property.locality, property.city].filter(Boolean).join(', ')}
                  </p>

                  {/* Specs & Price */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ fontSize: 12, color: colors.textSecondary }}>
                      {property.bedrooms && `${property.bedrooms} BHK`}
                      {property.area_sqft && ` • ${property.area_sqft.toLocaleString()} sq ft`}
                    </div>
                    {property.monthly_rent && (
                      <div style={{ fontSize: 14, fontWeight: 600, color: colors.primary }}>
                        {formatPrice(property.monthly_rent)}/mo
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
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
