import pytest

from tokenledger.loader import load_manifest, load_sessions


@pytest.fixture(scope="session")
def sessions():
    return load_sessions()


@pytest.fixture(scope="session")
def manifest():
    return load_manifest()


@pytest.fixture(scope="session")
def arcs(manifest):
    return {a["arc"]: a for a in manifest.planted_arcs}
