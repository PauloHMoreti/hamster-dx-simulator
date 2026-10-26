# Hamster DX Simulator (Python)

Simulador da **BiometricServiceAPI** da FingerTech/Nitgen para o leitor **Hamster DX**,
agora em Python com tela de configuração em Tkinter e pronto para virar `.exe` no Windows.

O simulador **não tem nenhuma dependência externa**: usa só a biblioteca padrão
(`http.server`, `json`, `tkinter`...). Isso deixa o executável pequeno e reduz o risco de
falso positivo de antivírus.

## Rodar a partir do código

```bat
python main.py            :: abre a tela
python main.py --nogui    :: só o servidor, no terminal
python main.py --nogui --port 5001
```

Requer Python 3.10+ (o instalador do python.org já traz o Tkinter).

## Gerar o executável

```bat
build.bat
```

Resultado: `dist\HamsterDXSimulator\HamsterDXSimulator.exe`. Distribua a **pasta inteira**
`dist\HamsterDXSimulator` (zipada ou via instalador), não só o `.exe`.

### Por que assim (antivírus)

| Escolha | Motivo |
|---|---|
| Modo pasta (`onedir`), não `--onefile` | O onefile se descompacta em `%TEMP%` e executa de lá, padrão típico de malware. É a maior causa de falso positivo. |
| Sem UPX | Executável comprimido com UPX é muito sinalizado. |
| Ícone + recurso de versão | `.exe` com metadados (Propriedades > Detalhes) parece menos "anônimo" para os scanners. |
| Escuta em `127.0.0.1` por padrão | Não dispara o alerta do Firewall do Windows. |
| Sem dependências | Menos código de terceiros empacotado. |

Se ainda assim algum antivírus reclamar, em ordem de eficácia:

1. **Compilar o bootloader do PyInstaller localmente**: `build.bat bootloader`
   (precisa do *Visual Studio Build Tools* com C++). O bootloader pré-compilado é o mesmo
   usado por malware feito em PyInstaller, por isso é o que mais gera alerta.
2. **Usar o Nuitka** em vez do PyInstaller: `build_nuitka.bat`. Compila o Python para C
   e gera um binário nativo, sem bootloader genérico.
3. **Gerar um instalador** com o Inno Setup (`build_tools\installer.iss`).
4. **Assinar o executável** com um certificado de code signing. É a única forma de
   eliminar de vez o aviso do SmartScreen ("O Windows protegeu o computador").
5. Enviar o arquivo para análise de falso positivo da Microsoft:
   <https://www.microsoft.com/wdsi/filesubmission>.

> O aviso azul do **SmartScreen** é diferente do antivírus: aparece para qualquer `.exe`
> novo e sem assinatura. Clique em "Mais informações > Executar assim mesmo".

## A tela

- **Topo**: status do servidor, Iniciar/Parar, copiar URL.
- **Leitor simulado**: digital atual, cenário e capturas aguardando. *Colocar dedo no
  leitor* responde as capturas pendentes na hora; *Cancelar capturas* faz elas
  retornarem `Capture cancelled`.
- **Simulação**: cenário padrão, opção de forçar o cenário (ignorar o `?scenario=` que o
  sistema envia), modo de captura automático ou manual, tempos e serial do dispositivo.
- **Digitais**: cadastrar, editar e remover digitais mock (ID, finger ID, qualidade,
  template e imagem), com pré-visualização. Duplo clique define a digital atual.
- **Memória**: o que foi carregado via `/load-to-memory`, com atalho para carregar todas
  as digitais mock.
- **Servidor**: endereço, porta e início automático.
- **Log de requisições**: equivalente ao `morgan`.

As configurações são salvas automaticamente em
`%APPDATA%\HamsterDXSimulator\config.json`. As variáveis do antigo `.env`
(`PORT`, `MOCK_DEFAULT_SCENARIO`, `MOCK_CAPTURE_DELAY`) continuam funcionando e têm
prioridade.

## Modo de captura manual

No modo manual cada captura fica esperando até alguém clicar em **Colocar dedo no
leitor**, como no aparelho de verdade. Se ninguém clicar dentro do *timeout do modo
manual*, a API responde `Timeout`. Os cenários `disconnected` e `sdkError` respondem na
hora, porque não há dedo para esperar.

## API

Mesmas rotas e respostas da versão Node.js:

| Método | Rota |
|---|---|
| GET | `/apiservice/capture-hash?img=true&scenario=` |
| GET | `/apiservice/capture-for-verify` |
| POST | `/apiservice/match-one-on-one?img=true`, body `{"template": "..."}` |
| GET | `/apiservice/identification?img=true` |
| POST | `/apiservice/load-to-memory`, body `[{"id": 1, "template": "..."}]` |
| GET | `/apiservice/delete-all-from-memory` |
| GET | `/apiservice/total-in-memory` |
| GET | `/apiservice/device-unique-id` |
| POST | `/apiservice/join-templates`, body `[{"template": "..."}, ...]` |
| GET | `/apiservice/mock/fingerprints` (exclusivo do simulador) |
| POST | `/apiservice/mock/fingerprints/{id}/select` (exclusivo do simulador) |

Cenários (`?scenario=`): `success`, `lowQuality`, `timeout`, `disconnected`, `sdkError`,
`captureError`, `cancelled`.

## Testes

```bat
python -m unittest discover -s tests -v
```

## Estrutura

```
main.py                     ponto de entrada (GUI ou --nogui)
hamster_sim/
  service.py                regras (antigo biometric.service.js)
  server.py                 HTTP + rotas + CORS (antigo app.js/routes/controller)
  scenarios.py              cenários (antigo mocks/scenarios.js)
  config.py                 configuração persistente (antigo .env + mocks/fingerprints.js)
  paths.py                  caminhos no código e no .exe
  gui.py                    tela Tkinter
fixtures/                   imagens das digitais
assets/                     ícone
HamsterDXSimulator.spec     build PyInstaller
build.bat / build_nuitka.bat
build_tools/                version_info.txt, installer.iss
tests/test_api.py
```
