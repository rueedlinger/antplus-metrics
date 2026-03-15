import asyncio
import json
import os
from pathlib import Path
import logging
from typing import List
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.ant import Metrics
from app.model import (
    IntervalModel,
    IntervalProgressModel,
    MetricsModel,
    MetricsSettingsModel,
    DeviceModel,
)
from app.workout import Timer
from app.core import setup_logging

# --------------------
# Constants
# --------------------
current_file = Path(__file__).resolve()
root_store = current_file.parent.parent
METRICS_FILE = os.path.join(root_store, "metrics.json")
WORKOUT_FILE = os.path.join(root_store, "workout.json")

METRICS_DELAY_SECONDS = 0.5
DEVICES_DELAY_SECONDS = 1
WORKOUT_DELAY_SECONDS = 0.1

setup_logging()
logger = logging.getLogger("app.api")
shutdown_event = asyncio.Event()  # shared shutdown flag


# --------------------
# JSON Persistence Helpers
# --------------------
def load_metrics_settings() -> MetricsSettingsModel:
    """Load metrics settings from /tmp or return defaults."""
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r") as f:
                data = json.load(f)
            return MetricsSettingsModel(**data)
        except Exception as e:
            logger.warning(f"Failed to load metrics from {METRICS_FILE}: {e}")
    # default
    return MetricsSettingsModel(
        age=20, speed_wheel_circumference_m=0.141, distance_wheel_circumference_m=0.141
    )


def save_metrics_settings(metrics: Metrics):
    """Save current metrics settings to /tmp."""
    try:
        data = metrics.get_metrics_settings().model_dump()
        with open(METRICS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Metrics settings saved to {METRICS_FILE}")
    except Exception as e:
        logger.warning(f"Failed to save metrics settings: {e}")


def load_workout() -> list[IntervalModel]:
    """Load workout intervals from /tmp or return empty list."""
    if os.path.exists(WORKOUT_FILE):
        try:
            with open(WORKOUT_FILE, "r") as f:
                data = json.load(f)
            return [IntervalModel(**i) for i in data]
        except Exception as e:
            logger.warning(f"Failed to load workout from {WORKOUT_FILE}: {e}")
    return []


def save_workout(workout: list[IntervalModel]):
    """Save workout intervals to /tmp."""
    try:
        data = [i.model_dump() for i in workout]
        with open(WORKOUT_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Workout saved to {WORKOUT_FILE}")
    except Exception as e:
        logger.warning(f"Failed to save workout: {e}")


# --------------------
# Lifespan: load and save state
# --------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Starting ANT+ Metrics Service...")

    # Load metrics settings and workout from /tmp
    app.state.metrics = Metrics(metrics_settings=load_metrics_settings())
    app.state.workout = load_workout()
    app.state.timer = Timer(app.state.workout)

    yield

    logging.info("Shutting down ANT+ Metrics Service...")
    shutdown_event.set()
    if app.state.metrics:
        await asyncio.to_thread(app.state.metrics.stop)

    # Save current settings/workout on shutdown
    await asyncio.to_thread(save_metrics_settings, app.state.metrics)
    await asyncio.to_thread(save_workout, app.state.workout)


# --------------------
# FastAPI App & Router
# --------------------
app = FastAPI(
    title="ANT+ Metrics Service",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)
api_router = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------
# Status Endpoint
# --------------------
@api_router.get("/status")
def get_status():
    return {"up": "true"}


# --------------------
# Metrics Endpoints
# --------------------
@api_router.post("/metrics/start")
def start_metrics():
    try:
        app.state.metrics.start()
        return {"message": "Metrics collection started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed start metrics: {str(e)}")


@api_router.post("/metrics/stop")
def stop_metrics():
    try:
        app.state.metrics.stop()
        return {"message": "Metrics collection stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop metrics: {str(e)}")


@api_router.post("/metrics/settings")
def update_metrics_settings(payload: MetricsSettingsModel):
    metrics: Metrics = app.state.metrics
    if metrics.is_running():
        raise HTTPException(
            status_code=400, detail="Cannot update metrics while running"
        )
    try:
        metrics.set_metrics_settings(payload)
        save_metrics_settings(metrics)  # persist immediately
        return {"message": f"Metrics settings updated to {payload}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update: {str(e)}")


@api_router.get("/metrics/settings", response_model=MetricsSettingsModel)
def get_metrics_settings():
    try:
        return app.state.metrics.get_metrics_settings()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")


@api_router.get("/metrics", response_model=MetricsModel)
def get_metrics():
    try:
        return app.state.metrics.get_metrics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


@api_router.get("/metrics/devices", response_model=list[DeviceModel])
def get_metrics_devices():
    try:
        devices = app.state.metrics.get_devices()
        return [DeviceModel(**d) for d in devices]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get devices: {str(e)}")


# --------------------
# Workout Endpoints
# --------------------
@api_router.get("/workout", response_model=list[IntervalModel])
def get_workout():
    return app.state.workout


@api_router.post("/workout", response_model=list[IntervalModel])
def set_workout(intervals: list[IntervalModel]):
    timer: Timer = app.state.timer
    if timer.is_running():
        raise HTTPException(
            status_code=400, detail="Cannot update workout while the timer is running"
        )
    app.state.workout = intervals
    save_workout(app.state.workout)  # persist immediately
    return app.state.workout


@api_router.post("/workout/start")
def start_workout():
    try:
        timer: Timer = app.state.timer
        timer.set_intervak(app.state.workout)
        timer.start()
        return {"message": "Workout started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start: {str(e)}")


@api_router.post("/workout/stop")
def stop_workout():
    try:
        app.state.timer.stop()
        return {"message": "Workout stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop: {str(e)}")


# --------------------
# SSE Streaming
# --------------------
async def metrics_event_generator():
    while not shutdown_event.is_set():
        try:
            metrics: MetricsModel = await asyncio.to_thread(
                app.state.metrics.get_metrics
            )
            yield f"data: {metrics.model_dump_json()}\n\n"
            await asyncio.sleep(METRICS_DELAY_SECONDS)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in metrics_event_generator", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(METRICS_DELAY_SECONDS)


@api_router.get("/metrics/stream")
async def stream_metrics():
    return StreamingResponse(metrics_event_generator(), media_type="text/event-stream")


async def device_event_generator():
    while not shutdown_event.is_set():
        try:
            devices: List[DeviceModel] = await asyncio.to_thread(
                app.state.metrics.get_devices
            )
            data = json.dumps([device.model_dump() for device in devices])
            yield f"data: {data}\n\n"
            await asyncio.sleep(DEVICES_DELAY_SECONDS)
        except asyncio.CancelledError:
            break
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(DEVICES_DELAY_SECONDS)


@api_router.get("/metrics/devices/stream")
async def stream_devices():
    return StreamingResponse(device_event_generator(), media_type="text/event-stream")


async def workout_event_generator():
    timer: Timer = app.state.timer
    while True:
        try:
            progress: IntervalProgressModel = await asyncio.to_thread(
                timer.current_interval
            )
            if progress:
                yield f"data: {progress.model_dump_json()}\n\n"
            else:
                yield f"data: {json.dumps({})}\n\n"
            await asyncio.sleep(WORKOUT_DELAY_SECONDS)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in workout_event_generator", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(WORKOUT_DELAY_SECONDS)


@api_router.get("/workout/stream")
async def stream_workout():
    return StreamingResponse(workout_event_generator(), media_type="text/event-stream")


# --------------------
# Include router
# --------------------
app.include_router(api_router)
