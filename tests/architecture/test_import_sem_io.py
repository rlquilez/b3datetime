"""Invariante "nada faz I/O no import", provada por audit hook — não por cronômetro.

O ``import b3datetime.main`` roda num subprocesso com ``sys.addaudithook`` instalado antes,
num diretório de trabalho temporário que tem um ``.env`` plantado. O hook registra cada
evento de auditoria do interpretador; o teste reprova se houver:

* qualquer atividade de rede (``socket.*``) — o import conectava no Redis;
* qualquer subprocesso;
* qualquer arquivo aberto no diretório de trabalho — é onde mora o ``.env``, que o
  pydantic-settings lia no import quando havia ``Settings()`` em nível de módulo.

Abrir módulos Python e o tzdata (o ``exchange_calendars`` carrega os fusos das bolsas) é
esperado e não conta. O teste de integração ``test_import_nao_faz_io`` complementa este
com a prova comportamental (Redis numa porta fechada).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

SONDA = textwrap.dedent("""
    import json, os, sys
    eventos = []
    def hook(evento, args):
        if evento.startswith("socket.") or evento in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"):
            eventos.append([evento, repr(args[:2])])
        elif evento == "open" and isinstance(args[0], (str, bytes)):
            caminho = os.path.abspath(os.fsdecode(args[0]))
            if caminho.startswith(os.getcwd() + os.sep):
                eventos.append([evento, caminho])
    sys.addaudithook(hook)
    import b3datetime.main  # noqa: F401
    print(json.dumps(eventos))
""")


def test_importar_a_app_nao_abre_socket_subprocesso_nem_le_o_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TIMEZONE=Fuso/Inexistente\nREDIS_URL_ENV=redis://10.0.0.1:1\n")
    proc = subprocess.run(  # noqa: S603 - comando fixo, sem entrada externa
        [sys.executable, "-c", SONDA],
        cwd=tmp_path,
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    eventos = json.loads(proc.stdout.strip().splitlines()[-1])
    assert eventos == [], f"o import fez I/O proibido: {eventos}"
