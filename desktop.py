"""
Desktop entry point for DOSCAR Plotter.

Runs the Dash/Flask app in a background thread and shows it inside a native
window via pywebview — no separate browser tab, no visible terminal, works
the same way on macOS and Windows. This is the module PyInstaller freezes
into the standalone app / exe; running it directly (``python desktop.py``)
also works for local development.
"""

import logging
import socket
import sys
import threading
import time
import urllib.request

import webview

from app import app as dash_app

# pywebview blocks all downloads by default. The Save Plot / Save COHP plot /
# Save COOP plot buttons rely on the browser-style "download" flow (Dash's
# dcc.Download), which without this is silently swallowed. Enabling it makes
# each save open a native Save-As dialog pre-pointed at the user's actual
# Downloads folder (on both macOS and Windows) with the suggested filename.
webview.settings['ALLOW_DOWNLOADS'] = True

WINDOW_TITLE = "DOSCAR Plotter"
# Wide enough that the COHP/COOP page's two plots sit side by side by
# default instead of wrapping to stacked (see .dual-plot-row / #cohp-page
# .atomic-pane in assets/style.css) — narrower windows still work, they just
# wrap.
START_WIDTH = 1660
START_HEIGHT = 900
MIN_WIDTH = 1100
MIN_HEIGHT = 700


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_server(port: int) -> None:
    # Quiet Flask's dev-server request logging; the window is the UI now.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    dash_app.run(
        debug=False,
        use_reloader=False,
        host="127.0.0.1",
        port=port,
    )


def _wait_for_server(url: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=0.5)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def main() -> int:
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    server_thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    server_thread.start()

    if not _wait_for_server(url):
        print("DOSCAR Plotter failed to start its local server.", file=sys.stderr)
        return 1

    webview.create_window(
        WINDOW_TITLE,
        url,
        width=START_WIDTH,
        height=START_HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        background_color="#f3f4f8",
    )
    # gui='edgechromium' is picked automatically on Windows when available;
    # macOS uses the system WKWebView. Leaving gui unset lets pywebview
    # choose the right backend per platform.
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
