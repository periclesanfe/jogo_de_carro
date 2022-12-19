import pygame
import config as cf
from pygame.locals import *
from sys import exit
from button import botao


def diciculdade():

    while True:
        cf.tela.fill(cf.CINZA)
        cf.relogio.tick(cf.FPS)
        pos_mouse_telaAviso = pygame.mouse.get_pos()

        botao_facil= botao(image=cf.image_botao, pos=(cf.LARGURA//2, 175), 
                                text_input="FACIL", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=70)
        botao_normal= botao(image=cf.image_botao, pos=(cf.LARGURA//2, 275), 
                                text_input="NORMAL", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=70)
        botao_Dificil= botao(image=cf.image_botao, pos=(cf.LARGURA//2, 375), 
                                text_input="DIFICIL", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=70)
        botao_Infinito= botao(image=cf.image_botao, pos=(cf.LARGURA//2, 475), 
                                text_input="INFINITO", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=70)
        
        for button in [botao_facil]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_normal]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_Dificil]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_Infinito]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        
        for event in pygame.event.get():
            if event.type == QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                pygame.quit()
                exit()

            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_facil.checkForInput(pos_mouse_telaAviso):
                    return 1
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_normal.checkForInput(pos_mouse_telaAviso):
                    return 2
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_Dificil.checkForInput(pos_mouse_telaAviso):
                    return 3
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_Infinito.checkForInput(pos_mouse_telaAviso):
                    return 0
        
        pygame.display.flip()      
