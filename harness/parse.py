"""Turn one run's `codex exec --json` events and session rollout into a result."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

RATE_LIMIT = re.compile(r"\b429\b|rate.?limit|too many requests|usage limit|quota", re.IGNORECASE)
TRANSPORT = re.compile(
    r"stream disconnected|stream closed|connection|connect error|error sending request|timed? ?out|timeout"
    r"|\b50[0234]\b|bad gateway|service unavailable|gateway time|unexpected eof|broken pipe|reset by peer|dns",
    re.IGNORECASE,
)
_READ_VERB = re.compile(r"\b(cat|sed|head|tail|less|more|awk|bat|open|nl|python3?)\b")
_FILE_TIME = re.compile(r"\b(ls\s+[^|;&]*-\w*l|stat\b|find\b[^|;&]*(-newer|-mtime|-printf|-ls))")
_NOTICE = re.compile(r'"relation_notice"\s*:\s*"([^"]+)"')
_MEMORY_ID = re.compile(r"\bmem-[0-9a-f]{16}\b")
# A scrubbed transcript shows these placeholders where a developer path stood.
_OUTSIDE_PATH = re.compile(r"/Users/(?!Shared/wk/)[^\s\"'/]+|/var/folders/|/\.codex/\.tmp/|<redacted>|<developer-home>")
# Apple's git shim prints these on every call in a sandbox that cannot write the
# per-user temporary directory. They say nothing about what the agent reached.
_SHIM_NOISE = re.compile(r"^.*(xcrun_db-|xcodebuild\[|confstr\(\)|DVTDeveloperPaths|DVTFilePathFSEvents|DARWIN_USER_).*$", re.MULTILINE)


_REFUSAL = re.compile(r"[^\"\\\n]{0,60}[Oo]peration not permitted[^\"\\\n]{0,30}")


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def parse_events(path: Path) -> dict:
    commands, file_changes, mcp_calls, messages, warnings, failures, other_tools = [], [], [], [], [], [], Counter()
    usage = Counter()
    turns = 0
    thread_id = None
    for event in read_jsonl(path):
        kind = event.get("type")
        if kind == "thread.started":
            thread_id = event.get("thread_id")
        elif kind == "turn.completed":
            turns += 1
            for key, value in (event.get("usage") or {}).items():
                usage[key] += int(value or 0)
        elif kind == "turn.failed":
            failures.append(str((event.get("error") or {}).get("message") or event))
        elif kind == "error":
            failures.append(str(event.get("message") or event))
        elif kind == "item.completed":
            item = event.get("item") or {}
            item_type = item.get("type")
            if item_type == "command_execution":
                commands.append({"command": item.get("command", ""), "exit_code": item.get("exit_code"), "output": item.get("aggregated_output", "")})
            elif item_type == "file_change":
                file_changes += [change.get("path") for change in item.get("changes", [])]
            elif item_type == "mcp_tool_call":
                mcp_calls.append(item)
            elif item_type == "agent_message":
                messages.append(item.get("text", ""))
            elif item_type == "error":
                warnings.append(item.get("message", ""))
            elif item_type not in ("reasoning", "todo_list"):
                other_tools[item_type] += 1
    return {
        "thread_id": thread_id,
        "commands": commands,
        "file_changes": file_changes,
        "mcp_calls": mcp_calls,
        "messages": messages,
        "warnings": warnings,
        "failures": failures,
        "other_item_types": dict(other_tools),
        "usage": dict(usage),
        "turns": turns,
    }


def parse_rollouts(paths: list[Path]) -> dict:
    """Settings and context the run actually got, read from Codex's own session records."""
    found = {
        "rollouts": len(paths),
        "cwd": None,
        "model": None,
        "model_provider": None,
        "effort": None,
        "sandbox_type": None,
        "network_access": None,
        "network_policy": None,
        "permission_profile": None,
        "approval_policy": None,
        "agents_md_paths": [],
        "skill_roots": [],
        "hook_guidance_in_context": False,
        "agents_index_in_context": False,
        "subagents": 0,
        "web_search_items": 0,
        "tokens": {},
    }
    totals = Counter()
    for path in paths:
        last_total = {}
        for row in read_jsonl(path):
            kind, payload = row.get("type"), row.get("payload") or {}
            if kind == "session_meta":
                found["cwd"] = found["cwd"] or payload.get("cwd")
                found["model_provider"] = payload.get("model_provider")
                if payload.get("source") not in ("exec", None):
                    found["subagents"] += 1
            elif kind == "turn_context" and found["model"] is None:
                found["model"] = payload.get("model")
                found["effort"] = payload.get("effort")
                found["approval_policy"] = payload.get("approval_policy")
                policy = payload.get("sandbox_policy") or {}
                found["sandbox_type"] = policy.get("type")
                found["network_access"] = policy.get("network_access")
                found["network_policy"] = (payload.get("permission_profile") or {}).get("network")
                found["permission_profile"] = (payload.get("active_permission_profile") or {}).get("id")
            elif kind == "world_state":
                agents = (payload.get("state") or {}).get("agents_md") or {}
                if agents:
                    found["agents_md_paths"] = sorted({*found["agents_md_paths"], *_agents_paths(agents)})
            elif kind == "response_item":
                item_type = payload.get("type")
                if item_type == "message" and payload.get("role") in ("developer", "user"):
                    text = json.dumps(payload.get("content"), ensure_ascii=False)
                    if "MemForge Usage Guidance" in text:
                        found["hook_guidance_in_context"] = True
                    if "# Docs index" in text:
                        found["agents_index_in_context"] = True
                    found["skill_roots"] = sorted({*found["skill_roots"], *re.findall(r"`r\d+` = `([^`]+)`", text)})
                elif item_type == "web_search_call":
                    found["web_search_items"] += 1
            elif kind == "event_msg" and payload.get("type") == "token_count":
                last_total = (payload.get("info") or {}).get("total_token_usage") or last_total
        for key, value in last_total.items():
            totals[key] += int(value or 0)
    found["tokens"] = dict(totals)
    return found


def parse_tool_activity(paths: list[Path]) -> dict:
    """Every tool call and output the session recorded.

    Codex's event stream leaves out commands the sandbox refuses at once, so the
    session record is what isolation is judged on.
    """
    inputs, outputs = [], []
    for path in paths:
        for row in read_jsonl(path):
            payload = row.get("payload") or {}
            if row.get("type") != "response_item":
                continue
            if payload.get("type") in ("custom_tool_call", "function_call"):
                inputs.append(str(payload.get("input") or payload.get("arguments") or ""))
            elif payload.get("type") in ("custom_tool_call_output", "function_call_output"):
                text = json.dumps(payload.get("output"), ensure_ascii=False)
                outputs.append(_SHIM_NOISE.sub("", text.replace("\\\\n", "\n").replace("\\n", "\n")))
    commands = []
    for text in inputs:
        for match in re.finditer(r"""cmd\s*:\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)""", text):
            commands.append(match.group(1)[1:-1])
    return {"tool_calls": len(inputs), "inputs": inputs, "outputs": outputs, "commands": commands}


def _agents_paths(agents: dict) -> list[str]:
    return [agents["directory"]] if agents.get("directory") else sorted(agents)


def documents_seen(commands: list[dict], manifest: dict, task_id: str) -> dict:
    """Which of the task's documents the run's commands actually showed it."""
    seen: dict[str, bool] = {"stale": False, "current": False}
    other = False
    for name, document in manifest.items():
        for entry in commands:
            shown = document["marker"] in entry["output"]
            named = name in entry["command"] and _READ_VERB.search(entry["command"]) and entry["exit_code"] == 0
            if shown or named:
                if document["task"] == task_id:
                    seen[document["role"]] = True
                else:
                    other = True
    return {"read_stale_doc": seen["stale"], "read_current_doc": seen["current"], "read_other_task_doc": other}


def memory_usage(mcp_calls: list[dict], memory_roles: dict, task_id: str) -> dict:
    """Which memory tools were called, what they showed, and whether a notice arrived."""
    tools, failed = Counter(), Counter()
    seen_ids: set[str] = set()
    notices: list[str] = []
    fetched: list[str] = []
    for call in mcp_calls:
        tool = call.get("tool", "")
        if call.get("status") == "completed" and not call.get("error"):
            tools[tool] += 1
        else:
            failed[tool] += 1
            continue
        if tool == "get_memory":
            fetched.append((call.get("arguments") or {}).get("memory_id"))
        text = " ".join(part.get("text", "") for part in ((call.get("result") or {}).get("content") or []) if isinstance(part, dict))
        seen_ids.update(_MEMORY_ID.findall(text))
        notices += _NOTICE.findall(text)
    on_task = [memory_id for memory_id in seen_ids if memory_roles.get(memory_id, (None, None))[0] == task_id]
    stale_ids = {memory_id for memory_id, (task, role) in memory_roles.items() if task == task_id and role == "stale"}
    current_ids = {memory_id for memory_id, (task, role) in memory_roles.items() if task == task_id and role == "current"}
    task_notices = [notice for notice in notices if any(memory_id in notice for memory_id in current_ids)]
    return {
        "memory_tools": dict(tools),
        "memory_tool_failures": dict(failed),
        "called_memory_tool": bool(tools or failed),
        "saw_stale_memory": bool(seen_ids & stale_ids),
        "saw_current_memory": bool(seen_ids & current_ids),
        "fetched_memories": fetched,
        "saw_relation_notice": bool(notices),
        "relation_notice_count": len(notices),
        "saw_relation_notice_for_task": bool(task_notices),
        "memories_on_task": sorted(on_task),
    }


def classify_failure(failures: list[str], stderr: str) -> str | None:
    """A failed run's cause: rate_limited, transport or other. None when nothing failed."""
    if not failures:
        return None
    text = "\n".join(failures)
    if RATE_LIMIT.search(text):
        return "rate_limited"
    if TRANSPORT.search(text):
        return "transport"
    return "other"


def _bare(command: str) -> str:
    """A command without the quoting that differs between a tool call and the shell line."""
    return re.sub(r"[\s'\"\\]", "", command)


def isolation_findings(parsed_events: dict, rollout: dict, activity: dict, dirs_root: str, repo: str, group: str) -> dict:
    """What this run's own records say about isolation; `violations` must stay empty."""
    violations: list[str] = []
    outside_refs = []
    for command in activity["commands"]:
        hits = _OUTSIDE_PATH.findall(command)
        if hits:
            outside_refs.append({"command": command[:300], "paths": sorted(set(hits))[:10]})
    for output in activity["outputs"]:
        hits = _OUTSIDE_PATH.findall(output)
        if hits:
            outside_refs.append({"output_excerpt": output[:200], "paths": sorted(set(hits))[:10]})
    refused = [match for output in activity["outputs"] for match in _REFUSAL.findall(output)]
    recorded = _bare(" ".join(entry["command"] for entry in parsed_events["commands"]))
    unreported = [command[:160] for command in activity["commands"] if _bare(command) not in recorded]
    servers = sorted({call.get("server", "") for call in parsed_events["mcp_calls"]})
    if rollout["cwd"] != repo:
        violations.append(f"session cwd is not the run's repository: {rollout['cwd']}")
    if rollout["sandbox_type"] != "workspace-write" or rollout["network_access"] is not False:
        violations.append(f"sandbox is {rollout['sandbox_type']} with network_access {rollout['network_access']}")
    if rollout["permission_profile"] != "iso":
        violations.append(f"permission profile is {rollout['permission_profile']}")
    if rollout["model"] != "gpt-6-luna" or rollout["model_provider"] != "relay":
        violations.append(f"model is {rollout['model']} through {rollout['model_provider']}")
    if group == "D":
        if set(servers) - {"memforge"}:
            violations.append(f"MCP servers called: {servers}")
    elif servers:
        violations.append(f"group {group} called MCP servers: {servers}")
    if parsed_events["other_item_types"].get("web_search") or rollout["web_search_items"]:
        violations.append("web search was used")
    for root in rollout["skill_roots"]:
        if not root.startswith(dirs_root):
            violations.append(f"skill root outside the run's home: {root}")
    for path in rollout["agents_md_paths"]:
        if path != repo:
            violations.append(f"AGENTS.md from outside the run's repository: {path}")
    if group == "C" and not rollout["agents_index_in_context"]:
        violations.append("group C's AGENTS.md did not reach the agent")
    if group != "C" and rollout["agents_index_in_context"]:
        violations.append("an index reached a group that should not have one")
    if group == "D" and not rollout["hook_guidance_in_context"]:
        violations.append("the plugin's session-start guidance did not reach the agent")
    if group != "D" and rollout["hook_guidance_in_context"]:
        violations.append("plugin guidance reached a group without the plugin")
    return {
        "violations": violations,
        "mcp_servers_called": servers,
        "commands_touching_paths_outside_run": outside_refs,
        "commands_denied_by_sandbox": len(refused),
        "sandbox_refusals": refused,
        "commands_issued": len(activity["commands"]),
        "commands_absent_from_event_stream": unreported,
        "agents_md_paths": rollout["agents_md_paths"],
        "skill_roots": rollout["skill_roots"],
    }


def checked_file_times(commands: list[dict]) -> bool:
    return any(_FILE_TIME.search(entry["command"]) for entry in commands)
