import pygame
import config as cf
import os
from random import randint
from random import randrange

pygame.mixer.init()

def musica_partida():
    musica_partida = pygame.mixer.music.load(os.path.join(cf.diretorio_sons, 'musica_partida.mp3'))
    pygame.mixer.music.set_volume(0.25)
    pygame.mixer.music.play(-1)

def inicio_partida():
    inicio_partida = pygame.mixer.music.load(os.path.join(cf.diretorio_sons, 'inicio_partida.wav'))
    pygame.mixer.music.set_volume(0.35)
    pygame.mixer.music.play(-1)

def musica_menu():
    musica_menu = pygame.mixer.music.load(os.path.join(cf.diretorio_sons, 'musica_menu.mp3'))
    pygame.mixer.music.set_volume(0.25)
    pygame.mixer.music.play(-1)

def colisao_buraco():
    colisao_buraco = pygame.mixer.music.load(os.path.join(cf.diretorio_sons, 'colisao_buracos.wav'))
    pygame.mixer.music.set_volume(0.35)
    pygame.mixer.music.play(-1)

def colisao_carros():   
    colisao_carros = pygame.mixer.music.load(os.path.join(cf.diretorio_sons, 'colisao_carros.wav'))
    pygame.mixer.music.set_volume(0.35)
    pygame.mixer.music.play(-1)

def colisao_troncos():
    colisao_troncos = pygame.mixer.music.load(os.path.join(cf.diretorio_sons, 'colisao_troncos.wav'))
    pygame.mixer.music.set_volume(0.35)
    pygame.mixer.music.play(-1)

def aceleracao_carro():
    aceleracao_carro = pygame.mixer.music.load(os.path.join(cf.diretorio_sons, 'aceleracao_carro.wav'))
    pygame.mixer.music.set_volume(0.35)
    pygame.mixer.music.play(-1)

def som_moeda():
    som_moeda = pygame.mixer.music.load(os.path.join(cf.diretorio_sons, 'som_moeda.wav'))
    pygame.mixer.music.set_volume(0.35)
    pygame.mixer.music.play(-1)


#Essa função vai reiniciar os parâmetros do jogo
def reiniciar_jogo():
    cf.contador = 0
    cf.segundo = 0
    cf.minuto = 0
    cf.rua_numero = 0
    cf.morreu = False
    cf.carro_pos_x = 555
    cf.carro_pos_y = 556
    cf.car_pos_x = randrange(355, 755, 100)
    cf.car_pos_y = randint(- 350, - 200)
    cf.pedra_pos_x = randrange(360, 760, 100)
    cf.pedra_pos_y = randint(- 1100, - 950)
    cf.buraco_pos_x = randrange(355, 755, 100)
    cf.buraco_pos_y = randint(- 890, - 750)
    cf.tronco_pos_x = randrange(360, 760, 100)
    cf.tronco_pos_y = randint(- 600, - 470)
    cf.moeda_pos_x = randrange(360, 760, 100)
    cf.moeda_pos_y = randint(- 3000, 2800)
    cf.VELOCIDADE = 10
    pygame.display.update()

def tempo():
    if cf.contador == 60:
        cf.segundo += 1
        cf.contador = 0
        if cf.segundo == 60:
            cf.segundo = 0
            cf.minuto += 1
    if (cf.segundo % 10) == 0:
        cf.VELOCIDADE = cf.VELOCIDADE + 0.05

def missao():
    if cf.missao == 'tempo':
            cf.contador += 1
            tempo()
            pontuacao = '{:02d}:{:02d}'.format(cf.minuto, cf.segundo)
            quadro_de_pontuacao = cf.fonte.render(pontuacao, True, cf.BRANCO)
            cf.tela.blit(quadro_de_pontuacao, (100,60))

    if cf.missao == 'moeda':
        cf.tela.blit(cf.moeda, (80,60))
        pontuacao = '{:02d}'.format(cf.contador)
        quadro_de_pontuacao = cf.fonte.render(pontuacao, True, cf.BRANCO)
        if cf.contador % 10 == 0:
            cf.VELOCIDADE = int(round(cf.VELOCIDADE + 0.2))
        cf.tela.blit(quadro_de_pontuacao, (135,60))

def menu_skin():
    if cf.escolha_skin == 0:
        return cf.carro_amarelo_cortado
    elif cf.escolha_skin == 1:
        return cf.carro_preto_cortado
    elif cf.escolha_skin == 2:
        return cf.carro_azul_cortado
    elif cf.escolha_skin == 3:
        return cf.carro_rosa_cortado
    elif cf.escolha_skin == 4:
        return cf.carro_vermelho_cortado
    elif cf.escolha_skin == 5:
        return cf.carro_branco_cortado
