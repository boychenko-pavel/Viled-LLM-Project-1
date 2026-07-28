# Архитектура SQL-агента

Схема показывает фактический поток запроса в `BI Analytics`: локальную LLM в
LM Studio, два режима OpenAI API, детерминированную сборку SQL и границу доступа
к SQL Server.

```mermaid
flowchart TB
    U["Пользователь<br/>BI Analytics"] --> UI["Web UI<br/>запрос + настройки режима"]
    UI --> API["FastAPI<br/>POST /api/chat"]
    API --> W["WebSqlAgent.stream()"]

    W --> CALC{"SQL CALCULATION?"}

    CALC -- "ON" --> OGEN["OpenAI API<br/>генерация SQL"]
    DOCS["docs/database_schema.md<br/>docs/business_logic.md"] --> OGEN
    OGEN --> SAFE1["Проверка:<br/>один read-only SELECT / CTE"]
    SAFE1 --> OVERRIDE["SqlAgentService<br/>sql_override"]

    CALC -- "OFF" --> LOCAL["Локальный контур SQL"]
    MEM["Локальная память<br/>.agent_memory/sql_agent_memory.json"] --> LOCAL
    LOCAL --> CLARIFY{"Нужно уточнение?"}
    CLARIFY -- "Да" --> ANSWER
    CLARIFY -- "Нет" --> EXPLICIT{"В сообщении есть<br/>явный SELECT?"}
    EXPLICIT -- "Да" --> SAFE2["Проверка read-only SQL"]
    EXPLICIT -- "Нет" --> INTENT["IntentParser<br/>правила → fallback к локальной LLM"]
    LM["LM Studio<br/>llama-3.2-3b-instruct<br/>127.0.0.1:1234/v1"] --> INTENT
    INTENT --> BUILDER["SqlBuilder<br/>детерминированный SQL"]
    BUILDER --> LOCALSQL["Локально сформированный SQL"]
    LOCALSQL --> CHECK{"SQL CHECK MODE?"}
    CHECK -- "ON" --> OREVIEW["OpenAI API<br/>семантическая проверка SQL"]
    DOCS --> OREVIEW
    OREVIEW --> REVIEWNOTE["Статус проверки<br/>или рекомендуемый SQL"]
    CHECK -- "OFF" --> NOCHECK["Проверка отключена"]

    OVERRIDE --> EXEC
    SAFE2 --> EXEC
    LOCALSQL --> EXEC["Валидация и выполнение<br/>исходного read-only SELECT"]

    EXEC --> DB["Microsoft SQL Server<br/>DWH.LLM.* / LLM.sales"]
    DB --> FORMAT["Колонки + строки<br/>форматирование ответа"]
    FORMAT --> ANSWER["Ответ пользователю<br/>SQL + результат + пояснение"]
    REVIEWNOTE -. "показывается отдельно;<br/>не заменяет выполняемый SQL" .-> ANSWER
    NOCHECK -.-> ANSWER
    ANSWER --> MEM

    OFFICE["Office Manager"] --> LM
    OFFICE -. "отдельная память;<br/>без SQL-инструментов" .-> OFFMEM[".agent_memory/<br/>office_manager_memory.json"]

    classDef user fill:#E8F1FF,stroke:#2563EB,color:#0F172A;
    classDef local fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef openai fill:#FFF7ED,stroke:#EA580C,color:#0F172A;
    classDef data fill:#F5F3FF,stroke:#7C3AED,color:#0F172A;
    classDef guard fill:#FEF2F2,stroke:#DC2626,color:#0F172A;

    class U,UI,API,W,ANSWER user;
    class LOCAL,CLARIFY,EXPLICIT,INTENT,BUILDER,LOCALSQL,LM,OFFICE local;
    class OGEN,OREVIEW,REVIEWNOTE openai;
    class MEM,OFFMEM,DOCS,DB data;
    class SAFE1,SAFE2,EXEC,CALC,CHECK guard;
```

## Режимы OpenAI

| SQL CALCULATION | SQL CHECK MODE | Кто формирует SQL | Что делает OpenAI | Что выполняется |
|---|---|---|---|---|
| ON | ON или OFF | OpenAI API | Генерирует read-only SQL; повторная проверка пропускается | SQL от OpenAI после локальной валидации |
| OFF | ON | Локальный контур | Проверяет смысл локального SQL и при ошибке показывает рекомендацию | Исходный локальный SQL |
| OFF | OFF | Локальный контур | Не вызывается | Исходный локальный SQL |

## Границы данных и доступа

- Локальная LLM участвует в разборе неоднозначного намерения, но стандартные
  запросы проходят через правила `IntentParser` и детерминированный `SqlBuilder`.
- OpenAI получает запрос пользователя, документацию схемы и бизнес-правил, а в
  режиме проверки — также сформированный SQL.
- OpenAI не получает инструменты SQL Server, не выполняет запрос и не видит
  строки результата.
- Подключение к SQL Server и выполнение read-only SQL остаются внутри локального
  приложения.
- При недоступном OpenAI режим `SQL CALCULATION` останавливает запрос безопасной
  ошибкой; автоматического перехода на локальную генерацию нет.

Источники реализации: `sql_agent/web.py`, `sql_agent/service.py`,
`sql_agent/intent_parser.py`, `sql_agent/sql_builder.py`,
`sql_agent/sql_reviewer.py`, `sql_agent/langchain_factory.py`.
