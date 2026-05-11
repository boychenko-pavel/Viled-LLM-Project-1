# Viled ATLAS LLM Project start-stop

## Start

Open PowerShell and run:

```powershell
cd "C:\Users\p.boychenko\Desktop\MachineLearning\Viled ATLAS LLM Project"
python -m uvicorn sql_agent.web:app --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

## Stop

If the server is running in the same PowerShell window, press:

```text
Ctrl + C
```

If the server is running in the background, find the process on port `8000`:

```powershell
Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess
```

Then stop it:

```powershell
Stop-Process -Id <PID>
```

Example:

```powershell
Stop-Process -Id 24184
```

## Requirements

- Keep VPN enabled when using `BI Analytics`, because SQL Server is available only through VPN.
- Keep LM Studio running at `http://127.0.0.1:1234/v1` when using `Office Manager` or LLM fallback.
- If dependencies are missing, run:

```powershell
python -m pip install -r requirements.txt
```
