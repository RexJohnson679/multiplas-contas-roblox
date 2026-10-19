# Executável único, sem console

O build padrão gera **`dist\MultiplasContasRoblox.exe`**. Abra esse arquivo com dois
cliques: aparece apenas a interface gráfica. Não é preciso manter PowerShell ou
Python abertos, nem instalar Python na máquina em que o `.exe` será usado.

Compile no Windows 10/11 com Python de 64 bits, incluindo Tcl/Tk. A CI usa Python
3.13, mas os comandos abaixo usam `py -3`, sem exigir essa versão específica.
PyInstaller não faz compilação cruzada: build no Linux não gera `.exe` Windows.

## Atualizar e compilar agora

No PowerShell, na pasta do projeto:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean MultiplasContasRoblox.spec
Start-Process .\dist\MultiplasContasRoblox.exe
```

Se ainda não existir uma `.venv`, crie-a antes da instalação:

```powershell
py -3 -m venv .venv
```

Após compilar, você pode fechar o PowerShell e iniciar o aplicativo pelo Explorador
de Arquivos. O arquivo de saída fica diretamente em `dist`, não na subpasta do
build antigo. Feche a versão antiga antes de testar a nova.

## O que o `.spec` configura

- Empacotamento equivalente a **`--onefile`**: binários e dados fazem parte de `EXE`;
  não existe uma etapa `COLLECT` que exija distribuir uma pasta `_internal`.
- **`console=False`**, equivalente a **`--noconsole` / `--windowed`**: usa o
  subsistema gráfico do Windows e abre somente a GUI.
- Fontes, temas e arquivos necessários do CustomTkinter incluídos no pacote.
- Licenças da aplicação e das dependências incorporadas ao executável.
- UPX desativado e código sem ofuscação.

Ao fornecer o `.spec`, use o comando acima: as opções de empacotamento já estão
salvas nele; não acrescente `--onefile` ou `--noconsole` ao comando com `.spec`.
Não é necessário definir `MULTIROBLOX_ONEFILE` ou qualquer outra variável.

O executável pode levar alguns segundos na primeira abertura, pois o modo
`onefile` extrai dependências para uma pasta temporária. Essa pasta é gerenciada
pelo PyInstaller; não precisa acompanhar o arquivo distribuído. As preferências
continuam em `%LOCALAPPDATA%\MultiplasContasRoblox`, fora dessa pasta temporária.

## Testar o build

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
$app = Start-Process -FilePath '.\dist\MultiplasContasRoblox.exe' -ArgumentList '--smoke-test' -PassThru
$app.WaitForExit()
$app.ExitCode
```

O smoke test abre e fecha uma GUI isolada. O resultado esperado é `0`; o processo
Windows empacotado também verifica que não está ligado a uma janela de console.
Esse teste não ativa recursos nem altera a instalação do jogo.

Para testar o uso normal:

1. Feche o console antigo, a GUI anterior e os clientes Roblox.
2. Abra `dist\MultiplasContasRoblox.exe` com dois cliques.
3. Feche o PowerShell e confira que a GUI continua funcionando.
4. Ative Multi-instância e só então abra suas contas no jogo.
5. Confira Anti-lag e FPS como descrito no README. Compatibilidade e ganho de
   desempenho dependem do cliente e da máquina.
6. Feche a GUI normalmente para restaurar os efeitos e salvar as preferências.

Executar `python desktop_app.py` continua sendo um modo de desenvolvimento ligado
ao terminal. Use o `.exe` compilado para o comportamento independente do console.

## Build automático

Em **Actions → Build Windows**, o GitHub executa testes, gera esse mesmo arquivo
único, verifica o subsistema Windows GUI no cabeçalho PE e executa o smoke test.
Uma execução concluída com sucesso disponibiliza `MultiplasContasRoblox-Windows`
em **Artifacts**, com o `.exe`, hash SHA-256 e versões das dependências. Pode ser
necessário entrar no GitHub para baixar artefatos. Não é criada uma Release nem
uma assinatura automaticamente; confira o resultado da execução.

## Hashes, assinatura e falsos positivos

```powershell
Get-FileHash .\dist\MultiplasContasRoblox.exe -Algorithm SHA256
```

Registre também `git rev-parse HEAD`, a versão do Python e `pip freeze` ao publicar
um build. Isso ajuda a reproduzir o ambiente, sem garantir arquivos idênticos byte
a byte. Um hash compara arquivos; sozinho não comprova segurança.

PyInstaller e `onefile` podem receber alertas heurísticos. Nenhuma opção garante
que Defender ou SmartScreen deixarão de alertar. Use dependências oficiais, evite
empacotadores extras/ofuscação e publique o código e os hashes. Quando disponível,
assine com um certificado Authenticode válido e carimbo de tempo; calcule o hash
depois de assinar. Em caso de falso positivo, envie a amostra ao
[portal oficial da Microsoft](https://www.microsoft.com/en-us/wdsi/filesubmission).
Não desative o Defender nem use exclusões como solução de distribuição.
