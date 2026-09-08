"""Ограничение доступа к сетевым службам моста.

Сам протокол не шифруется и защищён одним паролем, поэтому важно, чтобы
подобрать его было нельзя, а число соединений оставалось конечным.
"""

from __future__ import annotations

import ipaddress
import logging
import time

log = logging.getLogger("access")


class AccessControl:
    def __init__(self, allow_from: list[str] | tuple[str, ...] = (),
                 max_failures: int = 5, ban_seconds: int = 300,
                 max_connections: int = 8):
        self.networks = []
        for item in allow_from:
            try:
                self.networks.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                log.warning("не разобрал адрес в списке разрешённых: %r", item)
        self.max_failures = max_failures
        self.ban_seconds = ban_seconds
        self.max_connections = max_connections
        self.connections = 0
        self._failures: dict[str, tuple[int, float]] = {}

    # --- кто может подключаться -----------------------------------------

    def allowed(self, host: str) -> bool:
        """Пустой список разрешённых означает «отовсюду»."""
        if not self.networks:
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return any(address in network for network in self.networks)

    def banned(self, host: str) -> bool:
        count, until = self._failures.get(host, (0, 0.0))
        if until and time.time() < until:
            return True
        if until and time.time() >= until:
            self._failures.pop(host, None)
        return False

    def note_failure(self, host: str) -> bool:
        """Считает неудачный вход. True — адрес заблокирован."""
        count, _ = self._failures.get(host, (0, 0.0))
        count += 1
        if count >= self.max_failures:
            self._failures[host] = (count, time.time() + self.ban_seconds)
            log.warning("адрес %s заблокирован на %d с после %d неудачных попыток",
                        host, self.ban_seconds, count)
            return True
        self._failures[host] = (count, 0.0)
        return False

    def note_success(self, host: str) -> None:
        self._failures.pop(host, None)

    # --- сколько их одновременно ----------------------------------------

    def take_slot(self) -> bool:
        if self.connections >= self.max_connections:
            return False
        self.connections += 1
        return True

    def free_slot(self) -> None:
        self.connections = max(0, self.connections - 1)
