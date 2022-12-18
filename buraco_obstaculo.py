import pygame
import os
import config as cf
from random import randint
from random import randrange

class buraco_Obstaculo(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
    def __init__(self): #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
        pygame.sprite.Sprite.__init__(self)
        self.image = pygame.image.load(os.path.join(cf.diretorio_imagens, 'hole.png')).convert_alpha()
        self.image = pygame.transform.scale(self.image, (70, 70))                    #(((cf.LARGURA-340)//5.7), (cf.ALTURA//1.5)))
        self.rect = self.image.get_rect()
        self.rect.center =  (cf.buraco_pos_x), (cf.buraco_pos_y)                                         
        self.mask = pygame.mask.from_surface(self.image)



    def update(self): #Está tambem estará responsavel pela posição do carrinho na tela, aplicando condições especificas
        cf.buraco_pos_y += cf.FPS//6
        if self.rect.y >= 880:
            cf.buraco_pos_y = randint(-450, -300)                                 
            cf.buraco_pos_x = randrange(355, 755, 100)
        self.rect.center = (cf.buraco_pos_x), (cf.buraco_pos_y)
