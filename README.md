# Múltiplas contas Roblox — objetos nomeados do Windows

Utilitário de console em Python, com licença MIT e sem dependências externas.
Cria e retém o evento `ROBLOX_SINGLE_INSTANCE` e, opcionalmente, o mutex
`ROBLOX_singletonMutex`. O código é legível e usa somente a biblioteca padrão.

**Compatibilidade experimental:** criar esse evento não comprova que o Roblox
atual o utiliza nem que permitirá várias instâncias. A implementação consultada
do ic3w0lf22 usa `ROBLOX_singletonMutex`, e não `ROBLOX_SINGLE_INSTANCE`.
O parâmetro `--legacy-mutex` disponibiliza essa abordagem separadamente.
Não foi realizado um teste com o jogo real neste ambiente Linux.

## Instalação e execução

1. Use Windows 10/11, o cliente desktop do Roblox e Python 3.10 ou superior.
   Instale o Python pelo [site oficial](https://www.python.org/downloads/windows/),
   incluindo o launcher `py`. Não é necessário instalar pacotes com `pip`.
2. Baixe este repositório e extraia o ZIP, ou clone-o com Git:

   ```powershell
   git clone https://github.com/RexJohnson679/multiplas-contas-roblox.git
   cd multiplas-contas-roblox
   ```

3. Feche normalmente todos os clientes Roblox e outras ferramentas de múltiplas
   instâncias. No PowerShell, entre na pasta extraída, se usou o ZIP.
4. Confira o Python e inicie a ferramenta **antes** de abrir o jogo:

   ```powershell
   py -3 --version
   py -3 multi_roblox.py
   ```

   Para criar também o mutex usado pela referência consultada, encerre a
   ferramenta com `Ctrl+C` e execute:

   ```powershell
   py -3 multi_roblox.py --legacy-mutex
   ```

   Use a mesma conta do Windows, sessão e nível de elevação do jogo, normalmente
   sem executar como administrador. Não execute os dois comandos simultaneamente.
   Se `py` não existir, use `python` após conferir sua versão.
5. Aguarde a mensagem `Evento retido` e mantenha esse terminal aberto.
6. Entre na primeira conta pelo site oficial do Roblox e abra uma experiência.
   Para a segunda conta, use outro perfil de navegador, outro navegador ou uma
   janela anônima e abra a experiência novamente. Abas comuns compartilham cookies;
   várias janelas anônimas do mesmo navegador também podem compartilhar uma sessão.
   Repita usando sessões de navegação separadas e contas que você controla.
7. Verifique que a primeira janela continua aberta e que cada cliente está na
   conta pretendida. Se uma janela fechar, a técnica não está funcionando nessa
   versão/configuração. Não há garantia de compatibilidade com todas as versões,
   com o aplicativo da Microsoft Store ou com atualizações futuras.
8. Ao terminar, feche os clientes e pressione `Ctrl+C` no terminal da ferramenta.
   `Ctrl+Break` também pede encerramento limpo. Fechar a janela à força faz o Windows
   fechar os handles do processo, mas pode deixar o mutex em estado abandonado.

## Funcionamento técnico

Um **evento** é um objeto de sincronização com estado sinalizado/não sinalizado;
não tem proprietário. Um **mutex** tem propriedade por thread e permite exclusão
mútua. Ambos podem ter nomes compartilhados entre processos, mas não são
intercambiáveis: usar o mesmo nome para tipos diferentes provoca erro Win32 6.

`CreateEventW(NULL, TRUE, FALSE, L"ROBLOX_SINGLE_INSTANCE")` cria um evento de reset
manual, inicialmente não sinalizado. A ferramenta mantém o handle aberto e não
chama `SetEvent` nem `ResetEvent`. Isso mantém o objeto existente, sem impedir que
outro processo autorizado abra ou sinalize o evento. **Reter um evento não equivale
a bloqueá-lo**, e sua simples existência pode até fazer um aplicativo recusar uma
segunda instância, dependendo da lógica desse aplicativo.

Com `--legacy-mutex`, `CreateMutexW(NULL, TRUE, L"ROBLOX_singletonMutex")` cria também
um mutex cuja propriedade é mantida pela thread principal. A referência comunitária
pré-cria e adquire esse mutex antes do jogo. O efeito sobre o cliente depende de
como ele trata esse objeto; o Windows não oferece uma função genérica para
"liberar múltiplas instâncias" de qualquer aplicativo.

As funções vêm de `kernel32.dll`, carregada com `ctypes.WinDLL(...,
use_last_error=True)`. As assinaturas usam `HANDLE` do tamanho de um ponteiro,
compatível com processos Python de 32 e 64 bits. `ctypes.get_last_error()` captura
o diagnóstico imediatamente após a criação.

Se o objeto já existir, as funções podem retornar um handle válido e o erro 183
(`ERROR_ALREADY_EXISTS`); nesse caso a ferramenta fecha sua referência e encerra,
pois não pode assegurar a configuração original ou a propriedade do mutex.
Quando um handle não pode ser criado, ela informa o código Win32 e sai com falha.
Uma falha posterior também libera os objetos criados anteriormente.

O atributo de segurança `NULL` usa a ACL padrão derivada do token do usuário e
torna os handles não herdáveis. Não há DACL nula que conceda acesso irrestrito,
alteração de permissões do sistema ou solicitação automática de administrador.
Os nomes sem `Global\` usam o namespace da sessão interativa; não se pretende
compartilhar objetos entre usuários ou sessões diferentes do Windows.

O loop usa `time.sleep(1)`, sem espera ocupada. Ao receber `Ctrl+C`, os contextos
liberam a propriedade do mutex na mesma thread e executam `CloseHandle` em ordem
inversa. Um objeto só é destruído depois que **todos** os processos fecharem seus
handles; sair da ferramenta não fecha handles pertencentes ao Roblox.

## Diagnóstico

| Resultado | Ação |
| --- | --- |
| Win32 183: já existe | Feche clientes e outras cópias da ferramenta e tente novamente. Não se tenta assumir um objeto existente. |
| Win32 5: acesso negado | Confira usuário, sessão e nível de elevação. Não desative proteções do Windows. |
| Win32 6: handle inválido na criação | Pode haver objeto de outro tipo com o mesmo nome; feche a ferramenta que o criou. |
| Handles criados, mas uma janela do jogo fecha | A API funcionou; a compatibilidade com esse cliente não está demonstrada. |
| Mensagem de Windows obrigatório | Execute no Windows; Linux, macOS e Wine não são alvos suportados. |

Saídas: `0` após encerramento manual limpo, `1` em falhas nativas ou objeto
preexistente, `2` em plataforma incompatível ou argumentos inválidos.

## Auditoria e testes

O utilitário não faz requisições de rede, lê cookies, pede senhas, captura tokens,
enumera processos, abre a memória do jogo ou altera arquivos do Roblox.
O interpretador Python precisa ler o próprio script; essa transparência refere-se
ao comportamento do utilitário, não ao navegador ou ao cliente oficial.

Execute os testes sem instalar dependências:

```powershell
py -3 -m unittest discover -s tests -v
```

Os testes de integração usam nomes aleatórios, nunca os objetos reais do Roblox.
No Windows verificam criação, retenção, estado do evento, propriedade do mutex e
liberação usando o kernel real. Em Linux/macOS esses testes são explicitamente
ignorados; apenas os testes com API simulada podem ser executados. O workflow
do GitHub Actions inclui Windows e Linux; sua inclusão não significa que já rodou.
Nenhum desses testes comprova compatibilidade com o jogo; faça a validação manual
dos passos 5–7, e novamente após atualizações do cliente.

## Aviso de uso e licença

Esta ferramenta não injeta DLLs ou código, não modifica o executável nem arquivos
do Roblox e não implementa exploits de jogabilidade. **Isso não garante ausência
de banimentos, detecção, restrições de conta ou sanções.** A Roblox e cada
experiência definem e podem alterar suas regras sobre múltiplas contas e clientes.
Consulte os termos vigentes e use apenas onde permitido. Não há afiliação com a
Roblox Corporation. O software é fornecido sem garantias, sob a [licença MIT](LICENSE).

## Referências

- [ic3w0lf22: criação e aquisição de ROBLOX_singletonMutex, revisão consultada](https://github.com/ic3w0lf22/Roblox-Account-Manager/blob/c2b13d146d5db609d499870145e8d2dff2506581/RBX%20Alt%20Manager/AccountManager.cs#L1254-L1273).
- [Microsoft: CreateEventW](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createeventw).
- [Microsoft: CreateMutexW](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createmutexw).
- [Microsoft: CloseHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-closehandle).

Implementação independente: a referência comunitária informa o método histórico,
sem comprovar o comportamento de versões atuais do cliente.
