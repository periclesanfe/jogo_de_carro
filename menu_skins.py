import pygame
import config as cf
from pygame.locals import *
from sys import exit
from button import botao


def skin():

    while True:
        cf.tela.fill(cf.CINZA)
        cf.relogio.tick(cf.FPS)
        pos_mouse_telaAviso = pygame.mouse.get_pos()

        botao_amarelo= botao(image=cf.carro_amarelo_cortado, pos=((cf.LARGURA//2)-240, 160), 
                                text_input="", font=cf.fonte, base_color='White', hovering_color="Red", size_x=300, size_y=200)
        botao_preto= botao(image=cf.carro_preto_cortado, pos=((cf.LARGURA//2), 160), 
                                text_input="", font=cf.fonte, base_color='White', hovering_color="Red", size_x=300, size_y=200)
        botao_azul= botao(image=cf.carro_azul_cortado, pos=((cf.LARGURA//2)+240, 160), 
                                text_input="", font=cf.fonte, base_color='White', hovering_color="Red", size_x=300, size_y=200)
        botao_rosa= botao(image=cf.carro_rosa_cortado, pos=((cf.LARGURA//2)-240, 480), 
                                text_input="", font=cf.fonte, base_color='White', hovering_color="Red", size_x=300, size_y=200)
        botao_vermelho= botao(image=cf.carro_vermelho_cortado, pos=((cf.LARGURA//2), 480), 
                                text_input="", font=cf.fonte, base_color='White', hovering_color="Red", size_x=300, size_y=200)
        botao_branco= botao(image=cf.carro_branco_cortado, pos=((cf.LARGURA//2)+240, 480), 
                                text_input="", font=cf.fonte, base_color='White', hovering_color="Red", size_x=300, size_y=200)
        

        for button in [botao_amarelo]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_preto]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_azul]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_rosa]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_vermelho]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_branco]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        


        for event in pygame.event.get():
            if event.type == QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                pygame.quit()
                exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_amarelo.checkForInput(pos_mouse_telaAviso):
                    return 0
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_preto.checkForInput(pos_mouse_telaAviso):
                    return 1
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_azul.checkForInput(pos_mouse_telaAviso):
                    return 2
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_rosa.checkForInput(pos_mouse_telaAviso):
                    return 3
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_vermelho.checkForInput(pos_mouse_telaAviso):
                    return 4
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_branco.checkForInput(pos_mouse_telaAviso):
                    return 5
                

            
    
        pygame.display.flip()      


