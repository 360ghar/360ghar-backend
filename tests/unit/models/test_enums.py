"""
Tests for app.models.enums module.
"""

import pytest

from app.models.enums import (
    PropertyType,
    PropertyPurpose,
    PropertyStatus,
    BookingStatus,
    PaymentStatus,
    VisitStatus,
    AgentType,
    ExperienceLevel,
    BugType,
    BugSeverity,
    BugStatus,
    PageFormat,
    ImageCategory,
    UserRole,
    ManagedPropertyStatus,
    TenantStatus,
    LeaseStatus,
    RentChargeStatus,
    ExpenseCategory,
    MaintenanceUrgency,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    WorkOrderStatus,
    DocumentType,
    InspectionType,
    MessageThreadType,
)


class TestPropertyType:
    """Tests for PropertyType enum."""

    def test_all_property_types(self):
        """Test all property types are defined."""
        assert PropertyType.house.value == "house"
        assert PropertyType.apartment.value == "apartment"
        assert PropertyType.builder_floor.value == "builder_floor"
        assert PropertyType.room.value == "room"
        assert PropertyType.villa.value == "villa"
        assert PropertyType.plot.value == "plot"
        assert PropertyType.condo.value == "condo"
        assert PropertyType.penthouse.value == "penthouse"
        assert PropertyType.studio.value == "studio"
        assert PropertyType.loft.value == "loft"

    def test_property_type_count(self):
        """Test correct number of property types."""
        assert len(PropertyType) == 10

    def test_property_type_is_str_enum(self):
        """Test PropertyType inherits from str."""
        assert isinstance(PropertyType.house, str)
        assert PropertyType.house == "house"


class TestPropertyPurpose:
    """Tests for PropertyPurpose enum."""

    def test_all_property_purposes(self):
        """Test all property purposes are defined."""
        assert PropertyPurpose.buy.value == "buy"
        assert PropertyPurpose.rent.value == "rent"
        assert PropertyPurpose.short_stay.value == "short_stay"

    def test_property_purpose_count(self):
        """Test correct number of property purposes."""
        assert len(PropertyPurpose) == 3


class TestPropertyStatus:
    """Tests for PropertyStatus enum."""

    def test_all_property_statuses(self):
        """Test all property statuses are defined."""
        assert PropertyStatus.available.value == "available"
        assert PropertyStatus.sold.value == "sold"
        assert PropertyStatus.rented.value == "rented"
        assert PropertyStatus.under_offer.value == "under_offer"
        assert PropertyStatus.maintenance.value == "maintenance"

    def test_property_status_count(self):
        """Test correct number of property statuses."""
        assert len(PropertyStatus) == 5


class TestBookingStatus:
    """Tests for BookingStatus enum."""

    def test_all_booking_statuses(self):
        """Test all booking statuses are defined."""
        assert BookingStatus.pending.value == "pending"
        assert BookingStatus.confirmed.value == "confirmed"
        assert BookingStatus.checked_in.value == "checked_in"
        assert BookingStatus.checked_out.value == "checked_out"
        assert BookingStatus.cancelled.value == "cancelled"
        assert BookingStatus.completed.value == "completed"

    def test_booking_status_count(self):
        """Test correct number of booking statuses."""
        assert len(BookingStatus) == 6


class TestPaymentStatus:
    """Tests for PaymentStatus enum."""

    def test_all_payment_statuses(self):
        """Test all payment statuses are defined."""
        assert PaymentStatus.pending.value == "pending"
        assert PaymentStatus.partial.value == "partial"
        assert PaymentStatus.paid.value == "paid"
        assert PaymentStatus.refunded.value == "refunded"
        assert PaymentStatus.failed.value == "failed"

    def test_payment_status_count(self):
        """Test correct number of payment statuses."""
        assert len(PaymentStatus) == 5


class TestVisitStatus:
    """Tests for VisitStatus enum."""

    def test_all_visit_statuses(self):
        """Test all visit statuses are defined."""
        assert VisitStatus.scheduled.value == "scheduled"
        assert VisitStatus.confirmed.value == "confirmed"
        assert VisitStatus.completed.value == "completed"
        assert VisitStatus.cancelled.value == "cancelled"
        assert VisitStatus.rescheduled.value == "rescheduled"

    def test_visit_status_count(self):
        """Test correct number of visit statuses."""
        assert len(VisitStatus) == 5


class TestUserRole:
    """Tests for UserRole enum."""

    def test_all_user_roles(self):
        """Test all user roles are defined."""
        assert UserRole.user.value == "user"
        assert UserRole.agent.value == "agent"
        assert UserRole.admin.value == "admin"

    def test_user_role_count(self):
        """Test correct number of user roles."""
        assert len(UserRole) == 3


class TestAgentType:
    """Tests for AgentType enum."""

    def test_all_agent_types(self):
        """Test all agent types are defined."""
        assert AgentType.general.value == "general"
        assert AgentType.specialist.value == "specialist"
        assert AgentType.senior.value == "senior"


class TestExperienceLevel:
    """Tests for ExperienceLevel enum."""

    def test_all_experience_levels(self):
        """Test all experience levels are defined."""
        assert ExperienceLevel.beginner.value == "beginner"
        assert ExperienceLevel.intermediate.value == "intermediate"
        assert ExperienceLevel.expert.value == "expert"


class TestBugEnums:
    """Tests for bug-related enums."""

    def test_bug_types(self):
        """Test all bug types are defined."""
        assert BugType.ui_bug.value == "ui_bug"
        assert BugType.functionality_bug.value == "functionality_bug"
        assert BugType.performance_issue.value == "performance_issue"
        assert BugType.crash.value == "crash"
        assert BugType.feature_request.value == "feature_request"
        assert BugType.other.value == "other"

    def test_bug_severities(self):
        """Test all bug severities are defined."""
        assert BugSeverity.low.value == "low"
        assert BugSeverity.medium.value == "medium"
        assert BugSeverity.high.value == "high"
        assert BugSeverity.critical.value == "critical"

    def test_bug_statuses(self):
        """Test all bug statuses are defined."""
        assert BugStatus.open.value == "open"
        assert BugStatus.in_progress.value == "in_progress"
        assert BugStatus.resolved.value == "resolved"
        assert BugStatus.closed.value == "closed"


class TestImageCategory:
    """Tests for ImageCategory enum."""

    def test_all_image_categories(self):
        """Test all image categories are defined."""
        categories = [
            "room", "hall", "kitchen", "bathroom", "balcony",
            "terrace", "garden", "parking", "entrance",
            "exterior", "interior", "others"
        ]
        for cat in categories:
            assert hasattr(ImageCategory, cat)
            assert getattr(ImageCategory, cat).value == cat


class TestPageFormat:
    """Tests for PageFormat enum."""

    def test_all_page_formats(self):
        """Test all page formats are defined."""
        assert PageFormat.html.value == "html"
        assert PageFormat.markdown.value == "markdown"
        assert PageFormat.json.value == "json"


class TestPropertyManagementEnums:
    """Tests for property management enums."""

    def test_managed_property_status(self):
        """Test ManagedPropertyStatus values."""
        assert ManagedPropertyStatus.draft.value == "draft"
        assert ManagedPropertyStatus.active.value == "active"
        assert ManagedPropertyStatus.archived.value == "archived"

    def test_tenant_status(self):
        """Test TenantStatus values."""
        assert TenantStatus.applicant.value == "applicant"
        assert TenantStatus.approved.value == "approved"
        assert TenantStatus.active.value == "active"
        assert TenantStatus.notice_period.value == "notice_period"
        assert TenantStatus.vacated.value == "vacated"
        assert TenantStatus.rejected.value == "rejected"

    def test_lease_status(self):
        """Test LeaseStatus values."""
        assert LeaseStatus.draft.value == "draft"
        assert LeaseStatus.pending_signature.value == "pending_signature"
        assert LeaseStatus.active.value == "active"
        assert LeaseStatus.expiring_soon.value == "expiring_soon"
        assert LeaseStatus.expired.value == "expired"
        assert LeaseStatus.terminated.value == "terminated"
        assert LeaseStatus.renewed.value == "renewed"

    def test_rent_charge_status(self):
        """Test RentChargeStatus values."""
        assert RentChargeStatus.pending.value == "pending"
        assert RentChargeStatus.partial.value == "partial"
        assert RentChargeStatus.paid.value == "paid"
        assert RentChargeStatus.overdue.value == "overdue"
        assert RentChargeStatus.waived.value == "waived"


class TestExpenseCategory:
    """Tests for ExpenseCategory enum."""

    def test_all_expense_categories(self):
        """Test all expense categories are defined."""
        categories = [
            "maintenance", "repairs", "insurance", "property_tax",
            "hoa", "utilities", "marketing", "legal", "other"
        ]
        for cat in categories:
            assert hasattr(ExpenseCategory, cat)


class TestMaintenanceEnums:
    """Tests for maintenance-related enums."""

    def test_maintenance_urgency(self):
        """Test MaintenanceUrgency values."""
        assert MaintenanceUrgency.emergency.value == "emergency"
        assert MaintenanceUrgency.high.value == "high"
        assert MaintenanceUrgency.medium.value == "medium"
        assert MaintenanceUrgency.low.value == "low"

    def test_maintenance_category(self):
        """Test MaintenanceCategory values."""
        categories = [
            "plumbing", "electrical", "hvac", "appliance",
            "structural", "pest_control", "cleaning", "other"
        ]
        for cat in categories:
            assert hasattr(MaintenanceCategory, cat)

    def test_maintenance_request_status(self):
        """Test MaintenanceRequestStatus values."""
        assert MaintenanceRequestStatus.open.value == "open"
        assert MaintenanceRequestStatus.in_review.value == "in_review"
        assert MaintenanceRequestStatus.work_order_created.value == "work_order_created"
        assert MaintenanceRequestStatus.resolved.value == "resolved"
        assert MaintenanceRequestStatus.closed.value == "closed"

    def test_work_order_status(self):
        """Test WorkOrderStatus values."""
        statuses = ["created", "assigned", "in_progress", "completed", "closed", "cancelled"]
        for status in statuses:
            assert hasattr(WorkOrderStatus, status)


class TestDocumentType:
    """Tests for DocumentType enum."""

    def test_all_document_types(self):
        """Test all document types are defined."""
        doc_types = [
            "lease_agreement", "id_proof", "address_proof", "income_proof",
            "inspection_report", "receipt", "invoice", "property_deed",
            "insurance_policy", "other"
        ]
        for doc_type in doc_types:
            assert hasattr(DocumentType, doc_type)


class TestInspectionType:
    """Tests for InspectionType enum."""

    def test_all_inspection_types(self):
        """Test all inspection types are defined."""
        assert InspectionType.move_in.value == "move_in"
        assert InspectionType.move_out.value == "move_out"
        assert InspectionType.routine.value == "routine"


class TestMessageThreadType:
    """Tests for MessageThreadType enum."""

    def test_all_message_thread_types(self):
        """Test all message thread types are defined."""
        assert MessageThreadType.lease.value == "lease"
        assert MessageThreadType.maintenance.value == "maintenance"
        assert MessageThreadType.general.value == "general"


class TestEnumStringBehavior:
    """Tests for enum string comparison behavior."""

    def test_enum_equals_string(self):
        """Test enum values equal their string counterparts."""
        assert PropertyType.house == "house"
        assert BookingStatus.pending == "pending"
        assert UserRole.admin == "admin"

    def test_enum_in_list(self):
        """Test enum values can be checked in string lists."""
        allowed = ["buy", "rent"]
        assert PropertyPurpose.buy in allowed
        assert PropertyPurpose.rent in allowed

    def test_enum_as_dict_key(self):
        """Test enum values can be used as dict keys."""
        data = {PropertyType.house: "House", PropertyType.apartment: "Apartment"}
        assert data["house"] == "House"
        assert data[PropertyType.apartment] == "Apartment"
