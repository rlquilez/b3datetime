"""O Agentic Mermaid (``am verify``) sobre cada diagrama, por canal local.

Reprova em todo erro de nível 1 (``RENDER_FAILED``, ``GROUP_BREACH``, ``OFF_CANVAS``…) e em
todo aviso fora de :data:`tests.docs.agentic.TOLERADOS` — inclusive ``LABEL_OVERFLOW`` e
``LOW_CONTRAST``. Exige também um layout não vazio: um diagrama que o ``am`` não consegue
modelar "passa" no ``verify`` sem verificar nada (era o que acontecia com markdown strings).
"""

from __future__ import annotations

import pytest

from tests.docs.agentic import AM, avisos_relevantes, verificar
from tests.docs.diagramas import Diagrama, diagramas

pytestmark = pytest.mark.diagramas

TODOS = diagramas()


@pytest.mark.parametrize("diagrama", TODOS, ids=[d.id for d in TODOS])
def test_agentic_mermaid_verify(diagrama: Diagrama) -> None:
    assert AM.is_file(), "rode `npm ci` em tests/docs (o Agentic Mermaid)"
    resultado = verificar(diagrama.fonte)
    assert resultado["ok"], resultado["warnings"]
    assert not avisos_relevantes(resultado)
    assert resultado["layout"]["nodes"], "o am não modelou nenhum nó do diagrama"
