"""PortfolioOS GraphQL schema."""

import json
from datetime import datetime
from typing import List, Optional

import strawberry
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from strawberry.types import Info

from app.database.models import DesignSystem, Portfolio, PortfolioData, User


@strawberry.type
class UserType:
    id: int
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    avatar_url: Optional[str]
    created_at: datetime


@strawberry.type
class PortfolioType:
    id: int
    user_id: int
    title: str
    slug: str
    status: str
    custom_domain: Optional[str]
    design_system_id: Optional[int]
    template_id: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]


@strawberry.type
class PortfolioDataType:
    id: int
    section_key: str
    content: str
    order_index: int


@strawberry.type
class DesignSystemType:
    id: int
    name: str
    slug: str
    description: Optional[str]
    tokens: str
    is_public: bool


@strawberry.type
class ApiResponse:
    success: bool
    message: str
    data: Optional[str] = None


def _db(info: Info) -> Session:
    return info.context["db"]


def _user_type(user: User) -> UserType:
    return UserType(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar_url,
        created_at=user.created_at,
    )


def _portfolio_type(portfolio: Portfolio) -> PortfolioType:
    return PortfolioType(
        id=portfolio.id,
        user_id=portfolio.user_id,
        title=portfolio.title,
        slug=portfolio.slug,
        status=portfolio.status,
        custom_domain=portfolio.custom_domain,
        design_system_id=portfolio.design_system_id,
        template_id=portfolio.template_id,
        created_at=portfolio.created_at,
        updated_at=portfolio.updated_at,
    )


def _portfolio_data_type(section: PortfolioData) -> PortfolioDataType:
    return PortfolioDataType(
        id=section.id,
        section_key=section.section_key,
        content=json.dumps(section.content),
        order_index=section.order_index,
    )


@strawberry.type
class Query:
    @strawberry.field
    def health(self) -> str:
        return "PortfolioOS API is healthy"

    @strawberry.field
    def get_user(self, info: Info, user_id: int) -> Optional[UserType]:
        user = _db(info).get(User, user_id)
        return _user_type(user) if user else None

    @strawberry.field
    def get_portfolio(self, info: Info, slug: str) -> Optional[PortfolioType]:
        portfolio = (
            _db(info).query(Portfolio).filter(Portfolio.slug == slug).one_or_none()
        )
        return _portfolio_type(portfolio) if portfolio else None

    @strawberry.field
    def list_user_portfolios(self, info: Info, user_id: int) -> List[PortfolioType]:
        portfolios = (
            _db(info)
            .query(Portfolio)
            .filter(Portfolio.user_id == user_id)
            .order_by(Portfolio.updated_at.desc(), Portfolio.id.desc())
            .all()
        )
        return [_portfolio_type(portfolio) for portfolio in portfolios]

    @strawberry.field
    def get_design_systems(self, info: Info) -> List[DesignSystemType]:
        systems = (
            _db(info)
            .query(DesignSystem)
            .filter(DesignSystem.is_public.is_(True))
            .order_by(DesignSystem.name)
            .all()
        )
        return [
            DesignSystemType(
                id=system.id,
                name=system.name,
                slug=system.slug,
                description=system.description,
                tokens=json.dumps(system.tokens),
                is_public=system.is_public,
            )
            for system in systems
        ]

    @strawberry.field
    def get_portfolio_data(
        self, info: Info, portfolio_id: int
    ) -> List[PortfolioDataType]:
        sections = (
            _db(info)
            .query(PortfolioData)
            .filter(PortfolioData.portfolio_id == portfolio_id)
            .order_by(PortfolioData.order_index, PortfolioData.id)
            .all()
        )
        return [_portfolio_data_type(section) for section in sections]


@strawberry.type
class Mutation:
    @strawberry.mutation
    def signup(
        self, email: str, password: str, first_name: Optional[str] = None
    ) -> ApiResponse:
        return ApiResponse(
            success=False,
            message="Authentication is not implemented yet; no credentials were stored.",
        )

    @strawberry.mutation
    def login(self, email: str, password: str) -> ApiResponse:
        return ApiResponse(
            success=False, message="Authentication is not implemented yet."
        )

    @strawberry.mutation
    def refresh_token(self, refresh_token: str) -> ApiResponse:
        return ApiResponse(
            success=False, message="Token refresh is not implemented yet."
        )

    @strawberry.mutation
    def create_portfolio(
        self,
        info: Info,
        user_id: int,
        title: str,
        slug: str,
        design_system_id: Optional[int] = None,
        template_id: Optional[int] = None,
    ) -> ApiResponse:
        db = _db(info)
        if db.get(User, user_id) is None:
            return ApiResponse(success=False, message="User not found.")

        portfolio = Portfolio(
            user_id=user_id,
            title=title.strip(),
            slug=slug.strip().lower(),
            design_system_id=design_system_id,
            template_id=template_id,
        )
        db.add(portfolio)
        try:
            db.commit()
            db.refresh(portfolio)
        except IntegrityError:
            db.rollback()
            return ApiResponse(
                success=False, message="Portfolio slug is already in use."
            )

        return ApiResponse(
            success=True,
            message="Portfolio created.",
            data=json.dumps({"id": portfolio.id, "slug": portfolio.slug}),
        )

    @strawberry.mutation
    def update_portfolio(
        self,
        info: Info,
        portfolio_id: int,
        title: Optional[str] = None,
        custom_domain: Optional[str] = None,
    ) -> ApiResponse:
        db = _db(info)
        portfolio = db.get(Portfolio, portfolio_id)
        if portfolio is None:
            return ApiResponse(success=False, message="Portfolio not found.")
        if title is not None:
            portfolio.title = title.strip()
        if custom_domain is not None:
            portfolio.custom_domain = custom_domain.strip() or None
        db.commit()
        return ApiResponse(success=True, message="Portfolio updated.")

    @strawberry.mutation
    def delete_portfolio(self, info: Info, portfolio_id: int) -> ApiResponse:
        db = _db(info)
        portfolio = db.get(Portfolio, portfolio_id)
        if portfolio is None:
            return ApiResponse(success=False, message="Portfolio not found.")
        db.delete(portfolio)
        db.commit()
        return ApiResponse(success=True, message="Portfolio deleted.")

    @strawberry.mutation
    def update_portfolio_data(
        self,
        info: Info,
        portfolio_id: int,
        section_key: str,
        content: str,
        order_index: int = 0,
    ) -> ApiResponse:
        db = _db(info)
        if db.get(Portfolio, portfolio_id) is None:
            return ApiResponse(success=False, message="Portfolio not found.")
        try:
            parsed_content = json.loads(content)
        except json.JSONDecodeError:
            return ApiResponse(
                success=False, message="Section content must be valid JSON."
            )

        section = (
            db.query(PortfolioData)
            .filter(
                PortfolioData.portfolio_id == portfolio_id,
                PortfolioData.section_key == section_key,
            )
            .one_or_none()
        )
        if section is None:
            section = PortfolioData(
                portfolio_id=portfolio_id,
                section_key=section_key,
                content=parsed_content,
                order_index=order_index,
            )
            db.add(section)
        else:
            section.content = parsed_content
            section.order_index = order_index
        db.commit()
        return ApiResponse(success=True, message="Portfolio section saved.")

    @strawberry.mutation
    def publish_portfolio(self, info: Info, portfolio_id: int) -> ApiResponse:
        db = _db(info)
        portfolio = db.get(Portfolio, portfolio_id)
        if portfolio is None:
            return ApiResponse(success=False, message="Portfolio not found.")
        portfolio.status = "published"
        db.commit()
        return ApiResponse(success=True, message="Portfolio published.")

    @strawberry.mutation
    def upload_resume(self, portfolio_id: int, file_url: str) -> ApiResponse:
        return ApiResponse(
            success=False,
            message="Use POST /upload for binary résumé uploads.",
        )

    @strawberry.mutation
    def extract_resume_data(self, resume_id: int) -> ApiResponse:
        return ApiResponse(
            success=False, message="Resume extraction is not implemented yet."
        )

    @strawberry.mutation
    def customize_design_system(
        self,
        portfolio_id: int,
        primary_color: str,
        secondary_color: Optional[str] = None,
    ) -> ApiResponse:
        return ApiResponse(
            success=False, message="Design customization is not implemented yet."
        )

    @strawberry.mutation
    def deploy_portfolio(self, portfolio_id: int) -> ApiResponse:
        return ApiResponse(
            success=False, message="Portfolio deployment is not implemented yet."
        )
