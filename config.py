import pygame
import os
import carro_obstaculo as co
import carro_player as cp


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
car_pos_x = 555
car_pos_y = -120
rua_numero = 0
contador = 0
relogio = pygame.time.Clock() 


#MENSAGENS

mensagem_morreu = f'Você morreu, aperte R para reiniciar'
pontuacao = f'{str(contador).zfill(2)}'
quadro_de_pontuacao = fonte.render(pontuacao, True, BRANCO, PRETO)


#TELAS              

tela = pygame.display.set_mode((LARGURA, ALTURA))

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


# MÚSICAS

pygame.mixer.init()

musica_partida = pygame.mixer.music.load(os.path.join(diretorio_sons, 'audios_convertidos/musica_partida.mp3'))
musica_partida = pygame.mixer.music.set_volume(0.25)

musica_menu = pygame.mixer.music.load(os.path.join(diretorio_sons, 'audios_convertidos/musica_menu.mp3'))
musica_menu = pygame.mixer.music.set_volume(0.25)

colisao_buraco = pygame.mixer.music.load(os.path.join(diretorio_sons, 'audios_convertidos/colisao_buracos.wav'))
colisao_buraco = pygame.mixer.music.set_volume(0.35)

colisao_carros = pygame.mixer.music.load(os.path.join(diretorio_sons, 'audios_convertidos/colisao_carros.wav'))
colisão_carros = pygame.mixer.music.set_volume(0.35)

colisao_troncos = pygame.mixer.music.load(os.path.join(diretorio_sons, 'audios_convertidos/colisao_troncos.wav'))
colisao_troncos = pygame.mixer.music.set_volume(0.35)  