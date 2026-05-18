import os
import datetime

def get_timestamped_output_dir(base_dir: str, prefix: str = "certificacion") -> str:
    """Return a new subdirectory under `base_dir` named `{prefix}_YYYYMMDD_HHMM`.
    Created if it does not exist.
    """
    timestamp = datetime.datetime.now().strftime(f"{prefix}_%Y%m%d_%H%M")
    out_path = os.path.join(base_dir, timestamp)
    os.makedirs(out_path, exist_ok=True)
    return out_path
