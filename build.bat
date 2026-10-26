@echo off
REM ===================================================================
REM  Gera dist\HamsterDXSimulator\HamsterDXSimulator.exe com PyInstaller
REM  (modo pasta, sem UPX, com ícone e metadados de versão).
REM
REM  Pré-requisito: Python 3.10+ do python.org com "tcl/tk" marcado.
REM
REM  Opcional (menos falso positivo): compilar o bootloader localmente.
REM  Exige "Visual Studio Build Tools" com o workload C++ instalado:
REM      build.bat bootloader
REM ===================================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

if not exist .venv-build (
    echo [1/4] Criando ambiente virtual de build...
    %PY% -m venv .venv-build || goto :erro
)
call .venv-build\Scripts\activate.bat || goto :erro

echo [2/4] Instalando PyInstaller...
python -m pip install --upgrade pip >nul
if /I "%~1"=="bootloader" (
    echo      Compilando o bootloader do PyInstaller a partir do codigo-fonte...
    set PYINSTALLER_COMPILE_BOOTLOADER=1
    python -m pip install --force-reinstall --no-binary pyinstaller -r requirements-build.txt || goto :erro
) else (
    python -m pip install -r requirements-build.txt || goto :erro
)

echo [3/4] Rodando os testes da API...
python -m unittest discover -s tests || goto :erro

echo [4/4] Gerando o executavel...
pyinstaller --clean --noconfirm HamsterDXSimulator.spec || goto :erro

echo.
echo Pronto! Executavel em: dist\HamsterDXSimulator\HamsterDXSimulator.exe
echo Distribua a PASTA dist\HamsterDXSimulator inteira (zip ou instalador).
exit /b 0

:erro
echo.
echo *** Falhou. Veja a mensagem acima. ***
exit /b 1
