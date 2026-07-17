@echo off
cd /d "C:\Users\p.boychenko\Desktop\MachineLearning\Viled ATLAS LLM Project"
python -m uvicorn sql_agent.web:app --host 127.0.0.1 --port 8000
pause
