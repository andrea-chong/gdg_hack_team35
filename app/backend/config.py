# backend/config.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List

PACKAGE_ROOT = Path(__file__).resolve().parent  # .../app/backend


def _candidate_directories() -> Iterable[Path]:
    """
    Generate all possible synthetic_data directories in order:
    1. Environment variable DATA_DIR;
    2. New convention: ../data/synthetic_data;
    3. Backward compatibility: backend/synthetic_data;
    4. Backward compatibility: ../synthetic_data.
    """
    env_dir = os.getenv("DATA_DIR")
    if env_dir:
        yield Path(env_dir).expanduser().resolve()

    yield PACKAGE_ROOT.parent / "data" / "synthetic_data"

    yield PACKAGE_ROOT / "synthetic_data"
    yield PACKAGE_ROOT.parent / "synthetic_data"


def default_data_directory() -> Path:
    """
    Return the directory containing synthetic CSV data.
    Check candidate paths in order and use the first one that exists and is a directory.
    """
    candidates: List[Path] = list(_candidate_directories())
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate

    searched_paths = "\n  - ".join(str(path) for path in candidates)
    raise FileNotFoundError(
        "Could not locate synthetic data directory. Searched paths:\n"
        f"  - {searched_paths}\n"
        "Please set DATA_DIR to a valid directory or place the CSV files in one of the locations above."
    )


DATA_DIR = default_data_directory()