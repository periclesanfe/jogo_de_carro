#Importar as bibliotecas/módulos necessários para o código
import pygame
from pygame.locals import *   #Importa todas as funções e as constantes existentes no submódulo locals
from sys import exit          #Essa função dentro do módulo sys torna possível fechar a janela
import os      
   
#Este comando inicializa as funções e variáveis da biblioteca pygame
pygame.init()

#Criando as varáveis do jogo
ALTURA = 644
LARGURA = 820
BRANCO = (255,255,255)
CINZA = (100,100,100)
PRETO = (0,0,0)
RUA_IMG = 'road.png'
FPS = 60
contador = 0
fonte = pygame.font.SysFont('arial', 40, True, False)
morreu = False
carro_pos_x = 555
carro_pos_y = 556


diretorio_principal = os.path.dirname(__file__) #Este diretório é o principal, trabalha com o arquivo em si
diretorio_imagens = os.path.join(diretorio_principal, 'sprites') #Este diretório é responsavel pelas sprites do jogo
diretorio_sons = os.path.join(diretorio_principal, 'songs') #Este diretório é responsavel pelos sons do jogo(game)


def load_assets(diretorio_imagens):
    assets = {}
    assets[RUA_IMG] = pygame.image.load(os.path.join(diretorio_imagens, 'road.png'))
    return assets


#Essa função vai reiniciar os parâmetros do jogo
def reiniciar_jogo(todas_as_sprites):
    global contador, carro_pos_x, carro_pos_y, rua_numero, morreu
    contador = 0
    rua_numero = 0
    morreu = False
    pygame.display.update()
    carro_pos_x = 555
    carro_pos_y = 556
    todas_as_sprites.draw(tela)


def aumentar_contador(contador):
    return contador + 1 


def jogar(tela, contador, carro, relogio, todas_as_sprites, rua, rua_rect, rua_rect2):
    global morreu, carro_pos_y, carro_pos_x
    pygame.display.flip()
    while morreu == False: 
        
        tela.fill(CINZA)
        relogio.tick(FPS*10)
        pontuacao = f'{str(contador).zfill(3)}'
        quadro_de_pontuacao = fonte.render(pontuacao, False, (BRANCO))

        todas_as_sprites.update() #Este comando vai atualizar frequente comandos a tela, auxiliando na fluidez do jogo

        rua_numero = 0
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

        #Esse loop tem a função de verificar se um evento aconteceu
        for event in pygame.event.get():
            
            #Essa condição de repetição vai auxiliar no botão de fechar a tela
            if event.type == QUIT:
                pygame.quit()
                exit()             #Chama a função importada anteriormente

            #Essas condições vão controlar quaisquer movimentos feitos pelo carrinho na tela
            if event.type == KEYDOWN: 
                if event.key == K_r:
                    morreu = True
                if event.key == K_a:
                    carro_pos_x = carro_pos_x - 100
                    contador = aumentar_contador(contador)
                    carro.movimento()
                if event.key == K_LEFT:
                    carro_pos_x = carro_pos_x - 100
                    contador = aumentar_contador(contador)
                    carro.movimento()
                if event.key == K_d:
                   carro_pos_x = carro_pos_x + 100
                   contador = aumentar_contador(contador)
                   carro.movimento()
                if event.key == K_RIGHT:
                    carro_pos_x = carro_pos_x + 100
                    contador = aumentar_contador(contador)
                    carro.movimento()
                if event.key == K_w:
                    carro_pos_y = carro_pos_y - 120
                    contador = aumentar_contador(contador)
                    carro.movimento()
                if event.key == K_UP:
                    carro_pos_y = carro_pos_y - 120
                    contador = aumentar_contador(contador)
                    carro.movimento()
                if event.key == K_s:
                    carro_pos_y = carro_pos_y + 120
                    contador = aumentar_contador(contador)
                    carro.movimento()
                if event.key == K_DOWN:
                    carro_pos_y = carro_pos_y + 120
                    contador = aumentar_contador(contador)
                    carro.movimento()

        tela.blit(quadro_de_pontuacao, (18,20))
        todas_as_sprites.draw(tela) #Este comando auxilia na exibição das sprites na tela
        
        #Essa função atualiza a tela do jogo a cada interação
        pygame.display.flip()


def tela_de_morte(tela, relogio, todas_as_sprites):   
    global tela_reiniciar, morreu, FPS, BRANCO, PRETO

    while morreu: 
        relogio.tick(FPS*10)
        tela.fill(BRANCO)
        mensagem_morreu = f'Você morreu, aperte R para reiniciar'
        tela_reiniciar = fonte.render(mensagem_morreu, False, (PRETO))
        tela_reiniciar.get_rect()
        tela.blit(tela_reiniciar.rect.center, (ALTURA, LARGURA))
        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                exit()
            if event.type == KEYDOWN: 
                if event.key == K_r:
                    reiniciar_jogo(todas_as_sprites)
        pygame.display.update()


class Carro(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
   
    #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
    def __init__(self): 
        global carro_pos_x, carro_pos_y
        sprite_carro = pygame.image.load(os.path.join(diretorio_imagens, 'car_yellow.png')).convert_alpha()
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
            self.rect.center = (carro_pos_x, carro_pos_y)

        if self.index_lista > 1:
            self.index_lista = 0
        self.index_lista += 0.25
        self.image = self.imagens_carro[int(self.index_lista)]


def tela_jogo(tela, contador):

    global carro_pos_x, carro_pos_y, morreu
    
    #Esta variável vai definir se o carro já colidiu ou não
    #Este comando controla a velocidade do objeto na tela
    relogio = pygame.time.Clock() 

    todas_as_sprites = pygame.sprite.Group() #Este comando vai auxiliar, quando formos adicionar o carrinho na tela
    carro = Carro()
    todas_as_sprites.add(carro)

    """assets = load_assets(os.path.join(diretorio_imagens))
    rua = assets[RUA_IMG]"""
    rua = pygame.image.load(os.path.join(diretorio_imagens, 'road.png'))
    rua = pygame.transform.scale(rua, ((LARGURA-300, int(ALTURA*5.36))))
    rua_rect = rua.get_rect()
    rua_rect.bottomleft = (300, ALTURA)
    rua_rect2 = rua_rect.copy()
    
    while True:
        if morreu == False:
            jogar(tela, contador, carro, relogio, todas_as_sprites, rua, rua_rect, rua_rect2)
        elif morreu == True:
            tela_de_morte(tela, relogio, todas_as_sprites)
   

#Criada uma variável (objeto) e a função cria uma janela
tela = pygame.display.set_mode((LARGURA, ALTURA))

#Este comando insere um nome ao jogo
pygame.display.set_caption('jogo_de_carro') 
pygame_icon = pygame.image.load(os.path.join(diretorio_imagens, 'icon.png')).convert_alpha() #Este comando auxilia na exibição do icone do jogo
pygame.display.set_icon(pygame_icon) #Este comando também auxilia nesta exibiçao

try:
    tela_jogo(tela, contador)
finally:
    pygame.quit()
