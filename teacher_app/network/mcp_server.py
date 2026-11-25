"""Localhost MCP (Model Context Protocol) Streamable HTTP server for AI-driven classroom PowerShell & management."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from teacher_app.network.server import TeacherServer

logger = logging.getLogger("classroom_manager.teacher.mcp")

MCP_PROTOCOL_VERSION = "2025-03-26"
MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024


def generate_mcp_token() -> str:
    """Generate a high-entropy bearer token for local MCP authentication."""
    return "cm_" + secrets.token_urlsafe(24)


def build_mcp_client_config(port: int, token: str) -> str:
    """Return ready-to-paste JSON configuration for MCP-compatible AI clients."""
    cfg = {
        "mcpServers": {
            "classroom-manager": {
                "url": f"http://127.0.0.1:{port}/mcp",
                "headers": {
                    "Authorization": f"Bearer {token}",
                },
            }
        }
    }
    return json.dumps(cfg, ensure_ascii=False, indent=2)


MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_classrooms",
        "description": "Показать список всех настроенных кабинетов и текущий активный кабинет.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_students",
        "description": "Получить список всех подключённых ПК учеников (client_id, имя, hostname, пользователь, IP, кабинет, статус блокировки, активное окно, пинг).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "classroom_id": {
                    "type": "string",
                    "description": "Необязательный фильтр по ID кабинета (например, Cab-101).",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_system_info",
        "description": "Запросить подробную системную информацию (ОС, CPU, мониторы, активное окно) с выбранного ПК ученика.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "client_id, имя парты (например, Парта-01), hostname или IP ученика.",
                },
            },
            "required": ["target"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_powershell",
        "description": "Выполнить PowerShell-скрипт на одном конкретном ПК ученика и вернуть stdout, stderr и код возврата.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "client_id, имя парты, hostname или IP ученика.",
                },
                "script": {
                    "type": "string",
                    "description": "Код PowerShell для выполнения (UTF-8).",
                },
                "timeout": {
                    "type": "number",
                    "description": "Таймаут выполнения в секундах (по умолчанию 30).",
                    "default": 30,
                },
            },
            "required": ["target", "script"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_powershell_all",
        "description": "Массово выполнить PowerShell-скрипт на всех подключённых ПК учеников (или в одном кабинете) для настройки ПО, проверки окружения и администрирования.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "Код PowerShell для выполнения на каждом ПК.",
                },
                "classroom_id": {
                    "type": "string",
                    "description": "Необязательно: выполнить только в указанном кабинете.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Таймаут выполнения в секундах (по умолчанию 30).",
                    "default": 30,
                },
            },
            "required": ["script"],
            "additionalProperties": False,
        },
    },
    {
        "name": "send_message",
        "description": "Показать текстовое сообщение на экране одного ПК ученика или всего класса.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Текст сообщения."},
                "title": {"type": "string", "description": "Заголовок окна сообщения.", "default": "Сообщение от учителя"},
                "target": {"type": "string", "description": "Необязательно: конкретный ПК (если не указан – отправится всему классу)."},
                "classroom_id": {"type": "string", "description": "Необязательно: фильтр по кабинету при массовой отправке."},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_screen_lock",
        "description": "Заблокировать или разблокировать экран одного ПК ученика или всего класса.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "locked": {"type": "boolean", "description": "true – заблокировать экран, false – разблокировать."},
                "target": {"type": "string", "description": "Необязательно: конкретный ПК (если не указан – применится ко всему классу)."},
                "classroom_id": {"type": "string", "description": "Необязательно: фильтр по кабинету."},
                "message": {"type": "string", "description": "Подпись на экране блокировки.", "default": "срок бана: 1000 лет"},
            },
            "required": ["locked"],
            "additionalProperties": False,
        },
    },
    {
        "name": "send_file",
        "description": "Передать локальный файл с компьютера учителя на один ПК ученика или весь класс с проверкой SHA-256.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Абсолютный путь к файлу на ПК учителя."},
                "dest_dir": {
                    "type": "string",
                    "description": "Папка назначения (@desktop, @downloads, @documents, @public_desktop или путь на ПК ученика).",
                    "default": "@desktop",
                },
                "target": {"type": "string", "description": "Необязательно: конкретный ПК ученика (если не указан – всем)."},
                "classroom_id": {"type": "string", "description": "Необязательно: фильтр по кабинету."},
                "overwrite": {"type": "boolean", "default": True},
                "open_after": {"type": "boolean", "default": False},
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    },
]


class ClassroomMCPServer:
    """Zero-dependency asyncio Streamable HTTP MCP server bound strictly to 127.0.0.1."""

    def __init__(
        self,
        teacher_server: TeacherServer,
        port: int = 45460,
        token: str = "",
        on_activity: Callable[[str], None] | None = None,
    ) -> None:
        self.teacher_server = teacher_server
        self.port = int(port)
        self.token = token or generate_mcp_token()
        self.on_activity = on_activity
        self._server: asyncio.AbstractServer | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def bound_port(self) -> int:
        if self._server and self._server.sockets:
            return int(self._server.sockets[0].getsockname()[1])
        return self.port

    @property
    def endpoint_url(self) -> str:
        return f"http://127.0.0.1:{self.bound_port}/mcp"

    def _emit_activity(self, text: str) -> None:
        logger.info("[MCP] %s", text)
        if self.on_activity is not None:
            try:
                self.on_activity(text)
            except Exception:
                pass

    async def start(self) -> None:
        if self._running:
            return
        self._server = await asyncio.start_server(
            self._handle_http,
            host="127.0.0.1",
            port=self.port,
        )
        self._running = True
        self._emit_activity(f"MCP-сервер запущен на {self.endpoint_url}")

    async def stop(self) -> None:
        self._running = False
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self._emit_activity("MCP-сервер остановлен")

    async def _handle_http(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw_head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15.0)
        except Exception:
            writer.close()
            return

        try:
            head_text = raw_head.decode("utf-8", errors="replace")
            lines = head_text.split("\r\n")
            req_line = lines[0].split(" ")
            if len(req_line) < 2:
                await self._send_http(writer, 400, {"error": "Bad Request"})
                return
            method, path = req_line[0].upper(), req_line[1].split("?", 1)[0]

            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            # CORS preflight support for local tools
            if method == "OPTIONS":
                await self._send_http(writer, 204, None)
                return

            # Health check without auth
            if method == "GET" and path in ("/health", "/"):
                await self._send_http(
                    writer,
                    200,
                    {
                        "ok": True,
                        "service": "classroom-manager-mcp",
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "students_online": len(self.teacher_server.clients),
                    },
                )
                return

            # Bearer token auth check on /mcp
            auth_hdr = headers.get("authorization", "")
            expected_hdr = f"Bearer {self.token}"
            if not secrets.compare_digest(auth_hdr, expected_hdr):
                await self._send_http(writer, 401, {"error": "Unauthorized: invalid Bearer token"})
                return

            if path != "/mcp":
                await self._send_http(writer, 404, {"error": "Not Found"})
                return

            if method != "POST":
                await self._send_http(writer, 405, {"error": "Use POST /mcp with JSON-RPC 2.0"})
                return

            content_len = int(headers.get("content-length") or "0")
            if content_len < 0 or content_len > MAX_HTTP_BODY_BYTES:
                await self._send_http(writer, 413, {"error": "Payload too large"})
                return

            body_bytes = await asyncio.wait_for(reader.readexactly(content_len), timeout=15.0) if content_len else b""
            try:
                rpc = json.loads(body_bytes.decode("utf-8"))
            except json.JSONDecodeError:
                await self._send_http(
                    writer,
                    400,
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                )
                return

            response = await self._dispatch_rpc(rpc)
            if response is None:
                await self._send_http(writer, 202, None)
            else:
                await self._send_http(writer, 200, response)
        except Exception as exc:
            logger.exception("MCP HTTP handler error: %s", exc)
            await self._send_http(
                writer,
                500,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(exc)}},
            )
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    async def _send_http(writer: asyncio.StreamWriter, status: int, payload: dict[str, Any] | None) -> None:
        reasons = {
            200: "OK",
            202: "Accepted",
            204: "No Content",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            405: "Method Not Allowed",
            413: "Payload Too Large",
            500: "Internal Server Error",
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        hdrs = [
            f"HTTP/1.1 {status} {reasons.get(status, 'OK')}",
            "Content-Type: application/json; charset=utf-8",
            f"Content-Length: {len(body)}",
            "Access-Control-Allow-Origin: *",
            "Access-Control-Allow-Headers: Authorization, Content-Type, Mcp-Session-Id",
            "Access-Control-Allow-Methods: GET, POST, OPTIONS",
            "Connection: close",
            "",
            "",
        ]
        writer.write("\r\n".join(hdrs).encode("ascii") + body)
        await writer.drain()

    async def _dispatch_rpc(self, rpc: dict[str, Any]) -> dict[str, Any] | None:
        rpc_id = rpc.get("id")
        method = str(rpc.get("method") or "")
        params = rpc.get("params") or {}

        # Notifications have no id and expect no JSON-RPC body
        if method.startswith("notifications/"):
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "classroom-manager", "version": "2.2.0"},
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": MCP_TOOLS}}

        if method == "tools/call":
            tool_name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            try:
                result_data = await self._execute_tool(tool_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result_data, ensure_ascii=False, indent=2),
                            }
                        ],
                        "isError": False,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Ошибка: {exc}"}],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _resolve_client_id(self, target: str) -> str:
        needle = target.strip().lower()
        if not needle:
            raise ValueError("Не указан target (client_id, имя ПК или IP)")
        if target in self.teacher_server.clients:
            return target
        for cid, s in self.teacher_server.clients.items():
            if needle in (
                cid.lower(),
                s.label.strip().lower(),
                s.hostname.strip().lower(),
                s.ip.strip().lower(),
            ):
                return cid
        raise ValueError(f"ПК ученика «{target}» не найден среди подключённых")

    def _filter_client_ids(self, classroom_id: str | None = None) -> list[str]:
        room = (classroom_id or "").strip().lower()
        if not room:
            return list(self.teacher_server.clients.keys())
        return [
            cid
            for cid, s in self.teacher_server.clients.items()
            if (s.classroom_id or self.teacher_server.config.classroom_id).strip().lower() == room
        ]

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        srv = self.teacher_server

        if name == "list_classrooms":
            rooms = srv.config.ensure_classrooms()
            return {
                "active_classroom": srv.config.classroom_id,
                "classrooms": [
                    {
                        "id": r["id"],
                        "online_count": len(self._filter_client_ids(r["id"])),
                    }
                    for r in rooms
                ],
            }

        if name == "list_students":
            cids = self._filter_client_ids(args.get("classroom_id"))
            students = []
            for cid in cids:
                s = srv.clients[cid]
                students.append(
                    {
                        "client_id": s.client_id,
                        "label": s.label,
                        "hostname": s.hostname,
                        "username": s.username,
                        "ip": s.ip,
                        "classroom_id": s.classroom_id or srv.config.classroom_id,
                        "locked": s.locked,
                        "active_window": s.active_window,
                        "monitors": len(s.monitors) or 1,
                        "ping_ms": s.last_ping_ms,
                    }
                )
            return {"count": len(students), "students": students}

        if name == "get_system_info":
            cid = self._resolve_client_id(str(args.get("target") or ""))
            res = await srv.send_command(cid, "GET_SYSTEM_INFO", timeout=10.0)
            return {"client_id": cid, "result": res}

        if name == "run_powershell":
            cid = self._resolve_client_id(str(args.get("target") or ""))
            script = str(args.get("script") or "").strip()
            if not script:
                raise ValueError("Пустой PowerShell-скрипт")
            timeout = float(args.get("timeout") or 30.0)
            sess = srv.clients[cid]
            self._emit_activity(f"AI -> PS [{sess.label}]: {script}")
            res = await srv.run_powershell(cid, script, timeout=timeout)
            return {"client_id": cid, "label": sess.label, "result": res}

        if name == "run_powershell_all":
            script = str(args.get("script") or "").strip()
            if not script:
                raise ValueError("Пустой PowerShell-скрипт")
            timeout = float(args.get("timeout") or 30.0)
            cids = self._filter_client_ids(args.get("classroom_id"))
            if not cids:
                return {"count": 0, "results": {}, "message": "Нет подключённых ПК учеников"}
            self._emit_activity(f"AI -> PS [ВСЕ ({len(cids)} ПК)]: {script}")

            async def _run_one(cid: str) -> tuple[str, dict[str, Any]]:
                sess = srv.clients.get(cid)
                label = sess.label if sess else cid
                res = await srv.run_powershell(cid, script, timeout=timeout)
                return label, res

            pairs = await asyncio.gather(*(_run_one(c) for c in cids))
            return {"count": len(pairs), "results": dict(pairs)}

        if name == "send_message":
            text = str(args.get("text") or "").strip()
            title = str(args.get("title") or "Сообщение от учителя").strip()
            if not text:
                raise ValueError("Пустой текст сообщения")
            target = str(args.get("target") or "").strip()
            if target:
                cid = self._resolve_client_id(target)
                res = await srv.show_message(cid, title, text)
                return {"sent": 1, "result": res}
            cids = self._filter_client_ids(args.get("classroom_id"))
            results = {}
            for cid in cids:
                results[srv.clients[cid].label] = await srv.show_message(cid, title, text)
            return {"sent": len(cids), "results": results}

        if name == "set_screen_lock":
            locked = bool(args.get("locked"))
            message = str(args.get("message") or "срок бана: 1000 лет")
            target = str(args.get("target") or "").strip()
            cids = [self._resolve_client_id(target)] if target else self._filter_client_ids(args.get("classroom_id"))
            results = {}
            for cid in cids:
                lbl = srv.clients[cid].label
                if locked:
                    results[lbl] = await srv.lock_screen(cid, message)
                else:
                    results[lbl] = await srv.unlock_screen(cid)
            return {"count": len(cids), "locked": locked, "results": results}

        if name == "send_file":
            fpath = Path(str(args.get("file_path") or "").strip())
            if not fpath.is_file():
                raise ValueError(f"Файл не найден: {fpath}")
            dest_dir = str(args.get("dest_dir") or "@desktop")
            overwrite = bool(args.get("overwrite", True))
            open_after = bool(args.get("open_after", False))
            target = str(args.get("target") or "").strip()
            cids = [self._resolve_client_id(target)] if target else self._filter_client_ids(args.get("classroom_id"))
            if not cids:
                return {"count": 0, "results": {}, "message": "Нет подключённых ПК учеников"}
            self._emit_activity(f"AI -> Файл [{fpath.name}] на {len(cids)} ПК -> {dest_dir}")
            results = await srv.broadcast_file(
                fpath,
                dest_dir=dest_dir,
                overwrite=overwrite,
                open_after=open_after,
                client_ids=cids,
            )
            return {"count": len(cids), "results": results}

        raise ValueError(f"Неизвестный инструмент MCP: {name}")
