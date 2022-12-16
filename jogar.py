import pygame
from pygame.locals import *
from sys import exit
import config as cf
import main
import defs
import os


def tela_jogo():

    contador = 0
    cf.musica_partida = pygame.mixer.music.play()
    while cf.morreu == False: 
        
        """RODANDO = 0
        PAUSADO = 1
        jogo = RODANDO"""
        cf.tela.fill(cf.CINZA)
        main.relogio.tick(cf.FPS*10)
        pontuacao = f'{str(contador).zfill(2)}'
        quadro_de_pontuacao = cf.fonte.render(pontuacao, True, cf.BRANCO, cf.PRETO)
        """tela__de_pause = fonte.render('Aperte P para Continuar', False, PRETO, BRANCO)"""

        main.todas_as_sprites.update() #Este comando vai atualizar frequente comandos a tela, auxiliando na fluidez do jogo

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

                """if event.key == K_p:
                    if jogo != PAUSADO:
                        jogo = PAUSADO
                    else:
                        jogo = RODANDO"""


                if event.key == K_a:
                    if cf.carro_pos_x <= 355:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x - 100
                        contador = main.aumentar_contador(contador)
                        main.carro.movimento()
                if event.key == K_LEFT:
                    if cf.carro_pos_x == 355:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x - 100
                        contador = main.aumentar_contador(contador)
                        main.carro.movimento()
                if event.key == K_d:
                    if cf.arro_pos_x == 755:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x + 100
                        contador = main.aumentar_contador(contador)
                        main.carro.movimento()
                if event.key == K_RIGHT:
                    if cf.carro_pos_x == 755:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x + 100
                        contador = main.aumentar_contador(contador)
                        main.carro.movimento()
                if event.key == K_w:
                    if cf.carro_pos_y == 76:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y - 120
                        contador = main.aumentar_contador(contador)
                        main.carro.movimento()
                if event.key == K_UP:
                    if cf.carro_pos_y == 76:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y - 120
                        contador = main.aumentar_contador(contador)
                        main.carro.movimento()
                if event.key == K_s:
                    if cf.carro_pos_y == 556:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y + 120
                        contador = main.aumentar_contador(contador)
                        main.carro.movimento()
                if event.key == K_DOWN:
                    if cf.carro_pos_y == 556:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y + 120
                        contador = main.aumentar_contador(contador)
                        main.carro.movimento()
            ''' if event.key == pygame.K_p:
                    if jogo != PAUSADO:
                        pygame.mixer.music.pause()
                        pause = fonte_pause.render("PAUSE", True, AZUL, CINZA)
                        tela.blit(pause, ((tela.get_width()-pause.get_width())/2, (tela.get_height()-pause.get_height())/2))
                        jogo = PAUSADO
                        

                    else:
                        jogo = RODANDO
                        pygame.mixer.music.unpause()
                        
                      
        if jogo == PAUSADO:
         pygame.display.flip()      ''' 

        
        """if jogo == PAUSADO:
            pygame.display.flip()
            continue"""
        
        if cf.rua_numero == 0:
            if main.rua_rect.topleft[1] >= 0:
                main.rua_rect.bottomleft = (300, cf.ALTURA)
                cf.rua_numero = 1
            else:
                cf.tela.blit(main.rua, main.rua_rect)
                main.rua_rect.y += cf.FPS//16
        else:
            if main.rua_rect2.topleft[1] >= 0:
                main.rua_rect2.bottomleft = (300, cf.ALTURA)
                cf.rua_numero = 0
            else:
                cf.tela.blit(main.rua, main.rua_rect2)
                main.rua_rect2.y += cf.FPS//16

        cf.tela.blit(quadro_de_pontuacao, (115,60))
        main.todas_as_sprites.draw(cf.tela) #Este comando auxilia na exibição das sprites na tela

        #Essa função atualiza a tela do jogo a cada interação
        pygame.display.flip()


def tela_de_morte(tela, relogio):   

    while cf.morreu: 
        relogio.tick(cf.FPS*10)
        cf.tela.fill(cf.BRANCO)
        cf.musica_partida = pygame.mixer.music.stop()
        mensagem_morreu = f'Você morreu, aperte R para reiniciar'
        tela_reiniciar = cf.fonte.render(mensagem_morreu, False, cf.PRETO)
        tela_reiniciar.get_rect()
        cf.tela.blit(tela_reiniciar, (75, 280))
        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                exit()
            if event.type == KEYDOWN: 
                if event.key == K_r:
                    defs.reiniciar_jogo()
        pygame.display.update()