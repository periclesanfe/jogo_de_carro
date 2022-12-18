import pygame
from pygame.locals import *
from sys import exit
import config as cf
from button import botao

def morto():   
    while cf.morreu: 
        cf.relogio.tick(cf.FPS)
        cf.tela.fill(cf.BRANCO)
        cf.musica_partida = pygame.mixer.music.stop()
        cf.tela.blit(cf.tela_reiniciar, (100, 200))
        pos_mouse_telaAviso = pygame.mouse.get_pos()
        botao_reiniciar= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)+100), 
                                text_input="REINICIAR", font=cf.fonte, base_color='Grey', hovering_color="Black")

        for button in [botao_reiniciar]:
                button.changeColor(pos_mouse_telaAviso)
                button.update(cf.tela)

        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_reiniciar.checkForInput(pos_mouse_telaAviso):
                    cf.morreu = False
        
        pygame.display.update()

