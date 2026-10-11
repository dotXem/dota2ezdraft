"""Shared setup. This runs before any test module imports the app's modules."""
import os
import tempfile
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# The app opens heroes.yaml, stratz_hero_to_id.yaml, ... relative to the cwd
os.chdir(ROOT)

# Tests never touch real accounts. Set before load_dotenv, which won't override it.
os.environ["EZDRAFT_USERS_PATH"] = os.path.join(tempfile.mkdtemp(prefix="ezdraft-tests-"), "users.yaml")

load_dotenv(ROOT / ".env")
HAS_STRATZ_TOKEN = bool(os.environ.get("STRATZ_API_TOKEN"))
# get_data_from_stratz reads the variable at import, so offline tests need it set
os.environ.setdefault("STRATZ_API_TOKEN", "unset")


@pytest.fixture
def needs_stratz():
    if not HAS_STRATZ_TOKEN:
        pytest.skip("needs STRATZ_API_TOKEN (in .env)")
