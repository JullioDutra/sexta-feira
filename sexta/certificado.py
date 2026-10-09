"""Certificado HTTPS autoassinado para o acesso pelo celular.

O navegador do celular só libera o microfone em páginas HTTPS. Na primeira vez
ele mostra um aviso ("conexão não é particular"): toque em Avançado → Continuar.
Para HTTPS sem aviso e acesso fora de casa, use o Tailscale (ver README).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def garantir_certificado(pasta: Path, ips: list[str], nomes: list[str]) -> tuple[Path, Path]:
    """Cria (ou recria, se os IPs mudaram) o par certificado/chave."""
    pasta.mkdir(parents=True, exist_ok=True)
    cert_path, key_path, meta_path = pasta / "sexta.crt", pasta / "sexta.key", pasta / "sans.json"
    sans = sorted(set(ips + ["127.0.0.1"])), sorted(set(nomes + ["localhost"]))
    if cert_path.exists() and key_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if set(sans[0]) <= set(meta.get("ips", [])) and set(sans[1]) <= set(meta.get("nomes", [])):
                expira = dt.datetime.fromisoformat(meta["expira"])
                if expira - dt.datetime.now(dt.timezone.utc) > dt.timedelta(days=30):
                    return cert_path, key_path
        except (ValueError, KeyError, json.JSONDecodeError):
            pass

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    chave = ec.generate_private_key(ec.SECP256R1())
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Sexta-Feira"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Sexta-Feira (local)")])
    agora = dt.datetime.now(dt.timezone.utc)
    alternativos: list[x509.GeneralName] = [x509.DNSName(n) for n in sans[1]]
    for ip in sans[0]:
        try:
            alternativos.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue
    expira = agora + dt.timedelta(days=825)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - dt.timedelta(minutes=5))
        .not_valid_after(expira)
        .add_extension(x509.SubjectAlternativeName(alternativos), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(chave, hashes.SHA256())
    )
    key_path.write_bytes(chave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    meta_path.write_text(json.dumps({"ips": sans[0], "nomes": sans[1], "expira": expira.isoformat()}), encoding="utf-8")
    log.info("Certificado HTTPS gerado para %s", ", ".join(sans[0] + sans[1]))
    return cert_path, key_path
