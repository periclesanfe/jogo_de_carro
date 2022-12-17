import pygame
import os
import config as cf


class Carro_Obstaculo(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
    def __init__(self): #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
        sprite_carro_player_obstaculo = pygame.image.load(os.path.join(
            cf.diretorio_imagens, 'car_red.png')).convert_alpha()
        pygame.sprite.Sprite.__init__(self)
        self.imagens_carro_obstaculo = []
        for i in range(2):
            img = sprite_carro_player_obstaculo.subsurface((56*i, 0), (56, 40))
            img = pygame.transform.scale(img, (((cf.LARGURA-340)//2.7), (cf.ALTURA//5.5)))
            img = pygame.transform.flip(img, False, True)
            self.imagens_carro_obstaculo.append(img)

        self.index_lista = 0
        self.image = self.imagens_carro_obstaculo[self.index_lista]
        self.rect = self.image.get_rect()
        self.rect.center = (cf.car_pos_x, cf.car_pos_y)
        self.mask = pygame.mask.from_surface(self.image)



    def update(self): #Está tambem estará responsavel pela posição do carrinho na tela, aplicando condições especificas
        if self.index_lista > 1:
            self.index_lista = 0
        self.index_lista += 0.25
        self.image = self.imagens_carro_obstaculo[int(self.index_lista)]

        cf.car_pos_y += cf.FPS//6
        if self.rect.y >= 880:
            cf.car_pos_y = cf.car_pos_y_inicial
        
        self.rect.center = (cf.car_pos_x, cf.car_pos_y)

        


        #3.9 #7.5