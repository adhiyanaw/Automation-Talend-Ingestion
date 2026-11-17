@echo off
REM contoh: run_push.bat --job ZZ_SAMPLE_PUSH            (dry-run)
python "%~dp0deploy.py" %*
