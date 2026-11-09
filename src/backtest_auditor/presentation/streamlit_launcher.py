"""Installed command that launches the optional Streamlit application."""

import sys
from importlib.resources import as_file, files


def main() -> None:
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError as error:
        raise SystemExit(
            "Streamlit is not installed. Install the optional UI with "
            "`pip install backtest-integrity-auditor[ui]`."
        ) from error

    resource = files("backtest_auditor.presentation").joinpath("streamlit_app.py")
    with as_file(resource) as app_path:
        sys.argv = ["streamlit", "run", str(app_path)]
        raise SystemExit(streamlit_cli.main())
