import pygame
import config as cf
from random import randrange, choice

pygame.mixer.init()

def musica_partida():
    pygame.mixer.music.stop()
    pygame.mixer.music.load('./songs/musica_partida.mp3')
    pygame.mixer.music.set_volume(0.25)
    pygame.mixer.music.play(-1)

def inicio_partida():
    pygame.mixer.music.stop()
    pygame.mixer.music.load('./songs/inicio_partida.wav')
    pygame.mixer.music.set_volume(0.35)
    pygame.mixer.music.play(1)

def musica_menu():
    pygame.mixer.music.stop()
    pygame.mixer.music.load('./songs/musica_menu.mp3')
    pygame.mixer.music.set_volume(0.25)
    pygame.mixer.music.play(-1)


def moeda_contador():
    cf.contador + 1
    if cf.contador // 5 == 0:
        cf.VELOCIDADE =+ 3
    print(f'ta contando {cf.contador}')

#Essa função vai reiniciar os parâmetros do jogo
def reiniciar_jogo():
    cf.contador = 0
    cf.segundo = 0
    cf.minuto = 0
    cf.rua_numero = 0
    cf.morreu = False
    cf.carro_pos_x = 555
    cf.carro_pos_y = 556
    cf.car_pos_x = randrange(355, 855, 100)
    cf.car_pos_y = choice((-70, -879))
    cf.pedra_pos_x = randrange(355, 855, 100)
    cf.pedra_pos_y = choice((-179, -762))
    cf.buraco_pos_x = randrange(355, 855, 100)
    cf.buraco_pos_y = choice((-139, -670)) 
    cf.tronco_pos_x = randrange(355, 855, 100)
    cf.tronco_pos_y = choice((-243, -619))
    cf.VELOCIDADE = 10
    cf.jogar = False
    cf.ganhou = False
    cf.morreu = False
    pygame.display.update()

def tempo():
    cf.contador += 1
    if cf.contador == 60:
        cf.segundo += 1
        cf.contador = 0
        if cf.segundo == 60:
            cf.segundo = 0
            cf.minuto += 1
    if (cf.segundo % 10) == 0:
        cf.VELOCIDADE = cf.VELOCIDADE + 0.05
    cf.pontuacao = '{:02d}:{:02d}'.format(cf.minuto, cf.segundo)
    cf.quadro_de_pontuacao = cf.fonte.render(cf.pontuacao, True, cf.BRANCO)
    


def sett_dificuldade():
    if cf.dificuldade == 0:
        cf.condicao_vitoria = 0
    if cf.dificuldade == 1:
        cf.condicao_vitoria = 1
    if cf.dificuldade == 2:
        cf.condicao_vitoria = 2
    else:
        cf.dificuldade = 3
    


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
