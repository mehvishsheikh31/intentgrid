"""Loads the sample policy for tests (scripts/ is not a package)."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "scripts" / "seed_policies.py"
_spec = importlib.util.spec_from_file_location("seed_policies", _path)
_seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_seed)
load_sample_policy = _seed.load_sample_policy
