"""Revisão das corridas (plano §6.7). Uso: python -m jogo_server.admin <comando> (no VPS: jogo-admin ...)

    revisar             as corridas em análise, da mais antiga à mais nova
    aprovar <corrida>   entra no ranking
    rejeitar <corrida>  sai do ranking (em análise ou já aprovada); de uma partida, anula a partida
    banir <apelido>     sai de todas as sessões e do ranking; as corridas em análise são rejeitadas e
                        os desafios dele em aberto, anulados
    export <corrida>    o log de entradas (v1), para: python -m jogo_de_carro --replay run.json

O banco é $JOGO_DB (/var/lib/jogo/jogo.db). Banido, o jogo aberto cai na próxima corrida que tentar começar.
"""

import json
import os
import sys
import zlib

from . import auth, db


def main(args: list[str]) -> int:
    conn = db.connect(os.environ.get("JOGO_DB") or "/var/lib/jogo/jogo.db")
    match args:
        case ["revisar"]:
            sql = "SELECT runs.*, nick FROM runs JOIN users ON users.id = user_id WHERE state = 'review'"
            rows = conn.execute(sql + " ORDER BY runs.id").fetchall()
            for r in rows:
                f = json.loads(r["features"])
                print(
                    f"{r['id']:>7} {r['nick']:<16} {r['mode']:<8} {r['score']:>7} pts {r['seconds']:6.1f} s"
                    f"  {r['why']:<5} max_lag {r['max_lag']:.2f}  reações {f['n']} p10 {f['p10']}"
                    f" mediana {f['median']}  corredor {f['adherence']:.3f}  boost {f['boost']:.2f}"
                    f"  lag_up {f['lag_up']}"
                )
            print(f"{len(rows)} em análise")
        case ["aprovar", run] if run.isdigit():
            sql = "UPDATE runs SET state = 'ok' WHERE id = ? AND state = 'review'"
            done = conn.execute(sql, (int(run),)).rowcount
            print(f"corrida {run}: " + ("aprovada" if done else "não está em análise"))
            return 0 if done else 1
        case ["rejeitar", run] if run.isdigit():
            sql = "UPDATE runs SET state = 'rejected' WHERE id = ? AND state IN ('review', 'ok')"
            done = conn.execute(sql, (int(run),)).rowcount
            print(f"corrida {run}: " + ("rejeitada" if done else "não está em análise nem no ranking"))
            return 0 if done else 1
        case ["banir", nick]:
            with db.tx(conn):
                user = conn.execute(
                    "UPDATE users SET role = 'banned' WHERE nick = ? RETURNING id", (nick,)
                ).fetchone()
                if user:
                    auth.end_sessions(conn, user["id"])
                    sql = "UPDATE runs SET state = 'rejected' WHERE user_id = ? AND state = 'review'"
                    conn.execute(sql, (user["id"],))
                    conn.execute(
                        "UPDATE matches SET state = 'void' WHERE a = ? AND state = 'open'", (user["id"],)
                    )
            print(f"{nick}: banido" if user else f"{nick}: ninguém com esse apelido")
            return 0 if user else 1
        case ["export", run] if run.isdigit():
            r = conn.execute("SELECT * FROM runs WHERE id = ? AND log IS NOT NULL", (int(run),)).fetchone()
            if r is None:
                print(f"corrida {run}: sem log", file=sys.stderr)
                return 1
            ev = json.loads(zlib.decompress(r["log"]))["ev"]
            log = {
                "v": 1,
                "mode": r["mode"],
                "skin": r["skin"],
                "seed": r["seed"],
                "shared": bool(r["shared"]),
            }
            print(json.dumps({**log, "end": r["ticks"], "ev": ev}))
        case _:
            print(__doc__, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
