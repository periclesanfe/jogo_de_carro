import pygame
import os
import config as cf

class Carro(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
   
    #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
    def __init__(self): 
        escolha = 5
        if escolha == 0:
            sprite_carro = pygame.image.load(os.path.join(cf.diretorio_imagens, 'car_yellow.png')).convert_alpha()
        if escolha == 1:
            sprite_carro = pygame.image.load(os.path.join(cf.diretorio_imagens, 'car_black.png')).convert_alpha()
        if escolha == 2:
            sprite_carro = pygame.image.load(os.path.join(cf.diretorio_imagens, 'car_blue.png')).convert_alpha()
        if escolha == 3:
            sprite_carro = pygame.image.load(os.path.join(cf.diretorio_imagens, 'car_pink.png')).convert_alpha()
        if escolha == 4:
            sprite_carro = pygame.image.load(os.path.join(cf.diretorio_imagens, 'car_red.png')).convert_alpha()
        if escolha == 5:
            sprite_carro = pygame.image.load(os.path.join(cf.diretorio_imagens, 'car_white.png')).convert_alpha()
        pygame.sprite.Sprite.__init__(self)
        self.imagens_carro = []

        for i in range(2):
            img = sprite_carro.subsurface((56*i, 0), (56, 40))
            img = pygame.transform.scale(img, (((cf.LARGURA-340)//2.7), (cf.ALTURA//5.5)))
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
            self.rect.center = (cf.carro_pos_x, cf.carro_pos_y)

        if self.index_lista > 1:
            self.index_lista = 0
        self.index_lista += 0.25
        self.image = self.imagens_carro[int(self.index_lista)]


class Car(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
    def __init__(self): #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
        sprite_car = pygame.image.load(os.path.join(
            cf.diretorio_imagens, 'car_red.png')).convert_alpha()
        pygame.sprite.Sprite.__init__(self)
        self.imagens_car = []
        for i in range(2):
            img = sprite_car.subsurface((56*i, 0), (56, 30))
            img = pygame.transform.scale(img, ((cf.LARGURA//3.9), (cf.ALTURA//7.5)))
            self.imagens_car.append(img)

        self.index_lista = 0
        self.image = self.imagens_car[self.index_lista]
        self.rect = self.image.get_rect()
        self.rect.center = (cf.car_pos_x, cf.car_pos_y)
        self.mask = pygame.mask.from_surface(self.image)

    def update(self): #Está tambem estará responsavel pela posição do carrinho na tela, aplicando condições especificas
        if self.index_lista > 1:
            self.index_lista = 0
        self.index_lista += 0.25
        self.image = self.imagens_car[int(self.index_lista)]


        #3.9 #7.5