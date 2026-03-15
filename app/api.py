import asyncio
import json
import logging
from typing import List
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from app.ant import Metrics
from contextlib import asynccontextmanager

from app.core import setup_logging
from app.model import (
    IntervalModel,
    IntervalProgressModel,
    MetricsModel,
    MetricsSettingsModel,
    DeviceModel,
)
from app.workout import Timer


METRICS_DELAY_SECONDS = 0.5
DEVICES_DELAY_SECONDS = 1
WORKOUT_DELAY_SECONDS = 0.1


setup_logging()
logger = logging.getLogger("app.api")

shutdown_event = asyncio.Event()  # shared shutdown flag


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- startup ----
    logging.info("Starting ANT+ Metrics Service...")
    app.state.metrics = Metrics(
        metrics_settings=MetricsSettingsModel(
            age=45,
            speed_wheel_circumference_m=0.141,
            distance_wheel_circumference_m=0.141,
        )
    )

    app.state.workout = []
    app.state.timer = Timer(app.state.workout)

    yield

    # ---- shutdown ----
    logging.info("Shutting down ANT+ Metrics Service...")
    shutdown_event.set()  # signal shutdown to generators
    if app.state.metrics:
        await asyncio.to_thread(app.state.metrics.stop)


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
    allow_origins=["*"],  # or your frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api_router.get("/status")
def get_status():
    return {"up": "true"}


# -------------------------
# Metrics endpoints
# -------------------------
@api_router.post("/metrics/start")
def start_metrics():
    try:
        metrics: Metrics = app.state.metrics
        metrics.start()
        return {"message": "Metrics collection started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed start metrcics: {str(e)}")


@api_router.post("/metrics/stop")
def stop_metrics():
    try:
        metrics: Metrics = app.state.metrics
        metrics.stop()
        return {"message": "Metrics collection stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop metrics: {str(e)}")


@api_router.post("/metrics/settings")
def update_metrics_settings(payload: MetricsSettingsModel):

    metrics: Metrics = app.state.metrics

    if metrics.is_running():
        raise HTTPException(
            status_code=400, detail="Cannot update metrcis while running"
        )

    try:
        metrics.set_metrics_settings(payload)
        return {"message": f"Metrics settings updated to {payload}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update: {str(e)}")


@api_router.get("/metrics/settings", response_model=MetricsSettingsModel)
def get_metrics_settings():
    try:
        metrics: Metrics = app.state.metrics
        settings = metrics.get_metrics_settings()
        return settings
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")


@api_router.get("/metrics", response_model=MetricsModel)
def get_metrics():
    try:
        metrics: Metrics = app.state.metrics
        metrics = metrics.get_metrics()
        return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


@api_router.get("/metrics/devices", response_model=list[DeviceModel])
def get_metrics_devices():
    try:
        metrics: Metrics = app.state.metrics
        devices = metrics.get_devices()
        return [DeviceModel(**d) for d in devices]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get devices: {str(e)}")


async def metrics_event_generator():
    while not shutdown_event.is_set():
        try:
            metrics: MetricsModel = await asyncio.to_thread(
                app.state.metrics.get_metrics
            )

            # Convert to JSON string (Pydantic handles datetime automatically)
            data = metrics.model_dump_json()

            # SSE format: `data: <payload>\n\n`
            yield f"data: {data}\n\n"

            # Send updates every second (adjust as needed)
            await asyncio.sleep(METRICS_DELAY_SECONDS)
        except asyncio.CancelledError:
            # Client disconnected
            break
        except Exception as error:
            logger.error("Error in metrics_event_generator", exc_info=True)
            # Send error to client
            yield f"data: {json.dumps({'error': str(error), 'type': type(error).__name__, 'cause': repr(error.__cause__)})}\n\n"
            await asyncio.sleep(METRICS_DELAY_SECONDS)


@api_router.get("/metrics/stream")
async def stream_metrics():
    return StreamingResponse(metrics_event_generator(), media_type="text/event-stream")


async def device_event_generator():
    while not shutdown_event.is_set():
        try:
            # Get current devices from app state
            # devices = app.state.metrics.get_devices()  # returns list of dicts
            devices: List[DeviceModel] = await asyncio.to_thread(
                app.state.metrics.get_devices
            )
            data = json.dumps([device.model_dump() for device in devices])

            # SSE format: `data: <payload>\n\n`
            yield f"data: {data}\n\n"
            await asyncio.sleep(DEVICES_DELAY_SECONDS)  # adjust frequency as needed
        except asyncio.CancelledError:
            # client disconnected
            break
        except Exception as error:
            yield f"data: {json.dumps({'error': str(error), 'type': type(error).__name__, 'cause': repr(error.__cause__)})}\n\n"
            await asyncio.sleep(DEVICES_DELAY_SECONDS)


@api_router.get("/metrics/devices/stream")
async def stream_devices():
    return StreamingResponse(device_event_generator(), media_type="text/event-stream")


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
        timer: Timer = app.state.timer
        timer.stop()
        return {"message": "Workout stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop pdate: {str(e)}")


async def workout_event_generator():
    timer: Timer = app.state.timer

    while True:
        try:
            progress: IntervalProgressModel = await asyncio.to_thread(
                timer.current_interval
            )
            if progress:
                data = progress.model_dump_json()
                yield f"data: {data}\n\n"
            else:
                yield f"data: {json.dumps({})}\n\n"

            await asyncio.sleep(WORKOUT_DELAY_SECONDS)  # send updates twice per second
        except asyncio.CancelledError:
            break
        except Exception as error:
            logger.error("Error in workout_event_generator", exc_info=True)
            yield f"data: {json.dumps({'error': str(error), 'type': type(error).__name__, 'cause': repr(error.__cause__)})}\n\n"
            await asyncio.sleep(WORKOUT_DELAY_SECONDS)


@api_router.get("/workout/stream")
async def stream_workout():
    """
    Stream live workout interval progress using SSE.
    """
    return StreamingResponse(workout_event_generator(), media_type="text/event-stream")


app.include_router(api_router)
