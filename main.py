import pygame
from pygame.locals import *
from sys import exit
import os
from tkinter import *

root = Tk()

ALTURA = 920
LARGURA = 685

diretorio_principal = os.path.dirname(__file__) #Este diretório é o principal, trabalha com o arquivo em si
diretorio_imagens = os.path.join(diretorio_principal, 'sprites') #Este diretório é responsavel pelas sprites do jogo
diretorio_sons = os.path.join(diretorio_principal, 'songs') #Este diretório é responsavel pelos sons do jogo

BRANCO = (255, 255, 255)

carro_pos_x = 68*5
carro_pos_y = 144*5.75

tela = pygame.display.set_mode((LARGURA, ALTURA)) #Este comando abre a tela

pygame.display.set_caption('jogo_de_carro') #Este comando insere um nome ao jogo
pygame_icon = pygame.image.load(os.path.join(diretorio_imagens, 'icon.png')).convert_alpha() #Este comando auxilia na exibição do icone do jogo
pygame.display.set_icon(pygame_icon) #Este comando também auxilia nesta exibiçao


class Carro(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
    def __init__(self): #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
        sprite_carro = pygame.image.load(os.path.join(
            diretorio_imagens, 'car_yellow.png')).convert_alpha()
        pygame.sprite.Sprite.__init__(self)
        self.imagens_carro = []
        for i in range(2):
            img = sprite_carro.subsurface((56*i, 0), (56, 40))
            img = pygame.transform.scale(img, ((LARGURA//2.7), (ALTURA//5.5)))
            self.imagens_carro.append(img)

        self.index_lista = 0
        self.image = self.imagens_carro[self.index_lista]
        self.rect = self.image.get_rect()
        self.rect.center = (carro_pos_x, carro_pos_y)
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


class Rua(pygame.sprite.Sprite): #Esta classe vai auxiliar na imagem da tela
    def __init__(self):#Esta função tambem vai auxiliar na imagem de fundo, dando as devidas medidas e a deixando de um modo claro e executável
        sprite_rua = pygame.image.load(os.path.join(
            diretorio_imagens, 'road.png'))
        pygame.sprite.Sprite.__init__(self)
        self.imagens_rua = []
        for i in range(16):
            img = sprite_rua.subsurface((0, 160*i), (137, 160)) #Esses dois comandos vão dar as escalas, as medidas que apareceram na tela
            img = pygame.transform.scale(img, (685, 920))
            self.imagens_rua.append(img)

        self.index_lista = 0
        self.image = self.imagens_rua[self.index_lista]
        self.rect = self.image.get_rect()
        self.rect.topleft = (0, 0)

    def update(self): #Esta função vai auxiliar de grande forma o funcionamento do jogo, o mantendo fluido
        if self.index_lista > 15:
            self.index_lista = 0
        self.index_lista += 1
        self.image = self.imagens_carro[int(self.index_lista)]


todas_as_sprites = pygame.sprite.Group() #Este comando vai auxiliar, quando formos adicionar o carrinho na tela
carro = Carro()
todas_as_sprites.add(carro)


rodovia = pygame.sprite.Group() #Este vai auxiliar quando formos exibir a pista na tela
rua = Rua()
rodovia.add(rua)

relogio = pygame.time.Clock() #Este comando controla a velocidade do objeto na tela
while True: #Esse laço de repetição vai auxiliar no botão de fechar a tela
    relogio.tick(30)
    rodovia.draw(tela)
    for event in pygame.event.get():
        if event.type == QUIT:
            pygame.quit()
            exit()
        if event.type == KEYDOWN: #Essas condições vão controlar quaisquer movimentos feitos pelo carrinho na tela
            if event.key == K_a or event.key == K_LEFT:
                carro_pos_x = carro_pos_x - 127
                carro.movimento()
            if event.key == K_d or event.key == K_RIGHT:
                carro_pos_x = carro_pos_x + 127
                carro.movimento()
            if event.key == K_w or event.key == K_UP:
                carro_pos_y = carro_pos_y - ALTURA//5
                carro.movimento()
            if event.key == K_s or event.key == K_DOWN:
                carro_pos_y = carro_pos_y + ALTURA//5
                carro.movimento()

    todas_as_sprites.draw(tela) #Este comando auxilia na exibição das sprites na tela
    todas_as_sprites.update() #Este comando vai atualizar frequente comandos a tela, auxiliando na fluidez do jogo

    pygame.display.flip()
