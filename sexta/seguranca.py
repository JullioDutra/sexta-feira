"""Acesso e bloqueio da Sexta-Feira.

- **Tokens**: todo acesso ao servidor (HUD do PC ou celular) exige um token.
  O HUD do PC recebe o token na URL aberta pela própria Sexta; o celular recebe
  um token próprio ao ser pareado por QR code. Assim, nenhum site aberto no
  navegador consegue mandar comandos para a Sexta pelas suas costas.
- **PIN**: opcional, protege desbloqueio pelo celular e ações de energia.
- **Sessão**: o bloqueio *da própria Sexta-Feira* (não é a tela de bloqueio do
  Windows). Bloqueada, ela só obedece depois de reconhecer seu rosto ou o PIN.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Cliente:
    tipo: str  # "pc" ou "celular"
    id: str
    nome: str


class ErroAcesso(Exception):
    pass


class Acesso:
    ITERACOES_PIN = 200_000

    def __init__(self, arquivo: Path):
        self.arquivo = arquivo
        self._lock = threading.RLock()
        self._dados: dict[str, Any] = {"token_pc": "", "dispositivos": [], "pin": None}
        self._pareamento: dict[str, Any] | None = None
        self._falhas_pin = 0
        self._pin_bloqueado_ate = 0.0
        if arquivo.exists():
            try:
                self._dados.update(json.loads(arquivo.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                log.warning("Arquivo de acesso inválido; recriando tokens")
        if not self._dados.get("token_pc"):
            self._dados["token_pc"] = secrets.token_urlsafe(32)
            self._salvar()

    # ------------------------------------------------------------------
    @property
    def token_pc(self) -> str:
        return self._dados["token_pc"]

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def autenticar(self, token: str | None) -> Cliente | None:
        if not token:
            return None
        with self._lock:
            if hmac.compare_digest(token, self.token_pc):
                return Cliente("pc", "pc", "Computador")
            h = self._hash(token)
            for disp in self._dados["dispositivos"]:
                if hmac.compare_digest(h, disp["hash"]):
                    agora = time.time()
                    if agora - disp.get("visto", 0) > 60:
                        disp["visto"] = agora
                        self._salvar()
                    return Cliente("celular", disp["id"], disp["nome"])
        return None

    # -- pareamento ------------------------------------------------------
    def iniciar_pareamento(self) -> dict[str, Any]:
        with self._lock:
            codigo = f"{secrets.randbelow(1_000_000):06d}"
            self._pareamento = {"codigo": codigo, "expira": time.time() + 300, "tentativas": 0}
            return {"codigo": codigo, "expira_em": 300}

    def concluir_pareamento(self, codigo: str, nome: str) -> tuple[str, Cliente]:
        with self._lock:
            p = self._pareamento
            if not p or time.time() > p["expira"]:
                raise ErroAcesso("Código expirado. Gere um novo QR code no PC.")
            p["tentativas"] += 1
            if p["tentativas"] > 5:
                self._pareamento = None
                raise ErroAcesso("Muitas tentativas. Gere um novo QR code no PC.")
            if not hmac.compare_digest(str(codigo).strip(), p["codigo"]):
                raise ErroAcesso("Código incorreto.")
            self._pareamento = None
            token = secrets.token_urlsafe(32)
            disp = {
                "id": secrets.token_hex(4),
                "nome": (nome or "Celular").strip()[:40] or "Celular",
                "hash": self._hash(token),
                "criado": time.time(),
                "visto": time.time(),
            }
            self._dados["dispositivos"].append(disp)
            self._salvar()
            log.info("Dispositivo pareado: %s", disp["nome"])
            return token, Cliente("celular", disp["id"], disp["nome"])

    def listar_dispositivos(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{k: v for k, v in d.items() if k != "hash"} for d in self._dados["dispositivos"]]

    def remover_dispositivo(self, id_: str) -> bool:
        with self._lock:
            antes = len(self._dados["dispositivos"])
            self._dados["dispositivos"] = [d for d in self._dados["dispositivos"] if d["id"] != id_]
            if len(self._dados["dispositivos"]) != antes:
                self._salvar()
                return True
            return False

    # -- PIN ---------------------------------------------------------------
    def tem_pin(self) -> bool:
        return bool(self._dados.get("pin"))

    def definir_pin(self, pin: str | None) -> None:
        with self._lock:
            if not pin:
                self._dados["pin"] = None
            else:
                pin = str(pin).strip()
                if not pin.isdigit() or not 4 <= len(pin) <= 8:
                    raise ErroAcesso("O PIN precisa ter de 4 a 8 números.")
                sal = os.urandom(16)
                h = hashlib.pbkdf2_hmac("sha256", pin.encode(), sal, self.ITERACOES_PIN)
                self._dados["pin"] = {"sal": sal.hex(), "hash": h.hex(), "iteracoes": self.ITERACOES_PIN}
            self._salvar()

    def verificar_pin(self, pin: str) -> bool:
        with self._lock:
            dados = self._dados.get("pin")
            if not dados:
                return False
            agora = time.time()
            if agora < self._pin_bloqueado_ate:
                espera = int(self._pin_bloqueado_ate - agora) + 1
                raise ErroAcesso(f"Muitas tentativas erradas. Tente de novo em {espera} segundos.")
            h = hashlib.pbkdf2_hmac("sha256", str(pin).strip().encode(), bytes.fromhex(dados["sal"]), dados["iteracoes"])
            if hmac.compare_digest(h.hex(), dados["hash"]):
                self._falhas_pin = 0
                return True
            self._falhas_pin += 1
            if self._falhas_pin >= 5:
                self._pin_bloqueado_ate = agora + 60 * 2 ** min(self._falhas_pin - 5, 5)
            return False

    def _salvar(self) -> None:
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._dados, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.arquivo)


class Sessao:
    """Estado de bloqueio da Sexta-Feira (independente do Windows)."""

    def __init__(self, prefs, barramento, rosto_cadastrado) -> None:
        self.prefs = prefs
        self.barramento = barramento
        self._rosto_cadastrado = rosto_cadastrado  # callable -> bool
        self._lock = threading.Lock()
        self.bloqueada = False
        self.motivo = ""
        self._verificado_em = 0.0

    def protecao_ativa(self) -> bool:
        return bool(self.prefs.get("bloqueio_facial")) and self._rosto_cadastrado()

    def bloquear(self, motivo: str = "manual") -> None:
        if not self.protecao_ativa():
            return
        with self._lock:
            mudou = not self.bloqueada
            self.bloqueada = True
            self.motivo = motivo
            self._verificado_em = 0.0
        if mudou:
            log.info("Sexta-Feira bloqueada (%s)", motivo)
        self.publicar()

    def desbloquear(self, metodo: str) -> None:
        with self._lock:
            mudou = self.bloqueada
            self.bloqueada = False
            self.motivo = ""
            self._verificado_em = time.time()
        if mudou:
            log.info("Sexta-Feira desbloqueada (%s)", metodo)
        self.publicar(metodo=metodo)

    def registrar_verificacao(self) -> None:
        with self._lock:
            self._verificado_em = time.time()

    def precisa_verificar(self) -> bool:
        """Verdadeiro se um comando de voz precisa de checagem facial antes."""
        if not self.protecao_ativa():
            return False
        with self._lock:
            if self.bloqueada:
                return True
            minutos = float(self.prefs.get("sessao_minutos") or 30)
            return time.time() - self._verificado_em > minutos * 60

    def estado(self) -> dict[str, Any]:
        return {
            "bloqueada": self.bloqueada and self.protecao_ativa(),
            "motivo": self.motivo,
            "protecao": self.protecao_ativa(),
        }

    def publicar(self, **extra: Any) -> None:
        self.barramento.publicar("bloqueio", **self.estado(), **extra)
