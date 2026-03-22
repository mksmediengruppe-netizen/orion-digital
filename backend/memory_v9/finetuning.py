"""
Experience Fine-Tuning — заглушка (требует GPU для реального обучения).
"""
import os, logging
from typing import Dict, Optional, List
from .config import MemoryConfig

logger = logging.getLogger("memory.finetuning")


class DatasetExporter:
    EXPORT_DIR = os.path.join(MemoryConfig.DATA_DIR, "training_data")

    @staticmethod
    def export_all() -> Dict:
        os.makedirs(DatasetExporter.EXPORT_DIR, exist_ok=True)
        return {
            "episodes": "",
            "skills": "",
            "errors": "",
            "dir": DatasetExporter.EXPORT_DIR,
            "note": "GPU required for fine-tuning"
        }


class FineTuner:
    @staticmethod
    def is_available() -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except:
            return False

    @staticmethod
    def train(dataset_path: str, output_dir: str = None) -> Dict:
        if not FineTuner.is_available():
            return {"success": False, "error": "GPU not available"}
        return {"success": False, "error": "Fine-tuning not configured"}


class InferenceRouter:
    @staticmethod
    def is_finetuned_available() -> bool:
        return False

    @staticmethod
    def should_use_finetuned(task: str, user_id: str) -> bool:
        return False

    @staticmethod
    def query_finetuned(prompt: str) -> Optional[str]:
        return None
