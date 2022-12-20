#Importar as bibliotecas/módulos necessários para o código
import pygame
import config as cf
from pygame.locals import *
from sys import exit
import defs
from button import botao
import obstaculo_carro as co
import player_carro as cp
import obstaculo_pedra as po
import obstaculo_buraco as bo
import obstaculo_tronco as to


def menu():
    
    defs.musica_menu()
    defs.reiniciar_jogo()

    while True:
        cf.tela.fill(cf.CINZA)
        cf.relogio.tick(cf.FPS)
        skin = defs.menu_skin()
        skin = pygame.transform.scale(skin, (100,70))
        
        
        pos_mouse_telaAviso = pygame.mouse.get_pos()

        botao_jogar= botao(image=cf.image_botao, pos=(cf.LARGURA//2, 180), 
                                text_input="JOGAR", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=80)
        botao_skin= botao(image=cf.image_botao, pos=(cf.LARGURA//2, 280), 
                                text_input="SKIN    ", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=90)
        botao_dificuldade= botao(image=cf.image_botao, pos=((cf.LARGURA//2), 380), 
                                text_input="DIFICULDADE", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=340, size_y=80)
        botao_Sair= botao(image=cf.image_botao, pos=(cf.LARGURA//2, 480), 
                                text_input="SAIR", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=240, size_y=80)

        for button in [botao_jogar]:
            button.changeColor(pos_mouse_telaAviso)
            button.update(cf.tela)
        for button in [botao_skin]:
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
                    defs.inicio_partida()
                    pygame.time.wait(2500)
                    jogar()
                if botao_skin.checkForInput(pos_mouse_telaAviso):
                    cf.escolha_skin = menu_skin()
                if botao_dificuldade.checkForInput(pos_mouse_telaAviso):
                    cf.dificuldade = diciculdade()
                    defs.sett_dificuldade()
                if botao_Sair.checkForInput(pos_mouse_telaAviso):
                    pygame.quit()
                    exit()

        cf.tela.blit(skin, (430,245))
        pygame.display.flip()      


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
                    return 0
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_normal.checkForInput(pos_mouse_telaAviso):
                    return 1
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_Dificil.checkForInput(pos_mouse_telaAviso):
                    return 2
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_Infinito.checkForInput(pos_mouse_telaAviso):
                    return 3
        
        pygame.display.flip()      


def menu_skin():

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


def jogar():
    defs.musica_partida()

    player = pygame.sprite.Group()
    obstaculos = pygame.sprite.Group()
    carro_player = cp.Carro_Player()
    carro_obstaculo = co.Carro_Obstaculo()
    pedra_obstaculo = po.pedra_Obstaculo()
    buraco_obstaculo = bo.buraco_Obstaculo()
    tronco_obstaculo = to.Tronco_Obstaculo()


    player.add(carro_player)

    obstaculos.add(carro_obstaculo,pedra_obstaculo, buraco_obstaculo, tronco_obstaculo)



    while True: 
        cf.tela.fill(cf.CINZA)
        cf.relogio.tick(cf.FPS*6)

        player.update() #Este comando vai atualizar frequente comandos a tela, auxiliando na fluidez do jogo
        obstaculos.update()


        grupo_obstaculos = pygame.sprite.Group()
        grupo_obstaculos.add(buraco_obstaculo, carro_obstaculo, pedra_obstaculo, tronco_obstaculo)

        
        
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
                    morto()
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

        if pygame.sprite.spritecollide(carro_player, grupo_obstaculos, False,  pygame.sprite.collide_mask):
            cf.som_colisao.play()
            pygame.time.wait(1000)
            morto()


        if cf.rua_numero == 0:
            if cf.rua_rect.topleft[1] >= 0:
                cf.rua_rect.bottomleft = (300, cf.ALTURA)
                cf.rua_numero = 1
            else:
                cf.tela.blit(cf.rua, cf.rua_rect)
                cf.rua_rect.y += cf.VELOCIDADE//6
        else:
            if cf.rua_rect2.topleft[1] >= 0:
                cf.rua_rect2.bottomleft = (300, cf.ALTURA)
                cf.rua_numero = 0
            else:
                cf.tela.blit(cf.rua, cf.rua_rect2)
                cf.rua_rect2.y += cf.VELOCIDADE//6

        
        player.draw(cf.tela) #Este comando auxilia na exibição das sprites na tela
        obstaculos.draw(cf.tela)
        cf.tela.blit(cf.quadro_de_pontuacao, (100,60))
        pygame.display.flip()  #Essa função atualiza a tela do jogo a cada interação
        defs.tempo()

        if cf.condicao_vitoria == 0:
            if cf.minuto == 1 and cf.segundo == 30:
                vitoria()
        elif cf.condicao_vitoria == 1:
            if cf.minuto == 3 and cf.segundo == 00:
                vitoria()
        elif cf.condicao_vitoria == 2:
            if cf.minuto == 4 and cf.segundo == 30:
                vitoria()
        elif cf.condicao_vitoria == 3:
            pass


def vitoria():   
    while True: 
        cf.relogio.tick(cf.FPS)
        cf.tela.fill(cf.BRANCO)
        pygame.mixer.music.stop()
        cf.tela.blit(cf.tela_vitoria, (220, 100))
        pos_mouse_telaAviso = pygame.mouse.get_pos()
        botao_jogar= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)), 
                                text_input="JOGAR NOVAMENTE", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=500, size_y=100)
        botao_menu= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)+110), 
                                text_input="MENU", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=260, size_y=80)
        botao_sair= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)+210), 
                                text_input="SAIR", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=260, size_y=80)

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
                    jogar()
                if botao_menu.checkForInput(pos_mouse_telaAviso):
                    menu()
                if botao_sair.checkForInput(pos_mouse_telaAviso):
                    pygame.quit()
                    exit()
        
        pygame.display.update()


def morto():   
    pygame.mixer.music.stop()
    while True: 
        cf.relogio.tick(cf.FPS)
        cf.tela.fill(cf.BRANCO)
        cf.tela.blit(cf.tela_reiniciar, (100, 200))
        pos_mouse_telaAviso = pygame.mouse.get_pos()

        botao_reiniciar= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)+100), 
                                text_input="REINICIAR", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=300, size_y=100)
        botao_menu= botao(image=cf.image_botao, pos=(cf.LARGURA//2, (cf.ALTURA//2)+220), 
                                text_input="MENU", font=cf.fonte, base_color='Grey', hovering_color="Black", size_x=300, size_y=100)

        for button in [botao_reiniciar]:
                button.changeColor(pos_mouse_telaAviso)
                button.update(cf.tela)
        for button in [botao_menu]:
                button.changeColor(pos_mouse_telaAviso)
                button.update(cf.tela)

        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if botao_reiniciar.checkForInput(pos_mouse_telaAviso):
                    defs.reiniciar_jogo()
                    jogar()
                if botao_menu.checkForInput(pos_mouse_telaAviso):
                    menu()
        
        pygame.display.update()


try:
    menu()
finally:
    pygame.quit()
