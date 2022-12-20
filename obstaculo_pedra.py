import pygame
import os
import config as cf
from random import randrange, choice


class pedra_Obstaculo(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
    def __init__(self): #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
        pygame.sprite.Sprite.__init__(self)
        sprite_stone = pygame.image.load(os.path.join(cf.diretorio_imagens, 'stone.png')).convert_alpha()
        self.image = sprite_stone.subsurface((0, 0), (46, 40))
        self.image = pygame.transform.scale(self.image, (90, 70))
        self.rect = self.image.get_rect()
        self.rect.center = (cf.pedra_pos_x, cf.pedra_pos_y)                                                  
        self.mask = pygame.mask.from_surface(self.image)



    def update(self): #Está tambem estará responsavel pela posição do carrinho na tela, aplicando condições especificas
        cf.pedra_pos_y += cf.VELOCIDADE//7
        if self.rect.topright[1] > 644:
            cf.pedra_pos_y = choice((-179, -462))
            cf.pedra_pos_x = randrange(355, 755, 100)
        self.rect.center = (cf.pedra_pos_x), (cf.pedra_pos_y)
