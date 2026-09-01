"""FastAPI application entry point"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import strawberry
from strawberry.fastapi import GraphQLRouter

from app.config import get_settings
from app.database.connection import engine, Base
from app.schema import Query, Mutation

settings = get_settings()

# Create tables on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created")
    yield
    # Shutdown
    print("Shutting down...")


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
    allow_origins=["*"],  # Change to specific domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GraphQL Schema
schema = strawberry.Schema(query=Query, mutation=Mutation)

# GraphQL Router
graphql_app = GraphQLRouter(schema, path_prefix="/graphql")
app.include_router(graphql_app)


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
        "health_endpoint": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.get("api_host", "0.0.0.0"),
        port=settings.get("api_port", 8000),
        reload=settings.debug,
    )
