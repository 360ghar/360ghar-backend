"""
Property Management Data Populator

Creates comprehensive mock data for PM features:
- Leases
- Rent Charges & Payments
- Maintenance Requests
- Expenses
- Documents
- Inspections
"""
import asyncio
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.database import AsyncSessionLocal
from app.models.users import User
from app.models.properties import Property
from app.models.pm_leases import Lease
from app.models.pm_finance import RentCharge, RentPayment, Expense
from app.models.pm_maintenance import MaintenanceRequest
from app.models.pm_documents import Document
from app.models.pm_inspections import InspectionChecklist
from app.models.enums import (
    LeaseStatus,
    RentChargeStatus,
    MaintenanceCategory,
    MaintenanceUrgency,
    MaintenanceRequestStatus,
    WorkOrderStatus,
    ExpenseCategory,
    DocumentType,
    InspectionType,
)

logger = get_logger(__name__)


class PMDataPopulator:
    """Populator for Property Management mock data"""

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.data_dir = Path(__file__).parent.parent / "data"
        self._pm_data: Optional[Dict] = None

    @property
    def pm_data(self) -> Dict:
        """Load PM data from JSON file"""
        if self._pm_data is None:
            pm_data_path = self.data_dir / "pm_data.json"
            with open(pm_data_path, "r", encoding="utf-8") as f:
                self._pm_data = json.load(f)
        return self._pm_data

    async def get_db_session(self) -> AsyncSession:
        """Get a database session"""
        return AsyncSessionLocal()

    async def get_owner_with_properties(self, session: AsyncSession) -> Optional[tuple]:
        """Get a user who owns properties"""
        # Get users who own at least one property
        stmt = (
            select(User)
            .join(Property, Property.owner_id == User.id)
            .distinct()
            .limit(1)
        )
        result = await session.execute(stmt)
        owner = result.scalar_one_or_none()
        
        if not owner:
            self.logger.warning("No user with properties found")
            return None
        
        # Get their properties
        prop_stmt = select(Property).where(Property.owner_id == owner.id)
        prop_result = await session.execute(prop_stmt)
        properties = prop_result.scalars().all()
        
        return owner, list(properties)

    async def clear_pm_data(self, owner_id: Optional[int] = None) -> Dict[str, int]:
        """Clear all PM data, optionally for a specific owner"""
        self.logger.info(f"Clearing PM data{f' for owner {owner_id}' if owner_id else ''}...")
        
        counts = {
            "inspections": 0,
            "documents": 0,
            "expenses": 0,
            "maintenance_requests": 0,
            "rent_payments": 0,
            "rent_charges": 0,
            "leases": 0,
        }
        
        async with AsyncSessionLocal() as session:
            try:
                # Delete in dependency order (children first)
                from sqlalchemy import delete
                
                # Get lease IDs to filter child records
                if owner_id:
                    lease_stmt = select(Lease.id).where(Lease.owner_id == owner_id)
                    lease_result = await session.execute(lease_stmt)
                    lease_ids = [r[0] for r in lease_result.fetchall()]
                    
                    # Get property IDs
                    prop_stmt = select(Property.id).where(Property.owner_id == owner_id)
                    prop_result = await session.execute(prop_stmt)
                    property_ids = [r[0] for r in prop_result.fetchall()]
                else:
                    lease_ids = None
                    property_ids = None
                
                # Delete inspections
                if lease_ids:
                    del_stmt = delete(InspectionChecklist).where(InspectionChecklist.lease_id.in_(lease_ids))
                else:
                    del_stmt = delete(InspectionChecklist)
                result = await session.execute(del_stmt)
                counts["inspections"] = result.rowcount or 0
                
                # Delete documents (for owner or all)
                if owner_id:
                    del_stmt = delete(Document).where(Document.owner_id == owner_id)
                else:
                    del_stmt = delete(Document)
                result = await session.execute(del_stmt)
                counts["documents"] = result.rowcount or 0
                
                # Delete expenses
                if property_ids:
                    del_stmt = delete(Expense).where(Expense.property_id.in_(property_ids))
                else:
                    del_stmt = delete(Expense)
                result = await session.execute(del_stmt)
                counts["expenses"] = result.rowcount or 0
                
                # Delete maintenance requests
                if property_ids:
                    del_stmt = delete(MaintenanceRequest).where(MaintenanceRequest.property_id.in_(property_ids))
                else:
                    del_stmt = delete(MaintenanceRequest)
                result = await session.execute(del_stmt)
                counts["maintenance_requests"] = result.rowcount or 0
                
                # Delete rent payments
                if lease_ids:
                    del_stmt = delete(RentPayment).where(RentPayment.lease_id.in_(lease_ids))
                else:
                    del_stmt = delete(RentPayment)
                result = await session.execute(del_stmt)
                counts["rent_payments"] = result.rowcount or 0
                
                # Delete rent charges
                if lease_ids:
                    del_stmt = delete(RentCharge).where(RentCharge.lease_id.in_(lease_ids))
                else:
                    del_stmt = delete(RentCharge)
                result = await session.execute(del_stmt)
                counts["rent_charges"] = result.rowcount or 0
                
                # Delete leases
                if owner_id:
                    del_stmt = delete(Lease).where(Lease.owner_id == owner_id)
                else:
                    del_stmt = delete(Lease)
                result = await session.execute(del_stmt)
                counts["leases"] = result.rowcount or 0
                
                await session.commit()
                self.logger.info(f"Cleared PM data: {counts}")
                
            except Exception as e:
                await session.rollback()
                self.logger.error(f"Failed to clear PM data: {e}")
                raise
        
        return counts

    async def populate_all(self, max_leases_per_property: int = 2) -> Dict[str, int]:
        """Populate all PM data"""
        self.logger.info("Starting PM data population...")
        
        counts = {
            "leases": 0,
            "rent_charges": 0,
            "rent_payments": 0,
            "maintenance_requests": 0,
            "expenses": 0,
            "documents": 0,
            "inspections": 0,
        }
        
        async with AsyncSessionLocal() as session:
            try:
                # Get owner with properties
                result = await self.get_owner_with_properties(session)
                if not result:
                    self.logger.error("No owner with properties found. Run property population first.")
                    return counts
                
                owner, properties = result
                self.logger.info(f"Found owner: {owner.full_name} (ID: {owner.id}) with {len(properties)} properties")
                
                # Limit to first 5 properties for seeding
                properties = properties[:5]
                
                # Create leases for each property
                leases = []
                for prop in properties:
                    prop_leases = await self._create_leases_for_property(
                        session, owner, prop, max_leases_per_property
                    )
                    leases.extend(prop_leases)
                    counts["leases"] += len(prop_leases)
                
                await session.flush()
                self.logger.info(f"Created {counts['leases']} leases")
                
                # Create rent charges and payments for each lease
                for lease in leases:
                    charges = await self._create_rent_charges_for_lease(session, lease)
                    counts["rent_charges"] += len(charges)
                    
                    payments = await self._create_rent_payments(session, charges)
                    counts["rent_payments"] += len(payments)
                
                await session.flush()
                self.logger.info(f"Created {counts['rent_charges']} rent charges, {counts['rent_payments']} payments")
                
                # Create maintenance requests for each property
                for prop in properties:
                    requests = await self._create_maintenance_requests(session, owner, prop)
                    counts["maintenance_requests"] += len(requests)
                
                await session.flush()
                self.logger.info(f"Created {counts['maintenance_requests']} maintenance requests")
                
                # Create expenses for each property
                for prop in properties:
                    expenses = await self._create_expenses(session, owner, prop)
                    counts["expenses"] += len(expenses)
                
                await session.flush()
                self.logger.info(f"Created {counts['expenses']} expenses")
                
                # Create documents for each lease
                for lease in leases:
                    docs = await self._create_documents(session, owner, lease)
                    counts["documents"] += len(docs)
                
                await session.flush()
                self.logger.info(f"Created {counts['documents']} documents")
                
                # Create inspections for some leases
                for lease in leases[:len(leases)//2 + 1]:  # First half + 1
                    inspections = await self._create_inspections(session, owner, lease)
                    counts["inspections"] += len(inspections)
                
                await session.commit()
                self.logger.info(f"PM data population complete: {counts}")
                
            except Exception as e:
                await session.rollback()
                self.logger.error(f"PM data population failed: {e}")
                raise
        
        return counts

    async def _create_leases_for_property(
        self, 
        session: AsyncSession, 
        owner: User, 
        prop: Property,
        max_leases: int = 2
    ) -> List[Lease]:
        """Create leases for a property"""
        tenants = self.pm_data["tenants"]
        templates = self.pm_data["lease_templates"]
        leases = []
        
        # Status distribution: mostly active, some other statuses
        statuses = [LeaseStatus.active] * 3 + [
            LeaseStatus.draft, 
            LeaseStatus.pending_signature,
            LeaseStatus.expired
        ]
        
        for i in range(min(max_leases, len(tenants))):
            tenant = tenants[i % len(tenants)]
            monthly_rent = random.choice(templates["monthly_rents"])
            security_deposit = monthly_rent * templates["security_deposit_months"]
            
            # Calculate dates
            start_date = date.today() - timedelta(days=random.randint(30, 365))
            end_date = start_date + timedelta(days=365)
            
            status = random.choice(statuses)
            if status == LeaseStatus.expired:
                end_date = date.today() - timedelta(days=random.randint(1, 30))
            
            lease = Lease(
                property_id=prop.id,
                owner_id=owner.id,
                tenant_name=tenant["name"],
                tenant_phone=tenant["phone"],
                tenant_email=tenant["email"],
                status=status,
                start_date=start_date,
                end_date=end_date,
                monthly_rent=monthly_rent,
                security_deposit=security_deposit,
                late_fee_amount=random.choice(templates["late_fee_amounts"]),
                late_fee_percentage=random.choice(templates["late_fee_percentages"]),
                grace_period_days=random.choice(templates["grace_period_days"]),
                payment_due_day=random.choice(templates["payment_due_days"]),
                special_clauses=random.choice(templates["special_clauses"]),
            )
            session.add(lease)
            leases.append(lease)
        
        return leases

    async def _create_rent_charges_for_lease(
        self, 
        session: AsyncSession, 
        lease: Lease
    ) -> List[RentCharge]:
        """Create rent charges for a lease"""
        charges = []
        
        # Generate charges for past months
        today = date.today()
        current_month = date(today.year, today.month, 1)
        
        # Go back 6 months from start date or today, whichever is less
        months_back = min(6, (today - lease.start_date).days // 30)
        
        for i in range(months_back):
            billing_month = current_month - timedelta(days=30 * i)
            billing_month = date(billing_month.year, billing_month.month, 1)
            
            # Skip if before lease start
            if billing_month < date(lease.start_date.year, lease.start_date.month, 1):
                continue
            
            period_start = billing_month
            period_end = (billing_month + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            due_date = billing_month.replace(day=min(lease.payment_due_day, 28))
            
            # Status distribution
            if i == 0:  # Current month
                status = random.choice([RentChargeStatus.pending, RentChargeStatus.paid])
            elif i < 3:  # Recent months - mostly paid
                status = random.choices(
                    [RentChargeStatus.paid, RentChargeStatus.partial, RentChargeStatus.overdue],
                    weights=[7, 2, 1]
                )[0]
            else:  # Older months - paid
                status = RentChargeStatus.paid
            
            late_fee = 0.0
            if status == RentChargeStatus.overdue:
                late_fee = lease.late_fee_amount or 0.0
            
            charge = RentCharge(
                lease_id=lease.id,
                property_id=lease.property_id,
                owner_id=lease.owner_id,
                billing_month=billing_month,
                period_start=period_start,
                period_end=period_end,
                due_date=due_date,
                amount_due=lease.monthly_rent,
                late_fee_assessed=late_fee,
                status=status,
            )
            session.add(charge)
            charges.append(charge)
        
        return charges

    async def _create_rent_payments(
        self, 
        session: AsyncSession, 
        charges: List[RentCharge]
    ) -> List[RentPayment]:
        """Create payments for rent charges"""
        payments = []
        payment_methods = ["bank_transfer", "upi", "cheque", "cash", "online"]
        
        for charge in charges:
            if charge.status == RentChargeStatus.pending:
                continue
            
            if charge.status == RentChargeStatus.paid:
                # Full payment
                amount = charge.amount_due + charge.late_fee_assessed
            elif charge.status == RentChargeStatus.partial:
                # Partial payment (50-80%)
                amount = charge.amount_due * random.uniform(0.5, 0.8)
            else:
                continue
            
            payment = RentPayment(
                charge_id=charge.id,
                lease_id=charge.lease_id,
                property_id=charge.property_id,
                owner_id=charge.owner_id,
                paid_at=datetime.combine(
                    charge.due_date + timedelta(days=random.randint(0, 5)),
                    datetime.min.time()
                ),
                amount_paid=round(amount, 2),
                payment_method=random.choice(payment_methods),
                reference=f"PAY-{random.randint(100000, 999999)}",
                notes=random.choice([None, "On-time payment", "Regular payment"]),
            )
            session.add(payment)
            payments.append(payment)
        
        return payments

    async def _create_maintenance_requests(
        self, 
        session: AsyncSession, 
        owner: User, 
        prop: Property
    ) -> List[MaintenanceRequest]:
        """Create maintenance requests for a property"""
        templates = self.pm_data["maintenance_templates"]
        requests = []
        
        # Create 2-4 requests per property
        num_requests = random.randint(2, 4)
        selected_templates = random.sample(templates, min(num_requests, len(templates)))
        
        statuses = [
            MaintenanceRequestStatus.open,
            MaintenanceRequestStatus.in_review,
            MaintenanceRequestStatus.work_order_created,
            MaintenanceRequestStatus.resolved,
            MaintenanceRequestStatus.closed,
        ]
        
        for template in selected_templates:
            category = MaintenanceCategory(template["category"])
            urgency = MaintenanceUrgency(template["urgency"])
            status = random.choice(statuses)
            
            work_order_status = None
            if status in [MaintenanceRequestStatus.work_order_created, MaintenanceRequestStatus.resolved]:
                work_order_status = random.choice([
                    WorkOrderStatus.created,
                    WorkOrderStatus.assigned,
                    WorkOrderStatus.in_progress,
                    WorkOrderStatus.completed,
                ])
            
            req = MaintenanceRequest(
                property_id=prop.id,
                owner_id=owner.id,
                category=category,
                urgency=urgency,
                title=template["title"],
                description=template["description"],
                request_status=status,
                work_order_status=work_order_status,
                estimated_cost=round(random.uniform(500, 10000), 2) if work_order_status else None,
                actual_cost=round(random.uniform(500, 10000), 2) if status == MaintenanceRequestStatus.resolved else None,
            )
            session.add(req)
            requests.append(req)
        
        return requests

    async def _create_expenses(
        self, 
        session: AsyncSession, 
        owner: User, 
        prop: Property
    ) -> List[Expense]:
        """Create expenses for a property"""
        templates = self.pm_data["expense_templates"]
        expenses = []
        
        # Create 3-6 expenses per property
        num_expenses = random.randint(3, 6)
        selected_templates = random.sample(templates, min(num_expenses, len(templates)))
        
        for template in selected_templates:
            category = ExpenseCategory(template["category"])
            amount_min, amount_max = template["amount_range"]
            
            expense = Expense(
                property_id=prop.id,
                owner_id=owner.id,
                category=category,
                amount=round(random.uniform(amount_min, amount_max), 2),
                expense_date=date.today() - timedelta(days=random.randint(1, 180)),
                description=template["description"],
                is_recurring=category in [ExpenseCategory.maintenance, ExpenseCategory.hoa],
            )
            session.add(expense)
            expenses.append(expense)
        
        return expenses

    async def _create_documents(
        self, 
        session: AsyncSession, 
        owner: User, 
        lease: Lease
    ) -> List[Document]:
        """Create documents for a lease"""
        templates = self.pm_data["document_templates"]
        documents = []
        
        # Create 2-4 documents per lease
        num_docs = random.randint(2, 4)
        selected_templates = random.sample(templates, min(num_docs, len(templates)))
        
        for template in selected_templates:
            doc_type = DocumentType(template["document_type"])
            
            doc = Document(
                owner_id=owner.id,
                property_id=lease.property_id,
                lease_id=lease.id,
                document_type=doc_type,
                title=template["title"],
                file_url=template["file_url"],
                file_path=f"pm/{owner.id}/{lease.id}/{doc_type.value}.pdf",
                mime_type="application/pdf",
                file_size=random.randint(50000, 500000),
                shared_with_tenant=doc_type in [DocumentType.lease_agreement],
                created_by_user_id=owner.id,
            )
            session.add(doc)
            documents.append(doc)
        
        return documents

    async def _create_inspections(
        self, 
        session: AsyncSession, 
        owner: User, 
        lease: Lease
    ) -> List[InspectionChecklist]:
        """Create inspection checklists for a lease"""
        rooms_data = self.pm_data["inspection_rooms"]
        inspections = []
        
        # Create 1-2 inspections per lease
        inspection_types = [InspectionType.move_in]
        if lease.status == LeaseStatus.expired:
            inspection_types.append(InspectionType.move_out)
        
        for insp_type in inspection_types:
            # Format rooms_data for storage
            formatted_rooms = {
                "rooms": rooms_data,
                "summary": "Overall good condition",
                "needs_attention": []
            }
            
            inspection = InspectionChecklist(
                property_id=lease.property_id,
                lease_id=lease.id,
                owner_id=owner.id,
                inspection_type=insp_type,
                conducted_by_user_id=owner.id,
                conducted_at=datetime.combine(
                    lease.start_date if insp_type == InspectionType.move_in else lease.end_date,
                    datetime.min.time()
                ),
                rooms_data=formatted_rooms,
                overall_notes=f"{insp_type.value.replace('_', ' ').title()} inspection completed. Property in good condition.",
            )
            session.add(inspection)
            inspections.append(inspection)
        
        return inspections


async def main():
    """Test the populator"""
    populator = PMDataPopulator()
    
    # Clear existing data
    await populator.clear_pm_data()
    
    # Populate new data
    counts = await populator.populate_all()
    print(f"Created: {counts}")


if __name__ == "__main__":
    asyncio.run(main())
