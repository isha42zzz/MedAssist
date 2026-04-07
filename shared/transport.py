from __future__ import annotations

import socket

from shared.proto import diagnosis_pb2


HEADER_SIZE = 4
MAX_FRAME_SIZE = 4 * 1024 * 1024


def send_frame(sock: socket.socket, frame: diagnosis_pb2.Frame) -> None:
    payload = frame.SerializeToString()
    if len(payload) > MAX_FRAME_SIZE:
        raise ValueError("frame exceeds max size")
    sock.sendall(len(payload).to_bytes(HEADER_SIZE, "big") + payload)


def recv_frame(sock: socket.socket) -> diagnosis_pb2.Frame:
    header = _recv_exact(sock, HEADER_SIZE)
    size = int.from_bytes(header, "big")
    if size <= 0 or size > MAX_FRAME_SIZE:
        raise ValueError("invalid frame size")
    payload = _recv_exact(sock, size)
    frame = diagnosis_pb2.Frame()
    frame.ParseFromString(payload)
    return frame


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError("connection closed")
        data.extend(chunk)
    return bytes(data)
