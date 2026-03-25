"""
ORION Parallel Map — Phase 7
Manus-style parallel subtask processing.
Maps a prompt template across multiple inputs, executing subtasks in parallel.
"""
import logging
import json
import time
import csv
import io
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout

logger = logging.getLogger("parallel_map")


def parallel_map(
    prompt_template: str,
    inputs: List[str],
    output_schema: List[Dict],
    call_ai_fn=None,
    max_workers: int = 5,
    timeout_per_task: int = 120
) -> Dict[str, Any]:
    """
    Execute parallel subtasks using a prompt template.
    
    Like Manus map() tool:
    - Takes a prompt template with {{input}} placeholder
    - Applies it to each input in parallel
    - Returns structured results matching output_schema
    
    Args:
        prompt_template: Template with {{input}} placeholder
        inputs: List of input strings
        output_schema: List of output field definitions
        call_ai_fn: Function to call AI (messages) -> str
        max_workers: Max parallel workers
        timeout_per_task: Timeout per subtask in seconds
    
    Returns:
        Dict with results array and summary
    """
    if not call_ai_fn:
        return {"success": False, "error": "call_ai_fn is required"}
    
    if not inputs:
        return {"success": False, "error": "inputs list is empty"}
    
    max_workers = min(max_workers, 10)  # Safety limit
    
    # Build schema description for AI
    schema_desc = "Return a JSON object with these fields:\n"
    for field in output_schema:
        schema_desc += f"- {field['name']} ({field['type']}): {field.get('description', '')}\n"
    
    def process_single(input_str: str, index: int) -> Dict:
        """Process a single input."""
        start = time.time()
        try:
            # Replace {{input}} in template
            prompt = prompt_template.replace("{{input}}", input_str)
            
            messages = [
                {
                    "role": "system",
                    "content": f"You are a research assistant. Complete the task and return ONLY a valid JSON object.\n{schema_desc}"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
            
            response = call_ai_fn(messages)
            
            # Parse JSON from response
            result = _extract_json(response, output_schema)
            result["_input"] = input_str
            result["_index"] = index
            result["_success"] = True
            result["_duration_ms"] = round((time.time() - start) * 1000)
            
            return result
            
        except Exception as e:
            logger.error(f"[MAP] Subtask {index} failed: {e}")
            result = {field["name"]: None for field in output_schema}
            result["_input"] = input_str
            result["_index"] = index
            result["_success"] = False
            result["_error"] = str(e)
            result["_duration_ms"] = round((time.time() - start) * 1000)
            return result
    
    # Execute in parallel
    results = [None] * len(inputs)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_single, inp, i): i 
            for i, inp in enumerate(inputs)
        }
        
        for future in as_completed(futures):
            idx = futures[future]
            try:
                result = future.result(timeout=timeout_per_task)
                results[idx] = result
            except FuturesTimeout:
                results[idx] = {
                    field["name"]: None for field in output_schema
                }
                results[idx].update({
                    "_input": inputs[idx],
                    "_index": idx,
                    "_success": False,
                    "_error": f"Timeout after {timeout_per_task}s"
                })
            except Exception as e:
                results[idx] = {
                    field["name"]: None for field in output_schema
                }
                results[idx].update({
                    "_input": inputs[idx],
                    "_index": idx,
                    "_success": False,
                    "_error": str(e)
                })
    
    # Generate summary
    success_count = sum(1 for r in results if r and r.get("_success"))
    total_duration = sum(r.get("_duration_ms", 0) for r in results if r)
    
    return {
        "success": True,
        "total": len(inputs),
        "succeeded": success_count,
        "failed": len(inputs) - success_count,
        "total_duration_ms": total_duration,
        "results": results
    }


def _extract_json(text: str, schema: List[Dict]) -> Dict:
    """Extract JSON from AI response."""
    import re
    
    # Try to find JSON in response
    # First try: direct JSON parse
    try:
        return json.loads(text)
    except:
        pass
    
    # Second try: find JSON block
    json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except:
            pass
    
    # Third try: find ```json block
    json_block = re.search(r'```json?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_block:
        try:
            return json.loads(json_block.group(1))
        except:
            pass
    
    # Fallback: extract field values from text
    result = {}
    for field in schema:
        name = field["name"]
        # Try to find "name": "value" pattern
        pattern = rf'"{name}"\s*:\s*"([^"]*)"'
        match = re.search(pattern, text)
        if match:
            result[name] = match.group(1)
        else:
            result[name] = None
    
    return result


# Tool schema for parallel_map
PARALLEL_MAP_TOOL = {
    "type": "function",
    "function": {
        "name": "parallel_map",
        "description": "Execute parallel subtasks. Maps a prompt template across multiple inputs, processing them simultaneously. Like Pool.map() in Python multiprocessing.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt_template": {
                    "type": "string",
                    "description": "Template prompt with {{input}} placeholder for each subtask"
                },
                "inputs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of input strings to process"
                },
                "output_schema": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string", "enum": ["string", "number", "boolean"]},
                            "description": {"type": "string"}
                        }
                    },
                    "description": "Schema for output fields"
                },
                "max_workers": {
                    "type": "integer",
                    "description": "Max parallel workers (default 5, max 10)",
                    "default": 5
                }
            },
            "required": ["prompt_template", "inputs", "output_schema"]
        }
    }
}
