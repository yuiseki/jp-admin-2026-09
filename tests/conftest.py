"""The scripts are named 01_build.py and 02_verify.py, which import cannot
spell, so they are loaded by path."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def build():
    return _load("build", "01_build.py")


@pytest.fixture(scope="session")
def verify():
    return _load("verify", "02_verify.py")
