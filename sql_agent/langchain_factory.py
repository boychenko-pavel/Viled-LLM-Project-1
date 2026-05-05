from __future__ import annotations

from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_openai import ChatOpenAI

from sql_agent.config import LM_STUDIO_BASE_URL, LM_STUDIO_MODEL
from sql_agent.memory import SqlAgentMemory
from sql_agent.prompts import build_system_prompt


def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=LM_STUDIO_MODEL,
        base_url=LM_STUDIO_BASE_URL,
        api_key="lm-studio",
        temperature=0,
    )


def build_agent(db: SQLDatabase, memory: SqlAgentMemory):
    llm = build_llm()
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    system_prompt = build_system_prompt(memory, db)
    return create_sql_agent(
        llm=llm,
        toolkit=toolkit,
        prefix=system_prompt,
        verbose=False,
        max_iterations=20,
        agent_executor_kwargs={"handle_parsing_errors": True},
    )


class LangChainSqlAgentFactory:
    def build_llm(self) -> ChatOpenAI:
        return build_llm()

    def build_agent(self, db: SQLDatabase, memory: SqlAgentMemory):
        return build_agent(db, memory)
