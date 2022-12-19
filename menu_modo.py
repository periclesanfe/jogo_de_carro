import pygame
import config as cf
from pygame.locals import *
from sys import exit
from button import botao


def modo_de_jogo():

    while True:
        cf.tela.fill(cf.CINZA)
        cf.relogio.tick(cf.FPS)
        pos_mouse_telaAviso = pygame.mouse.get_pos()

        botao_tempo= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)-50), 
                                text_input="TEMPO", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=70)
        botao_moeda= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)+50), 
                                text_input="MOEDA", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=70)

        
        for button in [botao_tempo]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_moeda]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)

        for event in pygame.event.get():
            if event.type == QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                pygame.quit()
                exit()

            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_tempo.checkForInput(pos_mouse_telaAviso):
                    return 0
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_moeda.checkForInput(pos_mouse_telaAviso):
                    return 1

        
        pygame.display.flip()  