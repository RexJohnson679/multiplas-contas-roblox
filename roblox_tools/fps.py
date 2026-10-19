"""Ajuste reversível de um único FastFlag, com diário persistente de restauração."""

from pathlib import Path

from .settings import FPS_CHOICES, read_object, write_object

FPS_KEY = "DFIntTaskSchedulerTargetFps"


class FpsSettingsError(RuntimeError):
    pass


class FpsSettingsManager:
    def __init__(self, versions_directory, state_directory):
        self.versions = Path(versions_directory).resolve()
        self.journal = Path(state_directory) / "fps-backup.json"

    def _read_journal(self):
        if not self.journal.exists():
            return {}
        data = read_object(self.journal)
        if data.get("schema") != 1 or not isinstance(data.get("files"), dict):
            raise FpsSettingsError("Diário de FPS inválido; nenhuma configuração foi alterada.")
        records = data["files"]
        for name, record in records.items():
            path = Path(name)
            try:
                relative = path.resolve().relative_to(self.versions)
            except ValueError as error:
                raise FpsSettingsError("Caminho fora da instalação no diário de FPS.") from error
            if (
                len(relative.parts) != 3
                or not relative.parts[0].startswith("version-")
                or relative.parts[1:] != ("ClientSettings", "ClientAppSettings.json")
                or not isinstance(record, dict)
                or type(record.get("present")) is not bool
                or type(record.get("created_file")) is not bool
                or type(record.get("written")) is not int
                or record["written"] not in FPS_CHOICES
                or (record["present"] and "original" not in record)
            ):
                raise FpsSettingsError("Registro inválido no diário de FPS.")
        return records

    def _save_journal(self, records):
        # Mesmo um diário vazio é gravado atomicamente: seguro após encerramento abrupto.
        write_object(self.journal, {"schema": 1, "files": records})

    def targets(self):
        return sorted(
            directory / "ClientSettings" / "ClientAppSettings.json"
            for directory in self.versions.glob("version-*")
            if directory.is_dir() and (directory / "RobloxPlayerBeta.exe").is_file()
            and directory.resolve().parent == self.versions
            and not (directory / "ClientSettings").is_symlink()
        )

    def apply(self, limit):
        if type(limit) is not int or limit not in FPS_CHOICES:
            raise ValueError("Limite de FPS inválido.")
        records = self._read_journal()
        targets = self.targets()
        if not targets:
            raise FpsSettingsError("Cliente desktop não encontrado em Roblox/Versions.")
        changed = 0
        for path in targets:
            # Resolve também junctions/reparse points, além de links simbólicos.
            try:
                relative = path.resolve().relative_to(self.versions)
            except ValueError as error:
                raise FpsSettingsError("A pasta de configurações aponta para fora da instalação.") from error
            if len(relative.parts) != 3 or relative.parts[1:] != ("ClientSettings", "ClientAppSettings.json"):
                raise FpsSettingsError("Caminho de configurações inesperado; edição recusada.")
            if path.is_symlink():
                raise FpsSettingsError("ClientAppSettings.json é um link; edição recusada.")
            name = str(path)
            if name in records:
                continue
            existed = path.exists()
            document = read_object(path) if existed else {}
            records[name] = {
                "present": FPS_KEY in document,
                "original": document.get(FPS_KEY),
                "created_file": not existed,
                "written": limit,
            }
            # Persiste a informação de recuperação ANTES de alterar o cliente.
            self._save_journal(records)
            document[FPS_KEY] = limit
            write_object(path, document)
            changed += 1
        return changed

    def restore(self):
        records = self._read_journal()
        errors = []
        preserved = 0
        for name, record in list(records.items()):
            path = Path(name)
            try:
                if path.is_symlink():
                    raise FpsSettingsError("Arquivo tornou-se um link; restauração recusada.")
                if path.exists():
                    document = read_object(path)
                    # Se outro programa/usuário mudou o valor, sua escolha prevalece.
                    if document.get(FPS_KEY) == record["written"]:
                        if record["present"]:
                            document[FPS_KEY] = record["original"]
                        else:
                            document.pop(FPS_KEY, None)
                        if record["created_file"] and not document:
                            path.unlink()
                        else:
                            write_object(path, document)
                    else:
                        preserved += 1
                del records[name]
            except (OSError, ValueError, FpsSettingsError) as error:
                errors.append(f"{path.parent.parent.name}: {error}")
        self._save_journal(records)
        if errors:
            raise FpsSettingsError("Restauração de FPS pendente: " + "; ".join(errors))
        return preserved

    def run(self, stop, report, limit=240, recover_only=False):
        self.restore()  # Recupera uma execução anterior interrompida.
        if recover_only:
            report("info", "Configuração anterior de FPS restaurada.")
            return
        try:
            changed = self.apply(limit)
            report("ready", f"Limite solicitado: {limit} FPS. Reinicie os clientes para testar.")
            report("status", f"{changed} instalação(ões) configurada(s) · efeito depende do Roblox")
            while not stop.wait(5):
                changed = self.apply(limit)
                if changed:
                    report("info", "Nova instalação detectada; FPS configurado para a próxima abertura.")
        finally:
            preserved = self.restore()
            if preserved:
                report("warning", "Valores de FPS alterados por outro programa foram preservados.")
