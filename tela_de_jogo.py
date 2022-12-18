import pygame
from pygame.locals import *
from sys import exit
import config as cf
import carro_obstaculo as co
import tronco_obstaculo as to
import carro_player as cp
import defs

def jogar():
    defs.aceleracao_carro()
    defs.musica_partida()
    player = pygame.sprite.Group()
    obstaculos = pygame.sprite.Group()
    carro_player = cp.Carro_Player()
    carro_obstaculo = co.Carro_Obstaculo()
    tronco_obstaculo = to.Tronco()
    player.add(carro_player)
    obstaculos.add(carro_obstaculo)
    obstaculos.add(tronco_obstaculo)

    while cf.morreu == False: 
        cf.tela.fill(cf.CINZA)
        cf.relogio.tick(cf.FPS*6)

        defs.missao()


        player.update() #Este comando vai atualizar frequente comandos a tela, auxiliando na fluidez do jogo
        obstaculos.update()

        #Esse loop tem a função de verificar se um evento aconteceu
        for event in pygame.event.get():
            
            #Essa condição de repetição vai auxiliar no botão de fechar a tela (no X e Esc)
            if event.type == QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                pygame.quit()
                exit()             #Chama a função importada anteriormente

            #Essas condições vão controlar quaisquer movimentos feitos pelo carrinho na tela
            if event.type == KEYDOWN: 
                if event.key == K_r:
                    pygame.display.flip()
                    cf.morreu = True

                if event.key == K_a:
                    if cf.carro_pos_x <= 355:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x - 100
                        carro_player.movimento()
                if event.key == K_LEFT:
                    if cf.carro_pos_x == 355:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x - 100
                        carro_player.movimento()
                if event.key == K_d:
                    if cf.carro_pos_x == 755:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x + 100
                        carro_player.movimento()
                if event.key == K_RIGHT:
                    if cf.carro_pos_x == 755:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x + 100
                        carro_player.movimento()
                if event.key == K_w:
                    if cf.carro_pos_y == 76:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y - 120
                        carro_player.movimento()
                if event.key == K_UP:
                    if cf.carro_pos_y == 76:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y - 120
                        carro_player.movimento()
                if event.key == K_s:
                    if cf.carro_pos_y == 556:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y + 120
                        carro_player.movimento()
                if event.key == K_DOWN:
                    if cf.carro_pos_y == 556:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y + 120
                        carro_player.movimento()


        if cf.rua_numero == 0:
            if cf.rua_rect.topleft[1] >= 0:
                cf.rua_rect.bottomleft = (300, cf.ALTURA)
                cf.rua_numero = 1
            else:
                cf.tela.blit(cf.rua, cf.rua_rect)
                cf.rua_rect.y += cf.FPS//6
        else:
            if cf.rua_rect2.topleft[1] >= 0:
                cf.rua_rect2.bottomleft = (300, cf.ALTURA)
                cf.rua_numero = 0
            else:
                cf.tela.blit(cf.rua, cf.rua_rect2)
                cf.rua_rect2.y += cf.FPS//6

        
        player.draw(cf.tela) #Este comando auxilia na exibição das sprites na tela
        obstaculos.draw(cf.tela)
        pygame.display.flip()  #Essa função atualiza a tela do jogo a cada interação