"""Textos do passo a passo: preparação da TV e frases do 'próximo passo'.

Os nomes dos menus variam com a marca e a versão do sistema; os textos dizem sempre o caminho típico.
"""
from __future__ import annotations

PREP_STEPS: dict[str, list[tuple[str, str]]] = {
    "androidtv": [
        ("Liga a TV e este computador à mesma rede",
         "Os dois no mesmo router, por Wi-Fi ou cabo. Evita redes de convidados/visitantes (isolam os aparelhos)."),
        ("Ativa o modo de programador na TV",
         "Definições → Sistema → Acerca de → carrega 7 vezes em 'Compilação' (Build). Aparece uma mensagem a dizer "
         "que já és programador. Na Google TV: Definições → Sistema → Acerca de → 'Android TV OS build'."),
        ("Liga a depuração",
         "Definições → Sistema → Opções de programador: liga 'Depuração USB' e, se existir, 'Depuração sem fios' "
         "(Android 11 ou mais recente)."),
        ("Descobre o endereço IP da TV",
         "Definições → Rede e Internet → a tua rede (ou 'Estado'). É algo como 192.168.1.50. Vais escrevê-lo no "
         "separador 1."),
        ("Se existir 'Depuração sem fios': abre-a e vê o código de pareamento",
         "Em 'Parear dispositivo com código' aparece um IP:porta e um código de 6 dígitos. Vais usá-los no "
         "separador 1 (a porta de pareamento é diferente da 5555)."),
        ("Põe o comando à mão e vê o que está nas portas USB da TV",
         "A TV vai perguntar 'Permitir depuração USB?' e tens de escolher Permitir. Algumas TVs cortam a energia "
         "às portas USB com a depuração ligada (colunas, discos): diz-me o que lá tens no separador 1."),
    ],
    "firetv": [
        ("Liga a Fire TV e este computador à mesma rede",
         "Os dois no mesmo router, por Wi-Fi ou cabo. Evita redes de convidados/visitantes."),
        ("Ativa as Opções de programador",
         "Definições → My Fire TV → Acerca de → carrega 7 vezes no nome do aparelho. Depois aparecem as "
         "'Opções de programador' em My Fire TV."),
        ("Liga a depuração ADB",
         "Opções de programador → 'Depuração ADB' ligada. Para instalar APKs liga também 'Aplicações de origens "
         "desconhecidas'."),
        ("Descobre o endereço IP",
         "Definições → My Fire TV → Acerca de → Rede. É algo como 192.168.1.50."),
        ("Põe o comando à mão",
         "A Fire TV vai perguntar 'Permitir depuração USB?': escolhe Permitir (e 'Permitir sempre')."),
    ],
}

NEXT = {
    "start": "Passo 0 — segue a checklist de preparação (separador 0) e escolhe o sistema e a marca da tua TV.",
    "prep_done": ("✔ Preparação feita. Passo 1 — vai ao separador '1 · Ligar', escreve o IP da TV e carrega em "
                  "'Ligar à TV'. Quando a TV perguntar 'Permitir depuração USB?', escolhe Permitir."),
    "no_adb": ("Esta TV não permite ADB, por isso não há mais passos nesta app: segue o guia acima "
               "(ação ao nível da rede e das definições da TV)."),
    "connected": ("✔ Ligado. Passo 2 — separador '2 · Backup': escolhe a pasta e carrega em 'Fazer backup'. "
                  "Ainda não se muda nada na TV."),
    "backup_done": ("✔ Backup feito (e o script de restauro já existe). Passo 3 — separador '3 · Pacotes': carrega em "
                    "'Marcar grupos 1 e 2', revê a lista e carrega em 'Desativar selecionados'. Depois de cada lote "
                    "confirmas no ecrã de verificação."),
    "verify": ("Confere a TV: o ecrã inicial aparece? O menu Entradas abre? Dá para ir ao HDMI? Se estiver tudo bem, "
               "'continuar'; se algo partiu, reativa o lote."),
    "queue_done": ("✔ Lotes concluídos. A seguir (por ordem): passo 4 troca o ecrã inicial por um sem anúncios, "
                   "passo 6 filtra anúncios por DNS e instala apps, e o passo 5 reduz animações, reinicia e mede a "
                   "memória antes/depois."),
    "final": "Passo 5 — gera o relatório: tens a tabela antes/depois e o comando que desfaz tudo.",
}
