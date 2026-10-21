"""pt-BR email (plain text plus an HTML copy) over SMTP with STARTTLS, sent from a thread: a reply never waits
on the relay, nor tells by its timing whether an address has an account."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

import jinja2

log = logging.getLogger("jogo.mail")
templates = jinja2.Environment(loader=jinja2.PackageLoader("jogo_server"), autoescape=True)
# The HTML's "Definir senha" button is a link; the address under it is text. Set False for no link at all in
# the HTML (the relay's click tracking then has nothing to rewrite there): the address replaces the button.
LINKS = True


def link_message(base: str, token: str) -> EmailMessage:
    link = f"{base}/senha?t={token}"
    msg = EmailMessage()
    msg["Subject"] = "Jogo de Carro: defina sua senha"
    msg.set_content(  # the source of truth: the HTML says the same, with the same link
        "Olá!\n\n"
        "Recebemos um pedido para entrar no Jogo de Carro com este e-mail. Para definir sua senha,\n"
        "abra o link abaixo. Ele vale por 1 hora e só pode ser usado uma vez.\n\n"
        f"{link}\n\n"
        "Se não foi você, ignore este e-mail: nada muda.\n"
    )
    html = templates.get_template("email_link.html").render(base=base, link=link, links=LINKS)
    msg.add_alternative(html, subtype="html")
    return msg


def review_message(base: str, n: int) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Jogo de Carro: {n} corrida(s) em análise"
    msg.set_content(
        f"{n} corrida(s) aguardam revisão em {base}.\n\n"
        "No servidor: jogo-admin revisar\n"
        "Este aviso se repete a cada hora enquanto houver corridas em análise.\n"
    )
    return msg


def send(cfg: Any, to: str, msg: EmailMessage) -> None:
    msg["From"], msg["To"] = cfg.mail_from, to
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
            if not cfg.dev:  # a local debug sink speaks plain SMTP; a real relay never does
                smtp.starttls(context=ssl.create_default_context())
            if cfg.smtp_user:
                smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(msg)
    except Exception as e:  # logged without the address or the link
        log.error("e-mail não enviado: %s %s", type(e).__name__, getattr(e, "smtp_code", ""))
