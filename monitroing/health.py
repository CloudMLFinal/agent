from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from monitroing.k8s import get_worker_status

from logger import logger

app = FastAPI()

# 全局状态变量
is_ready = False
is_alive = True

def set_ready(status: bool):
    global is_ready
    is_ready = status

def set_alive(status: bool):
    global is_alive
    is_alive = status

@app.get("/healthz")
async def liveness_probe():
    """Liveness probe endpoint"""
    if is_alive:
        return JSONResponse(
            content={"status": "healthy"},
            status_code=200
        )
    return JSONResponse(
        content={"status": "unhealthy"},
        status_code=503
    )

@app.get("/readyz")
async def readiness_probe():
    """Readiness probe endpoint"""
    if is_ready:
        return JSONResponse(
            content={"status": "ready"},
            status_code=200
        )
    return JSONResponse(
        content={"status": "not ready"},
        status_code=503
    )

@app.get("/status")
async def status():
    """Get detailed status information"""
    return JSONResponse({
        "status": "ok",
        "ready": is_ready,
        "alive": is_alive,
        "k8s": get_worker_status(),
    }) 