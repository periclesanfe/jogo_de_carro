import pygame
import os
from random import randint
from random import randrange

pygame.init()


#DIRETÓRIOS

diretorio = os.path.dirname(__file__)                   #Este diretório é o principal, trabalha com o arquivo em si
diretorio_imagens = os.path.join(diretorio, 'sprites')  #Este diretório é responsavel pelas sprites do jogo
diretorio_sons = os.path.join(diretorio, 'songs')       #Este diretório é responsavel pelos sons do jogo(game)


#VARIÁVEIS GLOBAIS DO JOGO

ALTURA = 644
LARGURA = 820
BRANCO = (255,255,255)
CINZA = (100,100,100)
PRETO = (0,0,0)
RUA_IMG = 'road.png'
FPS = 10
VELOCIDADE = 10

fonte = pygame.font.SysFont('Arial', 40, True, False)
fonte_game_over = pygame.font.SysFont('Times New Roman', 100, False, False)

morreu = False
carro_pos_x = 555
carro_pos_y = 556
car_pos_x = 455
car_pos_y = randint(- 350, - 200)
pedra_pos_x = 660
pedra_pos_y = randint(-1100, - 950)
buraco_pos_x = 555
buraco_pos_y = randint(- 890, - 750)
tronco_pos_x = 760
tronco_pos_y = randint(- 600, - 470)
moeda_pos_x = 360
moeda_pos_y = randint(- 3000, - 2800)
rua_numero = 0
relogio = pygame.time.Clock()
contador = 0
segundo = 1
minuto = 0
escolha_skin = 0
modo_de_jogo = 0
dificuldade = 0
escolha_missao = 0
missao = ''




#TELAS              

tela = pygame.display.set_mode((LARGURA, ALTURA))

mensagem_morreu = f'GAME OVER'
tela_reiniciar = fonte_game_over.render(mensagem_morreu, False, CINZA)
tela_reiniciar.get_rect()


tela_reiniciar = fonte_game_over.render(mensagem_morreu, False, CINZA)
tela_reiniciar.get_rect()

tela_reiniciar = fonte_game_over.render(mensagem_morreu, False, CINZA)
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

#BOTÃO

image_botao = pygame.image.load(os.path.join(diretorio_imagens, "button.png")).convert_alpha()
image_botao = pygame.transform.scale(image_botao, (300, 75))

#CARROS

carro_amarelo = pygame.image.load(os.path.join(diretorio_imagens, 'car_yellow.png')).convert_alpha()
carro_amarelo_cortado = carro_amarelo.subsurface((0, 0), (56, 40))

carro_preto = pygame.image.load(os.path.join(diretorio_imagens, 'car_black.png')).convert_alpha()
carro_preto_cortado = carro_preto.subsurface((0, 0), (56, 40))

carro_azul = pygame.image.load(os.path.join(diretorio_imagens, 'car_blue.png')).convert_alpha()
carro_azul_cortado = carro_azul.subsurface((0, 0), (56, 40))

carro_rosa = pygame.image.load(os.path.join(diretorio_imagens, 'car_pink.png')).convert_alpha()
carro_rosa_cortado = carro_rosa.subsurface((0, 0), (56, 40))

carro_vermelho = pygame.image.load(os.path.join(diretorio_imagens, 'car_red.png')).convert_alpha()
carro_vermelho_cortado = carro_vermelho.subsurface((0, 0), (56, 40))

carro_branco = pygame.image.load(os.path.join(diretorio_imagens, 'car_white.png')).convert_alpha()
carro_branco_cortado = carro_branco.subsurface((0, 0), (56, 40))