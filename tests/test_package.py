from asharelens import __version__


def test_package_exposes_semantic_version() -> None:
    major, minor, patch = __version__.split(".")
    assert (major, minor, patch) == ("0", "1", "0")
