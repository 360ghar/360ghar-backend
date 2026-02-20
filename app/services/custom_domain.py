"""
Custom Domain service for managing branded tour URLs.

Handles domain creation, DNS verification, and SSL provisioning.
"""
import secrets
from typing import Optional, List
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.tours import CustomDomain
from app.schemas.custom_domain import (
    CustomDomainCreate,
    CustomDomainResponse,
    CustomDomainVerification,
)

logger = get_logger(__name__)


def generate_verification_token() -> str:
    """Generate a secure verification token for DNS TXT record."""
    return f"360ghar-verify-{secrets.token_hex(16)}"


async def create_custom_domain(
    db: AsyncSession,
    user_id: int,
    data: CustomDomainCreate,
) -> CustomDomainResponse:
    """
    Create a new custom domain for the user.

    Generates a verification token that must be added as a DNS TXT record.
    """
    # Check if domain already exists
    stmt = select(CustomDomain).where(CustomDomain.domain == data.domain)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        if existing.user_id == user_id:
            # Return existing domain for this user
            return CustomDomainResponse.model_validate(existing)
        else:
            raise ValueError("Domain is already registered by another user")

    # Create new domain
    verification_token = generate_verification_token()
    domain = CustomDomain(
        user_id=user_id,
        domain=data.domain,
        verification_status="pending",
        ssl_status="pending",
        verification_token=verification_token,
    )

    db.add(domain)
    await db.commit()
    await db.refresh(domain)

    logger.info(f"Created custom domain {data.domain} for user {user_id}")
    return CustomDomainResponse.model_validate(domain)


async def get_custom_domain(
    db: AsyncSession,
    domain_id: str,
    user_id: int,
) -> Optional[CustomDomainResponse]:
    """Get a custom domain by ID, ensuring user ownership."""
    stmt = select(CustomDomain).where(
        CustomDomain.id == domain_id,
        CustomDomain.user_id == user_id,
    )
    result = await db.execute(stmt)
    domain = result.scalar_one_or_none()

    if domain:
        return CustomDomainResponse.model_validate(domain)
    return None


async def get_user_domains(
    db: AsyncSession,
    user_id: int,
) -> List[CustomDomainResponse]:
    """Get all custom domains for a user."""
    stmt = select(CustomDomain).where(CustomDomain.user_id == user_id).order_by(CustomDomain.created_at.desc())
    result = await db.execute(stmt)
    domains = result.scalars().all()

    return [CustomDomainResponse.model_validate(d) for d in domains]


async def verify_domain(
    db: AsyncSession,
    domain_id: str,
    user_id: int,
) -> CustomDomainVerification:
    """
    Verify a custom domain by checking DNS TXT record.

    The user must add a TXT record to their DNS:
    _360ghar-verify.example.com -> verification_token
    """
    stmt = select(CustomDomain).where(
        CustomDomain.id == domain_id,
        CustomDomain.user_id == user_id,
    )
    result = await db.execute(stmt)
    domain = result.scalar_one_or_none()

    if not domain:
        raise ValueError("Domain not found")

    txt_record_name = f"_360ghar-verify.{domain.domain}"
    txt_record_value = domain.verification_token or ""

    # Attempt DNS verification
    is_verified = await _check_dns_txt_record(domain.domain, txt_record_value)

    if is_verified:
        domain.verification_status = "verified"
        # Start SSL provisioning
        domain.ssl_status = "provisioning"
        await db.commit()
        await db.refresh(domain)

        logger.info(f"Domain {domain.domain} verified successfully")

        return CustomDomainVerification(
            domain=domain.domain,
            is_verified=True,
            txt_record_name=txt_record_name,
            txt_record_value=txt_record_value,
        )

    return CustomDomainVerification(
        domain=domain.domain,
        is_verified=False,
        verification_instructions=f"Add a TXT record:\nName: {txt_record_name}\nValue: {txt_record_value}",
        txt_record_name=txt_record_name,
        txt_record_value=txt_record_value,
    )


async def _check_dns_txt_record(domain: str, expected_token: str) -> bool:
    """
    Check if the DNS TXT record contains the verification token.

    Uses dnspython for DNS resolution.
    """
    try:
        import dns.resolver

        txt_record_name = f"_360ghar-verify.{domain}"

        try:
            answers = dns.resolver.resolve(txt_record_name, "TXT")
            for rdata in answers:
                txt_value = str(rdata).strip('"')
                if expected_token in txt_value:
                    return True
        except dns.resolver.NXDOMAIN:
            logger.debug(f"No TXT record found for {txt_record_name}")
        except dns.resolver.NoAnswer:
            logger.debug(f"No TXT answer for {txt_record_name}")
        except dns.resolver.Timeout:
            logger.warning(f"DNS timeout for {txt_record_name}")

    except ImportError:
        logger.warning("dnspython not installed, DNS verification skipped")
    except Exception as e:
        logger.error(f"DNS verification error: {e}")

    return False


async def delete_custom_domain(
    db: AsyncSession,
    domain_id: str,
    user_id: int,
) -> bool:
    """Delete a custom domain."""
    stmt = select(CustomDomain).where(
        CustomDomain.id == domain_id,
        CustomDomain.user_id == user_id,
    )
    result = await db.execute(stmt)
    domain = result.scalar_one_or_none()

    if not domain:
        return False

    await db.delete(domain)
    await db.commit()

    logger.info(f"Deleted custom domain {domain.domain} for user {user_id}")
    return True


async def get_domain_by_hostname(
    db: AsyncSession,
    hostname: str,
) -> Optional[CustomDomainResponse]:
    """
    Look up a custom domain by hostname.

    Used for routing requests from custom domains to the correct user's tours.
    """
    stmt = select(CustomDomain).where(
        CustomDomain.domain == hostname,
        CustomDomain.verification_status == "verified",
    )
    result = await db.execute(stmt)
    domain = result.scalar_one_or_none()

    if domain:
        return CustomDomainResponse.model_validate(domain)
    return None
