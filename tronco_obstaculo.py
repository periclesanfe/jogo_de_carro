import pygame
import os
import config as cf 
from random import randint
from random import randrange #Biblioteca para sortear a posiçaõ em x do tronco

sprite_tronco = pygame.image.load(os.path.join(cf.diretorio_imagens, 'tree_Trunk.png')).convert_alpha()

class Tronco(pygame.sprite.Sprite):

    def __init__(self):
        pygame.sprite.Sprite.__init__(self)
        self.imagens_tronco_obstaculo = []
<<<<<<< HEAD
        
        for i in range (4):
            img = self.sprite_tronco.subsurface((i*40,0), (40,32))
=======
        for i in range(4):
            img = sprite_tronco.subsurface((i*40,0), (40,32))
>>>>>>> parent of d6a9c58 (atualizando variáveis do obstáculo)
            img = pygame.transform.scale(img, (40*2.5, 32*2.5))
            self.imagens_tronco_obstaculo.append(img)

        self.index_lista = 0    
        self.image = self.imagens_tronco_obstaculo[self.index_lista]
        self.rect = self.image.get_rect()
<<<<<<< HEAD
        self.rect.center = (cf.tronco_pos_x, cf.tronco_pos_y)
        self.mask = pygame.mask.from_surface(self.image)

    def update(self):
=======
        self.rect.x = randrange(4, 575, 105)
        self.rect.y = -115
             

    def update(self): 
>>>>>>> parent of d6a9c58 (atualizando variáveis do obstáculo)
        if self.index_lista > 3:
            self.index_lista = 0
        self.index_lista += 0.25
        self.image = self.imagens_tronco_obstaculo[int(self.index_lista)]

<<<<<<< HEAD
        cf.tronco_pos_y += cf.FPS//5
        if self.rect.y >= 800:
            cf.tronco_pos_y = cf.tronco_pos_x_inicial
            cf.tronco_pos_x = randrange(360, 760, 100)
        self.rect.center = (cf.tronco_pos_x), (cf.tronco_pos_y)

#100largura 80altura
=======
        cf.car_pos_y += cf.FPS//5
        if self.rect.topright[0] < 0:
            self.rect.y = cf.LARGURA
            self.rect.x = randrange(4, 575, 105)
        self.rect.y -= 115
>>>>>>> parent of d6a9c58 (atualizando variáveis do obstáculo)
