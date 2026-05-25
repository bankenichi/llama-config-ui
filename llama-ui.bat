@echo off
echo Starting Llama Config UI...
start "" http://127.0.0.1:8082
python "%~dp0server.py" 8082
