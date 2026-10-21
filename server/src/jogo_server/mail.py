"""Plain-text pt-BR email over SMTP with STARTTLS, sent from a thread: a reply never waits on the relay, nor
tells by its timing whether an address has an account."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

log = logging.getLogger("jogo.mail")


def link_message(base: str, token: str) -> tuple[str, str]:
    return (
        "Jogo de Carro: defina sua senha",
        "Olá!\n\n"
        "Recebemos um pedido para entrar no Jogo de Carro com este e-mail. Para definir sua senha,\n"
        "abra o link abaixo. Ele vale por 1 hora e só pode ser usado uma vez.\n\n"
        f"{base}/senha?t={token}\n\n"
        "Se não foi você, ignore este e-mail: nada muda.\n",
    )


def send(cfg: Any, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg.mail_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
            if not cfg.dev:  # a local debug sink speaks plain SMTP; a real relay never does
                smtp.starttls(context=ssl.create_default_context())
            if cfg.smtp_user:
                smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(msg)
    except Exception as e:  # logged without the address or the link
        log.error("e-mail não enviado: %s %s", type(e).__name__, getattr(e, "smtp_code", ""))
