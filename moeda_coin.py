import pygame
import os
import config as cf
from random import randint
from random import randrange

class moeda_coin(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
    def __init__(self): #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
        self.image = cf.sprite_moeda
        pygame.sprite.Sprite.__init__(self)
        self.imagens_moeda = []
        for i in range(6):
            img = self.image.subsurface((56*i, 0), (56, 40))
            img = pygame.transform.scale(img, (90, 75))
            self.imagens_moeda.append(img)
    
        self.index_lista = 0
        self.image = self.imagens_moeda[self.index_lista]
        self.rect = self.image.get_rect()
        self.rect.center = (cf.moeda_pos_x, cf.moeda_pos_y)                                         
        self.mask = pygame.mask.from_surface(self.image)
        
        
    def update(self): #Está tambem estará responsavel pela posição do carrinho na tela, aplicando condições especificas
        if self.index_lista > 5:
            self.index_lista = 0
        self.index_lista += 0.15
        self.image = self.imagens_moeda[int(self.index_lista)]

        cf.moeda_pos_y += cf.FPS//7
        if self.rect.y >= 880:
            cf.moeda_pos_y = randint(- 3000, - 2800)                                 
            cf.moeda_pos_x = randrange(360, 760, 100)
        self.rect.center = (cf.moeda_pos_x), (cf.moeda_pos_y)
        


        