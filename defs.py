import pygame
import config as cf

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