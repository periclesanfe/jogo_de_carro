#Importar as bibliotecas/módulos necessários para o código
from asyncio import Event
import pygame
from pygame.locals import *   #Importa todas as funções e as constantes existentes no submódulo locals
from sys import exit          #Essa função dentro do módulo sys torna possível fechar a janela
import os
            
#Este comando inicializa as funções e variáveis da biblioteca pygame
pygame.init()
pygame.mixer.init()          #Iniciando o módulo mixer


#Criando as varáveis do jogo
ALTURA = 644
LARGURA = 820
BRANCO = (255,255,255)
CINZA = (20,20,20)
RUA_IMG = 'road.png'
FPS = 60
pause = False

diretorio_principal = os.path.dirname(__file__) #Este diretório é o principal, trabalha com o arquivo em si
diretorio_imagens = os.path.join(diretorio_principal, 'sprites') #Este diretório é responsavel pelas sprites do jogo
diretorio_sons = os.path.join(diretorio_principal, 'songs') #Este diretório é responsavel pelos sons do jogo(game)

musica_partida = pygame.mixer.Sound(os.path.join(diretorio_sons, './audios_convertidos/musica_partida.mp3'))
musica_partida.set_volume(0.25)

'''musica_menu = pygame.mixer.Sound(os.path.join(diretorio_sons, './audios_convertidos/musica_menu.mp3'))
musica_partida.set_volume(1)

colisao_buraco = pygame.mixer.Sound(os.path.join(diretorio_sons, 'colisao_buraco.wav'))
colisao_buraco.set_volume(1)

colisão_carros = pygame.mixer.Sound(os.path.join(diretorio_sons, 'colisão_carros.wav'))
colisão_carros.set_volume(1)

colisao_troncos = pygame.mixer.Sound(os.path.join(diretorio_sons, 'colisao_troncos.wav'))
colisao_troncos.set_volume(1)                    
    '''


def load_assets(diretorio_imagens):
    assets = {}
    assets[RUA_IMG] = pygame.image.load(os.path.join(diretorio_imagens, 'road.png'))
    return assets

carro_pos_x = 555
carro_pos_y = 556

contador = 0
fonte = pygame.font.SysFont('arial', 40, True, False)

#Péricles fez*
def reiniciar_jogo(todas_as_sprites):
    print('aqui dentro vai?')
    global contador, carro_pos_x, carro_pos_y, rua_numero, morreu
    contador = 0
    rua_numero = 0
    morreu = False
    carro_pos_x = 555
    carro_pos_y = 556
    todas_as_sprites.draw(tela)
    pygame.display.flip()

def pausar_jogo():

    if pause == True:
        pygame.K_PAUSE()

    while pause:    
        tela_jogo.fill(CINZA)
        pygame.display.update()

class Carro(pygame.sprite.Sprite): #Este classe vai auxiliar na sprite do carro na tela
   
    #Esta função por completo trabalhará com a inserção do carrinho na tela, convertendo a imagem e a inserindo onde bem entender por meio das medidas dadas em comandos abaixo
    def __init__(self): 
        sprite_carro = pygame.image.load(os.path.join(diretorio_imagens, 'car_yellow.png')).convert_alpha()
        pygame.sprite.Sprite.__init__(self)
        self.imagens_carro = []

        for i in range(2):
            img = sprite_carro.subsurface((56*i, 0), (56, 40))
            img = pygame.transform.scale(img, (((LARGURA-340)//2.7), (ALTURA//5.5)))
            self.imagens_carro.append(img)

        self.index_lista = 0
        self.image = self.imagens_carro[self.index_lista]
        self.rect = self.image.get_rect()
        self.rect.center = (carro_pos_x, carro_pos_y)
        self.mask = pygame.mask.from_surface(self.image)
        self.movimentar = False


    def movimento(self): #Já esta função estará responsavel pela posição que o carro aparece na tela
        self.movimentar = True

    def update(self): #Está tambem estará responsavel pela posição do carrinho na tela, aplicando condições especificas
        if self.movimentar == True:
            self.movimentar = False
            self.rect.center = (carro_pos_x, carro_pos_y)

        if self.index_lista > 1:
            self.index_lista = 0
        self.index_lista += 0.25
        self.image = self.imagens_carro[int(self.index_lista)]


def tela_jogo(tela,contador):

    global carro_pos_x, carro_pos_y
    #Este comando controla a velocidade do objeto na tela
    relogio = pygame.time.Clock() 

    todas_as_sprites = pygame.sprite.Group() #Este comando vai auxiliar, quando formos adicionar o carrinho na tela
    carro = Carro()
    todas_as_sprites.add(carro)

    assets = load_assets(os.path.join(diretorio_imagens))
    rua = assets[RUA_IMG]
    rua = pygame.transform.scale(rua, ((LARGURA-300, int(ALTURA*5.36))))
    rua_rect = rua.get_rect()
    rua_rect.bottomleft = (300, ALTURA)
    rua_rect2 = rua_rect.copy()
    musica_partida.play()         #Este comando reproduz a música da partida
    

    
    #Criamos o laço de repetição(loop) para rodar o jogo atualizando
    while True: 
        tela.fill(CINZA)
        relogio.tick(FPS*10)
        pontuacao = f'{str(contador).zfill(3)}'
        quadro_de_pontuacao = fonte.render(pontuacao, False, (BRANCO))

        todas_as_sprites.update() #Este comando vai atualizar frequente comandos a tela, auxiliando na fluidez do jogo

        rua_numero = 0
        if rua_numero == 0:
            if rua_rect.topleft[1] >= 0:
                rua_rect.bottomleft = (300, ALTURA)
                rua_numero = 1
            else:
                tela.blit(rua, rua_rect)
                rua_rect.y += FPS//16
        else:
            if rua_rect2.topleft[1] >= 0:
                rua_rect2.bottomleft = (300, ALTURA)
                rua_numero = 0
            else:
                tela.blit(rua, rua_rect2)
                rua_rect2.y += FPS//16
        tela.blit(quadro_de_pontuacao, (18,20))

        #Esse loop tem a função de verificar se um evento aconteceu
        for event in pygame.event.get():
            
            #Essa condição de repetição vai auxiliar no botão de fechar a tela
            if event.type == QUIT:
                pygame.quit()
                exit()             #Chama a função importada anteriormente
            
            #Essas condições vão controlar quaisquer movimentos feitos pelo carrinho na tela
            if event.type == KEYDOWN: 
                contador = contador + 1 
                if event.key == K_a:
                    carro_pos_x = carro_pos_x - 100
                    carro.movimento()
                if event.key == K_LEFT:
                    carro_pos_x = carro_pos_x - 100
                    carro.movimento()
                if event.key == K_d:
                    carro_pos_x = carro_pos_x + 100
                    carro.movimento()
                if event.key == K_RIGHT:
                    carro_pos_x = carro_pos_x + 100
                    carro.movimento()
                if event.key == K_w:
                    carro_pos_y = carro_pos_y - 120
                    carro.movimento()
                if event.key == K_UP:
                    carro_pos_y = carro_pos_y - 120
                    carro.movimento()
                if event.key == K_s:
                    carro_pos_y = carro_pos_y + 120
                    carro.movimento()
                if event.key == K_DOWN:
                    carro_pos_y = carro_pos_y + 120
                    carro.movimento()

                if event.key == K_r:
                    print('reinicia?')
                    reiniciar_jogo(todas_as_sprites)
                if event.key == K_p:
                    pause = True
                    print('pause?')
                    pausar_jogo()

    
        todas_as_sprites.draw(tela) #Este comando auxilia na exibição das sprites na tela
        
        #Essa função atualiza a tela do jogo a cada interação
        pygame.display.flip()

    

#Criada uma variável (objeto) e a função cria uma janela
tela = pygame.display.set_mode((LARGURA, ALTURA))

#Este comando insere um nome ao jogo
pygame.display.set_caption('jogo_de_carro') 
pygame_icon = pygame.image.load(os.path.join(diretorio_imagens, 'icon.png')).convert_alpha() #Este comando auxilia na exibição do icone do jogo
pygame.display.set_icon(pygame_icon) #Este comando também auxilia nesta exibiçao

tela_jogo(tela,contador)
