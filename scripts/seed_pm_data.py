#!/usr/bin/env python3
"""
Seed script for PM (Property Management) mock data.
Creates comprehensive test data for the 360-estate-app.

Usage:
    python scripts/seed_pm_data.py

Requirements:
    - Database must be running and migrations applied
    - Environment variables set (.env file)
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.enums import (
    DocumentType,
    ExpenseCategory,
    InspectionType,
    LeaseStatus,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    ManagedPropertyStatus,
    PropertyPurpose,
    PropertyType,
    RentChargeStatus,
    UserRole,
    WorkOrderStatus,
)
from app.models.pm_documents import Document
from app.models.pm_finance import Expense, RentCharge, RentPayment
from app.models.pm_inspections import InspectionChecklist
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Property
from app.models.users import User

logger = get_logger(__name__)


# ============================================================================
# MOCK DATA DEFINITIONS
# ============================================================================

import uuid

def generate_supabase_id():
    """Generate a unique supabase-style user ID."""
    return str(uuid.uuid4())

MOCK_OWNER = {
    "supabase_user_id": "test-owner-" + generate_supabase_id()[:8],
    "phone": "+919999999999",
    "email": "testowner@360ghar.com",
    "full_name": "Test Owner",
    "role": UserRole.user.value,
}

MOCK_TENANTS = [
    {
        "supabase_user_id": "test-tenant1-" + generate_supabase_id()[:8],
        "phone": "+919876543210",
        "email": "rahul.sharma@gmail.com",
        "full_name": "Rahul Sharma",
        "role": UserRole.user.value,
    },
    {
        "supabase_user_id": "test-tenant2-" + generate_supabase_id()[:8],
        "phone": "+919876543211",
        "email": "priya.patel@gmail.com",
        "full_name": "Priya Patel",
        "role": UserRole.user.value,
    },
    {
        "supabase_user_id": "test-tenant3-" + generate_supabase_id()[:8],
        "phone": "+919876543212",
        "email": "amit.kumar@gmail.com",
        "full_name": "Amit Kumar",
        "role": UserRole.user.value,
    },
]

MOCK_PROPERTIES = [
    {
        "title": "Spacious 2BHK Apartment in Vijay Nagar",
        "description": "Modern 2BHK apartment with modular kitchen, 24x7 water supply, and covered parking. Located in prime area near schools and markets.",
        "property_type": PropertyType.apartment,
        "purpose": PropertyPurpose.rent,
        "base_price": 15000,
        "monthly_rent": 15000,
        "security_deposit": 30000,
        "city": "Indore",
        "state": "Madhya Pradesh",
        "locality": "Vijay Nagar",
        "pincode": "452010",
        "bedrooms": 2,
        "bathrooms": 2,
        "area_sqft": 1100,
        "floor_number": 3,
        "total_floors": 5,
        "is_managed": True,
        "management_status": ManagedPropertyStatus.active,
    },
    {
        "title": "Premium 3BHK House in Arera Colony",
        "description": "Independent 3BHK house with garden, parking for 2 cars, servant quarter, and RO water system. Ideal for families.",
        "property_type": PropertyType.house,
        "purpose": PropertyPurpose.rent,
        "base_price": 25000,
        "monthly_rent": 25000,
        "security_deposit": 50000,
        "city": "Bhopal",
        "state": "Madhya Pradesh",
        "locality": "Arera Colony",
        "pincode": "462016",
        "bedrooms": 3,
        "bathrooms": 3,
        "area_sqft": 1800,
        "floor_number": 0,
        "total_floors": 2,
        "is_managed": True,
        "management_status": ManagedPropertyStatus.active,
    },
    {
        "title": "Luxury 4BHK Villa in Worli",
        "description": "Sea-facing luxury villa with private pool, home theater, modular kitchen, and 24x7 security. Premium living at its best.",
        "property_type": PropertyType.house,
        "purpose": PropertyPurpose.rent,
        "base_price": 50000,
        "monthly_rent": 50000,
        "security_deposit": 150000,
        "city": "Mumbai",
        "state": "Maharashtra",
        "locality": "Worli",
        "pincode": "400018",
        "bedrooms": 4,
        "bathrooms": 4,
        "area_sqft": 3500,
        "floor_number": 0,
        "total_floors": 3,
        "is_managed": True,
        "management_status": ManagedPropertyStatus.active,
    },
]

MOCK_MAINTENANCE_REQUESTS = [
    {
        "category": MaintenanceCategory.plumbing,
        "urgency": MaintenanceUrgency.high,
        "title": "Kitchen sink leakage",
        "description": "Water is leaking from the kitchen sink pipe. Need immediate repair.",
        "request_status": MaintenanceRequestStatus.resolved,
        "work_order_status": WorkOrderStatus.completed,
        "actual_cost": 1500.0,
    },
    {
        "category": MaintenanceCategory.electrical,
        "urgency": MaintenanceUrgency.medium,
        "title": "Power socket not working",
        "description": "The power socket in the master bedroom is not working. Please check.",
        "request_status": MaintenanceRequestStatus.work_order_created,
        "work_order_status": WorkOrderStatus.in_progress,
        "estimated_cost": 500.0,
    },
    {
        "category": MaintenanceCategory.hvac,
        "urgency": MaintenanceUrgency.low,
        "title": "AC service required",
        "description": "Regular AC service is due. Please schedule a technician visit.",
        "request_status": MaintenanceRequestStatus.open,
        "work_order_status": None,
    },
    {
        "category": MaintenanceCategory.other,
        "urgency": MaintenanceUrgency.low,
        "title": "Wall painting needed",
        "description": "The walls in the living room need repainting. Some patches are visible.",
        "request_status": MaintenanceRequestStatus.in_review,
        "work_order_status": None,
    },
    {
        "category": MaintenanceCategory.pest_control,
        "urgency": MaintenanceUrgency.medium,
        "title": "Pest control treatment",
        "description": "Annual pest control treatment for the property.",
        "request_status": MaintenanceRequestStatus.closed,
        "work_order_status": WorkOrderStatus.completed,
        "actual_cost": 2500.0,
    },
]

MOCK_EXPENSES = [
    {
        "category": ExpenseCategory.maintenance,
        "amount": 1500.0,
        "description": "Plumbing repair - kitchen sink",
        "expense_date": date.today() - timedelta(days=15),
    },
    {
        "category": ExpenseCategory.property_tax,
        "amount": 12000.0,
        "description": "Annual property tax payment",
        "expense_date": date.today() - timedelta(days=60),
    },
    {
        "category": ExpenseCategory.insurance,
        "amount": 5000.0,
        "description": "Property insurance premium",
        "expense_date": date.today() - timedelta(days=30),
    },
    {
        "category": ExpenseCategory.utilities,
        "amount": 3500.0,
        "description": "Electricity and water charges",
        "expense_date": date.today() - timedelta(days=5),
    },
    {
        "category": ExpenseCategory.maintenance,
        "amount": 2500.0,
        "description": "Annual pest control service",
        "expense_date": date.today() - timedelta(days=45),
    },
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def get_or_create_user(db: AsyncSession, user_data: dict) -> User:
    """Get existing user by phone or email, or create new one."""
    from sqlalchemy import or_
    
    # Look for existing user by phone OR email
    stmt = select(User).where(
        or_(
            User.phone == user_data.get("phone"),
            User.email == user_data.get("email"),
        )
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user:
        logger.info(f"Found existing user: {user.full_name} (ID: {user.id})")
        return user
    
    # Create new user
    user = User(**user_data)
    db.add(user)
    await db.flush()
    logger.info(f"Created user: {user.full_name} (ID: {user.id})")
    return user


async def create_property(db: AsyncSession, owner_id: int, prop_data: dict) -> Property:
    """Create a managed property."""
    prop_data = {**prop_data, "owner_id": owner_id}
    prop = Property(**prop_data)
    db.add(prop)
    await db.flush()
    logger.info(f"Created property: {prop.title} (ID: {prop.id})")
    return prop


async def create_lease(
    db: AsyncSession,
    property: Property,
    owner_id: int,
    tenant: User,
    status: LeaseStatus,
    months_ago_start: int,
    duration_months: int,
) -> Lease:
    """Create a lease with proper dates."""
    start_date = date.today() - relativedelta(months=months_ago_start)
    end_date = start_date + relativedelta(months=duration_months)
    
    lease = Lease(
        property_id=property.id,
        owner_id=owner_id,
        tenant_user_id=tenant.id,
        tenant_name=tenant.full_name,
        tenant_phone=tenant.phone,
        tenant_email=tenant.email,
        status=status,
        start_date=start_date,
        end_date=end_date,
        monthly_rent=property.monthly_rent,
        security_deposit=property.security_deposit,
        grace_period_days=5,
        payment_due_day=5,
    )
    db.add(lease)
    await db.flush()
    logger.info(f"Created lease for {tenant.full_name} on {property.title} (ID: {lease.id})")
    return lease


async def create_rent_charges(
    db: AsyncSession,
    lease: Lease,
    property: Property,
    owner_id: int,
    tenant_id: int,
    months: int = 3,
) -> list[RentCharge]:
    """Create rent charges for past months."""
    charges = []
    today = date.today()
    
    for i in range(months):
        billing_month = (today - relativedelta(months=i)).replace(day=1)
        period_start = billing_month
        period_end = (billing_month + relativedelta(months=1)) - timedelta(days=1)
        due_date = billing_month.replace(day=lease.payment_due_day)
        
        # Determine status based on age
        if i == 0:
            status = RentChargeStatus.pending
        elif i == 1:
            status = RentChargeStatus.partial
        else:
            status = RentChargeStatus.paid
        
        charge = RentCharge(
            lease_id=lease.id,
            property_id=property.id,
            owner_id=owner_id,
            tenant_user_id=tenant_id,
            billing_month=billing_month,
            period_start=period_start,
            period_end=period_end,
            due_date=due_date,
            amount_due=lease.monthly_rent,
            status=status,
        )
        db.add(charge)
        charges.append(charge)
    
    await db.flush()
    logger.info(f"Created {len(charges)} rent charges for lease {lease.id}")
    return charges


async def create_rent_payment(
    db: AsyncSession,
    charge: RentCharge,
    amount: float,
    days_ago: int = 0,
) -> RentPayment:
    """Create a rent payment."""
    payment = RentPayment(
        charge_id=charge.id,
        lease_id=charge.lease_id,
        property_id=charge.property_id,
        owner_id=charge.owner_id,
        tenant_user_id=charge.tenant_user_id,
        amount_paid=amount,
        paid_at=datetime.now() - timedelta(days=days_ago),
        payment_method="UPI",
        reference=f"PAY-{charge.id}-{days_ago}",
    )
    db.add(payment)
    await db.flush()
    logger.info(f"Created payment of ₹{amount} for charge {charge.id}")
    return payment


async def create_maintenance_request(
    db: AsyncSession,
    property: Property,
    lease: Lease,
    owner_id: int,
    tenant_id: int,
    req_data: dict,
) -> MaintenanceRequest:
    """Create a maintenance request."""
    req = MaintenanceRequest(
        property_id=property.id,
        lease_id=lease.id,
        owner_id=owner_id,
        tenant_user_id=tenant_id,
        **req_data,
    )
    db.add(req)
    await db.flush()
    logger.info(f"Created maintenance request: {req.title} (ID: {req.id})")
    return req


async def create_expense(
    db: AsyncSession,
    property: Property,
    owner_id: int,
    exp_data: dict,
) -> Expense:
    """Create an expense record."""
    expense = Expense(
        property_id=property.id,
        owner_id=owner_id,
        **exp_data,
    )
    db.add(expense)
    await db.flush()
    logger.info(f"Created expense: {expense.description} (₹{expense.amount})")
    return expense


async def create_document(
    db: AsyncSession,
    owner_id: int,
    property_id: int,
    lease_id: int | None,
    doc_type: DocumentType,
    title: str,
) -> Document:
    """Create a document record."""
    doc = Document(
        owner_id=owner_id,
        property_id=property_id,
        lease_id=lease_id,
        document_type=doc_type,
        title=title,
        file_url=f"https://storage.360ghar.com/docs/{doc_type.value}/{title.replace(' ', '_').lower()}.pdf",
    )
    db.add(doc)
    await db.flush()
    logger.info(f"Created document: {title}")
    return doc


async def create_inspection(
    db: AsyncSession,
    property: Property,
    lease: Lease,
    owner_id: int,
    conducted_by_id: int,
    inspection_type: InspectionType,
    days_ago: int,
) -> InspectionChecklist:
    """Create an inspection checklist."""
    rooms_data = {
        "living_room": {"condition": "good", "notes": "Clean and well maintained"},
        "bedroom_1": {"condition": "good", "notes": "No issues"},
        "bedroom_2": {"condition": "fair", "notes": "Minor wall scratches"},
        "kitchen": {"condition": "good", "notes": "All appliances working"},
        "bathroom_1": {"condition": "good", "notes": "Clean"},
        "bathroom_2": {"condition": "good", "notes": "Clean"},
    }
    
    inspection = InspectionChecklist(
        property_id=property.id,
        lease_id=lease.id,
        owner_id=owner_id,
        inspection_type=inspection_type,
        conducted_by_user_id=conducted_by_id,
        conducted_at=datetime.now() - timedelta(days=days_ago),
        rooms_data=rooms_data,
        overall_notes=f"{inspection_type.value.replace('_', ' ').title()} inspection completed successfully.",
    )
    db.add(inspection)
    await db.flush()
    logger.info(f"Created {inspection_type.value} inspection for lease {lease.id}")
    return inspection


# ============================================================================
# MAIN SEED FUNCTION
# ============================================================================

async def seed_pm_data():
    """Main function to seed all PM data."""
    logger.info("=" * 60)
    logger.info("Starting PM Data Seed Script")
    logger.info("=" * 60)
    
    async with AsyncSessionLocal() as db:
        try:
            # 1. Create Owner
            logger.info("\n--- Creating Owner ---")
            owner = await get_or_create_user(db, MOCK_OWNER)
            
            # 2. Create Tenants
            logger.info("\n--- Creating Tenants ---")
            tenants = []
            for tenant_data in MOCK_TENANTS:
                tenant = await get_or_create_user(db, tenant_data)
                tenants.append(tenant)
            
            # Commit users so they're visible for FK constraints
            await db.commit()
            logger.info(f"Committed {1 + len(tenants)} users")
            
            # 3. Create Properties
            logger.info("\n--- Creating Properties ---")
            properties = []
            for prop_data in MOCK_PROPERTIES:
                prop = await create_property(db, owner.id, prop_data)
                properties.append(prop)
            
            # Commit properties so they're visible for FK constraints
            await db.commit()
            logger.info(f"Committed {len(properties)} properties")
            
            # 4. Create Leases
            logger.info("\n--- Creating Leases ---")
            leases = [
                await create_lease(db, properties[0], owner.id, tenants[0], LeaseStatus.active, 6, 12),
                await create_lease(db, properties[1], owner.id, tenants[1], LeaseStatus.active, 3, 12),
                await create_lease(db, properties[2], owner.id, tenants[2], LeaseStatus.expired, 13, 12),
            ]
            
            # 5. Create Rent Charges and Payments
            logger.info("\n--- Creating Rent Charges & Payments ---")
            for i, lease in enumerate(leases[:2]):  # Only for active leases
                charges = await create_rent_charges(
                    db, lease, properties[i], owner.id, tenants[i].id
                )
                # Create payments for some charges
                if charges:
                    # Full payment for oldest charge
                    if len(charges) > 2:
                        await create_rent_payment(db, charges[2], charges[2].amount_due, 45)
                    # Partial payment for middle charge  
                    if len(charges) > 1:
                        await create_rent_payment(db, charges[1], charges[1].amount_due * 0.5, 15)
            
            # 6. Create Maintenance Requests
            logger.info("\n--- Creating Maintenance Requests ---")
            for i, req_data in enumerate(MOCK_MAINTENANCE_REQUESTS):
                prop_idx = i % len(properties)
                lease_idx = min(i, len(leases) - 1)
                await create_maintenance_request(
                    db,
                    properties[prop_idx],
                    leases[lease_idx],
                    owner.id,
                    tenants[lease_idx].id,
                    req_data,
                )
            
            # 7. Create Expenses
            logger.info("\n--- Creating Expenses ---")
            for i, exp_data in enumerate(MOCK_EXPENSES):
                await create_expense(db, properties[i % len(properties)], owner.id, exp_data)
            
            # 8. Create Documents
            logger.info("\n--- Creating Documents ---")
            for i, lease in enumerate(leases):
                await create_document(
                    db, owner.id, properties[i].id, lease.id,
                    DocumentType.lease_agreement,
                    f"Lease Agreement - {properties[i].title[:30]}"
                )
            await create_document(
                db, owner.id, properties[0].id, None,
                DocumentType.receipt,
                "Rent Receipt - January 2026"
            )
            
            # 9. Create Inspections
            logger.info("\n--- Creating Inspections ---")
            await create_inspection(
                db, properties[0], leases[0], owner.id, owner.id,
                InspectionType.move_in, 180
            )
            await create_inspection(
                db, properties[2], leases[2], owner.id, owner.id,
                InspectionType.move_out, 30
            )
            
            # Commit all changes
            await db.commit()
            
            logger.info("\n" + "=" * 60)
            logger.info("PM Data Seed Completed Successfully!")
            logger.info("=" * 60)
            logger.info(f"\nSummary:")
            logger.info(f"  - Owner ID: {owner.id}")
            logger.info(f"  - Tenants: {len(tenants)}")
            logger.info(f"  - Properties: {len(properties)}")
            logger.info(f"  - Leases: {len(leases)}")
            logger.info(f"  - Maintenance Requests: {len(MOCK_MAINTENANCE_REQUESTS)}")
            logger.info(f"  - Expenses: {len(MOCK_EXPENSES)}")
            logger.info(f"\nYou can now test PM endpoints with owner phone: {owner.phone}")
            
        except Exception as e:
            await db.rollback()
            import traceback
            logger.error(f"Error seeding data: {e}")
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            raise


if __name__ == "__main__":
    asyncio.run(seed_pm_data())
