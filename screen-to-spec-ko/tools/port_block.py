# -*- coding: utf-8 -*-
"""빌드 · 채점 · 탐침이 같은 포트를 잡지 않게 포트 10칸을 예약한다 (run_build · grade_run · pii_probe · own_contract_probe 공용).
칸은 10 단위로 맞춘다(9600~9609). 끝자리 9 를 배타적으로 bind 해 쥐고 있는 동안이 예약이고, 앞 9칸(9600~9608)을 쓴다.
쥔 프로세스가 죽으면 OS 가 풀어 주니 남는 파일이 없고, 다른 세션 · 다른 프로세스끼리도 서로 보인다.
8000~8999 는 쓰지 않는다 — kill_servers.py 가 치우는 자리이고, 빌더가 제멋대로 고르는 포트도 거기다.

사용: with PortBlock(9600) as pb: env["PORT"] = str(pb.port)"""
import os
import socket

BUILD_BASE = 9600
STEP = 10


def _bind(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        s.close()
        raise
    return s


def _free(port):
    try:
        _bind(port).close()
        return True
    except OSError:
        return False


class PortBlock:
    """start 가 든 10칸부터 찾아 올라가 비어 있는 첫 묶음을 잡는다. .port 첫 칸, .ports 쓸 수 있는 9칸."""

    def __init__(self, start=BUILD_BASE):
        port = start - start % STEP
        while port + STEP < 65000:
            try:
                self._guard = _bind(port + STEP - 1)
            except OSError:
                port += STEP
                continue
            if all(_free(p) for p in range(port, port + STEP - 1)):
                self.port, self.ports = port, list(range(port, port + STEP - 1))
                return
            self._guard.close()
            port += STEP
        raise RuntimeError("빈 포트 묶음을 못 찾음 (시작 %d)" % start)

    def close(self):
        self._guard.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
