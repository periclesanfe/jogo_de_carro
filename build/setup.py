import cx_Freeze

executables = [cx_Freeze.Executable('main.py')]

cx_Freeze.setup(
    name="Jogo do Bicho",
    options={'build_exe': {'packages':['pygame', 'random', 'sys'],
                           'include_files':['songs', 'sprites', 'button.py', 'config.py', 'defs.py', 'obstaculo_buraco.py', 'obstaculo_carro.py', 'obstaculo_pedra.py', 'obstaculo_tronco.py', 'player_carro.py']}},

    executables = executables
    
)