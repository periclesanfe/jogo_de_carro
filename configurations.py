import pygame
import os

#Este comando inicializa as funções e variáveis da biblioteca pygame
pygame.init()

#Criando as varáveis para dimensões
ALTURA = 920
LARGURA = 685

diretorio_principal = os.path.dirname(__file__) #Este diretório é o principal, trabalha com o arquivo em si
diretorio_imagens = os.path.join(diretorio_principal, 'sprites') #Este diretório é responsavel pelas sprites do jogo
diretorio_sons = os.path.join(diretorio_principal, 'songs') #Este diretório é responsavel pelos sons do jogo(game)

BRANCO = (255, 255, 255)

carro_pos_x = 68*5
carro_pos_y = 144*5.75

#Criada uma variável (objeto) e a função cria uma janela
tela = pygame.display.set_mode((LARGURA, ALTURA))

#Este comando insere um nome ao jogo
pygame.display.set_caption('jogo_de_carro') 
pygame_icon = pygame.image.load(os.path.join(diretorio_imagens, 'icon.png')).convert_alpha() #Este comando auxilia na exibição do icone do jogo
pygame.display.set_icon(pygame_icon) #Este comando também auxilia nesta exibiçao