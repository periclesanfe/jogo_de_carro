import pygame
import config as cf
from random import randrange, choice

class buraco_Obstaculo(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
    def __init__(self): #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
        pygame.sprite.Sprite.__init__(self)
        self.image = pygame.image.load('./codigo/sprites/buraco.png').convert_alpha()
        self.image = pygame.transform.scale(self.image, (100, 100))                    #(((cf.LARGURA-340)//5.7), (cf.ALTURA//1.5)))
        self.rect = self.image.get_rect()
        self.rect.center =  (cf.buraco_pos_x), (cf.buraco_pos_y)                                         
        self.mask = pygame.mask.from_surface(self.image)



    def update(self): #Está tambem estará responsavel pela posição do carrinho na tela, aplicando condições especificas
        cf.buraco_pos_y += cf.VELOCIDADE//7
        if self.rect.topright[1] > 644:
            cf.buraco_pos_y = choice((-243, -619))
            cf.buraco_pos_x = randrange(355, 855, 100)
        self.rect.center = (cf.buraco_pos_x), (cf.buraco_pos_y)
