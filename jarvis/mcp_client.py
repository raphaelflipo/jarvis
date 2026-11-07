"""
Client MCP (Model Context Protocol) minimal, sans dépendance : transport stdio, JSON-RPC 2.0.
Permet de brancher n'importe quel serveur MCP open-source (fichiers, bases de données, Git, Notion…)
déclaré dans config.json → "mcp_servers". Ses outils apparaissent sous le nom mcp__<serveur>__<outil>.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
import threading
from pathlib import Path

import registry
from registry import Tool
from security import NORMAL, RISKY, SAFE

PROTOCOL = "2025-06-18"
READ_HINT = re.compile(r"(^|_)(get|list|read|search|find|fetch|query|describe|view|show|status|info)", re.I)
WRITE_HINT = re.compile(r"(create|delete|remove|update|write|send|post|push|merge|move|rename|drop|insert|execute|run)", re.I)


class MCPServer:
    def __init__(self, name: str, spec: dict):
        self.name = re.sub(r"[^A-Za-z0-9_-]", "_", name)
        cmd = [spec["command"], *[os.path.expanduser(a) for a in spec.get("args", [])]]
        env = {**os.environ, **{k: str(v) for k, v in (spec.get("env") or {}).items()}}
        env["PATH"] = f"/opt/homebrew/bin:{Path.home()}/.local/bin:" + env.get("PATH", "")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1, env=env)
        self.ids = itertools.count(1)
        self.pending: dict[int, dict] = {}
        self.events: dict[int, threading.Event] = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()
        self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                    "clientInfo": {"name": "jarvis", "version": "2.0"}}, timeout=60)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg: dict):
        with self.lock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()

    def _reader(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                self.pending[msg["id"]] = msg
                ev = self.events.get(msg["id"])
                if ev:
                    ev.set()
            elif "id" in msg and "method" in msg:  # requête du serveur : on décline poliment
                resp = {"jsonrpc": "2.0", "id": msg["id"]}
                if msg["method"] == "ping":
                    resp["result"] = {}
                else:
                    resp["error"] = {"code": -32601, "message": "non supporté par Jarvis"}
                self._send(resp)

    def request(self, method: str, params: dict, timeout: int = 120) -> dict:
        i = next(self.ids)
        ev = threading.Event()
        self.events[i] = ev
        self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        if not ev.wait(timeout):
            raise TimeoutError(f"MCP {self.name}: pas de réponse à {method}")
        self.events.pop(i, None)
        msg = self.pending.pop(i)
        if "error" in msg:
            raise RuntimeError(f"MCP {self.name}: {msg['error'].get('message')}")
        return msg["result"]

    def tools(self) -> list[dict]:
        out, cursor = [], None
        while True:
            res = self.request("tools/list", {"cursor": cursor} if cursor else {})
            out += res.get("tools", [])
            cursor = res.get("nextCursor")
            if not cursor:
                return out

    def call(self, tool: str, args: dict) -> str:
        res = self.request("tools/call", {"name": tool, "arguments": args}, timeout=600)
        parts = []
        for c in res.get("content", []):
            if c.get("type") == "text":
                parts.append(c["text"])
            elif c.get("type") == "resource":
                parts.append(json.dumps(c.get("resource"), ensure_ascii=False)[:4000])
            else:
                parts.append(f"[{c.get('type')}]")
        text = "\n".join(parts)
        return ("[erreur MCP] " + text) if res.get("isError") else text

    def close(self):
        try:
            self.proc.terminate()
        except OSError:
            pass


SERVERS: dict[str, MCPServer] = {}


def load_all(cfg: dict, log=print) -> int:
    count = 0
    for name, spec in (cfg.get("mcp_servers") or {}).items():
        try:
            srv = MCPServer(name, spec)
            SERVERS[srv.name] = srv
            tool_list = srv.tools()
            for t in tool_list:
                full = f"mcp__{srv.name}__{t['name']}"[:64]
                schema = t.get("inputSchema") or {"type": "object", "properties": {}}
                allow = set(cfg.get("mcp_auto_allow") or [])

                def risk(_full=full, _name=t["name"], **kw):
                    if _full in allow:
                        return SAFE, ""
                    if WRITE_HINT.search(_name):
                        return RISKY, "outil MCP qui modifie des données"
                    if READ_HINT.search(_name):
                        return SAFE, ""
                    return NORMAL, ""

                def fn(_srv=srv, _name=t["name"], **kw):
                    return _srv.call(_name, kw)

                registry.TOOLS[full] = Tool(
                    name=full, description=f"[MCP {srv.name}] {(t.get('description') or '')[:400]}",
                    params=schema.get("properties", {}), required=schema.get("required", []),
                    fn=fn, category="mcp", risk=risk, untrusted=True)
                count += 1
            log(f"MCP « {name} » : {len(tool_list)} outil(s)")
        except Exception as e:
            log(f"MCP « {name} » indisponible : {e}")
    return count


def close_all():
    for s in SERVERS.values():
        s.close()
