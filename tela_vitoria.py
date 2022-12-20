import pygame
from pygame.locals import *
from sys import exit
import config as cf
import defs
from button import botao

def vitoria():   
    while cf.morreu: 
        cf.relogio.tick(cf.FPS)
        cf.tela.fill(cf.BRANCO)
        pygame.mixer.music.stop()
        cf.tela.blit(cf.tela_vitoria, (100, 160))
        pos_mouse_telaAviso = pygame.mouse.get_pos()
        botao_jogar= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)+100), 
                                text_input="JOGAR NOVAMENTE", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=300, size_y=100)
        botao_menu= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)+220), 
                                text_input="MENU", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=300, size_y=100)
        botao_sair= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)+320), 
                                text_input="SAIR", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=300, size_y=100)

        for button in [botao_jogar]:
                button.changeColor(pos_mouse_telaAviso)
                button.update(cf.tela)
        for button in [botao_menu]:
                button.changeColor(pos_mouse_telaAviso)
                button.update(cf.tela)
        for button in [botao_sair]:
                button.changeColor(pos_mouse_telaAviso)
                button.update(cf.tela)

        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_jogar.checkForInput(pos_mouse_telaAviso):
                    defs.reiniciar_jogo()
                    cf.ganhou = False
                if botao_menu.checkForInput(pos_mouse_telaAviso):
                    defs.reiniciar_jogo()
                    cf.ganhou = False
                    defs.jogando = False
                if botao_sair.checkForInput(pos_mouse_telaAviso):
                    pygame.quit()
                    exit()
        
        pygame.display.update()