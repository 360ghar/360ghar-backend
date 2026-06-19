"""
Custom Domain API endpoints for managing branded tour URLs.

Provides endpoints for creating, verifying, and managing custom domains.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.custom_domain import (
    CustomDomainCreate,
    CustomDomainList,
    CustomDomainResponse,
    CustomDomainVerification,
)
from app.schemas.user import User as UserSchema
from app.services import custom_domain as custom_domain_service

router = APIRouter()
logger = get_logger(__name__)


@router.post("", response_model=CustomDomainResponse, status_code=status.HTTP_201_CREATED, summary="Create custom domain")
async def create_custom_domain(
    domain_data: CustomDomainCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Create a new custom domain.

    Returns the domain with a verification token that must be added as a DNS TXT record.
    """
    try:
        domain = await custom_domain_service.create_custom_domain(
            db=db,
            user_id=current_user.id,
            data=domain_data,
        )
        return domain
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None


@router.get("", response_model=CustomDomainList, summary="List custom domains")
async def list_custom_domains(
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    List all custom domains for the current user.
    """
    domains = await custom_domain_service.get_user_domains(
        db=db,
        user_id=current_user.id,
    )
    return CustomDomainList(items=domains, total=len(domains))


@router.get("/{domain_id}", response_model=CustomDomainResponse, summary="Get custom domain")
async def get_custom_domain(
    domain_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get a specific custom domain by ID.
    """
    domain = await custom_domain_service.get_custom_domain(
        db=db,
        domain_id=domain_id,
        user_id=current_user.id,
    )
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )
    return domain


@router.post("/{domain_id}/verify", response_model=CustomDomainVerification, summary="Verify custom domain")
async def verify_custom_domain(
    domain_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Trigger verification for a custom domain.

    Checks if the DNS TXT record has been added correctly.
    Returns verification status and instructions if not yet verified.
    """
    try:
        result = await custom_domain_service.verify_domain(
            db=db,
            domain_id=domain_id,
            user_id=current_user.id,
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from None


@router.delete("/{domain_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete custom domain")
async def delete_custom_domain(
    domain_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Delete a custom domain.
    """
    deleted = await custom_domain_service.delete_custom_domain(
        db=db,
        domain_id=domain_id,
        user_id=current_user.id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )
    return None
