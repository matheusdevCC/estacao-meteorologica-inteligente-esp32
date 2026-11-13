# ESTACAO METEOROLOGICA INTELIGENTE - ESP32 / MicroPython
# Versao para demonstracao e gravacao com OBS Studio
# DHT22  -> GPIO4     | temperatura e umidade
# BMP280 -> SDA GPIO21 / SCL GPIO22, I2C endereco 0x76 ou 0x77
# LDR    -> DO GPIO27 | 0 = claro; 1 = escuro (ajuste observado)
# MQ-135 -> AO GPIO34 | valor ADC bruto, SEM calibracao de gases
#
# SEGURANCA DO MQ-135:
# Este codigo somente faz leitura da entrada GPIO34. Nao regula tensao.
# NUNCA conecte AO de um MQ-135 alimentado em 5 V diretamente ao GPIO34,
# pois a saida pode ultrapassar 3,3 V. Use adaptacao de nivel adequada.
# Se o MQ-135 estiver sem sinal eletricamente seguro, marque USAR_MQ135=False.
# A alimentacao experimental em 3,3 V nao atende a especificacao nominal
# do aquecedor e NAO permite conclusoes sobre concentracao de gases.
#
# Execute no Thonny pressionando F5. Para ligar automaticamente, salve
# no dispositivo MicroPython como main.py.

import gc
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

# ====== CONFIGURACOES ======
WIFI_NOME = 'Estacao-ESP32'
WIFI_SENHA = 'Estacao2026'
INTERVALO_LEITURA_MS = 3000
USAR_MQ135 = True  # True SOMENTE se AO nao puder exceder 3,3 V.

print('==============================================')
print(' ESTACAO METEOROLOGICA - ESP32 / MicroPython')
print('==============================================')
print('[BOOT] Iniciando sensores...')

# ====== BMP280 ======
class BMP280:
    def __init__(self, i2c):
        self.i2c = i2c
        dispositivos = i2c.scan()
        if 0x76 in dispositivos:
            self.endereco = 0x76
        elif 0x77 in dispositivos:
            self.endereco = 0x77
        else:
            raise OSError('BMP280 nao encontrado; enderecos: ' + str(dispositivos))

        chip = i2c.readfrom_mem(self.endereco, 0xD0, 1)[0]
        if chip != 0x58:
            raise OSError('Identificacao inesperada: ' + hex(chip))

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
            raise OSError('Conversao incompleta do BMP280')

        v1 = (adc_t / 16384.0 - self.t1 / 1024.0) * self.t2
        v2 = ((adc_t / 131072.0 - self.t1 / 8192.0) ** 2) * self.t3
        t_fine = v1 + v2
        temperatura = t_fine / 5120.0

        p1, p2, p3, p4, p5, p6, p7, p8, p9 = self.p
        v1 = t_fine / 2.0 - 64000.0
        v2 = v1 * v1 * p6 / 32768.0
        v2 = v2 + v1 * p5 * 2.0
        v2 = v2 / 4.0 + p4 * 65536.0
        v1 = (p3 * v1 * v1 / 524288.0 + p2 * v1) / 524288.0
        v1 = (1.0 + v1 / 32768.0) * p1
        if v1 == 0:
            raise OSError('Coeficientes de pressao invalidos')
        pressao_pa = (1048576.0 - adc_p - v2 / 4096.0) * 6250.0 / v1
        v1 = p9 * pressao_pa * pressao_pa / 2147483648.0
        v2 = pressao_pa * p8 / 32768.0
        pressao_pa = pressao_pa + (v1 + v2 + p7) / 16.0
        return round(temperatura, 2), round(pressao_pa / 100.0, 2)


def iniciar_sensor(nome, funcao):
    try:
        sensor = funcao()
        print('[OK]   ' + nome)
        return sensor
    except Exception as erro:
        print('[ERRO] ' + nome + ': ' + str(erro))
        return None


def criar_bmp280():
    bus = SoftI2C(sda=Pin(21), scl=Pin(22), freq=100000)
    sensor = BMP280(bus)
    print('       I2C: ' + hex(sensor.endereco))
    return sensor


def criar_adc():
    sensor = ADC(Pin(34))
    sensor.atten(ADC.ATTN_11DB)
    return sensor


dht22 = iniciar_sensor('DHT22  | DATA: GPIO4',
                     lambda: dht.DHT22(Pin(4, Pin.IN, Pin.PULL_UP)))
bmp280 = iniciar_sensor('BMP280 | SDA: 21 / SCL: 22', criar_bmp280)
ldr = iniciar_sensor('LDR    | DO: GPIO27', lambda: Pin(27, Pin.IN))
mq135 = iniciar_sensor('MQ-135 | AO: GPIO34 (ADC experimental)', criar_adc) if USAR_MQ135 else None

ultima_leitura_ms = None
cache = {}


def ler_sensores():
    global ultima_leitura_ms, cache
    agora = time.ticks_ms()
    if ultima_leitura_ms is not None and time.ticks_diff(agora, ultima_leitura_ms) < INTERVALO_LEITURA_MS:
        return cache

    # Evita colher DHT22 antes do tempo minimo recomendado (2 segundos).
    ultima_leitura_ms = agora
    dados = {
        'dht_temp': None, 'umidade': None, 'bmp_temp': None,
        'pressao': None, 'pressao_bruta': None,
        'pressao_status': 'Sem leitura', 'ldr': None,
        'mq_raw': None, 'mq_percent_adc': None,
        'mq_status': 'Leitura experimental, sem calibracao',
        'tempo_s': agora // 1000
    }

    if dht22 is not None:
        try:
            dht22.measure()
            dados['dht_temp'] = round(dht22.temperature(), 1)
            dados['umidade'] = round(dht22.humidity(), 1)
        except Exception as erro:
            print('[AVISO] Falha de leitura DHT22:', erro)

    if bmp280 is not None:
        try:
            temp, pressao = bmp280.ler()
            dados['bmp_temp'] = temp
            dados['pressao_bruta'] = pressao
            # Faixa de plausibilidade para o nosso teste, nao calibracao.
            if 800 <= pressao <= 1100:
                dados['pressao'] = pressao
                dados['pressao_status'] = 'Leitura de pressao disponivel'
            else:
                dados['pressao_status'] = 'Leitura suspeita: %.2f hPa; revisar BMP280' % pressao
        except Exception as erro:
            print('[AVISO] Falha de leitura BMP280:', erro)

    if ldr is not None:
        try:
            dados['ldr'] = 'CLARO' if ldr.value() == 0 else 'ESCURO'
        except Exception as erro:
            print('[AVISO] Falha de leitura LDR:', erro)

    if mq135 is not None:
        try:
            amostras = 5
            soma = 0
            for n in range(amostras):
                soma += mq135.read()
                time.sleep_ms(10)
            adc = soma // amostras
            dados['mq_raw'] = adc
            dados['mq_percent_adc'] = round(adc * 100.0 / 4095.0, 1)
        except Exception as erro:
            print('[AVISO] Falha de leitura MQ-135:', erro)
    elif not USAR_MQ135:
        dados['mq_status'] = 'Sinal desconectado por seguranca'

    cache = dados
    return dados


def mostrar_no_thonny(d):
    def valor(v, unidade=''):
        return '--' if v is None else str(v) + unidade

    print('----------------------------------------------')
    print('[LEITURA] ESP32 ligado ha %s segundos' % d['tempo_s'])
    print(' DHT22 - Temperatura :', valor(d['dht_temp'], ' C'))
    print(' DHT22 - Umidade     :', valor(d['umidade'], ' %'))
    print(' BMP280 - Temperatura:', valor(d['bmp_temp'], ' C'))
    print(' BMP280 - Pressao    :', valor(d['pressao'], ' hPa'))
    if d['pressao'] is None:
        print(' BMP280 - Diagnostico:', d['pressao_status'])
    print(' LDR - Luminosidade  :', valor(d['ldr']))
    print(' MQ-135 - ADC bruto  :', valor(d['mq_raw'], ' / 4095'))
    print(' NOTA: ADC do MQ-135 nao equivale a ppm ou indice de qualidade do ar.')


# ====== FRONTEND: HTML + CSS + JAVASCRIPT ======
PAGINA = '''<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Estacao Meteorologica ESP32</title>
<style>
:root{--bg:#091522;--card:#12283c;--edge:#2c475c;--text:#eaf3fa;--mute:#a8becf;--accent:#5bdec0}
*{box-sizing:border-box}body{font-family:Arial,sans-serif;margin:0;min-height:100vh;color:var(--text);background:linear-gradient(135deg,#142b41,var(--bg) 65%)}
main{max-width:1050px;margin:0 auto;padding:40px 20px 70px}header{margin-bottom:30px}small{color:var(--accent);font-size:12px;letter-spacing:1.4px;font-weight:bold}h1{font-size:clamp(28px,5vw,44px);margin:9px 0}p{color:var(--mute);margin:7px 0 0}.pill{display:inline-block;margin-top:15px;background:#16463d;color:#abffe9;border-radius:30px;padding:8px 15px;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px}.card{background:var(--card);border:1px solid var(--edge);border-radius:14px;padding:25px;min-width:0}.label{color:var(--mute);font-size:14px}.value{font-size:clamp(28px,5vw,43px);font-weight:700;margin-top:15px;overflow-wrap:anywhere}.unit{font-size:18px;color:var(--mute);font-weight:400}.note{font-size:12px;color:var(--mute);margin-top:12px;min-height:17px}.warn{color:#ffd18b}.track{height:9px;border-radius:10px;background:#294357;margin-top:20px;overflow:hidden}.fill{height:100%;width:0;background:var(--accent)}footer{color:var(--mute);font-size:12px;margin-top:24px;line-height:1.6}
@media(max-width:650px){.grid{grid-template-columns:1fr}main{padding:25px 14px}.card{padding:20px}}
</style></head><body><main>
<header><small>UNIP | PROJETO INTEGRADOR | IOT</small><h1>Estacao Meteorologica Inteligente</h1>
<p>Monitoramento ambiental com ESP32 e MicroPython</p><span class="pill" id="status">Conectando...</span></header>
<section class="grid">
<article class="card"><div class="label">Temperatura ambiente | DHT22</div><div class="value"><span id="t">--</span> <span class="unit">C</span></div><div class="note">Temperatura medida pelo DHT22</div></article>
<article class="card"><div class="label">Umidade relativa | DHT22</div><div class="value"><span id="u">--</span> <span class="unit">%</span></div><div class="note">Umidade do ar</div></article>
<article class="card"><div class="label">Temperatura auxiliar | BMP280</div><div class="value"><span id="bt">--</span> <span class="unit">C</span></div><div class="note">Sensor barometrico BMP280</div></article>
<article class="card"><div class="label">Pressao atmosferica | BMP280</div><div class="value"><span id="p">--</span> <span class="unit">hPa</span></div><div class="note warn" id="pn">Aguardando leitura</div></article>
<article class="card"><div class="label">Luminosidade | LDR</div><div class="value" id="l">--</div><div class="note">Indicador digital claro/escuro</div></article>
<article class="card"><div class="label">MQ-135 | Sinal analogico</div><div class="value"><span id="mq">--</span> <span class="unit">/ 4095</span></div><div class="track"><div class="fill" id="fill"></div></div><div class="note" id="mqnote">Leitura ADC experimental; nao indica ppm</div></article>
</section><footer id="rodape">Aguardando dados... Atualizacao automatica a cada 3 segundos.</footer>
</main><script>
function fmt(x,d){return x===null||x===undefined?'--':Number(x).toFixed(d).replace('.',',')}
async function atualizar(){try{const r=await fetch('/api?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('HTTP');const d=await r.json();
document.getElementById('t').textContent=fmt(d.dht_temp,1);document.getElementById('u').textContent=fmt(d.umidade,1);
document.getElementById('bt').textContent=fmt(d.bmp_temp,2);document.getElementById('p').textContent=fmt(d.pressao,2);
document.getElementById('pn').textContent=d.pressao_status;document.getElementById('l').textContent=d.ldr||'--';
document.getElementById('mq').textContent=d.mq_raw===null?'--':d.mq_raw;
document.getElementById('fill').style.width=d.mq_percent_adc===null?'0%':d.mq_percent_adc+'%';
document.getElementById('mqnote').textContent=d.mq_status+' - ADC nao representa ppm';
document.getElementById('status').textContent='Ao vivo | Wi-Fi ESP32';
document.getElementById('rodape').textContent='ESP32 ligado ha '+d.tempo_s+' segundos | Atualizacao a cada 3 segundos';
}catch(e){document.getElementById('status').textContent='Sem conexao';}}
atualizar();setInterval(atualizar,3000);
</script></body></html>'''


def iniciar_wifi():
    print('[WIFI] Ativando rede local do ESP32...')
    try:
        ap = network.WLAN(network.AP_IF)
    except AttributeError:
        ap = network.WLAN(network.WLAN.IF_AP)
    ap.active(True)
    try:
        ap.config(essid=WIFI_NOME, password=WIFI_SENHA, authmode=3)
    except (TypeError, ValueError, OSError):
        ap.config(ssid=WIFI_NOME, password=WIFI_SENHA)
    time.sleep_ms(750)
    if not ap.active():
        raise OSError('Nao foi possivel ativar o Access Point')
    endereco = ap.ifconfig()[0]
    print('[WIFI] Rede:', WIFI_NOME)
    print('[WIFI] Senha:', WIFI_SENHA)
    print('[WIFI] Endereco: http://' + endereco)
    print('[WIFI] Funciona sem internet: conecte-se diretamente a rede acima')
    return ap, endereco


def responder(cliente, corpo, tipo='text/html; charset=utf-8', status='200 OK'):
    if isinstance(corpo, str):
        corpo = corpo.encode('utf-8')
    cab = ('HTTP/1.1 ' + status + '\r\n'
           'Content-Type: ' + tipo + '\r\n'
           'Content-Length: ' + str(len(corpo)) + '\r\n'
           'Cache-Control: no-store\r\n'
           'Connection: close\r\n\r\n')
    cliente.sendall(cab.encode('utf-8'))
    for indice in range(0, len(corpo), 1024):
        cliente.sendall(corpo[indice:indice + 1024])


def executar():
    print('[BOOT] Aguardando estabilidade dos sensores...')
    time.sleep_ms(2100)
    amostra = ler_sensores()
    mostrar_no_thonny(amostra)
    ap, ip = iniciar_wifi()

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    servidor.bind(('0.0.0.0', 80))
    servidor.listen(3)
    servidor.settimeout(0.4)
    print('[HTTP] Servidor iniciado na porta 80')
    print('[HTTP] Painel: http://' + ip)
    print('[HTTP] API JSON: http://' + ip + '/api')
    print('[OBS]  Leituras aparecerao abaixo a cada 3 segundos')
    print('[OBS]  Pressione Ctrl+C para finalizar a demonstracao')

    proximo_log = time.ticks_ms()
    try:
        while True:
            agora = time.ticks_ms()
            if time.ticks_diff(agora, proximo_log) >= 0:
                amostra = ler_sensores()
                mostrar_no_thonny(amostra)
                proximo_log = time.ticks_add(agora, INTERVALO_LEITURA_MS)
            cliente = None
            try:
                cliente, endereco = servidor.accept()
                cliente.settimeout(4)
                requisicao = cliente.recv(512)
                if not requisicao:
                    continue
                linha = requisicao.split(b'\r\n', 1)[0]
                partes = linha.split(b' ')
                rota = partes[1].split(b'?', 1)[0] if len(partes) >= 2 else b'/'
                if rota == b'/api':
                    responder(cliente, json.dumps(ler_sensores()), 'application/json; charset=utf-8')
                elif rota in (b'/', b'/index.html'):
                    responder(cliente, PAGINA)
                elif rota == b'/favicon.ico':
                    responder(cliente, b'', 'text/plain', '204 No Content')
                else:
                    responder(cliente, 'Pagina nao encontrada', 'text/plain', '404 Not Found')
            except OSError:
                # Timeout do accept(): normal, permite atualizar a Shell.
                pass
            except Exception as erro:
                print('[HTTP] Erro ao atender requisicao:', erro)
            finally:
                if cliente is not None:
                    try:
                        cliente.close()
                    except Exception:
                        pass
                gc.collect()
    except KeyboardInterrupt:
        print('[FIM] Demonstracao encerrada')
    finally:
        servidor.close()


# Executa com F5 e tambem como main.py no dispositivo.
executar()
