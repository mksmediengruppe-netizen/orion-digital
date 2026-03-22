"""WSGI entry point for ORION Digital backend."""
import logging

# BUG-5 FIX: настраиваем логирование чтобы [MEMORY] логи попадали в journalctl
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
# Включаем DEBUG для memory модулей
for _mem_logger in ["memory.engine", "memory.profile", "memory.semantic"]:
    logging.getLogger(_mem_logger).setLevel(logging.DEBUG)

from app import app

if __name__ == "__main__":
    app.run()
