import pytest

from app.config import settings


@pytest.fixture(scope="session", autouse=True)
def isolate_persistent_runtime_indexes(tmp_path_factory):
    original_path = settings.VECTOR_INDEX_PATH
    settings.VECTOR_INDEX_PATH = str(tmp_path_factory.mktemp("runtime_indexes") / "vector_index.json")
    try:
        yield
    finally:
        settings.VECTOR_INDEX_PATH = original_path
