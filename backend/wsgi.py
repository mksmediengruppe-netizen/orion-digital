"""WSGI entry point for ORION Digital backend."""
# CRITICAL: gevent monkey-patching MUST happen before any other imports
from gevent import monkey
monkey.patch_all()

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
for _mem_logger in ["memory.engine", "memory.profile", "memory.semantic"]:
    logging.getLogger(_mem_logger).setLevel(logging.DEBUG)

from app import app
if __name__ == "__main__":
    app.run()

