"""SQLAlchemy ORM models"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Text,
    UniqueConstraint,
    CheckConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.connection import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    auth0_id = Column(String(255), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    avatar_url = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    portfolios = relationship(
        "Portfolio", back_populates="owner", cascade="all, delete-orphan"
    )
    resume_uploads = relationship(
        "ResumeUpload", back_populates="user", cascade="all, delete-orphan"
    )


class DesignSystem(Base):
    __tablename__ = "design_systems"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    tokens = Column(JSON, nullable=False)
    is_public = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WireframeTemplate(Base):
    __tablename__ = "wireframe_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    sections = Column(JSON, nullable=False)
    is_public = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    design_system_id = Column(Integer, ForeignKey("design_systems.id"))
    template_id = Column(Integer, ForeignKey("wireframe_templates.id"))
    resume_upload_id = Column(
        Integer, ForeignKey("resume_uploads.id"), unique=True, nullable=True
    )
    status = Column(String(50), default="draft")  # draft, published, archived
    custom_domain = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner = relationship("User", back_populates="portfolios")
    design_system = relationship("DesignSystem")
    template = relationship("WireframeTemplate")
    source_resume = relationship("ResumeUpload", back_populates="portfolio")
    portfolio_data = relationship(
        "PortfolioData", back_populates="portfolio", cascade="all, delete-orphan"
    )
    deployments = relationship(
        "Deployment", back_populates="portfolio", cascade="all, delete-orphan"
    )


class PortfolioData(Base):
    __tablename__ = "portfolio_data"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "section_key", name="uq_portfolio_data_section"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    section_key = Column(String(100), nullable=False)  # hero, about, experience, etc
    content = Column(JSON, nullable=False)  # Flexible content structure
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    portfolio = relationship("Portfolio", back_populates="portfolio_data")


class ResumeUpload(Base):
    __tablename__ = "resume_uploads"
    __table_args__ = (
        CheckConstraint(
            "extraction_status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_resume_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    file_url = Column(Text, nullable=False)
    original_filename = Column(String(255))
    extracted_data = Column(JSON)  # Extracted resume data
    extraction_status = Column(
        String(50), default="pending"
    )  # pending, processing, completed, failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user = relationship("User", back_populates="resume_uploads")
    portfolio = relationship("Portfolio", back_populates="source_resume", uselist=False)


class Deployment(Base):
    __tablename__ = "deployments"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    deployment_url = Column(Text, nullable=False)
    status = Column(String(50), default="in_progress")  # in_progress, success, failed
    logs = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    portfolio = relationship("Portfolio", back_populates="deployments")
