"""
PyBullet GUI simulation that mirrors the real robot command interface.

Usage:
  - Run: python pybullet_virtual_gui.py
  - Send commands (comma-separated floats, 24 values max) via UDP to 127.0.0.1:5556
    Example (PowerShell):
      $udp = New-Object System.Net.Sockets.UdpClient; \
      $bytes = [System.Text.Encoding]::UTF8.GetBytes('0,0,0,0,200,45,0,1,1,0.2,1,1,0.2,0,0,80,1.2,1,50,1,180,0,0,1'); \
      $udp.Send($bytes, $bytes.Length, '127.0.0.1', 5556) | Out-Null

This accepts the same 24-length control vector used by the real environment
and updates a simple visual model if the original URDF is not available.
"""
from __future__ import annotations

import socket
import threading
import time
from typing import Optional

from robot_reloj.virtual_robot import VirtualRobotController


class UDPCommandServer:
    def __init__(self, controller: VirtualRobotController, host: str = "127.0.0.1", port: int = 5556) -> None:
        self.controller = controller
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None
        self._th: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((self.host, self.port))
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()
        print(f"UDP listening on {self.host}:{self.port}")

    def _loop(self) -> None:
        assert self._sock is not None
        while self._running:
            try:
                data, _ = self._sock.recvfrom(8192)
                if not data:
                    continue
                text = data.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue
                try:
                    values = [float(ch.strip()) for ch in text.split(",") if ch.strip()]
                except ValueError:
                    continue
                self.controller.apply_command(values)
            except OSError:
                break

    def stop(self) -> None:
        self._running = False
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None


def main() -> None:
    ctrl = VirtualRobotController(use_gui=True)

    # Background integrator ticking at ~60 Hz
    def tick() -> None:
        last = time.time()
        while True:
            now = time.time()
            dt = now - last
            last = now
            try:
                ctrl.advance(dt)
            except Exception:
                pass
            time.sleep(max(0.0, 1.0 / 60.0 - (time.time() - now)))

    threading.Thread(target=tick, daemon=True).start()

    # UDP command server
    udp = UDPCommandServer(ctrl)
    udp.start()

    print("PyBullet GUI ready. Send 24-value commands via UDP to 127.0.0.1:5556")
    print("Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        udp.stop()


if __name__ == "__main__":
    main()

