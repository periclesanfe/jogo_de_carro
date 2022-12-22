import pygame
import config as cf 
from random import randrange, choice

class Tronco_Obstaculo(pygame.sprite.Sprite):
    def __init__(self):
        pygame.sprite.Sprite.__init__(self)
        self.sprite_tronco_obstaculo = pygame.image.load('./codigo/sprites/tree_Trunk.png').convert_alpha()
        self.imagens_tronco_obstaculo = []
        
        for i in range (4):
            img = self.sprite_tronco_obstaculo.subsurface((i*40,0), (40,32))
            img = pygame.transform.scale(img, (30*2.5, 32*2.5))
            self.imagens_tronco_obstaculo.append(img)

        self.index_lista = 0
        self.image = self.imagens_tronco_obstaculo[self.index_lista]
        self.rect = self.image.get_rect()
        self.rect.center = (cf.tronco_pos_x, cf.tronco_pos_y)
        self.mask = pygame.mask.from_surface(self.image)

    def update(self):
        if self.index_lista > 3:
            self.index_lista = 0
        self.index_lista += 0.25
        self.image = self.imagens_tronco_obstaculo[int(self.index_lista)]

        cf.tronco_pos_y += cf.VELOCIDADE//7
        if self.rect.topright[1] > 644:
            cf.tronco_pos_y = choice((-243, -759))  
            cf.tronco_pos_x = randrange(355, 855, 100)
        self.rect.center = (cf.tronco_pos_x), (cf.tronco_pos_y)
