"""FastAPI application entry point"""
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import strawberry
from strawberry.fastapi import GraphQLRouter

from app.config import get_settings
from sqlalchemy.orm import Session

from app.database.connection import engine, Base, get_db
from app.database import models  # noqa: F401 - registers ORM metadata
from app.schema import Query, Mutation
from app.resume_uploads import router as resume_upload_router
from app.resume_extraction import router as resume_extraction_router
from app.portfolio_generation import router as portfolio_generation_router

settings = get_settings()


# Create tables on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    print("Database tables ready")
    yield
    # Shutdown


# Initialize FastAPI app
app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=settings.api_version,
    debug=settings.debug,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GraphQL Schema
schema = strawberry.Schema(query=Query, mutation=Mutation)


def get_graphql_context(db: Session = Depends(get_db)):
    return {"db": db}


# GraphQL Router
graphql_app = GraphQLRouter(schema, context_getter=get_graphql_context)
app.include_router(graphql_app, prefix="/graphql")
app.include_router(resume_upload_router)
app.include_router(resume_extraction_router)
app.include_router(portfolio_generation_router)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "environment": settings.environment,
            "version": settings.api_version,
        },
    )


# Root endpoint
@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "description": settings.api_description,
        "graphql_endpoint": "/graphql",
        "resume_upload_endpoint": "/upload",
        "resume_extraction_endpoint": "/resumes/{upload_id}/extract",
        "portfolio_generation_endpoint": "/resumes/{upload_id}/portfolio",
        "health_endpoint": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
