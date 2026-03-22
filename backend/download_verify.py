"""
MEGA PATCH Bug 3.2: Download verification utilities
"""
import re
import logging

logger = logging.getLogger("download_verify")


def verify_download_size(command, ssh_conn, min_size=1000):
    """After wget/curl, verify file was downloaded correctly.
    Returns (ok, filepath, size)"""
    if not ssh_conn:
        return True, None, 0

    filepath = None
    # Extract output path from wget -O or curl -o
    match = re.search(r'(?:-O|--output-document[= ]|-o)\s*["\'"]?([^\s"\']+)', command)
    if match:
        filepath = match.group(1)
    else:
        # Try to extract from wget URL (last path component)
        url_match = re.search(r'(?:wget|curl)\s+.*?(https?://\S+)', command)
        if url_match:
            url = url_match.group(1).split('?')[0]
            filepath = url.split('/')[-1]

    if not filepath:
        return True, None, 0

    try:
        _, check_out, _ = ssh_conn.exec_command(f"stat -c%s {filepath} 2>/dev/null || echo 0")
        size = int(check_out.read().decode().strip())
        if size < min_size:
            logger.warning(f"Download appears failed: {filepath} = {size} bytes")
            return False, filepath, size
        return True, filepath, size
    except Exception as e:
        logger.warning(f"Download verify failed: {e}")
        return True, filepath, 0
