#Importar as bibliotecas/módulos necessários para o código
from asyncio import Event
import pygame
from pygame.locals import *   #Importa todas as funções e as constantes existentes no submódulo locals
from sys import exit          #Essa função dentro do módulo sys torna possível fechar a janela
import os     
from random import choice


#Este comando inicializa as funções e variáveis da biblioteca pygame
pygame.init()
pygame.mixer.init()          #Iniciando o módulo mixer

#Criando as varáveis do jogo
ALTURA = 644
LARGURA = 820
BRANCO = (255,255,255)
CINZA = (100,100,100)
PRETO = (0,0,0)
RUA_IMG = 'road.png'
FPS = 60
fonte = pygame.font.SysFont('arial', 40, True, False)
morreu = False
carro_pos_x = 555
carro_pos_y = 556
rua_numero = 0


diretorio_principal = os.path.dirname(__file__)                   #Este diretório é o principal, trabalha com o arquivo em si
diretorio_imagens = os.path.join(diretorio_principal, 'sprites')  #Este diretório é responsavel pelas sprites do jogo
diretorio_sons = os.path.join(diretorio_principal, 'songs')       #Este diretório é responsavel pelos sons do jogo(game)


musica_partida = pygame.mixer.Sound(os.path.join(diretorio_sons, './audios_convertidos/musica_partida.mp3'))
pygame.mixer.music.play(-1)
musica_partida.set_volume(0.25)

'''musica_menu = pygame.mixer.Sound(os.path.join(diretorio_sons, './audios_convertidos/musica_menu.mp3'))
musica_partida.set_volume(1)

colisao_buraco = pygame.mixer.Sound(os.path.join(diretorio_sons, 'colisao_buraco.wav'))
colisao_buraco.set_volume(1)

colisão_carros = pygame.mixer.Sound(os.path.join(diretorio_sons, 'colisão_carros.wav'))
colisão_carros.set_volume(1)

colisao_troncos = pygame.mixer.Sound(os.path.join(diretorio_sons, 'colisao_troncos.wav'))
colisao_troncos.set_volume(1)                    
    '''

class Carro(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
   
    #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
    def __init__(self): 
        escolha = choice((0,1,2,3,4,5))
        if escolha == 0:
            sprite_carro = pygame.image.load(os.path.join(diretorio_imagens, 'car_yellow.png')).convert_alpha()
        if escolha == 1:
            sprite_carro = pygame.image.load(os.path.join(diretorio_imagens, 'car_black.png')).convert_alpha()
        if escolha == 2:
            sprite_carro = pygame.image.load(os.path.join(diretorio_imagens, 'car_blue.png')).convert_alpha()
        if escolha == 3:
            sprite_carro = pygame.image.load(os.path.join(diretorio_imagens, 'car_pink.png')).convert_alpha()
        if escolha == 4:
            sprite_carro = pygame.image.load(os.path.join(diretorio_imagens, 'car_red.png')).convert_alpha()
        if escolha == 5:
            sprite_carro = pygame.image.load(os.path.join(diretorio_imagens, 'car_white.png')).convert_alpha()
        pygame.sprite.Sprite.__init__(self)
        self.imagens_carro = []

        for i in range(2):
            img = sprite_carro.subsurface((56*i, 0), (56, 40))
            img = pygame.transform.scale(img, (((LARGURA-340)//2.7), (ALTURA//5.5)))
            self.imagens_carro.append(img)
        
        self.index_lista = 0
        self.image = self.imagens_carro[self.index_lista]
        self.rect = self.image.get_rect()
        self.rect.center = (555, 556)
        self.mask = pygame.mask.from_surface(self.image)
        self.movimentar = False

    def movimento(self): #Já esta função estará responsavel pela posição que o carro aparece na tela
        self.movimentar = True

    def update(self): #Está tambem estará responsavel pela posição do carrinho na tela, aplicando condições especificas
        if self.movimentar == True:
            self.movimentar = False
            self.rect.center = (configurations.carro_pos_x, configurations.carro_pos_y)

        if self.index_lista > 1:
            self.index_lista = 0
        self.index_lista += 0.25
        self.image = self.imagens_carro[int(self.index_lista)]


#Essa função vai reiniciar os parâmetros do jogo
def reiniciar_jogo():
    global contador, rua_numero, morreu, carro_pos_x, carro_pos_y
    contador = 0
    rua_numero = 0
    morreu = False
    carro_pos_x = 555
    carro_pos_y = 556
    pygame.display.update()


def aumentar_contador(contador):
    return contador + 1 


def jogar(tela, relogio, fonte, todas_as_sprites, rua, rua_rect, rua_rect2, carro):
    global carro_pos_y, carro_pos_x, rua_numero, morreu

    contador = 0

    while morreu == False: 
        
        """RODANDO = 0
        PAUSADO = 1
        jogo = RODANDO"""
        tela.fill(CINZA)
        relogio.tick(FPS*10)
        pontuacao = f'{str(contador).zfill(3)}'
        quadro_de_pontuacao = fonte.render(pontuacao, True, BRANCO, PRETO)
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
                    morreu = True

                """if event.key == K_p:
                    if jogo != PAUSADO:
                        jogo = PAUSADO
                    else:
                        jogo = RODANDO"""


                if event.key == K_a:
                    if carro_pos_x <= 355:
                        pass
                    else:
                        carro_pos_x = carro_pos_x - 100
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_LEFT:
                    if carro_pos_x == 355:
                        pass
                    else:
                        carro_pos_x = carro_pos_x - 100
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_d:
                    if carro_pos_x == 755:
                        pass
                    else:
                        carro_pos_x = carro_pos_x + 100
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_RIGHT:
                    if carro_pos_x == 755:
                        pass
                    else:
                        carro_pos_x = carro_pos_x + 100
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_w:
                    if carro_pos_y == 76:
                        pass
                    else:
                        carro_pos_y = carro_pos_y - 120
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_UP:
                    if carro_pos_y == 76:
                        pass
                    else:
                        carro_pos_y = carro_pos_y - 120
                        contador = aumentar_contador(contador)
                        carro.movimento()
                if event.key == K_s:
                    if carro_pos_y == 556:
                        pass
                    else:
                        carro_pos_y = carro_pos_y + 120
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
                rua_rect.bottomleft = (300, ALTURA)
                rua_numero = 1
            else:
                tela.blit(rua, rua_rect)
                rua_rect.y += FPS//16
        else:
            if rua_rect2.topleft[1] >= 0:
                rua_rect2.bottomleft = (300, ALTURA)
                rua_numero = 0
            else:
                tela.blit(rua, rua_rect2)
                rua_rect2.y += FPS//16

        tela.blit(quadro_de_pontuacao, (115,60))
        todas_as_sprites.draw(tela) #Este comando auxilia na exibição das sprites na tela

        #Essa função atualiza a tela do jogo a cada interação
        pygame.display.flip()


def tela_de_morte(tela, relogio, FPS):   

    while morreu: 
        relogio.tick(FPS*10)
        tela.fill(BRANCO)
        mensagem_morreu = f'Você morreu, aperte R para reiniciar'
        tela_reiniciar = fonte.render(mensagem_morreu, False, PRETO)
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
    global morreu
    
    #Esta variável vai definir se o carro já colidiu ou não
    #Este comando controla a velocidade do objeto na tela
    relogio = pygame.time.Clock() 

    todas_as_sprites = pygame.sprite.Group() #Este comando vai auxiliar, quando formos adicionar o carrinho na tela
    carro = Carro()
    todas_as_sprites.add(carro)

    rua = pygame.image.load(os.path.join(diretorio_imagens, 'road.png'))
    rua = pygame.transform.scale(rua, ((LARGURA-300, int(ALTURA*5.36))))
    rua_rect = rua.get_rect()
    rua_rect.bottomleft = (300, ALTURA)
    rua_rect2 = rua_rect.copy()
    musica_partida.play()         #Este comando reproduz a música da partida
    
    fonte_pause = pygame.font.Font(pygame.font.get_default_font(), 40)
    
    #Variáveis para pausar o jogo
    RODANDO = 0
    PAUSADO = 1
    jogo = RODANDO 
    
    while True:
        if morreu == False:
            jogar(tela, relogio, fonte, todas_as_sprites, rua, rua_rect, rua_rect2, carro)
        elif morreu == True:
            tela_de_morte(tela, relogio, FPS)

#Criada uma variável (objeto) e a função cria uma janela
tela = pygame.display.set_mode((LARGURA, ALTURA))

#Este comando insere um nome ao jogo
pygame.display.set_caption('jogo_de_carro') 
pygame_icon = pygame.image.load(os.path.join(diretorio_imagens, 'icon.png')).convert_alpha() #Este comando auxilia na exibição do icone do jogo
pygame.display.set_icon(pygame_icon) #Este comando também auxilia nesta exibiçao

try:
    tela_jogo()
finally:
    pygame.quit()

