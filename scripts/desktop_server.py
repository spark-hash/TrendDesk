"""Packaged localhost service. The launcher owns stdin for graceful shutdown."""
from pathlib import Path
import socket
import sys
import threading


def main():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    # Reserve the port before loading the database or starting market workers.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', 8765))
        import uvicorn
        from app.main import app
        from desktop_update import monitor_releases

        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))

        def watch_launcher():
            sys.stdin.readline()
            server.should_exit = True

        threading.Thread(target=watch_launcher, daemon=True).start()
        threading.Thread(target=monitor_releases, daemon=True).start()
        server.run(sockets=[listener])


if __name__ == '__main__':
    main()
