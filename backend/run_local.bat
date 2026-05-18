@echo off
echo ============================================================
echo   BACKEND SII CERTIFICADOR - MODO LOCAL
echo ============================================================
echo.

:: Verificar que pip este instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no encontrado. Instala Python 3.12+
    pause
    exit /b 1
)

:: Instalar dependencias si no estan
echo [1/2] Verificando dependencias...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo ERROR: Fallo al instalar dependencias.
    pause
    exit /b 1
)

:: Configurar OpenSSL legacy para .pfx con cifrados antiguos (RC2, 3DES)
set OPENSSL_CONF=%~dp0openssl_legacy.cnf

echo [2/2] Iniciando backend en http://localhost:8000
echo.
echo   Documentacion: http://localhost:8000/docs
echo   Para detener:  Ctrl+C
echo.
echo ============================================================

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
