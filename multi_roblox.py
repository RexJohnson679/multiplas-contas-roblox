#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Retém objetos nomeados do Windows; não acessa o processo do Roblox."""

import argparse
from contextlib import ExitStack, contextmanager
import ctypes
from ctypes import wintypes
import os
import signal
import sys
import time

EVENT_NAME = "ROBLOX_SINGLE_INSTANCE"
LEGACY_MUTEX_NAME = "ROBLOX_singletonMutex"
ERROR_ALREADY_EXISTS = 183


class ToolError(RuntimeError):
    """Falha de preparação ou de liberação de um objeto nativo."""


def load_kernel32():
    # use_last_error mantém uma cópia do erro Win32 na thread do Python.
    api = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    # HANDLE tem tamanho de ponteiro: restype evita truncamento em 64 bits.
    api.CreateEventW.argtypes = [
        wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR
    ]
    api.CreateEventW.restype = wintypes.HANDLE
    api.CreateMutexW.argtypes = [
        wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR
    ]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.ReleaseMutex.argtypes = [wintypes.HANDLE]
    api.ReleaseMutex.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


def native_error(operation, name, code):
    detail = ctypes.FormatError(code).strip()
    if code == 5:
        detail += " Execute a ferramenta e o jogo com o mesmo usuário e nível de elevação."
    elif code == 6:
        detail += " Pode existir um objeto de outro tipo com esse nome."
    return ToolError(f"{operation} em {name!r}: Win32 {code}: {detail}")


@contextmanager
def hold_object(api, kind, name):
    """Cria um objeto novo e mantém seu handle; recusa objetos preexistentes."""
    if kind not in ("event", "mutex"):
        raise ValueError("Tipo de objeto inválido.")

    # Limpa erro residual antes da chamada que cria ou abre o objeto nomeado.
    ctypes.set_last_error(0)
    if kind == "event":
        # NULL: ACL padrão do usuário e handle não herdável.
        # TRUE/FALSE: evento de reset manual, inicialmente não sinalizado.
        handle = api.CreateEventW(None, True, False, name)
        operation = "CreateEventW"
    else:
        # TRUE: a thread atual torna-se proprietária SOMENTE se criar o mutex.
        handle = api.CreateMutexW(None, True, name)
        operation = "CreateMutexW"
    # Captura o erro imediatamente, antes de outras chamadas nativas.
    code = ctypes.get_last_error()
    if not handle:
        raise native_error(operation, name, code)

    try:
        if code == ERROR_ALREADY_EXISTS:
            raise ToolError(
                f"{name!r} já existe (Win32 183). Feche os clientes Roblox e "
                "outras ferramentas de múltiplas instâncias e tente novamente. "
                "O estado e a origem do objeto existente não foram alterados."
            )
        yield handle
    finally:
        errors = []
        # ReleaseMutex exige a mesma thread que adquiriu a propriedade.
        # Um mutex preexistente não foi adquirido por esta ferramenta.
        if kind == "mutex" and code != ERROR_ALREADY_EXISTS:
            if not api.ReleaseMutex(handle):
                errors.append(str(native_error("ReleaseMutex", name, ctypes.get_last_error())))
        # Fecha apenas NOSSO handle, inclusive se a criação seguinte falhar.
        if not api.CloseHandle(handle):
            errors.append(str(native_error("CloseHandle", name, ctypes.get_last_error())))
        if errors:
            raise ToolError("; ".join(errors))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Retém ROBLOX_SINGLE_INSTANCE usando a API do Windows."
    )
    parser.add_argument(
        "--legacy-mutex", action="store_true",
        help="também cria e mantém a propriedade de ROBLOX_singletonMutex",
    )
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("Este utilitário requer Windows 10/11 e Python 3.10+.", file=sys.stderr)
        return 2

    # Ctrl+Break, assim como Ctrl+C, pede saída pela thread principal.
    signal.signal(signal.SIGBREAK, signal.default_int_handler)
    try:
        api = load_kernel32()
        with ExitStack() as stack:
            stack.enter_context(hold_object(api, "event", EVENT_NAME))
            if args.legacy_mutex:
                stack.enter_context(hold_object(api, "mutex", LEGACY_MUTEX_NAME))
            print(f"Evento retido: {EVENT_NAME}", flush=True)
            if args.legacy_mutex:
                print(f"Mutex adquirido: {LEGACY_MUTEX_NAME}", flush=True)
            print("Compatibilidade com o cliente Roblox não verificada.", flush=True)
            print("Abra o jogo agora. Mantenha este terminal aberto; Ctrl+C para sair.", flush=True)
            # Dormir evita espera ocupada; referências e handles permanecem vivos.
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrado; handles locais liberados.")
        return 0
    except (ToolError, OSError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
