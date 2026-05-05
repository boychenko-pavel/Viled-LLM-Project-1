from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sql_agent.config import MAX_HISTORY_MESSAGES


@dataclass
class SqlAgentMemory:
    instructions: list[str] = field(default_factory=list)
    conversation: list[dict[str, str]] = field(default_factory=list)
    schema_snapshot: str = ""

    @classmethod
    def load(cls, memory_path: Path) -> "SqlAgentMemory":
        if not memory_path.exists():
            return cls()

        data = json.loads(memory_path.read_text(encoding="utf-8"))
        conversation = [
            item
            for item in list(data.get("conversation", []))
            if str(item.get("content", "")).strip()
        ]
        return cls(
            instructions=list(data.get("instructions", [])),
            conversation=conversation,
            schema_snapshot=str(data.get("schema_snapshot", "")),
        )

    def save(self, memory_path: Path) -> None:
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned_conversation = [
            item
            for item in self.conversation[-MAX_HISTORY_MESSAGES:]
            if item.get("content", "").strip()
        ]
        payload = {
            "instructions": self.instructions,
            "conversation": cleaned_conversation,
            "schema_snapshot": self.schema_snapshot,
        }
        memory_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_instruction(self, instruction: str) -> None:
        cleaned = instruction.strip()
        if cleaned:
            self.instructions.append(cleaned)

    def add_turn(self, user_message: str, assistant_message: str) -> None:
        user_message = user_message.strip()
        assistant_message = assistant_message.strip()
        if user_message:
            self.conversation.append({"role": "user", "content": user_message})
        if assistant_message:
            self.conversation.append({"role": "assistant", "content": assistant_message})
        self.conversation = self.conversation[-MAX_HISTORY_MESSAGES:]


class SqlAgentMemoryRepository:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path

    def load(self) -> SqlAgentMemory:
        return SqlAgentMemory.load(self.memory_path)

    def save(self, memory: SqlAgentMemory) -> None:
        memory.save(self.memory_path)
