#!/usr/bin/env python3
"""
AI Workflow Engine - API Server Runner

Simple script to start the FastAPI server for workflow execution and validation.

Usage:
    python run_api_server.py

API will be available at:
- http://localhost:8000/docs (Interactive documentation)
- http://localhost:8000/health (Health check)
- http://localhost:8000/api/v1/workflows/execute (Execute workflows)

Author: AI Workflow Engine Team
"""

import sys
import os
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded environment variables from {env_path}")
    else:
        print(f"⚠️  No .env file found at {env_path}")
except ImportError:
    print("⚠️  python-dotenv not installed, skipping .env file loading")

# Add src to Python path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

def main():
    """Start the API server."""
    try:
        import uvicorn
        from workflow_engine.api.main import app
        
        print("🚀 AI Workflow Engine - API Server")
        print("=" * 50)
        print("📖 Interactive Docs: http://localhost:8000/docs")
        print("📚 ReDoc: http://localhost:8000/redoc")
        print("❤️  Health Check: http://localhost:8000/health")
        print("🔧 Validation API: http://localhost:8000/api/v1/workflows/validate/health")
        print("⚡ Execution API: http://localhost:8000/api/v1/workflows/health")
        print("=" * 50)
        print("💡 Example curl command:")
        print("   curl -X GET http://localhost:8000/health")
        print("=" * 50)
        
        # Start the server
        uvicorn.run(
            app,
            host="0.0.0.0", 
            port=8000,
            log_level="info",
            reload=False  # Set to True for development
        )
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("💡 Make sure you're in the virtual environment:")
        print("   source venv/bin/activate")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()