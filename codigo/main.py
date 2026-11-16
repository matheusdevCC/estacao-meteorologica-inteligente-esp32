# ESTACAO METEOROLOGICA INTELIGENTE / UNIP
# ESP32 + MicroPython - Versao API documentada + plano 2D
#
# DHT22  DATA GPIO4
# BMP280 SDA GPIO21, SCL GPIO22, CSB 3V3, SDO GND
# LDR    DO GPIO27 (0 claro / 1 escuro na montagem testada)
# MQ-135 VCC -> HW-131 5V, GND -> HW-131 GND, AO desconectado neste modo
#
# LIGAR HW-131 GND -> ESP32 GND para referencia comum.
# O GND NAO carrega os dados do MQ-135: o sinal vem do pino AO.
# Se alimentar o MQ-135 em 5V, NAO ligue AO diretamente ao ESP32.
# Modo demonstracao exibe 0 e avisa que NAO e leitura real do sensor.
# Para ler ADC real no GPIO32, use somente sinal adaptado a no maximo 3,3 V.

import gc
import math
import struct
import time
import socket
import network
from machine import Pin, ADC, SoftI2C
import dht
try:
    import ujson as json
except ImportError:
    import json

WIFI_NOME = 'Estacao-ESP32'
WIFI_SENHA = 'Estacao2026'
INTERVALO_LEITURA_MS = 3000
MQ_MODO = 'demonstracao'  # 'demonstracao' (zero sinalizado) ou 'adc' (sinal seguro no GPIO32)
MQ_GPIO = 32            # Entrada ADC1 utilizada se MQ_MODO == 'adc'

# Origem de um plano LOCAL DIDATICO, nao coordenadas GPS reais.
ESTACAO_X = 0.0
ESTACAO_Y = 0.0

print('==============================================')
print(' ESTACAO METEOROLOGICA / API + GEOMETRIA 2D')
print('==============================================')


class BMP280:
    def __init__(self, i2c):
        self.i2c = i2c
        dispositivos = i2c.scan()
        if 0x76 in dispositivos:
            self.endereco = 0x76
        elif 0x77 in dispositivos:
            self.endereco = 0x77
        else:
            raise OSError('BMP280 nao encontrado: ' + str(dispositivos))
        chip = i2c.readfrom_mem(self.endereco, 0xD0, 1)[0]
        if chip != 0x58:
            raise OSError('Chip BMP280 inesperado: ' + hex(chip))
        calib = i2c.readfrom_mem(self.endereco, 0x88, 24)
        self.t1, self.t2, self.t3 = struct.unpack('<Hhh', calib[:6])
        self.p = struct.unpack('<Hhhhhhhhh', calib[6:24])
        i2c.writeto_mem(self.endereco, 0xF5, b'\x00')
        i2c.writeto_mem(self.endereco, 0xF4, b'\x27')
        time.sleep_ms(150)

    def ler(self):
        b = self.i2c.readfrom_mem(self.endereco, 0xF7, 6)
        adc_p = (b[0] << 12) | (b[1] << 4) | (b[2] >> 4)
        adc_t = (b[3] << 12) | (b[4] << 4) | (b[5] >> 4)
        if adc_p == 0x80000 or adc_t == 0x80000:
            raise OSError('Conversao BMP280 incompleta')
        v1 = (adc_t / 16384.0 - self.t1 / 1024.0) * self.t2
        v2 = ((adc_t / 131072.0 - self.t1 / 8192.0) ** 2) * self.t3
        fino = v1 + v2
        temperatura = fino / 5120.0
        p1, p2, p3, p4, p5, p6, p7, p8, p9 = self.p
        v1 = fino / 2.0 - 64000.0
        v2 = v1 * v1 * p6 / 32768.0
        v2 = v2 + v1 * p5 * 2.0
        v2 = v2 / 4.0 + p4 * 65536.0
        v1 = (p3 * v1 * v1 / 524288.0 + p2 * v1) / 524288.0
        v1 = (1.0 + v1 / 32768.0) * p1
        if v1 == 0:
            raise OSError('Calibracao invalida para pressao')
        pa = (1048576.0 - adc_p - v2 / 4096.0) * 6250.0 / v1
        v1 = p9 * pa * pa / 2147483648.0
        v2 = pa * p8 / 32768.0
        pa = pa + (v1 + v2 + p7) / 16.0
        return round(temperatura, 2), round(pa / 100.0, 2)


def iniciar_sensor(nome, funcao):
    try:
        sensor = funcao()
        print('[OK] ' + nome)
        return sensor
    except Exception as erro:
        print('[ERRO] ' + nome + ': ' + str(erro))
        return None


def novo_bmp():
    return BMP280(SoftI2C(sda=Pin(21), scl=Pin(22), freq=100000))


def novo_mq():
    adc = ADC(Pin(MQ_GPIO))
    adc.atten(ADC.ATTN_11DB)
    return adc


dht22 = iniciar_sensor('DHT22 / GPIO4', lambda: dht.DHT22(Pin(4, Pin.IN, Pin.PULL_UP)))
bmp = iniciar_sensor('BMP280 / I2C 21,22', novo_bmp)
ldr = iniciar_sensor('LDR / GPIO27', lambda: Pin(27, Pin.IN))
mq = iniciar_sensor('MQ-135 / ADC GPIO%d' % MQ_GPIO, novo_mq) if MQ_MODO == 'adc' else None
if MQ_MODO == 'demonstracao':
    print('[MQ] Modo demonstracao: painel exibe 0; NAO e leitura real do sensor')
elif MQ_MODO != 'adc':
    raise ValueError('MQ_MODO deve ser demonstracao ou adc')

ultimo_ms = None
ultima_amostra = {}


def leituras():
    global ultimo_ms, ultima_amostra
    agora = time.ticks_ms()
    if ultimo_ms is not None and time.ticks_diff(agora, ultimo_ms) < INTERVALO_LEITURA_MS:
        return ultima_amostra
    ultimo_ms = agora
    d = {
        'versao_api': '1.2', 'estacao': {'id': 'ESP32-01', 'x_m': ESTACAO_X,
        'y_m': ESTACAO_Y, 'referencia': 'plano cartesiano local didatico'},
        'dht_temp': None, 'umidade': None, 'bmp_temp': None,
        'pressao': None, 'pressao_bruta': None,
        'pressao_status': 'Sem leitura', 'ldr': None,
        'mq_raw': None, 'mq_percent_adc': None,
        'mq_origem': MQ_MODO, 'mq_sinal_detectado': False,
        'mq_status': 'Aguardando leitura',
        'tempo_s': agora // 1000,
        'intervalo_atualizacao_s': INTERVALO_LEITURA_MS // 1000
    }
    if dht22 is not None:
        try:
            dht22.measure()
            d['dht_temp'] = round(dht22.temperature(), 1)
            d['umidade'] = round(dht22.humidity(), 1)
        except Exception as erro:
            print('[DHT22] ', erro)
    if bmp is not None:
        try:
            t, p = bmp.ler()
            d['bmp_temp'] = t
            d['pressao_bruta'] = p
            if 800 <= p <= 1100:
                d['pressao'] = p
                d['pressao_status'] = 'Valor disponivel (nao calibrado)'
            else:
                d['pressao_status'] = 'Leitura suspeita: %.2f hPa' % p
        except Exception as erro:
            print('[BMP280] ', erro)
    if ldr is not None:
        try:
            d['ldr'] = 'CLARO' if ldr.value() == 0 else 'ESCURO'
        except Exception as erro:
            print('[LDR] ', erro)
    if MQ_MODO == 'demonstracao':
        # Valor fixo para o painel: demonstra a integracao da interface,
        # mas NAO e apresentado como leitura fisica do MQ-135.
        d['mq_raw'] = 0
        d['mq_percent_adc'] = 0.0
        d['mq_status'] = 'Demonstracao: 0 ADC, sem sinal AO validado'
    elif mq is not None:
        try:
            soma = 0
            for i in range(5):
                soma += mq.read()
                time.sleep_ms(10)
            d['mq_raw'] = soma // 5
            d['mq_percent_adc'] = round(d['mq_raw'] * 100.0 / 4095.0, 1)
            d['mq_sinal_detectado'] = d['mq_raw'] > 0
            if d['mq_raw'] == 0:
                d['mq_status'] = 'ADC real = 0: sem sinal util confirmado'
            else:
                d['mq_status'] = 'ADC bruto real; nao equivale a ppm'
        except Exception as erro:
            d['mq_status'] = 'Erro na leitura ADC'
            print('[MQ-135] ', erro)
    ultima_amostra = d
    return d


def geometria(x, y):
    # Vetor que sai da estacao e termina no ponto do plano escolhido.
    dx = x - ESTACAO_X
    dy = y - ESTACAO_Y
    return {
        'referencia': 'plano local ilustrativo; nao usa GPS',
        'unidade': 'm (escala didatica)',
        'estacao': {'x': ESTACAO_X, 'y': ESTACAO_Y},
        'ponto_consulta': {'x': x, 'y': y},
        'vetor': {'dx': round(dx, 2), 'dy': round(dy, 2)},
        'distancia_m': round(math.sqrt(dx * dx + dy * dy), 2),
        'angulo_graus': round(math.atan2(dy, dx) * 180.0 / math.pi, 2)
    }


PAGINA = '''<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Estacao Meteorologica | Acesso do cidadao</title>
<style>
:root{--bg:#091827;--card:#10293d;--edge:#284b62;--txt:#eef7ff;--mut:#a6c0d1;--a:#5ee2c6}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;color:var(--txt);font:15px/1.5 Arial,sans-serif;background:linear-gradient(130deg,#173550,var(--bg) 50%)}
main{max-width:1100px;padding:28px 18px 60px;margin:auto}nav{display:flex;gap:18px;align-items:center;flex-wrap:wrap;margin-bottom:26px}
nav a,a{color:var(--a);text-decoration:none}nav b{margin-right:auto;font-size:14px;letter-spacing:.05em}
h1{font-size:clamp(28px,5vw,43px);margin:4px 0 8px}.sub{color:var(--mut);margin:0 0 22px}
.pill{display:inline-block;padding:7px 13px;border-radius:20px;background:#17463e;color:#a9ffe7;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:20px 0 24px}
.card,.panel{background:#112b3e;border:1px solid var(--edge);border-radius:16px;padding:21px;min-width:0}
.label{color:var(--mut);font-size:13px}.val{font-size:clamp(27px,4vw,39px);font-weight:750;margin:12px 0 4px}
.unit{font-size:16px;font-weight:400;color:var(--mut)}.note{font-size:12px;color:var(--mut)}.warning{color:#ffd392}
.bar{height:7px;background:#294558;border-radius:9px;overflow:hidden;margin:12px 0}.fill{height:100%;width:0;background:var(--a)}
h2{font-size:21px;margin:0 0 9px}.geogrid{display:grid;grid-template-columns:1.4fr 1fr;gap:20px}
canvas{width:100%;height:auto;border:1px solid #36576c;background:#091b2b;border-radius:11px;cursor:crosshair}
.controls{display:flex;flex-wrap:wrap;gap:12px;margin:17px 0 8px}
.controls label{font-size:12px;color:var(--mut)}input{display:block;background:#061624;color:white;border:1px solid #54748c;border-radius:6px;padding:8px;width:105px;margin-top:4px}
.metric{background:#092132;padding:13px;border-radius:10px;margin:12px 0}.metric strong{font-size:24px;display:block;margin-top:5px}
footer{font-size:12px;color:var(--mut);margin-top:22px;line-height:1.7}
@media(max-width:750px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.geogrid{grid-template-columns:1fr}}
@media(max-width:480px){.grid{grid-template-columns:1fr}main{padding:18px 12px}.card,.panel{padding:16px}}
</style></head><body><main>
<nav><b>UNIP &middot; ESTACAO ESP32</b><a href="#indicadores">Indicadores</a><a href="#mapa">Plano 2D</a><a href="/docs">Documentacao da API</a></nav>
<h1>Estacao Meteorologica Inteligente</h1><p class="sub">Painel de consulta local para o cidadao &middot; ESP32 / MicroPython</p><div class="pill" id="status">Conectando...</div>
<section class="grid" id="indicadores">
<div class="card"><div class="label">Temperatura ambiente | DHT22</div><div class="val"><span id="temp">--</span> <span class="unit">&deg;C</span></div><div class="note">Leitura automatica</div></div>
<div class="card"><div class="label">Umidade relativa | DHT22</div><div class="val"><span id="umid">--</span> <span class="unit">%</span></div><div class="note">Umidade do ar</div></div>
<div class="card"><div class="label">Temperatura auxiliar | BMP280</div><div class="val"><span id="tempbmp">--</span> <span class="unit">&deg;C</span></div><div class="note">Sensor barometrico</div></div>
<div class="card"><div class="label">Pressao atmosferica | BMP280</div><div class="val"><span id="pressao">--</span> <span class="unit">hPa</span></div><div id="pressaonota" class="note warning">Em diagnostico</div></div>
<div class="card"><div class="label">Luminosidade | LDR</div><div id="luz" class="val">--</div><div class="note">Deteccao de claro/escuro</div></div>
<div class="card"><div class="label">MQ-135 | Sinal experimental</div><div class="val"><span id="mq">--</span> <span class="unit">/4095</span></div><div class="bar"><div id="fill" class="fill"></div></div><div id="mqnota" class="note">Aguardando sinal</div></div>
</section>
<section class="panel" id="mapa"><h2>Geometria analitica &middot; Mapa cartesiano 2D</h2><p class="sub">Clique no plano ou altere as coordenadas do ponto de consulta.</p>
<div class="geogrid"><div><canvas id="plano" width="720" height="330"></canvas><div class="controls"><label>Posicao X (m)<input type="number" id="x" value="30" min="-100" max="100"></label><label>Posicao Y (m)<input type="number" id="y" value="40" min="-50" max="50"></label></div></div>
<div><div class="metric"><span class="label">Estacao de referencia</span><strong>S (0, 0)</strong></div>
<div class="metric"><span class="label">Vetor de posicao</span><strong id="vetor">--</strong></div>
<div class="metric"><span class="label">Distancia euclidiana</span><strong id="distancia">--</strong></div>
<div class="metric"><span class="label">Angulo em relacao ao eixo X</span><strong id="angulo">--</strong></div>
<p class="note warning">Representacao didatica em metros. Este plano nao mostra localizacao geografica real, GPS nem um mapa de ruas.</p></div></div></section>
<footer><div id="rodape">Atualizacao automatica a cada 3 segundos.</div><div>Acesso disponivel apenas a dispositivos conectados ao Wi-Fi do ESP32. Para acesso pela internet seria necessario um servidor publico.</div></footer>
</main><script>
const $=id=>document.getElementById(id);const cv=$('plano'),ctx=cv.getContext('2d');
function fmt(x,n){return x===null||x===undefined?'--':Number(x).toFixed(n).replace('.',',')}
function plot(x,y){return [360+x*2.95,165-y*2.9]}
function desenhar(x,y){ctx.clearRect(0,0,720,330);ctx.fillStyle='#091b2b';ctx.fillRect(0,0,720,330);
ctx.strokeStyle='#274258';ctx.lineWidth=1;for(let i=-100;i<=100;i+=20){let px=plot(i,0)[0];ctx.beginPath();ctx.moveTo(px,0);ctx.lineTo(px,330);ctx.stroke();}
for(let j=-50;j<=50;j+=10){let py=plot(0,j)[1];ctx.beginPath();ctx.moveTo(0,py);ctx.lineTo(720,py);ctx.stroke();}
ctx.strokeStyle='#678da7';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(0,165);ctx.lineTo(720,165);ctx.moveTo(360,0);ctx.lineTo(360,330);ctx.stroke();
ctx.fillStyle='#a7c4d8';ctx.font='13px Arial';ctx.fillText('X (m)',660,182);ctx.fillText('Y (m)',370,18);
let p=plot(x,y);ctx.strokeStyle='#5ee2c6';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(360,165);ctx.lineTo(p[0],p[1]);ctx.stroke();
ctx.fillStyle='#71d8f9';ctx.beginPath();ctx.arc(360,165,7,0,Math.PI*2);ctx.fill();ctx.fillStyle='#5ee2c6';ctx.beginPath();ctx.arc(p[0],p[1],7,0,Math.PI*2);ctx.fill();
ctx.fillStyle='#e6f6ff';ctx.font='bold 14px Arial';ctx.fillText('S (0,0)',369,185);
ctx.fillText('P ('+x+','+y+')',Math.min(p[0]+10,630),Math.max(p[1]-12,16));}
function coords(){const x=Number($('x').value),y=Number($('y').value);if(!Number.isFinite(x)||!Number.isFinite(y)||x < -100||x>100||y < -50||y>50){return null;}return {x,y};}
async function atualizarGeometria(){const p=coords();if(!p){$('vetor').textContent='Coordenadas fora do plano';return;}desenhar(p.x,p.y);
try{let r=await fetch('/api/geometria?x='+p.x+'&y='+p.y,{cache:'no-store'});if(!r.ok)throw Error('API');let d=await r.json();
$('vetor').textContent='('+fmt(d.vetor.dx,1)+', '+fmt(d.vetor.dy,1)+') m';$('distancia').textContent=fmt(d.distancia_m,2)+' m';$('angulo').textContent=fmt(d.angulo_graus,1)+' graus';
}catch(e){$('vetor').textContent='Sem conexao';$('distancia').textContent='--';$('angulo').textContent='--';}}
cv.addEventListener('click',e=>{let r=cv.getBoundingClientRect(),px=(e.clientX-r.left)*720/r.width,py=(e.clientY-r.top)*330/r.height;
$('x').value=Math.max(-100,Math.min(100,Math.round((px-360)/2.95)));$('y').value=Math.max(-50,Math.min(50,Math.round((165-py)/2.9)));atualizarGeometria();});
$('x').addEventListener('change',atualizarGeometria);$('y').addEventListener('change',atualizarGeometria);
async function atualizar(){try{let r=await fetch('/api?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('HTTP');let d=await r.json();
$('temp').textContent=fmt(d.dht_temp,1);$('umid').textContent=fmt(d.umidade,1);$('tempbmp').textContent=fmt(d.bmp_temp,2);
$('pressao').textContent=fmt(d.pressao,2);$('pressaonota').textContent=d.pressao_status;$('luz').textContent=d.ldr||'--';
$('mq').textContent=d.mq_raw===null?'--':d.mq_raw;$('fill').style.width=(d.mq_percent_adc||0)+'%';$('mqnota').textContent=d.mq_status;
$('status').textContent='Ao vivo | Atualizando a cada 3 segundos';$('rodape').textContent='ESP32 ligado ha '+d.tempo_s+' segundos | Fonte: GET /api';
}catch(e){$('status').textContent='Sem conexao com o ESP32';}}
desenhar(30,40);atualizar();atualizarGeometria();setInterval(atualizar,3000);
</script></body></html>'''

DOCS = '''<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Documentacao API | ESP32</title>
<style>body{background:#0b1825;color:#edf5ff;font:15px/1.6 Arial,sans-serif;margin:0}main{max-width:900px;margin:auto;padding:28px 18px}h1{font-size:32px}h2{margin-top:32px;color:#8be8d4}a{color:#80dac8}code,pre{background:#162b3b;border:1px solid #315269;border-radius:7px}code{padding:3px 6px}pre{padding:17px;overflow:auto;white-space:pre-wrap;word-break:break-word}table{width:100%;border-collapse:collapse}td,th{text-align:left;border-bottom:1px solid #315269;padding:9px}small{color:#bad1df}.pill{display:inline-block;background:#20564c;padding:6px 12px;border-radius:20px}</style>
</head><body><main><a href="/">Voltar ao dashboard</a><h1>Documentacao da API HTTP</h1>
<p class="pill">Versao 1.2 | MicroPython ESP32 | JSON</p>
<p>API embarcada no ESP32, disponivel apenas para clientes ligados a rede <b>Estacao-ESP32</b>.</p>
<h2>Rotas disponiveis</h2><table><tr><th>Metodo</th><th>Rota</th><th>Descricao</th></tr>
<tr><td>GET</td><td><a href="/">/</a></td><td>Dashboard para consulta local</td></tr>
<tr><td>GET</td><td><a href="/api">/api</a></td><td>Leituras atuais em JSON</td></tr>
<tr><td>GET</td><td><a href="/api/status">/api/status</a></td><td>Estado e identificacao da estacao</td></tr>
<tr><td>GET</td><td><a href="/api/geometria?x=30&y=40">/api/geometria?x=30&amp;y=40</a></td><td>Vetor, distancia e angulo em plano 2D</td></tr>
<tr><td>GET</td><td><a href="/docs">/docs</a></td><td>Esta documentacao</td></tr></table>
<h2>Exemplo atual: GET /api</h2><p>Resposta atual do ESP32. O campo mq_origem diferencia demonstracao de ADC real:</p>
<pre id="json">Buscando dados...</pre>
<h2>Geometria analitica</h2><p>A estacao e a origem S = (0, 0) e o ponto ilustrativo P = (x, y). O vetor e <b>(x-0, y-0)</b>, a distancia e <b>raiz(dx*dx + dy*dy)</b> e o angulo e <b>atan2(dy,dx)</b> em graus.</p>
<p>Exemplo de geometria para P = (30,40): <a href="/api/geometria?x=30&y=40">abrir JSON</a>.</p>
<h2>Limites e avisos</h2><p>O plano 2D e didatico, nao utiliza GPS. Em modo demonstracao, MQ-135 mostra 0 identificado como demonstracao, nao como leitura real. Em modo adc, precisa de ligacao eletricamente segura; nunca indica ppm. A pressao barometrica continua em diagnostico.</p>
<p><small>Captura sugerida para a entrega: fotografe esta pagina com a tabela de rotas e o JSON preenchido.</small></p>
<script>fetch('/api',{cache:'no-store'}).then(r=>r.json()).then(d=>document.getElementById('json').textContent=JSON.stringify(d,null,2)).catch(e=>document.getElementById('json').textContent='API temporariamente indisponivel');</script>
</main></body></html>'''


def iniciar_wifi():
    try:
        ap = network.WLAN(network.AP_IF)
    except AttributeError:
        ap = network.WLAN(network.WLAN.IF_AP)
    ap.active(True)
    try:
        ap.config(essid=WIFI_NOME, password=WIFI_SENHA, authmode=3)
    except (TypeError, ValueError, OSError):
        ap.config(ssid=WIFI_NOME, password=WIFI_SENHA)
    time.sleep_ms(600)
    ip = ap.ifconfig()[0]
    print('[WIFI] SSID:', WIFI_NOME)
    print('[WIFI] Senha:', WIFI_SENHA)
    return ap, ip


def responder(cliente, corpo, tipo='text/html; charset=utf-8', status='200 OK'):
    if isinstance(corpo, str):
        corpo = corpo.encode('utf-8')
    cab = ('HTTP/1.1 ' + status + '\r\n'
           'Content-Type: ' + tipo + '\r\n'
           'Content-Length: ' + str(len(corpo)) + '\r\n'
           'Cache-Control: no-store\r\n'
           'Connection: close\r\n\r\n')
    cliente.sendall(cab.encode('utf-8'))
    for inicio in range(0, len(corpo), 1024):
        cliente.sendall(corpo[inicio:inicio + 1024])


def parametro(consulta, chave, padrao):
    for p in consulta.split(b'&'):
        k, sep, v = p.partition(b'=')
        if sep and k == chave:
            return float(v.decode())
    return padrao


def log_leitura(d):
    print('----------------------------------------------')
    print('[LEITURA] %d segundos | API 1.2' % d['tempo_s'])
    print(' DHT22: ', d['dht_temp'], 'C |', d['umidade'], '%')
    print(' BMP280:', d['bmp_temp'], 'C | pressao:', d['pressao_status'])
    print(' LDR:   ', d['ldr'])
    print(' MQ-135:', d['mq_raw'], 'ADC |', d['mq_status'])


def executar():
    print('[BOOT] Estabilizando sensores...')
    time.sleep_ms(2100)
    log_leitura(leituras())
    ap, ip = iniciar_wifi()
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    servidor.bind(('0.0.0.0', 80))
    servidor.listen(3)
    servidor.settimeout(0.4)
    print('[HTTP] Dashboard : http://' + ip)
    print('[HTTP] API JSON  : http://' + ip + '/api')
    print('[HTTP] Docs API  : http://' + ip + '/docs')
    print('[HTTP] Plano 2D  : http://' + ip + '/#mapa')
    print('[HTTP] Geometria : http://' + ip + '/api/geometria?x=30&y=40')
    proximo_log = time.ticks_add(time.ticks_ms(), INTERVALO_LEITURA_MS)
    try:
        while True:
            agora = time.ticks_ms()
            if time.ticks_diff(agora, proximo_log) >= 0:
                log_leitura(leituras())
                proximo_log = time.ticks_add(agora, INTERVALO_LEITURA_MS)
            cliente = None
            try:
                cliente, endereco = servidor.accept()
                cliente.settimeout(3)
                pedido = cliente.recv(512)
                if not pedido:
                    continue
                primeira = pedido.split(b'\r\n', 1)[0]
                partes = primeira.split(b' ')
                if len(partes) < 2 or partes[0] != b'GET':
                    responder(cliente, 'Metodo nao permitido', 'text/plain', '405 Method Not Allowed')
                    continue
                rota, sep, consulta = partes[1].partition(b'?')
                if rota in (b'/', b'/index.html'):
                    responder(cliente, PAGINA)
                elif rota == b'/docs':
                    responder(cliente, DOCS)
                elif rota == b'/api':
                    responder(cliente, json.dumps(leituras()), 'application/json; charset=utf-8')
                elif rota == b'/api/status':
                    responder(cliente, json.dumps({'status': 'online', 'id': 'ESP32-01', 'versao_api': '1.2', 'ip': ip, 'tempo_s': time.ticks_ms() // 1000, 'mq_modo': MQ_MODO}), 'application/json; charset=utf-8')
                elif rota == b'/api/geometria':
                    try:
                        x = parametro(consulta, b'x', 30.0)
                        y = parametro(consulta, b'y', 40.0)
                        if not (-100 <= x <= 100 and -50 <= y <= 50):
                            raise ValueError('Valores aceitos: -100 <= x <= 100; -50 <= y <= 50')
                        responder(cliente, json.dumps(geometria(x, y)), 'application/json; charset=utf-8')
                    except (ValueError, OverflowError):
                        responder(cliente, json.dumps({'erro': 'Coordenadas invalidas ou fora do plano'}), 'application/json', '400 Bad Request')
                elif rota == b'/favicon.ico':
                    responder(cliente, b'', 'text/plain', '204 No Content')
                else:
                    responder(cliente, 'Rota nao encontrada', 'text/plain', '404 Not Found')
            except OSError:
                # Timeout do accept e normal: permite logs periodicos no Thonny.
                pass
            except Exception as erro:
                print('[HTTP] Erro:', erro)
            finally:
                if cliente is not None:
                    try:
                        cliente.close()
                    except Exception:
                        pass
                gc.collect()
    except KeyboardInterrupt:
        print('[FIM] Servidor encerrado pelo Thonny')
    finally:
        servidor.close()


executar()
