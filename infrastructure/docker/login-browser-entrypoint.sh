#!/bin/sh
# noVNC web client + websocket bridge to the per-login Xvnc display (password-protected, one-time password).
set -e
websockify --web /usr/share/novnc 0.0.0.0:6080 localhost:5900 &
exec uvicorn app.login_browser:app --host 0.0.0.0 --port 7900
