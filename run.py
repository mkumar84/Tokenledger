"""Local runner: python run.py  ->  http://localhost:8000/docs

Railway sets $PORT; default to 8000 locally.
"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "tokenledger.api:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=bool(os.environ.get("TOKENLEDGER_RELOAD")),
    )
