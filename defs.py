import pygame
import config as cf
import os

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
    global contador
    contador = 0
    cf.rua_numero = 0
    cf.morreu = False
    cf.carro_pos_x = 555
    cf.carro_pos_y = 556
    cf.car_pos_x = 300
    cf.car_pos_y = 556
    pygame.display.update()
    cf.VELOCAIDE = 10

def tempo():
    print(cf.VELOCIDADE, cf.FPS)
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