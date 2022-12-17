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