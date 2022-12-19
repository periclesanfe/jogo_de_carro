#Importar as bibliotecas/módulos necessários para o código
import pygame
import config as cf
import tela_de_jogo
import menu_skins
import menu_dificuldades
import menu_modo
from pygame.locals import *
from sys import exit
import defs
from button import botao


def menu():
    defs.musica_menu()

    while True:
        cf.tela.fill(cf.CINZA)
        cf.relogio.tick(cf.FPS)
        skin = defs.menu_skin()
        skin = pygame.transform.scale(skin, (100,70))
        
        
        pos_mouse_telaAviso = pygame.mouse.get_pos()

        botao_jogar= botao(image=cf.image_botao, pos=(cf.LARGURA//2, 120), 
                                text_input="JOGAR", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=80)
        botao_skin= botao(image=cf.image_botao, pos=(cf.LARGURA//2, 220), 
                                text_input="SKIN   ", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=90)
        botao_Modo_Jogo= botao(image=cf.image_botao, pos=((cf.LARGURA//2), 320), 
                                text_input="MODO DE JOGO", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=400, size_y=80)
        botao_dificuldade= botao(image=cf.image_botao, pos=((cf.LARGURA//2), 420), 
                                text_input="DIFICULDADE", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=340, size_y=80)
        botao_Sair= botao(image=cf.image_botao, pos=(cf.LARGURA//2, 520), 
                                text_input="SAIR", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=80)

        for button in [botao_jogar]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_skin]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_Modo_Jogo]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_dificuldade]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_Sair]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)


        for event in pygame.event.get():
            if event.type == QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                pygame.quit()
                exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_jogar.checkForInput(pos_mouse_telaAviso):
                    cf.morreu == False
                    tela_de_jogo.jogar()
                if botao_skin.checkForInput(pos_mouse_telaAviso):
                    cf.escolha_skin = menu_skins.skin()
                if botao_dificuldade.checkForInput(pos_mouse_telaAviso):
                    cf.dificuldade = menu_dificuldades.diciculdade()
                if botao_Modo_Jogo.checkForInput(pos_mouse_telaAviso):
                    modo_de_jogo = menu_modo.modo_de_jogo()
                    if modo_de_jogo == 0:
                        cf.missao = 'tempo'
                    elif modo_de_jogo == 1:
                        cf.missao = 'moeda'
                if botao_Sair.checkForInput(pos_mouse_telaAviso):
                    pygame.quit()
                    exit()

        cf.tela.blit(skin, (430,185))
        pygame.display.flip()      


try:
    menu()
finally:
    pygame.quit()
