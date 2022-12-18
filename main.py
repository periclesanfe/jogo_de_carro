#Importar as bibliotecas/módulos necessários para o código
import pygame
import config as cf
import tela_de_jogo
import tela_de_morte


def tela_jogo():
    while True:
        if cf.morreu == False:
            tela_de_jogo.jogar()
        elif cf.morreu == True:
            tela_de_morte.morto()

try:
    tela_jogo()
finally:
    pygame.quit()
