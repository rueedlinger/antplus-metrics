import asyncio
import pathlib
import time
import json
import logging
from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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


app = FastAPI(title="ANT+ Metrics Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or your frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Path to frontend build folder inside app/
build_path = pathlib.Path(__file__).parent / "dist"
assets_path = build_path / "assets"

logger.info("looking for ui in %s", build_path)
if build_path.exists() and build_path.is_dir():
    if assets_path.exists() and assets_path.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
    else:
        logger.warning(
            "Assets folder not found at %s, skipping assets mount.", assets_path
        )

    # Check index.html
    index_file = build_path / "index.html"
    if index_file.exists():

        @app.get("/")
        def root():
            return FileResponse(index_file)
    else:
        logger.warning("index.html not found at %s, skipping assets mount.", index_file)

else:
    logger.warning(
        "Frontend build folder not found at %s, skipping frontend mount.", build_path
    )


@app.get("/status")
def get_status():
    return {"up": "true"}


# -------------------------
# Metrics endpoints
# -------------------------
@app.post("/metrics/start")
def start_metrics():
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            app.state.metrics.start()
            return {"message": "Metrics collection started"}
        except Exception as e:
            logging.warning(f"Failed to start metrics (attempt {attempt}): {str(e)}")
            time.sleep(1)  # brief pause before retrying

    # If all retries failed, raise HTTPException
    raise HTTPException(
        status_code=500, detail=f"Failed to start metrics after {max_retries} attempts"
    )


@app.post("/metrics/stop")
def stop_metrics():
    try:
        app.state.metrics.stop()
        return {"message": "Metrics collection stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop metrics: {str(e)}")


@app.post("/metrics/settings")
def update_metrics_settings(payload: MetricsSettingsModel):
    try:
        app.state.metrics.set_metrics_settings(payload)
        return {"message": f"Metrics settings updated to {payload}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update: {str(e)}")


@app.get("/metrics/settings", response_model=MetricsSettingsModel)
def get_metrics_settings():
    try:
        settings = app.state.metrics.get_metrics_settings()
        return settings
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")


@app.get("/metrics", response_model=MetricsModel)
def get_metrics():
    try:
        metrics = app.state.metrics.get_metrics()
        return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


@app.get("/metrics/devices", response_model=list[DeviceModel])
def get_metrics_devices():
    try:
        devices = app.state.metrics.get_devices()
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


@app.get("/metrics/stream")
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


@app.get("/metrics/devices/stream")
async def stream_devices():
    return StreamingResponse(device_event_generator(), media_type="text/event-stream")


@app.get("/workout", response_model=list[IntervalModel])
def get_workout():
    return app.state.workout


@app.post("/workout", response_model=list[IntervalModel])
def set_workout(intervals: list[IntervalModel]):
    timer: Timer = app.state.timer

    if timer.is_running():
        raise HTTPException(
            status_code=400, detail="Cannot update workout while the timer is running"
        )

    app.state.workout = intervals
    return app.state.workout


@app.post("/workout/start")
def start_workout():
    try:
        timer: Timer = app.state.timer
        timer.set_intervak(app.state.workout)
        timer.start()
        return {"message": "Workout started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start: {str(e)}")


@app.post("/workout/stop")
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


@app.get("/workout/stream")
async def stream_workout():
    """
    Stream live workout interval progress using SSE.
    """
    return StreamingResponse(workout_event_generator(), media_type="text/event-stream")
