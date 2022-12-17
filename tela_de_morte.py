import pygame
from pygame.locals import *
from sys import exit
import config as cf
import defs

def morto():   

    while cf.morreu: 
        cf.relogio.tick(cf.FPS)
        cf.tela.fill(cf.BRANCO)
        cf.musica_partida = pygame.mixer.music.stop()
        cf.tela.blit(cf.tela_reiniciar, (75, 280))
        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                exit()
            if event.type == KEYDOWN: 
                if event.key == K_r:
                    defs.reiniciar_jogo()
        pygame.display.update()