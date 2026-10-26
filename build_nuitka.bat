@echo off
REM ===================================================================
REM  Alternativa ao PyInstaller: compila o Python para C com o Nuitka.
REM  Gera dist-nuitka\main.dist\HamsterDXSimulator.exe
REM
REM  Costuma ter ainda menos falso positivo que o PyInstaller, porque o
REM  .exe é um binário C nativo, sem o bootloader genérico.
REM  Na primeira vez o Nuitka oferece baixar o compilador (MinGW) sozinho;
REM  responda "yes". Leva alguns minutos.
REM ===================================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

if not exist .venv-nuitka (
    %PY% -m venv .venv-nuitka || goto :erro
)
call .venv-nuitka\Scripts\activate.bat || goto :erro
python -m pip install --upgrade pip >nul
python -m pip install "nuitka>=2.4" || goto :erro

python -m unittest discover -s tests || goto :erro

python -m nuitka main.py ^
    --standalone ^
    --enable-plugin=tk-inter ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=assets\icon.ico ^
    --include-data-dir=fixtures=fixtures ^
    --include-data-dir=assets=assets ^
    --output-dir=dist-nuitka ^
    --output-filename=HamsterDXSimulator.exe ^
    --company-name="Hamster DX Simulator" ^
    --product-name="Hamster DX Simulator" ^
    --file-version=2.0.0.0 ^
    --product-version=2.0.0.0 ^
    --file-description="Simulador do leitor biometrico Fingertech Hamster DX" ^
    --assume-yes-for-downloads ^
    --remove-output || goto :erro

echo.
echo Pronto! Executavel em: dist-nuitka\main.dist\HamsterDXSimulator.exe
echo Distribua a PASTA dist-nuitka\main.dist inteira.
exit /b 0

:erro
echo.
echo *** Falhou. Veja a mensagem acima. ***
exit /b 1
