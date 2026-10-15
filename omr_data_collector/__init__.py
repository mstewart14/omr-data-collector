from importlib.metadata import PackageNotFoundError, version

APP_NAME = "OMR Data Collector"
# The installed package's name, which its version is recorded under.
DISTRIBUTION_NAME = "omr-data-collector"
REPOSITORY_URL = "https://github.com/mstewart14/omr-data-collector"
ISSUES_URL = f"{REPOSITORY_URL}/issues"


def app_version() -> str:
    """The app's version, as installed (pyproject.toml's); "" if it isn't recorded.

    The installers bundle the package's metadata for this (see the PyInstaller
    spec), and the self-check fails without it.
    """
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return ""
