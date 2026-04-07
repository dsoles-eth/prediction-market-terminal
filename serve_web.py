#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from textual_serve.server import Server

pkg = os.path.dirname(os.path.abspath(__import__("textual_serve").__file__))

if __name__ == "__main__":
    server = Server(
        command=f"python3 {os.path.abspath('run_terminal.py')}",
        host="100.64.2.12",   # Tailscale IP — so JS loads correctly from phone
        port=8080,
        title="Polymarket Terminal",
        statics_path=os.path.join(pkg, "static"),
        templates_path=os.path.join(pkg, "templates"),
    )
    print("Polymarket Terminal → http://100.64.2.12:8080")
    server.serve()
