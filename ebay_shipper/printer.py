"""Print module for Rollo thermal label printer via CUPS/lpr."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def print_file(file_path: Path, printer_name: str) -> bool:
    """Print a file to the specified CUPS printer.

    Args:
        file_path: Path to the file to print (PDF or text).
        printer_name: CUPS printer name (e.g. "Rollo").

    Returns:
        True if print job was submitted successfully.
    """
    if not file_path.exists():
        logger.error("File not found: %s", file_path)
        return False

    suffix = file_path.suffix.lower()
    cmd = ["lpr", "-P", printer_name]

    if suffix == ".zpl":
        # Raw mode for ZPL (thermal printer language)
        cmd.extend(["-o", "raw"])
    elif suffix == ".pdf":
        # Scale PDF to fill 4x6 label on Rollo thermal printer
        cmd.extend(["-o", "media=Custom.4x6in", "-o", "fit-to-page"])

    cmd.append(str(file_path))

    logger.info("Printing %s to %s", file_path.name, printer_name)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error("Print failed: %s", result.stderr)
            return False
        logger.info("Print job submitted: %s", file_path.name)
        return True
    except subprocess.TimeoutExpired:
        logger.error("Print command timed out for %s", file_path.name)
        return False
