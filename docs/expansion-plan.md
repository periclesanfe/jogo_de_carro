# (A) Plano final: carteira, loja de carros, cenários e power-ups

**Base:** `docs/web-platform-plan.md`, o código em `main` @ 7280470 (a árvore de c0a3bf6), as medições do plano anterior e as duas críticas.

**GOLDEN hoje:** `ec215a67…248d`. As referências `arquivo:linha` apontam para esse commit.

---

## 1. Resumo e marcos

**O que entra:**
- **Carteira (E1).** As moedas coletadas ficam guardadas no servidor. A única fonte é a re-simulação que o próprio servidor faz das corridas online: ranqueada solo, ao vivo e desafio (decisão c).
  - O saldo é **calculado, não armazenado**: soma das moedas das corridas pagas menos a soma dos preços dos carros comprados.
  - Não há ledger, nem coluna de saldo, nem gatilhos de pagamento.
- **Carros (E2).** 20 carros pagos com moedas: os 16 pedidos e mais 4 estilos (Táxi, Kombi, Fórmula 1, Monster Truck), estes desenhados por último.
  - Ficam todos em uma tabela, `CARS`. A loja é a própria garagem do jogo.
- **Cenários (E3).** 5 biomas que mudam a cada 1 km.
  - Um bioma é liberado quando o jogador chega a N km em uma corrida.
  - O bioma liberado pode ser escolhido como cenário inicial.
  - É só cosmético e vale em todos os modos.
- **Power-ups (E4).** ESTRELA, FANTASMA, TURBO, DEVAGAR e VIDA EXTRA, mais o ESCUDO de hoje.
  - Todos usam **o mesmo slot** do escudo: mesma chance, mesmo cooldown e um sorteio a mais para escolher o item.
  - O ranking continua o mesmo, sem nova temporada (decisão b).

| # | Entrega | GOLDEN | ≈ LOC (código + arte + testes) | Verificação que fica |
|---|---|---|---|---|
| **E1 Carteira** | migração 5 (`runs.coins` + gatilho `matches_keep_runs`); `PAID`/`BALANCE`; `result.coins`/`wallet`; `welcome.coins`; chip no título; "+N moedas" no resultado; aviso offline | igual | 40 + 0 + 45 | `server/tests/test_wallet.py` |
| **E2 Garagem/loja** | `CARS`/`PRICE`; validação por `CARS` (4 lugares); migração 6 (`garage`); troca para `yellow` no `hello`; `buy`/`wallet`; cadeado e preço, confirmar duas vezes, "LIBERADO!"; 20 sprites | igual | 75 + 300 + 30 | testes de compra; corrida ranqueada completa com carro pago; digest igual antes e depois |
| **E3 Cenários** | `BIOMES` (5); `Road.biome(y)`; chão por bioma em cache e preguiçoso; banner; aba CENÁRIOS; `save.best_m`, `save.biome` | igual | 70 + 90 + 15 | corpus idêntico para todo bioma inicial; `biome_at`; o servidor não constrói chão |
| **E4 Power-ups** | 5 itens; relógio do mundo + fix A; slot único; HUD; `result.k`; adesão sem ticks protegidos; anulação automática de desafios; portão de comparabilidade | **novo** | 160 + 65 + 85 | testes do §7; corpus regravado; portão do §5.5; CI do golden |

**Total:** cerca de 345 linhas de código, 455 de arte e 175 de testes, ou seja, ≈ 1,0k. O plano anterior tinha ≈ 1,35k.

**Por que esta ordem (E1 → E2 → E3 → E4):**
- O E1 sai o quanto antes, porque moedas não são retroativas.
- O E2 depende do E1.
- A arte do E3 pode ser feita enquanto o E2 é publicado; os dois são independentes e não mexem no GOLDEN.
- O E4 sai por último e **sozinho**, porque é a única mudança de GOLDEN. Ele não deve ser dividido: cada GOLDEN novo anula desafios e obriga a regravar o corpus.

---

## 2. Economia (E1)

### 2.1 Moedas por corrida hoje (medido)

**Corpus de replays, re-simulado:**

| Log | Fim | s | Moedas | Moedas/min |
|---|---|---|---|---|
| `facil_win` | vitória | 90 | 140 | 93 |
| `normal_crash` | batida | 49,6 | 104 | 126 |
| `normal_shared_win` | vitória | 180 | 343 | 114 |
| `dificil_win` | vitória | 270 | 629 | 140 |
| `infinito_trunks_giveup` | desistência | 200 | 390 | 117 |

**Bots, 20 sementes por nível (mediana por corrida):**
- iniciante (0,20): 30–52 moedas;
- médio (0,13): 84–214;
- bom (0,07): 108–1.073.

Isso dá 62–135 moedas por minuto, e modos mais difíceis pagam mais por minuto. O teto, um piloto perfeito no corredor, fica em cerca de **8 mil moedas por hora por conta**: o ritmo da corrida prende ao tempo real e cada conta só corre uma corrida por vez.

**Os preços supõem cerca de 80 moedas por corrida típica.**

### 2.2 Quais corridas pagam

O valor pago é `run.score.coins` como o servidor simulou. O cliente nunca envia uma contagem de moedas.

| Corrida | Paga |
|---|---|
| Ranqueada solo `ok` (inclusive `desync` e desistência) | sim |
| Em revisão (`top10`/`bot`) | sim, na hora; se o admin rejeitar, a moeda sai do saldo, que pode ficar negativo (dívida) |
| `rejected/substituida` (legítima, mas pior que a retida) | sim |
| `rejected/conexao` (caiu a conexão) | sim. São entradas que o servidor já aceitou, e cair não dá vantagem sobre sair, que já paga |
| Ao vivo e desafio, os dois jogadores | sim, até o tick em que o servidor parou a corrida |
| `ritmo`, `adiantado`, `invalido`, `prazo`, `anulada`, `reinicio` | 0 |
| Bot versus, offline, desktop | 0. Na web o resultado diz "Moedas só ficam na carteira nas corridas online" |

**Regra permanente:** nunca pagar por **vencer** uma corrida ou um desafio. É a única mudança que permitiria contas alternativas criarem moedas, com corridas entregues de propósito.

### 2.3 Carteira no servidor

**Migração 5:**

```sql
-- migration 5
ALTER TABLE runs ADD COLUMN coins INTEGER;  -- run.score.coins como o servidor simulou (paga ou não: auditoria)
-- conta excluída: o DELETE em cascata das matches apagaria a corrida do rival, e as moedas dele junto
CREATE TRIGGER matches_keep_runs BEFORE DELETE ON matches
BEGIN UPDATE runs SET match_id = NULL WHERE match_id = OLD.id; END;
```

**Migração 6 (no E2):**

```sql
-- migration 6
CREATE TABLE garage(user_id INTEGER NOT NULL REFERENCES users ON DELETE CASCADE, skin TEXT NOT NULL,
  price INTEGER NOT NULL, PRIMARY KEY (user_id, skin)) WITHOUT ROWID;  -- só carros pagos
```

**No `hub.py`:**

```python
PAID = "(state IN ('ok', 'review') OR why IN ('substituida', 'conexao'))"
BALANCE = (
    f"(SELECT coalesce(sum(coins), 0) FROM runs WHERE user_id = :u AND {PAID})"
    " - (SELECT coalesce(sum(price), 0) FROM garage WHERE user_id = :u)"
)
BUY = f"INSERT OR IGNORE INTO garage SELECT :u, :skin, :price WHERE {BALANCE} >= :price"  # atômico: 1 comando
# ponytail: o saldo é um SUM pelo índice runs_user; guardar em users só se um profile mostrar custo
```

- **`end()`:**
  - grava `row["coins"] = run.score.coins`;
  - depois do `UPDATE`, lê o valor pago com `SELECT coins FROM runs WHERE id = ? AND {PAID}` (`fetchone() or (0,)`; uma linha apagada dá 0) e o saldo com `SELECT {BALANCE}`;
  - `result` ganha `coins` (pago por esta corrida) e `wallet` (saldo absoluto). Em corrida ao vivo, `settle` → `end` faz isso para cada jogador.
- **`welcome`** ganha `coins`.

**Propriedades que saem do desenho, sem código:**
- Uma corrida não paga duas vezes: é uma linha só.
- Quando o admin rejeita (`rejeitar`, `banir`), a moeda sai do saldo. Se já tiver sido gasta, o saldo fica negativo e a dívida bloqueia novas compras.
- Ids de corrida reaproveitados não causam conflito.
- O saldo de uma conta já apagada é 0, sem `None`.

**Verificado num rascunho em SQLite (vira `server/tests/test_wallet.py` no E1).** Cobre compra, compra repetida, saldo insuficiente, exclusão em cascata da conta do amigo e dívida depois de uma rejeição.

**Suporte, sem comandos novos no admin:**
- Estorno de carro: `DELETE FROM garage WHERE user_id = ? AND skin = ?`. O preço volta ao saldo sozinho.
- Os comandos `moedas`/`dar` entram quando chegar o primeiro chamado de suporte.

**Cliente:**
- `net.py` guarda `coins` vindo de `welcome`, `result` e `wallet`. É sempre o valor absoluto; o cliente nunca soma nada.
- Título: um chip com o sprite `coin` e o saldo, quando `net.coins` existir.
- Resultado: "+37 moedas · carteira 357".

### 2.4 Escada de preços

| Faixa | Preço | Corridas (~80/corrida) | Carros |
|---|---|---|---|
| 1 | 300 | ~4 | Herbie 53, Moto, *Táxi, Kombi* |
| 2 | 800 | ~10 | Supra MK4, Charger R/T 70, Cadillac Series 62, Carrinho RC |
| 3 | 1.500 | ~19 | Impala 67, Máquina Mistério, Flintstones, *Fórmula 1, Monster Truck* |
| 4 | 3.000 | ~38 | Bumblebee, Cybertruck, Mach 5 |
| 5 | 5.000 | ~63 | Relâmpago McQueen, Tanque de Guerra |
| 6 | 8.000 | ~100 | Batmóvel, Optimus Prime |

Os nomes em itálico são os 4 extras, desenhados por último.

- A coleção completa custa 46.900 moedas, cerca de 10 a 16 horas de jogo online.
- Preço é um dado em `CARS`. Mudar um preço é um deploy de cliente e servidor juntos, sem mudar o GOLDEN.
- **Reajuste depois de 2 semanas,** pela métrica de moedas pagas por jogador ativo por dia:

```sql
SELECT sum(coins) * 1.0 / count(DISTINCT user_id || date(started, 'unixepoch'))
FROM runs WHERE <PAID>
```

  A mediana por corrida não serve: é dominada por batidas curtas.

### 2.5 Farming

**Sem teto diário no lançamento:**
- moedas só compram cosméticos;
- não há transferência, presente ou troca;
- o ritmo da corrida limita um bot a cerca de 8 mil por hora;
- sair logo depois do `go` rende cerca de 0.

**Se um teto vier a ser necessário:** uma coluna `runs.paid` ao lado de `runs.coins`, para manter a contagem simulada para auditoria, com `PAID` somando `paid`.

---

## 3. Carros e loja (E2)

### 3.1 Uma tabela

```python
# settings.py: a chave é o que se grava (runs.skin, garage, save); nome e preço mudam sem migração
CARS: dict[str, tuple[str, int]] = {
    "yellow": ("Amarelo", 0), "black": (..., 0), "blue": ..., "pink": ..., "red": ..., "white": ...,  # = SKINS
    "beetle": ("Herbie 53", 300), "moto": ("Moto", 300), ...,  # depois por preço, na ordem da tabela 3.2
}
PRICE = {k: p for k, (_, p) in CARS.items() if p}
assert tuple(CARS)[:6] == SKINS  # SKINS continua a paleta do trânsito e a lista que o golden lê
```

- **`SKIN_NAMES` sai.** Os dois usos (`title.py:109`, `garage.py:96`) passam a ler `CARS[k][0]`.
- **`SKINS` fica onde é simulação:**
  - `golden.py:49`;
  - `world.py:147-149`: o trânsito nunca usa carros famosos.
- **Validação por `CARS`** (sem isso, um carro comprado gera `BadInput`):
  - `run.py:44`: `skin in CARS`;
  - `save.py:58`: `raw.get("skin") in CARS`;
  - `save.py:68`: `best_by_skin` com as chaves de `CARS`;
  - `backdrop.py:28`;
  - `hub.SHAPES["hello"]["skin"] = tuple(CARS)`;
  - a garagem percorre `tuple(CARS)`.
- **Hitbox canônica, já garantida:**
  - `assets.mask` troca todo `car_*` por `car_yellow` (`assets.py:111`), e `bounds` passa pela máscara;
  - o retângulo vem do tamanho do quadro 24×40 ×3, igual para todos;
  - moto e tanque correm com a hitbox do carro amarelo.
- **Gerador:**
  - `tools/make_assets.py` mantém sua própria tabela `CAR_DESIGNS[key]`: um trio (estilo, deco, vidro) para a rota A, ou uma função que desenha o sprite inteiro para a rota B;
  - o `SPRITES` do gerador vem dela, e o gerador continua sem importar `settings`, porque roda com `python -I`;
  - o teste existente `test_shipped_assets_match_the_manifest` já falha se uma chave de `CARS` não tiver PNG.
- **Troca por takedown:** muda o nome em `CARS` e redesenha a deco com a mesma chave. Não precisa de migração.

### 3.2 Os 20 carros (24×40, 2 quadros, 1 px de margem, nariz para cima)

| Chave | Nome | Preço | Visual que identifica | Rota, LOC |
|---|---|---|---|---|
| `beetle` | Herbie 53 | 300 | Fusca branco: frente e traseira redondas, para-lamas saltados, grelha na tampa do motor; faixas vermelha, branca e azul do capô à traseira, deslocadas para a esquerda; "53" preto num círculo branco no capô e na tampa do motor | A "beetle" + dígitos, ~14 |
| `moto` | Moto | 300 | rodas em linha, tanque vermelho, capacete; guidão, retrovisores e alforjes abrem até ~18 px | B, ~32 |
| `jdm94` | Toyota Supra MK4 | 800 | carroceria esportiva laranja, aerofólio em arco, lanternas redondas duplas | A sport, ~10 |
| `muscle70` | Dodge Charger R/T 70 | 800 | preto brilhante, grade preta inteira, capô com bossa, faixa branca na traseira | A sedan, ~12 |
| `fins59` | Cadillac Series 62 (1959) | 800 | rosa e comprido, rabos de peixe nas linhas 31–38 com lanternas-bala, para-choques cromados | A sedan, ~16 |
| `rc_buggy` | Carrinho RC (Toy Story) | 800 | buggy verde aberto, rodas pretas grandes com cubo azul, antena de ponta vermelha | B, 20 |
| `sedan67` | Impala 67 (Sobrenatural) | 1.500 | estilo "classic" (capô longo, teto curto), preto, cromados, 3 lanternas de cada lado | A, ~14 |
| `mystery_van` | Máquina Mistério | 1.500 | van caixote verde-água, faixa azul, flores laranja no teto | A "box", 12 |
| `stone_age` | Carro dos Flintstones | 1.500 | rolos de pedra na frente e atrás (sulcos animados), estrutura de troncos, toldo de oncinha | B, 23 |
| `robot_camaro` | Bumblebee | 3.000 | esportivo amarelo, duas faixas pretas, emblema vermelho de 3 px | A sport, 6 |
| `cyber` | Cybertruck | 3.000 | aço em dois tons dividido na crista, faixa de vidro preta, LED branco na frente e vermelho atrás | A jeep, ~16 |
| `racer5` | Mach 5 | 3.000 | esportivo branco, "M" vermelho no capô, "5" num círculo vermelho | A sport + dígitos, ~18 |
| `racer95` | Relâmpago McQueen | 5.000 | esportivo vermelho, raios amarelos, "95", aerofólio, olhos no para-brisa | A sport, ~15 |
| `tank` | Tanque de Guerra | 5.000 | esteiras animadas, casco oliva, torre redonda, cano até a linha 0, estrela branca | B, 18 |
| `bat` | Batmóvel (1989) | 8.000 | preto e longo, entrada de turbina central, canopi, aletas de morcego nas colunas 0–2 e 21–23 | A sedan, ~20 |
| `robot_truck` | Optimus Prime | 8.000 | só a cabine: vermelha, grade cromada inteira, 2 escapamentos, traseira azul com quinta roda | A jeep, ~25 |
| *`taxi`* | Táxi | 300 | sedan amarelo, faixa xadrez no teto, luminoso 4×2 | A sedan, ~10 |
| *`kombi`* | Kombi | 300 | caixote arredondado, teto branco sobre faixa vermelha, V no nariz | A "box", ~10 |
| *`formula`* | Fórmula 1 | 1.500 | bico estreito vermelho, asas largas, 4 rodas expostas | B, ~22 |
| *`monster`* | Monster Truck | 1.500 | jipe sobre rodas enormes que saem dos 4 cantos, chamas no capô | B (a função do RC com parâmetros), ~10 |

**Peças compartilhadas:** dígitos 3×5 (~8 linhas; Herbie, Mach 5 e McQueen) e o desvio da rota B no `car_sheet` (2 linhas). Arte ≈ 300 linhas.

**Ordem na garagem:** os 6 grátis, depois por preço. `tests/test_smoke.py:58-64` continua passando.

### 3.3 Posse e compra no servidor

```python
# on_hello
owned = {r[0] for r in self.db.execute("SELECT skin FROM garage WHERE user_id = ?", (sock.uid,))}
sock.skin = d["skin"] if d["skin"] not in PRICE or d["skin"] in owned else "yellow"  # troca, nunca recusa
welcome |= {"skin": sock.skin, "coins": self.balance(sock.uid), "owned": sorted(owned)}


async def on_buy(self, sock, d, now):  # SHAPES["buy"] = {"skin": tuple(PRICE)}
    self.db.execute(BUY, {"u": sock.uid, "skin": d["skin"], "price": PRICE[d["skin"]]})  # já tem/falta: nada
    await self.send(sock, self.wallet(sock.uid))  # {"t": "wallet", "coins": n, "owned": [...]}
```

**`sock.skin` alimenta** a linha `runs.skin` (`hub.py:526`), a `Run` (`:686`) e o `op.skin` que o rival vê (`:671`). Online só corre carro próprio. Um cliente adulterado só muda a própria tela, e a hitbox é igual para todos.

**`welcome.skin` vai para `net.skin` e `save.skin`.** Isso mantém honesta a verificação de reconexão em `online.py:106`: carro diferente abre um socket novo, e o novo `hello` é checado.

Um carro estornado com o socket aberto continua utilizável até o próximo `hello`. É aceitável para um cosmético.

### 3.4 Garagem (a loja)

- **Bloqueado:** `PRICE.get(k) and k not in net.owned and k != save.skin`.
  - Offline e no desktop, `net.owned` fica vazio, então os carros pagos ficam bloqueados, exceto o que já estava selecionado.
  - Não há cache de carros comprados no save.
- **Desenho:** carros laterais bloqueados aparecem escurecidos (`BLEND_RGB_MULT`). O carro do centro fica colorido.
- **Linha de informação:**
  - "1.500 moedas · você tem 320";
  - sem conta: "Entre no site para comprar";
  - sem saldo: "Faltam 1.180 moedas";
  - no desktop: "Disponível na versão online".
- **Comprar é confirmar duas vezes:** o primeiro ENTER mostra "ENTER de novo para comprar por 1.500", e o segundo envia `buy`.
- **Quando chega `wallet` com o carro:** "LIBERADO!" com `particles.confetti` e o som `record`, e o carro fica selecionado.

---

## 4. Cenários (E3), sem mudar o GOLDEN

**Regra:** `biome_at(start, meters) = (start + int(meters // 1000)) % len(BIOMES)`.
- O `Road` acumula seu próprio `px`, zerado depois do pré-povoamento.
- `Road.biome(y)` dá o bioma na linha de tela `y`: `biome_at(self.start, (self.px + PLAYER_Y - y) / PX_PER_METER)`.
- Props usam o bioma da linha onde nascem (`y = -100`). Cada ladrilho de chão de 576 px usa o bioma da sua borda de baixo.
- O banner usa `biome(PLAYER_Y)`. O cenário novo aparece chegando cerca de 45 a 85 m antes, e o banner confirma.

**Tabela de biomas** (`BIOMES` em `road.py`, uma linha por bioma). O asfalto, as faixas e os obstáculos são os mesmos em todos.

| # | Chave / nome | Libera em | Chão (as 8 cores de `build_ground`) | Props (peso) | Arte |
|---|---|---|---|---|---|
| 0 | `campo` / Campo | sempre | o de hoje | tree 42, bush 28, flowers 15, rock_small 15 | 0 |
| 1 | `deserto` / Deserto | 1 km | areia e ocre, terra rachada | cactus 45, bush seco 25, rock_small 30 | ~20 |
| 2 | `neve` / Neve | 2 km | branco e azul-acinzentado, acostamento de lama | pine nevado 45, bush nevado 40, snowman 15 | ~20 |
| 3 | `cidade` / Cidade à noite | 3 km | calçada escura, meio-fio | building 70, bush 30 (canteiros) | ~25 |
| 4 | `vulcao` / Vulcão | 4 km | basalto com rachaduras vermelhas | basalt 50, rock_small 30, lava 20 | ~20 |

**Sprites novos** (em `SPRITES` nos dois arquivos):

| Sprite | Tamanho nativo | Quadros |
|---|---|---|
| `cactus` | 14×26 | 2 (saguaro, barril) |
| `pine` | 20×32 | 2 (verde, nevado) |
| `snowman` | 12×16 | 1 |
| `building` | 40×40 | 2 (caixa d'água, ar-condicionado) |
| `basalt` | 14×10 | 2 |
| `lava` | 24×14 | 1 |
| `bush` | 16×12 | passa de 2 para 4 (seco, nevado) |

- Os postes continuam em todos os biomas.
- Cada entrada da tabela de props leva uma `margin`: tree, pine e building ficam 40 px longe da pista, como as árvores hoje. `_spawn_prop` lê a tabela ponderada.

**Segunda leva** (são só linhas de dados, sem decisão de projeto): Floresta e Praia.

**Escolha do cenário inicial (decisão d): só cosmético, vale em todos os modos, ranqueado incluído.**
- O cenário nunca entra em `Run`, `hello` ou no log.
- O cliente chama `run.world.road.restart(save.biome)` depois de criar a `Run`. `restart` limpa e re-povoa os props, para a contagem regressiva já mostrar o cenário certo.
- No versus, as duas metades usam a minha escolha, e cada uma muda pela distância do seu próprio mundo.
- A leitura é igual para todos: mesmo asfalto, mesmos sprites e máscaras de obstáculo, nenhum filtro de tela cheia.
- O `Road` usa o próprio `road.rng`, nunca o `world.rng`. O GOLDEN não lê o `Road`.

**Liberação:**
- `save.best_m` guarda a maior distância em uma única corrida, offline incluído, porque é cosmético. O bioma *i* libera em *i* km.
- O resultado mostra "Cenário liberado: NEVE" quando o limite é cruzado.
- `save.biome` é validado: precisa estar liberado, senão vira 0.

**Aba CENÁRIOS na garagem:**
- CIMA e BAIXO alternam entre CARROS e CENÁRIOS.
- ESQUERDA e DIREITA percorrem os nomes, e cada troca chama `ctx.backdrop.world.road.restart(i)`: o fundo desfocado da garagem é a prévia.
- Bioma bloqueado: dá para ver a prévia, mas não confirmar. A linha mostra "Chegue a N km numa corrida para liberar · seu recorde: X km".
- No título, o fundo de demonstração percorre os biomas como numa corrida, como vitrine e sem código.

**Banner:**
- No solo, o nome do bioma fica na margem esquerda, centrado em (200, 70), por 1,6 s, fora da pista (x de 400 a 880).
- No versus, com alpha 120 no topo da minha metade.

**Desempenho e servidor:**
- `ground(assets, biome)` continua com `functools.cache` e `Random(2022)` fixo. Os 5 chãos são aquecidos atrás da tela de carregamento: cerca de 3 MB cada já escalados, ≈ 15 MB no total.
- O `Road.ground` passa a ser **preguiçoso, lido no `draw()`**. Isso é uma mudança: hoje o `Road.__init__` constrói o chão no servidor. Com ela, o servidor não constrói nenhum.
- Marcar com `ponytail:`: se a memória do wasm reclamar, trocar por `lru_cache(2)` e pré-escalar antes da troca.
- Não há transição pontilhada entre biomas: a costura é seca, junto com o banner.

---

## 5. Power-ups (E4), o único GOLDEN novo

### 5.1 Lista

```python
Power = namedtuple("Power", "label colour seconds weight capped")
POWERS = {  # a ordem do dict é a ordem do sorteio: não reordenar sem mudar o GOLDEN
    Item.SHIELD: Power("ESCUDO", ..., 8.0, 3, False),
    Item.STAR: Power("ESTRELA", GOLD, 5.0, 2, False),
    Item.GHOST: Power("FANTASMA", LAVENDER, 6.0, 2, False),
    Item.TURBO: Power("TURBO", FLAME, 4.0, 2, False),
    Item.SLOW: Power("DEVAGAR", LIGHT_BLUE, 4.0, 2, True),
    Item.LIFE: Power("VIDA EXTRA", RED, 0.0, 1, True),
}
TIME_SCALE = {Item.SLOW: 0.5, Item.TURBO: 1.5}  # frações binárias exatas: multiplicação IEEE pura, sem libm
PROTECT = {Item.STAR, Item.GHOST, Item.TURBO}
NO_NEAR_MISS = PROTECT | {Item.SLOW}
```

| Item | Efeito | Tempo (real) | Modos |
|---|---|---|---|
| ESCUDO | como hoje: quebra no primeiro golpe e dá 0,9 s de graça | 8 s | todos |
| ESTRELA | invencível; obstáculo tocado é destruído (detritos da quebra de escudo, 0 pontos) | 5 s | todos |
| FANTASMA | invencível; atravessa obstáculos; o carro é desenhado translúcido | 6 s | todos |
| TURBO | relógio do mundo ×1,5, com a proteção do FANTASMA | 4 s (6 s de mundo) | todos |
| DEVAGAR | relógio do mundo ×0,5 (bullet time: troca de faixa em tempo real) | 4 s (2 s de mundo) | Fácil, Normal, Difícil |
| VIDA EXTRA | guardada até um golpe, que vira uma quebra de escudo; no máximo 1 por corrida | — | Fácil, Normal, Difícil |

- **Slot único:** o jogador tem `player.power: Item | None`, `player.power_t` e `player.lives` (0 ou 1).
  - Pegar um item substitui o poder ativo. A VIDA vai para `lives`, não para o slot.
  - `player.shield` deixa de existir. Os leitores passam a usar `player.power`: `demo.py:153`, `race.py:458`, `versus.py:207` e `player.draw`.
- **No Infinito o sorteio só tem itens protetores:** escudo, estrela, fantasma e turbo.
  - DEVAGAR fica de fora **por obrigação**: um relógio lento chegaria ao limite de entradas antes da vitória, e `Run.load` recusaria `k > cap` como `invalido`.
  - VIDA fica de fora para não inflar o Infinito.
- **Sem ÍMÃ:** não foi pedido, inflava moedas e baixava os pontos no Infinito.

### 5.2 Spawn: determinístico, na faixa livre, igual para os dois jogadores

```python
# spawner: a rolagem, a chance (0,04), o cooldown (25 s) e o primeiro em 15 s de hoje; um sorteio a mais escolhe
if t >= self.next_item_t and rng.random() < ITEM_CHANCE:
    self.next_item_t = t + ITEM_COOLDOWN
    pool = [
        i
        for i, p in POWERS.items()
        if (self.mode.win_s or not p.capped) and not (i is Item.LIFE and self.life_placed)
    ]
    item = rng.choices(pool, weights=[POWERS[i].weight for i in pool])[0]
    self.life_placed |= item is Item.LIFE
    return [ItemPlacement(item, LANE_CENTERS[lane], g)]  # na faixa livre reservada
```

- **A escolha depende só** do RNG, do tempo nominal, do modo e do estado do próprio spawner. Nunca depende do jogador.
- **Na estrada compartilhada** (ao vivo e desafio), os dois jogadores veem o mesmo item no mesmo lugar, e cada um pega o seu.
- `rng.choices` com pesos inteiros não usa libm.
- O spawner nunca lê `world.obstacles`, então a ESTRELA destruir obstáculos não separa as estradas.
- O modo de demonstração mantém `next_item_t = inf`.
- Todos os ícones são 16×16 com 4 quadros, como o escudo, então o alcance de coleta é o mesmo.

### 5.3 DEVAGAR e TURBO: relógio do mundo e fix A (medido)

**O relógio do mundo.** Em `World.update`, `wdt = dt * TIME_SCALE.get(player.power, 1.0)`.
- Usam `wdt`: `elapsed`, a rampa de velocidade, `px = speed * wdt` (guardado em `world.px`) e as atualizações de obstáculos, pickups, estrada e partículas.
- `player.update(dt)` continua em tempo real.
- `Run.step` pontua por `world.px`.
- Com escala 1,0, os bits são os mesmos de hoje.

**Fix A (planejar as linhas em um relógio nominal):**

```python
n = self.clock  # [t, v, d]: uma corrida sem poder de tempo, com a fórmula do próprio mundo
while n[2] + LOOKAHEAD < self.prev_g:
    n[0] += FIXED_DT
    n[1] = min(speed_at(mode, n[0]), n[1] + mode.base_speed / START_RAMP_S * FIXED_DT)
    n[2] += n[1] * FIXED_DT
t, speed = n[0], max(n[1], speed_at(mode, n[0]))  # o modo de demonstração passa seu t congelado (uma flag)
```

`START_RAMP_S` vai para `settings.py`.

**Medido:**

| Verificação | Resultado |
|---|---|
| Estrada compartilhada, com o relógio do mundo, sem fix A | posicionamentos diferentes |
| Estrada compartilhada, com fix A | idênticos nos 12 casos (338 a 543 posicionamentos em cada) |
| Faixa livre: piloto perfeito no corredor, sem proteção, 40 sementes, Difícil e Infinito | 0 batidas em 40 com DEVAGAR e com TURBO |
| GOLDEN com só o fix A | igual ao de hoje |
| Custo | +5 a 8 % por tick no servidor |

**Por que o TURBO protege:** uma troca de duas faixas precisaria de 0,42 s de mundo, mas a janela planejada é de 0,40 s.

**Linhas de velocidade:** `world.py:181` passa a comparar `self.speed * scale > 520`. Sem isso, o TURBO não as mostraria no Fácil. Como o E4 já muda o GOLDEN, isso não custa nada a mais.

### 5.4 Colisão, vida, veredito

**Protegido** (`invulnerable or grace > 0 or power in PROTECT`):
- o obstáculo é marcado como passado;
- a ESTRELA também o remove, com os detritos da quebra de escudo;
- `grace = max(grace, 2 * FIXED_DT)`, para nunca acabar a proteção dentro de um caminhão;
- ESTRELA, FANTASMA e TURBO terminam na graça de 0,9 s de hoje, com o carro piscando.

**Golpe sem proteção:**
- com ESCUDO: a quebra de hoje;
- senão, com VIDA: `lives -= 1`, pelo mesmo caminho da quebra, e um `EventKind.LIFE_LOST` para o HUD;
- senão: batida.

Não há respawn. Perder uma vida não conta como batida.

**Quase-batidas:** não pontuam enquanto `power in NO_NEAR_MISS`, o que inclui o DEVAGAR (`world.py:223`). Uma batida limpa o poder ativo.

**Veredito nas corridas com amigos: não muda; continua por tick.**
- "Quem bate primeiro, no tempo real, perde", que é exatamente o que a tela dividida mostra.
- Quando os dois vencem, decide a pontuação.
- O desafio já grava `tick` (`hub.py:592`).
- Muda só a docstring de `run.py:183-184`: "foi mais longe" vira "durou mais".

**`result` ganha `"k": run.tick`,** e `versus.py:352` passa a usar `dict(self.kept).get(result.get("k"))`. Com o relógio do mundo, `secs / FIXED_DT` deixa de ser o tick, e a tela mostraria a pontuação local em vez da do servidor.

### 5.5 Ranking (decisão b): mesmo quadro, sem temporada

**O que garante que fica comparável:**
- o mesmo slot, a mesma chance e o mesmo cooldown;
- nenhum multiplicador: destruir obstáculo vale 0, não há quase-batida com poder ativo, não há ÍMÃ;
- no Infinito, só itens protetores no orçamento de proteção de hoje;
- nos modos com limite de tempo, a pontuação de quem vence continua presa à distância em `win_s`. Os pontos vêm de `world.px`, então o TURBO não dá pontos por metro.

**O que muda, dito ao jogador:**
- A mesma semente dá outra estrada. Isso não importa, porque as sementes são secretas.
- Jogadores mais fracos vencem mais vezes nos modos com limite (VIDA, DEVAGAR), então entram mais linhas no quadro. O topo continua limitado pela distância.
- As linhas antigas continuam válidas. `runs.build` marca o corte, caso um dia se queira uma temporada (cerca de 35 linhas, documentado).

**Medido antes, com ÍMÃ no sorteio, Bot 0,07, 40 sementes:**
- Normal −0,6 % e Difícil −2,7 % nas medianas.
- No Infinito, −10 % na mediana e −33 % no máximo contra o braço "só sorteio" (mesmas estradas). A queda foi atribuída ao ÍMÃ, que ocupava 2/11 do slot sem proteger.

**Portão antes do merge do E4 (script de scratch, fora do repositório):**
- `powers.py` sem ÍMÃ, com braços pareados "só sorteio" e "novo" nas mesmas sementes, **N ≥ 200 por modo**.
- Dois pilotos: o Bot 0,07 e um caçador de quase-batidas (o piloto automático que prefere a faixa vizinha ao próximo obstáculo quando o corredor permite, cerca de 15 linhas).
- Relatar mediana, p90 e máximo.
- **Passa** se o p90 ficar dentro de ±5 % em Fácil, Normal e Difícil e de ±10 % no Infinito.
- **Se falhar**, aplicar o fallback C1.

### 5.6 HUD, arte e som

- **Painel:** `_draw_shield` vira `_draw_power` (`race.py:479-488`), com um único painel `SHIELD_BOX`.
  - O rótulo e a cor vêm de `POWERS`.
  - Uma barra no lugar de texto de contagem, para não mexer no cache de texto.
  - A barra pisca nos últimos 2 s.
  - Um coração ao lado quando `lives`.
- **Popups** ("ESTRELA!", "-1 VIDA") reaproveitam o tremor e o flash de `SHIELD_BREAK`. O velocímetro mostra km/h × escala.
- **Versus (`versus.py:207`):** o cartão lê `player.power`. O poder do rival aparece só como efeito no carro dele.
- **Efeitos no carro**, todos em `draw()`, sem partículas no `update()`:
  - FANTASMA: uma cópia em cache com alpha 110;
  - ESTRELA: o halo do escudo em dourado;
  - TURBO: as linhas de velocidade.
- **Sprites:** 5 ícones de 16×16 com 4 quadros (estrela com olhos, fantasma, raio, ampulheta, coração), cerca de 65 linhas. `pickups.py:28,38` lê a cor do halo em `POWERS`.
- **Som:** `shield_up` em toda coleta e `shield_break` para destruição ou vida perdida.

### 5.7 Bot, flags e desafios abertos

- **Pilotos de corredor** (piloto automático, `Bot`): pegam os itens sem lógica nova.
  - O `Bot` reage pelo `world.elapsed` (`autopilot.py:66`), então o DEVAGAR não o ajuda como ajuda um humano.
  - Remedir `BOT_LEVELS` depois do E4.
- **Flags:** `flags.Watch.advance` conta para a adesão só os ticks desprotegidos (`player.power is None and player.grace == 0`). Um bot não consegue mais sair do corredor de graça enquanto está protegido, e o `FLAG_*` não precisa de reajuste.
- **Desafios abertos:** anulação automática na partida do servidor, em `app.py` ao lado de `check_runtime`, cerca de 5 linhas.
  - Para cada desafio `open`, comparar o `golden.txt` do build da corrida do desafiante com o atual. Se o arquivo faltar ou for diferente, `state = 'void'`.
  - Deploys cosméticos mantêm os desafios. Não há migração manual.

---

## 6. Protocolo

```
S→C welcome += "coins":320 (E1), "skin":"yellow","owned":["beetle"] (E2)   skin: o carro com que o servidor corre
C→S {"t":"buy","skin":"beetle"}                                               (E2)
S→C {"t":"wallet","coins":20,"owned":["beetle"]}                              a única resposta ao buy
S→C result += "coins":37,"wallet":357 (E1), "k":5412 (E4)
```

---

## 7. GOLDEN, rollout e testes

**GOLDEN por marco:**
- **E1:** igual.
- **E2:** igual. `SKINS` continua em `golden.py:49` e `world.py:147`. O teste "digest igual antes e depois" pega qualquer mudança acidental nos pixels de `car_yellow`, van ou caminhão durante a refatoração de `vehicle()`.
- **E3:** igual. Só muda o `Road`.
- **E4:** novo.
  - O estado por tick também passa a incluir `world.elapsed` no hash.
  - Os 5 logs do corpus são regravados (`tests/test_run.py:24-30`).
  - Um script de scratch procura sementes do piloto automático na estrada compartilhada Normal até encontrar no máximo 2 logs que, juntos, peguem os 5 itens novos. Não há gancho de teste no código da simulação.
  - O gate de CI (nativo igual ao Chrome) e o `check_runtime` do servidor provam a igualdade de bits.

**Rollout:**
- **E1 a E3:** deploys normais, de um commit cada.
- **E4:**
  1. Portão do §5.5.
  2. Rodar `python -m jogo_server.load` no build novo e baixar `MAX_ATIVAS` se preciso.
  3. Esvaziar a fila de revisão no build antigo (`revisar`, depois `aprovar`/`rejeitar`).
  4. Deploy (drain, cópia do banco, troca, saúde). Na partida, o servidor anula os desafios de golden antigo.
  5. Aviso no site.
  6. Acompanhar `desync_24h` e remedir `BOT_LEVELS`.

**Testes:**
- **E1 (`test_wallet.py`):**
  - corrida honesta paga o `run.score.coins` do servidor, igual a `result.coins`;
  - `ritmo`, `adiantado`, `invalido`, `prazo` e `reinicio` pagam 0;
  - `conexao` paga;
  - `top10` paga; `rejeitar` faz o saldo cair e pode deixar dívida;
  - ao vivo e desafio pagam os dois jogadores, e `decided` paga até o tick de parada;
  - o amigo apaga a conta e as moedas da minha corrida contra ele ficam;
  - o saldo de uma conta apagada é 0;
  - mais o ajuste das asserções exatas existentes: `test_ranked.py:140`, `test_live.py:205,387,392,494`, `test_challenge.py:74,123,229`, `test_online.py:405-417`.
- **E2:**
  - comprar funciona; sem saldo nada muda; comprar duas vezes cobra uma; o `DELETE` estorna;
  - `hello` com carro não comprado grava `runs.skin = 'yellow'` e `welcome.skin = 'yellow'`;
  - **uma corrida ranqueada completa com um carro pago comprado;**
  - `Run` e `SaveData` aceitam um carro pago;
  - na garagem, confirmar duas vezes envia `buy` (rede falsa);
  - digest igual antes e depois.
- **E3:**
  - limites e ciclo de `biome_at`;
  - o corpus dá resultados idênticos com todo bioma inicial, e o `world.rng` não é consumido;
  - uma `Run` no caminho do servidor deixa vazio o cache de `ground`.
- **E4:**
  - cada item aparece nos modos permitidos; VIDA e DEVAGAR nunca aparecem no Infinito; no máximo 1 VIDA por corrida;
  - 3 pilotos (um pega TURBO, outro DEVAGAR) recebem posicionamentos idênticos, estendendo `test_shared_road_is_the_same_for_every_driver`;
  - o piloto automático não bate em 40 sementes com DEVAGAR forçado;
  - o FANTASMA terminando dentro de um caminhão não bate;
  - vida perdida não é batida nem quase-batida;
  - não há quase-batida com poder ativo;
  - com TURBO forçado, os metros na vitória diferem menos de um tick de uma corrida sem poder;
  - o versus usa `result.k`;
  - a adesão ignora ticks protegidos;
  - a anulação automática funciona: golden igual mantém o desafio, golden diferente ou ausente anula;
  - os níveis de bot continuam ordenados.

---

## 8. Riscos

| Risco | Mitigação |
|---|---|
| Takedown de propriedade intelectual (aceito na decisão a) | chaves neutras, nomes em `CARS`, visual em `CAR_DESIGNS` com a mesma chave; trocar = renomear e redesenhar, sem migração |
| O ranking se desloca depois do E4 | sem multiplicadores, Infinito só com protetores, portão medido com fallback (C1) |
| O relógio do mundo toca todo obstáculo | escala 1,0 tem bits idênticos; o fix A é neutro no corpus; testes de estrada compartilhada e de faixa livre; logs que pegam os poderes |
| Desafios abertos e replays antigos | anulação automática por golden; esvaziar a fila de revisão antes do E4 |
| Farming por bots | cosmético, sem transferências, cerca de 8 mil por hora; teto via `runs.paid` se necessário |
| Moto e tanque com hitbox de carro | hitbox canônica; a moto preenche cerca de 18 px de largura |
| Engasgos no wasm | 5 chãos aquecidos no carregamento; nada de tela cheia; barra no lugar de texto de contagem |
| O gerador reescreve todo PNG e WAV | as saídas são determinísticas; `git status` deve mostrar só os sprites novos ou alterados |

---

# (B) Mudanças a partir da crítica

**Crítica de economia, anti-cheat e determinismo**

| Ponto | Decisão | Mudança |
|---|---|---|
| 1. Carro comprado gera `BadInput` fora da garagem | **Aceito** | validação por `CARS` em `run.py:44`, `save.py:58,68`, `backdrop.py:28` e no `SHAPES` do `hello`; `SKINS` fica no golden e no trânsito; teste de ranqueada completa com carro pago |
| 2. Ids reaproveitados quebram o índice único do ledger; `fetchone()` devolve `None` | **Aceito, resolvido por desenho** | a carteira derivada não tem ledger nem índice único; `or (0,)` e saldo 0 para conta apagada. Achado novo ao validar: a exclusão em cascata apagaria as moedas do rival, corrigido pelo gatilho `matches_keep_runs` (testado em scratch) |
| 3. Comparabilidade não demonstrada | **Aceito em parte** | DEVAGAR entra em `NO_NEAR_MISS`; ÍMÃ cortado, então o Infinito só tem protetores; portão pareado com N ≥ 200, p90/máximo e caçador de quase-batidas. **Rejeito tirar a VIDA da estrada solo como padrão:** a estrada solo é a mesma do jogo offline, e tirar a VIDA a removeria de quase todo o jogo pedido pelo dono. Fica como fallback C1 |
| 4. Bot escapa da flag enquanto protegido | **Aceito** | a adesão conta só ticks desprotegidos; sem reajuste de `FLAG_*` |
| 5. Anular desafios depende de alguém lembrar | **Aceito** | anulação automática por `golden.txt` na partida; a migração manual sai |
| 6. Estorno só funciona se a moeda não foi gasta | **Aceito pelo desenho** | o saldo derivado pode ficar negativo e a dívida bloqueia compras; `substituida` ainda paga (aceito, cosmético) |
| 7. Queda de conexão perde as moedas | **Aceito** | `conexao` entra em `PAID` (decisão C3 já com o padrão) |
| 8. Farming | **Aceito** | regra "nunca pagar por vitória"; teto futuro via `runs.paid`, preservando a auditoria |
| 9. Reajuste de preço pela métrica errada | **Aceito** | moedas por jogador ativo por dia |
| 10. Banner cobre a pista | **Aceito** | margem esquerda no solo, alpha 120 no versus |
| 11. Capacidade do servidor | **Aceito** | teste de carga e `MAX_ATIVAS` antes do E4; a cinza do vulcão foi cortada |

**Crítica de escopo**

| Ponto | Decisão | Mudança |
|---|---|---|
| Cortar o ÍMÃ | **Aceito** | — |
| Cortar `admin moedas/dar/estornar` | **Aceito** | estorno é um `DELETE` em `garage`, documentado para a operação |
| Cortar o cache de carros comprados no save | **Aceito** | `net.owned` online; `save.skin` mantém o carro escolhido |
| Diálogo de compra → confirmar duas vezes | **Aceito** | — |
| Transição pontilhada, cinza, lava animada, carros estacionados, recorte de disco | **Aceito** | prévia pelo fundo desfocado |
| 7 biomas → 5 | **Aceito** | Floresta e Praia numa segunda leva, só com dados (C5) |
| Arcos no velocímetro, faixa de ícones no versus, pílula de VIDA, estrela com 6 cores | **Aceito** | um painel e um coração |
| Segunda leva de carros | **Aceito, cortada** | os 4 originais ficam, desenhados por último |
| Linha em `/conta` | **Aceito, cortada** | — |
| Carteira derivada | **Aceito** | mais o gatilho de cascata (item 2 acima) |
| Veredito por tick | **Aceito** | sem reescrever o veredito; só a docstring muda |
| Slot único | **Aceito** | `power`, `power_t`, `lives`; leitores de `player.shield` atualizados |
| Seletor de cenário por nomes e liberação por `best_m` | **Aceito** | — |
| Um cache de chão por bioma | **Aceito** | aquecido no carregamento; `ground` preguiçoso no `draw()` |
| `versus.py:352` | **Aceito** | `result.k` |
| Linhas de velocidade do TURBO | **Aceito** | `speed * scale` |
| Chão preguiçoso é mudança, não o código de hoje | **Aceito** | listado no §4 |
| Pré-carga estrita não é trabalho novo | **Aceito** | o teste existente cobre |
| Gerador importando `CARS` | **Aceito em parte** | o gerador mantém o próprio `CAR_DESIGNS` sem importar; **rejeito o `assert` no gerador**, porque o teste de manifesto existente já falha se faltar o PNG de uma chave |
| "(Sobrenatural)" | **Aceito** | — |
| `Bot` reage em tempo de mundo | **Aceito** | anotado no §5.7 |
| Props, slots de CENÁRIOS, onde medir a fronteira, log do corpus, números de migração | **Aceito** | §4 (sprites, `Road.biome(y)`); §7 (até 2 logs por busca de semente); migrações 5 (E1) e 6 (E2), sem migração no E4 |
| Ordem, não dividir o E4, E1 cedo | **Aceito** | — |
| Nenhuma pergunta ao dono | **Aceito em parte** | os padrões estão aplicados; restam as poucas escolhas de produto em (C) |

---

# (C) Decisões que restam ao dono (o padrão recomendado já está aplicado no plano)

1. **Se o portão de comparabilidade do E4 falhar:** **tirar a VIDA EXTRA da estrada solo**, o que vale para a ranqueada e para o offline solo, porque a estrada é a mesma. A alternativa é deixar só o escudo no slot da estrada solo.
2. **Corridas em revisão (top 10, flag de bot):** **pagar na hora; se rejeitada, vira dívida.** A alternativa é pagar só depois da aprovação.
3. **Corridas encerradas por queda de conexão:** **pagam.** A alternativa é não pagar.
4. **Veredito nas corridas com amigos:** **por tick, "quem bate primeiro perde".** A alternativa é por distância percorrida, que favorece o TURBO.
5. **Cenários no lançamento:** **5 biomas, com Floresta e Praia numa segunda leva.** A alternativa é lançar os 7 no E3 (cerca de 45 linhas a mais de arte).
6. **Teto diário de moedas:** **nenhum.**
7. **Moedas por corridas antes do E1:** **não.**
8. **Onde guardar os cenários liberados:** **no aparelho.** A alternativa é por conta.
9. **Nomes e modelos:** **nomes oficiais em pt-BR** (Relâmpago McQueen, Máquina Mistério, Batmóvel, Impala 67 (Sobrenatural)). O Cadillac será o **Series 62 de 1959**, o de rabo de peixe. O Fusca é o **Herbie 53** (pedido do dono, no lugar do Fusca amarelo). Os 4 extras (Táxi, Kombi, Fórmula 1, Monster Truck) **entram por último e saem se a arte atrasar.**

O teste da carteira derivada e do gatilho de cascata foi validado num rascunho fora do repositório; ele entra em `server/tests/test_wallet.py` no E1.
