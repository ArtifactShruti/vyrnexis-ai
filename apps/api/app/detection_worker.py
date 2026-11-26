"""Process the durable detection queue. Redis wakes the worker when events arrive."""
import logging
import time

from redis import RedisError
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from .database import SessionLocal
from .detection import HEARTBEAT_KEY, WAKE_CHANNEL, evaluate_detections, redis_client
from .models import DetectionInput
from .nexus_worker import process_investigation, task_timeout
from .workflow_engine import advance_one as advance_workflow, schedule_one as schedule_workflow
from .semantic import process_embeddings


logger = logging.getLogger(__name__)


def process_one() -> bool:
    event_id = None
    try:
        with SessionLocal.begin() as db:
            event = db.scalars(select(DetectionInput).where(DetectionInput.status == "queued")
                               .order_by(DetectionInput.queued_at, DetectionInput.event_id)
                               .limit(1).with_for_update(skip_locked=True)).first()
            if event is None:
                return False
            event_id = event.event_id
            evaluate_detections(db, event)
            event.attempts += 1
        return True
    except SQLAlchemyError:
        logger.error("Detection transaction failed. The worker will retry queued work.")
        if event_id:
            with SessionLocal.begin() as db:
                db.execute(update(DetectionInput).where(
                    DetectionInput.event_id == event_id, DetectionInput.status == "queued",
                ).values(attempts=DetectionInput.attempts + 1))
                db.execute(update(DetectionInput).where(
                    DetectionInput.event_id == event_id, DetectionInput.status == "queued",
                    DetectionInput.attempts >= 3,
                ).values(status="failed"))
        raise


def heartbeat(client, ttl):
    try:
        client.set(HEARTBEAT_KEY, "ready", ex=ttl)
    except RedisError:
        pass


def run() -> None:
    client = redis_client()
    if client is None:
        raise RuntimeError("REDIS_URL is required for the PostgreSQL detection worker.")
    seconds = task_timeout()
    heartbeat_ttl = max(30, seconds + 10)
    while True:
        try:
            did_work = False
            for _ in range(50):
                if not process_one():
                    break
                did_work = True
            for _ in range(2):
                heartbeat(client, heartbeat_ttl)
                if not process_investigation(seconds):
                    break
                did_work = True
            did_work = schedule_workflow() or did_work
            for _ in range(4):
                if not advance_workflow():
                    break
                did_work = True
            did_work = process_embeddings() or did_work
        except SQLAlchemyError:
            time.sleep(3)
            continue
        try:
            if not did_work:
                client.blpop(WAKE_CHANNEL, timeout=3)
        except RedisError:
            if not did_work:
                time.sleep(3)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
