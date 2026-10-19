"""Preferências locais e gravação atômica de JSON, sem credenciais."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
import uuid

FPS_CHOICES = (60, 120, 144, 165, 240, 360)


def app_directory():
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise OSError("LOCALAPPDATA não está disponível nesta sessão do Windows.")
    return Path(base) / "MultiplasContasRoblox"


def read_object(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{Path(path).name} deve conter um objeto JSON.")
    return value


def write_object(path, value):
    """Substitui o arquivo só após gravar o JSON inteiro na mesma pasta."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass
class AppConfig:
    multi_instance: bool = False
    optimizer: bool = False
    fps_unlock: bool = False
    fps_limit: int = 240


class SettingsStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "config.json"
        self.warning = ""

    def load(self):
        if not self.path.exists():
            return AppConfig()
        try:
            data = read_object(self.path)
            config = AppConfig()
            for name in ("multi_instance", "optimizer", "fps_unlock"):
                value = data.get(name, False)
                if type(value) is not bool:
                    raise ValueError(f"{name} deve ser booleano.")
                setattr(config, name, value)
            limit = data.get("fps_limit", 240)
            if type(limit) is not int or limit not in FPS_CHOICES:
                raise ValueError("Limite de FPS inválido.")
            config.fps_limit = limit
            return config
        except (ValueError, UnicodeError) as error:
            # Preserva o arquivo defeituoso antes de permitir novas gravações.
            backup = self.path.with_name(f"config.invalid-{uuid.uuid4().hex[:8]}.json")
            self.path.replace(backup)
            self.warning = f"Configuração inválida; cópia preservada em {backup.name}: {error}"
            return AppConfig()

    def save(self, config):
        write_object(self.path, asdict(config))
