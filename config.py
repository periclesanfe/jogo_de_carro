import pygame
import os
from random import randint
from random import randrange

pygame.init()


#DIRETÓRIOS

diretorio_principal = os.path.dirname(__file__)                   #Este diretório é o principal, trabalha com o arquivo em si
diretorio_imagens = os.path.join(diretorio_principal, 'sprites')  #Este diretório é responsavel pelas sprites do jogo
diretorio_sons = os.path.join(diretorio_principal, 'songs')       #Este diretório é responsavel pelos sons do jogo(game)


#VARIÁVEIS GLOBAIS DO JOGO

ALTURA = 644
LARGURA = 820
BRANCO = (255,255,255)
CINZA = (100,100,100)
PRETO = (0,0,0)
RUA_IMG = 'road.png'
FPS = 10
fonte = pygame.font.SysFont('arial', 40, True, False)
morreu = False
carro_pos_x = 555
carro_pos_y = 556
car_pos_x = randrange(345,745, 105)
car_pos_y_inicial = randint(-2000, -1000)
car_pos_y = randint(-200, -120)
pedra_pos_x = 555
pedra_pos_y = 556
buraco_pos_x = 555
buraco_pos_y = 556
rua_numero = 0
relogio = pygame.time.Clock()
missao = 'tempo'
contador = 0
segundo = 1
minuto = 0


#TELAS              

tela = pygame.display.set_mode((LARGURA, ALTURA))
mensagem_morreu = f'Você morreu, aperte R para reiniciar'
tela_reiniciar = fonte.render(mensagem_morreu, False, PRETO)
tela_reiniciar.get_rect()

pygame.display.set_caption('jogo_de_carro') #Este comando insere um nome ao jogo
pygame_icon = pygame.image.load(os.path.join(diretorio_imagens, 'icon.png')).convert_alpha() #Este comando auxilia na exibição do icone do jogo
pygame.display.set_icon(pygame_icon) #Este comando também auxilia nesta exibiçao


#SPRITES

rua = pygame.image.load(os.path.join(diretorio_imagens, 'road.png')) #RUA
rua = pygame.transform.scale(rua, ((LARGURA-300, int(ALTURA*5.36))))
rua_rect = rua.get_rect()
rua_rect.bottomleft = (300, ALTURA)
rua_rect2 = rua_rect.copy()
sprite_moeda = pygame.image.load(os.path.join(diretorio_imagens, 'coin.png')).convert_alpha()
moeda = sprite_moeda.subsurface((56*4, 0), (56, 40))
moeda = pygame.transform.scale(moeda, (60, 46))