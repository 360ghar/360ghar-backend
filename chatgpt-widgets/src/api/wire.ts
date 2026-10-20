/**
 * Wire types for the widgets.
 *
 * Source of truth: `openapi/openapi.json` (generated into `schema.gen.ts`).
 *
 * 1. Enums and payload envelopes are aliases of the generated components.
 * 2. The row objects inside the payloads (`items`, `leases`, `charges`, ...) are free-form
 *    objects in OpenAPI (`list[dict[str, Any]]`). Their shapes follow the MCP serializers in
 *    `app/mcp/utils.py`, `app/mcp/tool_ops/*` and `app/mcp/chatgpt/*`. They are declared here by hand.
 * 3. Enum values on rows are typed `string | null` (the raw wire value). Parse them with
 *    `enumKey()` and the tables in `utils/status.ts`: a value the table does not hold gives null.
 * 4. Money is a JSON number. Datetimes are UTC ISO strings with a Z suffix. Date-only fields
 *    are `YYYY-MM-DD`.
 */

import type { components } from './schema.gen';

type Schemas = components['schemas'];

// ---------------------------------------------------------------------------
// Enums (generated)
// ---------------------------------------------------------------------------

export type PropertyPurpose = Schemas['PropertyPurpose'];
export type PropertyType = Schemas['PropertyType'];
export type FurnishingLevel = Schemas['FurnishingLevel'];
export type VisitStatus = Schemas['VisitStatus'];
export type BookingStatus = Schemas['BookingStatus'];
export type LeaseStatus = Schemas['LeaseStatus'];
export type RentChargeStatus = Schemas['RentChargeStatus'];
export type RentPaymentStatus = Schemas['RentPaymentStatus'];
export type PaymentMethod = Schemas['PaymentMethod'];
export type MaintenanceCategory = Schemas['MaintenanceCategory'];

/**
 * Status and priority labels of the MCP maintenance tools. They are not an OpenAPI enum:
 * `serialize_maintenance_request` derives them (app/mcp/utils.py), and the tool arguments
 * are typed Literals (app/mcp/tool_ops/maintenance.py).
 */
export type MaintenanceStatusLabel = 'open' | 'in_progress' | 'scheduled' | 'completed' | 'cancelled';
export type MaintenancePriorityLabel = 'low' | 'medium' | 'high' | 'urgent';

// ---------------------------------------------------------------------------
// Payload helpers
// ---------------------------------------------------------------------------

/**
 * The generated payload models allow extra keys (`extra="allow"`), so openapi-typescript
 * adds an index signature. `Known` keeps the declared keys only, so a row type can replace
 * the free-form `items` type without losing the other keys.
 */
export type Known<T> = {
  [K in keyof T as string extends K ? never : number extends K ? never : K]: T[K];
};

/** Keys any tool result can carry besides the payload keys. */
export interface ToolResultKeys {
  requires_auth?: boolean;
  action?: string;
  code?: string;
}

type PayloadWithRows<P, Key extends string, Row> = Omit<Known<P>, Key> &
  { [K in Key]?: Row[] | null } &
  ToolResultKeys;

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

/** The property fields nested in visits, leases and bookings. */
export interface PropertyRef {
  id: number;
  title: string;
  locality: string | null;
  city: string | null;
  full_address?: string | null;
  main_image_url: string | null;
}

/** serialize_property_basic, plus the owner list enrichment. */
export interface PropertyRow extends PropertyRef {
  property_type: string | null;
  purpose: string | null;
  status: string | null;
  /** Buy price. */
  base_price: number | null;
  /** Same value as base_price. */
  price: number | null;
  monthly_rent: number | null;
  /** Nightly rate of a short stay. REST names it nightly_rate too (Property.nightly_rate). */
  daily_rate: number | null;
  nightly_rate?: number | null;
  bedrooms: number | null;
  bathrooms: number | null;
  area_sqft: number | null;
  is_available: boolean;
  is_managed: boolean;
  management_status: string | null;
  latitude: number | null;
  longitude: number | null;
  created_at: string | null;
  has_active_lease?: boolean;
  tenant_name?: string;
  swiped_at?: string | null;
}

export interface PropertyImage {
  url: string;
  caption: string | null;
}

export interface PropertyAmenity {
  id: number | null;
  name: string | null;
  icon: string | null;
  category: string | null;
}

/** serialize_property_full. */
export interface PropertyDetailRow extends PropertyRow {
  /** Owner number for the owner and admins. The agent or company number for everyone else. */
  owner_phone: string | null;
  owner_name: string | null;
  /** FurnishingLevel value. */
  furnished_status: string | null;
  age_years: number | null;
  description: string | null;
  sub_locality: string | null;
  landmark: string | null;
  pincode: string | null;
  state: string | null;
  country: string | null;
  price_per_sqft: number | null;
  security_deposit: number | null;
  maintenance_charges: number | null;
  balconies: number | null;
  parking_spaces: number | null;
  floor_number: number | null;
  total_floors: number | null;
  max_occupancy: number | null;
  available_from: string | null;
  minimum_stay_days: number | null;
  view_count: number;
  like_count: number;
  images: PropertyImage[];
  amenities: PropertyAmenity[];
  updated_at: string | null;
  user_liked?: boolean;
}

/** visit_tools._serialize_visit. `status` is a VisitStatus value. */
export interface VisitRow {
  id: number;
  property_id: number;
  property: PropertyRef | null;
  scheduled_date: string;
  status: string | null;
  notes: string | null;
  created_at: string | null;
}

/** serialize_booking. `status` repeats `booking_status`. `scheduled_date` repeats `check_in_date`. */
export interface BookingRow {
  id: number;
  booking_reference: string | null;
  property_id: number;
  property: PropertyRow | null;
  status: string | null;
  scheduled_date: string | null;
  user_id: number;
  check_in_date: string | null;
  check_out_date: string | null;
  guests: number | null;
  nights: number | null;
  base_amount: number;
  taxes_amount: number;
  service_charges: number;
  discount_amount: number;
  total_amount: number;
  booking_status: string | null;
  payment_status: string | null;
  payment_method: string | null;
  special_requests: string | null;
  cancellation_reason: string | null;
  cancellation_date: string | null;
  created_at: string | null;
}

export type VisitListRow = VisitRow | BookingRow;

/** The tenant of a lease: a PublicUserRef. Contact fields only reach the owner, admins and the tenant. */
export type LeaseTenant = Schemas['PublicUserRef'] & {
  phone?: string | null;
  email?: string | null;
};

/** serialize_lease. Dates are YYYY-MM-DD. */
export interface LeaseRow {
  id: number;
  property_id: number;
  property: PropertyRef | null;
  owner_id: number | null;
  tenant_user_id: number | null;
  tenant: LeaseTenant | null;
  start_date: string | null;
  end_date: string | null;
  monthly_rent: number;
  security_deposit: number;
  status: string | null;
  payment_due_day: number | null;
  grace_period_days: number | null;
  late_fee_amount: number | null;
  late_fee_percentage: number | null;
  terms: Record<string, unknown> | null;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** serialize_maintenance_request. */
export interface MaintenanceRow {
  id: number;
  property_id: number | null;
  lease_id: number | null;
  reported_by_user_id: number | null;
  tenant_user_id: number | null;
  title: string | null;
  description: string | null;
  /** MaintenanceCategory value. */
  category: string | null;
  /** MaintenancePriorityLabel value. */
  priority: string | null;
  /** MaintenanceStatusLabel value. */
  status: string | null;
  request_status: string | null;
  work_order_status: string | null;
  estimated_cost: number | null;
  actual_cost: number | null;
  scheduled_date: string | null;
  completed_at: string | null;
  vendor_name: string | null;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Rent charge rows of owner_rent_status, agent_rent_list_due and tenant_rent_dues. */
export interface RentChargeRow {
  id: number;
  lease_id: number;
  property_id?: number;
  owner_id?: number;
  tenant_user_id?: number | null;
  /** Date, YYYY-MM-DD. */
  billing_month: string | null;
  /** Date, YYYY-MM-DD. */
  due_date: string | null;
  grace_end?: string | null;
  /** Rent plus the late fee, including the fee the daily job has not stored yet. */
  amount_due: number;
  amount_paid: number;
  balance: number;
  late_fee: number;
  /** RentChargeStatus value. */
  status: string | null;
  is_overdue?: boolean;
}

/** serialize_rent_payment. */
export interface RentPaymentRow {
  id: number;
  charge_id: number;
  lease_id: number;
  property_id: number;
  amount_paid: number;
  /** Instant, UTC with Z. */
  paid_at: string | null;
  /** PaymentMethod value. */
  payment_method: string | null;
  /** RentPaymentStatus value. */
  status: string | null;
  reference: string | null;
  notes: string | null;
  created_at: string | null;
}

export type RentTotals = Known<Schemas['RentTotals']>;

export interface VisitCounts {
  total?: number;
  upcoming?: number;
  completed?: number;
  cancelled?: number;
  requested?: number;
  confirmed?: number;
  reschedule_suggested?: number;
}

export interface LeaseStats {
  active_leases: number;
  total_monthly_rent: number;
}

/** Portfolio stats of the property list tools and the in-app agent dashboard. */
export interface PortfolioStats {
  total_properties: number;
  occupied: number;
  vacant: number;
  occupancy_rate?: number;
  total_monthly_income: number;
  monthly_rent_expected?: number;
  open_maintenance_requests?: number;
}

/** `metrics` of the admin MCP agent_dashboard_overview. */
export interface AgentMetrics {
  total_properties: number;
  active_leases: number;
  occupancy_rate: number;
  open_maintenance_requests: number;
  upcoming_bookings: number;
  monthly_rent_expected: number;
}

export type DashboardOverview = Schemas['DashboardOverview'];

// ---------------------------------------------------------------------------
// Widget outputs (generated payload models, rows narrowed)
// ---------------------------------------------------------------------------

/**
 * discovery_search and the agent copy send `items`. discovery_feed, discovery_recommendations
 * and discovery_shortlist send `properties` (their key is not the one the payload model declares).
 */
export type PropertySearchOutput = PayloadWithRows<Schemas['PropertySearchPayload'], 'items', PropertyRow> & {
  properties?: PropertyRow[] | null;
  filters_applied?: Record<string, unknown>;
};

export type PropertySwipeOutput = PayloadWithRows<Schemas['PropertySwipePayload'], 'items', PropertyRow> & {
  properties?: PropertyRow[] | null;
  count?: number;
  is_personalized?: boolean;
};

export type PropertyDetailsOutput = Omit<Known<Schemas['PropertyDetailsPayload']>, 'property' | 'active_lease'> & {
  property?: PropertyDetailRow | null;
  active_lease?: LeaseRow | null;
  property_id?: number;
} & ToolResultKeys;

export type VisitSchedulerOutput = Omit<Known<Schemas['VisitSchedulerPayload']>, 'visit' | 'booking' | 'property'> & {
  visit?: VisitRow | null;
  booking?: BookingRow | null;
  property?: PropertyRow | PropertyRef | null;
} & ToolResultKeys;

export type VisitListOutput = PayloadWithRows<Schemas['VisitListPayload'], 'items', VisitListRow> & {
  counts?: VisitCounts | null;
  /** visits_get sends one visit. */
  visit?: VisitRow | null;
};

export type LeaseDetailsOutput = Omit<Known<Schemas['LeaseDetailsPayload']>, 'lease'> & {
  lease?: LeaseRow | null;
} & ToolResultKeys;

export type MaintenanceOutput = PayloadWithRows<Schemas['MaintenancePayload'], 'items', MaintenanceRow> & {
  /** tenant_maintenance_create sends the new request. */
  request?: MaintenanceRow | null;
};

export type OwnerDashboardOutput = PayloadWithRows<Schemas['OwnerDashboardPayload'], 'items', PropertyRow> & {
  stats?: PortfolioStats | null;
  /** owner_dashboard_overview nests its numbers under `dashboard`. */
  dashboard?: DashboardOverview | null;
  /** The admin MCP agent_dashboard_overview nests its numbers under `metrics`. */
  metrics?: AgentMetrics | null;
};

export type LeaseManagementOutput = Omit<Known<Schemas['LeaseManagementPayload']>, 'leases' | 'stats' | 'lease'> & {
  leases?: LeaseRow[] | null;
  stats?: LeaseStats | null;
  /** owner_leases_get sends one lease. */
  lease?: LeaseRow | null;
} & ToolResultKeys;

export type RentCollectionOutput = Omit<Known<Schemas['RentCollectionPayload']>, 'items' | 'charges' | 'totals' | 'payment'> & {
  /** owner_rent_status sends `charges`. agent_rent_list_due sends charge rows under `items`. owner_rent_history sends payment rows under `items`. */
  charges?: RentChargeRow[] | null;
  items?: (RentChargeRow | RentPaymentRow)[] | null;
  totals?: RentTotals | null;
  /** owner_rent_record_payment sends the saved payment. */
  payment?: RentPaymentRow | null;
} & ToolResultKeys;

/** tenant_rent_dues sends `charges`, `total_due` and `overdue_count`. tenant_rent_history sends `items` and `total_collected`. */
export type TenantRentOutput = Omit<Known<Schemas['TenantRentPayload']>, 'items'> & {
  charges?: RentChargeRow[] | null;
  total_due?: number;
  overdue_count?: number;
  items?: RentPaymentRow[] | null;
} & ToolResultKeys;
