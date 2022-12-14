import pygame
import os

#Este comando inicializa as funções e variáveis da biblioteca pygame
pygame.init()
pygame.mixer.init()          #Iniciando o módulo mixer

#Criando as varáveis do jogo
ALTURA = 644
LARGURA = 820
BRANCO = (255,255,255)
CINZA = (100,100,100)
PRETO = (0,0,0)
RUA_IMG = 'road.png'
FPS = 60
fonte = pygame.font.SysFont('arial', 40, True, False)
morreu = False
carro_pos_x = 555
carro_pos_y = 556
rua_numero = 0


diretorio_principal = os.path.dirname(__file__)                   #Este diretório é o principal, trabalha com o arquivo em si
diretorio_imagens = os.path.join(diretorio_principal, 'sprites')  #Este diretório é responsavel pelas sprites do jogo
diretorio_sons = os.path.join(diretorio_principal, 'songs')       #Este diretório é responsavel pelos sons do jogo(game)


musica_partida = pygame.mixer.music.load(os.path.join(diretorio_sons, './audios_convertidos/musica_partida.mp3'))
musica_partida = pygame.mixer.music.set_volume(0.25)

'''musica_menu = pygame.mixer.music.load(os.path.join(diretorio_sons, './audios_convertidos/musica_menu.mp3'))
pygame.mixer.w
musica_partida.set_volume(1)

colisao_buraco = pygame.mixer.music.load(os.path.join(diretorio_sons, 'colisao_buraco.wav'))
colisao_buraco.set_volume(1)

colisão_carros = pygame.mixer.music.load(os.path.join(diretorio_sons, 'colisão_carros.wav'))
colisão_carros.set_volume(1)

colisao_troncos = pygame.mixer.music.load(os.path.join(diretorio_sons, 'colisao_troncos.wav'))
colisao_troncos.set_volume(1)                    
    '''

#Criada uma variável (objeto) e a função cria uma janela
tela = pygame.display.set_mode((LARGURA, ALTURA))

#Este comando insere um nome ao jogo
pygame.display.set_caption('jogo_de_carro') 
pygame_icon = pygame.image.load(os.path.join(diretorio_imagens, 'icon.png')).convert_alpha() #Este comando auxilia na exibição do icone do jogo
pygame.display.set_icon(pygame_icon) #Este comando também auxilia nesta exibiçao
