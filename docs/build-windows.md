# Compilar o aplicativo no Windows

Use Windows 10/11 com Python 3.13 de 64 bits, incluindo Tcl/Tk. PyInstaller não faz
compilação cruzada: executar o build no Linux não produz um `.exe` Windows.
Um pacote para outra arquitetura exige um Python e um ambiente compatíveis.

## 1. Atualizar e preparar

No PowerShell, na pasta do projeto:

```powershell
git pull --ff-only
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe desktop_app.py --smoke-test
```

Se o Git avisar sobre alterações locais, preserve-as antes de atualizar; não use
`reset --hard` para resolver isso. Os comandos não dependem de `Activate.ps1` e
não exigem mudar a política de execução do PowerShell.

`requirements.txt` fixa CustomTkinter e psutil. `requirements-build.txt` acrescenta
PyInstaller. Para registrar também as versões das dependências transitivas:

```powershell
New-Item -ItemType Directory -Force build | Out-Null
.\.venv\Scripts\python.exe -m pip freeze | Set-Content -Encoding utf8 build\build-environment.txt
git rev-parse HEAD
```

O commit, a versão do Python e esse arquivo ajudam a reproduzir o ambiente de
compilação. Isso não garante executáveis idênticos byte a byte entre builds.

## 2. Pacote em pasta — recomendado

```powershell
Remove-Item Env:MULTIROBLOX_ONEFILE -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean MultiplasContasRoblox.spec
```

Abra `dist\MultiplasContasRoblox\MultiplasContasRoblox.exe`. Esse build usa
`console=False`, equivalente a `--windowed`, e inclui fontes/temas do CustomTkinter
com `collect_data_files`. UPX está desativado. O diretório `_internal` contém
bibliotecas e dados necessários: distribua a **pasta completa** em ZIP.

Faça o teste do executável, aguardando sua saída:

```powershell
$app = Start-Process -FilePath '.\dist\MultiplasContasRoblox\MultiplasContasRoblox.exe' -ArgumentList '--smoke-test' -PassThru
$app.WaitForExit()
$app.ExitCode
```

O resultado esperado é `0`. Em seguida, abra a GUI normalmente e valide os três
controles com o jogo instalado. O smoke test não valida FPS real ou desempenho.

## 3. Arquivo único — opcional

```powershell
$env:MULTIROBLOX_ONEFILE = '1'
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean MultiplasContasRoblox.spec
Remove-Item Env:MULTIROBLOX_ONEFILE
```

Resultado: `dist\MultiplasContasRoblox.exe`, sem janela de console. A variável
seleciona o modo equivalente a `--onefile --windowed` no mesmo arquivo `.spec`.
Esse modo extrai bibliotecas em uma pasta temporária ao abrir, pode iniciar mais
devagar e pode receber mais alertas heurísticos que o pacote em pasta. Teste-o
novamente antes de distribuir; a CI gera e testa o pacote em pasta.

## 4. Confiança, hashes e Windows Defender

Nenhuma opção do PyInstaller garante ausência de falso positivo ou de alertas
SmartScreen. SmartScreen também considera reputação do arquivo/editor; isso não
equivale a uma análise de malware. Boas práticas de distribuição:

- Compile um commit auditado usando Python e dependências de fontes oficiais.
- Prefira o pacote em pasta; evite ofuscação, empacotadores extras e UPX.
- Publique o código, as versões usadas e o hash SHA-256 do arquivo distribuído.
- Quando disponível, assine o executável com um certificado Authenticode válido
  e carimbo de tempo. Assinatura identifica o editor, sem garantir reputação.
- Se um arquivo legítimo for detectado, envie a amostra pelo
  [portal oficial de análise da Microsoft](https://www.microsoft.com/en-us/wdsi/filesubmission).
  Não desative o Defender nem crie exclusões como solução de distribuição.

Para empacotar e calcular o hash do ZIP:

```powershell
Compress-Archive -Path .\dist\MultiplasContasRoblox -DestinationPath .\dist\MultiplasContasRoblox-Windows.zip -Force
Get-FileHash .\dist\MultiplasContasRoblox-Windows.zip -Algorithm SHA256
```

Para um executável assinado, calcule o hash **depois** da assinatura. Um hash
permite comparar arquivos; sozinho não prova que um programa seja seguro.

## 5. Build no GitHub Actions

O workflow **Build Windows** usa uma máquina Windows, instala as dependências,
executa os testes, gera o pacote em pasta e abre o executável com `--smoke-test`.
Ao terminar com sucesso, publica um artefato com os arquivos, hashes e versões.

No repositório, abra **Actions → Build Windows → execução concluída → Artifacts**
e baixe `MultiplasContasRoblox-Windows`. É possível que seja necessário entrar no
GitHub para baixar artefatos. Esse fluxo não cria automaticamente uma Release nem
assina o executável. A presença do workflow não comprova que uma execução passou.

## Verificação manual com dois clientes

1. Feche o console antigo e todos os clientes; ative Multi-instância na GUI.
2. Abra duas contas em sessões separadas de navegador e confira ambas no jogo.
3. Ative o otimizador. No Gerenciador de Tarefas → Detalhes, confira Normal no
   cliente em foco e Baixa no outro; troque o foco para conferir a inversão.
   Ao focar o Gerenciador de Tarefas, ambos podem aparecer como Baixa.
4. Desative o otimizador e confira a restauração das prioridades anteriores.
5. Feche os clientes, ative FPS e confira a chave no JSON. Abra novamente o jogo
   e confira o FPS pelo próprio cliente, se a versão aceitar o ajuste local.
6. Desative FPS e confira a restauração da chave e a preservação das demais opções.
7. Feche e reabra a GUI para conferir as preferências salvas. Fechar normalmente
   restaura os efeitos; as opções escolhidas são reaplicadas na próxima abertura.
