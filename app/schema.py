"""Strawberry GraphQL Schema"""
import strawberry
from typing import Optional, List
from datetime import datetime


@strawberry.type
class UserType:
    """User object for GraphQL"""
    id: int
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime


@strawberry.type
class PortfolioType:
    """Portfolio object for GraphQL"""
    id: int
    title: str
    slug: str
    status: str
    custom_domain: Optional[str] = None
    design_system_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class PortfolioDataType:
    """Portfolio data section object"""
    id: int
    section_key: str
    content: str  # JSON as string
    order_index: int


@strawberry.type
class Query:
    """GraphQL Query root type"""
    
    @strawberry.field
    def hello(self, name: str = "World") -> str:
        """Hello world query for testing"""
        return f"Hello, {name}! 🚀"
    
    @strawberry.field
    def api_info(self) -> str:
        """Get API information"""
        return "PortfolioOS GraphQL API v0.1.0"


@strawberry.type
class Mutation:
    """GraphQL Mutation root type"""
    
    @strawberry.mutation
    def create_portfolio(self, title: str, slug: str) -> PortfolioType:
        """Create a new portfolio (placeholder)"""
        # TODO: Implement portfolio creation
        return PortfolioType(
            id=1,
            title=title,
            slug=slug,
            status="draft",
            design_system_id=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
    
    @strawberry.mutation
    def signup(self, email: str, password: str) -> str:
        """User signup (placeholder - Auth0 integration coming)"""
        # TODO: Implement Auth0 signup
        return f"Signup initiated for {email}"
    
    @strawberry.mutation
    def login(self, email: str, password: str) -> str:
        """User login (placeholder - Auth0 integration coming)"""
        # TODO: Implement Auth0 login
        return f"Login initiated for {email}"
