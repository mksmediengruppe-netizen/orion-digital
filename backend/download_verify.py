
"""B3: wget download verification utility."""
import re
import logging

logger = logging.getLogger("wget_verify")

def verify_wget_download(command, tool_result, ssh_executor, server_config):
    """Verify wget downloaded file has reasonable size."""
    if "wget " not in str(command):
        return tool_result
    
    if not tool_result.get("success"):
        return tool_result
    
    match = re.search(r'-O\s+(\S+)', command)
    if not match:
        return tool_result
    
    filepath = match.group(1)
    size_result = ssh_executor.execute(
        f"stat -c%s {filepath} 2>/dev/null || echo 0",
        server_config
    )
    size = int(size_result.get("output", "0").strip())
    
    if size < 1000:
        logger.warning(f"[B3] wget file too small: {filepath} = {size} bytes, retrying")
        retry_cmd = command.replace("wget ", "wget -c ")
        ssh_executor.execute(retry_cmd, server_config)
        # Re-check
        size_result = ssh_executor.execute(
            f"stat -c%s {filepath} 2>/dev/null || echo 0",
            server_config
        )
        new_size = int(size_result.get("output", "0").strip())
        tool_result["wget_verified"] = True
        tool_result["file_size"] = new_size
    else:
        tool_result["wget_verified"] = True
        tool_result["file_size"] = size
    
    return tool_result
