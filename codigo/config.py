import pygame

pygame.init()



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

carro_pos_x = 555
carro_pos_y = 556
car_pos_x = 0
car_pos_y = 0
pedra_pos_x = 0
pedra_pos_y = 0
buraco_pos_x = 0
buraco_pos_y = 0 
tronco_pos_x = 0
tronco_pos_y = 0
rua_numero = 0
relogio = pygame.time.Clock()
contador = 0
segundo = 0
minuto = 0
escolha_skin = 0
dificuldade = 1
condicao_vitoria = 1
pontuacao = ''
quadro_de_pontuacao = fonte.render(pontuacao, True, BRANCO)
escolha = 0



#TELAS              

tela = pygame.display.set_mode((LARGURA, ALTURA))

mensagem_morreu = f'GAME OVER'
tela_reiniciar = fonte_game_over.render(mensagem_morreu, False, CINZA)
tela_reiniciar.get_rect()

mensagem_venceu = f'WINNER'
tela_vitoria = fonte_game_over.render(mensagem_venceu, False, (218,165,32))
tela_vitoria.get_rect()



#SONS


som_colisao = pygame.mixer.Sound('./codigo/songs/colisao_carros.wav')
som_colisao.set_volume(0.35)

pygame.display.set_caption('jogo_de_carro') #Este comando insere um nome ao jogo
pygame_icon = pygame.image.load('./codigo/sprites/icon.png').convert_alpha() #Este comando auxilia na exibição do icone do jogo
pygame.display.set_icon(pygame_icon) #Este comando também auxilia nesta exibiçao

#SPRITES

rua = pygame.image.load('./codigo/sprites/road.png') #RUA
rua = pygame.transform.scale(rua, ((LARGURA-300, int(ALTURA*5.36))))
rua_rect = rua.get_rect()
rua_rect.bottomleft = (300, ALTURA)
rua_rect2 = rua_rect.copy()

#BOTÃO

image_botao = pygame.image.load("./codigo/sprites/button.png").convert_alpha()
image_botao = pygame.transform.scale(image_botao, (300, 75))

#CARROS

carro_amarelo = pygame.image.load('./codigo/sprites/car_yellow.png').convert_alpha()
carro_amarelo_cortado = carro_amarelo.subsurface((0, 0), (56, 40))

carro_preto = pygame.image.load('./codigo/sprites/car_black.png').convert_alpha()
carro_preto_cortado = carro_preto.subsurface((0, 0), (56, 40))

carro_azul = pygame.image.load('./codigo/sprites/car_blue.png').convert_alpha()
carro_azul_cortado = carro_azul.subsurface((0, 0), (56, 40))

carro_rosa = pygame.image.load('./codigo/sprites/car_pink.png').convert_alpha()
carro_rosa_cortado = carro_rosa.subsurface((0, 0), (56, 40))

carro_vermelho = pygame.image.load('./codigo/sprites/car_red.png').convert_alpha()
carro_vermelho_cortado = carro_vermelho.subsurface((0, 0), (56, 40))

carro_branco = pygame.image.load('./codigo/sprites/car_white.png').convert_alpha()
carro_branco_cortado = carro_branco.subsurface((0, 0), (56, 40))