"""Supervise one PostgreSQL investigation process at a time."""
import json
import os
import subprocess
import sys

from .database import SessionLocal
from .nexus import LEASE_SECONDS, claim, fail_claim, perform_claim


def task_timeout():
    seconds = int(os.getenv("VYRNEXIS_INVESTIGATION_TASK_TIMEOUT_SECONDS", "30"))
    if not 3 <= seconds <= LEASE_SECONDS - 5:
        raise ValueError("VYRNEXIS_INVESTIGATION_TASK_TIMEOUT_SECONDS must be between 3 and 40")
    return seconds


def supervise_claim(job, seconds, session_factory=SessionLocal):
    try:
        subprocess.run(
            [sys.executable, "-m", "app.nexus_worker"], input=json.dumps(job), text=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=seconds, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        fail_claim(job, "The investigation process exceeded its execution deadline",
                   timed_out=True, session_factory=session_factory)
    except (OSError, subprocess.CalledProcessError):
        fail_claim(job, "The investigation process could not complete", session_factory=session_factory)


def process_investigation(seconds):
    job = claim()
    if isinstance(job, bool):
        return job
    supervise_claim(job, seconds)
    return True


if __name__ == "__main__":
    from .main import evidence_integrity, read_evidence_bytes

    perform_claim(json.load(sys.stdin), read_evidence_bytes, evidence_integrity)
