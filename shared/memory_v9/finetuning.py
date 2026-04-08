"""
Experience Fine-Tuning — дообучение модели на собственном опыте.

Три этапа:
1. DatasetExporter: episodes + tool_skills → JSONL датасет
2. FineTuner: LoRA обучение через unsloth/axolotl (если GPU)
3. InferenceRouter: когда использовать fine-tuned vs cloud API

Требования для обучения:
- GPU: минимум RTX 3060 12GB (для 7B модели с LoRA)
- RAM: 32GB+
- Диск: 20GB для модели + датасет
- pip install unsloth transformers datasets peft

Без GPU: только DatasetExporter (экспорт датасета для обучения в облаке).
"""

import json, os, re, logging, hashlib
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from .config import MemoryConfig

logger = logging.getLogger("memory.finetuning")

# ══════════════════════════════════════════════════════════════
# 1. DATASET EXPORTER
# ══════════════════════════════════════════════════════════════

class DatasetExporter:
    """Экспорт опыта агента в JSONL для fine-tuning."""

    EXPORT_DIR = os.path.join(MemoryConfig.DATA_DIR, "training_data")

    @staticmethod
    def export_episodes(min_success: bool = True, min_actions: int = 3) -> str:
        """
        Экспортировать эпизоды в JSONL формат.
        Формат: {"instruction": "задача", "input": "контекст", "output": "действия и результат"}
        """
        os.makedirs(DatasetExporter.EXPORT_DIR, exist_ok=True)
        output_path = os.path.join(DatasetExporter.EXPORT_DIR,
                                    f"episodes_{datetime.now().strftime('%Y%m%d')}.jsonl")
        try:
            from .learning import _conn as learn_conn
            c = learn_conn()
            query = "SELECT * FROM episodes"
            if min_success:
                query += " WHERE success=1"
            query += f" AND json_array_length(actions)>={min_actions}"
            query += " ORDER BY timestamp DESC LIMIT 5000"

            rows = c.execute(query).fetchall()
            count = 0
            with open(output_path, "w", encoding="utf-8") as f:
                for row in rows:
                    row = dict(row)
                    actions = json.loads(row.get("actions", "[]"))
                    if len(actions) < min_actions:
                        continue

                    # Формируем instruction/output пару
                    actions_text = "\n".join(
                        f"{'✅' if a.get('ok') else '❌'} {a.get('tool','')}: {a.get('s','')[:100]}"
                        for a in actions
                    )

                    entry = {
                        "instruction": row.get("task", "")[:1000],
                        "input": f"План: {row.get('plan', '')[:500]}",
                        "output": f"Действия:\n{actions_text}\n\nРезультат: {row.get('result', '')[:500]}"
                    }
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    count += 1

            logger.info(f"Exported {count} episodes to {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Export episodes failed: {e}")
            return ""

    @staticmethod
    def export_tool_skills() -> str:
        """Экспортировать tool skills в JSONL."""
        os.makedirs(DatasetExporter.EXPORT_DIR, exist_ok=True)
        output_path = os.path.join(DatasetExporter.EXPORT_DIR,
                                    f"skills_{datetime.now().strftime('%Y%m%d')}.jsonl")
        try:
            from .learning import _conn as learn_conn
            c = learn_conn()
            rows = c.execute("SELECT * FROM tool_skills WHERE success_count>=3").fetchall()
            count = 0
            with open(output_path, "w", encoding="utf-8") as f:
                for row in rows:
                    row = dict(row)
                    entry = {
                        "instruction": f"Какую команду использовать на сервере {row.get('os_type','Linux')} для {row.get('tool_name','')}?",
                        "input": f"Хост: {row.get('host','')}, ОС: {row.get('os_type','')}",
                        "output": f"Команда: {row.get('command_pattern','')}\nУспешно: {row.get('success_count',0)} раз"
                    }
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    count += 1

            logger.info(f"Exported {count} skills to {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Export skills failed: {e}")
            return ""

    @staticmethod
    def export_error_patterns() -> str:
        """Экспортировать error patterns в JSONL."""
        os.makedirs(DatasetExporter.EXPORT_DIR, exist_ok=True)
        output_path = os.path.join(DatasetExporter.EXPORT_DIR,
                                    f"errors_{datetime.now().strftime('%Y%m%d')}.jsonl")
        try:
            from .learning import _conn as learn_conn
            c = learn_conn()
            rows = c.execute("SELECT * FROM error_patterns WHERE fix_command IS NOT NULL AND success_rate>0.5").fetchall()
            count = 0
            with open(output_path, "w", encoding="utf-8") as f:
                for row in rows:
                    row = dict(row)
                    entry = {
                        "instruction": f"Как исправить ошибку: {row.get('error_message','')[:200]}",
                        "input": f"Инструмент: {row.get('tool_name','')}",
                        "output": f"Решение: {row.get('fix_description','')}\nКоманда: {row.get('fix_command','')}"
                    }
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    count += 1

            logger.info(f"Exported {count} error patterns to {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Export errors failed: {e}")
            return ""

    @staticmethod
    def export_all() -> Dict:
        """Экспортировать всё."""
        return {
            "episodes": DatasetExporter.export_episodes(),
            "skills": DatasetExporter.export_tool_skills(),
            "errors": DatasetExporter.export_error_patterns(),
            "dir": DatasetExporter.EXPORT_DIR
        }


# ══════════════════════════════════════════════════════════════
# 2. FINE-TUNER (требует GPU)
# ══════════════════════════════════════════════════════════════

class FineTuner:
    """
    LoRA fine-tuning через unsloth.
    
    Запуск:
        tuner = FineTuner()
        if tuner.is_available():
            tuner.train("path/to/episodes.jsonl")
    """

    MODEL_NAME = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"  # 4-bit quantized, ~4GB VRAM
    OUTPUT_DIR = os.path.join(MemoryConfig.DATA_DIR, "finetuned_model")
    LORA_R = 16
    LORA_ALPHA = 16
    EPOCHS = 3
    BATCH_SIZE = 2
    LEARNING_RATE = 2e-4

    @staticmethod
    def is_available() -> bool:
        """Проверить доступен ли GPU и unsloth."""
        try:
            import torch
            if not torch.cuda.is_available():
                return False
            from unsloth import FastLanguageModel
            return True
        except ImportError:
            return False

    @staticmethod
    def get_gpu_info() -> Dict:
        """Информация о GPU."""
        try:
            import torch
            if torch.cuda.is_available():
                return {
                    "available": True,
                    "device": torch.cuda.get_device_name(0),
                    "memory_gb": round(torch.cuda.get_device_properties(0).total_mem / 1e9, 1),
                    "memory_free_gb": round(torch.cuda.mem_get_info()[0] / 1e9, 1)
                }
        except:
            pass
        return {"available": False}

    @staticmethod
    def train(dataset_path: str, output_dir: str = None) -> Dict:
        """
        Запустить LoRA fine-tuning.
        
        dataset_path: путь к JSONL файлу
        output_dir: куда сохранить модель
        """
        if not FineTuner.is_available():
            return {"success": False, "error": "GPU or unsloth not available. Install: pip install unsloth"}

        output_dir = output_dir or FineTuner.OUTPUT_DIR
        os.makedirs(output_dir, exist_ok=True)

        try:
            from unsloth import FastLanguageModel
            from datasets import load_dataset
            from trl import SFTTrainer
            from transformers import TrainingArguments

            # Загрузить модель
            model, tokenizer = FastLanguageModel.from_pretrained(
                model_name=FineTuner.MODEL_NAME,
                max_seq_length=2048,
                load_in_4bit=True,
            )

            # Добавить LoRA адаптер
            model = FastLanguageModel.get_peft_model(
                model,
                r=FineTuner.LORA_R,
                lora_alpha=FineTuner.LORA_ALPHA,
                target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                "gate_proj", "up_proj", "down_proj"],
                lora_dropout=0,
                bias="none",
                use_gradient_checkpointing="unsloth",
            )

            # Загрузить датасет
            dataset = load_dataset("json", data_files=dataset_path, split="train")

            # Форматировать промпты
            def format_prompt(example):
                return {
                    "text": f"### Instruction:\n{example['instruction']}\n\n### Input:\n{example['input']}\n\n### Response:\n{example['output']}"
                }
            dataset = dataset.map(format_prompt)

            # Обучение
            trainer = SFTTrainer(
                model=model,
                tokenizer=tokenizer,
                train_dataset=dataset,
                dataset_text_field="text",
                max_seq_length=2048,
                args=TrainingArguments(
                    output_dir=output_dir,
                    num_train_epochs=FineTuner.EPOCHS,
                    per_device_train_batch_size=FineTuner.BATCH_SIZE,
                    learning_rate=FineTuner.LEARNING_RATE,
                    fp16=True,
                    logging_steps=10,
                    save_strategy="epoch",
                    warmup_steps=5,
                ),
            )

            trainer.train()

            # Сохранить
            model.save_pretrained(output_dir)
            tokenizer.save_pretrained(output_dir)

            logger.info(f"Fine-tuning complete: {output_dir}")
            return {
                "success": True,
                "output_dir": output_dir,
                "dataset_size": len(dataset),
                "epochs": FineTuner.EPOCHS
            }
        except Exception as e:
            logger.error(f"Fine-tuning failed: {e}")
            return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# 3. INFERENCE ROUTER
# ══════════════════════════════════════════════════════════════

class InferenceRouter:
    """
    Решает когда использовать fine-tuned модель vs cloud API.
    
    Fine-tuned лучше для:
    - Задачи специфичные для этого пользователя/сервера
    - Быстрые ответы (локальный inference)
    - Экономия API costs
    
    Cloud API лучше для:
    - Сложные задачи требующие большого контекста
    - Новые типы задач (не было в обучающих данных)
    - Креативные задачи
    """

    @staticmethod
    def is_finetuned_available() -> bool:
        """Проверить есть ли fine-tuned модель."""
        model_dir = FineTuner.OUTPUT_DIR
        return os.path.exists(os.path.join(model_dir, "adapter_config.json"))

    @staticmethod
    def should_use_finetuned(task: str, user_id: str) -> bool:
        """
        Решить использовать ли fine-tuned модель для задачи.
        True = использовать fine-tuned (быстро, дёшево, специализированно)
        False = использовать cloud API (мощнее, больше контекст)
        """
        if not InferenceRouter.is_finetuned_available():
            return False

        task_lower = task.lower()

        # Cloud API для сложных/креативных задач
        cloud_indicators = [
            "напиши статью", "создай дизайн", "проанализируй",
            "сравни", "объясни", "расскажи",
            "написать отчёт", "аудит", "code review",
        ]
        if any(kw in task_lower for kw in cloud_indicators):
            return False

        # Fine-tuned для рутинных операций
        finetune_indicators = [
            "деплой", "deploy", "установи", "install",
            "перезапусти", "restart", "обнови", "update",
            "проверь сервер", "check server", "настрой nginx",
            "создай файл", "systemctl",
        ]
        if any(kw in task_lower for kw in finetune_indicators):
            return True

        # По умолчанию — cloud API
        return False

    @staticmethod
    def query_finetuned(prompt: str, max_tokens: int = 1000) -> Optional[str]:
        """Запросить fine-tuned модель."""
        if not InferenceRouter.is_finetuned_available():
            return None

        try:
            from unsloth import FastLanguageModel

            model, tokenizer = FastLanguageModel.from_pretrained(
                model_name=FineTuner.OUTPUT_DIR,
                max_seq_length=2048,
                load_in_4bit=True,
            )
            FastLanguageModel.for_inference(model)

            formatted = f"### Instruction:\n{prompt}\n\n### Response:\n"
            inputs = tokenizer(formatted, return_tensors="pt").to("cuda")
            outputs = model.generate(
                **inputs, max_new_tokens=max_tokens,
                temperature=0.3, do_sample=True,
                pad_token_id=tokenizer.eos_token_id
            )
            result = tokenizer.decode(outputs[0], skip_special_tokens=True)
            # Извлечь только ответ
            if "### Response:" in result:
                result = result.split("### Response:")[-1].strip()
            return result
        except Exception as e:
            logger.error(f"Fine-tuned inference failed: {e}")
            return None
