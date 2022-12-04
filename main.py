import pygame
from pygame.locals import *
from sys import exit
import os
from tkinter import *

root = Tk()

ALTURA = (root.winfo_screenheight() - 150)
LARGURA = (root.winfo_screenwidth() - 150)

diretorio_principal = os.path.dirname(__file__)
diretorio_imagens = os.path.join(diretorio_principal, 'sprites')
diretorio_sons = os.path.join(diretorio_principal, 'songs')

LARGURA = 640
ALTURA = 945

BRANCO = (255, 255, 255)

carro_pos_x = LARGURA//2
carro_pos_y = ALTURA//2

tela = pygame.display.set_mode((LARGURA, ALTURA))

pygame.display.set_caption('jogo_de_carro')


class Carro(pygame.sprite.Sprite):
    def __init__(self):
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

    def movimento(self):
        self.movimentar = True

    def update(self):
        if self.movimentar == True:
            self.movimentar = False
            self.rect.center = (carro_pos_x, carro_pos_y)

        if self.index_lista > 1:
            self.index_lista = 0
        self.index_lista += 0.25
        self.image = self.imagens_carro[int(self.index_lista)]


class Rua(pygame.sprite.Sprite):
    def __init__(self):
        sprite_rua = pygame.image.load(os.path.join(
            diretorio_imagens, 'road.png')).convert_alpha()
        pygame.sprite.Sprite.__init__(self)
        self.imagens_rua = []
        for i in range(16):
            img = sprite_rua.subsurface((135*i, 0), (135, 160))
            img = pygame.transform.scale(img, (LARGURA, ALTURA))
            self.imagens_rua.append(img)

        self.index_lista = 0
        self.image = self.imagens_rua[self.index_lista]
        self.rect = self.image.get_rect()
        self.rect.topleft = (0, 0)

    def update(self):
        if self.index_lista > 15:
            self.index_lista = 0
        self.index_lista += 1
        self.image = self.imagens_carro[int(self.index_lista)]


todas_as_sprites = pygame.sprite.Group()
carro = Carro()
todas_as_sprites.add(carro)

rodovia = pygame.sprite.Group()
rua = Rua()
rodovia.add(rua)

relogio = pygame.time.Clock()
while True:
    relogio.tick(30)
    rodovia.draw(tela)
    for event in pygame.event.get():
        if event.type == QUIT:
            pygame.quit()
            exit()
        if event.type == KEYDOWN:
            if event.key == K_a or event.key == K_LEFT:
                carro_pos_x = carro_pos_x - (LARGURA - 20)//5
                carro.movimento()
            if event.key == K_d or event.key == K_RIGHT:
                carro_pos_x = carro_pos_x + (LARGURA - 20)//5
                carro.movimento()
            if event.key == K_w or event.key == K_UP:
                carro_pos_y = carro_pos_y - ALTURA//7
                carro.movimento()
            if event.key == K_s or event.key == K_DOWN:
                carro_pos_y = carro_pos_y + ALTURA//7
                carro.movimento()

    todas_as_sprites.draw(tela)
    todas_as_sprites.update()

    pygame.display.flip()
