#Importar as bibliotecas/módulos necessários para o código
import pygame
from pygame.locals import *   #Importa todas as funções e as constantes existentes no submódulo locals
from sys import exit          #Essa função dentro do módulo sys torna possível fechar a janela
import os
import config as cf
import classes as cl


#Essa função vai reiniciar os parâmetros do jogo
def reiniciar_jogo():
    global contador
    contador = 0
    cf.rua_numero = 0
    cf.morreu = False
    cf.carro_pos_x = 555
    cf.carro_pos_y = 556
    pygame.display.update()


def aumentar_contador(contador):
    return contador + 1 


def jogar(tela, relogio, fonte, todas_as_sprites, rua, rua_rect, rua_rect2, carro):

    contador = 0

    while cf.morreu == False: 
        
        """RODANDO = 0
        PAUSADO = 1
        jogo = RODANDO"""
        tela.fill(cf.CINZA)
        relogio.tick(cf.FPS*10)
        pontuacao = f'{str(contador).zfill(3)}'
        quadro_de_pontuacao = fonte.render(pontuacao, True, cf.BRANCO, cf.PRETO)
        """tela__de_pause = fonte.render('Aperte P para Continuar', False, PRETO, BRANCO)"""

        todas_as_sprites.update() #Este comando vai atualizar frequente comandos a tela, auxiliando na fluidez do jogo

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
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_LEFT:
                    if cf.carro_pos_x == 355:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x - 100
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_d:
                    if cf.arro_pos_x == 755:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x + 100
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_RIGHT:
                    if cf.carro_pos_x == 755:
                        pass
                    else:
                        cf.carro_pos_x = cf.carro_pos_x + 100
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_w:
                    if cf.carro_pos_y == 76:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y - 120
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_UP:
                    if cf.carro_pos_y == 76:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y - 120
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_s:
                    if carro_pos_y == 556:
                        pass
                    else:
                        cf.carro_pos_y = cf.carro_pos_y + 120
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_DOWN:
                    if carro_pos_y == 556:
                        pass
                    else:
                        carro_pos_y = carro_pos_y + 120
                        contador = aumentar_contador(contador)
                        carro.movimento()
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

        
        if rua_numero == 0:
            if rua_rect.topleft[1] >= 0:
                rua_rect.bottomleft = (300, cf.ALTURA)
                rua_numero = 1
            else:
                tela.blit(rua, rua_rect)
                rua_rect.y += cf.FPS//16
        else:
            if rua_rect2.topleft[1] >= 0:
                rua_rect2.bottomleft = (300, cf.ALTURA)
                rua_numero = 0
            else:
                tela.blit(rua, rua_rect2)
                rua_rect2.y += cf.FPS//16

        tela.blit(quadro_de_pontuacao, (115,60))
        todas_as_sprites.draw(tela) #Este comando auxilia na exibição das sprites na tela
        
        #Essa função atualiza a tela do jogo a cada interação
        pygame.display.flip()


def tela_de_morte(tela, relogio):   

    while cf.morreu: 
        relogio.tick(cf.FPS*10)
        tela.fill(cf.BRANCO)
        mensagem_morreu = f'Você morreu, aperte R para reiniciar'
        tela_reiniciar = cf.fonte.render(mensagem_morreu, False, cf.PRETO)
        tela_reiniciar.get_rect()
        tela.blit(tela_reiniciar, (75, 280))
        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                exit()
            if event.type == KEYDOWN: 
                if event.key == K_r:
                    reiniciar_jogo()
        pygame.display.update()


def tela_jogo():
    #Este comando controla a velocidade do objeto na tela
    relogio = pygame.time.Clock() 
    todas_as_sprites = pygame.sprite.Group() #Este comando vai auxiliar, quando formos adicionar o carrinho na tela
    carro = cl.Carro()
    todas_as_sprites.add(carro)

    rua = pygame.image.load(os.path.join(cf.diretorio_imagens, 'road.png'))
    rua = pygame.transform.scale(rua, ((cf.LARGURA-300, int(cf.ALTURA*5.36))))
    rua_rect = rua.get_rect()
    rua_rect.bottomleft = (300, cf.ALTURA)
    rua_rect2 = rua_rect.copy()
    cf.musica_partida.play()         #Este comando reproduz a música da partida
    fonte_pause = pygame.font.Font(pygame.font.get_default_font(), 40)
    #Variáveis para pausar o jogo
    RODANDO = 0
    PAUSADO = 1
    jogo = RODANDO 
    
    while True:
        if cf.morreu == False:
            jogar(tela, relogio, todas_as_sprites, rua, rua_rect, rua_rect2, carro)
        elif cf.morreu == True:
            tela_de_morte(tela, relogio)

#Criada uma variável (objeto) e a função cria uma janela
tela = pygame.display.set_mode((cf.LARGURA, cf.ALTURA))
#Este comando insere um nome ao jogo
pygame.display.set_caption('jogo_de_carro') 
pygame_icon = pygame.image.load(os.path.join(cf.diretorio_imagens, 'icon.png')).convert_alpha() #Este comando auxilia na exibição do icone do jogo
pygame.display.set_icon(pygame_icon) #Este comando também auxilia nesta exibiçao

try:
    tela_jogo()
finally:
    pygame.quit()
