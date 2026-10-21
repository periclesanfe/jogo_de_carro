"""/amigos: requests by nickname, accept, decline, remove."""


def pair(s, x: int, y: int):
    return s.db.execute(
        "SELECT asked_by, accepted FROM friends WHERE a = ? AND b = ?", sorted((x, y))
    ).fetchone()


def test_request_accept_remove(s):
    (ana, ana_id), (bia, bia_id) = s.player("ana"), s.player("bia")
    r = ana.post("/amigos", data={"apelido": "BIA"})
    assert r.status_code == 303 and tuple(pair(s, ana_id, bia_id)) == (ana_id, 0)
    assert "Pedidos enviados" in ana.get("/amigos").text
    page = bia.get("/amigos").text
    assert "Pedidos recebidos" in page and f"/amigos/{ana_id}/aceitar" in page

    ana.post(f"/amigos/{bia_id}/aceitar")  # only the one asked can accept
    assert pair(s, ana_id, bia_id)["accepted"] == 0
    assert bia.post(f"/amigos/{ana_id}/aceitar").headers["location"] == "/amigos"
    assert pair(s, ana_id, bia_id)["accepted"] == 1
    for c, other in ((ana, "bia"), (bia, "ana")):
        page = c.get("/amigos").text
        assert "Seus amigos" in page and other in page and "Pedidos" not in page

    ana.post(f"/amigos/{bia_id}/remover")
    assert pair(s, ana_id, bia_id) is None


def test_decline_and_cancel(s):
    (ana, ana_id), (bia, bia_id) = s.player("ana"), s.player("bia")
    ana.post("/amigos", data={"apelido": "bia"})
    bia.post(f"/amigos/{ana_id}/recusar")
    assert pair(s, ana_id, bia_id) is None
    ana.post("/amigos", data={"apelido": "bia"})
    ana.post(f"/amigos/{bia_id}/remover")  # cancel a request sent
    assert pair(s, ana_id, bia_id) is None


def test_asking_someone_who_asked_you_accepts(s):
    (ana, ana_id), (bia, bia_id) = s.player("ana"), s.player("bia")
    ana.post("/amigos", data={"apelido": "bia"})
    ana.post("/amigos", data={"apelido": "bia"})  # asking twice changes nothing
    assert pair(s, ana_id, bia_id)["accepted"] == 0
    bia.post("/amigos", data={"apelido": "ana"})
    assert pair(s, ana_id, bia_id)["accepted"] == 1


def test_bad_requests(s):
    ana, _ = s.player("ana")
    for nick, why in (("ninguem", "Ninguém"), ("a b", "Ninguém"), ("ANA", "é o seu")):
        r = ana.post("/amigos", data={"apelido": nick})
        assert r.status_code == 400 and why in r.text
    assert ana.post("/amigos/1/bloquear").status_code == 404
    assert ana.post("/amigos/99999999999999999999/aceitar").status_code == 404  # beyond SQLite's INTEGER
    assert s.count("friends") == 0


def test_thirty_requests_a_day(s):
    ana, _ = s.player("ana")
    for i in range(30):
        s.user(f"p{i}@x.test", f"amigo{i}")
        assert ana.post("/amigos", data={"apelido": f"amigo{i}"}).status_code == 303
    s.user("q@x.test", "q_31")
    assert ana.post("/amigos", data={"apelido": "q_31"}).status_code == 429
    assert s.count("friends") == 30


def test_friends_need_a_session_and_a_nickname(s):
    c = s.client()
    assert c.get("/amigos").headers["location"] == "/entrar"
    s.login(c, s.user("ana@x.test"))
    assert c.get("/amigos").headers["location"] == "/apelido"
    assert c.post("/amigos", data={"apelido": "bia"}).headers["location"] == "/apelido"
