import pygame
import os
import config as cf

class Carro_Player(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
   
    #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
    def __init__(self): 
        if cf.escolha_skin == 0:
            sprite_carro_player = cf.carro_amarelo
        if cf.escolha_skin == 1:
            sprite_carro_player = cf.carro_preto
        if cf.escolha_skin == 2:
            sprite_carro_player = cf.carro_azul
        if cf.escolha_skin == 3:
            sprite_carro_player = cf.carro_rosa
        if cf.escolha_skin == 4:
            sprite_carro_player = cf.carro_vermelho
        if cf.escolha_skin == 5:
            sprite_carro_player = cf.carro_branco
        pygame.sprite.Sprite.__init__(self)
        self.imagens_carro = []
       

        for i in range(2):
            img = sprite_carro_player.subsurface((56*i, 0), (56, 40))
            img = pygame.transform.scale(img, (((cf.LARGURA-340)//2.7), (cf.ALTURA//5.5)))
            self.imagens_carro.append(img)
        
        self.index_lista = 0
        self.image = self.imagens_carro[self.index_lista]
        self.rect = self.image.get_rect()
        self.rect.center = (cf.carro_pos_x, cf.carro_pos_y)
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

    
