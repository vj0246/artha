"""P0 smoke test: the package imports and reports a coherent version."""

import artha


def test_package_imports() -> None:
    assert artha.__version__ == "0.1.0"
