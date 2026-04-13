#!/usr/bin/env python3
"""
Redis/RQ worker process.
Run this on your GPU server alongside Ollama.

Usage:
  REDIS_URL=redis://localhost:6379 python3 worker.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

import redis
from rq import Worker, Queue

conn = redis.from_url(redis_url)
queues = [Queue("ada", connection=conn)]

print(f"Worker starting. Listening on queue 'ada' at {redis_url}")
w = Worker(queues, connection=conn)
w.work()
