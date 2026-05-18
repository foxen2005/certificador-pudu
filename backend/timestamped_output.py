import os
import datetime

def get_timestamped_output_dir(base_dir: str) -> str:
    """Return a new subdirectory under `base_dir` named
    `certificacion_YYYYMMDD_HHMM`. Created if it does not exist.
    Colons are not used because Windows does not allow them in path names.
    """
    timestamp = datetime.datetime.now().strftime("certificacion_%Y%m%d_%H%M")
    out_path = os.path.join(base_dir, timestamp)
    os.makedirs(out_path, exist_ok=True)
    return out_path
