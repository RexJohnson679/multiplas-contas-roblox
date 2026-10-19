#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Entrada da GUI; a ferramenta de console continua em multi_roblox.py."""

import argparse
import os
from pathlib import Path
import sys
import tempfile


def main(argv=None):
    parser = argparse.ArgumentParser(description="Multi Roblox — aplicativo desktop")
    parser.add_argument("--smoke-test", action="store_true", help="abre e fecha uma GUI isolada para validar o build")
    args = parser.parse_args(argv)
    if os.name != "nt" and not args.smoke_test:
        print("O aplicativo requer Windows 10/11.", file=sys.stderr)
        return 2

    from roblox_tools.gui import run_application

    if args.smoke_test:
        # Não lê preferências reais, não inicia workers nem toca a instalação do jogo.
        with tempfile.TemporaryDirectory(prefix="multi-roblox-smoke-") as directory:
            return run_application(Path(directory), smoke_test=True)
    from roblox_tools.settings import app_directory

    return run_application(app_directory())


if __name__ == "__main__":
    raise SystemExit(main())
