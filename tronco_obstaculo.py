import pygame
import os
import config as cf 
from random import randint
from random import randrange #Biblioteca para sortear a posiçaõ em x do tronco

class Tronco(pygame.sprite.Sprite):
    def __init__(self):
        pygame.sprite.Sprite.__init__(self)
        self.sprite_tronco = pygame.image.load(os.path.join(cf.diretorio_imagens, 'tree_Trunk.png')).convert_alpha()
        self.imagens_tronco_obstaculo = []
        
        for i in range (4):
            img = self.sprite_tronco.subsurface((i*40,0), (40,32))
            img = pygame.transform.scale(img, (40*2.5, 32*2.5))
            img = pygame.transform.flip(img, False, True)
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

        cf.tronco_pos_y += cf.FPS//5
        if self.rect.y >= 800:
            cf.tronco_pos_y = cf.tronco_pos_x_inicial
            cf.tronco_pos_x = randrange(360, 760, 100)
        self.rect.center = (cf.tronco_pos_x), (cf.tronco_pos_y)

#100largura 80altura